"""ASGI entry point. Kept separate from app.main so the factory can be exercised in tests with
an explicit Settings object rather than through the environment.

Logging is configured HERE and not in ``create_app()``: it is a property of the process, and this
module is imported exactly once per process. See app/logging_config.py for why the service had no
logging configuration at all until 2026-09-04, and what that cost.
"""

from app.logging_config import configure_logging

configure_logging()

from app.main import create_app  # noqa: E402 - logging must be installed before the app logs

app = create_app()
