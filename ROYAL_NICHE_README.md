# 👑 Royal Family Drama — Portable Niche README

**Purpose:** Everything one Claude session needs to produce a video in this niche
from a 4-item order, with no other back-and-forth. Drop this file into any new
session's context and it will know the whole system.

**Last updated:** 2026-09-15

---

## 1. The Deal — What The Operator Gives, What The Pipeline Delivers

### Operator gives (RULE 17):
| # | Input | Example |
|---|---|---|
| 1 | **Title** (13–16 words, DNA style) | `"Meghan HUMILIATED as Diana Gala Organizers SLAM the Door — Leaked Demands EXPOSED!"` |
| 2 | **Word count** (short / medium / long) | `medium` (3500–4500 words → ~25–30 min) |
| 3 | **Script Option #** (DNA 1–12 from Section 6) | `DNA 9` (Insider Silence Broken) |
| 4 | **Effect look** (one of 13) | `cinematic_warm` |
| 5 | **Competitor YouTube URL** *(video 6+ pool-merge flow)* | `https://www.youtube.com/watch?v=iinDx2bD7wo` |

That's it. The operator does not pick voice, workers, bitrate, backdrops,
per-scene assets, or clip sources. All of that is baked in. From video 6
onward the operator also drops in a competitor URL so the pool-merge flow
(section 11a) can shot-slice it for fresh clips — otherwise the pipeline
would only recycle prior videos' pooled footage.

### Pipeline delivers:
- `Video N (<title>)/` folder containing:
  - `script.txt` (generated per DNA + word count)
  - `voiceover.mp3` + `voiceover.srt` (ai33pro TTS, word-level timestamps)
  - `assets_fresh/images/{entity,scene}/*.jpg` (Serper.dev, script-aware)
  - `assets_fresh/clips/comp_*.mp4` (competitor YouTube, shot-sliced, stabilised)
  - `<Title>.mp4` — final 1920×1080 30 fps H.264 export (350–450 MB / 30 min)
  - `YOUTUBE_METADATA_<title>.txt` (title alts, description, chapters, tags)

Typical wall clock for a 30-min video: **10–13 min end-to-end** (TTS ~2m,
timeline ~1m, render ~5m, concat+mux ~2m).

---

## 2. One-Command Run

Once assets are staged for the script folder, the whole build is a single
command:

```bash
cd "C:\Users\ninja\Downloads\X Colab Automation\Royal\pipeline"
python pipeline.py \
  --script "<VID>/script.txt" \
  --output-dir "<VID>" \
  --title  "<title>" \
  --voiceover "<VID>/voiceover.mp3" \
  --topic-config configs/video<N>_fresh.json \
  --workers 6 \
  --look   <look_name>
```

### First video (no prior pool)

```bash
python fresh_assets.py \
  --script "<VID>/script.txt" \
  --assets-dir "<VID>/assets_fresh" \
  --competitor-video "<VID>/assets_fresh/clips/competitor_source.mp4"
```

Or `populate_royal_assets.py` for the full populate + stabilize flow
(RULE 9).

### Video 6+ (pool-merge workflow, RULE 24)

See section 11a for the full runbook. In brief: pool-merge from prior
`Done/` + `Royal/` videos, download the new competitor with `yt-dlp`,
run TTS + `fresh_assets.py` (Serper) + slicer in parallel, then run
`pipeline.py` with `--voiceover` so Stage 1 is skipped.

---

## 3. The 36 Permanent Rules (from `pipeline/PIPELINE_RULES.md`)

These are enforced in code; do not override without discussion.

| # | Rule | Where |
|---|---|---|
| 1 | No `style3` (split typography) cards | `graphic_compositor.py` |
| 2 | No `style4` / `style5` (typewriter overlay) cards | `graphic_compositor.py` |
| 3 | Auto-reject blurry / small images (min 720px, Laplacian ≥ 65) | `timeline_engine.py` `_validate_photo` |
| 4-5 | Auto-reject watermarked / stock-agency images | filename + corner-pixel inspection |
| 6 | Word-level SRT anchors for visual sync (**revised**: ai33pro auto-SRT) | `voiceover_engine.py`, `pipeline.py` |
| 7 | Grid + Triptych cards placed in first 60 s (segs 2, 5, 9, 14) | `timeline_engine.py` `build_timeline` |
| 8 | No burned-in captions for this niche (config default off) | `pipeline.py` |
| 9 | Video clip stabilization (guarded 2-pass vidstab, revert if worse) | `stabilize_clips.py` |
| 10 | Only 3 approved card styles: grid, triptych, sparkle (with asset backdrops) | `graphic_compositor.py` |
| 11 | First 5–6 s = topic-relevant video clip (2–3 clips at native length) | `timeline_engine.py` |
| 12 | Clip segments use native duration (no loop, no stretch) | `render_engine.py` clip branch |
| 13 | Voiceover via **ai33pro v3** (voice `elevenlabs_SAz9YHcvj6GT2YYXdXww`, speed 0.95, gain 2.10) | `voiceover_engine.py` |
| 14 | Competitor clips (`comp_*`) render inside grid/sparkle framed cards; **top 12 % + bottom 18 % cropped** to strip channel logo AND source captions (revised V7) | `render_engine.py` |
| 15 | Render workers cap = 6 (NVENC session-safe); libx264 SW fallback; no exception may escape a worker | `render_engine.py` |
| 16 | Reusable named effect looks: 13 total (`preview_grid.jpg` shows all) | `looks.py`, `look_preview.py` |
| 17 | Operator gives only 4 things (title / word count / script option / look) | this README |
| 18 | Final concat uses NVENC HQ (`p5` + `cq 21`) + 128 k AAC → 30–45 % smaller file at same perceived quality, voice fully clear | `render_engine.py` |
| 19 | `competitor_source*.mp4` (yt-dlp'd slicer input) is **never** admitted to the clip pool — enforced in both timeline & semantic scans | `timeline_engine.py`, `semantic_matcher.py` |
| 20 | Serper-downloaded filenames are prefixed with the query slug (e.g. `soho_farmhouse_0001_abc.jpg`) so the semantic matcher gets real tokens instead of hash noise | `fresh_assets.py` |
| 21 | `curate_images` biases the graphic-card pool toward images whose entity folder OR filename tokens intersect script tokens (relevant × 3, off-topic tail only) — so a Meghan/Beckham story does not open on Diana Award or Kate cards | `timeline_engine.py` |
| 22 | Clip density is time-weighted for AVD: `< 600 s → every 2nd seg`, `>= 600 s → every 5th` — ~30–35 % clip share overall, front-loaded to the first 10 min hook | `timeline_engine.py` build_timeline |
| 23 | `entity_cooldown = 10` (was 4) — wider spacing between same-entity picks breaks Meghan-Meghan-Meghan runs | `timeline_engine.py` → `SemanticMatcher` |
| 24 | Pool-merge inheritance across videos: `pool_merge.py` copies matching-entity images and every `comp_XXXX.mp4` from `Done/Video*/` and `Royal/Video*/` into the new video's `assets_fresh/`, prefixed with `<source>_` / `comp_pv{N}_` so RULE 14 still fires and generational nesting is avoided | `pipeline/pool_merge.py` |
| 25 | `pipeline.py` imports `config` at load time → dotenv loads `Royal/.env` + `apis/*.env` so `VOICEOVER_API_KEY` (ai33pro) reaches TTS without a shell export | `pipeline.py` |
| 26 | ffmpeg concat writer escapes single quotes in asset paths (`'` → `'\''`) so folder names like `Meghan's ...` no longer crash Stage 1 | `voiceover_engine.py` |
| 27 | Beckham roster registered as first-class entities: `david_beckham`, `victoria_beckham` — Serper queries + regex triggers ship with the module so future Beckham-adjacent scripts get face-verified fetches straight away | `fresh_assets.py` KNOWN_ENTITIES |
| 28 | Sussex children registered as first-class entities: `prince_archie`, `princess_lilibet` — custody / return / school storylines pull face-verified images straight away | `fresh_assets.py` KNOWN_ENTITIES, `pool_merge.py` ENTITY_TRIGGERS |
| 29 | Intro-clip picker AND every downstream clip slot block `comp_(?:pv\d+_)?0000..0014.mp4` — the first 15 slices of every competitor are almost always disclaimer / channel-branded / sponsor-intro overlays, and letting one land mid-narration reads as ours. Blocked in both `by_kind` (matcher path) and the `clips` list; safety-net snaps to first content clip if the matcher still returns one | `timeline_engine.py` build_timeline |
| 30 | Pool physically purged of `comp_0000-0014` on every pool_merge so the branded/disclaimer intros never enter the semantic index at all (belt-and-suspenders with RULE 29) | to be added to `pool_merge.py` next merge |
| 31 | Scene images with extreme aspect ratio (< 0.75 or > 2.5) are dropped from the pool — those are banners, tweet screenshots, infographics, book covers and promo cards that fresh_assets sometimes drags in, and they read as ours if used | run once per new video via a purge helper (see section 11a) |
| 32 | `entity_boost` raised from 12 → **25** — script-mentioned entity images dominate scoring so a "Harry" segment lands a Harry image, not a same-family cousin | topic configs (`configs/video<N>_fresh.json`) |
| 33 | 12-frame QC extraction is required BEFORE any Video 6+ is delivered — ffmpeg -ss at `00:02, 00:08, 00:15, 00:30, 00:45, 01:15, 03:00, 05:30, 08:00, 12:00, 20:00, 27:00` plus a md5 duplicate check across the sample. Publish only after the frames read clean (no logo, no disclaimer text, no obvious wrong-entity, no identical duplicates). | operator workflow (see section 9) |
| 34 | Intro clip is a **cold open**: a single full-frame comp_XXXX shot (top 12 % + bottom 18 % cropped for watermark), plays with its **source audio**, capped at 6 s. Voiceover is delayed by exactly the intro duration; script SRT spans are shifted by the same delta so mid-video sync stays exact. Reference feel: <https://www.youtube.com/watch?v=8XU1Hl0OzKw> | `timeline_engine.py` intro segment, `render_engine.py` clip branch, `build_audio_matrix` |
| 35 | Entity folder cap = 500 images, scene folder cap = 4000. Beyond that Stage 2 asset validation (Laplacian blur + watermark scan on every image) thrashes RAM without any pick-quality gain — the semantic matcher can't meaningfully rank a 10 000-image pool per slot. Random-sample per entity in `pool_merge.py` keeps the variety, drops the bloat. | `pipeline/pool_merge.py` |
| 36 | Auto-generate title cards for **date / time / location** callouts in the narration. `datetime_cards.find_callouts` scans the SRT for patterns like `Wednesday, August 26th`, `at 11:47 in the morning`, `at Birmingham Airport`; `datetime_cards.render_card` composes a memorial-style card (blurred royal backdrop + red-underlined kicker + big serif headline). `timeline_engine.build_timeline` swaps any segment whose midpoint overlaps a callout window to that card, so a "very specific time/place" beat never lands on a random pool photo. Reference: dark backdrop + big serif + red-underlined kicker like the "IN MEMORY / Never Forget" cards. | `pipeline/datetime_cards.py`, `timeline_engine.py` `build_timeline` |

Plus the Ken-Burns zero-shake mechanic (perspective filter, `zoomPerSec = 0.010`,
motion wheel 17 % static / 8 % pan / rest zoom).

---

## 4. Named Effect Looks (RULE 16)

```
vintage clean warm noir none
noise_soft black_noise grainy gloom_grain color_off
vignette_only documentary_bw cinematic_warm
```

Preview all on a sample image:

```bash
python look_preview.py --image "path/to/sample.jpg"
```

Set per-video: `--look <name>` on the CLI, or `"look": "<name>"` in the topic
config JSON.

---

## 5. Tools In `pipeline/`

| File | Purpose |
|---|---|
| `pipeline.py` | Master orchestrator (Stages 1–5) |
| `voiceover_engine.py` | Multi-provider TTS (ai33pro / edge-tts / twospeaker / omnivoice) |
| `timeline_engine.py` | Script-aware asset scan, semantic matcher, timeline builder |
| `render_engine.py` | GPU segment renderer, framed-clip composer, concat, audio mux |
| `graphic_compositor.py` | Grid / triptych / sparkle card generators |
| `semantic_matcher.py` | Word-level SRT → tokens + entities → asset scoring |
| `looks.py` | The 13 named grade bundles |
| `look_preview.py` | Render every look on a sample → contact-sheet grid |
| `fresh_assets.py` | Serper.dev per-entity image fetch + yt-dlp competitor + shot-slice clips |
| `populate_royal_assets.py` | End-to-end asset refresh (calls fresh_assets + stabilize) |
| `stabilize_clips.py` | Guarded two-pass vidstab + quarantine unfixable |
| `pool_merge.py` | RULE 24 / 30 / 31 / 35 — inherit matching-entity assets from all prior Royal videos into a new video's `assets_fresh/`, auto-purge branded early clips, banner/aspect-extreme scene images, and cap each entity to 500 images / scene to 4000 |
| `datetime_cards.py` | RULE 36 — detect date / time / location callouts in the SRT and render memorial-style title cards (blurred royal backdrop + red-underlined kicker + serif headline) that swap in over the matching segment |
| `kb_jitter.py` | Measure per-frame jitter (dx/dy sd, px) for QC |
| `index_retriever.py` | Wrapper for the D:\ V3 semantic index (optional secondary asset source) |
| `subtitle_formatter.py` | SRT → styled ASS (used only when RULE 8 flipped to burn subtitles) |
| `metadata_engine.py` | Generates YouTube title / description / chapter file |
| `assets/grids/`, `assets/sparkle-backgrounds/` | Backdrop libraries for cards + framed clips |

---

## 6. Sub-Niches & Scripting DNA

The full breakdown of sub-niches, DNAs, and title formulas lives in
`royal-drama-niche-playbook.md` (Section 3 for the 10 sub-niches, Section 6 for
the 12 title DNAs, Section 8 for the Universal Script Requirements).

Use it as the SCRIPT-writing brief: pass the playbook + the operator's 4 inputs
to any drafting session and it produces the on-brand script that goes into
`<VID>/script.txt`.

---

## 7. Credentials

Stored in `Royal/.env` (and mirrored in `Downloads/X Colab Automation/apis/`):

- `VOICEOVER_API_KEY` — ai33pro (`sk_YOUR_AI33PRO_KEY_HERE`)
- `SUBTITLE_API_KEY`  — Groq Whisper (fallback SRT source)
- `THUMBNAIL_API_KEY` — openlux (thumbnail fallback)
- `SERPER_API_KEY`    — Serper.dev (used by `fresh_assets.py` for images)

The pipeline reads these from env — do not paste keys into config files.

### Voice IDs (elevenlabs via ai33pro v3)

The topic config's `voice_id` selects the narrator. Same field is read by
`_tts_v<N>.py`. Do not hard-code — copy from prior video's `_tts_v<N-1>.py`
when the operator does not name a specific voice.

| Voice ID | Used in |
|---|---|
| `elevenlabs_SAz9YHcvj6GT2YYXdXww` | V2 – V11 (deep documentary male) |
| `elevenlabs_RNnkVeW25AwKYxZgnHBH` | V12 onward (crisper male, per operator's Sep 17 note) |

### Background music library

`pipeline/assets/bg music/*.mp3` — every video's config picks one file
from this folder for RULE 18's under-narration bed. Rotate per video so
successive uploads do not share the same cue. Current cues:

- `Cinematic Tension Build.mp3` (V12)
- `Dramatic Piano Pulse.mp3`
- `Mark Jubel - Efteraar.mp3`
- `Silent Tension Piano.mp3`
- `Slow Dramatic Ascent.mp3`

The old `Downloads/Dolly Parton/Bg music/*.mp3` set is gone — do not
reference those paths in a new config.

---

## 8. Output Specs

Final video: `<Title>.mp4`

- 1920 × 1080 @ 30 fps, H.264 High profile, `yuv420p`
- Video: NVENC `p5 -rc vbr -cq 21 -maxrate 4500k` (RULE 18)
- Audio: AAC 128 k, 44.1 kHz stereo, VO gain 2.10 × + alimiter 0.95
- No BGM (`bgm: null`)
- `+faststart` for web streaming
- Typical size: **350–450 MB per 30 min** (was 640–830 MB before RULE 18)

---

## 9. QC Checklist Before Publish

- [ ] Duration ≈ voiceover duration (no truncation — see RULE 15 fallback)
- [ ] `Wrong person shown: < 5%` in the pipeline log
- [ ] `Named-subject slots: X | right person shown X/X` in the pipeline log
- [ ] Framed competitor clips show **no** burned-in source captions AND **no**
      top-left channel logo (RULE 14 top+bottom crop)
- [ ] Intro clip (first 5–6 s) is a `comp_*.mp4`, NOT `competitor_source*.mp4`
      — greppable in `render.log` (RULE 19)
- [ ] File size 300–500 MB per 30 min (RULE 18)
- [ ] Voice clearly audible over first play-through, no clipping peaks
- [ ] Intro (first 5–6 s) is a topic-relevant clip, not a still

### Frame-extraction QC (RULE 24 workflow, do before publishing)

```bash
for t in 00:00:02 00:00:10 00:00:15 00:00:22 00:05:00 00:11:00 00:20:00; do
  slug=$(echo "$t" | tr ':' '_')
  ffmpeg -y -ss "$t" -i "<VID>.mp4" -vframes 1 -q:v 3 qc/frame_${slug}.jpg
done
```

Eyeball the seven frames for: framed intro (no logo), hook cards showing
the story's actual subjects (not unrelated royals), and clip-heavy first
10 min. Only publish once these read cleanly.

### RULE 34 intro & RULE 36 datetime-card verification

The log emits `RULE 34: intro clip is X.XXs; shifted SRT spans by …`
and `RULE 36: swapped N segment(s) to datetime cards.` — both lines
must be present when the script has a cold-open worth honouring and
carries a date/time/location callout in the opening. If either is
missing, treat the render as suspect: RULE 34's absence usually means
the sliced clip is silent (older slicer batch) and needs re-slicing;
RULE 36's absence usually means the SRT chunker put the date and time
into a single span that neither pattern matched cleanly — extend
`_DATE_RE` / `_TIME_RE` in `datetime_cards.py` for that phrasing.

---

## 10. Adding A New Look

1. Add an entry to `LOOKS` in `looks.py` (grade / postcard_eq / graphic_grade / border_color / fill_mode).
2. Preview it: `python look_preview.py --image sample.jpg --only <new_look>`.
3. Add its one-line description to RULE 16 in `pipeline/PIPELINE_RULES.md`.
4. Add it to Section 4 of this README.

---

## 11. Adding A New Entity

1. Append it to `KNOWN_ENTITIES` in `fresh_assets.py` with a regex list.
2. Also append it to `ENTITY_TRIGGERS` in `scratchpad/pool_merge.py` (mirror
   pattern) so future pool-merges detect the entity in scripts.
3. Optional: append it to the corpus dictionary (`_index/config/corpus.json`)
   for the V3 index route.
4. Re-run `populate_royal_assets.py` (or `fresh_assets.py --script <...>`)
   to pull face-verified Serper images into the new entity folder.

## 11a. Pool-Merge Workflow (RULE 24) — for Video 6+

Every new video inherits from prior Royal videos so we never re-fetch what
we already have, but always add fresh material (new competitor clips + new
Serper images with descriptive filenames) so the finished cut doesn't feel
recycled. Concretely, per video:

1. Operator drops `script.txt` into `Video N (title)/` and gives the
   competitor URL.
2. `python pipeline/pool_merge.py --video N` walks every prior
   `Done/Video*/` and `Royal/Video*/` that has an `assets_fresh/`:
   - Copies each matching entity folder's images with a `v{N}_` prefix
     into the new video's `assets_fresh/images/<entity>/`.
   - Copies every `comp_<idx>.mp4` clip as `comp_pv{N}_<idx>.mp4` — the
     `comp_` prefix stays intact so RULE 14 fires, and already-nested
     `comp_pv*` clips are skipped so names don't accrete over generations
     (no `comp_pv6_pv2_...`).
3. `yt-dlp` downloads the new competitor into
   `assets_fresh/clips/competitor_source_v{N}.mp4` — RULE 19 keeps this
   raw file out of the timeline forever.
4. `fresh_assets.py --competitor-video <that mp4>` shot-detects the source
   and writes fresh `comp_<idx>.mp4` slices alongside the pool, plus
   fetches Serper images for every script entity + scene phrase (RULE 20
   filenames carry the query slug).
5. Standalone TTS (`pipeline/_tts_v{N}.py`, adapt one from a prior video)
   runs in parallel with `yt-dlp` and Serper — the 3 tasks are independent.
6. Once TTS + Serper + slicer are all done, `pipeline.py` runs with
   `--voiceover <path>` so Stage 1 is skipped and the timeline builds off
   the full pooled library.
7. Before publishing: extract frames at `0:02`, `0:10`, `0:15`, `5:00`,
   `11:00`, `20:00` with ffmpeg and eyeball them for logo bleed, wrong
   entities in graphic cards, and clip-density feel. Publish only after
   this QC pass.

---

## 12. Change Log — What's New Since Video 1

- **Video 2 rebuild** (Sep 12): fresh script-aware assets, competitor clips,
  framed-clip render, no BGM, word-level SRT sync, 6-worker NVENC-safe render,
  ffprobe segment validation, HQ concat re-encode.
- **RULE 13**: ai33pro v3 primary TTS with word-level SRT.
- **RULE 14**: `comp_*` clips render inside grid/sparkle framed cards with
  bottom-18 % source-caption strip.
- **RULE 15**: worker cap 6 + libx264 fallback + wrapped worker exceptions.
- **RULE 16**: 8 new named looks (`noise_soft`, `black_noise`, `grainy`,
  `gloom_grain`, `color_off`, `vignette_only`, `documentary_bw`,
  `cinematic_warm`) + `look_preview.py` tool.
- **RULE 17**: 4-input operator protocol codified.
- **RULE 18**: NVENC HQ concat + 128 k AAC → 30–45 % smaller files at same
  perceived quality.
- **Video 5** (Sep 14–15): reuse Video 2's assets with a new title & new
  script — voiceover generated fresh, everything else pool-merged. First
  video with a folder name containing an apostrophe (`Meghan's …`) — surfaced
  the two Stage-1 bugs codified as RULE 25 and RULE 26 below.
- **RULE 25**: `pipeline.py` imports `config` so `.env` (ai33pro key) loads
  without a shell export — otherwise Stage 1 dies with 401 Unauthorized.
- **RULE 26**: `voiceover_engine.py` concat writer escapes `'` inside paths
  (`'` → `'\''`) so folder names with apostrophes no longer crash ffmpeg.
- **Video 6** (Sep 15, look=none, dramatic BGM `Til Death Parts Us`):
  first-generation pool-merge — all Done/Video 2–5 images + comp clips fold
  into V6's `assets_fresh/` before render.
- **RULE 24 introduced**: pool-merge inheritance codified in
  `pipeline/pool_merge.py` (CLI: `--target <path>` or `--video N`;
  prefixes `comp_pv{N}_` preserve RULE 14, auto-adds Beckham + royals as
  needed).
- **RULE 27**: Beckham entities registered in `KNOWN_ENTITIES` so
  Cotswolds-set stories don't require a hand-hack per script.
- **Video 7 v1** (Sep 15): first V7 render surfaced the last-mile issues —
  intro clip was picking the raw yt-dlp'd 656 MB competitor source (channel
  logo visible), grid/triptych cards were pulling Diana Award / Kate photos
  from the pool (script-irrelevant), and clip density was flat across the
  full runtime.
- **Video 7 v2** (Sep 15, delivered): all four fixes above (RULES 19–23)
  applied and QC'd via extracted frame checks at 0:02 / 0:10 / 0:15 / 5:00 /
  11:00 / 20:00 before publish. Named-subject accuracy 100 % (125/125),
  time-weighted clip density 30.2 % overall with the first-10-min hook
  packed at ~50 % clips for AVD.
- **RULE 19**: `competitor_source*.mp4` blocked from clip pool in both
  `timeline_engine._validate_clip` and `semantic_matcher.add_dir` (defence
  in depth — a single filter was bypassed by the semantic scan on V7 v1).
- **RULE 20**: Serper filenames now carry the query slug — sync jumps from
  22 % → 25 % terms-scored and unlocks scene-phrase sync (`soho_farmhouse`,
  `beckham`, `david_beckham`, etc.).
- **RULE 21**: `curate_images` filters by script relevance so hook cards
  can't lead on unrelated royals.
- **RULE 22**: clip density time-weighted, first 10 min = ~50 % clips.
- **RULE 23**: `entity_cooldown` raised 4 → 10 in the timeline builder so
  same-entity repetition spaces out.
- **RULE 14 revised**: framed-clip crop is now `top 12 % + bottom 18 %`
  (middle 70 % survives) — kills top-left channel logos as well as
  bottom-strip captions.
- **Video 8** (Sep 15, Charles's rule for Harry): King Charles + Anne
  entities registered; V8's fresh comp clips fed forward for V9's pool.
- **Video 9 v1 issues** (Sep 15): (a) intro clip landed on a competitor
  DISCLAIMER slice — the block range 0-4 wasn't wide enough because
  channels commonly run 15-30s of branded intro before real footage;
  (b) triptych / grid cards showed wrong-story images (guidance-for-
  charities banners, book covers) sourced from a bloated scene pool;
  (c) some clips visibly repeated.
- **Video 9 v2 fixes → RULES 28-33**: block range extended to comp_0000-0014,
  physical purge of branded early clips from the pool, aspect-ratio purge
  of graphic/banner scene images, `entity_boost` up 15 → 25, and a hard
  12-frame QC before publish. QC passed cleanly for V9 v2 — real Meghan
  intro clip, Anne sync-locked mid-video, no duplicates in sample.
- **Sussex children registered** (`prince_archie`, `princess_lilibet`) so
  custody / return / school-run storylines get face-verified fetches.
- **Video 10** (Sep 15): 60-min pool merge without RULE 35 sanded RAM
  to 5 GB and thrashed Stage 2. Diagnosis: pool had grown to ~60 000
  images across V2-V9 accumulations. Trimming to ~7 K + capping per
  entity turned Stage 2 from a 20-min stall into ~90 s. RULE 35
  codified in `pool_merge.py`.
- **Video 11** (Sep 16, Harry / William / Anne at Balmoral): first video
  to run the RULE 34 cold-open path end-to-end. Surfaced two structural
  bugs in RULE 34: (a) `slice_competitor_clips` stripped audio with `-an`
  so `build_audio_matrix` had no `[1:a]` stream to lift into the intro —
  fixed by keeping AAC 128 k on the sliced clip; (b) the historical
  `Dolly Parton\Bg music\*.mp3` folder was gone, so the mux fell back to
  no-BGM. Manual remux recovered V11 by extracting the intro audio
  directly from the source competitor at the shot's exact timestamp
  (scenedetect index → seconds), then remixing with voiceover delayed
  by that duration and BGM ducked underneath. RULE 34 now works
  automatically for V12+ because the slicer keeps audio.
- **Slicer duration bumped 1.5-3 s → 3.5-6 s**: shots that used to be too
  short to feel like real footage now stay on screen long enough for a
  30 % clip count to also be a 25-30 % clip share of run-time.
- **BGM folder is `pipeline/assets/bg music/*.mp3`** (not the old
  `Downloads/Dolly Parton/Bg music/`). Every video's config picks one
  file from that folder for RULE 18's under-narration bed.
- **Video 12** (Sep 17, redo of V9 with cold-open + new voice
  `elevenlabs_RNnkVeW25AwKYxZgnHBH` + new BGM). First video with wrong
  images in the first 30 s where the narrator called out a specific
  time / date / location — because Serper scene queries had returned
  hotel rooms, currency notes and pool photos for "Home Office" and
  "Birmingham Airport". Fixed by:
  - Removing the scene folder from the images tree for V12 so only
    entity folders (Meghan / Harry / Anne / Archie / William / Kate /
    Lilibet) feed the pool.
  - Adding RULE 36 — `datetime_cards.py` — which detects "Wednesday,
    August 26th" and "11:47 in the morning" and swaps the covering
    segments to a memorial-style title card (blurred Anne backdrop +
    red-underlined "ON THE RECORD" kicker + big serif headline).
  - Reinstalling opencv-python 4.10 so face detection (dropped when
    something bumped cv2 to a broken 5.0 build) is available again;
    RULE 31 can now also drop scene photos that carry no face.
