"""The semantic API — the single place each metric is defined, and read-only by construction.

What this service will not do, stated as properties rather than intentions:

* **It never accepts raw SQL.** ``/v1/query`` takes a metric name and allow-listed dimensions and
  filters. There is no parameter that carries SQL and no code path that compiles a caller string
  into an identifier (:mod:`app.compiler`).
* **It never chooses its own tenant.** ``tenant_id`` comes from the verified JWT. No header, query
  string, cookie or body is consulted, and a ``tenant_id`` in the filter block is a scope violation,
  not an override.
* **It never queries Odoo's OLTP Postgres.** It holds one DSN, to the warehouse, as
  ``warehouse_rls`` (anti-pattern 7.3).
* **It performs no masking and can perform none.** The data is already masked upstream; there is no
  salt in this process and no unmasking function anywhere in the codebase.
"""

from __future__ import annotations

import logging
import os
import time

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field

from .auth import TokenRejected, Verifier
from .compiler import QueryRejected, compile_query
from .db import PoolGuardTripped, TenantScopeError, Warehouse
from .freshness import read_freshness
from .registry import load_registry

_logger = logging.getLogger("semantic_api")

QUERY_TOTAL = Counter(
    "bct_semantic_query_total", "Metric queries by outcome.", ["metric", "status"]
)
QUERY_DURATION = Histogram(
    "bct_semantic_query_duration_seconds",
    "Metric query latency.",
    ["metric"],
    # Bracketing the section 4 p95 budget of 2 s, so the panel can resolve either side of it
    # instead of dumping everything into one +Inf bucket.
    buckets=(0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0),
)
STALE_TOTAL = Counter(
    "bct_semantic_stale_response_total", "Responses served with is_stale=true.", ["metric"]
)
SCOPE_VIOLATIONS = Counter(
    "bct_semantic_tenant_scope_violation_total", "Cross-tenant requests refused with 403."
)
POOL_GUARD_TRIPS = Gauge(
    "bct_semantic_pool_guard_trips",
    "Times a pooled connection was checked out carrying a stale tenant scope (finding T-1). "
    "Should be 0 forever; a non-zero value means the SET LOCAL discipline was bypassed.",
)

#: Contract 02's scope-violation body, verbatim. Not built from a template: this exact JSON is what
#: the Frontend and the security tests assert on, and it deliberately does not reveal whether the
#: requested tenant exists.
TENANT_SCOPE_VIOLATION_BODY = {
    "error": "tenant_scope_violation",
    "detail": "Session is not scoped to the requested tenant.",
}


class QueryRequest(BaseModel):
    metric: str = Field(min_length=1, max_length=128)
    dimensions: list = Field(default_factory=list)
    filters: dict = Field(default_factory=dict)
    order_by: str = None
    limit: int = None


def create_app(warehouse=None, verifier=None, registry=None, max_limit=None) -> FastAPI:
    metrics_dir = os.environ.get(
        "SEMANTIC_API_METRICS_DIR", os.path.join(os.path.dirname(__file__), "..", "metrics")
    )
    registry = registry or load_registry(os.path.abspath(metrics_dir))

    if warehouse is None:
        dsn = os.environ["SEMANTIC_API_WAREHOUSE_DSN"]
        warehouse = Warehouse(dsn)
    if verifier is None:
        verifier = Verifier(
            os.environ.get("SEMANTIC_API_JWKS_URL", ""),
            os.environ.get("SEMANTIC_API_JWT_ISSUER", ""),
            os.environ.get("SEMANTIC_API_JWT_AUDIENCE", "insight-portal"),
        )
    if max_limit is None:
        max_limit = int(os.environ.get("SEMANTIC_API_MAX_LIMIT", "5000"))

    app = FastAPI(title="BCT semantic API", docs_url=None, redoc_url=None, openapi_url=None)
    router = APIRouter()

    def _audit(event, session, **fields):
        """Audit line. Carries subject, tenant and timestamp; never a value from a row."""
        _logger.info(
            "audit %s sub=%s tenant=%s %s",
            event,
            getattr(session, "subject", None),
            getattr(session, "tenant_id", None),
            " ".join("%s=%s" % (k, v) for k, v in sorted(fields.items())),
        )

    def _session_from(request: Request):
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise TokenRejected("Missing bearer token")
        return verifier.verify(header[7:].strip())

    @router.get("/healthz")
    def healthz():
        return {"status": "ok", "metrics": len(registry)}

    @router.get("/metrics")
    def prometheus_metrics():
        POOL_GUARD_TRIPS.set(warehouse.guard_trips)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @router.get("/v1/metrics")
    def list_metrics(request: Request):
        """The metric catalogue. Requires a token: the catalogue is not public."""
        try:
            _session_from(request)
        except TokenRejected:
            return JSONResponse({"error": "unauthorized", "detail": "Invalid token."}, 401)
        return {
            "metrics": [
                {
                    "name": m.name, "label": m.label, "description": m.description,
                    "grain": m.grain, "dimensions": m.dimensions,
                    "filters": m.filters, "type": m.type, "unit": m.unit,
                    "aggregation": m.aggregation,
                    "refresh_sla_seconds": m.refresh_sla_seconds,
                    "pdp_class": m.pdp_class,
                }
                for m in registry.all()
            ]
        }

    @router.post("/v1/query")
    def query(payload: QueryRequest, request: Request):
        started = time.time()
        try:
            session = _session_from(request)
        except TokenRejected as exc:
            _logger.info("token rejected: %s", exc)
            QUERY_TOTAL.labels(metric=payload.metric or "?", status="401").inc()
            return JSONResponse({"error": "unauthorized", "detail": "Invalid token."}, 401)

        # A tenant in the request body is a scope violation, never an override. Checked before the
        # metric is looked up so that probing for tenants cannot also probe for metric names.
        requested_tenant = payload.filters.get("tenant_id") if payload.filters else None
        if requested_tenant is not None and requested_tenant != session.tenant_id:
            SCOPE_VIOLATIONS.inc()
            QUERY_TOTAL.labels(metric=payload.metric, status="403").inc()
            _audit("tenant_scope_violation", session, requested=requested_tenant)
            return JSONResponse(TENANT_SCOPE_VIOLATION_BODY, 403)

        metric = registry.get(payload.metric)
        if metric is None:
            QUERY_TOTAL.labels(metric=payload.metric, status="400").inc()
            return JSONResponse(
                {
                    "error": "unknown_metric",
                    "detail": "Metric %r is not defined." % payload.metric,
                    "field": "metric",
                    "available": registry.names(),
                },
                400,
            )

        filters = dict(payload.filters or {})
        filters.pop("tenant_id", None)  # already proven equal to the session tenant

        try:
            statement, params = compile_query(
                metric, payload.dimensions, filters, payload.order_by, payload.limit,
                session.tenant_id, session.allowed_ou, session.all_ou, max_limit=max_limit,
            )
        except QueryRejected as exc:
            QUERY_TOTAL.labels(metric=metric.name, status="400").inc()
            return JSONResponse(
                {"error": "invalid_query", "detail": exc.detail, "field": exc.field}, 400
            )

        try:
            rows = warehouse.fetch_all(session.tenant_id, statement, params)
        except PoolGuardTripped:
            QUERY_TOTAL.labels(metric=metric.name, status="503").inc()
            return JSONResponse(
                {"error": "scope_guard", "detail": "Request refused for safety; retry."}, 503
            )
        except TenantScopeError:
            SCOPE_VIOLATIONS.inc()
            QUERY_TOTAL.labels(metric=metric.name, status="403").inc()
            return JSONResponse(TENANT_SCOPE_VIOLATION_BODY, 403)
        except Exception as exc:
            _logger.exception("query failed for metric %s", metric.name)
            QUERY_TOTAL.labels(metric=metric.name, status="500").inc()
            return JSONResponse(
                {"error": "query_failed", "detail": exc.__class__.__name__}, 500
            )

        freshness = read_freshness(warehouse, session.tenant_id, metric.source_model)
        if freshness.get("is_stale"):
            STALE_TOTAL.labels(metric=metric.name).inc()

        elapsed = time.time() - started
        QUERY_DURATION.labels(metric=metric.name).observe(elapsed)
        QUERY_TOTAL.labels(metric=metric.name, status="200").inc()
        _audit("query", session, metric=metric.name, rows=len(rows))

        return {
            "metric": metric.name,
            "dimensions": list(payload.dimensions or []),
            "rows": rows,
            "meta": {
                "tenant_id": session.tenant_id,
                "row_count": len(rows),
                "last_refreshed_at": freshness["last_refreshed_at"],
                "is_stale": freshness["is_stale"],
                "refresh_sla_seconds": metric.refresh_sla_seconds,
                "source_model": metric.source_model,
                "unit": metric.unit,
                "type": metric.type,
                "query_duration_ms": round(elapsed * 1000, 1),
            },
        }

    app.include_router(router)
    app.state.registry = registry
    app.state.warehouse = warehouse
    return app
