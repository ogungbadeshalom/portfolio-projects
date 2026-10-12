"""End-to-end API tests: the full subscribe -> confirm -> send -> track flow,
exercised offline with SQLite + the FileSender backend via FastAPI's TestClient
(no external SMTP, no network).

Each test starts from a clean (truncated) database, courtesy of the autouse
``_clean_tables`` fixture in conftest.py.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from newsletter.config import settings
from newsletter.db import SessionLocal
from newsletter.models import Campaign, CampaignStatus, Send, Subscriber, SubscriberStatus
from newsletter.security import make_confirm_token, make_unsubscribe_token


# --- helpers ------------------------------------------------------------------

def _subscriber_row(email: str) -> Subscriber | None:
    with SessionLocal() as s:
        return s.query(Subscriber).filter(Subscriber.email == email.lower()).one_or_none()


def _send_row(campaign_id: int, subscriber_id: int) -> Send | None:
    with SessionLocal() as s:
        return (
            s.query(Send)
            .filter(Send.campaign_id == campaign_id, Send.subscriber_id == subscriber_id)
            .one_or_none()
        )


def _campaign_row(campaign_id: int) -> Campaign | None:
    with SessionLocal() as s:
        return s.query(Campaign).filter(Campaign.id == campaign_id).one_or_none()


def _confirm_token_for(email: str) -> str:
    """Fetch the subscriber row and build the HMAC confirm token (as mailer does)."""
    row = _subscriber_row(email)
    assert row is not None, "subscriber not found; confirm before building token"
    return make_confirm_token(row.email, row.unsubscribe_token)


def _unsubscribe_token_for(email: str) -> str:
    row = _subscriber_row(email)
    assert row is not None
    return make_unsubscribe_token(row.email, row.unsubscribe_token)


def _eml_bodies() -> list[str]:
    outbox = settings.outbox_dir
    if not outbox.exists():
        return []
    return [p.read_text(encoding="utf-8") for p in sorted(outbox.glob("*.eml"))]


# --- subscribe + confirm ------------------------------------------------------

def test_subscribe_creates_pending_and_outbox_eml(client: TestClient):
    resp = client.post("/api/subscribe", json={"email": "alice@example.com", "name": "Alice"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == "alice@example.com"
    assert body["status"] == SubscriberStatus.PENDING.value

    row = _subscriber_row("alice@example.com")
    assert row is not None
    assert row.status == SubscriberStatus.PENDING.value

    # A confirmation .eml appears in the outbox containing the confirm link.
    bodies = _eml_bodies()
    assert bodies, "FileSender should have written a confirmation .eml"
    assert any("api/subscribe/confirm" in b for b in bodies)


def test_subscribe_invalid_email_returns_400(client: TestClient):
    resp = client.post("/api/subscribe", json={"email": "not-an-email"})
    assert resp.status_code == 400
    with SessionLocal() as s:
        assert s.query(Subscriber).count() == 0


def test_confirm_activates_subscriber(client: TestClient):
    client.post("/api/subscribe", json={"email": "bob@example.com"})
    token = _confirm_token_for("bob@example.com")

    resp = client.get("/api/subscribe/confirm", params={"email": "bob@example.com", "token": token})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == SubscriberStatus.ACTIVE.value

    row = _subscriber_row("bob@example.com")
    assert row.status == SubscriberStatus.ACTIVE.value
    assert row.confirmed_at is not None


def test_confirm_forged_token_rejected(client: TestClient):
    client.post("/api/subscribe", json={"email": "carol@example.com"})
    # A token signed with the WRONG server HMAC key must be refused even when
    # the subscriber's real secret is embedded in the payload. (Confirm and
    # unsubscribe tokens share construction, so building this from
    # make_unsubscribe_token with a bad key is equivalent to a forged confirm.)
    forged = make_unsubscribe_token(
        "carol@example.com",
        _subscriber_row("carol@example.com").unsubscribe_token,
        signing_key=b"attacker-key",
    )
    resp = client.get(
        "/api/subscribe/confirm", params={"email": "carol@example.com", "token": forged}
    )
    assert resp.status_code == 400, resp.text
    assert _subscriber_row("carol@example.com").status == SubscriberStatus.PENDING.value


# --- campaigns (admin) --------------------------------------------------------

def test_create_and_get_campaign_admin(client: TestClient, auth):
    payload = {
        "subject": "Hello world",
        "html_body": "<p>Hi <a href='https://example.com'>link</a> $name</p>",
        "text_body": "Hi $name, click $unsubscribe_url",
    }
    resp = client.post("/api/admin/campaigns", json=payload, auth=auth)
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]
    assert resp.json()["status"] == CampaignStatus.DRAFT.value

    got = client.get(f"/api/admin/campaigns/{cid}", auth=auth)
    assert got.status_code == 200
    assert got.json()["subject"] == "Hello world"


def test_admin_requires_auth(client: TestClient):
    resp = client.get("/api/admin/stats")
    assert resp.status_code == 401


def test_send_campaign_creates_sends_and_marks_sent(client: TestClient, auth):
    # One ACTIVE subscriber (subscribe + confirm).
    client.post("/api/subscribe", json={"email": "dana@example.com"})
    token = _confirm_token_for("dana@example.com")
    client.get("/api/subscribe/confirm", params={"email": "dana@example.com", "token": token})

    # A second subscriber who stays PENDING (should NOT be sent).
    client.post("/api/subscribe", json={"email": "eve@example.com"})

    resp = client.post(
        "/api/admin/campaigns",
        json={"subject": "Sprint mail", "html_body": "<a href='https://example.com/x'>x</a>"},
        auth=auth,
    )
    cid = resp.json()["id"]

    send_resp = client.post(f"/api/admin/campaigns/{cid}/send", auth=auth)
    assert send_resp.status_code == 200, send_resp.text
    result = send_resp.json()
    assert result["sent"] == 1
    assert result["failed"] == 0
    assert result["status"] == CampaignStatus.SENT.value

    # Send row exists for the active subscriber, not the pending one.
    dana = _subscriber_row("dana@example.com")
    eve = _subscriber_row("eve@example.com")
    assert _send_row(cid, dana.id) is not None
    assert _send_row(cid, eve.id) is None

    # Campaign row reflects SENT.
    assert _campaign_row(cid).status == CampaignStatus.SENT.value
    assert _campaign_row(cid).sent_at is not None

    # .eml campaign mail(s) written: one per active subscriber (+ the earlier conf).
    bodies = _eml_bodies()
    assert sum("Sprint mail" in b for b in bodies) == 1


# --- open / click tracking ----------------------------------------------------

def test_open_tracking_sets_opened_and_sends_gif(client: TestClient, auth):
    client.post("/api/subscribe", json={"email": "fran@example.com"})
    fran = _subscriber_row("fran@example.com")
    client.get("/api/subscribe/confirm", params={"email": "fran@example.com", "token": _confirm_token_for("fran@example.com")})

    cid = client.post("/api/admin/campaigns", json={"subject": "Track"}, auth=auth).json()["id"]
    client.post(f"/api/admin/campaigns/{cid}/send", auth=auth)

    resp = client.get(f"/api/track/open/{cid}", params={"sid": fran.id})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/gif"
    assert resp.headers["cache-control"] == "no-store"
    assert resp.content[:6] == b"GIF89a"

    send = _send_row(cid, fran.id)
    assert send.opened_at is not None


def test_click_tracking_safe_redirect_sets_clicked(client: TestClient, auth):
    client.post("/api/subscribe", json={"email": "grace@example.com"})
    grace = _subscriber_row("grace@example.com")
    client.get("/api/subscribe/confirm", params={"email": "grace@example.com", "token": _confirm_token_for("grace@example.com")})

    cid = client.post("/api/admin/campaigns", json={"subject": "Links"}, auth=auth).json()["id"]
    client.post(f"/api/admin/campaigns/{cid}/send", auth=auth)

    target = "https://example.com/page"
    resp = client.get(
        f"/api/track/click/{cid}",
        params={"target": target, "sid": grace.id},
        follow_redirects=False,
    )
    assert resp.status_code == 307, resp.text
    assert resp.headers["location"].rstrip("/") == "https://example.com/page"

    send = _send_row(cid, grace.id)
    assert send.clicked_at is not None


def test_click_tracking_unsafe_target_not_redirected(client: TestClient, auth):
    client.post("/api/subscribe", json={"email": "heidi@example.com"})
    heidi = _subscriber_row("heidi@example.com")
    client.get("/api/subscribe/confirm", params={"email": "heidi@example.com", "token": _confirm_token_for("heidi@example.com")})

    cid = client.post("/api/admin/campaigns", json={"subject": "Danger"}, auth=auth).json()["id"]
    client.post(f"/api/admin/campaigns/{cid}/send", auth=auth)

    resp = client.get(
        f"/api/track/click/{cid}", params={"target": "javascript:alert(1)", "sid": heidi.id}
    )
    # Must NOT redirect: no 3xx Location to the javascript: URL.
    assert resp.status_code == 200, resp.text
    assert "javascript:" not in resp.headers.get("location", "")


# --- unsubscribe --------------------------------------------------------------

def test_unsubscribe_marks_unsubscribed_and_sends_notice(client: TestClient, auth):
    client.post("/api/subscribe", json={"email": "ivana@example.com"})
    token = _confirm_token_for("ivana@example.com")
    client.get("/api/subscribe/confirm", params={"email": "ivana@example.com", "token": token})

    unsub_token = _unsubscribe_token_for("ivana@example.com")
    resp = client.get("/api/unsubscribe", params={"token": unsub_token})
    assert resp.status_code == 200, resp.text

    row = _subscriber_row("ivana@example.com")
    assert row.status == SubscriberStatus.UNSUBSCRIBED.value

    # A CAN-SPAM notice .eml is produced.
    assert any("unsubscribed" in b.lower() for b in _eml_bodies())


def test_unsubscribe_forged_token_rejected(client: TestClient):
    client.post("/api/subscribe", json={"email": "julie@example.com"})
    # Signed with the wrong HMAC key -> invalid even with the right payload.
    forged = make_unsubscribe_token(
        "julie@example.com", _subscriber_row("julie@example.com").unsubscribe_token,
        signing_key=b"attacker-key",
    )
    resp = client.get("/api/unsubscribe", params={"token": forged})
    assert resp.status_code == 400, resp.text
    assert _subscriber_row("julie@example.com").status == SubscriberStatus.PENDING.value


def test_hmac_forged_unsubscribe_token_rejected(client: TestClient):
    """A token signed with the wrong HMAC secret must be refused even if the
    subscriber's real secret is known."""
    client.post("/api/subscribe", json={"email": "karl@example.com"})
    row = _subscriber_row("karl@example.com")
    forged = make_unsubscribe_token(row.email, row.unsubscribe_token, signing_key=b"wrong")
    resp = client.get("/api/unsubscribe", params={"token": forged})
    assert resp.status_code == 400, resp.text


# --- stats --------------------------------------------------------------------

def test_admin_stats_reflects_activity(client: TestClient, auth):
    # One active + one unsubscribed subscriber.
    client.post("/api/subscribe", json={"email": "liam@example.com"})
    client.get("/api/subscribe/confirm", params={"email": "liam@example.com", "token": _confirm_token_for("liam@example.com")})
    client.post("/api/subscribe", json={"email": "mia@example.com"})
    client.get("/api/unsubscribe", params={"token": _unsubscribe_token_for("mia@example.com")})

    # Send -> open -> click to exercise counted events.
    cid = client.post("/api/admin/campaigns", json={"subject": "Stats"}, auth=auth).json()["id"]
    client.post(f"/api/admin/campaigns/{cid}/send", auth=auth)
    liam = _subscriber_row("liam@example.com")
    client.get(f"/api/track/open/{cid}", params={"sid": liam.id})
    client.get(f"/api/track/click/{cid}", params={"target": "https://x.example/1", "sid": liam.id})

    stats = client.get("/api/admin/stats", auth=auth).json()
    assert stats["subscribers"] == 2
    assert stats["active"] == 1
    assert stats["unsubscribed"] == 1
    assert stats["sent"] == 1
    assert stats["opened"] == 1
    assert stats["clicked"] == 1


# --- import / export ----------------------------------------------------------

def test_subscribers_import_and_export(client: TestClient, auth):
    csv_text = "email,name\nnina@example.com,Nina\noana@example.com,Oana\ngarbage,\n"
    resp = client.post(
        "/api/admin/subscribers/import", content=csv_text.encode(), auth=auth
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["added"] == 2
    assert resp.json()["invalid_rows"] == 1

    exported = client.get("/api/admin/subscribers/export", auth=auth)
    assert exported.status_code == 200
    assert "nina@example.com" in exported.text
    assert "oana@example.com" in exported.text