"""RULE 36 — Auto-generate date/time/location title cards.

When the narration calls out a specific "at 8:46 AM on Monday, September 14,
2026 at Birmingham Airport" beat, showing whatever random pool photo landed
in that segment reads as a wrong shot. Instead, render a memorial-style
title card that repeats what the narrator just said, laid over a blurred
royal image so it still feels like part of the piece.

Reference feel: dark backdrop + big serif headline + red-underlined kicker,
like the "Never Forget / SEPTEMBER 11, 2001" callouts modern documentaries
use for a specific moment in time.
"""
from __future__ import annotations
import os
import re
from typing import List, Tuple, Optional

# ---------------------------------------------------------------- detectors
_TIME_RE = re.compile(
    r"\b(\d{1,2}):(\d{2})\s*(?:a\.?m\.?|p\.?m\.?|AM|PM|A\.M\.|P\.M\.)\b|"
    r"\b(\d{1,2})[:.](\d{2})\s*(?:in the (?:morning|afternoon|evening|night))\b",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"\b(?:(?:Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday)"
    r"(?:\s+(?:morning|afternoon|evening|night))?,?\s+)?"
    r"(?:January|February|March|April|May|June|July|"
    r"August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?"
    r"(?:,\s*\d{4})?",
    re.IGNORECASE,
)
_LOC_HINT = re.compile(
    r"\bat\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,4})\b"
)


def find_callouts(spans) -> List[Tuple[float, float, str, str, str]]:
    """Walk SRT spans and yield (start, end, big_line, small_line, kicker) for
    every span whose text carries a time / date / location beat worth cutting
    to a card for. `spans` is the ScriptTimeline.spans list of (a, b, txt)."""
    out = []
    for a, b, txt in spans:
        s = str(txt)
        time_m = _TIME_RE.search(s)
        date_m = _DATE_RE.search(s)
        loc_m  = _LOC_HINT.search(s)
        if not (time_m or date_m):
            continue

        big = ""
        small = ""
        kicker = ""

        if date_m:
            big = date_m.group(0).strip().rstrip(",")
        if time_m:
            t_txt = time_m.group(0).strip().upper().replace(".", "")
            if big:
                small = t_txt
            else:
                big = t_txt
        if loc_m:
            loc = loc_m.group(1).strip()
            if small:
                # already used slot; append location to the small line
                small = f"{small}  ·  {loc.upper()}"
            else:
                small = loc.upper()
        # Kicker over the headline
        if any(k in s.lower() for k in ("that morning", "the morning", "that evening",
                                        "that afternoon", "that night", "arrival",
                                        "departure", "flight")):
            kicker = "THE MOMENT"
        elif "reported" in s.lower() or "described" in s.lower():
            kicker = "ACCORDING TO THE ACCOUNT"
        else:
            kicker = "ON THE RECORD"

        out.append((float(a), float(b), big.upper(), small, kicker))
    # Dedup identical cards adjacent in time (same headline within 15 s)
    dedup = []
    for c in out:
        if dedup and c[2] == dedup[-1][2] and c[0] - dedup[-1][0] < 15:
            continue
        dedup.append(c)
    return dedup


# ---------------------------------------------------------------- renderer
def render_card(bg_image_path: Optional[str], out_path: str,
                big: str, small: str, kicker: str,
                width: int = 1920, height: int = 1080) -> Optional[str]:
    """Compose the card and write it to out_path. Falls back to a plain dark
    canvas if the backdrop can't be loaded."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    # 1. Background
    canvas = Image.new("RGB", (width, height), (16, 16, 20))
    if bg_image_path and os.path.exists(bg_image_path):
        try:
            with Image.open(bg_image_path) as im:
                im = im.convert("RGB")
                # cover-crop to 16:9
                ar = im.width / max(1, im.height)
                target = width / height
                if ar > target:
                    new_h = im.height
                    new_w = int(new_h * target)
                    x0 = (im.width - new_w) // 2
                    im = im.crop((x0, 0, x0 + new_w, new_h))
                else:
                    new_w = im.width
                    new_h = int(new_w / target)
                    y0 = (im.height - new_h) // 2
                    im = im.crop((0, y0, new_w, y0 + new_h))
                im = im.resize((width, height), Image.LANCZOS)
                # Heavy blur + darken so text pops
                im = im.filter(ImageFilter.GaussianBlur(radius=28))
                dark = Image.new("RGB", (width, height), (0, 0, 0))
                canvas = Image.blend(im, dark, 0.55)
        except Exception:
            pass  # keep the flat dark canvas

    draw = ImageDraw.Draw(canvas, "RGBA")

    # 2. Fonts — fall back to Pillow default if the system font is missing.
    def load(name_candidates, size):
        for name in name_candidates:
            for path in (name,
                         rf"C:\Windows\Fonts\{name}",
                         rf"C:\Windows\Fonts\{name}.ttf"):
                try:
                    return ImageFont.truetype(path, size)
                except (OSError, IOError):
                    continue
        return ImageFont.load_default()

    serif_big = load(["Georgia Bold", "Georgia", "Constantia", "PalatinoLinotype",
                      "Garamond"], 132)
    sans_small = load(["Arial Bold", "Arial", "Helvetica", "SegoeUI"], 42)
    sans_kicker = load(["Arial Bold", "Arial", "SegoeUI"], 34)

    def cx_text(font, text):
        box = draw.textbbox((0, 0), text, font=font)
        return (box[2] - box[0], box[3] - box[1])

    # 3. Kicker with underline (top of the block)
    y_center = height // 2
    if kicker:
        k_w, k_h = cx_text(sans_kicker, kicker)
        k_x = (width - k_w) // 2
        k_y = y_center - 200
        draw.text((k_x, k_y), kicker, font=sans_kicker, fill=(220, 220, 220, 255))
        # Red underline
        line_y = k_y + k_h + 12
        draw.rectangle((width // 2 - 90, line_y,
                        width // 2 + 90, line_y + 4),
                       fill=(210, 40, 40, 255))

    # 4. Big headline (center)
    if big:
        b_w, b_h = cx_text(serif_big, big)
        b_x = (width - b_w) // 2
        b_y = y_center - b_h // 2
        # subtle drop shadow for legibility
        draw.text((b_x + 3, b_y + 3), big, font=serif_big, fill=(0, 0, 0, 180))
        draw.text((b_x, b_y), big, font=serif_big, fill=(240, 240, 240, 255))

    # 5. Small line (below headline)
    if small:
        s_w, s_h = cx_text(sans_small, small)
        s_x = (width - s_w) // 2
        s_y = y_center + 90
        draw.text((s_x, s_y), small, font=sans_small, fill=(200, 200, 200, 255))

    canvas.save(out_path, "JPEG", quality=92)
    return out_path


def build_card_set(script_spans, out_dir: str, backdrops: list) -> list:
    """Render every detected callout and return a list of
    (start, end, path) tuples for build_timeline to consume."""
    os.makedirs(out_dir, exist_ok=True)
    callouts = find_callouts(script_spans)
    result = []
    for i, (a, b, big, small, kicker) in enumerate(callouts):
        bg = backdrops[i % len(backdrops)] if backdrops else None
        out = os.path.join(out_dir, f"datetime_card_{i:03d}.jpg")
        try:
            render_card(bg, out, big, small, kicker)
            result.append((a, b, out))
        except Exception as e:
            print(f"[datetime_cards] card {i} failed: {e}")
    return result
