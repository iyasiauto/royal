"""
Framed commentator panel template (editing-style upgrade, workstream F).

Renders expert / commentator / quote clips inside a rounded rectangle with a
glowing white "frost" border, centred on a dark navy background,
picture-in-picture style — matching the "Palace Insider" reference treatment.

This module is self-contained: it pre-renders the static background with PIL
and hands the coordinator an exact ``filter_complex`` string so a segment can
be rendered as::

    ffmpeg -y -loop 1 -framerate 30 -i <panel_bg.png> \
              -ss 0 -t <dur> -i <foreground> \
              -filter_complex "<build_panel_filter(...)>" \
              -map "[vout]" -c:v libx264 ... seg_NNNN.mp4

Inputs:  [0:v] = panel background PNG (looped still)
         [1:v] = foreground (video clip or still image)
Output:  [vout] = 1920x1080 yuv420p frame

Proposed segment-marking scheme (NOT implemented here — the coordinator wires
it into render_engine._render_segment):
  * Timeline marks a segment with ``seg["style"] = "commentator"``.
  * Heuristic candidates to set it in timeline_engine (kept out of this
    module on purpose):
      1. The segment's narration contains a direct quote — e.g. matches
         ``["\u201c\u201d]...{8,}["\u201c\u201d]`` or ``"..."`` — meaning an
         expert/commentator is being quoted, OR
      2. A config-provided explicit list ``COMMENTATOR_SEGMENT_INDEXES``
         (e.g. every "analyst reaction" beat the script-DNA author tags),
      3. Fallback: segment type "clip" whose source filename carries an
         "expert"/"panel" tag from the asset pool.
  * In _render_segment, ``seg.get("style") == "commentator"`` should take
    priority over the RULE 14 grid-card path (which stays for ordinary
    competitor clips).

Aesthetics follow graphic_compositor.py: rounded corners, layered alpha glow
instead of hard boxes, proportions expressed relative to the 1920x1080 grid.
"""

import os
import subprocess

from PIL import Image, ImageDraw, ImageFilter

# --------------------------------------------------------------------------
# Geometry (1920x1080 design grid)
# --------------------------------------------------------------------------
FRAME_W, FRAME_H = 1920, 1080
BG_COLOR = (10, 22, 40)          # dark navy ~#0a1628
BORDER_COLOR = (255, 255, 255)   # crisp inner border, white

PANEL_X, PANEL_Y = 269, 151      # centred: (1920-1382)//2, (1080-778)//2
PANEL_W, PANEL_H = 1382, 778     # ~72% of frame width, 16:9
CORNER_RADIUS = 36
BORDER_WIDTH = 6
# (pad_px, alpha) — layered translucent white rounded rects; alpha rises as
# the pad shrinks, giving a frosted falloff rather than a hard white box.
GLOW_LAYERS = [(64, 10), (48, 16), (32, 26), (16, 40)]
GLOW_BLUR = 18

PANEL_GEOMETRY = {
    "frame": (FRAME_W, FRAME_H),
    "panel": (PANEL_X, PANEL_Y, PANEL_W, PANEL_H),  # (x, y, w, h)
    "corner_radius": CORNER_RADIUS,
    "border_width": BORDER_WIDTH,
    "glow_layers": list(GLOW_LAYERS),
    "glow_blur": GLOW_BLUR,
    "bg_color": BG_COLOR,
    "border_color": BORDER_COLOR,
}


def _scaled_geometry(width, height):
    """Scale the 1920x1080 design grid to another frame size."""
    s = min(width / FRAME_W, height / FRAME_H)
    pw = int(PANEL_W * s) // 2 * 2
    ph = int(PANEL_H * s) // 2 * 2
    px = (int(width) - pw) // 2
    py = (int(height) - ph) // 2
    return {
        "frame": (int(width), int(height)),
        "panel": (px, py, pw, ph),
        "corner_radius": max(4, int(CORNER_RADIUS * s)),
        "border_width": max(2, int(BORDER_WIDTH * s)),
        "glow_layers": [(max(2, int(p * s)), a) for p, a in GLOW_LAYERS],
        "glow_blur": max(2, int(GLOW_BLUR * s)),
        "bg_color": BG_COLOR,
        "border_color": BORDER_COLOR,
    }


def make_panel_background(out_path, width=1920, height=1080):
    """Pre-render the static panel background PNG.

    Dark navy full-frame + frosted white glow halo + crisp white rounded
    border around the (empty) panel slot. The foreground is overlaid exactly
    onto the panel rect afterwards, so the interior of the panel is plain
    navy here (it gets covered).
    """
    g = _scaled_geometry(width, height)
    fw, fh = g["frame"]
    px, py, pw, ph = g["panel"]
    radius = g["corner_radius"]
    bw = g["border_width"]

    img = Image.new("RGBA", (fw, fh), g["bg_color"] + (255,))

    # Subtle vignette for depth: concentric dark rectangles, low alpha.
    vig = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vig)
    steps = 24
    for i in range(steps):
        a = int(46 * (i / steps) ** 2)
        inset = int(min(fw, fh) * 0.5 * (i / steps))
        vd.rectangle([inset, inset, fw - 1 - inset, fh - 1 - inset],
                     outline=(0, 0, 0, a), width=max(2, inset // max(1, steps // 6) + 2))
    img = Image.alpha_composite(img, vig.filter(ImageFilter.GaussianBlur(40)))

    # Frosted glow: layered translucent white rounded rects, blurred together.
    glow = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for pad, alpha in g["glow_layers"]:
        gd.rounded_rectangle(
            [px - pad, py - pad, px + pw + pad - 1, py + ph + pad - 1],
            radius=radius + pad,
            fill=(255, 255, 255, alpha),
        )
    glow = glow.filter(ImageFilter.GaussianBlur(g["glow_blur"]))
    img = Image.alpha_composite(img, glow)

    # Crisp white inner border, drawn just OUTSIDE the foreground slot so the
    # overlaid clip never covers it. Outline straddles the bbox edge, so
    # expand by (bw // 2 + 2) to leave a small navy gap from the clip.
    out = bw // 2 + 2
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [px - out, py - out, px + pw + out - 1, py + ph + out - 1],
        radius=radius + out,
        outline=g["border_color"] + (255,),
        width=bw,
    )

    img.convert("RGB").save(out_path, quality=95)
    return out_path


# --------------------------------------------------------------------------
# ffmpeg filter builder
# --------------------------------------------------------------------------
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")


def _geom_for_filter():
    px, py, pw, ph = PANEL_GEOMETRY["panel"]
    return px, py, pw, ph


def build_panel_filter(fg_kind="video", duration=4.0, fps=30):
    """Return the exact ``-filter_complex`` string for a panel segment.

    fg_kind="video": the clip is centre-cropped (RULE 14 style: top 12% and
        bottom 18% stripped to drop channel logos / burned-in captions), then
        cover-scaled into the panel slot and overlaid.
    fg_kind="image": the still is scaled 1.15x and given a slow horizontal
        drift pan inside the panel (constant 16:9 crop window) so it stays
        alive for the whole segment.
    """
    if duration is None or duration <= 0:
        raise ValueError("duration must be a positive number of seconds")
    px, py, pw, ph = _geom_for_filter()
    dur = float(duration)

    if fg_kind == "video":
        fg_chain = (
            f"[1:v]crop=iw:ih*0.70:0:ih*0.12,"
            f"scale={pw}:{ph}:force_original_aspect_ratio=increase,"
            f"crop={pw}:{ph},setsar=1[fg]"
        )
    elif fg_kind == "image":
        sw, sh = pw + pw // 7 - (pw + pw // 7) % 2, ph + ph // 7 - (ph + ph // 7) % 2
        fg_chain = (
            f"[1:v]scale={sw}:{sh}:force_original_aspect_ratio=increase,"
            f"crop={pw}:{ph}:"
            f"x='(in_w-{pw})*(t/{dur})':"
            f"y='(in_h-{ph})/2',setsar=1[fg]"
        )
    else:
        raise ValueError(f"fg_kind must be 'video' or 'image', got {fg_kind!r}")

    fc = (f"[0:v]format=rgba[bg];"
          f"{fg_chain};"
          f"[bg][fg]overlay={px}:{py}:format=yuv444,format=yuv420p[vout]")
    return fc


def detect_fg_kind(path):
    """Guess 'video' / 'image' from the foreground file extension."""
    ext = os.path.splitext(str(path))[1].lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in IMAGE_EXTS:
        return "image"
    raise ValueError(f"cannot infer foreground kind from {path!r}")


def _trim_white_border(path, workdir):
    """Strip a uniform near-white border baked into postcard-style photos
    (same idea as graphic_compositor.load_photo_trimmed, pure-PIL so this
    module stays dependency-light). Returns the path to use."""
    im = Image.open(path).convert("RGB")
    mask = im.convert("L").point(lambda v: 0 if v > 244 else 255)
    bbox = mask.getbbox()
    if bbox:
        frac = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) / float(im.width * im.height)
        if 0.15 < frac < 0.98:  # real border; protect legit light backgrounds
            im = im.crop(bbox)
            out = os.path.join(workdir, "_panel_fg_trimmed.png")
            im.save(out, quality=95)
            return out
    return path


def render_panel_segment(fg_path, duration, out_path, fps=30, fg_kind=None,
                         bg_path=None, crf=20):
    """Render one commentator-panel segment (libx264). Returns out_path.

    Self-contained helper used by tests / probes. The coordinator's segment
    renderer should instead use build_panel_filter() directly so it can add
    the look grade and fades in the same filter graph.
    """
    if fg_kind is None:
        fg_kind = detect_fg_kind(fg_path)
    duration = float(duration)
    if duration <= 0:
        raise ValueError("duration must be positive")

    workdir = os.path.dirname(os.path.abspath(out_path)) or "."
    os.makedirs(workdir, exist_ok=True)

    if bg_path is None:
        bg_path = os.path.join(workdir, "_panel_bg.png")
        make_panel_background(bg_path)

    fc = build_panel_filter(fg_kind=fg_kind, duration=duration, fps=fps)

    if fg_kind == "video":
        fg_args = ["-ss", "0", "-t", str(duration), "-i", fg_path]
    else:
        fg_path = _trim_white_border(fg_path, workdir)
        n_frames = max(1, int(round(duration * fps)))
        fg_args = ["-loop", "1", "-framerate", str(fps), "-i", fg_path]

    cmd = (["ffmpeg", "-y",
            "-loop", "1", "-framerate", str(fps), "-i", bg_path]
           + fg_args
           + ["-filter_complex", fc,
              "-map", "[vout]",
              "-t", str(duration)]
           + (["-frames:v", str(n_frames)] if fg_kind == "image" else [])
           + ["-c:v", "libx264", "-preset", "veryfast",
              "-crf", str(crf), "-pix_fmt", "yuv420p",
              "-r", str(fps), "-an", out_path])

    res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if res.returncode != 0 or not os.path.exists(out_path):
        tail = (res.stderr or "").strip().splitlines()[-5:]
        raise RuntimeError("panel render failed: " + " | ".join(tail))
    return out_path
