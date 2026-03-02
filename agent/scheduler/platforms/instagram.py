"""Instagram posting via Meta Graph API."""

import logging
import os
import time

import httpx

log = logging.getLogger(__name__)

GRAPH_API = "https://graph.facebook.com/v21.0"
ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
ACCOUNT_ID = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")


def is_configured() -> bool:
    return bool(ACCESS_TOKEN and ACCOUNT_ID and PUBLIC_BASE_URL)


def publish(post_id: str, caption: str) -> dict[str, str]:
    """Publish an image to Instagram.

    The image must already be saved at POSTS_DIR/{post_id}.png and
    be accessible at PUBLIC_BASE_URL/posts/{post_id}.png.

    Returns {"status": "ok", "media_id": "..."} or {"status": "error", "detail": "..."}.
    """
    if not is_configured():
        return {"status": "skipped", "detail": "Instagram not configured"}

    image_url = f"{PUBLIC_BASE_URL}/posts/{post_id}.png"

    # Step 1: Create media container
    try:
        resp = httpx.post(
            f"{GRAPH_API}/{ACCOUNT_ID}/media",
            params={
                "image_url": image_url,
                "caption": caption,
                "access_token": ACCESS_TOKEN,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        container_id = resp.json()["id"]
        log.info("IG container created: %s", container_id)
    except (httpx.HTTPError, KeyError) as e:
        log.error("IG container creation failed: %s", e)
        return {"status": "error", "detail": str(e)}

    # Step 2: Poll container until ready
    for _ in range(20):
        try:
            status_resp = httpx.get(
                f"{GRAPH_API}/{container_id}",
                params={"fields": "status_code", "access_token": ACCESS_TOKEN},
                timeout=10.0,
            )
            status = status_resp.json().get("status_code")
            if status == "FINISHED":
                break
            if status == "ERROR":
                error_msg = status_resp.json().get("status", "Unknown error")
                return {"status": "error", "detail": f"Container error: {error_msg}"}
        except httpx.HTTPError:
            pass
        time.sleep(3)
    else:
        return {"status": "error", "detail": "Container processing timed out"}

    # Step 3: Publish
    try:
        pub_resp = httpx.post(
            f"{GRAPH_API}/{ACCOUNT_ID}/media_publish",
            params={
                "creation_id": container_id,
                "access_token": ACCESS_TOKEN,
            },
            timeout=30.0,
        )
        pub_resp.raise_for_status()
        media_id = pub_resp.json()["id"]
        log.info("IG published: %s", media_id)
        return {"status": "ok", "media_id": media_id}
    except (httpx.HTTPError, KeyError) as e:
        log.error("IG publish failed: %s", e)
        return {"status": "error", "detail": str(e)}
