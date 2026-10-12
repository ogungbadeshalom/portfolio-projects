"""Shared fixtures for the githook test-suite.

The key idea: every test that exercises the webhook path injects an
``httpx.MockTransport`` into the app so the outbound Slack request is captured
in-memory and **never** touches the real Slack API. A recording handler stores
the outbound request for assertions and returns a canned 200.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest

from githook.config import Config
from githook.events import event_store

FIXTURES = Path(__file__).parent / "fixtures" / "github_payloads"
SECRET = "test-webhook-secret"


@pytest.fixture()
def fixture_payloads() -> Dict[str, bytes]:
    """Load every GitHub payload fixture as raw bytes keyed by event type."""
    out: Dict[str, bytes] = {}
    for name in ("push", "pull_request", "release", "star"):
        out[name] = (FIXTURES / f"{name}.json").read_bytes()
    return out


class Recorder:
    """Captures outbound Slack POST requests sent through httpx."""

    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.requests: List[httpx.Request] = []
        self.calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.calls += 1
        content = {
            "ok": True,
            "channel": "C0000000000",
            "ts": "1234.5678",
        }
        return httpx.Response(self.status_code, json=content)


@pytest.fixture()
def recorder() -> Recorder:
    return Recorder()


def sign(secret: str, payload: bytes) -> str:
    """Compute an ``X-Hub-Signature-256`` header value for ``payload``."""
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def make_headers(event_type: str, delivery_id: str = "00000000-0000-0000-0000-000000000001") -> Dict[str, str]:
    """Build the GitHub delivery headers (signature added by the caller)."""
    return {
        "X-GitHub-Event": event_type,
        "X-GitHub-Delivery": delivery_id,
        "Content-Type": "application/json",
    }


@pytest.fixture()
def test_config(tmp_path, monkeypatch) -> Config:
    """A Config isolated to a temp sqlite file and a throwaway webhook URL."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 't.db'}")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    return Config()


@pytest.fixture()
def store(test_config) -> Any:
    return event_store(test_config.database_url)