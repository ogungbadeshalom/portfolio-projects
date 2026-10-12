"""Block Kit formatter for GitHub ``pull_request`` events."""

from __future__ import annotations

from typing import Any, Dict, List

#: Human friendly label for each pull_request ``action``.
_ACTION_LABELS = {
    "opened": "opened",
    "reopened": "reopened",
    "closed": "closed",
    "merged": "merged",
    "synchronize": "updated",
    "edited": "edited",
    "review_requested": "got a review request",
    "review_request_removed": "had a review request removed",
    "ready_for_review": "is ready for review",
    "converted_to_draft": "was converted to a draft",
}


def format(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build a rich Slack message for a pull_request event."""
    pr = payload.get("pull_request") or {}
    repo = (payload.get("repository") or {}).get("full_name") or "unknown-repo"
    action = _label(payload.get("action"))

    number = pr.get("number")
    title = (pr.get("title") or "untitled").strip() or "untitled"
    url = _clean_url(pr.get("html_url"))
    user = (pr.get("user") or {}).get("login") or "unknown"
    head = (pr.get("head") or {}).get("ref") or "?"
    base = (pr.get("base") or {}).get("ref") or "?"

    # "merged" is a sub-state of "closed" in the GitHub API payload.
    state_verb = "merged" if pr.get("merged") else action
    if state_verb == "closed" and pr.get("merged"):
        state_verb = "merged"

    blocks: List[Dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f":pr_inbox_tray: PR #{number} {state_verb}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*<{url or '#'}|{title}>* by *{user}* on <{_repo_url(payload)}|{repo}>",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"`{head}` :point_right: `{base}`",
                }
            ],
        },
    ]
    return blocks


def _label(action: Any) -> str:
    key = str(action or "opened")
    return _ACTION_LABELS.get(key, key)


def _repo_url(payload: Dict[str, Any]) -> str:
    repo = payload.get("repository") or {}
    return _clean_url(repo.get("html_url"))


def _clean_url(url: Any) -> str:
    return str(url) if isinstance(url, str) and url else ""