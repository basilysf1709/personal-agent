"""WhatsApp tool for controlling the content scheduler."""

import logging

from agent.scheduler import engine

log = logging.getLogger(__name__)

MANAGE_SCHEDULER_SCHEMA = {
    "name": "manage_scheduler",
    "description": (
        "Control the automated content scheduler that posts LaTeX equations "
        "to Instagram as images and Reels. "
        "Actions: start, stop, status, post_image, post_reel, update."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start", "stop", "status", "post_image", "post_reel", "update"],
                "description": (
                    "start = enable auto-posting, "
                    "stop = disable, "
                    "status = show config & recent posts, "
                    "post_image = trigger immediate image post, "
                    "post_reel = trigger immediate reel post, "
                    "update = change schedule config"
                ),
            },
            "image_hours": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Hours for image posts (24h format). Only for 'update'.",
            },
            "reel_hours": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Hours for reel posts (24h format). Only for 'update'.",
            },
            "timezone": {
                "type": "string",
                "description": "Timezone string, e.g. 'America/Toronto'. Only for 'update'.",
            },
            "platforms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Platforms to post to: ['instagram']. Only for 'update'.",
            },
        },
        "required": ["action"],
    },
}


def manage_scheduler(
    action: str,
    image_hours: list[int] | None = None,
    reel_hours: list[int] | None = None,
    timezone: str | None = None,
    platforms: list[str] | None = None,
    **kwargs,
) -> str:
    """Execute a scheduler management action."""
    try:
        if action == "start":
            return engine.enable()
        elif action == "stop":
            return engine.disable()
        elif action == "status":
            return engine.get_status()
        elif action == "post_image":
            return engine.run_image_post()
        elif action == "post_reel":
            return engine.run_reel_post()
        elif action == "post_now":
            return engine.run_image_post()
        elif action == "update":
            return engine.update_config(
                image_hours=image_hours,
                reel_hours=reel_hours,
                timezone=timezone,
                platforms=platforms,
            )
        else:
            return f"Unknown action: {action}. Use: start, stop, status, post_image, post_reel, update."
    except Exception as e:
        log.error("Scheduler action '%s' failed: %s", action, e, exc_info=True)
        return f"Error: {e}"
