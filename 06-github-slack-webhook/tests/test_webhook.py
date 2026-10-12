"""Tests for HMAC verification and the /webhook/github endpoint.

Covers: valid-signature acceptance, invalid/replayed/unsupported cases,
idempotency (dedupe by X-GitHub-Delivery), and full "receive -> verify ->
store -> format -> send" integration against a mock Slack transport.
"""

from __future__ import annotations

import httpx
import pytest

from githook.app import create_app
from githook.webhook import compute_signature, verify_signature
from tests.conftest import SECRET, make_headers, sign


# --------------------------------------------------------------------------- #
# Pure HMAC unit tests
# --------------------------------------------------------------------------- #
class TestSignature:
    def test_compute_and_verify_roundtrip(self):
        payload = b'{"hello": "world"}'
        sig = compute_signature(SECRET, payload)
        assert sig.startswith("sha256=")
        assert verify_signature(SECRET, payload, sig) is True

    def test_rejects_wrong_secret(self):
        payload = b"some payload"
        sig = compute_signature("correct-secret", payload)
        assert verify_signature("wrong-secret", payload, sig) is False

    def test_rejects_tampered_payload(self):
        sig = compute_signature(SECRET, b'{"a": 1}')
        assert verify_signature(SECRET, b'{"a": 2}', sig) is False

    def test_rejects_missing_or_malformed(self):
        payload = b"whatever"
        assert verify_signature(SECRET, payload, None) is False
        assert verify_signature(SECRET, payload, "") is False
        assert verify_signature(SECRET, payload, "sha256=zzz") is False
        assert verify_signature(SECRET, payload, "  ") is False

    def test_accepts_bare_hex_without_prefix(self):
        import hashlib, hmac

        digest = hmac.new(SECRET.encode(), b"x", hashlib.sha256).hexdigest()
        assert verify_signature(SECRET, b"x", digest) is True


# --------------------------------------------------------------------------- #
# Endpoint integration
# --------------------------------------------------------------------------- #
def _client(test_config, recorder):
    transport = httpx.MockTransport(recorder.handler)
    app = create_app(test_config, slack_transport=transport, sync_slack_delivery=True)
    return app.test_client()


class TestWebhookEndpoint:
    def test_invalid_signature_rejected(self, test_config, fixture_payloads, recorder):
        client = _client(test_config, recorder)
        headers = make_headers("push")
        headers["X-Hub-Signature-256"] = sign("no-such-secret", fixture_payloads["push"])
        resp = client.post("/webhook/github", data=fixture_payloads["push"], headers=headers)
        assert resp.status_code == 401
        assert recorder.calls == 0  # nothing was sent to Slack

    def test_missing_signature_rejected(self, test_config, fixture_payloads, recorder):
        client = _client(test_config, recorder)
        headers = make_headers("push")
        resp = client.post("/webhook/github", data=fixture_payloads["push"], headers=headers)
        assert resp.status_code == 401

    def test_valid_push_is_stored_and_forwarded(self, test_config, fixture_payloads, recorder):
        client = _client(test_config, recorder)
        headers = make_headers("push")
        headers["X-Hub-Signature-256"] = sign(SECRET, fixture_payloads["push"])
        resp = client.post("/webhook/github", data=fixture_payloads["push"], headers=headers)
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "queued"

        # The MockTransport captured exactly one outbound Slack request.
        assert recorder.calls == 1
        outbound = recorder.requests[0]
        assert outbound.method == "POST"
        assert outbound.url.path.startswith("/services/T/B/X")
        payload = outbound.read()
        body = __import__("json").loads(payload)
        assert "blocks" in body and isinstance(body["blocks"], list)
        assert body["blocks"][0]["type"] == "header"
        # The repo + branch show up somewhere in the blocks text.
        assert "Hello-World" in __import__("json").dumps(body)

    @pytest.mark.parametrize("evt", ["pull_request", "release", "star"])
    def test_supported_event_types_forwarded(self, test_config, fixture_payloads, recorder, evt):
        client = _client(test_config, recorder)
        headers = make_headers(evt)
        headers["X-Hub-Signature-256"] = sign(SECRET, fixture_payloads[evt])
        resp = client.post("/webhook/github", data=fixture_payloads[evt], headers=headers)
        assert resp.status_code == 200
        assert recorder.calls == 1

    def test_idempotent_by_delivery_id(self, test_config, fixture_payloads, recorder):
        client = _client(test_config, recorder)
        headers = make_headers("push", delivery_id="ID-1234")
        headers["X-Hub-Signature-256"] = sign(SECRET, fixture_payloads["push"])

        first = client.post("/webhook/github", data=fixture_payloads["push"], headers=headers)
        second = client.post("/webhook/github", data=fixture_payloads["push"], headers=headers)
        assert first.status_code == 200 and second.status_code == 200
        assert second.get_json()["status"] == "duplicate"
        # Stored once, sent once.
        assert recorder.calls == 1

    def test_unknown_event_type_ignored_silently(self, test_config, fixture_payloads, recorder):
        client = _client(test_config, recorder)
        headers = make_headers("gollum")  # not supported -> silent 200
        headers["X-Hub-Signature-256"] = sign(SECRET, fixture_payloads["push"])
        resp = client.post("/webhook/github", data=fixture_payloads["push"], headers=headers)
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ignored"
        assert recorder.calls == 0

    def test_health_and_events_endpoints(self, test_config, fixture_payloads, recorder):
        client = _client(test_config, recorder)
        assert client.get("/health").get_json()["status"] == "ok"
        # Push something then render the HTML events page.
        headers = make_headers("push")
        headers["X-Hub-Signature-256"] = sign(SECRET, fixture_payloads["push"])
        client.post("/webhook/github", data=fixture_payloads["push"], headers=headers)
        page = client.get("/events")
        assert page.status_code == 200 and b"Hello-World" in page.data or b"push" in page.data