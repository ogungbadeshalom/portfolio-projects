"""Flask application factory for the invoice generator.

Creates the app, wires the SQLAlchemy engine/session into
``app.extensions["sqlalchemy"]`` (which the webhook route reads), registers
the webhook blueprint and the invoice-download routes, and creates the schema.

The app is fully runnable offline:

    python -m invoice.app            # or: flask --app invoice.app run

Use ``INVOICE_EMAIL_MODE=sync`` + ``EMAIL_DRY_RUN=1`` to skip networking in a
demo/test run.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Optional

from flask import Flask

from . import config, models
from .routes.invoices import invoices_bp
from .webhook import webhook_bp

logger = logging.getLogger(__name__)


def create_app(overrides: Optional[Dict[str, object]] = None) -> Flask:
    """Build and configure the Flask application.

    Args:
        overrides: Optional dict of ``app.config`` keys (used by tests to point
            at a temp DB / disable email).

    Returns:
        A ready-to-serve :class:`flask.Flask` instance.
    """
    config.configured_logging()
    config.ensure_dirs()

    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent / "templates"),
        static_folder=str(Path(__file__).resolve().parent / "static"),
    )
    app.config.update(
        INVOICE_EMAIL_MODE=os.environ.get("INVOICE_EMAIL_MODE", "async"),
        INVOICE_DATABASE_URL=config.DATABASE_URI,
        INVOICE_OUTPUT_DIR=str(config.INVOICES_DIR),
        STRIPE_WEBHOOK_SECRET=config.STRIPE_WEBHOOK_SECRET,
    )
    if overrides:
        app.config.update(overrides)

    # Resolve the database URI (override first, else env/config).
    db_uri = app.config.get("INVOICE_DATABASE_URL") or config.DATABASE_URI
    engine, SessionLocal = models.init_engine(db_uri)
    models.create_schema(engine)

    # The webhook route reads ``current_app.extensions["sqlalchemy"]["session"]``.
    session = SessionLocal()
    app.extensions["sqlalchemy"] = {
        "engine": engine,
        "session": session,
        "SessionLocal": SessionLocal,
    }

    app.register_blueprint(webhook_bp)
    app.register_blueprint(invoices_bp)

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover - direct run
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=False)