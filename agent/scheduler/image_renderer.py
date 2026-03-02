"""Render content to 1080x1350 portrait images for Instagram/TikTok."""

import logging
import os
import subprocess
import tempfile
import textwrap

import httpx
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

WIDTH, HEIGHT = 1080, 1350
MARGIN = 80
TEXT_WIDTH = WIDTH - 2 * MARGIN

COMPILE_URL = os.environ.get("COMPILE_URL", "https://compile.useoctree.com")
COMPILE_JWT = os.environ.get("COMPILE_JWT_TOKEN", "") or os.environ.get(
    "SUPABASE_SERVICE_ROLE_KEY", ""
)

POSTS_DIR = os.environ.get("POSTS_DIR", "/app/data/posts")

# Category-specific color palettes: (bg_top, bg_bottom, accent, text)
PALETTES: dict[str, tuple[str, str, str, str]] = {
    "math_equations": ("#1a1a2e", "#16213e", "#e94560", "#ffffff"),
    "coding_tips": ("#0d1117", "#161b22", "#58a6ff", "#e6edf3"),
    "science_facts": ("#0f0c29", "#302b63", "#24fe41", "#ffffff"),
    "motivational_quotes": ("#2d1b69", "#11998e", "#f8e71c", "#ffffff"),
    "tech_insights": ("#1b1b2f", "#162447", "#e43f5a", "#ffffff"),
    "algorithm_visualizations": ("#0a0a23", "#1b1b32", "#f5a623", "#ffffff"),
    "physics_concepts": ("#0c0032", "#190061", "#7b2ff7", "#ffffff"),
    "historical_tech_moments": ("#1a1a1a", "#2d2d2d", "#ff6b35", "#ffffff"),
}

# Font paths (DejaVu is installed via Dockerfile)
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]


def _get_font(style: str = "regular", size: int = 36) -> ImageFont.FreeTypeFont:
    """Load a font, falling back to default if not found."""
    idx = {"bold": 0, "regular": 1, "mono": 2}.get(style, 1)
    try:
        return ImageFont.truetype(FONT_PATHS[idx], size)
    except (OSError, IndexError):
        try:
            return ImageFont.truetype(FONT_PATHS[1], size)
        except OSError:
            return ImageFont.load_default()


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _draw_gradient(img: Image.Image, top: str, bottom: str) -> None:
    """Draw a vertical gradient on the image."""
    r1, g1, b1 = _hex_to_rgb(top)
    r2, g2, b2 = _hex_to_rgb(bottom)
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        r = int(r1 + (r2 - r1) * ratio)
        g = int(g1 + (g2 - g1) * ratio)
        b = int(b1 + (b2 - b1) * ratio)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b, 255))


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        # Estimate chars per line, then refine
        avg_char = font.getlength("x")
        chars = max(10, int(max_width / avg_char))
        wrapped = textwrap.wrap(paragraph, width=chars)
        # Refine: if any line is too wide, reduce and re-wrap
        while any(font.getlength(line) > max_width for line in wrapped) and chars > 10:
            chars -= 2
            wrapped = textwrap.wrap(paragraph, width=chars)
        lines.extend(wrapped if wrapped else [""])
    return lines


def _compile_latex_to_png(latex: str) -> Image.Image | None:
    """Compile a LaTeX equation to PNG via the octree compile service."""
    doc = (
        r"\documentclass[preview,border=10pt]{standalone}"
        "\n\\usepackage{amsmath,amssymb,amsfonts}\n"
        r"\usepackage[dvipsnames]{xcolor}"
        "\n\\begin{document}\n"
        r"{\color{white}\Huge" "\n"
        f"$\\displaystyle {latex}$\n"
        "}\\end{document}"
    )

    headers = {"Content-Type": "application/json"}
    if COMPILE_JWT:
        headers["Authorization"] = f"Bearer {COMPILE_JWT}"

    payload = {
        "files": [{"path": "main.tex", "content": doc}],
        "projectId": "scheduler-eq",
    }

    try:
        resp = httpx.post(
            f"{COMPILE_URL}/compile",
            json=payload,
            headers=headers,
            timeout=30.0,
        )
        if resp.status_code != 200:
            log.warning("LaTeX compile failed: %s", resp.text[:200])
            return None
    except httpx.HTTPError as e:
        log.warning("LaTeX compile request failed: %s", e)
        return None

    # PDF bytes -> PNG via pdftoppm
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(resp.content)
        pdf_path = f.name

    png_path = pdf_path.replace(".pdf", "")
    try:
        subprocess.run(
            ["pdftoppm", "-png", "-r", "300", "-singlefile", pdf_path, png_path],
            check=True,
            capture_output=True,
            timeout=15,
        )
        img = Image.open(f"{png_path}.png").convert("RGBA")
        return img
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        log.warning("pdftoppm failed: %s", e)
        return None
    finally:
        for p in [pdf_path, f"{png_path}.png"]:
            try:
                os.unlink(p)
            except OSError:
                pass


def render_image(
    post_id: str,
    category: str,
    title: str,
    body: str,
    latex: str | None = None,
    code: str | None = None,
    code_language: str | None = None,
    hashtags: list[str] | None = None,
) -> str:
    """Render content to a PNG image. Returns the file path."""
    os.makedirs(POSTS_DIR, exist_ok=True)
    out_path = os.path.join(POSTS_DIR, f"{post_id}.png")

    palette = PALETTES.get(category, PALETTES["tech_insights"])
    bg_top, bg_bottom, accent, text_color = palette
    accent_rgb = _hex_to_rgb(accent)
    text_rgb = _hex_to_rgb(text_color)

    img = Image.new("RGBA", (WIDTH, HEIGHT))
    _draw_gradient(img, bg_top, bg_bottom)
    draw = ImageDraw.Draw(img)

    # -- Title (centered, top area) --
    title_font = _get_font("bold", 48)
    title_lines = _wrap_text(title, title_font, TEXT_WIDTH)
    title_y = MARGIN + 60
    for line in title_lines:
        line_w = title_font.getlength(line)
        draw.text(((WIDTH - line_w) / 2, title_y), line, fill=text_rgb, font=title_font)
        title_y += 58

    # -- Accent line under title --
    line_y = title_y + 20
    draw.line([(WIDTH // 2 - 60, line_y), (WIDTH // 2 + 60, line_y)], fill=accent_rgb, width=4)

    # -- LaTeX equation (centered, main focus) --
    eq_img = None
    if latex:
        eq_img = _compile_latex_to_png(latex)
    if eq_img:
        # Scale to fit with generous sizing — this is the hero element
        max_eq_w = TEXT_WIDTH
        max_eq_h = 400
        eq_img.thumbnail((max_eq_w, max_eq_h), Image.LANCZOS)
        eq_x = (WIDTH - eq_img.width) // 2
        eq_y = (HEIGHT - eq_img.height) // 2 - 40
        # Draw semi-transparent background box
        box_pad = 30
        draw.rounded_rectangle(
            [
                eq_x - box_pad,
                eq_y - box_pad,
                eq_x + eq_img.width + box_pad,
                eq_y + eq_img.height + box_pad,
            ],
            radius=16,
            fill=(*_hex_to_rgb(bg_top), 180),
        )
        img.paste(eq_img, (eq_x, eq_y), eq_img if eq_img.mode == "RGBA" else None)

    # -- Body text (one sentence, centered below equation) --
    body_font = _get_font("regular", 30)
    body_lines = _wrap_text(body, body_font, TEXT_WIDTH)
    body_y = (HEIGHT + (eq_img.height if eq_img else 0)) // 2 + 60
    for line in body_lines[:2]:
        line_w = body_font.getlength(line)
        draw.text(((WIDTH - line_w) / 2, body_y), line, fill=(*text_rgb, 200), font=body_font)
        body_y += 40

    # -- "Generated by useoctree.com" --
    gen_font = _get_font("bold", 32)
    gen_text = "Generated by useoctree.com"
    gen_w = gen_font.getlength(gen_text)
    gen_y = HEIGHT - MARGIN - 100
    draw.text(((WIDTH - gen_w) / 2, gen_y), gen_text, fill=accent_rgb, font=gen_font)

    # -- Hashtags at bottom --
    if hashtags:
        tag_font = _get_font("regular", 26)
        tag_str = "  ".join(f"#{t}" for t in hashtags[:5])
        tag_w = tag_font.getlength(tag_str)
        tag_y = HEIGHT - MARGIN - 40
        draw.text(((WIDTH - tag_w) / 2, tag_y), tag_str, fill=(*text_rgb, 150), font=tag_font)

    img = img.convert("RGB")
    img.save(out_path, "PNG", optimize=True)
    log.info("Rendered image: %s", out_path)
    return out_path
