"""Warehouse access, and the answer to security finding T-1.

T-1: a connection pool silently defeats Row-Level Security
----------------------------------------------------------

Postgres RLS reads a **session** variable. A pool that hands a connection still carrying
``app.tenant_id = 'tenant_a'`` to a request for tenant B serves A's rows to B, and the database sees
nothing wrong: the query is well-formed, the policy evaluates, the rows match. There is no error to
find in a log. Contract 05 names three acceptable answers; this module implements the first and adds
the third as a backstop.

**Chosen: ``SET LOCAL`` inside an explicit transaction.** Every query runs as::

    BEGIN;
    SELECT set_config('app.tenant_id', %s, true);   -- true => LOCAL
    SELECT ...;
    COMMIT;

``SET LOCAL`` is scoped to the transaction. At ``COMMIT`` or ``ROLLBACK`` -- including a rollback
caused by an exception, a statement timeout, or the client dying -- Postgres restores the previous
value. **The setting cannot outlive the transaction that set it.** There is therefore no window in
which a pooled connection carries a stale tenant, and that property comes from the database rather
than from this code remembering to clean up. That is what makes it the strongest of the three.

Why not the alternatives:

* *A pool keyed per tenant* multiplies idle connections by the tenant count and still leaves the
  variable set between checkouts. It narrows the blast radius without closing the hole.
* *Reset on checkout and checkin* is a correct pattern but depends on the reset actually running. A
  crash between checkin and reset, or one code path that returns a connection by another route,
  re-opens it. It is used here **as well**, as a guard, but not as the primary control.

**Backstop: a checkout guard that fails closed.** :meth:`Warehouse.session` asserts on checkout that
``app.tenant_id`` is unset. If a connection ever arrives carrying a value -- meaning something
bypassed the transaction discipline above -- the connection is **discarded rather than reused** and
the request fails. Failing closed is the point: a guard that logged and carried on would turn a
containment failure into a data leak with a warning nobody read.

**Why the bound parameter matters.** ``SET LOCAL app.tenant_id = 'value'`` cannot take a
placeholder, because ``SET`` does not accept bind parameters, so the naive implementation
interpolates the tenant into SQL text. ``set_config()`` is an ordinary function call and does take
one, so the tenant travels as data. Contract 02 requires the tenant to be bound as a parameter *and*
set as the session variable; this satisfies both in one call.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
import time

import psycopg2
import psycopg2.extras
from psycopg2 import pool as pg_pool

_logger = logging.getLogger(__name__)

#: The RLS session variable of contract 05. Both agents use exactly this name.
TENANT_SETTING = "app.tenant_id"


class TenantScopeError(RuntimeError):
    """A query was attempted with no tenant scope."""


class PoolGuardTripped(RuntimeError):
    """A pooled connection carried a tenant scope on checkout. Fail closed, never reuse."""


class PoolExhausted(RuntimeError):
    """Every connection is busy and one did not free up within the acquire timeout.

    This is **saturation, not breakage**, and the distinction is the whole point of this class
    existing. Before it, psycopg2's ``PoolError`` fell through to a generic handler and the caller
    got a bare ``500 query_failed``. A 500 tells a caller "this server is broken, stop"; the truth
    was "every connection is busy for the next few milliseconds, come back". Callers behave
    completely differently under those two contracts, and Frontend had to spend time deciding
    whether the bug was its own before it could report this.

    Reproduced before it was fixed, with Frontend's recipe (a ten-panel PPOB view, cache disabled,
    10 concurrent queries, 300 requests): **52 x 500 PoolError**, while
    ``bct_semantic_pool_guard_trips`` stayed at 0 -- proving it was never the T-1 scope guard.
    """

    #: Seconds to advertise in ``Retry-After``. Deliberately small: the queries that saturate this
    #: pool take milliseconds, so the honest advice is "almost immediately", not a punitive backoff.
    retry_after = 1


def _acquire_slot(warehouse):
    """Wait for a free connection slot. Return the seconds waited, or raise :class:`PoolExhausted`.

    Returns 0.0 when a slot was free immediately, which is the overwhelmingly common case and the
    one that must stay free of overhead: ``acquire(blocking=False)`` first, and only then the
    timed wait.
    """
    if warehouse._slots.acquire(blocking=False):
        return 0.0
    started = time.time()
    if warehouse._slots.acquire(timeout=warehouse.acquire_timeout_s):
        waited = time.time() - started
        with warehouse._lock:
            warehouse.waits += 1
        return waited
    with warehouse._lock:
        warehouse.shed += 1
    _logger.warning(
        "pool saturated: all %d connections busy for %.0f ms; shedding this request with 503 "
        "rather than reporting it as a server fault. This is backpressure, not breakage -- if it "
        "is sustained rather than bursty, SEMANTIC_API_POOL_MAX is the knob, and it is sized "
        "against the warehouse's max_connections budget (see Warehouse.__init__).",
        warehouse.maxconn, warehouse.acquire_timeout_s * 1000.0,
    )
    raise PoolExhausted(
        "All %d warehouse connections are busy and none freed within %.0f ms."
        % (warehouse.maxconn, warehouse.acquire_timeout_s * 1000.0)
    )


def m_wait_observe(warehouse, waited):
    """Record a non-zero queue wait. Split out so the fast path calls nothing at all."""
    _logger.debug("waited %.1f ms for a warehouse connection", waited * 1000.0)


class Warehouse:
    """A read-only, tenant-scoped connection pool over the warehouse."""

    def __init__(self, dsn, minconn=1, maxconn=None, statement_timeout_ms=15000,
                 acquire_timeout_s=None):
        """Size the pool against the DATABASE's budget, not against the current panel count.

        ``maxconn`` defaults to 16, and that number is derived rather than picked. Measured on the
        warehouse:

            max_connections               40
            superuser_reserved_connections 3   ->  37 usable

        Allocated: dbt build ~8 (its thread count), postgres_exporter ~3, the CDC loader 3
        (warehouse_loader held 3 when measured), operator/QA psql and ad-hoc ~4, and ~3 of margin.
        37 - 8 - 3 - 3 - 4 - 3 = **16 for this service.** If any of those consumers changes, this
        number is the thing to revisit, which is why the arithmetic is written down instead of the
        answer alone.

        Raising the ceiling is NOT the fix here and must not be mistaken for one -- it moves the
        cliff from ten panels to seventeen. The fix is that hitting the ceiling now degrades
        correctly at ANY concurrency, via queue-then-shed below.
        """
        if maxconn is None:
            maxconn = int(os.environ.get("SEMANTIC_API_POOL_MAX", "16"))
        if acquire_timeout_s is None:
            acquire_timeout_s = (
                float(os.environ.get("SEMANTIC_API_POOL_ACQUIRE_TIMEOUT_MS", "2000")) / 1000.0
            )
        self.maxconn = maxconn
        self.acquire_timeout_s = acquire_timeout_s
        self._pool = pg_pool.ThreadedConnectionPool(minconn, maxconn, dsn)
        self._statement_timeout_ms = statement_timeout_ms
        self._lock = threading.Lock()
        self.guard_trips = 0
        #: QUEUE, then SHED -- in that order, because neither alone is right.
        #:
        #: Queue-only is how a saturated service becomes a hung one: latency grows without bound,
        #: callers time out anyway, and their retries make it worse. Shed-only turns a burst that
        #: would have cleared in 15 ms into user-visible failures -- ten panels against eight
        #: connections is a burst, not overload, and the queries take milliseconds.
        #:
        #: So: block up to ``acquire_timeout_s`` (absorbs the burst; the caller sees 200), and past
        #: that return a documented 503 with Retry-After (bounds the damage; the caller sees the
        #: truth). psycopg2's ThreadedConnectionPool.getconn does NOT block -- it raises PoolError
        #: the instant used == maxconn -- so the waiting is implemented here. Holding the semaphore
        #: makes getconn structurally incapable of exhausting, which is better than catching the
        #: error it would have raised.
        self._slots = threading.BoundedSemaphore(maxconn)
        self.waits = 0
        self.shed = 0

    def close(self):
        self._pool.closeall()

    @contextlib.contextmanager
    def session(self, tenant_id):
        """Yield a cursor inside a transaction scoped to ``tenant_id``.

        The tenant comes from the verified JWT and nowhere else. This method has no way to read a
        header, query string, cookie or body, which is deliberate rather than incidental.
        """
        if not tenant_id or not isinstance(tenant_id, str):
            # Fail closed. With app.tenant_id unset, contract 05's policy matches no rows, so an
            # empty tenant would return an empty result rather than an error -- and an empty result
            # is indistinguishable from "this tenant genuinely has no data". Refuse instead.
            raise TenantScopeError("No tenant scope on the request; refusing to query.")

        waited = _acquire_slot(self)

        try:
            conn = self._pool.getconn()
        except Exception:
            self._slots.release()
            raise
        try:
            self._assert_unscoped_on_checkout(conn)
        except Exception:
            # The guard already returned the connection with close=True; only the slot is ours.
            self._slots.release()
            raise

        discard = False
        try:
            conn.autocommit = False  # SET LOCAL needs an explicit transaction to be scoped to
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT set_config(%s, %s, true)", (TENANT_SETTING, tenant_id))
                cur.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self._statement_timeout_ms),),
                )
                yield cur
            conn.commit()  # ends the transaction -> Postgres undoes SET LOCAL
        except Exception:
            try:
                conn.rollback()  # also undoes SET LOCAL
            except Exception:  # pragma: no cover - connection already broken
                discard = True
            raise
        finally:
            try:
                self._pool.putconn(conn, close=discard)
            finally:
                # Released last and unconditionally. A slot leaked here is permanent: the pool
                # would shed for ever while the database sat idle, which is a worse failure than
                # the one this whole change is about.
                self._slots.release()
                if waited:
                    m_wait_observe(self, waited)

    def _assert_unscoped_on_checkout(self, conn):
        """Guard: a connection must arrive with no tenant scope.

        This should always pass, because ``SET LOCAL`` cannot survive its transaction. It exists so
        that if the invariant is ever broken -- a refactor using ``SET`` instead of ``SET LOCAL``, a
        code path opening its own cursor -- the result is a refused request rather than one tenant
        reading another's rows.
        """
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT current_setting(%s, true)", (TENANT_SETTING,))
                current = cur.fetchone()[0]
            conn.rollback()
        except psycopg2.Error:
            self._pool.putconn(conn, close=True)
            raise
        if current not in (None, ""):
            with self._lock:
                self.guard_trips += 1
            _logger.error(
                "pool guard tripped: a connection was checked out carrying %s=%r. Discarding it "
                "and failing the request rather than serving one tenant's rows to another.",
                TENANT_SETTING, current,
            )
            self._pool.putconn(conn, close=True)
            raise PoolGuardTripped(
                "A pooled connection carried a stale tenant scope. The request was refused."
            )

    def fetch_all(self, tenant_id, statement, params=None):
        with self.session(tenant_id) as cur:
            cur.execute(statement, params or ())
            return [dict(r) for r in cur.fetchall()]

    def current_scope(self, tenant_id):
        """What the database believes the scope is, read from inside the transaction."""
        with self.session(tenant_id) as cur:
            cur.execute("SELECT current_setting(%s, true) AS scope", (TENANT_SETTING,))
            return cur.fetchone()["scope"]
