"""TikTok posting via Content Posting API."""

import logging
import os

import httpx

log = logging.getLogger(__name__)

TIKTOK_API = "https://open.tiktokapis.com"
ACCESS_TOKEN = os.environ.get("TIKTOK_ACCESS_TOKEN", "")


def is_configured() -> bool:
    return bool(ACCESS_TOKEN)


def publish(image_path: str, caption: str) -> dict[str, str]:
    """Publish a photo post to TikTok.

    Returns {"status": "ok", "publish_id": "..."} or {"status": "error", "detail": "..."}.
    """
    if not is_configured():
        return {"status": "skipped", "detail": "TikTok not configured"}

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    # Read image bytes
    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
    except OSError as e:
        return {"status": "error", "detail": f"Cannot read image: {e}"}

    # Step 1: Initialize photo upload
    init_payload = {
        "post_info": {
            "title": caption[:150],
            "privacy_level": "PUBLIC_TO_EVERYONE",
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "media_type": "PHOTO",
            "photo_images": [{"image_type": "PNG"}],
        },
    }

    try:
        init_resp = httpx.post(
            f"{TIKTOK_API}/v2/post/publish/inbox/video/init/",
            json=init_payload,
            headers=headers,
            timeout=30.0,
        )
        init_resp.raise_for_status()
        init_data = init_resp.json().get("data", {})
        publish_id = init_data.get("publish_id", "")
        upload_url = init_data.get("upload_url", "")

        if not upload_url:
            return {
                "status": "error",
                "detail": f"No upload URL returned: {init_resp.text[:200]}",
            }
        log.info("TikTok upload initialized: %s", publish_id)
    except (httpx.HTTPError, KeyError) as e:
        log.error("TikTok init failed: %s", e)
        return {"status": "error", "detail": str(e)}

    # Step 2: Upload image binary
    try:
        upload_headers = {
            "Content-Type": "image/png",
            "Content-Length": str(len(image_bytes)),
        }
        upload_resp = httpx.put(
            upload_url,
            content=image_bytes,
            headers=upload_headers,
            timeout=60.0,
        )
        upload_resp.raise_for_status()
        log.info("TikTok image uploaded for publish_id: %s", publish_id)
        return {"status": "ok", "publish_id": publish_id}
    except httpx.HTTPError as e:
        log.error("TikTok upload failed: %s", e)
        return {"status": "error", "detail": str(e)}
