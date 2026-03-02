"""JSON-based persistence for scheduler state."""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

STATE_PATH = os.environ.get(
    "SCHEDULER_STATE_PATH", "/app/data/scheduler_state.json"
)

DEFAULT_STATE: dict[str, Any] = {
    "enabled": False,
    "cron_hours": [9, 17],
    "cron_minutes": [0, 0],
    "timezone": "America/Toronto",
    "platforms": ["instagram", "tiktok"],
    "category_pointer": 0,
    "posts": [],  # list of {id, category, title, platform_results, created_at}
}

CATEGORIES = [
    "math_equations",
    "coding_tips",
    "science_facts",
    "motivational_quotes",
    "tech_insights",
    "algorithm_visualizations",
    "physics_concepts",
    "historical_tech_moments",
]


def _ensure_dir():
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)


def load() -> dict[str, Any]:
    """Load state from disk, returning defaults if missing or corrupt."""
    try:
        with open(STATE_PATH) as f:
            data = json.load(f)
        # Merge defaults for any missing keys
        for k, v in DEFAULT_STATE.items():
            data.setdefault(k, v)
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULT_STATE)


def save(state: dict[str, Any]) -> None:
    """Persist state to disk."""
    _ensure_dir()
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, default=str)
    os.replace(tmp, STATE_PATH)


def next_category(state: dict[str, Any]) -> str:
    """Return the next category in the round-robin and advance the pointer."""
    idx = state["category_pointer"] % len(CATEGORIES)
    category = CATEGORIES[idx]
    state["category_pointer"] = (idx + 1) % len(CATEGORIES)
    return category


def recent_titles(state: dict[str, Any], n: int = 10) -> list[str]:
    """Return the last n post titles."""
    return [p["title"] for p in state["posts"][-n:]]


def record_post(
    state: dict[str, Any],
    post_id: str,
    category: str,
    title: str,
    platform_results: dict[str, str],
) -> None:
    """Append a post record and save."""
    state["posts"].append(
        {
            "id": post_id,
            "category": category,
            "title": title,
            "platform_results": platform_results,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    # Keep last 200 posts
    if len(state["posts"]) > 200:
        state["posts"] = state["posts"][-200:]
    save(state)
