"""Fresh, script-aware asset acquisition.

Reads a script (or its SRT), pulls a Serper.dev image search for each named
subject AND each key scene phrase in the script, downloads the results in
parallel, and drops them into per-entity subfolders inside <video>/assets_fresh/
so the semantic matcher gets tight per-scene coverage instead of a generic
person pool.

Also downloads a competitor YouTube video and slices it into 1.3-3.0s clips
matched to the shot-detection profile.

Usage:
  python fresh_assets.py --script "<VID>/script.txt" \
      --assets-dir "<VID>/assets_fresh" \
      [--competitor-video URL] \
      [--images-per-query 25]
"""
from __future__ import annotations
import argparse, hashlib, io, json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import requests

SERPER_KEY = os.environ.get("SERPER_API_KEY", "28890f9421ea0ccff876e66fb8ec00d938927cd7")
SERPER_URL = "https://google.serper.dev/images"

# Entities the Royal niche cares about — extend as new characters appear.
NEG = "-spaniel -dog -breed -cavalier -puppy -cartoon -illustration -painting -art -game -vector -clipart -toy"

# Each entity: (search query with disambiguation, list of narration regexes)
KNOWN_ENTITIES = {
    "meghan_markle":     (f"Meghan Markle Duchess of Sussex royal {NEG}",
                          [r"Meghan Markle", r"Meghan\b", r"Duchess of Sussex"]),
    "prince_harry":      (f"Prince Harry Duke of Sussex British royal {NEG}",
                          [r"Prince Harry", r"\bHarry\b(?! Styles| Potter)", r"Duke of Sussex"]),
    "princess_diana":    (f"Princess Diana of Wales British royal 1990s {NEG}",
                          [r"Princess Diana", r"\bDiana\b(?! Ross)", r"Princess of Wales"]),
    "king_charles":      (f"King Charles III British monarch coronation portrait {NEG}",
                          [r"King Charles", r"Charles III"]),
    "queen_camilla":     (f"Queen Camilla British royal consort portrait {NEG}",
                          [r"Queen Camilla", r"Camilla"]),
    "queen_elizabeth":   (f"Queen Elizabeth II British monarch portrait Buckingham {NEG}",
                          [r"Queen Elizabeth", r"Elizabeth II",
                           r"The (?:late )?Queen", r"Her Majesty"]),
    "prince_philip":     (f"Prince Philip Duke of Edinburgh British royal {NEG}",
                          [r"Prince Philip", r"Duke of Edinburgh"]),
    "prince_william":    (f"Prince William Prince of Wales British royal {NEG}",
                          [r"Prince William", r"William\b"]),
    "princess_catherine":(f"Princess Catherine Kate Middleton British royal {NEG}",
                          [r"Princess Catherine", r"Kate Middleton", r"Catherine\b"]),
    "princess_anne":     (f"Princess Anne Princess Royal British {NEG}",
                          [r"Princess Anne", r"Princess Royal"]),
    "prince_george":     (f"Prince George of Wales royal {NEG}", [r"Prince George"]),
    "princess_charlotte":(f"Princess Charlotte of Wales royal {NEG}", [r"Princess Charlotte"]),
    "prince_louis":      (f"Prince Louis of Wales royal {NEG}", [r"Prince Louis"]),
    "prince_edward":     (f"Prince Edward Duke of Edinburgh British royal portrait {NEG}",
                          [r"Prince Edward", r"\bEdward\b(?! VIII| VII)", r"Duke of Edinburgh"]),
    # Beckhams — recurring "Cotswolds set" adjacent to the Sussexes.
    "david_beckham":     (f"David Beckham British footballer portrait {NEG}",
                          [r"David Beckham", r"\bBeckham(?!s)\b"]),
    "victoria_beckham":  (f"Victoria Beckham British fashion designer portrait {NEG}",
                          [r"Victoria Beckham", r"\bPosh Spice\b"]),
    # Sussex children — recurring in custody/return storylines.
    "prince_archie":     (f"Prince Archie son Harry Meghan Sussex {NEG}",
                          [r"Prince Archie", r"\bArchie\b(?! Bunker)"]),
    "princess_lilibet":  (f"Princess Lilibet daughter Harry Meghan Sussex {NEG}",
                          [r"Princess Lilibet", r"\bLilibet\b", r"\bLili\b"]),
}
# Broader scene queries drawn from repeated proper-noun phrases in a script.
SCENE_KEYWORDS_FALLBACK = [
    "Diana Award gala",
    "Kensington Palace",
    "Montecito California Sussex",
    "Raffles London Old War Office",
    "royal charity gala evening",
    "British charity trustees meeting",
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121"
HEADERS = {"User-Agent": UA}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def scan_script_entities(script_text: str) -> list[tuple[str, str, int]]:
    """Return (entity_key, search_query, mention_count) for entities the script actually mentions."""
    hits = []
    for key, val in KNOWN_ENTITIES.items():
        # Backward compat: value can be either a plain list of regexes or a
        # (query, [regexes]) tuple. Tuple form carries the disambiguated Serper
        # query so 'King Charles' does not return spaniel breed photos.
        if isinstance(val, tuple):
            query, pats = val
        else:
            pats = val
            query = pats[0].replace("\\b", "").replace("(?! Ross)", "").replace("(?! Styles| Potter)", "")
        count = sum(len(re.findall(p, script_text)) for p in pats)
        if count > 0:
            hits.append((key, query, count))
    hits.sort(key=lambda t: -t[2])
    return hits


# --- face detection for entity-image filtering ------------------------------
_face_cascade = None
def _load_face_cascade():
    """Lazy-load Haar cascade for frontal-face detection. Skips filtering if
    OpenCV or the cascade file isn't available."""
    global _face_cascade
    if _face_cascade is not None:
        return _face_cascade
    try:
        import cv2
        path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        if os.path.exists(path):
            _face_cascade = cv2.CascadeClassifier(path)
        else:
            _face_cascade = False
    except Exception:
        _face_cascade = False
    return _face_cascade

def image_has_face(path):
    """True if a frontal face is detected in the image. Falls back to True when
    the cascade isn't available so we never reject on missing tools."""
    cascade = _load_face_cascade()
    if not cascade:
        return True
    try:
        import cv2
        im = cv2.imread(str(path))
        if im is None: return True
        gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        # Down-sample huge images so detection is quick
        h, w = gray.shape[:2]
        if max(h, w) > 1000:
            scale = 1000.0 / max(h, w)
            gray = cv2.resize(gray, (int(w * scale), int(h * scale)))
        faces = cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=4,
                                         minSize=(80, 80))
        return len(faces) > 0
    except Exception:
        return True


def extract_scene_phrases(script_text: str, top_n: int = 10) -> list[str]:
    """Pick recurring multi-word proper-noun phrases as scene queries."""
    counter: dict[str, int] = {}
    for m in re.finditer(r"\b(?:[A-Z][a-zA-Z]+(?:\s+(?:of|the|de)?\s*)?){2,4}\b", script_text):
        s = m.group(0).strip()
        if len(s.split()) < 2:
            continue
        counter[s] = counter.get(s, 0) + 1
    top = sorted(counter.items(), key=lambda x: -x[1])[:top_n]
    return [k for k, _ in top if _ >= 2]


def serper_images(query: str, want: int = 25, page: int = 1) -> list[dict]:
    """Call Serper.dev images with retries — a single DNS blip must not kill the fetch."""
    last_err = None
    for attempt in range(5):
        try:
            r = requests.post(SERPER_URL,
                              headers={"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"},
                              json={"q": query, "num": min(100, want), "page": page},
                              timeout=30)
            if r.status_code == 429:
                time.sleep(4.0 * (attempt + 1)); continue
            if not r.ok:
                print(f"  [serper] {query!r}: HTTP {r.status_code}", flush=True)
                return []
            return r.json().get("images", [])[:want]
        except Exception as e:
            last_err = e
            time.sleep(2.0 + attempt * 2.0)
    print(f"  [serper] {query!r}: gave up after 5 attempts ({last_err})", flush=True)
    return []


def _looks_like_stock_watermark(url: str, source: str) -> bool:
    junk = ("gettyimages", "alamy", "shutterstock", "istockphoto",
            "dreamstime", "123rf", "depositphotos", "adobestock",
            "bigstockphoto", "watermark", "stockphoto")
    b = (url + " " + (source or "")).lower()
    return any(j in b for j in junk)


def _query_slug(query: str) -> str:
    """Compact snake_case slug from a Serper query — becomes filename prefix so
    each downloaded image carries its query as tokens. Kept short (<= 4 words,
    32 chars) to leave room for idx+md5 without hitting Windows path limits."""
    # Strip the -NEG exclusion suffix — those aren't topic words.
    q = re.sub(r"\s+-\S+", " ", query).lower()
    parts = [w for w in re.findall(r"[a-z]{3,}", q)
             if w not in {"royal", "british", "the", "and", "with", "for"}]
    return "_".join(parts[:4])[:32] or "img"


def download_one(item: dict, out_dir: Path, idx: int, slug: str = "") -> tuple[str, dict]:
    from PIL import Image
    url = item.get("imageUrl") or ""
    w0, h0 = item.get("imageWidth", 0), item.get("imageHeight", 0)
    if not url or _looks_like_stock_watermark(url, item.get("source", "")):
        return "skip_stock", {"url": url}
    if w0 and h0 and min(w0, h0) < 720:
        return "skip_small", {"url": url, "w": w0, "h": h0}
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        if not r.ok or len(r.content) < 60000:
            return "http_err", {"url": url, "code": r.status_code, "bytes": len(r.content)}
        data = r.content
        try:
            with Image.open(io.BytesIO(data)) as im:
                im.verify()
        except Exception as e:
            return "bad_image", {"url": url, "err": str(e)}
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
            fmt = (im.format or "jpeg").lower()
        if min(w, h) < 720:
            return "skip_small_actual", {"url": url, "w": w, "h": h}
        ext = {"jpeg": "jpg", "jpg": "jpg", "png": "png", "webp": "webp"}.get(fmt, "jpg")
        md5 = hashlib.md5(data).hexdigest()
        # Query slug in the filename gives the semantic matcher real tokens to
        # score on — "soho_farmhouse_0001_abc.jpg" tokenises to
        # ["soho","farmhouse"] which sync-locks the script line about the venue.
        stem = f"{slug}_{idx:04d}_{md5[:10]}" if slug else f"{idx:04d}_{md5[:10]}"
        p = out_dir / f"{stem}.{ext}"
        p.write_bytes(data)
        return "ok", {"file": str(p), "w": w, "h": h, "md5": md5}
    except Exception as e:
        return "exc", {"url": url, "err": str(e)[:200]}


def fetch_for_query(query: str, out_dir: Path, want: int, seen_md5: set,
                    require_face: bool = False) -> int:
    """Fetch until `want` unique images landed. When require_face is on (entity
    folders), images without a detected frontal face are dropped."""
    out_dir.mkdir(parents=True, exist_ok=True)
    kept = 0
    idx = 0
    slug = _query_slug(query)
    # Serper pages 1-3 for wider net after face-reject cull.
    for page in (1, 2, 3):
        items = serper_images(query, want=want * 3, page=page)
        if not items:
            break
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {pool.submit(download_one, it, out_dir, idx + i, slug): i for i, it in enumerate(items)}
            for fu in as_completed(futs):
                status, info = fu.result()
                idx += 1
                if status != "ok":
                    continue
                md5 = info["md5"]
                if md5 in seen_md5:
                    Path(info["file"]).unlink(missing_ok=True)
                    continue
                # Entity folders: reject anything that isn't a portrait of a person.
                if require_face and not image_has_face(info["file"]):
                    Path(info["file"]).unlink(missing_ok=True)
                    continue
                seen_md5.add(md5)
                kept += 1
                if kept >= want:
                    return kept
        if kept >= want:
            break
    return kept


def fetch_images(script_text: str, assets_dir: Path, per_query: int) -> None:
    entities = scan_script_entities(script_text)
    scene_phrases = extract_scene_phrases(script_text, top_n=12) or SCENE_KEYWORDS_FALLBACK
    print(f"[fresh] {len(entities)} entities in script: "
          + ", ".join(f"{k}({c})" for k, _, c in entities))
    print(f"[fresh] {len(scene_phrases)} scene queries: {scene_phrases[:5]}...")

    imgs_root = assets_dir / "images"
    seen: set = set()

    # Per-entity image folders — REQUIRE a detectable frontal face so we never
    # ship spaniel photos when the narration says 'King Charles'.
    for key, display, count in entities:
        target = per_query if count < 8 else int(per_query * 1.5)
        kept = fetch_for_query(display, imgs_root / key, target, seen, require_face=True)
        print(f"  [+] {key}: {kept} images ({display!r})")

    # Scene / context folder — non-entity B-roll for "no named subject" moments.
    # Also face-required so we don't land video-game characters or cartoons in
    # the pool. Add royal / British context to every scene query.
    scene_dir = imgs_root / "scene"
    scene_dir.mkdir(exist_ok=True)
    for i, phrase in enumerate(scene_phrases):
        q = f"{phrase} British royal {NEG}"
        kept = fetch_for_query(q, scene_dir, max(8, per_query // 2), seen,
                               require_face=True)
        print(f"  [+] scene[{i}] {phrase!r}: {kept} images")


def slice_competitor_clips(competitor_mp4: Path, clips_dir: Path,
                           min_s: float = 3.5, max_s: float = 6.0) -> int:
    """Shot-detect competitor video, then cut 1.5-3.0s excerpts around each detected scene."""
    from scenedetect import open_video, SceneManager
    from scenedetect.detectors import ContentDetector
    video = open_video(str(competitor_mp4))
    sm = SceneManager()
    sm.add_detector(ContentDetector(threshold=27.0, min_scene_len=15))
    sm.detect_scenes(video, show_progress=False)
    scenes = sm.get_scene_list()
    print(f"[fresh] {len(scenes)} shots in competitor video.")
    clips_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    margin = 0.15
    for i, (a, b) in enumerate(scenes):
        s = a.get_seconds() + margin
        e = min(b.get_seconds() - margin, s + max_s)
        if e - s < min_s:
            continue
        out = clips_dir / f"comp_{i:04d}.mp4"
        if out.exists() and out.stat().st_size > 20000:
            written += 1
            continue
        r = subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{s:.3f}", "-i", str(competitor_mp4),
             "-t", f"{e - s:.3f}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             # KEEP audio so RULE 34 (cold-open intro) can extract it from the
             # first-picked sliced clip. AAC at 128 k is transparent for the
             # 1.5-3 s spoken word snippet a shot slice carries.
             "-c:a", "aac", "-b:a", "128k",
             "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080",
             "-r", "30", str(out)],
            capture_output=True, text=True)
        if r.returncode == 0 and out.exists() and out.stat().st_size > 20000:
            written += 1
    print(f"[fresh] wrote {written} competitor clips into {clips_dir}")
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True)
    ap.add_argument("--assets-dir", required=True)
    ap.add_argument("--competitor-video", help="Path to already-downloaded competitor mp4")
    ap.add_argument("--images-per-query", type=int, default=30)
    ap.add_argument("--skip-images", action="store_true")
    ap.add_argument("--skip-clips", action="store_true")
    args = ap.parse_args()

    script_text = Path(args.script).read_text(encoding="utf-8-sig")
    assets = Path(args.assets_dir)
    assets.mkdir(parents=True, exist_ok=True)

    if not args.skip_images:
        fetch_images(script_text, assets, per_query=args.images_per_query)

    if args.competitor_video and not args.skip_clips:
        p = Path(args.competitor_video)
        if p.exists():
            slice_competitor_clips(p, assets / "clips")
        else:
            print(f"[fresh] WARN: competitor mp4 not found: {p}")


if __name__ == "__main__":
    main()
