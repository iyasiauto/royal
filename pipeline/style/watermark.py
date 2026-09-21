"""
Channel watermark for the Royal channel.

Competitor reference ("Palace Insider") burns a small circular channel badge
into the TOP-RIGHT of every frame. This module:

- :func:`make_badge` bakes the badge PNG once per video into the work dir
  (not per segment).
- :func:`watermark_filter` returns a filtergraph fragment that overlays the
  badge top-right with a margin on every frame.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

# Palette: deep navy disc, thin gold ring, white serif type.
_NAVY = (13, 27, 54, 255)        # dark navy
_NAVY_EDGE = (9, 20, 42, 255)    # slightly darker rim for depth
_GOLD = (212, 175, 55, 255)      # thin gold ring
_WHITE = (245, 243, 235, 255)    # warm white text

_DEFAULT_NAME = "ROYAL INSIDER"
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
)


def _serif_font(px: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if os.path.isfile(path):
            return ImageFont.truetype(path, px)
    # Deterministic fallback; bitmap font, fixed rendering.
    return ImageFont.load_default(size=px)


def _split_two_lines(name: str) -> tuple[str, str]:
    """Balance the channel name across two lines for the badge."""
    words = name.split()
    if len(words) <= 1:
        return name, ""
    # Greedy: fill line 1 until adding the next word makes line 2 longer.
    best = None
    for cut in range(1, len(words)):
        line1 = " ".join(words[:cut])
        line2 = " ".join(words[cut:])
        score = abs(len(line1) - len(line2))
        if best is None or score < best[0]:
            best = (score, line1, line2)
    return best[1], best[2]


def make_badge(channel_name: str = _DEFAULT_NAME, out_path: str = "badge.png",
               size: int = 200) -> str:
    """Generate a circular channel badge PNG with an alpha channel.

    Dark navy disc, thin gold ring, channel name in white serif centered on
    one or two lines. Fully deterministic: identical inputs produce identical
    bytes.

    Args:
        channel_name: Text on the badge (e.g. "ROYAL INSIDER").
        out_path:     Where to write the RGBA PNG.
        size:         Badge diameter in px (square canvas).

    Returns the output path.
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = cy = size / 2.0
    r = size / 2.0 - 1

    # Navy disc with a subtly darker rim for depth.
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_NAVY_EDGE)
    inner = r - max(2, size * 0.02)
    draw.ellipse([cx - inner, cy - inner, cx + inner, cy + inner], fill=_NAVY)

    # Thin gold ring.
    ring_w = max(2, int(round(size * 0.018)))
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=_GOLD, width=ring_w)
    # Faint inner gold hairline for a premium feel.
    hair = r - ring_w - max(3, size * 0.02)
    draw.ellipse([cx - hair, cy - hair, cx + hair, cy + hair],
                 outline=_GOLD[:3] + (90,), width=1)

    # Channel name, white serif, centered on one or two lines.
    line1, line2 = _split_two_lines(channel_name.strip() or _DEFAULT_NAME)
    lines = [line1] if not line2 else [line1, line2]

    def fit(lines_, px):
        font = _serif_font(px)
        widths = [draw.textlength(t, font=font) for t in lines_]
        return font, max(widths)

    # Fit the longest line inside ~72% of the disc diameter.
    target_w = size * 0.72
    px = max(8, int(size * 0.20))
    font, widest = fit(lines, px)
    while widest > target_w and px > 8:
        px -= 1
        font, widest = fit(lines, px)

    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    total_h = line_h * len(lines)
    y = cy - total_h / 2.0
    for text in lines:
        w = draw.textlength(text, font=font)
        draw.text((cx - w / 2.0, y), text, font=font, fill=_WHITE)
        y += line_h

    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


def _escape_movie_path(path: str) -> str:
    """Escape a file path for the ffmpeg movie= filter argument."""
    return "".join(
        ("\\" + ch) if ch in "\\':,;[]" else ch for ch in path)


def watermark_filter(badge_path: str, margin: int = 24,
                     badge_px: int = 140, main_label: str = "[0:v]") -> str:
    """Return a filtergraph fragment overlaying the badge top-right.

    Uses the ``movie`` filter so the badge is self-contained — the render
    engine only needs the main video as its ffmpeg input, and the fragment
    references the badge path directly. The badge is scaled to ``badge_px``
    (square, ~140 px on 1080p) and pinned to
    ``overlay=W-w-<margin>:<margin>`` — top-right on every frame (the
    single-frame badge is held for the whole stream by overlay).

    Compose with the rest of the graph via ``;``, e.g.::

        vf = (f"[0:v]{grade_chain}[g];"
              + watermark_filter(badge, main_label="[g]"))

    Args:
        badge_path: Path to the badge PNG from :func:`make_badge`.
        margin:     Margin in px from the top and right edges.
        badge_px:   Displayed badge size in px (square).
        main_label: Filtergraph label carrying the main video stream.
    """
    escaped = _escape_movie_path(badge_path)
    return (
        f"movie={escaped},scale={badge_px}:{badge_px}:flags=lanczos[wm];"
        f"{main_label}[wm]overlay=x='W-w-{margin}':y='{margin}'"
        f":format=yuv420[vwm]"
    )
