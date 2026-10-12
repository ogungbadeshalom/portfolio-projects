"""Block Kit formatter for GitHub ``push`` events."""

from __future__ import annotations

from typing import Any, Dict, List


def format(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build a rich Slack message for a push event."""
    repo = (payload.get("repository") or {}).get("full_name") or "unknown-repo"
    branch = (payload.get("ref") or "refs/heads/main").rsplit("/", 1)[-1]

    commits = payload.get("commits") or []
    head = commits[0] if commits else {}
    author = (head.get("author") or {}).get("name") or "unknown"
    message = (head.get("message") or "").strip().split("\n")[0].strip() or "no message"

    compare_url = payload.get("compare")
    if not compare_url:
        repo_url = _clean_url((payload.get("repository") or {}).get("html_url"))
        compare_url = f"{repo_url}/compare/{branch}"

    added = len(payload.get("added") or [])
    removed = len(payload.get("removed") or [])
    modified = len(payload.get("modified") or [])

    num_commits = len(commits)
    commit_summary = (
        f"{num_commits} commit{'s' if num_commits != 1 else ''}"
        if num_commits
        else "no new commits"
    )
    diff_summary = _diff_summary(added, removed, modified)

    blocks: List[Dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{commit_summary} pushed to {branch}", "emoji": True},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*<{_clean_url((payload.get('repository') or {}).get('html_url')) or compare_url}|{repo}>* "
                    f"on branch *`{branch}`*"
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{author}* — {message}",
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": ":hammer_and_wrench: Compare", "emoji": True},
                "url": compare_url,
            },
        },
    ]

    if diff_summary:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": diff_summary}],
            }
        )
    return blocks


def _diff_summary(added: int, removed: int, modified: int) -> str:
    parts = []
    if added:
        parts.append(f"*+{added}* added")
    if removed:
        parts.append(f"*-{removed}* removed")
    if removed == 0 and added == 0:
        parts.append(f"*{modified}* modified")
    elif modified:
        parts.append(f"*{modified}* modified")
    return "  ·  ".join(parts) if parts else ""


def _clean_url(url: Any) -> str:
    return str(url) if isinstance(url, str) and url else ""