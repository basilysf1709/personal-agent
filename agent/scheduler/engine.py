"""APScheduler orchestrator — cron jobs and post cycle."""

import logging
import os
import uuid
from datetime import datetime, timezone

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from agent.scheduler import state
from agent.scheduler.content_generator import generate_content
from agent.scheduler.image_renderer import render_image
from agent.scheduler.platforms import instagram, tiktok

log = logging.getLogger(__name__)

BRIDGE_URL = os.environ.get("BRIDGE_URL", "http://bridge:3000")
NOTIFY_JID = os.environ.get("ALLOWED_JIDS", "").split(",")[0].strip()
if NOTIFY_JID and not NOTIFY_JID.endswith("@s.whatsapp.net"):
    NOTIFY_JID = NOTIFY_JID + "@s.whatsapp.net"

scheduler: AsyncIOScheduler | None = None


def _notify_whatsapp(message: str) -> None:
    """Send a notification to the primary WhatsApp number."""
    if not NOTIFY_JID:
        return
    try:
        httpx.post(
            f"{BRIDGE_URL}/send",
            json={"to": NOTIFY_JID, "text": message},
            timeout=10.0,
        )
    except httpx.HTTPError as e:
        log.warning("WhatsApp notification failed: %s", e)


def run_post_cycle() -> str:
    """Generate content, render image, and post to configured platforms.

    Returns a summary string.
    """
    s = state.load()
    category = state.next_category(s)
    recent = state.recent_titles(s)

    # Generate content
    log.info("Generating content for category: %s", category)
    try:
        content = generate_content(category, recent)
    except Exception as e:
        msg = f"Content generation failed: {e}"
        log.error(msg)
        state.save(s)  # save the advanced pointer
        return msg

    post_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    title = content["title"]

    # Render image
    log.info("Rendering image for: %s", title)
    try:
        image_path = render_image(
            post_id=post_id,
            category=category,
            title=title,
            body=content["body"],
            latex=content.get("latex"),
            code=content.get("code"),
            code_language=content.get("code_language"),
            hashtags=content.get("hashtags"),
        )
    except Exception as e:
        msg = f"Image rendering failed: {e}"
        log.error(msg)
        state.save(s)
        return msg

    caption = content.get("caption", title)

    # Post to platforms
    platform_results = {}
    platforms = s.get("platforms", ["instagram", "tiktok"])

    if "instagram" in platforms:
        log.info("Posting to Instagram...")
        platform_results["instagram"] = instagram.publish(post_id, caption)

    if "tiktok" in platforms:
        log.info("Posting to TikTok...")
        platform_results["tiktok"] = tiktok.publish(image_path, caption)

    # Record post
    state.record_post(s, post_id, category, title, platform_results)

    # Build summary
    summary_parts = [f"Posted: {title}", f"Category: {category.replace('_', ' ')}"]
    for platform, result in platform_results.items():
        status = result.get("status", "unknown")
        detail = result.get("detail", result.get("media_id", result.get("publish_id", "")))
        summary_parts.append(f"  {platform}: {status}" + (f" ({detail})" if detail else ""))

    summary = "\n".join(summary_parts)
    log.info("Post cycle complete:\n%s", summary)

    # Notify via WhatsApp
    _notify_whatsapp(f"📱 Auto-post complete!\n\n{summary}")

    return summary


async def _scheduled_post():
    """Async wrapper for the cron job."""
    try:
        summary = run_post_cycle()
        log.info("Scheduled post result: %s", summary)
    except Exception as e:
        log.error("Scheduled post failed: %s", e, exc_info=True)
        _notify_whatsapp(f"❌ Scheduled post failed: {e}")


def _rebuild_jobs() -> None:
    """Clear and recreate cron jobs based on current state."""
    if scheduler is None:
        return

    # Remove existing scheduler jobs
    scheduler.remove_all_jobs()

    s = state.load()
    if not s.get("enabled"):
        return

    tz = s.get("timezone", "America/Toronto")
    hours = s.get("cron_hours", [9, 17])
    minutes = s.get("cron_minutes", [0, 0])

    for i, (h, m) in enumerate(zip(hours, minutes)):
        trigger = CronTrigger(hour=h, minute=m, timezone=tz)
        scheduler.add_job(
            _scheduled_post,
            trigger=trigger,
            id=f"content_post_{i}",
            replace_existing=True,
        )
        log.info("Scheduled post job: %02d:%02d %s", h, m, tz)


def start_scheduler() -> None:
    """Initialize and start the APScheduler instance."""
    global scheduler
    if scheduler is not None:
        return

    scheduler = AsyncIOScheduler()
    scheduler.start()
    _rebuild_jobs()
    log.info("Scheduler started")


def stop_scheduler() -> None:
    """Shut down the scheduler."""
    global scheduler
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        scheduler = None
        log.info("Scheduler stopped")


def enable() -> str:
    """Enable scheduled posting."""
    s = state.load()
    s["enabled"] = True
    state.save(s)
    _rebuild_jobs()
    return "Scheduler enabled. Posts will be published on schedule."


def disable() -> str:
    """Disable scheduled posting."""
    s = state.load()
    s["enabled"] = False
    state.save(s)
    _rebuild_jobs()
    return "Scheduler disabled. No more auto-posts until re-enabled."


def get_status() -> str:
    """Return a human-readable status summary."""
    s = state.load()
    enabled = s.get("enabled", False)
    tz = s.get("timezone", "America/Toronto")
    hours = s.get("cron_hours", [9, 17])
    minutes = s.get("cron_minutes", [0, 0])
    platforms = s.get("platforms", [])
    cat_idx = s.get("category_pointer", 0) % len(state.CATEGORIES)
    next_cat = state.CATEGORIES[cat_idx]
    posts = s.get("posts", [])

    lines = [
        f"Status: {'ACTIVE' if enabled else 'PAUSED'}",
        f"Schedule: {', '.join(f'{h:02d}:{m:02d}' for h, m in zip(hours, minutes))} ({tz})",
        f"Platforms: {', '.join(platforms) if platforms else 'none'}",
        f"Next category: {next_cat.replace('_', ' ')}",
        f"Total posts: {len(posts)}",
    ]

    if posts:
        recent = posts[-3:]
        lines.append("\nRecent posts:")
        for p in reversed(recent):
            lines.append(f"  - [{p['category'].replace('_', ' ')}] {p['title']} ({p['created_at'][:16]})")

    if scheduler:
        jobs = scheduler.get_jobs()
        fire_times = [j.next_run_time for j in jobs if j.next_run_time]
        if fire_times:
            next_run = min(fire_times)
            lines.append(f"\nNext fire: {next_run.strftime('%Y-%m-%d %H:%M %Z')}")

    return "\n".join(lines)


def update_config(
    cron_hours: list[int] | None = None,
    cron_minutes: list[int] | None = None,
    timezone: str | None = None,
    platforms: list[str] | None = None,
) -> str:
    """Update scheduler configuration."""
    s = state.load()
    changes = []

    if cron_hours is not None:
        s["cron_hours"] = cron_hours
        if cron_minutes is None:
            # Pad minutes to match hours length
            s["cron_minutes"] = [0] * len(cron_hours)
        changes.append(f"hours={cron_hours}")

    if cron_minutes is not None:
        s["cron_minutes"] = cron_minutes
        changes.append(f"minutes={cron_minutes}")

    if timezone is not None:
        s["timezone"] = timezone
        changes.append(f"timezone={timezone}")

    if platforms is not None:
        s["platforms"] = platforms
        changes.append(f"platforms={platforms}")

    state.save(s)
    _rebuild_jobs()
    return f"Config updated: {', '.join(changes)}" if changes else "No changes made."
