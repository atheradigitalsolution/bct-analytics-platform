"""Process-level logging configuration for the semantic API.

WHY THIS FILE EXISTS. ``main.py`` calls ``_audit()`` at four places, and three of them are the
refusals that matter most: a token asking for a tenant it does not own
(``tenant_scope_violation``), a lapsed subscription (``subscription_inactive``) and a plan that
does not include this product (``product_not_entitled``). None of those lines was ever emitted.
Nothing configured logging in this service, and ``uvicorn`` configures only its own three loggers;
the root logger is left without a handler, so Python falls back to ``logging.lastResort`` at
WARNING and every ``logger.info`` goes nowhere.

A cross-tenant access attempt that is refused correctly but recorded nowhere is a control with no
evidence. This file is the evidence half.

WHERE IT IS CALLED FROM. ``asgi.py``, at import time, not from ``create_app()`` — the same
reasoning as the gateway: one process, one configuration, and a test suite that builds many apps
must not fight over the root logger.

ON CONTENT. ``_audit()`` carries the JWT subject, the tenant slug from the verified token, the
metric name and a row COUNT. It never carries a row value, a warehouse credential or the token
itself. That boundary is the reason the audit line is useful at all: it can be shipped to Loki,
which is not inside the PDP masking boundary.
"""

from __future__ import annotations

import logging.config
import os
import sys

DEFAULT_LEVEL = "INFO"

_NOISY = ("urllib3", "asyncio")


def configure_logging(level: str | None = None) -> str:
    """Install the process logging configuration. Returns the level actually applied."""
    resolved = (level or os.environ.get("SEMANTIC_API_LOG_LEVEL") or DEFAULT_LEVEL).upper()
    if resolved not in ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"):
        resolved = DEFAULT_LEVEL

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "semantic": {
                "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                "datefmt": "%Y-%m-%dT%H:%M:%S%z",
            },
        },
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
                "formatter": "semantic",
            },
        },
        # Root, so `app.db`, `app.auth`, `app.registry` and `app.freshness` are covered without
        # being listed one by one.
        "root": {"handlers": ["stdout"], "level": resolved},
        "loggers": {name: {"level": "WARNING"} for name in _NOISY},
    })
    logging.getLogger("semantic_api").info(
        "audit logging.configured level=%s", resolved,
    )
    return resolved
