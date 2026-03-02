"""Test script for the content scheduler pipeline.

Tests each layer independently:
1. Platform configuration check
2. Content generation (Claude API)
3. Image rendering (local)
4. Full dry-run post cycle
"""

import json
import os
import sys
import tempfile

# Load .env
from dotenv import load_dotenv

load_dotenv()

# Make agent importable
sys.path.insert(0, os.path.dirname(__file__))

# Override POSTS_DIR and STATE_PATH to use temp dirs for testing
TEST_DIR = tempfile.mkdtemp(prefix="scheduler_test_")
os.environ["POSTS_DIR"] = os.path.join(TEST_DIR, "posts")
os.environ["SCHEDULER_STATE_PATH"] = os.path.join(TEST_DIR, "state.json")

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
SKIP = "\033[93mSKIP\033[0m"
BOLD = "\033[1m"
RESET = "\033[0m"


def header(title: str):
    print(f"\n{BOLD}{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}{RESET}\n")


# ── Test 1: Platform Configuration ──────────────────────────
header("Test 1: Platform Configuration")

from agent.scheduler.platforms import instagram, tiktok

ig_configured = instagram.is_configured()
tk_configured = tiktok.is_configured()

print(f"  Instagram configured: {'Yes' if ig_configured else 'No'}")
if ig_configured:
    print(f"    - ACCESS_TOKEN: {'***' + instagram.ACCESS_TOKEN[-6:]}")
    print(f"    - ACCOUNT_ID:   {instagram.ACCOUNT_ID}")
    print(f"    - BASE_URL:     {instagram.PUBLIC_BASE_URL}")
    print(f"  [{PASS}] Instagram")
else:
    missing = []
    if not instagram.ACCESS_TOKEN:
        missing.append("INSTAGRAM_ACCESS_TOKEN")
    if not instagram.ACCOUNT_ID:
        missing.append("INSTAGRAM_ACCOUNT_ID")
    if not instagram.PUBLIC_BASE_URL:
        missing.append("PUBLIC_BASE_URL")
    print(f"  [{SKIP}] Instagram - Missing env vars: {', '.join(missing)}")

print()
print(f"  TikTok configured:   {'Yes' if tk_configured else 'No'}")
if tk_configured:
    print(f"    - ACCESS_TOKEN: {'***' + tiktok.ACCESS_TOKEN[-6:]}")
    print(f"  [{PASS}] TikTok")
else:
    print(f"  [{SKIP}] TikTok - Missing env var: TIKTOK_ACCESS_TOKEN")


# ── Test 2: State Management ────────────────────────────────
header("Test 2: State Management")

from agent.scheduler import state

try:
    s = state.load()
    print(f"  State loaded: {json.dumps({k: v for k, v in s.items() if k != 'posts'}, indent=4)}")
    cat = state.next_category(s)
    print(f"  Next category: {cat}")
    print(f"  [{PASS}] State management")
except Exception as e:
    print(f"  [{FAIL}] State management: {e}")


# ── Test 3: Content Generation ──────────────────────────────
header("Test 3: Content Generation (Claude API)")

from agent.scheduler.content_generator import generate_content

try:
    content = generate_content("coding_tips", [])
    print(f"  Title:         {content['title']}")
    print(f"  Body:          {content['body'][:100]}...")
    print(f"  Code:          {'Yes' if content.get('code') else 'No'}")
    print(f"  Code language: {content.get('code_language', 'N/A')}")
    print(f"  Hashtags:      {content.get('hashtags', [])}")
    print(f"  Caption:       {content.get('caption', '')[:80]}...")
    print(f"  [{PASS}] Content generation")
except Exception as e:
    print(f"  [{FAIL}] Content generation: {e}")
    content = None


# ── Test 4: Image Rendering ─────────────────────────────────
header("Test 4: Image Rendering")

from agent.scheduler.image_renderer import render_image

try:
    test_content = content or {
        "title": "Test: Python List Comprehension",
        "body": "List comprehensions provide a concise way to create lists.\nThey can replace map/filter patterns.",
        "code": "squares = [x**2 for x in range(10)]\neven = [x for x in squares if x % 2 == 0]",
        "code_language": "Python",
        "hashtags": ["python", "coding", "programming", "dev", "tips"],
    }

    image_path = render_image(
        post_id="test-001",
        category="coding_tips",
        title=test_content["title"],
        body=test_content["body"],
        latex=test_content.get("latex"),
        code=test_content.get("code"),
        code_language=test_content.get("code_language"),
        hashtags=test_content.get("hashtags"),
    )

    file_size = os.path.getsize(image_path)
    from PIL import Image

    img = Image.open(image_path)

    print(f"  Image path:    {image_path}")
    print(f"  Dimensions:    {img.size[0]}x{img.size[1]}")
    print(f"  File size:     {file_size / 1024:.1f} KB")
    print(f"  [{PASS}] Image rendering")

    # Open the image for visual inspection
    print(f"\n  Opening image for preview...")
    os.system(f'open "{image_path}"')

except Exception as e:
    print(f"  [{FAIL}] Image rendering: {e}")
    import traceback
    traceback.print_exc()


# ── Test 5: Full Post Cycle (Dry Run) ───────────────────────
header("Test 5: Full Post Cycle (Dry Run)")

print("  This will run the full pipeline but platform posting will be")
print(f"  skipped if tokens aren't configured.\n")

from agent.scheduler.engine import run_post_cycle

try:
    summary = run_post_cycle()
    print(f"  Result:\n")
    for line in summary.split("\n"):
        print(f"    {line}")
    print(f"\n  [{PASS}] Full post cycle")
except Exception as e:
    print(f"  [{FAIL}] Full post cycle: {e}")
    import traceback
    traceback.print_exc()


# ── Summary ─────────────────────────────────────────────────
header("Summary")
print(f"  Test output dir: {TEST_DIR}")
print(f"  You can inspect generated images in: {os.environ['POSTS_DIR']}")
print()
