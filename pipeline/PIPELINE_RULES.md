# Royal Documentary Pipeline — Permanent Rules
# These rules are enforced automatically and must never be overridden.

## RULE 1: No Split Typography Cards (style3)
# The split typography card (photo on left, title+subtitle on right over dark grid,
# red accent rule) is PERMANENTLY REMOVED from the pipeline.

## RULE 2: No Typewriter / Centered Headline / Quote Cards (style4 & style5)
# Typewriter text overlay cards (grayscale photos with Courier text overlay like
# "INSIDE THE ROYAL ARCHIVES OF BALMORAL") are PERMANENTLY REMOVED.
# - Do NOT generate style4_centered_headline or style5_quote_caption cards.
# - Keep all visual cards clean without typewriter text overlays.

## RULE 3: Auto-Reject Low Quality / Blurry Images
# Images that are blurry, low-resolution, or too small must be rejected
# automatically during asset validation.
# - min_image_px: 720 (both width AND height must be >= 720px)
# - min_image_bytes: 60000 (file must be >= 60KB)
# - Blur detection: Laplacian variance must be >= 65 (lower = blurrier = rejected)
# - Enforced in: timeline_engine.py → _validate_photo()

## RULE 4 & 5: Auto-Reject Watermarked Images & Stock Agency Banners
# Images with visible watermarks or stock photo agency banners must be rejected.
# Detection methods:
# 1. Filename keyword matching (getty, alamy, shutterstock, istockphoto, etc.)
# 2. Visual corner pixel banner inspection: checks bottom-right and bottom-left
#    corners for solid dark text boxes (dark_frac > 0.40 and text_frac > 0.03).
# - Enforced in: timeline_engine.py → _validate_photo() and _validate_clip()

## RULE 6: Exact SRT Word-Level Timestamp Alignment
# To guarantee 100% narration-to-visual sync (e.g. showing King Charles at the exact
# second his name is spoken), the pipeline MUST auto-detect and parse the voiceover
# subtitle file (voiceover.srt) using ScriptTimeline.from_srt().
# - Enables second-by-second sentence/word timestamp alignment across the entire video.
# - Enforced in: pipeline.py and timeline_engine.py → build_matcher()

## RULE 7: Card Layout Styling (Grid & Triptych Multi-Photo Cards)
# Grid-style cards (rounded-corner photo framed over dark grid backdrop) and
# Triptych/Split cards (side-by-side photo frames over blurred backdrop) are
# generated and placed across ~5% of the video timeline.
# - MUST be used in the first 60 seconds (intro segments 2, 5, 9, 14) to establish
#   a premium documentary visual feel.
# - Enforced in: timeline_engine.py → generate_graphics() & build_timeline()

## Ken Burns Zero-Shake Fix (images)
# Uses the 'perspective' filter with interpolation=cubic for sub-pixel accuracy.
# - zoomPerSec: 0.010 (rate per second)
# - Motion wheel: 17% static, 8% pan, rest alternating zoom-in/zoom-out
# - Verified: image/graphic segments measure dx_sd ~0.006 px (kb_jitter.py).

## RULE 8: No Burned-In Captions For This Niche
# This niche runs WITHOUT captions. Default is off (config "burn_subtitles": false).
# - Enforced in: pipeline.py (want_subs = cfg.burn_subtitles and not --no-subtitles).
# - Enable per-project only by setting "burn_subtitles": true.

## RULE 9: Video Clip Stabilization (source shake)
# Ken Burns fixes image shake; source news/archival CLIPS carry their own handheld
# shake (measured dx_sd 0.5-3.0 px) that scale-up amplifies. Run stabilize_clips.py
# after populate: two-pass vidstab (smoothing=30, zoom=5, optzoom=0, no unsharp).
# - Guarded: each clip is re-measured; the stabilized version is kept ONLY if jitter
#   actually dropped, else the original is left untouched (never makes a clip worse).
# - Very shaky clips with real camera motion are left as-is (revert).
# - Measure with: python kb_jitter.py <clip>  (sd <0.12 smooth, >0.40 shake).

## RULE 10: Three Approved Card Styles + Backdrop Assets
# Only these three card layouts are used (style3/4/5 remain banned per RULES 1-2):
#   1. Grid card    - rounded photo card over a real grid backdrop (assets/grids/*)
#   2. Triptych     - side-by-side framed photos over a blurred backdrop
#   3. Sparkle card - single framed portrait over a particle backdrop
#                     (assets/sparkle-backgrounds/*)
# - Backdrops loaded from pipeline/assets/{grids,sparkle-backgrounds}; override via
#   config grids_asset_dir / sparkle_asset_dir. Counts: grid_card_count,
#   triptych_count, sparkle_card_count.
# - All card photos pass through load_photo_trimmed() to strip baked-in postcard
#   white borders before framing.

## RULE 11: First 5-6s Is A Topic-Relevant Video Clip
# The opening 5.0-6.0s is video (not images): consecutive clips chosen by the
# semantic matcher against the opening narration so the hook is on-topic. Index
# clips are only 1.3-3s, so 2-3 clips cover the window with clean cuts (never a
# looped single clip, which seams).
# - Enforced in: timeline_engine.py build_timeline() (intro clip loop).

## RULE 17: Video Order Protocol — 4 Inputs From The User, Nothing Else
# The user commissions a new video by giving ONLY four things:
#   1. TITLE           - final YouTube title, 13-16 words, DNA style from the
#                        niche playbook (Section 6). Determines file/folder name.
#   2. WORD COUNT      - short 1500-2000 (~10-15 min), medium 3500-4500
#                        (~25-30 min), long 5500-6500 (~40-45 min).
#   3. SCRIPT OPTION # - the DNA number from the niche playbook Section 6 (1-12)
#                        so the script picks the right hook + structure.
#   4. EFFECT LOOK     - one of the 13 named looks (see RULE 16). Default per
#                        niche = "vintage".
# Every other decision is the pipeline's: script writing, TTS, image + clip
# fetch (fresh_assets.py), competitor sourcing, stabilization, timeline, render.
# The user does not pick voices, workers, bitrates, backdrops, or per-scene
# assets. Enforced in: the way this MD is loaded into any new session.

## RULE 18: Output Size Without Quality Loss — Concat Uses NVENC HQ, Not VBR-Fast
# The final concat re-encode (see RULE 15 fix) must produce a smaller file at
# the same perceived visual quality as the segment renders. Segment rendering
# still runs at NVENC p1 for speed; the FINAL concat encode switches to a
# tighter tune:
#   -c:v h264_nvenc -preset p5 -rc vbr -cq 21 -b:v 0
#   -maxrate 4500k -bufsize 9000k -profile:v high -bf 3 -spatial-aq 1 -aq-strength 8
#   -pix_fmt yuv420p -movflags +faststart
#   -c:a aac -b:a 128k -ar 44100  (voice is dialogue, 128k AAC is transparent)
# Result on a 30-min 1080p run: ~350-450 MB (was ~640-830 MB) with no visible
# quality drop and voiceover fully clear. Enforced in: render_engine.py
# concat_segments + build_audio_matrix.

## RULE 16: Reusable Named Effect Looks
# The pipeline ships with a catalogue of named grades in looks.py. Pick one
# per video with `--look <name>` or `"look": "<name>"` in the topic config.
# Original looks:  vintage, clean, warm, noir, none
# Effect presets (added Sep 12):
#   noise_soft      - light even film grain, no color shift
#   black_noise     - heavy grain in shadows + crushed blacks + vignette
#   grainy          - 16mm-style cinematic grain + subtle warmth
#   gloom_grain     - moody dark + heavy grain + steep vignette + desat
#   color_off       - drained/faded retro wash, low sat + lifted blacks
#   vignette_only   - dark corner vignette, no grain, faithful color
#   documentary_bw  - B&W + grain + vignette (matches Elvis/Dolly ref)
#   cinematic_warm  - warm amber lift + subtle grain + soft vignette
# Preview any / all on a sample image before committing:
#   python look_preview.py --image "path/to/sample.jpg"
# Writes preview_<look>.jpg + preview_grid.jpg to a look_previews/ folder.

## RULE 15: Render Worker Cap Respects NVENC Session Limit
# RTX 3070 Ti (and every consumer NVIDIA GPU) has a stock cap of ~3-5 concurrent
# NVENC sessions. Above 6 render workers, ffmpeg calls start queuing / timing
# out and even the fallback SW encode chokes waiting for GPU. Keep --workers <= 6
# for h264_nvenc. If a segment does time out, a software libx264 fallback runs
# so the pipeline never crashes on isolated failures.
# - Default: --workers 6 (locked in pipeline.py argparse).
# - Fallback: libx264 veryfast crf=22 (avoids NVENC entirely for the retry).
# - No exception may escape the worker — enforced in render_engine.py by wrapping
#   the whole subprocess flow in try/except (see _render_segment).

## RULE 14: Competitor-Sourced Clips Play Inside A Grid-Card Frame
# Any clip whose filename starts with `comp_` (i.e. sliced from a competitor
# YouTube via fresh_assets.py) MUST render inside a grid/sparkle backdrop with
# a white-bordered rectangular frame — NOT full-frame. This:
#   1. Makes reused footage read as our own graphic composition (fingerprint
#      change; avoids visual duplication issues with the source channel).
#   2. Matches the premium documentary card look (RULE 10, style 1/style_sparkle).
# - Backdrop: cycled from assets/grids/*.png (dark blue / editorial red / mono etc).
# - Clip box: ~72% of frame width, centred, white 8px border, subtle drop shadow.
# - Enforced in: render_engine.py (clip branch detects `comp_` prefix → framed path).

## RULE 13: Voiceover via ai33pro v3 (Primary TTS)
# Every Royal-niche video's narration is generated by ai33pro's v3 endpoint. This
# is the ONLY provider we ship on. edge-tts / twospeaker remain as fallbacks but
# are not used in production.
# - Endpoint:  POST https://api.ai33.pro/v3/text-to-speech (multipart FormData)
# - Auth:      xi-api-key: $VOICEOVER_API_KEY (from Royal/.env or apis/ai33pro.env)
# - Voice ID:  elevenlabs_SAz9YHcvj6GT2YYXdXww (see royal_config.json "voice_id")
# - Speed:     0.95 (config "speed"); user default — do not change without approval.
# - Volume:    vo_volume 2.10 (config "vo_volume"); alimiter ceiling 0.95 keeps peaks safe.
# - with_transcript=true is mandatory so RULE 6 (word-level SRT sync) works.
# - Polling:   GET /v3/task/{id} until status='done', then download audio_url + srt_url.
# - Rate limit: 10/s burst 20 — the engine caps concurrent chunk workers at 6.
# - Enforced in: voiceover_engine.py process_chunk_ai33pro + synthesize (ai33pro branch),
#   pipeline.py (tts_provider default "ai33pro", VOICEOVER_API_KEY read from env).

## RULE 6 (REVISED): Word-Level SRT Anchors For Visual Sync
# ai33pro returns a per-chunk SRT alongside each mp3. The engine concatenates
# them (with running audio-offset shifts) into a single voiceover.srt next to
# voiceover.mp3. Pipeline picks up that SRT and passes it to the TimelineEngine
# so the semantic matcher can place a person/place/event visual at the exact
# second their name is spoken — not just within the paragraph.
# - If a specific token (name, place, event) lands at 0.4–0.6s in a caption
#   window, the typography/photo swap is placed exactly there (word-level cue).
# - Without the SRT the matcher falls back to per-chunk boundaries (paragraph
#   granularity, ~5% wrong-person). With the SRT the wrong-person rate drops to
#   near zero on named-subject slots (measured on Video 1 with SRT provided).
# - Enforced in: voiceover_engine.py (_shift_srt merges chunks with offsets),
#   pipeline.py (auto-detects voiceover.srt and passes as srt_path).

## RULE 12: Clip Segments Use Native Duration (no loop, no stretch)
# A clip segment's length = the clip's own footage length (<= slot, minus a small
# tail), so a plain -t trim fills it with continuous footage. Looping a 2-3s clip
# into a ~5s slot created a jump-cut seam every loop that read as shake. Images
# still use 4.5-5.8s Ken Burns slots; the timeline packs more clip segments to
# keep total = voiceover length.
# - Enforced in: timeline_engine.py (_clip_seg_dur) + render_engine.py (clip path,
#   no -stream_loop). Quarantined-shaky clips (RULE 9) never enter the pool.
