"""
Pool-merge helper for Video 6+ (RULE 24).

Copies images and clips from every prior Royal video into a new video's
assets_fresh/ with a source-video prefix on every filename so that files
with the same original name (e.g. two videos' scene/img_007.jpg) never
overwrite. Only entities actually mentioned in the target script get
copied — keeps the pool relevant, not bloated.

Usage:
    python pool_merge.py --target "<full-path-to-new-Video-N-folder>"

Or pass just the video number to auto-resolve the folder from Royal/:
    python pool_merge.py --video 8

The target folder must contain a script.txt before this runs.
"""
from __future__ import annotations
import argparse
import re
import shutil
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

ROYAL = Path(r"C:\Users\ninja\Downloads\X Colab Automation\Royal")
# User moved finished videos out to D: to free up C: — check that archive
# first, then fall back to the legacy Royal/Done/ dir if it exists.
DONE  = Path(r"D:\Royal Data\Royal Videos Done")
DONE_LEGACY = ROYAL / "Done"

# --------------------- 1. Pick relevant entities from script --------------------
ENTITY_TRIGGERS = {
    "meghan_markle":    [r"Meghan Markle", r"\bMeghan\b", r"Duchess of Sussex"],
    "prince_harry":     [r"Prince Harry", r"\bHarry\b(?! Styles| Potter)", r"Duke of Sussex"],
    "prince_william":   [r"Prince William", r"\bWilliam\b(?! Shakespeare)"],
    "princess_catherine":[r"Princess Catherine", r"\bKate\b(?! Middleton\b)|Kate Middleton", r"Princess of Wales(?! Diana)"],
    "king_charles":     [r"King Charles", r"Charles III"],
    "queen_camilla":    [r"Queen Camilla", r"\bCamilla\b"],
    "princess_diana":   [r"Princess Diana", r"\bDiana\b(?! Ross)"],
    "queen_elizabeth":  [r"Queen Elizabeth", r"Elizabeth II"],
    "david_beckham":    [r"David Beckham", r"\bBeckham(?!s)\b"],
    "victoria_beckham": [r"Victoria Beckham", r"\bPosh Spice\b"],
    "prince_archie":    [r"Prince Archie", r"\bArchie\b(?! Bunker)"],
    "princess_lilibet": [r"Princess Lilibet", r"\bLilibet\b", r"\bLili\b"],
    "princess_anne":    [r"Princess Anne", r"Princess Royal"],
}

def entities_in_script(script_path: Path) -> list[str]:
    text = script_path.read_text(encoding="utf-8", errors="replace")
    hits = []
    for ent, patterns in ENTITY_TRIGGERS.items():
        for pat in patterns:
            if re.search(pat, text):
                hits.append(ent)
                break
    return hits

# --------------------- 2. Discover source Done videos ---------------------------
def source_videos(target: Path) -> list[Path]:
    """Return every prior Video-N folder we can pool from: Done/, plus any
    Video-N sitting at the Royal/ root that isn't the current target. Sorted
    by video number so the resulting pool is deterministic."""
    out: list[Path] = []
    seen = {target.resolve()}
    for root in (DONE, DONE_LEGACY, ROYAL):
        if not root.is_dir():
            continue
        for d in root.iterdir():
            if (d.is_dir()
                and d.name.lower().startswith("video ")
                and (d / "assets_fresh").exists()
                and d.resolve() not in seen):
                out.append(d)
                seen.add(d.resolve())
    def _num(p: Path) -> int:
        m = re.match(r"Video (\d+)", p.name)
        return int(m.group(1)) if m else 999
    return sorted(out, key=_num)


def resolve_target(args) -> Path:
    """CLI -> Path. Accept either an absolute --target folder or --video N
    (auto-glob for `Royal/Video N (...)` — a single match is required)."""
    if args.target:
        return Path(args.target)
    if args.video:
        matches = sorted(p for p in ROYAL.iterdir()
                         if p.is_dir() and re.match(rf"Video {args.video}\b", p.name))
        if not matches:
            sys.exit(f"[merge] no Royal/Video {args.video} (…) folder found")
        if len(matches) > 1:
            sys.exit(f"[merge] more than one Royal/Video {args.video} (…) folder — "
                     f"pass --target explicitly")
        return matches[0]
    sys.exit("[merge] need --target <path> or --video <N>")

# --------------------- 3. Copy with prefixed names ------------------------------
def copy_prefixed(src: Path, dst_dir: Path, prefix) -> int:
    """prefix can be a plain string (name = "{prefix}_{src.name}") or a tuple
    ("__RENAME__", "explicit_dst_name.ext") to force an exact destination name."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    if isinstance(prefix, tuple) and prefix[0] == "__RENAME__":
        dst = dst_dir / prefix[1]
    else:
        dst = dst_dir / f"{prefix}_{src.name}"
    if dst.exists() and dst.stat().st_size == src.stat().st_size:
        return 0  # already merged
    shutil.copy2(src, dst)
    return 1

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--target", help="Full path to the new Video N (...) folder")
    ap.add_argument("--video", type=int,
                    help="Video number — auto-resolves Royal/Video N (...)")
    args = ap.parse_args()

    target = resolve_target(args)
    script = target / "script.txt"
    if not script.exists():
        sys.exit(f"[merge] target has no script.txt: {script}")
    print(f"[merge] target: {target}")

    entities = entities_in_script(script)
    print(f"[merge] script entities: {entities}")

    videos = source_videos(target)
    print(f"[merge] source videos: {[v.name for v in videos]}")

    # Always include 'scene' as a b-roll bucket
    wanted_entities = set(entities) | {"scene"}

    total_imgs = 0
    total_clips = 0
    tasks: list[tuple[Path, Path, str]] = []

    _fresh = re.compile(r"^comp_(\d+\.mp4)$")  # matches comp_0000.mp4 only

    for v in videos:
        # Short prefix per source video — e.g. Video 2 -> v2, Video 3 -> v3
        m = re.match(r"Video (\d+)", v.name)
        if not m:
            continue
        vid_num = m.group(1)
        prefix = f"v{vid_num}"

        # Images: only copy the entity folders we care about
        img_root = v / "assets_fresh" / "images"
        if img_root.is_dir():
            for ent_dir in img_root.iterdir():
                if not ent_dir.is_dir() or ent_dir.name not in wanted_entities:
                    continue
                dst_ent = target / "assets_fresh" / "images" / ent_dir.name
                for f in ent_dir.iterdir():
                    if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                        tasks.append((f, dst_ent, prefix))

        # Clips: pool them all (competitor clips are topic-relevant royal footage).
        # RULE 14: render_engine detects competitor clips by filename prefix
        # "comp_" — so the merged name MUST still start with comp_. Store as
        # comp_pv{N}_<orig>.mp4 (comp_ prefix preserved, source video identifiable).
        # SKIP clips already re-pooled from earlier merges (comp_pv*.mp4) so
        # names don't nest as comp_pv6_pv2_XXXX.mp4 across generations.
        clip_root = v / "assets_fresh" / "clips"
        if clip_root.is_dir():
            dst_clips = target / "assets_fresh" / "clips"
            for f in clip_root.iterdir():
                m2 = _fresh.match(f.name)
                if not m2:
                    continue  # skip pool clips already prefixed (comp_pv*), and non-comp files
                tasks.append((f, dst_clips, ("__RENAME__", f"comp_pv{vid_num}_{m2.group(1)}")))

    print(f"[merge] {len(tasks)} files to copy (may include already-merged)")

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(copy_prefixed, s, d, p) for s, d, p in tasks]
        for i, fut in enumerate(as_completed(futs)):
            n = fut.result()
            if n:
                if "images" in str(tasks[i][1]):
                    total_imgs += n
                else:
                    total_clips += n

    print(f"[merge] copied {total_imgs} images and {total_clips} clips into {target}/assets_fresh")

    # RULE 30: physical purge of branded / disclaimer / sponsor early slices.
    # Every YouTube channel opens with ~15-30 s of channel-branded material,
    # and the shot-slicer catches those as comp_0000..0014 for every prior
    # competitor. Purge them here so they never enter the semantic index.
    ac = target / "assets_fresh" / "clips"
    pat_early = re.compile(r"^comp_(?:pv\d+_)?0*(?:[0-9]|1[0-4])\.mp4$")
    if ac.is_dir():
        purged = 0
        for f in ac.iterdir():
            if pat_early.match(f.name):
                try: f.unlink(); purged += 1
                except OSError: pass
        if purged:
            print(f"[merge] RULE 30 purged {purged} branded/disclaimer early-slice clips")

    # RULE 35: cap each entity folder at 500 images and the scene folder at
    # 4000. Beyond that the semantic matcher can't meaningfully rank picks and
    # Stage 2 asset validation (Laplacian blur + watermark scan on every image)
    # thrashes RAM. Random-sample per entity keeps variety without the bloat.
    import random
    ai_root = target / "assets_fresh" / "images"
    if ai_root.is_dir():
        for ent_dir in ai_root.iterdir():
            if not ent_dir.is_dir():
                continue
            cap = 4000 if ent_dir.name == "scene" else 500
            files = [f for f in ent_dir.iterdir()
                     if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
            if len(files) <= cap:
                continue
            random.seed(hash(ent_dir.name))
            keep = set(random.sample([f.name for f in files], cap))
            dropped = 0
            for f in files:
                if f.name not in keep:
                    try: f.unlink(); dropped += 1
                    except OSError: pass
            print(f"[merge] RULE 35 capped {ent_dir.name} at {cap} "
                  f"(dropped {dropped})")

    # RULE 31: aspect-ratio purge of scene images that are almost certainly
    # banners, tweet screenshots, infographics or promo cards — those show up
    # in graphic cards as "wrong content" and read as ours if used.
    scene = target / "assets_fresh" / "images" / "scene"
    if scene.is_dir():
        try:
            from PIL import Image
        except ImportError:
            Image = None
        if Image is not None:
            purged_ar = 0
            for f in list(scene.iterdir()):
                if f.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
                    continue
                try:
                    with Image.open(f) as im:
                        w, h = im.size
                    ar = w / max(1, h)
                    if ar < 0.75 or ar > 2.5:
                        f.unlink(); purged_ar += 1
                except Exception:
                    try: f.unlink(); purged_ar += 1
                    except OSError: pass
            if purged_ar:
                print(f"[merge] RULE 31 purged {purged_ar} banner/graphic scene images")

    # Summary
    ai_root = target / "assets_fresh" / "images"
    if ai_root.is_dir():
        print("\n[merge] final image counts by entity:")
        for e in sorted(ai_root.iterdir()):
            if e.is_dir():
                cnt = sum(1 for _ in e.glob("*"))
                print(f"    {e.name}: {cnt}")
    ac_root = target / "assets_fresh" / "clips"
    if ac_root.is_dir():
        n = sum(1 for _ in ac_root.glob("*.mp4"))
        print(f"[merge] final clip count: {n}")

if __name__ == "__main__":
    main()
