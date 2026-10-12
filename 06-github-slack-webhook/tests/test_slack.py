"""Tests for Slack delivery: payload building, retry/backoff, transport.

Everything uses ``httpx.MockTransport`` so no request leaves the process.
"""

from __future__ import annotations

import httpx
import pytest

from githook.retry import backoff_seconds
from githook.slack import build_payload, send_to_slack

WEBHOOK_URL = "https://hooks.slack.com/services/T0000/B0000/XXXX"

SIMPLE_BLOCKS = [
    {"type": "header", "text": {"type": "plain_text", "text": ":rocket: 1 commit pushed"}},
    {"type": "section", "text": {"type": "mrkdwn", "text": "octocat/Repo on branch *`main`*"}},
]


def _transport(statuses, capture=None):
    """Return a MockTransport returning the given status codes in sequence.

    ``capture`` (optional list) is appended with each outbound request.
    """
    statuses = list(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        status = statuses.pop(0) if statuses else statuses[-1]
        return httpx.Response(status, json={"ok": status == 200})

    return httpx.MockTransport(handler)


class TestPayload:
    def test_build_payload_wraps_blocks_and_adds_text(self):
        payload = build_payload(SIMPLE_BLOCKS)
        assert payload["blocks"] == SIMPLE_BLOCKS
        assert payload["text"]  # plain-text fallback is populated

    def test_build_payload_text_strips_slack_links(self):
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "*<https://x.com/y|Label>* done"}}]
        payload = build_payload(blocks)
        assert "Label" in payload["text"]
        assert "https://" not in payload["text"]


class TestSend:
    def test_success_on_200(self):
        captured = []
        result = send_to_slack(
            WEBHOOK_URL, SIMPLE_BLOCKS, transport=_transport([200], captured)
        )
        assert result.success is True
        assert result.status_code == 200
        assert len(captured) == 1

    def test_no_url_returns_passthrough(self):
        result = send_to_slack("", SIMPLE_BLOCKS)
        assert result.success is False

    @pytest.mark.parametrize("retry_status", [429, 500, 503])
    def test_retries_on_throttling(self, retry_status):
        captured = []
        result = send_to_slack(
            WEBHOOK_URL,
            SIMPLE_BLOCKS,
            transport=_transport([retry_status, 200], captured),
            max_retries=3,
        )
        assert result.success is True
        # first attempt throttled, second succeeded -> two outbound calls
        assert len(captured) == 2

    def test_exhausts_retries_and_fails(self):
        captured = []
        result = send_to_slack(
            WEBHOOK_URL,
            SIMPLE_BLOCKS,
            transport=_transport([429, 429, 429, 429], captured),
            max_retries=3,
        )
        assert result.success is False
        assert len(captured) == 3

    def test_hard_failure_not_retried(self):
        captured = []
        result = send_to_slack(
            WEBHOOK_URL,
            SIMPLE_BLOCKS,
            transport=_transport([400, 200], captured),
            max_retries=3,
        )
        assert result.success is False
        assert result.status_code == 400
        assert len(captured) == 1  # a 400 is a hard failure -> no retry


class TestBackoff:
    def test_exponential_schedule(self):
        assert backoff_seconds(1, 1.0) == 1.0
        assert backoff_seconds(2, 1.0) == 2.0
        assert backoff_seconds(3, 1.0) == 4.0
        assert backoff_seconds(4, 1.0) == 8.0

    def test_backoff_is_capped(self):
        assert backoff_seconds(10, 1.0) <= 60.0

    def test_backoff_with_custom_base(self):
        assert backoff_seconds(2, 0.5) == 1.0