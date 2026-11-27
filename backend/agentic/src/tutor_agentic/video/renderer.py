"""Renders video slides to MP4 using Pillow (frames) + moviepy (assembly).

Both are pure-Python and run locally without any external service.
If either library is missing, the renderer raises ImportError with an
informative message — the graph node catches this and skips the video block.

Slide layout
------------
Each frame is 1280×720 (720p). The layout is:
  - Coloured header bar at the top (accent blue)
  - Title text in white on the header
  - Body text in dark colour on white background below
  - Page number at the bottom right

The colour scheme respects the platform's design tokens.
"""
from __future__ import annotations

import logging
import textwrap
from pathlib import Path

log = logging.getLogger(__name__)

# Design tokens (matches styles.css)
_BG        = (247, 248, 251)   # --bg
_SURFACE   = (255, 255, 255)   # --surface
_ACCENT    = (29, 78, 216)     # --accent (#1d4ed8)
_ACCENT_TXT= (255, 255, 255)   # --accent-text
_TEXT      = (27, 36, 48)      # --text (#1b2430)
_MUTED     = (75, 87, 103)     # --muted (#4b5767)

W, H        = 1280, 720
HEADER_H    = 110
FOOTER_H    = 40
PADDING     = 48
FPS         = 24


def _get_font(size: int, bold: bool = False):
    """Load a TrueType font if available, fall back to Pillow's built-in."""
    from PIL import ImageFont
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            pass
    return ImageFont.load_default()


def _wrap(text: str, font, draw, max_width: int) -> list[str]:
    """Wrap text to fit within max_width pixels."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] > max_width and current:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def render_slide_to_image(slide, index: int, total: int):
    """Render one Slide to a PIL Image (1280×720)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), color=_SURFACE)
    draw = ImageDraw.Draw(img)

    # Header bar
    draw.rectangle([(0, 0), (W, HEADER_H)], fill=_ACCENT)

    # Title in header
    title_font = _get_font(32, bold=True)
    title_text = slide.title or ""
    # Wrap title if too long
    title_lines = []
    for line in title_text.split("\n"):
        title_lines.extend(_wrap(line, title_font, draw, W - 2 * PADDING) or [line])
    title_lines = title_lines[:2]  # max 2 lines in header
    y = (HEADER_H - len(title_lines) * 40) // 2
    for line in title_lines:
        draw.text((PADDING, y), line, font=title_font, fill=_ACCENT_TXT)
        y += 40

    # Body text area
    body_font = _get_font(26)
    body_text = slide.body or ""
    body_y = HEADER_H + PADDING
    max_body_h = H - HEADER_H - FOOTER_H - 2 * PADDING
    max_w = W - 2 * PADDING
    lines: list[str] = []
    for para in body_text.split("\n\n"):
        for raw_line in para.split("\n"):
            wrapped = _wrap(raw_line.strip(), body_font, draw, max_w)
            lines.extend(wrapped or [""])
        lines.append("")   # paragraph gap

    line_h = 34
    for line in lines:
        if body_y + line_h > H - FOOTER_H - PADDING:
            break
        draw.text((PADDING, body_y), line, font=body_font, fill=_TEXT)
        body_y += line_h

    # Footer: slide counter
    footer_font = _get_font(20)
    counter = f"{index + 1} / {total}"
    bbox = draw.textbbox((0, 0), counter, font=footer_font)
    draw.text(
        (W - PADDING - (bbox[2] - bbox[0]), H - FOOTER_H + 10),
        counter, font=footer_font, fill=_MUTED,
    )

    return img


def render_slides_to_mp4(slides: list, output_path: Path) -> Path:
    """Render a list of Slide objects to an MP4 file.

    Uses Pillow to generate PNG frames, moviepy to assemble.
    Returns the output path.

    Raises
    ------
    ImportError
        If Pillow or moviepy is not installed.
    """
    try:
        from PIL import Image  # noqa: F401 — verify available
        import moviepy.editor as mpy  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            f"Video generation requires Pillow and moviepy: {exc}. "
            "Install with: pip install pillow moviepy"
        ) from exc

    import numpy as np
    import moviepy.editor as mpy

    total = len(slides)
    clips = []

    for i, slide in enumerate(slides):
        img = render_slide_to_image(slide, i, total)
        frame = np.array(img)
        clip = mpy.ImageClip(frame, duration=slide.duration_s)
        clips.append(clip)

    if not clips:
        raise ValueError("No slides to render")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    video = mpy.concatenate_videoclips(clips, method="compose")
    video.write_videofile(
        str(output_path),
        fps=FPS,
        codec="libx264",
        audio=False,
        logger=None,       # suppress moviepy progress bar
    )
    video.close()
    for clip in clips:
        clip.close()

    log.info("Video rendered: %s (%.1fs)", output_path.name, video.duration)
    return output_path
