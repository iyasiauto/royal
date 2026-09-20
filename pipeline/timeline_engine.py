"""
Semantic Asset & Dynamic Timeline Engine.

Builds a segment timeline (JSON) that fills the master voiceover duration with a
mix of video clips, curated photographs and generated graphic cards.

All topic-specific content (card captions, keyword-matched clip groups, hook
assets) comes from a topic config dict, so the same engine drives any subject.
"""

import os
import re
import json
import glob
import time
import random
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from graphic_compositor import GraphicCompositor
from semantic_matcher import (AssetIndex, ScriptTimeline, SemanticMatcher,
                              folder_entity, load_tags)

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".m4v")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
DEFAULT_EXCLUDE = ("watermark", "getty", "alamy", "stock")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def get_duration(media_file):
    """Return media duration in seconds, or 0.0 if it cannot be probed."""
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", media_file],
        capture_output=True, text=True)
    try:
        return float(res.stdout.strip())
    except ValueError:
        return 0.0


def _as_dir_list(value):
    """Accept a single path, a list of paths, or an os.pathsep-joined string."""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        dirs = list(value)
    else:
        dirs = value.split(os.pathsep) if os.pathsep in value else [value]
    return [d for d in (p.strip() for p in dirs) if d and os.path.isdir(d)]


class TimelineEngine:
    """Builds a documentary timeline from a pool of clips, photos and grids."""

    def __init__(self, clips_dir, images_dir, grid_dir,
                 topic_assets_dir=None, graphics_dir=None, topic_config=None,
                 opening_lead_s=4.5, hook_end_s=22.5,
                 seg_min_s=4.5, seg_max_s=5.8,
                 clip_cooldown=15, max_images=350, hook_count=7,
                 asset_seed=1515, curate_seed=999, scan_workers=32,
                 semantic=True, script_text=None, voice_manifest=None, srt_path=None,
                 asset_tags=None, entity_boost=6.0,
                 width=1920, height=1080):
        self.clips_dirs = _as_dir_list(clips_dir)
        self.images_dirs = _as_dir_list(images_dir)
        self.grid_dirs = _as_dir_list(grid_dir)
        self.topic_assets_dir = (topic_assets_dir
                                 if topic_assets_dir and os.path.isdir(topic_assets_dir)
                                 else None)
        self.graphics_dir = graphics_dir
        self.cfg = dict(topic_config or {})

        # Backdrop asset libraries for the card styles. Default to the pipeline's
        # own assets/ folder so cards look premium out of the box; override per
        # project via grids_asset_dir / sparkle_asset_dir in the topic config.
        _pkg_assets = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
        self.grids_asset_dir = self.cfg.get("grids_asset_dir",
                                            os.path.join(_pkg_assets, "grids"))
        self.sparkle_asset_dir = self.cfg.get("sparkle_asset_dir",
                                              os.path.join(_pkg_assets, "sparkle-backgrounds"))

        self.opening_lead_s = float(opening_lead_s)
        self.hook_end_s = float(hook_end_s)
        self.seg_min_s = float(seg_min_s)
        self.seg_max_s = float(seg_max_s)
        self.clip_cooldown = int(clip_cooldown)
        self.max_images = int(max_images)
        self.hook_count = int(hook_count)
        self.asset_seed = asset_seed
        self.curate_seed = curate_seed
        self.scan_workers = int(scan_workers)

        self.exclude_keywords = tuple(
            k.lower() for k in self.cfg.get("exclude_keywords", DEFAULT_EXCLUDE))

        # Quality floors. They keep thumbnails and broken downloads out of a
        # documentary, but a legitimately small library must be able to lower
        # them rather than be told nothing was found.
        self.min_image_bytes = int(self.cfg.get("min_image_bytes", 60000))
        self.min_image_px = int(self.cfg.get("min_image_px", 720))
        self.min_clip_bytes = int(self.cfg.get("min_clip_bytes", 200000))

        # Watermark keywords — checked against BOTH filenames and image
        # metadata/EXIF. Images with these in filename are auto-rejected.
        self.watermark_keywords = tuple(
            k.lower() for k in self.cfg.get("watermark_keywords",
            ["gettyimages", "getty", "alamy", "shutterstock", "istockphoto",
             "dreamstime", "123rf", "depositphotos", "adobestock",
             "bigstockphoto", "stockphoto", "watermark"]))

        self.width = int(width)
        self.height = int(height)
        self.semantic = bool(semantic)
        self.script_text = script_text
        self.voice_manifest = voice_manifest
        self.srt_path = srt_path
        self.asset_tags = asset_tags or {}
        self.entity_boost = float(entity_boost)
        self.matcher = None
        self._clip_dur_cache = {}

    def _clip_native_dur(self, path):
        """Duration (s) of a clip, cached. 0.0 if unreadable."""
        if path in self._clip_dur_cache:
            return self._clip_dur_cache[path]
        import subprocess
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, timeout=20)
            d = float(r.stdout.strip())
        except Exception:
            d = 0.0
        self._clip_dur_cache[path] = d
        return d

    def _clip_seg_dur(self, path, slot):
        """How long a clip segment should run: its own footage length (minus a
        small tail so the trim never lands on the last frame), capped at the slot.
        Falls back to the slot if the duration can't be probed."""
        native = self._clip_native_dur(path)
        if native <= 0.3:
            return slot
        return round(max(1.3, min(slot, native - 0.08)), 2)

    # ------------------------------------------------------------- semantics

    def _entity_dirs(self):
        """Directories whose folder name identifies who or what is depicted."""
        pairs = []
        for entity, path in (self.cfg.get("entity_dirs") or {}).items():
            if os.path.isdir(path):
                pairs.append((entity.lower(), path))

        root = self.cfg.get("entity_root")
        if root and os.path.isdir(root):
            skip = {s.lower() for s in self.cfg.get("entity_root_skip", [])}
            owned = {os.path.normcase(os.path.abspath(d))
                     for d in self.clips_dirs + self.images_dirs + self.grid_dirs}
            for name in sorted(os.listdir(root)):
                path = os.path.join(root, name)
                if not os.path.isdir(path) or name.lower() in skip:
                    continue
                if os.path.normcase(os.path.abspath(path)) in owned:
                    continue
                entity = folder_entity(path)
                if entity:
                    pairs.append((entity, path))
        return pairs

    def build_matcher(self, vo_duration, lead):
        """Construct a semantic asset matcher index over the script text."""
        index = AssetIndex()
        default_entity = ((self.cfg.get("default_entity") or "")
                          .lower().replace("_", " ")) or None

        # An asset directory is either a generic pool (label everything with the
        # documentary's own subject) or a subject folder (label by folder name).
        # Getting this wrong collapses every folder into one entity and silently
        # disables folder-based matching, so it is stated explicitly in config.
        declared = self.cfg.get("generic_dirs")
        if declared is None:
            generic = None
        else:
            generic = {os.path.normcase(os.path.abspath(d))
                       for d in _as_dir_list(declared)}

        def label_for(d):
            if generic is None or os.path.normcase(os.path.abspath(d)) in generic:
                return default_entity
            return folder_entity(d) or default_entity

        entity_pairs = self._entity_dirs()
        for entity, path in entity_pairs:
            index.add_dir(path, "image", entity=entity, recursive=True)
            index.add_dir(path, "clip", entity=entity, recursive=True)

        for d in self.images_dirs:
            index.add_dir(d, "image", entity=label_for(d), recursive=True)
        for d in self.clips_dirs:
            index.add_dir(d, "clip", entity=label_for(d), recursive=True)

        applied = index.apply_tags(self.asset_tags)
        index.build_idf()

        if self.srt_path and os.path.exists(self.srt_path):
            script = ScriptTimeline.from_srt(self.srt_path, lead=lead)
            source = f"voiceover SRT file ({os.path.basename(self.srt_path)})"
        elif self.voice_manifest:
            script = ScriptTimeline.from_manifest(self.voice_manifest, lead=lead)
            source = "voiceover manifest (exact chunk timing)"
        elif self.script_text:
            script = ScriptTimeline.from_text(self.script_text, vo_duration, lead=lead)
            source = "proportional estimate from script"
        else:
            log("Semantic matching disabled: no script text, SRT, or voice manifest.")
            return None

        stats = index.stats()
        log(f"Semantic index: {stats['total']} assets "
            f"({stats['images']} images, {stats['clips']} clips), "
            f"{stats['entities']} entities, {stats['describable']} with usable terms.")
        if applied:
            log(f"Applied {applied} tag entries from the asset tags file.")
        log(f"Script alignment: {len(script.spans)} spans from {source}.")

        return SemanticMatcher(index, script, entity_boost=self.entity_boost,
                               cooldown=self.clip_cooldown,
                               entity_cooldown=10,   # wider spacing between
                                                     # same-entity picks (was 4)
                                                     # so Meghan-Meghan-Meghan
                                                     # runs get broken up.
                               default_entity=default_entity)

    # ---------------------------------------------------------------- assets

    def _validate_photo(self, path):
        """Return the path, or a short reason the photo was rejected.

        Checks applied:
        1. File size >= min_image_bytes
        2. Resolution >= min_image_px on both axes
        3. Filename must not contain watermark keywords (gettyimages, alamy, etc.)
        4. Image must not be blurry (Laplacian variance >= 65)
        5. Visual corner watermark banner inspection
        6. Structural integrity (verify + convert)
        """
        try:
            if os.path.getsize(path) < self.min_image_bytes:
                return "too small on disk (<%d bytes)" % self.min_image_bytes

            # Filename watermark check
            fname = os.path.basename(path).lower()
            hit = next((k for k in self.watermark_keywords if k in fname), None)
            if hit:
                return "watermark keyword '%s' in filename" % hit

            with Image.open(path) as im:
                w, h = im.size
                if w < self.min_image_px or h < self.min_image_px:
                    return "below %dpx" % self.min_image_px
                im.verify()

            # Full decode + blur & corner watermark check
            with Image.open(path) as im:
                rgb = im.convert("RGB")

                # Blur & corner watermark detection via numpy
                try:
                    import numpy as np
                    arr = np.array(rgb.convert("L"), dtype=np.float64)
                    h, w = arr.shape

                    # Laplacian blur variance check (low = blurry)
                    lap = (arr[:-2, 1:-1] + arr[2:, 1:-1] +
                           arr[1:-1, :-2] + arr[1:-1, 2:] -
                           4 * arr[1:-1, 1:-1])
                    variance = lap.var()
                    if variance < 65:
                        return "too blurry (laplacian %.1f)" % variance

                    # Corner stock watermark banner detection
                    br = arr[int(h * 0.7):, int(w * 0.55):]
                    bl = arr[int(h * 0.7):, :int(w * 0.45)]
                    for corner in (br, bl):
                        dark_frac = np.mean(corner < 70)
                        text_frac = np.mean(corner > 140)
                        if dark_frac > 0.40 and text_frac > 0.03:
                            return "stock watermark banner detected in corner"
                except ImportError:
                    pass  # numpy not available

            return path
        except Exception as e:
            return "unreadable (%s)" % type(e).__name__

    def _validate_grid(self, path):
        try:
            if os.path.getsize(path) < 4000:
                return None
            with Image.open(path) as im:
                im.verify()
            with Image.open(path) as im:
                im.convert("RGB")
            return path
        except Exception:
            return None

    def _validate_clip(self, path):
        """Return a clip record, or a short reason it was rejected."""
        try:
            if os.path.getsize(path) < self.min_clip_bytes:
                return "too small on disk (<%d bytes)" % self.min_clip_bytes
            name = os.path.basename(path).lower()
            # The raw yt-dlp'd competitor download sits in the clips folder as
            # the shot-slicer's input. Never let it into the intro-clip picker
            # or the timeline — it's a full-length video with the source
            # channel's logo/branding baked in, and playing it native (RULE 11
            # bypasses RULE 14 framing for non-comp_ names) shows that logo on
            # screen.
            if name.startswith("competitor_source"):
                return "competitor source video (slicer input, not a timeline asset)"
            hit = next((k for k in self.exclude_keywords if k in name), None)
            if hit:
                return "excluded by keyword %r" % hit
            wm_hit = next((k for k in self.watermark_keywords if k in name), None)
            if wm_hit:
                return "watermark keyword '%s' in filename" % wm_hit
            return {"path": path,
                    "has_audio": False,
                    "source_id": os.path.basename(path).split("_")[0]}
        except OSError as e:
            return "unreadable (%s)" % type(e).__name__

    def _scan(self, dirs, exts):
        found = []
        for d in dirs:
            for root, _, files in os.walk(d):
                for f in files:
                    if f.lower().endswith(exts):
                        found.append(os.path.join(root, f))
        return found

    def collect_assets(self):
        """Scan and validate every asset pool. Returns (images, grids, clips)."""
        raw_images = self._scan(self.images_dirs, IMAGE_EXTS)
        raw_grids = self._scan(self.grid_dirs, IMAGE_EXTS)
        raw_clips = self._scan(self.clips_dirs, VIDEO_EXTS)

        with ThreadPoolExecutor(max_workers=self.scan_workers) as pool:
            img_results = list(pool.map(self._validate_photo, raw_images))
            grids = [g for g in pool.map(self._validate_grid, raw_grids) if g]
            clip_results = list(pool.map(self._validate_clip, raw_clips))

        raw_image_set = set(raw_images)
        images = [r for r in img_results if r in raw_image_set]
        clips = [r for r in clip_results if isinstance(r, dict)]

        rejects = Counter(r for r in img_results if r not in raw_image_set)
        rejects.update(r for r in clip_results if isinstance(r, str))

        log(f"Assets validated: {len(images)} photos, {len(grids)} grids, {len(clips)} clips.")
        if rejects:
            summary = ", ".join(f"{n} {why}" for why, n in rejects.most_common(4))
            log(f"Rejected {sum(rejects.values())} files: {summary}")

        if not images and not clips:
            found = len(raw_images) + len(raw_clips)
            if found:
                # Reporting "nothing found" when the filters threw everything
                # away sends you looking in entirely the wrong place.
                detail = "; ".join(f"{n} {why}" for why, n in rejects.most_common())
                raise RuntimeError(
                    f"Found {found} media files but none passed validation: {detail}. "
                    f"Lower min_image_bytes / min_image_px / min_clip_bytes in the "
                    f"topic config if these files are genuinely usable.")
            raise RuntimeError(
                f"No media files found at all. Scanned {len(self.images_dirs)} image "
                f"and {len(self.clips_dirs)} clip directories - check --images-dir "
                f"and --clips-dir.")
        return images, grids, clips

    def curate_images(self, images):
        """Shuffle deterministically and weight topic assets more heavily.

        The graphic-card generator (triptych/grid/sparkle) draws its backdrops
        and inner photos from this list, so images not mentioned by the script
        show up as irrelevant subjects behind the first-60s hook cards. We now
        bias the curated pool toward images that live in entity folders the
        script actually names, or whose filenames contain any script token — so
        a Meghan/Beckham story does not open on Diana Award or Kate cards
        pulled from the pooled library.
        """
        topic_files = []
        if self.topic_assets_dir:
            topic_files = self._scan([self.topic_assets_dir], IMAGE_EXTS)

        random.seed(self.asset_seed)
        pool = list(images)
        random.shuffle(pool)

        weight = int(self.cfg.get("topic_asset_weight", 8))

        # Script-driven relevance: what's the story actually about?
        relevant = []
        off_topic = []
        if self.script_text:
            low = self.script_text.lower()
            # Alpha tokens in the script (≥ 4 chars, drop the most common words).
            _stop = {"that", "this", "with", "they", "them", "have", "been",
                     "were", "from", "into", "what", "when", "than", "there",
                     "their", "which", "would", "could", "about", "these",
                     "those", "then", "just", "some", "will", "said", "does"}
            script_tokens = {t for t in re.findall(r"[a-z]{4,}", low)
                             if t not in _stop}
            # Entity folders the script names — the folder name itself becomes
            # a check ("meghan_markle" -> both "meghan" and "markle" hit).
            for p in pool:
                parent = os.path.basename(os.path.dirname(p)).lower()
                stem = os.path.splitext(os.path.basename(p))[0].lower()
                parent_hit = any(w in script_tokens
                                 for w in re.split(r"[\s\-_]+", parent) if w)
                stem_hit = any(w in script_tokens
                               for w in re.findall(r"[a-z]{4,}", stem))
                (relevant if (parent_hit or stem_hit) else off_topic).append(p)
        else:
            relevant, off_topic = pool, []

        # Hook cards read best when they show the actual subjects, so overweight
        # the on-topic pool heavily; keep a smaller off-topic tail so long
        # videos don't run out of variety.
        curated = (topic_files * weight
                   + relevant * 3
                   + off_topic[:max(0, self.max_images - len(relevant) * 3)])
        if not curated:
            raise RuntimeError("No usable photographs after validation.")

        random.seed(self.curate_seed)
        random.shuffle(curated)
        return curated, topic_files

    def group_clips(self, clips, opening_clip):
        """Split clips into the generic pool plus keyword-matched groups."""
        groups = {g["name"]: [] for g in self.cfg.get("clip_groups", [])}
        generic = []

        for c in clips:
            if opening_clip and os.path.abspath(c["path"]) == os.path.abspath(opening_clip):
                continue
            name = os.path.basename(c["path"]).lower()
            for g in self.cfg.get("clip_groups", []):
                if any(k.lower() in name for k in g.get("keywords", [])):
                    groups[g["name"]].append(c)
                    break
            else:
                generic.append(c)

        random.seed(self.asset_seed)
        random.shuffle(generic)
        for name in groups:
            random.shuffle(groups[name])
        return generic, groups

    # -------------------------------------------------------------- graphics

    def generate_graphics(self, curated, grids):
        """Pre-render the graphic cards described by the topic config."""
        if not self.graphics_dir:
            return []
        os.makedirs(self.graphics_dir, exist_ok=True)

        made = []
        img_i = 0
        grid_i = 0

        def next_img():
            nonlocal img_i
            p = curated[img_i % len(curated)]
            img_i += 1
            return p

        def next_grid():
            nonlocal grid_i
            if not grids:
                return None
            g = grids[grid_i % len(grids)]
            grid_i += 1
            return g

        def safe(prefix, text, i):
            slug = "".join(ch if ch.isalnum() else "_" for ch in text.lower())[:28].strip("_")
            return os.path.join(self.graphics_dir, f"{prefix}_{i:02d}_{slug or 'card'}.jpg")

        # style3 (split typography card) — PERMANENTLY REMOVED from pipeline
        # style4 (centered headline card) — PERMANENTLY REMOVED from pipeline
        # style5 (typewriter quote caption) — PERMANENTLY REMOVED from pipeline

        def _list_backdrops(d):
            if not d or not os.path.isdir(d):
                return []
            exts = (".jpg", ".jpeg", ".png", ".webp")
            return sorted(os.path.join(d, f) for f in os.listdir(d)
                          if f.lower().endswith(exts))

        grid_bgs = _list_backdrops(self.grids_asset_dir)
        sparkle_bgs = _list_backdrops(self.sparkle_asset_dir)

        triptych_cards = []
        grid_cards = []
        sparkle_cards = []

        # Style 2 — triptych / split (side-by-side photos over blurred backdrop)
        for i in range(int(self.cfg.get("triptych_count", 18))):
            out = os.path.join(self.graphics_dir, f"triptych_{i + 1:02d}.jpg")
            bg = curated[img_i % len(curated)]
            three = [curated[(img_i + k) % len(curated)] for k in (1, 2, 3)]
            try:
                GraphicCompositor.style2_triptych_overlay(
                    bg, three, out, width=self.width, height=self.height)
                triptych_cards.append(out)
            except Exception as e:
                log(f"  triptych {i + 1} failed: {e}")
            img_i += 4

        # Style 1 — rounded photo card over a real grid backdrop (assets/grids)
        grid_pool = grid_bgs or grids  # fall back to legacy grid_dir, then generated
        for i in range(int(self.cfg.get("grid_card_count", 30))):
            out = os.path.join(self.graphics_dir, f"grid_card_{i + 1:02d}.jpg")
            bg = grid_pool[i % len(grid_pool)] if grid_pool else None
            try:
                GraphicCompositor.style1_rounded_card_on_grid(
                    next_img(), bg, out, width=self.width, height=self.height)
                grid_cards.append(out)
            except Exception as e:
                log(f"  grid card {i + 1} failed: {e}")

        # Style 3 — single portrait framed over a sparkle/particle backdrop
        if sparkle_bgs:
            for i in range(int(self.cfg.get("sparkle_card_count", 18))):
                out = os.path.join(self.graphics_dir, f"sparkle_card_{i + 1:02d}.jpg")
                bg = sparkle_bgs[i % len(sparkle_bgs)]
                try:
                    GraphicCompositor.style_sparkle_card(
                        next_img(), bg, out, width=self.width, height=self.height)
                    sparkle_cards.append(out)
                except Exception as e:
                    log(f"  sparkle card {i + 1} failed: {e}")

        # Interleave the three styles evenly across the video.
        pools = [p for p in (grid_cards, triptych_cards, sparkle_cards) if p]
        max_len = max((len(p) for p in pools), default=0)
        for k in range(max_len):
            for pool in pools:
                if k < len(pool):
                    made.append(pool[k])

        log(f"Generated {len(made)} graphic cards "
            f"(grid={len(grid_cards)}, triptych={len(triptych_cards)}, "
            f"sparkle={len(sparkle_cards)}) into {self.graphics_dir}")
        return made

    # -------------------------------------------------------------- timeline

    def _resolve_hook_assets(self, curated, graphics, topic_files):
        """Config-named hook assets first, then topic photos, graphics, curated."""
        resolved = []
        for entry in self.cfg.get("hook_assets", []):
            cand = entry
            if not os.path.isabs(cand) and self.topic_assets_dir:
                cand = os.path.join(self.topic_assets_dir, entry)
            if os.path.exists(cand):
                resolved.append(cand)

        fillers = list(graphics) + list(topic_files) + list(curated)
        fi = 0
        while len(resolved) < self.hook_count and fi < len(fillers):
            if fillers[fi] not in resolved:
                resolved.append(fillers[fi])
            fi += 1
        return resolved[:self.hook_count]

    def build_timeline(self, vo_duration, opening_clip, out_path):
        """Build the full segment list and write it to out_path as JSON."""
        vo_duration = float(vo_duration)
        images, grids, clips = self.collect_assets()
        curated, topic_files = self.curate_images(images)

        has_opening = bool(opening_clip and os.path.exists(opening_clip))
        lead = self.opening_lead_s if (has_opening or clips) else 0.0

        # Build the matcher early so the intro clip can be chosen to match the
        # opening narration (topic-relevant hook) rather than an arbitrary clips[0].
        self.matcher = self.build_matcher(vo_duration, lead) if self.semantic else None

        if not has_opening and clips:
            picked = None
            # YouTube channels usually open with a channel-branded card, a
            # disclaimer overlay, or a static title before the actual footage
            # starts — the shot-slicer catches these as comp_0000..comp_0004
            # and comp_pv{N}_0000..0004 for every pooled competitor. Reserve
            # those early slices for the body of the video where they can
            # blend in; the intro (RULE 11: first 5–6 s = topic-relevant video)
            # must land on an actual content shot.
            import re as _re_intro
            # Block the first 15 slices of every competitor (0000-0014). YouTube
            # channels routinely run 15-30 s of channel-branding + disclaimer
            # + sponsor sting before the actual footage, and the shot-slicer
            # catches every one of those as an early comp_*.mp4.
            _early = _re_intro.compile(r"^comp_(?:pv\d+_)?0*(?:[0-9]|1[0-4])\.mp4$")
            # Block matcher-side by adding blocked paths to used_paths. Match
            # against the matcher's own asset objects (their path form is what
            # matcher.score compares) — going via `clips` broke on any path
            # normalisation mismatch and silently let comp_0000 through.
            if self.matcher:
                _blocked = {a.path for a in self.matcher.by_kind.get("clip", [])
                            if _early.match(os.path.basename(a.path))}
                _reserved_before = set(self.matcher.used_paths)
                self.matcher.used_paths |= _blocked
                log(f"Intro picker: blocked {len(_blocked)} early-slice clips "
                    f"(comp_0000-comp_0004 across all competitors).")
                try:
                    asset, _score, _ents = self.matcher.pick(0.0, min(6.0, self.seg_max_s),
                                                              "clip", 0)
                finally:
                    # Only clear what THIS block added; keep whatever pick added.
                    keep = _reserved_before | ({asset.path} if asset else set())
                    self.matcher.used_paths &= keep
                if asset:
                    picked = asset.path
            if not picked:
                # Fall back to the first non-early clip, then first clip period.
                content_clips = [c for c in clips
                                 if not _early.match(os.path.basename(c["path"]))]
                picked = (content_clips[0]["path"] if content_clips else clips[0]["path"])
            # Extra safety: if the matcher somehow returned an early clip
            # anyway (path form mismatch), snap to the first content clip.
            if _early.match(os.path.basename(picked)):
                content_clips = [c for c in clips
                                 if not _early.match(os.path.basename(c["path"]))]
                if content_clips:
                    picked = content_clips[0]["path"]
                    log(f"Intro picker: matcher returned an early slice; "
                        f"snapping to first content clip.")
            opening_clip = picked
            has_opening = True
            log(f"Auto-selected intro clip: {opening_clip}")
        elif opening_clip and not has_opening:
            log(f"WARNING: opening clip not found, skipping: {opening_clip}")

        # Now that the intro is chosen, permanently block every early comp slice
        # from being picked ANYWHERE else in the timeline — those shots hold the
        # source channel's disclaimer / branded intro / sponsor cards, which read
        # as ours if they land mid-narration too.
        _early_perm = None
        try:
            _early_perm = _early
        except NameError:
            pass
        if _early_perm is not None:
            clips = [c for c in clips
                     if not _early_perm.match(os.path.basename(c["path"]))]
            if self.matcher:
                blocked_body = {a.path for a in self.matcher.by_kind.get("clip", [])
                                if _early_perm.match(os.path.basename(a.path))}
                self.matcher.used_paths |= blocked_body

        generic_clips, clip_groups = self.group_clips(
            clips, opening_clip if has_opening else None)
        graphics = self.generate_graphics(curated, grids)

        if self.matcher and has_opening:
            self.matcher.used_paths.add(opening_clip)

        segments = []
        seg_idx = 0
        current = 0.0
        used_paths = set()
        used_sources = {}
        group_cursors = {name: 0 for name in clip_groups}
        img_cursor = 0
        cg_cursor = 0
        motions = ["zoomin", "zoomout", "panright", "panleft"]

        random.seed(self.asset_seed)

        def pick_clip(at_index, start, end):
            """Semantic pick when available, else cooldown-ordered round robin."""
            if self.matcher:
                asset, _score, _ents = self.matcher.pick(start, end, "clip", at_index)
                if asset:
                    return {"path": asset.path, "has_audio": False,
                            "source_id": asset.source_id}
            for c in generic_clips:
                last = used_sources.get(c.get("source_id", c["path"]), -10 ** 9)
                if at_index - last >= self.clip_cooldown:
                    used_sources[c.get("source_id", c["path"])] = at_index
                    return c
            if generic_clips:
                c = generic_clips[at_index % len(generic_clips)]
                used_sources[c.get("source_id", c["path"])] = at_index
                return c
            return None

        # Segment 0 — RULE 34: full-frame intro clip carrying its OWN source
        # audio, up to 6 s. After it finishes, the narrator's voiceover kicks in
        # (build_audio_matrix extracts the source's audio track for the first
        # `lead` seconds and delays voiceover by exactly that much). Mirrors the
        # pacing of documentary channels that cold-open on a real found-footage
        # moment before commentary drops in.
        intro_clip = opening_clip if has_opening else (clips[0]["path"] if clips else None)
        if intro_clip:
            # Use the intro clip's native duration, capped at 6 s (RULE 34).
            # No stitching — one continuous shot reads as intentional, not
            # automated; a 2-3 s cold open is still "under 6 s".
            intro_dur = self._clip_seg_dur(intro_clip, 6.0)
            intro_dur = max(min(intro_dur, 6.0), 1.5)
            segments.append({
                "index": seg_idx, "start": 0.0,
                "end": round(intro_dur, 2), "duration": round(intro_dur, 2),
                "type": "clip", "file": intro_clip, "motion": "none",
                "postcard": False, "has_audio": True,   # <-- source audio kept
                "section": "opening_intro_native",       # render full-frame
            })
            current = round(intro_dur, 2)
            seg_idx += 1
            if self.matcher:
                self.matcher.used_paths.add(intro_clip)
            # Voiceover starts exactly when the intro ends. If that differs from
            # the lead the matcher was built with, shift every SRT span by the
            # delta so downstream picks still line up with what the narrator is
            # actually saying at wall-clock time t.
            actual_lead = round(intro_dur, 2)
            if self.matcher and abs(actual_lead - lead) > 0.01:
                delta = actual_lead - lead
                self.matcher.script.spans = [(a + delta, b + delta, txt)
                                             for (a, b, txt) in self.matcher.script.spans]
                log(f"RULE 34: intro clip is {actual_lead:.2f}s; shifted SRT "
                    f"spans by {delta:+.2f}s so voiceover picks stay in sync.")
            lead = actual_lead

        # Fast hook - front-loaded curated assets up to hook_end_s.
        hook_assets = self._resolve_hook_assets(curated, graphics, topic_files)
        if hook_assets and self.hook_end_s > current:
            remaining = len(hook_assets)
            for asset in hook_assets:
                if current >= self.hook_end_s:
                    break
                dur = round((self.hook_end_s - current) / max(1, remaining), 2)
                dur = max(dur, 2.0)
                if current + dur > self.hook_end_s:
                    dur = round(self.hook_end_s - current, 2)
                if dur < 1.0:
                    break
                segments.append({
                    "index": seg_idx, "start": round(current, 2),
                    "end": round(current + dur, 2), "duration": dur,
                    "type": "image", "file": asset, "motion": random.choice(motions),
                    "postcard": False, "has_audio": False, "section": "fast_hook",
                })
                current = round(current + dur, 2)
                seg_idx += 1
                remaining -= 1

        def group_for(t, index):
            """Return the keyword clip group whose time window covers t."""
            if index % 2 != 0:
                return None
            for g in self.cfg.get("clip_groups", []):
                name = g["name"]
                pool = clip_groups.get(name) or []
                if not pool or group_cursors[name] >= len(pool):
                    continue
                if float(g.get("start", 0)) <= t <= float(g.get("end", 0)):
                    return g
            return None

        target = vo_duration + lead

        while current < target:
            dur = round(random.uniform(self.seg_min_s, self.seg_max_s), 2)
            if current + dur > target:
                dur = round(target - current, 2)
                if dur < 1.0 and segments:
                    segments[-1]["duration"] = round(segments[-1]["duration"] + dur, 2)
                    segments[-1]["end"] = round(target, 2)
                    break
            used_dur = dur  # image slot length; clip branches shorten this to native

            def add_image(section, postcard):
                nonlocal img_cursor
                img = None
                if self.matcher:
                    asset, _score, _ents = self.matcher.pick(
                        current, current + dur, "image", seg_idx)
                    if asset:
                        img = asset.path
                if img is None:
                    img = curated[img_cursor % len(curated)]
                    img_cursor += 1
                segments.append({
                    "index": seg_idx, "start": round(current, 2),
                    "end": round(current + dur, 2), "duration": dur,
                    "type": "image", "file": img, "motion": random.choice(motions),
                    "postcard": postcard, "has_audio": False, "section": section,
                })

            group = group_for(current, seg_idx)
            if group:
                name = group["name"]
                c = clip_groups[name][group_cursors[name]]
                group_cursors[name] += 1
                used_dur = self._clip_seg_dur(c["path"], dur)
                segments.append({
                    "index": seg_idx, "start": round(current, 2),
                    "end": round(current + used_dur, 2), "duration": used_dur,
                    "type": "clip", "file": c["path"], "motion": "none",
                    "postcard": False, "has_audio": False, "section": name,
                })
            # Clip density is time-weighted for retention: pack half the first
            # 10 min with video, then ease off to ~1 clip per 3 image slots for
            # the tail. Target ~40 % clip share overall (V16 bump from 30–35 %),
            # still front-loaded so the opening feels like a documentary and
            # AVD holds up before the slower body of the story.
            elif (current < 600 and seg_idx % 2 == 0) or (current >= 600 and seg_idx % 3 == 0):
                c = pick_clip(seg_idx, current, current + dur)
                if c:
                    used_dur = self._clip_seg_dur(c["path"], dur)
                    segments.append({
                        "index": seg_idx, "start": round(current, 2),
                        "end": round(current + used_dur, 2), "duration": used_dur,
                        "type": "clip", "file": c["path"], "motion": "none",
                        "postcard": False, "has_audio": False,
                        "section": "documentary_clip",
                    })
                else:
                    add_image("body", seg_idx % 5 == 0)
            elif (seg_idx in (2, 5, 9, 14) or (seg_idx > 15 and seg_idx % 18 == 0)) and graphics:
                segments.append({
                    "index": seg_idx, "start": round(current, 2),
                    "end": round(current + dur, 2), "duration": dur,
                    "type": "image", "file": graphics[cg_cursor % len(graphics)],
                    "motion": "zoomout", "postcard": False, "has_audio": False,
                    "section": "custom_graphic",
                })
                cg_cursor += 1
            else:
                add_image("body", seg_idx % 5 == 0)

            current = round(current + used_dur, 2)
            seg_idx += 1

        # RULE 36: overlay date/time/location title cards on any segment whose
        # window overlaps a detected script callout. Prevents the "wrong photo
        # over a very specific time/place beat" problem — the card now
        # literally spells out what the narrator just said.
        try:
            import datetime_cards as _dtc
            if self.matcher and self.matcher.script and self.matcher.script.spans:
                # Backdrops for the cards: prefer entity images (they carry the
                # story subjects), fall back to whatever curated pool exists.
                backdrops = []
                for e in ("princess_anne", "meghan_markle", "prince_harry",
                          "king_charles", "queen_elizabeth"):
                    ent_dir = os.path.join(self.cfg.get("entity_root") or "",
                                            e)
                    if os.path.isdir(ent_dir):
                        for f in sorted(os.listdir(ent_dir))[:5]:
                            p = os.path.join(ent_dir, f)
                            if os.path.isfile(p): backdrops.append(p)
                if not backdrops and curated:
                    backdrops = curated[:20]
                cards_dir = os.path.join(self.graphics_dir or ".",
                                         "datetime_cards")
                dtc_cards = _dtc.build_card_set(
                    self.matcher.script.spans, cards_dir, backdrops)
                if dtc_cards:
                    log(f"RULE 36: generated {len(dtc_cards)} datetime/"
                        f"location title cards.")
                    # Replace any segment whose midpoint falls within a
                    # callout window.
                    replaced = 0
                    for i, s in enumerate(segments):
                        mid = (s["start"] + s["end"]) / 2.0
                        for (a, b, path) in dtc_cards:
                            # widen the window slightly so an image slot right
                            # over a callout still gets caught
                            if a - 0.5 <= mid <= b + 2.0:
                                s["type"] = "image"
                                s["file"] = path
                                s["motion"] = "zoomin"
                                s["postcard"] = False
                                s["section"] = "datetime_card"
                                replaced += 1
                                break
                    if replaced:
                        log(f"RULE 36: swapped {replaced} segment(s) to "
                            f"datetime cards.")
        except Exception as e:
            log(f"RULE 36 skipped: {e!r}")

        counts = {}
        for s in segments:
            counts[s["type"]] = counts.get(s["type"], 0) + 1

        data = {
            "total_duration": round(current, 2),
            "voiceover_duration": vo_duration,
            "opening_lead_s": lead,
            "segment_count": len(segments),
            "type_counts": counts,
            "custom_graphics_used": cg_cursor,
            "graphics_available": len(graphics),
            "semantic": bool(self.matcher),
            "segments": segments,
        }

        if self.matcher:
            cov = self.matcher.coverage()
            data["semantic_coverage"] = cov
            slots = cov["named_subject_slots"]
            log(f"Semantic picks: {cov['picks']} ({cov['scored']} scored on real terms)")
            if slots:
                reachable = cov["named_correct"] + cov["named_missed_despite_available"]
                pct = 100 * cov["named_correct"] / max(1, reachable)
                log(f"Named-subject slots: {slots} | right person shown "
                    f"{cov['named_correct']}/{reachable} ({pct:.0f}% of slots where "
                    f"they were available) | {cov['named_none_left_to_show']} had "
                    f"none left in the library")
                log(f"Wrong person shown: {cov['wrong_person_shown']} "
                    f"({100 * cov['wrong_person_shown'] / max(1, slots):.1f}% of "
                    f"named-subject slots)")
            with open(os.path.splitext(out_path)[0] + "_matches.json", "w",
                      encoding="utf-8") as f:
                json.dump(self.matcher.match_log, f, indent=2)

        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        log(f"Timeline: {len(segments)} segments, {current / 60:.2f} min, types={counts}")
        log(f"Saved timeline to {out_path}")
        return data
