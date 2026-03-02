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
from agent.scheduler.video_renderer import render_video
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


def _generate_and_render(post_type: str) -> tuple[str, str, dict, str]:
    """Generate content, render media. Returns (post_id, title, content, media_path)."""
    s = state.load()
    category = state.next_category(s)
    recent = state.recent_titles(s)

    log.info("Generating content for %s (%s)", post_type, category)
    content = generate_content(category, recent)

    post_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    title = content["title"]

    # Always render the LaTeX image first (needed for both image and video)
    log.info("Rendering image for: %s", title)
    image_path = render_image(
        post_id=post_id,
        category=category,
        title=title,
        body=content["body"],
        latex=content.get("latex"),
    )

    if post_type == "reel":
        log.info("Rendering video for: %s", title)
        media_path = render_video(post_id, image_path)
    else:
        media_path = image_path

    return post_id, title, content, category


def run_image_post() -> str:
    """Generate content and post as an image."""
    s = state.load()
    try:
        post_id, title, content, category = _generate_and_render("image")
    except Exception as e:
        msg = f"Image post failed: {e}"
        log.error(msg)
        state.save(s)
        return msg

    caption = content.get("caption", title)
    platform_results = {}

    if "instagram" in s.get("platforms", []):
        log.info("Publishing image to Instagram...")
        platform_results["instagram"] = instagram.publish(post_id, caption)

    state.record_post(s, post_id, category, title, platform_results, post_type="image")

    summary = _build_summary(title, category, platform_results, "image")
    _notify_whatsapp(f"📸 Image post complete!\n\n{summary}")
    return summary


def run_reel_post() -> str:
    """Generate content and post as a Reel video."""
    s = state.load()
    try:
        post_id, title, content, category = _generate_and_render("reel")
    except Exception as e:
        msg = f"Reel post failed: {e}"
        log.error(msg)
        state.save(s)
        return msg

    caption = content.get("caption", title)
    platform_results = {}

    if "instagram" in s.get("platforms", []):
        log.info("Publishing reel to Instagram...")
        platform_results["instagram_reel"] = instagram.publish_reel(post_id, caption)

    state.record_post(s, post_id, category, title, platform_results, post_type="reel")

    summary = _build_summary(title, category, platform_results, "reel")
    _notify_whatsapp(f"🎬 Reel post complete!\n\n{summary}")
    return summary


def run_post_cycle() -> str:
    """Run an image post (backwards compat for manual triggers)."""
    return run_image_post()


def _build_summary(title: str, category: str, platform_results: dict, post_type: str) -> str:
    parts = [f"[{post_type.upper()}] Posted: {title}", f"Category: {category.replace('_', ' ')}"]
    for platform, result in platform_results.items():
        status = result.get("status", "unknown")
        detail = result.get("detail", result.get("media_id", ""))
        parts.append(f"  {platform}: {status}" + (f" ({detail})" if detail else ""))
    summary = "\n".join(parts)
    log.info("Post cycle complete:\n%s", summary)
    return summary


async def _scheduled_image_post():
    """Async wrapper for scheduled image posts."""
    try:
        summary = run_image_post()
        log.info("Scheduled image post: %s", summary)
    except Exception as e:
        log.error("Scheduled image post failed: %s", e, exc_info=True)
        _notify_whatsapp(f"❌ Image post failed: {e}")


async def _scheduled_reel_post():
    """Async wrapper for scheduled reel posts."""
    try:
        summary = run_reel_post()
        log.info("Scheduled reel post: %s", summary)
    except Exception as e:
        log.error("Scheduled reel post failed: %s", e, exc_info=True)
        _notify_whatsapp(f"❌ Reel post failed: {e}")


def _rebuild_jobs() -> None:
    """Clear and recreate cron jobs based on current state."""
    if scheduler is None:
        return

    scheduler.remove_all_jobs()

    s = state.load()
    if not s.get("enabled"):
        return

    tz = s.get("timezone", "America/Toronto")

    # Image post schedule
    img_hours = s.get("image_hours", [9])
    img_minutes = s.get("image_minutes", [0])
    for i, (h, m) in enumerate(zip(img_hours, img_minutes)):
        trigger = CronTrigger(hour=h, minute=m, timezone=tz)
        scheduler.add_job(
            _scheduled_image_post,
            trigger=trigger,
            id=f"image_post_{i}",
            replace_existing=True,
        )
        log.info("Scheduled image post: %02d:%02d %s", h, m, tz)

    # Reel post schedule
    reel_hours = s.get("reel_hours", [17])
    reel_minutes = s.get("reel_minutes", [0])
    for i, (h, m) in enumerate(zip(reel_hours, reel_minutes)):
        trigger = CronTrigger(hour=h, minute=m, timezone=tz)
        scheduler.add_job(
            _scheduled_reel_post,
            trigger=trigger,
            id=f"reel_post_{i}",
            replace_existing=True,
        )
        log.info("Scheduled reel post: %02d:%02d %s", h, m, tz)


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
    return "Scheduler enabled."


def disable() -> str:
    """Disable scheduled posting."""
    s = state.load()
    s["enabled"] = False
    state.save(s)
    _rebuild_jobs()
    return "Scheduler disabled."


def get_status() -> str:
    """Return a human-readable status summary."""
    s = state.load()
    enabled = s.get("enabled", False)
    tz = s.get("timezone", "America/Toronto")
    img_hours = s.get("image_hours", [9])
    img_minutes = s.get("image_minutes", [0])
    reel_hours = s.get("reel_hours", [17])
    reel_minutes = s.get("reel_minutes", [0])
    platforms = s.get("platforms", [])
    cat_idx = s.get("category_pointer", 0) % len(state.CATEGORIES)
    next_cat = state.CATEGORIES[cat_idx]
    posts = s.get("posts", [])

    lines = [
        f"Status: {'ACTIVE' if enabled else 'PAUSED'}",
        f"Image schedule: {', '.join(f'{h:02d}:{m:02d}' for h, m in zip(img_hours, img_minutes))} ({tz})",
        f"Reel schedule:  {', '.join(f'{h:02d}:{m:02d}' for h, m in zip(reel_hours, reel_minutes))} ({tz})",
        f"Platforms: {', '.join(platforms) if platforms else 'none'}",
        f"Next category: {next_cat.replace('_', ' ')}",
        f"Total posts: {len(posts)}",
    ]

    if posts:
        recent = posts[-3:]
        lines.append("\nRecent posts:")
        for p in reversed(recent):
            ptype = p.get("post_type", "image")
            lines.append(f"  - [{ptype}] [{p['category'].replace('_', ' ')}] {p['title']} ({p['created_at'][:16]})")

    if scheduler:
        jobs = scheduler.get_jobs()
        fire_times = [j.next_run_time for j in jobs if j.next_run_time]
        if fire_times:
            next_run = min(fire_times)
            lines.append(f"\nNext fire: {next_run.strftime('%Y-%m-%d %H:%M %Z')}")

    return "\n".join(lines)


def update_config(
    image_hours: list[int] | None = None,
    image_minutes: list[int] | None = None,
    reel_hours: list[int] | None = None,
    reel_minutes: list[int] | None = None,
    timezone: str | None = None,
    platforms: list[str] | None = None,
) -> str:
    """Update scheduler configuration."""
    s = state.load()
    changes = []

    if image_hours is not None:
        s["image_hours"] = image_hours
        if image_minutes is None:
            s["image_minutes"] = [0] * len(image_hours)
        changes.append(f"image_hours={image_hours}")

    if image_minutes is not None:
        s["image_minutes"] = image_minutes
        changes.append(f"image_minutes={image_minutes}")

    if reel_hours is not None:
        s["reel_hours"] = reel_hours
        if reel_minutes is None:
            s["reel_minutes"] = [0] * len(reel_hours)
        changes.append(f"reel_hours={reel_hours}")

    if reel_minutes is not None:
        s["reel_minutes"] = reel_minutes
        changes.append(f"reel_minutes={reel_minutes}")

    if timezone is not None:
        s["timezone"] = timezone
        changes.append(f"timezone={timezone}")

    if platforms is not None:
        s["platforms"] = platforms
        changes.append(f"platforms={platforms}")

    state.save(s)
    _rebuild_jobs()
    return f"Config updated: {', '.join(changes)}" if changes else "No changes made."
