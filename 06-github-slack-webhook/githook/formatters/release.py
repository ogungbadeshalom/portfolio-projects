"""Block Kit formatter for GitHub ``release`` events."""

from __future__ import annotations

from typing import Any, Dict, List


def format(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build a rich Slack message for a release event."""
    release = payload.get("release") or {}
    repo = (payload.get("repository") or {}).get("full_name") or "unknown-repo"
    action = payload.get("action") or "published"

    tag_name = release.get("tag_name") or "?"
    name = release.get("name") or tag_name
    url = _clean_url(release.get("html_url"))
    author = (release.get("author") or {}).get("login") or "unknown"
    body = ((release.get("body") or "").strip() or "No release notes")
    # Keep the notes snippet reasonably short for Slack.
    body = body[:280] + ("…" if len(body) > 280 else "")

    blocks: List[Dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f":sparkles: Release {tag_name} {action}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*<{url or '#'}|{name}>* by *{author}* on <{_repo_url(payload)}|{repo}>",
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"> {body}"},
        },
    ]
    return blocks


def _repo_url(payload: Dict[str, Any]) -> str:
    repo = payload.get("repository") or {}
    return _clean_url(repo.get("html_url"))


def _clean_url(url: Any) -> str:
    return str(url) if isinstance(url, str) and url else ""