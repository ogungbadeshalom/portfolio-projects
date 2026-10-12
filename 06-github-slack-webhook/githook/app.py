"""Flask application factory.

Exposes three routes:

* ``POST /webhook/github`` -- GitHub webhook receipt (registered in
  :mod:`githook.webhook`).
* ``GET  /events``        -- a small HTML page listing recent events.
* ``GET  /health``        -- liveness for monitoring.

``create_app`` is a factory so tests (and ``flask run``) can build bespoke
apps with an isolated event store and a mock Slack transport.
"""

from __future__ import annotations

import logging
from typing import Optional

from flask import Flask, jsonify, render_template

from githook import retry, webhook
from githook.config import Config, configure_logging
from githook.events import EventStore, event_store

logger = logging.getLogger(__name__)


def create_app(
    config: Optional[Config] = None,
    *,
    store: Optional[EventStore] = None,
    slack_transport=None,
    sync_slack_delivery: bool = True,
) -> Flask:
    """Build a configured Flask application.

    Parameters
    ----------
    config:
        Override the default :class:`~githook.config.Config` (e.g. a test one
        pointing at an in-memory SQLite DB or a throwaway webhook URL).
    store:
        Pre-built event store. When omitted one is created from ``config``.
    slack_transport:
        ``httpx`` transport used for the outbound Slack call. Tests inject an
        ``httpx.MockTransport`` here; production leaves it ``None`` (real pool).
    sync_slack_delivery:
        When ``True`` (default, useful for tests) Slack sends complete before
        the webhook responds. Set ``False`` for a demo of the background path.
    """
    if config is None:
        config = Config()
    configure_logging(config.log_level)

    app = Flask(
        __name__,
        template_folder=str(config.base_dir / "templates"),
        static_folder=str(config.base_dir / "static"),
    )
    app.config["GITHUB_WEBHOOK_SECRET"] = config.github_webhook_secret
    app.config["SLACK_WEBHOOK_URL"] = config.slack_webhook_url
    app.config["MAX_SLACK_RETRIES"] = config.max_retries
    app.config["SLACK_BACKOFF_BASE"] = config.backoff_base_seconds
    app.config["EVENTS_LIMIT"] = config.recent_events_limit
    # Injected hooks for the delivery path.
    app.config["SLACK_TRANSPORT"] = slack_transport
    app.config["SYNC_SLACK_DELIVERY"] = sync_slack_delivery
    app.config["SLACK_RETRY_QUEUE"] = retry.RetryQueue()

    app.config["EVENT_STORE"] = store if store is not None else event_store(config.database_url)

    app.register_blueprint(webhook.webhook_bp)

    @app.get("/health")
    def health() -> tuple:
        return jsonify({"status": "ok", "service": "github-slack-webhook"}), 200

    @app.get("/")
    def index():
        return jsonify(
            {
                "service": "github-slack-webhook",
                "endpoints": ["/webhook/github", "/events", "/health"],
            }
        )

    @app.get("/events")
    def events() -> str:
        store: EventStore = app.config["EVENT_STORE"]
        limit = int(app.config.get("EVENTS_LIMIT", 100))
        records = store.recent(limit)
        rows = [
            {
                "id": r.id,
                "event": r.event_type,
                "delivery_id": r.delivery_id,
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in records
        ]
        return render_template("events.html", events=rows)

    _register_errorhandlers(app)
    _register_middleware(app)

    return app


def _register_middleware(app: Flask) -> None:
    """Attach a request-id and JSON access log to every request."""

    @app.after_request
    def _add_request_id(response):
        from flask import request

        request_id = request.headers.get("X-Request-Id", "")
        if request_id:
            response.headers["X-Request-Id"] = request_id
        logger.info("%s %s -> %s (request_id=%s)", request.method, request.path, response.status_code, request_id)
        return response


def _register_errorhandlers(app: Flask) -> None:
    """Return structured JSON for HTTP errors so clients can parse them."""

    @app.errorhandler(404)
    def _not_found(_exc):  # pragma: no cover - trivial
        return jsonify({"error": "Not found", "status": 404}), 404

    @app.errorhandler(405)
    def _method_not_allowed(_exc):  # pragma: no cover - trivial
        return jsonify({"error": "Method not allowed", "status": 405}), 405