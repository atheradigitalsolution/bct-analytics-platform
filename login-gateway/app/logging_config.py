"""Process-level logging configuration for the gateway.

WHY THIS FILE EXISTS. ``main.py`` has called ``_audit()`` at fourteen places since the gateway
was written — every failed login, every rate-limit lockout, every rejected CSRF token, every SSO
refusal. Not one of those lines was ever emitted. Nothing in this service configured logging, and
``uvicorn`` configures only its own three loggers (``uvicorn``, ``uvicorn.error``,
``uvicorn.access``); it leaves the root logger without a handler. Python then falls back to
``logging.lastResort``, which is a ``StreamHandler`` fixed at WARNING. Every ``logger.info`` in
this process — the entire audit trail — was written to nothing.

That is worse than having no audit trail at all, because the code reads as though there is one.

WHERE IT IS CALLED FROM. ``asgi.py``, at import time, not from ``create_app()``. Logging is a
property of the process, not of the application object: tests build an app per test case and must
not fight over the root logger, while the container has exactly one process and wants exactly one
configuration. uvicorn applies its own ``dictConfig`` inside ``Config.__init__``, which runs
before it imports the ASGI app, so this configuration is applied second and wins.

WHAT IT DELIBERATELY DOES NOT DO. It does not add a JSON formatter, a file handler or a rotation
policy. The container writes to stdout, Docker's ``json-file`` driver frames it and promtail ships
it to Loki; adding a second framing layer here would mean parsing JSON out of JSON downstream.

ON CONTENT. ``_audit()`` carries an event name, a database name, a uid, a reason and a client IP.
It never carries a password, an access token, a refresh token, a signing key or a row value —
that is asserted by ``tests/test_audit_logging.py``, not merely intended. The client IP is a
personal datum under UU 27/2022 and is present on purpose: an authentication log without a source
address cannot answer the one question it is kept to answer.
"""

from __future__ import annotations

import logging.config
import os
import sys

#: Anything at or above this level reaches stdout. INFO by default because the audit trail is
#: emitted at INFO; setting this to WARNING silences the audit trail, which is why the name says
#: LOG_LEVEL and not DEBUG.
DEFAULT_LEVEL = "INFO"

#: Third-party loggers that are chatty at INFO and carry nothing this service is accountable for.
_NOISY = ("urllib3", "asyncio")


def configure_logging(level: str | None = None) -> str:
    """Install the process logging configuration. Returns the level actually applied."""
    resolved = (level or os.environ.get("LOGIN_GATEWAY_LOG_LEVEL") or DEFAULT_LEVEL).upper()
    if resolved not in ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"):
        resolved = DEFAULT_LEVEL

    logging.config.dictConfig({
        "version": 1,
        # uvicorn's own loggers are already configured by the time this runs. Disabling existing
        # loggers would mute uvicorn's startup errors, which is the opposite of the goal.
        "disable_existing_loggers": False,
        "formatters": {
            "gateway": {
                "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                "datefmt": "%Y-%m-%dT%H:%M:%S%z",
            },
        },
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
                "formatter": "gateway",
            },
        },
        # The ROOT logger, so a module that calls `logging.getLogger(__name__)` is covered without
        # having to be listed here. `app.keys` and `app.odoo` do exactly that.
        "root": {"handlers": ["stdout"], "level": resolved},
        "loggers": {name: {"level": "WARNING"} for name in _NOISY},
    })
    logging.getLogger("login_gateway").info(
        "audit logging.configured level=%s", resolved,
    )
    return resolved
