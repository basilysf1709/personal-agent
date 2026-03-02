"""WhatsApp tool for controlling the content scheduler."""

import logging

from agent.scheduler import engine

log = logging.getLogger(__name__)

MANAGE_SCHEDULER_SCHEMA = {
    "name": "manage_scheduler",
    "description": (
        "Control the automated content scheduler that posts educational content "
        "(math, coding tips, science facts, quotes, tech insights, etc.) to "
        "Instagram and TikTok. Actions: start, stop, status, post_now, update."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start", "stop", "status", "post_now", "update"],
                "description": (
                    "start = enable auto-posting schedule, "
                    "stop = disable it, "
                    "status = show current config and recent posts, "
                    "post_now = trigger an immediate post, "
                    "update = change schedule/platform config"
                ),
            },
            "cron_hours": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Hours to post at (24h format), e.g. [9, 17]. Only for 'update' action.",
            },
            "cron_minutes": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Minutes to post at, matching cron_hours. Only for 'update' action.",
            },
            "timezone": {
                "type": "string",
                "description": "Timezone string, e.g. 'America/Toronto'. Only for 'update' action.",
            },
            "platforms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Platforms to post to: ['instagram', 'tiktok']. Only for 'update' action.",
            },
        },
        "required": ["action"],
    },
}


def manage_scheduler(
    action: str,
    cron_hours: list[int] | None = None,
    cron_minutes: list[int] | None = None,
    timezone: str | None = None,
    platforms: list[str] | None = None,
) -> str:
    """Execute a scheduler management action."""
    try:
        if action == "start":
            return engine.enable()

        elif action == "stop":
            return engine.disable()

        elif action == "status":
            return engine.get_status()

        elif action == "post_now":
            return engine.run_post_cycle()

        elif action == "update":
            return engine.update_config(
                cron_hours=cron_hours,
                cron_minutes=cron_minutes,
                timezone=timezone,
                platforms=platforms,
            )

        else:
            return f"Unknown action: {action}. Use: start, stop, status, post_now, update."

    except Exception as e:
        log.error("Scheduler action '%s' failed: %s", action, e, exc_info=True)
        return f"Error: {e}"
