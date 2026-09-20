"""Scan competitor clips for title-card style frames (big bold text on solid
color) and print which files to delete. Uses edge-density + solid-color ratio,
no OCR needed."""
import os, glob, sys, subprocess, tempfile
import numpy as np
import cv2

CLIPS_DIR = (
    "C:\\Users\\ninja\\Downloads\\X Colab Automation\\Royal\\"
    "Video 3 (Charles LOCKS Harry Out on Elizabeth's Death Anniversary "
    "\u2014 No Meeting, No Mercy, No Return!)\\assets_fresh\\clips"
)


def mid_frame(path):
    """Extract a frame at ~50% of the clip into a tempfile PNG and return an array."""
    d = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True)
    try:
        dur = float((d.stdout or "0").strip() or 0)
    except ValueError:
        return None
    if dur <= 0:
        return None
    t = dur / 2.0
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    r = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
         "-vf", "scale=640:-2", tmp.name, "-loglevel", "error"],
        capture_output=True)
    if r.returncode != 0 or not os.path.exists(tmp.name):
        return None
    img = cv2.imread(tmp.name)
    try: os.unlink(tmp.name)
    except OSError: pass
    return img


def is_title_card(img):
    """Return True if the frame reads as a title card / lower-third overlay:
    - dominant near-solid color region (dark or light), AND
    - very high horizontal-edge density from bold text.
    """
    if img is None:
        return False
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    # 1. Solid-color ratio: pixels either very dark (<30) or very light (>225)
    dark = float((gray < 30).sum()) / (h * w)
    light = float((gray > 225).sum()) / (h * w)
    solid = dark + light
    # 2. Edge density from Canny — text has lots of edges
    edges = cv2.Canny(gray, 100, 200)
    edge_ratio = float(edges.sum() > 0) if edges is None else float((edges > 0).mean())
    # 3. Standard deviation of pixel intensities: title cards have bimodal
    # distribution (bg + text) so std is moderate but flat photo/scene has
    # much richer histogram.
    return solid > 0.28 and edge_ratio > 0.05


def main():
    clips = sorted(glob.glob(os.path.join(CLIPS_DIR, "comp_*.mp4")))
    bad = []
    for i, p in enumerate(clips):
        img = mid_frame(p)
        if is_title_card(img):
            bad.append(p)
            print(f"  TITLE-CARD  {os.path.basename(p)}")
        if (i + 1) % 100 == 0:
            print(f"  scanned {i+1}/{len(clips)}")
    print(f"\n{len(bad)} title-card clips out of {len(clips)}")
    # Write list of files to remove
    out = os.path.join(CLIPS_DIR, "_title_cards_to_remove.txt")
    with open(out, "w", encoding="utf-8") as f:
        for p in bad: f.write(p + "\n")
    print(f"list -> {out}")


if __name__ == "__main__":
    main()
