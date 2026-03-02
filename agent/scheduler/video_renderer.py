"""Render a Reel video from a LaTeX-compiled PNG + sound effect via ffmpeg."""

import logging
import os
import shutil
import subprocess
import tempfile

import httpx

log = logging.getLogger(__name__)

# Instagram Reels: 1080x1920 (9:16)
REEL_W, REEL_H = 1080, 1920
BG_COLOR = "1a1a2e"

POSTS_DIR = os.environ.get("POSTS_DIR", "/app/data/posts")
SOUND_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "bgm.mp3")

COMPILE_URL = os.environ.get("COMPILE_URL", "https://compile.useoctree.com")
COMPILE_JWT = os.environ.get("COMPILE_JWT_TOKEN", "") or os.environ.get(
    "SUPABASE_SERVICE_ROLE_KEY", ""
)

# Duration settings (seconds)
EQUATION_DURATION = 5
CTA_DURATION = 3
TOTAL_DURATION = EQUATION_DURATION + CTA_DURATION


def _compile_cta_frame() -> str:
    """Compile a 'Try useoctree.com' LaTeX frame, return path to PNG."""
    doc = (
        "\\documentclass[border=40pt]{standalone}\n"
        "\\usepackage[dvipsnames]{xcolor}\n"
        "\\usepackage{varwidth}\n"
        "\n"
        "\\begin{document}\n"
        "\\begin{varwidth}{480pt}\n"
        "\\centering\n"
        "\\pagecolor[HTML]{1a1a2e}\n"
        "\\color{white}\n"
        "\n"
        "{\\fontsize{42}{50}\\selectfont\\bfseries Try}\\par\n"
        "\\vspace{20pt}\n"
        "{\\fontsize{48}{58}\\selectfont\\bfseries\\color[HTML]{e94560} useoctree.com}\\par\n"
        "\n"
        "\\end{varwidth}\n"
        "\\end{document}\n"
    )

    headers = {"Content-Type": "application/json"}
    if COMPILE_JWT:
        headers["Authorization"] = f"Bearer {COMPILE_JWT}"

    resp = httpx.post(
        f"{COMPILE_URL}/compile",
        json={"files": [{"path": "main.tex", "content": doc}], "projectId": "scheduler-cta"},
        headers=headers,
        timeout=30.0,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"CTA LaTeX compile failed: {resp.text[:200]}")

    pdf_tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    pdf_tmp.write(resp.content)
    pdf_tmp.close()

    png_prefix = pdf_tmp.name.replace(".pdf", "")
    subprocess.run(
        ["pdftoppm", "-png", "-r", "300", "-singlefile", pdf_tmp.name, png_prefix],
        check=True, capture_output=True, timeout=15,
    )
    os.unlink(pdf_tmp.name)
    return f"{png_prefix}.png"


def render_video(post_id: str, equation_png: str) -> str:
    """Create a 1080x1920 Reel video: equation image + CTA frame + sound effect.

    Returns path to the .mp4 file.
    """
    os.makedirs(POSTS_DIR, exist_ok=True)
    out_path = os.path.join(POSTS_DIR, f"{post_id}.mp4")

    # Compile the CTA "Try useoctree.com" frame
    log.info("Compiling CTA frame...")
    cta_png = _compile_cta_frame()

    tmpdir = tempfile.mkdtemp(prefix="reel_")
    try:
        # Pad equation image to 1080x1920 with dark background
        eq_padded = os.path.join(tmpdir, "eq.png")
        subprocess.run([
            "ffmpeg", "-y",
            "-i", equation_png,
            "-vf", (
                f"scale={REEL_W}:-1:force_original_aspect_ratio=decrease,"
                f"pad={REEL_W}:{REEL_H}:(ow-iw)/2:(oh-ih)/2:color=#{BG_COLOR}"
            ),
            eq_padded,
        ], check=True, capture_output=True, timeout=30)

        # Pad CTA image to 1080x1920
        cta_padded = os.path.join(tmpdir, "cta.png")
        subprocess.run([
            "ffmpeg", "-y",
            "-i", cta_png,
            "-vf", (
                f"scale={REEL_W}:-1:force_original_aspect_ratio=decrease,"
                f"pad={REEL_W}:{REEL_H}:(ow-iw)/2:(oh-ih)/2:color=#{BG_COLOR}"
            ),
            cta_padded,
        ], check=True, capture_output=True, timeout=30)

        # Create video segments from still images
        eq_vid = os.path.join(tmpdir, "eq.mp4")
        subprocess.run([
            "ffmpeg", "-y",
            "-loop", "1", "-i", eq_padded,
            "-t", str(EQUATION_DURATION),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-r", "30",
            eq_vid,
        ], check=True, capture_output=True, timeout=30)

        cta_vid = os.path.join(tmpdir, "cta.mp4")
        subprocess.run([
            "ffmpeg", "-y",
            "-loop", "1", "-i", cta_padded,
            "-t", str(CTA_DURATION),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-r", "30",
            cta_vid,
        ], check=True, capture_output=True, timeout=30)

        # Concatenate equation + CTA segments
        concat_list = os.path.join(tmpdir, "concat.txt")
        with open(concat_list, "w") as f:
            f.write(f"file '{eq_vid}'\nfile '{cta_vid}'\n")

        concat_vid = os.path.join(tmpdir, "concat.mp4")
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", concat_list,
            "-c", "copy",
            concat_vid,
        ], check=True, capture_output=True, timeout=30)

        # Add audio track (trim to video length)
        audio = SOUND_PATH
        if not os.path.exists(audio):
            log.warning("Sound file not found at %s, creating video without audio", audio)
            shutil.move(concat_vid, out_path)
        else:
            subprocess.run([
                "ffmpeg", "-y",
                "-i", concat_vid,
                "-i", audio,
                "-t", str(TOTAL_DURATION),
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-map", "0:v:0", "-map", "1:a:0",
                "-shortest",
                out_path,
            ], check=True, capture_output=True, timeout=30)

        log.info("Rendered video: %s", out_path)
        return out_path

    finally:
        # Cleanup temp files
        shutil.rmtree(tmpdir, ignore_errors=True)
        try:
            os.unlink(cta_png)
        except OSError:
            pass
