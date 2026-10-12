"""Block Kit formatter for GitHub ``star`` events."""

from __future__ import annotations

from typing import Any, Dict, List


def format(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build a rich Slack message for a star (watch) event."""
    repo = (payload.get("repository") or {}).get("full_name") or "unknown-repo"
    starred_by = (payload.get("sender") or {}).get("login") or "someone"
    repo_url = _clean_url((payload.get("repository") or {}).get("html_url"))
    stars = (payload.get("repository") or {}).get("stargazers_count")

    action = payload.get("action") or "starred"
    is_star = action == "starred"
    verb = "starred" if is_star else "unstarred"

    blocks: List[Dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ("⭐ " if is_star else ":heart: ") + f"{starred_by} {verb} {repo}",
                "emoji": True,
            },
        }
    ]
    if is_star and stars is not None:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"⭐ Total stars: *{stars}*  ·  <{repo_url or '#'}|View repo>",
                    }
                ],
            }
        )
    return blocks


def _clean_url(url: Any) -> str:
    return str(url) if isinstance(url, str) and url else ""