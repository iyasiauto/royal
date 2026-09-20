"""Two-pass vidstab stabilization for every clip in royal_clips.

The source news/archival clips carry handheld shake that the render's scale-up
amplifies (measured dx_sd 0.5-3.0 px vs 0.01 px for the Ken Burns images). This
removes it once, in place, so every render that reuses a clip is already smooth.

Idempotent: a clip whose companion marker (<name>.stab) is newer than the clip
is skipped. Run after populate, before render.
"""
import os, sys, subprocess, tempfile, shutil, argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from kb_jitter import measure

CLIPS_DIR = Path(r"C:\Users\ninja\Downloads\X Colab Automation\Royal\royal_clips")
SMOOTH_SD = 0.15   # already-smooth clips (sd below this) are left untouched

def _probe_ok(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return r.returncode == 0 and bool(r.stdout.strip()) and os.path.getsize(path) > 10000

def stabilize_one(clip: Path, shakiness=10, smoothing=30, zoom=5):
    marker = clip.with_suffix(clip.suffix + ".stab")
    if marker.exists() and marker.stat().st_mtime >= clip.stat().st_mtime:
        return clip.name, "cached"
    if not _probe_ok(clip):
        return clip.name, "invalid-source"
    # Skip clips that are already smooth — stabilizing them risks fighting real
    # camera motion and making them worse.
    before = measure(str(clip))
    before_sd = max(before["dx_sd"], before["dy_sd"]) if before else 0.0
    if before and before_sd < SMOOTH_SD:
        marker.write_text("already-smooth")
        return clip.name, "already-smooth"
    # Work in a private temp dir so the .trf transform file is a bare filename
    # (the ffmpeg filter parser mishandles Windows drive-colon paths).
    tmp = tempfile.mkdtemp(prefix="stab_")
    try:
        # Pass 1: detect
        p1 = subprocess.run(
            ["ffmpeg", "-y", "-i", str(clip),
             "-vf", "vidstabdetect=shakiness=%d:accuracy=15:result=transforms.trf" % shakiness,
             "-f", "null", "-"],
            cwd=tmp, capture_output=True, text=True)
        if p1.returncode != 0 or not os.path.exists(os.path.join(tmp, "transforms.trf")):
            return clip.name, "detect-failed"
        # Pass 2: transform. Fixed crop zoom (optzoom OFF — adaptive zoom re-introduces
        # per-frame scale jitter) and no sharpening (adds high-freq noise the eye reads
        # as shake). Measured: dx_sd 0.245 -> 0.030 px.
        out_tmp = os.path.join(tmp, "stabilized.mp4")
        vf = ("vidstabtransform=input=transforms.trf:smoothing=%d:zoom=%d:"
              "optzoom=0:interpol=bicubic" % (smoothing, zoom))
        p2 = subprocess.run(
            ["ffmpeg", "-y", "-i", str(clip), "-vf", vf,
             "-c:v", "libx264", "-preset", "fast", "-crf", "18",
             "-c:a", "copy", out_tmp],
            cwd=tmp, capture_output=True, text=True)
        if p2.returncode != 0 or not _probe_ok(out_tmp):
            return clip.name, "transform-failed"
        # Keep the stabilized version only if it actually reduced jitter; otherwise
        # the source had motion vidstab fought — leave the original untouched.
        after = measure(out_tmp)
        after_sd = max(after["dx_sd"], after["dy_sd"]) if after else 9.9
        if after_sd >= before_sd - 0.02:
            marker.write_text(f"kept-original(before={before_sd:.2f} after={after_sd:.2f})")
            return clip.name, f"no-gain({before_sd:.2f}->{after_sd:.2f})"
        shutil.copyfile(out_tmp, clip)
        marker.write_text(f"stabilized({before_sd:.2f}->{after_sd:.2f})")
        return clip.name, f"ok({before_sd:.2f}->{after_sd:.2f})"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips-dir", default=str(CLIPS_DIR))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--shakiness", type=int, default=10)
    ap.add_argument("--smoothing", type=int, default=30)
    ap.add_argument("--zoom", type=int, default=5)
    ap.add_argument("--shaky-max", type=float, default=0.35,
                    help="clips still above this jitter (px sd) are quarantined to _shaky/")
    ap.add_argument("--no-quarantine", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    d = Path(args.clips_dir)
    clips = sorted(d.glob("*.mp4"))
    if args.force:
        for c in clips:
            m = c.with_suffix(c.suffix + ".stab")
            if m.exists(): m.unlink()
    print(f"[stab] {len(clips)} clips, {args.workers} workers")
    stats = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(stabilize_one, c, args.shakiness, args.smoothing, args.zoom): c for c in clips}
        for i, fu in enumerate(as_completed(futs), 1):
            name, status = fu.result()
            stats[status] = stats.get(status, 0) + 1
            if status not in ("cached", "ok") or i % 10 == 0 or i == len(clips):
                print(f"  [{i}/{len(clips)}] {name}: {status}")
    print(f"[stab] done: {stats}")

    # Quarantine clips that are still visibly shaky after the stabilize attempt
    # (source has fast camera motion vidstab can't fix). Moving them out of the
    # pool keeps the render smooth; plenty of clean clips remain.
    if not args.no_quarantine:
        shaky_dir = d / "_shaky"
        moved = 0
        for c in sorted(d.glob("*.mp4")):
            r = measure(str(c))
            if r and max(r["dx_sd"], r["dy_sd"]) > args.shaky_max:
                shaky_dir.mkdir(exist_ok=True)
                dest = shaky_dir / c.name
                c.replace(dest)
                m = c.with_suffix(c.suffix + ".stab")
                if m.exists(): m.unlink()
                moved += 1
        remaining = len(list(d.glob("*.mp4")))
        print(f"[stab] quarantined {moved} still-shaky clips -> _shaky/ ; {remaining} clean clips remain")

if __name__ == "__main__":
    main()
