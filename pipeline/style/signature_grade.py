"""
Signature grade for the Royal channel.

Competitor reference ("Palace Insider") burns a subtle signature into ALL
footage: a hint of chromatic aberration (RGB-split edges) plus fine film
grain / sparkle. That combination reads as "premium archival leak" without
screaming "effect".

Design goals:
- Subtle, not cartoonish: 1-2 px red/blue offsets at 1080p, light temporal
  grain.
- Resolution-independent: the shift is scaled from the frame height so 720p
  and 1080p sources get the same perceived split.
- Cheap: rgbashift + noise only, both slice-threaded, no warping or blurs.
- Composable: the returned string is a plain -vf fragment the render engine
  splices into its existing grade chain.
"""

from __future__ import annotations

import os
import shlex
import subprocess

# Shift targets ~1.5 px at 1080p; scale linearly with frame height so the
# look is resolution-independent. Kept tiny on purpose — anything above ~3 px
# at 1080p starts to read as broken/cartoonish.
_SHIFT_PER_1080P = 1.5

# Fine, lively grain (temporal-only, like the other looks use `allf=t+u`).
# Slightly below the "noise_soft" look (12) so it stays a signature, not a
# texture.
_DEFAULT_GRAIN = 9


def _shift_px(height: int) -> int:
    """Red/blue offset in px for a given frame height (min 1)."""
    return max(1, int(round(_SHIFT_PER_1080P * height / 1080.0)))


def grade_filter(height: int = 1080, grain: int = _DEFAULT_GRAIN) -> str:
    """Return an ffmpeg -vf filter string for the signature grade.

    Chain: subtle RGB-split edges (red shifted right, blue shifted left,
    smear edges so nothing wraps) + fine temporal film grain.

    Args:
        height: Frame height used to scale the shift (resolution-independent).
        grain:  noise=alls=<grain> strength. 0 disables grain.
    """
    shift = _shift_px(height)
    parts = [f"rgbashift=rh={shift}:rv=0:gh=0:gv=0:bh=-{shift}:bv=0:edge=0"]
    if grain and grain > 0:
        parts.append(f"noise=alls={int(grain)}:allf=t")
    return ",".join(parts)


from style.watermark import watermark_filter


def preview(input_path: str, out_path: str, seconds: float = 3.0,
            width: int = 1280, height: int = 720,
            badge_path: str | None = None, badge_margin: int = 24,
            badge_px: int = 140) -> str:
    """Render a quick visual-check clip of the signature grade.

    Args:
        input_path:   Still image or video to grade.
        out_path:     Output MP4 path.
        seconds:      Clip length.
        width/height: Output resolution.
        badge_path:  Optional badge PNG (from watermark.make_badge) to burn
                     into the top-right, exactly as the final render does.

    Returns the output path. Raises RuntimeError if ffmpeg fails.
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"preview input not found: {input_path}")

    graded = (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
              f"crop={width}:{height},{grade_filter(height=height)}")
    if badge_path:
        vf = (f"[0:v]{graded}[g];"
              + watermark_filter(badge_path, margin=badge_margin,
                                 badge_px=badge_px, main_label="[g]"))
    else:
        vf = graded

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-loop", "1", "-framerate", "30", "-i", input_path,
        "-vf", vf,
        "-t", str(seconds),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "ffmpeg preview failed:\n$ " + shlex.join(cmd) + "\n" + proc.stderr)
    return out_path
