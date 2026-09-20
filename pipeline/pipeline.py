"""
Master Orchestrator for long-form YouTube documentary automation.

Stage 1  Voiceover synthesis (TwoSpeaker / ElevenLabs async burst TTS)
Stage 2  Narration-aware timeline & asset synchronisation
Stage 3  Pure GPU NVENC segment rendering
Stage 4  Lossless concat + multi-track audio matrix mux
Stage 5  YouTube upload metadata

Subject, framing, pacing and grade are all supplied by the caller - through
--topic-config, through flags, or both. Nothing here is specific to any
documentary.
"""

import os
import sys
import json
import time
import argparse

import config  # noqa: F401  # triggers load_dotenv for VOICEOVER_API_KEY etc.
import looks as looks_module
from voiceover_engine import VoiceoverEngine
from timeline_engine import TimelineEngine, get_duration
from render_engine import RenderEngine
from metadata_engine import MetadataEngine
from semantic_matcher import load_tags

DEFAULT_API_KEY = "vk-30bcf8472580aa90e90c3a7fa9563b1bd269c868a206f1fa"

FRAME_PRESETS = {
    "1080p": (1920, 1080),
    "720p": (1280, 720),
    "1440p": (2560, 1440),
    "4k": (3840, 2160),
    "vertical": (1080, 1920),
    "square": (1080, 1080),
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_topic_config(path):
    if not path:
        return {}
    if not os.path.exists(path):
        sys.exit(f"ERROR: topic config not found: {path}")
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def safe_name(title):
    keep = "".join(ch if (ch.isalnum() or ch in " -_") else "_" for ch in title)
    return keep.strip() or "documentary"


def format_timestamp(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def build_chapters(cfg, total_seconds):
    """Use configured chapters, else evenly spaced placeholders to be reviewed."""
    chapters = cfg.get("chapters")
    if chapters:
        return list(chapters)
    titles = cfg.get("chapter_titles") or ["Introduction", "Early Years",
                                           "The Turning Point", "Rising Stakes",
                                           "The Reckoning", "Legacy"]
    step = total_seconds / max(1, len(titles))
    return [f"{format_timestamp(i * step)} {t}  # PLACEHOLDER - review before upload"
            for i, t in enumerate(titles)]


def parse_args():
    p = argparse.ArgumentParser(
        description="YouTube Long-Form Documentary Production Pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    core = p.add_argument_group("core")
    core.add_argument("--script", required=True, help="Documentary script text file")
    core.add_argument("--output-dir", required=True, help="Destination directory")
    core.add_argument("--title", required=True, help="Documentary title")
    core.add_argument("--topic-config", default=None,
                      help="JSON with captions, clip groups, metadata, asset dirs")

    assets = p.add_argument_group("assets")
    assets.add_argument("--opening-clip", default=None, help="Opening hook clip")
    assets.add_argument("--bgm", default=None, help="Background music file")
    assets.add_argument("--clips-dir", default=None,
                        help="Clip directories (separate multiple with os.pathsep)")
    assets.add_argument("--images-dir", default=None, help="Photo directories")
    assets.add_argument("--grid-dir", default=None, help="Grid background directories")
    assets.add_argument("--topic-assets-dir", default=None,
                        help="Small folder of subject photos, weighted heavily")

    voice = p.add_argument_group("voice")
    voice.add_argument("--voice-id", default=None, help="TTS voice ID")
    voice.add_argument("--api-key", default=None,
                       help="TTS API key (default: VOICEOVER_API_KEY env, else TWOSPEAKER_API_KEY, else built-in)")
    voice.add_argument("--speed", type=float, default=None, help="TTS speech rate (default 0.95)")
    voice.add_argument("--voiceover", default=None,
                       help="Reuse an existing MP3 and skip TTS entirely")
    voice.add_argument("--tts", default=None,
                       choices=["ai33pro", "twospeaker", "edge-tts", "omnivoice", "famespeak"],
                       help="TTS provider (default: ai33pro from config)")
    voice.add_argument("--tts-base-url", default=None,
                       help="Override TTS API base URL")

    frame = p.add_argument_group("frame and pacing")
    frame.add_argument("--frame", choices=sorted(FRAME_PRESETS), default=None,
                       help="Frame size preset (overridden by --width/--height)")
    frame.add_argument("--width", type=int, default=None, help="Frame width")
    frame.add_argument("--height", type=int, default=None, help="Frame height")
    frame.add_argument("--fps", type=int, default=None, help="Frames per second")
    frame.add_argument("--seg-min", type=float, default=None,
                       help="Shortest body segment, seconds")
    frame.add_argument("--seg-max", type=float, default=None,
                       help="Longest body segment, seconds")
    frame.add_argument("--hook-end", type=float, default=None,
                       help="Seconds of front-loaded hook imagery")
    frame.add_argument("--opening-lead", type=float, default=None,
                       help="Length of the opening soundbite, seconds")

    style = p.add_argument_group("look")
    style.add_argument("--look", default=None,
                       help=f"Named grade: {', '.join(looks_module.names())}")
    style.add_argument("--fill-mode", choices=["blur", "black", "crop"], default=None,
                       help="How off-aspect sources fill the frame")
    style.add_argument("--fill-blur", type=float, default=None,
                       help="Blur strength of the fill backdrop")
    style.add_argument("--grade", default=None,
                       help="Raw FFmpeg filter chain, replaces the look's grade")
    style.add_argument("--border-color", default=None,
                       help="Opening-clip border, e.g. 0xdc2626")
    style.add_argument("--fade", type=float, default=None, help="Crossfade seconds")
    style.add_argument("--zoom-per-sec", type=float, default=None,
                       help="Ken Burns zoom rate per second")

    matching = p.add_argument_group("semantic matching")
    matching.add_argument("--no-semantic", action="store_true",
                          help="Disable narration-aware matching (round robin)")
    matching.add_argument("--asset-tags", default=None,
                          help="JSON of {file: [keywords]} enriching asset labels")
    matching.add_argument("--entity-boost", type=float, default=6.0,
                          help="How strongly a named subject pulls in their folder")
    matching.add_argument("--clip-cooldown", type=int, default=15,
                          help="Minimum segments between clips from one source")

    audio = p.add_argument_group("audio")
    audio.add_argument("--vo-volume", type=float, default=2.10, help="Voiceover gain (RULE 13)")
    audio.add_argument("--bgm-volume", type=float, default=0.08, help="Music gain")
    audio.add_argument("--limiter-ceiling", type=float, default=0.95,
                       help="Peak ceiling for the final mix (0 disables)")

    run = p.add_argument_group("run control")
    run.add_argument("--workers", type=int, default=6,
                     help="Parallel GPU workers (RULE 15: 6 is NVENC-safe on consumer GPUs; 8+ risks session saturation)")
    run.add_argument("--encoder", default="h264_nvenc", help="FFmpeg video encoder")
    run.add_argument("--bitrate", default="2500k", help="Target video bitrate")
    run.add_argument("--limit-seconds", type=float, default=None,
                     help="Cap timeline length, for quick smoke tests")
    run.add_argument("--skip-render", action="store_true",
                     help="Build voiceover, timeline and metadata only")
    run.add_argument("--no-resume", action="store_true",
                     help="Re-render segments even if they already exist")
    run.add_argument("--no-subtitles", action="store_true",
                     help="Do not burn narration captions into the video")
    return p.parse_args()


def main():
    args = parse_args()
    cfg = load_topic_config(args.topic_config)

    def pick(cli_value, cfg_key, default=None):
        if cli_value is not None:
            return cli_value
        if cfg.get(cfg_key) is not None:
            return cfg[cfg_key]
        return default

    clips_dir = pick(args.clips_dir, "clips_dir")
    images_dir = pick(args.images_dir, "images_dir")
    grid_dir = pick(args.grid_dir, "grid_dir")
    topic_assets_dir = pick(args.topic_assets_dir, "topic_assets_dir")
    opening_clip = pick(args.opening_clip, "opening_clip")
    bgm = pick(args.bgm, "bgm")

    if not clips_dir and not images_dir:
        sys.exit("ERROR: supply at least --clips-dir or --images-dir "
                 "(or set clips_dir / images_dir in the topic config).")

    # ------------------------------------------------------- frame and pacing
    preset = pick(args.frame, "frame", "1080p")
    pw, ph = FRAME_PRESETS.get(preset, FRAME_PRESETS["1080p"])
    width = int(pick(args.width, "width", pw))
    height = int(pick(args.height, "height", ph))
    fps = int(pick(args.fps, "fps", 30))
    seg_min = float(pick(args.seg_min, "seg_min_s", 4.5))
    seg_max = float(pick(args.seg_max, "seg_max_s", 5.8))
    if seg_max < seg_min:
        sys.exit(f"ERROR: --seg-max ({seg_max}) is below --seg-min ({seg_min}).")
    hook_end = float(pick(args.hook_end, "hook_end_s", 22.5))
    opening_lead = float(pick(args.opening_lead, "opening_lead_s", 0.0))

    # ------------------------------------------------------------------ look
    look_overrides = {
        "grade": pick(args.grade, "grade"),
        "fill_mode": pick(args.fill_mode, "fill_mode"),
        "fill_blur": pick(args.fill_blur, "fill_blur"),
        "border_color": pick(args.border_color, "border_color"),
        "fade_s": pick(args.fade, "fade_s"),
        "zoom_per_sec": pick(args.zoom_per_sec, "zoom_per_sec"),
    }
    try:
        looks_module.resolve(pick(args.look, "look"), look_overrides)
    except ValueError as e:
        sys.exit(f"ERROR: {e}")

    work_dir = os.path.join(args.output_dir, "temp_render_workspace")
    os.makedirs(work_dir, exist_ok=True)

    t_start = time.time()
    log("=" * 60)
    log(f"PRODUCTION PIPELINE: {args.title}")
    log(f"{width}x{height}@{fps} | look={pick(args.look, 'look') or 'vintage'} | "
        f"segments {seg_min}-{seg_max}s")
    log("=" * 60)

    # ---------------------------------------------------------- 1. voiceover
    script_text = None
    if os.path.exists(args.script):
        with open(args.script, "r", encoding="utf-8-sig") as f:
            script_text = f.read()

    srt_path = None
    voice_manifest = None
    if args.voiceover:
        if not os.path.exists(args.voiceover):
            sys.exit(f"ERROR: voiceover not found: {args.voiceover}")
        master_mp3 = args.voiceover
        vo_dur = get_duration(master_mp3)
        log(f"Stage 1 skipped, reusing voiceover: {vo_dur / 60:.2f} min")
        beside_srt = os.path.splitext(master_mp3)[0] + ".srt"
        if os.path.exists(beside_srt):
            srt_path = beside_srt
            log(f"Found voiceover SRT subtitle file ({os.path.basename(srt_path)}).")
        beside = os.path.join(os.path.dirname(master_mp3), "voice_manifest.json")
        if os.path.exists(beside):
            with open(beside, "r", encoding="utf-8-sig") as f:
                voice_manifest = json.load(f).get("chunks")
            log(f"Found voice manifest beside the MP3 ({len(voice_manifest)} chunks).")
    else:
        if script_text is None:
            sys.exit(f"ERROR: script not found: {args.script}")
        log(f"Stage 1: synthesising {len(script_text.split())} words...")
        t0 = time.time()
        # Provider selection driven by --tts (or the topic config's "tts" key).
        # ai33pro is the primary voice for the Royal niche — it returns MP3 +
        # word-level SRT so RULE 6 (per-word visual sync) works end-to-end.
        tts_provider = pick(args.tts, "tts", "ai33pro")
        # Resolve TTS credentials + voice from CLI / config / env, in priority order.
        _vo_id = pick(args.voice_id, "voice_id",
                      "elevenlabs_SAz9YHcvj6GT2YYXdXww" if tts_provider in ("ai33pro", "famespeak")
                      else "gcdNeREzHPJpCf9wnB0l")
        _vo_speed = float(pick(args.speed, "speed", 0.95))
        _api_key = (args.api_key
                    or os.environ.get("FAMESPEAK_API_KEY")
                    or os.environ.get("VOICEOVER_API_KEY")
                    or os.environ.get("TWOSPEAKER_API_KEY")
                    or DEFAULT_API_KEY)
        vo_engine = VoiceoverEngine(
            api_key=_api_key, voice_id=_vo_id, speed=_vo_speed,
            # FameSpeak must always hit its own API even when the topic config
            # still carries the stale ai33pro tts_base_url; an explicit CLI
            # --tts-base-url still wins.
            base_url=(args.tts_base_url
                      or ("https://famespeak.online" if tts_provider == "famespeak" else None)
                      or pick(None, "tts_base_url",
                              "https://api.ai33.pro" if tts_provider == "ai33pro"
                              else "https://api.twospeaker.com")),
            provider=tts_provider)
        master_mp3 = os.path.join(work_dir, "voiceover.mp3")
        master_mp3, vo_dur = vo_engine.synthesize(script_text, work_dir, master_mp3)
        # ai33pro writes a merged voiceover.srt beside the mp3 — pick it up so
        # the timeline matcher gets word-level anchors.
        _beside_srt = os.path.splitext(master_mp3)[0] + ".srt"
        if os.path.exists(_beside_srt):
            srt_path = _beside_srt
            log(f"Found generated SRT with word-level timestamps ({os.path.basename(srt_path)}).")
        log(f"Stage 1 done in {time.time() - t0:.1f}s: "
            f"{vo_dur:.1f}s ({vo_dur / 60:.2f} min) of narration")
        manifest_path = os.path.join(work_dir, "voice_manifest.json")
        if os.path.exists(manifest_path):
            with open(manifest_path, "r", encoding="utf-8-sig") as f:
                voice_manifest = json.load(f).get("chunks")

    timeline_duration = vo_dur
    if args.limit_seconds:
        timeline_duration = min(vo_dur, args.limit_seconds)
        log(f"Timeline capped at {timeline_duration:.1f}s for this run.")

    # ----------------------------------------------------------- 2. timeline
    log("Stage 2: building timeline...")
    t0 = time.time()
    tl_engine = TimelineEngine(
        clips_dir=clips_dir, images_dir=images_dir, grid_dir=grid_dir,
        topic_assets_dir=topic_assets_dir,
        graphics_dir=os.path.join(work_dir, "generated_graphics"),
        topic_config=cfg, clip_cooldown=args.clip_cooldown,
        opening_lead_s=opening_lead, hook_end_s=hook_end,
        seg_min_s=seg_min, seg_max_s=seg_max,
        width=width, height=height,
        semantic=not args.no_semantic, script_text=script_text,
        voice_manifest=voice_manifest, srt_path=srt_path, entity_boost=args.entity_boost,
        asset_tags=load_tags(args.asset_tags or cfg.get("asset_tags")))
    timeline_json = os.path.join(work_dir, "timeline.json")
    timeline = tl_engine.build_timeline(timeline_duration, opening_clip, timeline_json)
    log(f"Stage 2 done in {time.time() - t0:.1f}s")

    # ----------------------------------------------------------- 3+4. render
    final_video_path = os.path.join(args.output_dir, f"{safe_name(args.title)}.mp4")
    if args.skip_render:
        log("Stage 3+4 skipped (--skip-render).")
        bench = {}
    else:
        log("Stage 3+4: GPU rendering and audio mux...")
        # Captions are opt-in. This niche runs without burned-in captions, so the
        # default is OFF; enable per-project with "burn_subtitles": true in the
        # topic config, or force off with --no-subtitles.
        subtitle_path = None
        want_subs = bool(cfg.get("burn_subtitles", False)) and not args.no_subtitles
        if want_subs and srt_path:
            ass_beside = os.path.splitext(srt_path)[0] + ".ass"
            subtitle_path = ass_beside if os.path.exists(ass_beside) else srt_path
            log(f"Captions will be burned in from {os.path.basename(subtitle_path)}.")
        else:
            log("Captions off (burn_subtitles disabled for this niche).")

        _vo_vol = float(pick(args.vo_volume, "vo_volume", 2.10))
        r_engine = RenderEngine(
            work_dir=work_dir, bgm_path=bgm, workers=args.workers,
            width=width, height=height, fps=fps,
            vo_volume=_vo_vol, bgm_volume=args.bgm_volume,
            limiter_ceiling=args.limiter_ceiling,
            encoder=args.encoder, bitrate=args.bitrate,
            look=pick(args.look, "look"), look_overrides=look_overrides,
            subtitle_path=subtitle_path)
        bench = r_engine.render_and_mux(timeline_json, master_mp3, final_video_path,
                                        resume=not args.no_resume)

    # ----------------------------------------------------------- 5. metadata
    total_seconds = bench.get("final_duration_sec") or timeline["total_duration"]
    meta_path = os.path.join(
        args.output_dir,
        f"YOUTUBE_METADATA_{safe_name(args.title).replace(' ', '_').upper()}.txt")
    MetadataEngine.generate_metadata(
        title=cfg.get("youtube_title", args.title),
        alt_titles=cfg.get("alt_titles",
                           [f"The Untold Story of {args.title}",
                            f"Inside the Life of {args.title}"]),
        description=cfg.get("description",
                            f"A full-length documentary exploring {args.title}."),
        chapters=build_chapters(cfg, total_seconds),
        tags=cfg.get("tags", ["Documentary", "Biography", "History"]),
        hashtags=cfg.get("hashtags", ["#Documentary", "#Biography"]),
        out_path=meta_path)
    log(f"Stage 5 done: {meta_path}")

    elapsed = time.time() - t_start
    log("=" * 60)
    log(f"PIPELINE COMPLETE in {elapsed:.1f}s ({elapsed / 60:.2f} min)")
    if not args.skip_render:
        log(f"Video: {final_video_path}")
    log(f"Metadata: {meta_path}")
    log("=" * 60)


if __name__ == "__main__":
    main()
