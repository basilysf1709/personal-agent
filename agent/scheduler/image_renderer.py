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

    y = MARGIN

    # -- Category label --
    cat_font = _get_font("bold", 24)
    cat_label = category.replace("_", " ").upper()
    draw.text((MARGIN, y), cat_label, fill=accent_rgb, font=cat_font)
    y += 40

    # -- Accent line --
    draw.line([(MARGIN, y), (MARGIN + 120, y)], fill=accent_rgb, width=4)
    y += 30

    # -- Title --
    title_font = _get_font("bold", 52)
    for line in _wrap_text(title, title_font, TEXT_WIDTH):
        draw.text((MARGIN, y), line, fill=text_rgb, font=title_font)
        y += 62
    y += 20

    # -- LaTeX equation (if present) --
    if latex:
        eq_img = _compile_latex_to_png(latex)
        if eq_img:
            # Scale to fit width with padding
            max_eq_w = TEXT_WIDTH - 40
            max_eq_h = 250
            eq_img.thumbnail((max_eq_w, max_eq_h), Image.LANCZOS)
            eq_x = MARGIN + (TEXT_WIDTH - eq_img.width) // 2
            # Draw semi-transparent background box
            box_pad = 20
            draw.rounded_rectangle(
                [
                    eq_x - box_pad,
                    y - box_pad,
                    eq_x + eq_img.width + box_pad,
                    y + eq_img.height + box_pad,
                ],
                radius=12,
                fill=(*_hex_to_rgb(bg_top), 180),
            )
            img.paste(eq_img, (eq_x, y), eq_img if eq_img.mode == "RGBA" else None)
            y += eq_img.height + 40

    # -- Body text --
    body_font = _get_font("regular", 34)
    body_lines = _wrap_text(body, body_font, TEXT_WIDTH)
    for line in body_lines:
        if y > HEIGHT - 200:
            break
        draw.text((MARGIN, y), line, fill=text_rgb, font=body_font)
        y += 44
    y += 20

    # -- Code block (if present) --
    if code and y < HEIGHT - 200:
        mono_font = _get_font("mono", 26)
        code_lines = code.strip().split("\n")[:15]  # Max 15 lines
        block_h = len(code_lines) * 34 + 40
        available = HEIGHT - y - 160
        if block_h > available:
            code_lines = code_lines[: max(3, available // 34)]
            block_h = len(code_lines) * 34 + 40

        # Code background
        draw.rounded_rectangle(
            [MARGIN - 10, y, WIDTH - MARGIN + 10, y + block_h],
            radius=12,
            fill=(0, 0, 0, 200),
        )
        if code_language:
            lang_font = _get_font("mono", 20)
            draw.text(
                (MARGIN + 10, y + 8),
                code_language.upper(),
                fill=accent_rgb,
                font=lang_font,
            )
            y += 30
        else:
            y += 15

        for cl in code_lines:
            draw.text(
                (MARGIN + 10, y + 5), cl[:80], fill=(200, 200, 200), font=mono_font
            )
            y += 34
        y += 30

    # -- Hashtags at bottom --
    if hashtags:
        tag_font = _get_font("regular", 26)
        tag_str = "  ".join(f"#{t}" for t in hashtags[:5])
        tag_y = HEIGHT - MARGIN - 30
        draw.text((MARGIN, tag_y), tag_str, fill=accent_rgb, font=tag_font)

    # -- Watermark / brand --
    brand_font = _get_font("bold", 22)
    draw.text(
        (WIDTH - MARGIN - 10, HEIGHT - MARGIN + 5),
        "@iqbalyusuf.dev",
        fill=(*text_rgb, 120),
        font=brand_font,
        anchor="ra",
    )

    img = img.convert("RGB")
    img.save(out_path, "PNG", optimize=True)
    log.info("Rendered image: %s", out_path)
    return out_path
