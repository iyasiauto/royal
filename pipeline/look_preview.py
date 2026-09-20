"""Render one sample image through EVERY named look and save side-by-side
previews so you can pick the effect for a video before committing to a full
render.

Usage:
  python look_preview.py --image "path/to/sample.jpg" [--out "path/to/dir"]

Outputs:
  <out>/preview_<look>.jpg      one preview per look
  <out>/preview_grid.jpg        contact sheet with a caption per tile
"""
from __future__ import annotations
import argparse, os, subprocess, tempfile, textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

import looks as looks_module


W, H = 1920, 1080


def render_still(src: Path, grade: str, out_path: Path):
    """Apply a look's grade to a single image and write a 1920x1080 JPG."""
    fit = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
    vf = f"{fit},{grade}" if grade else fit
    cmd = ["ffmpeg", "-y", "-i", str(src), "-vf", vf,
           "-frames:v", "1", "-q:v", "3", str(out_path), "-loglevel", "error"]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def make_grid(files: list[tuple[str, Path]], out_path: Path, tile_w: int = 720):
    """3-per-row contact sheet with each look's name across the bottom of its tile."""
    tile_h = int(tile_w * H / W)
    cols = 3
    rows = (len(files) + cols - 1) // cols
    pad = 12
    label_h = 44
    sheet_w = cols * tile_w + (cols + 1) * pad
    sheet_h = rows * (tile_h + label_h) + (rows + 1) * pad
    sheet = Image.new("RGB", (sheet_w, sheet_h), (18, 18, 20))
    try:
        font = ImageFont.truetype(
            os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arialbd.ttf"),
            26)
    except Exception:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(sheet)
    for i, (name, path) in enumerate(files):
        r, c = divmod(i, cols)
        x = pad + c * (tile_w + pad)
        y = pad + r * (tile_h + label_h + pad)
        im = Image.open(path).convert("RGB")
        im = im.resize((tile_w, tile_h), Image.LANCZOS)
        sheet.paste(im, (x, y))
        label = name
        bbox = draw.textbbox((0, 0), label, font=font)
        lw = bbox[2] - bbox[0]; lh = bbox[3] - bbox[1]
        draw.rectangle([x, y + tile_h, x + tile_w, y + tile_h + label_h],
                       fill=(28, 28, 32))
        draw.text((x + (tile_w - lw) // 2, y + tile_h + (label_h - lh) // 2 - 4),
                  label, font=font, fill=(240, 240, 245))
    sheet.save(out_path, "JPEG", quality=90)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, help="Source image to preview looks on")
    ap.add_argument("--out", default=None,
                    help="Output directory (default: sibling 'look_previews' folder)")
    ap.add_argument("--only", default=None,
                    help="Comma-separated subset of look names (default: all)")
    args = ap.parse_args()

    src = Path(args.image)
    if not src.exists():
        raise SystemExit(f"image not found: {src}")

    out_dir = Path(args.out) if args.out else src.parent / "look_previews"
    out_dir.mkdir(parents=True, exist_ok=True)

    only = None
    if args.only:
        only = {n.strip() for n in args.only.split(",") if n.strip()}

    names = [n for n in looks_module.names() if not only or n in only]
    files = []
    for name in names:
        spec = looks_module.resolve(name)
        out = out_dir / f"preview_{name}.jpg"
        try:
            render_still(src, spec.get("grade", ""), out)
            files.append((name, out))
            print(f"  [+] {name}  ->  {out.name}")
        except Exception as e:
            print(f"  [-] {name}: {e}")

    grid = out_dir / "preview_grid.jpg"
    if files:
        make_grid(files, grid)
        print(f"\n[preview] grid: {grid}")
    print(f"[preview] {len(files)} looks previewed in {out_dir}")


if __name__ == "__main__":
    main()
