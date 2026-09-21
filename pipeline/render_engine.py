"""
Pure GPU NVENC Rendering Engine.

Renders every timeline segment in parallel with hardware encoding, concatenates
them losslessly, then muxes the multi-track audio matrix (opening soundbite +
boosted master voiceover + ducked background music).

Frame size, pacing and the visual grade are all supplied by the caller - see
looks.py for the named grades. Nothing about the subject of the documentary,
or about how it should look, is baked in here.
"""

import os
import json
import time
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

import looks as looks_module

# Style-upgrade layer (RULES 43-46). Imported lazily-tolerant: the pipeline
# package layout (pipeline.py) and bare-script layout (tests) differ.
try:
    from style.signature_grade import grade_filter
    from style.watermark import watermark_filter
    from style.commentator_panel import (
        build_panel_filter, make_panel_background, detect_fg_kind)
    _STYLE_OK = True
except ImportError:  # pragma: no cover - style layer missing
    _STYLE_OK = False
    grade_filter = watermark_filter = None
    build_panel_filter = make_panel_background = detect_fg_kind = None


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def probe_duration(path):
    """Return media duration in seconds, or 0.0 if it cannot be probed."""
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True)
    try:
        return float(res.stdout.strip())
    except ValueError:
        return 0.0


def _join(*parts):
    """Comma-join filter fragments, dropping the empty ones."""
    return ",".join(p for p in parts if p)


def motion_wheel(num, static_share=0.17, pan_share=0.08):
    """Distribute static, pan, zoom-in, zoom-out evenly across shots."""
    B = 12
    nS = max(0, min(B, int(round((static_share or 0.17) * B))))
    nP = max(0, min(B - nS, int(round((pan_share or 0.08) * B))))
    w = [None] * B
    for k in range(nS):
        idx = int(round((k + 0.5) * B / max(1, nS))) % B
        while w[idx] is not None:
            idx = (idx + 1) % B
        w[idx] = 'static'
    for k in range(nP):
        idx = int(round((k + 0.5) * B / max(1, nP))) % B
        while w[idx] is not None:
            idx = (idx + 1) % B
        w[idx] = 'pan'
    flip = 0
    for i in range(B):
        if w[i] is None:
            w[i] = 'out' if (flip % 2) else 'in'
            flip += 1
    return w[num % B]


class RenderEngine:
    """Renders a timeline JSON into a finished, muxed MP4."""

    def __init__(self, work_dir, bgm_path=None, workers=6,
                 width=1920, height=1080, fps=30,
                 encoder="h264_nvenc", preset="p1",
                 bitrate="2500k", maxrate="3500k", bufsize="5000k",
                 vo_volume=1.75, bgm_volume=0.08, opening_volume=1.5,
                 limiter_ceiling=0.95, hwaccel="cuda",
                 look=None, look_overrides=None, subtitle_path=None,
                 channel_name="ROYAL INSIDER", watermark=True, badge_path=None,
                 badge_display_px=140, badge_margin_px=24,
                 signature_grade=True, grade_grain=9,
                 commentator_panel=True, **kwargs):
        self.work_dir = work_dir
        self.bgm_path = bgm_path if bgm_path and os.path.exists(bgm_path) else None
        if bgm_path and not self.bgm_path:
            log(f"WARNING: BGM not found, continuing without it: {bgm_path}")
        self.workers = int(workers)

        self.W = int(width)
        self.H = int(height)
        self.fps = int(fps)
        self.encoder = encoder
        self.preset = preset
        self.bitrate = bitrate
        self.maxrate = maxrate
        self.bufsize = bufsize

        self.vo_volume = float(vo_volume)
        self.bgm_volume = float(bgm_volume)
        self.opening_volume = float(opening_volume)
        self.limiter_ceiling = float(limiter_ceiling) if limiter_ceiling else 0.0
        self.hwaccel = hwaccel
        # Linux-port (2026-09-20): CPU-only box, no NVIDIA GPU. When a
        # software encoder is selected, drop CUDA hwaccel and NVENC-only
        # flags everywhere (segments, concat).
        self.cpu_mode = (encoder != "h264_nvenc")
        if self.cpu_mode:
            self.hwaccel = "none"

        self.look = looks_module.resolve(look, look_overrides)
        self.fade_s = float(self.look.get("fade_s") or 0.25)
        self.zoom_per_sec = float(self.look.get("zoom_per_sec") or 0.010)

        self.segments_dir = os.path.join(work_dir, "segments")
        self.cache_dir = os.path.join(work_dir, "image_cache")
        self.subtitle_path = subtitle_path if subtitle_path and os.path.exists(subtitle_path) else None
        if subtitle_path and not self.subtitle_path:
            log(f"WARNING: subtitle file not found, captions will be off: {subtitle_path}")

        # Style-upgrade layer (RULES 43-46): signature grade + channel badge
        # are applied once at the final mux; the commentator panel is a
        # per-segment treatment (see _render_commentator_segment).
        self.channel_name = channel_name or "ROYAL INSIDER"
        self.watermark = bool(watermark)
        self.badge_path = badge_path if badge_path and os.path.exists(badge_path) else None
        if watermark and badge_path and not self.badge_path:
            log(f"WARNING: badge not found, watermark off: {badge_path}")
            self.watermark = False
        self.badge_display_px = int(badge_display_px or 140)
        self.badge_margin_px = int(badge_margin_px or 24)
        self.signature_grade = bool(signature_grade)
        self.grade_grain = int(grade_grain or 0)
        self.commentator_panel = bool(commentator_panel)
        self._panel_bg = None  # lazily generated per work_dir

    def _stage_subtitle(self):
        """Copy the subtitle to a special-char-free temp dir and return
        (bare_filename, temp_dir). The mux runs with cwd=temp_dir and references
        the subtitle by name only, sidestepping the ffmpeg filter parser's problems
        with Windows drive colons, spaces and apostrophes (e.g. "Camilla's Future")."""
        import tempfile, shutil
        ext = os.path.splitext(self.subtitle_path)[1] or ".ass"
        tmp = tempfile.gettempdir()
        name = f"royal_captions{ext}"
        shutil.copyfile(self.subtitle_path, os.path.join(tmp, name))
        return name, tmp

    # ----------------------------------------------------------- filtergraph

    def _decode_args(self):
        """Extra ffmpeg input flags for HW decode; empty on CPU-only boxes."""
        return [] if self.hwaccel == "none" else ["-hwaccel", self.hwaccel]

    def _gpu_encode_args(self):
        if self.cpu_mode:
            # Plain software encode: NVENC-only flags (-preset pX, -rc vbr,
            # -b:v CBR ladder) are invalid for libx264.
            return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                    "-pix_fmt", "yuv420p",
                    "-r", str(self.fps), "-an"]
        return ["-c:v", self.encoder, "-preset", self.preset, "-rc", "vbr",
                "-b:v", self.bitrate, "-maxrate", self.maxrate,
                "-bufsize", self.bufsize, "-pix_fmt", "yuv420p",
                "-r", str(self.fps), "-an"]

    _backdrop_cache = None
    def _backdrop_pool(self):
        """{'grid':[...], 'sparkle':[...]} full-frame backdrops for framed_clip
        composites. Split per subfolder so the two card styles (grid vs sparkle)
        pull from their intended visual family. Cached per process."""
        if RenderEngine._backdrop_cache is not None:
            return RenderEngine._backdrop_cache
        here = os.path.dirname(os.path.abspath(__file__))
        pools = {"grid": [], "sparkle": []}
        for sub, key in (("grids", "grid"), ("sparkle-backgrounds", "sparkle")):
            d = os.path.join(here, "assets", sub)
            if os.path.isdir(d):
                for f in sorted(os.listdir(d)):
                    if f.lower().endswith((".jpg", ".jpeg", ".png")):
                        pools[key].append(os.path.join(d, f))
        RenderEngine._backdrop_cache = pools
        return pools

    @staticmethod
    def _segment_ok(path):
        """A rendered segment is 'ok' only if ffprobe can read a positive
        duration. Simple existence/size checks miss the moov-atom-missing case
        that happens when ffmpeg is killed mid-write; those files pass concat
        as inputs but silently truncate the whole output."""
        if not path or not os.path.exists(path) or os.path.getsize(path) < 2000:
            return False
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error",
                 "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, timeout=8)
            return r.returncode == 0 and float((r.stdout or "0").strip() or 0) > 0.1
        except Exception:
            return False

    def _pick_backdrop_for(self, idx, style):
        pools = self._backdrop_pool()
        pool = pools.get(style) or pools["grid"] or pools["sparkle"]
        if not pool:
            return None
        return pool[idx % len(pool)]

    def _fades(self, dur):
        out_at = max(0.0, dur - self.fade_s)
        return f"fade=t=in:st=0:d={self.fade_s},fade=t=out:st={out_at:.4f}:d={self.fade_s}"

    def _to_png(self, img_path):
        """WebP sources are decoded once to PNG; other formats pass through."""
        if not img_path or not os.path.exists(img_path):
            return img_path
        if not img_path.lower().endswith(".webp"):
            return img_path
        os.makedirs(self.cache_dir, exist_ok=True)
        out_png = os.path.join(
            self.cache_dir, os.path.splitext(os.path.basename(img_path))[0] + ".png")
        if not os.path.exists(out_png) or os.path.getsize(out_png) == 0:
            subprocess.run(["ffmpeg", "-y", "-i", img_path, out_png], capture_output=True)
        return out_png

    def _fit(self, w, h, tag=""):
        """Fit any aspect ratio into w x h without leaving dead black bars.

        A portrait photograph in a landscape frame used to be padded with solid
        black down both sides, which is the single most obvious flaw in the
        finished video. "blur" instead fills the surround with a scaled-up,
        blurred, slightly darkened copy of the same frame.
        """
        mode = self.look["fill_mode"]
        fit = f"scale={w}:{h}:force_original_aspect_ratio=decrease"

        if mode == "crop":
            # Fill the frame completely, losing whatever falls outside it.
            return (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                    f"crop={w}:{h},setsar=1")

        if mode != "blur":
            return (f"{fit},pad={w}:{h}:trunc((ow-iw)/2):trunc((oh-ih)/2):black,"
                    f"setsar=1")

        sigma = float(self.look["fill_blur"])
        dim = float(self.look["fill_dim"])
        # Blurring at full resolution is the single most expensive filter in the
        # chain. Shrinking first, blurring the thumbnail, then scaling back up
        # is visually identical once blurred and roughly six times cheaper, so
        # sigma is divided by the same factor to keep the same apparent blur.
        shrink = max(1, int(self.look["fill_downscale"]))
        bw = max(16, (w // shrink) // 2 * 2)
        bh = max(16, (h // shrink) // 2 * 2)
        bg, fg, out = f"bg{tag}", f"fg{tag}", f"px{tag}"
        return (
            f"split[{bg}][{fg}];"
            f"[{bg}]scale={bw}:{bh}:force_original_aspect_ratio=increase,"
            f"crop={bw}:{bh},gblur=sigma={max(0.5, sigma / shrink):.3f},"
            f"scale={w}:{h}:flags=bilinear,eq=brightness=-{dim:.3f}[{out}];"
            f"[{fg}]{fit}[{fg}s];"
            f"[{out}][{fg}s]overlay=(W-w)/2:(H-h)/2,setsar=1"
        )

    # ------------------------------------------------ zero-shake Ken Burns

    def _ken_burns(self, num, dur, is_graphic=False, postcard=False):
        """Zero-shake sub-pixel motion via perspective interpolation=cubic filter.

        Uses the perspective filter instead of zoompan to avoid whole-pixel
        truncation that caused visible shake (sd 0.44px per frame).

        Key rules:
        - CW is always a multiple of 16
        - zoomPerSec = 0.010 (rate, not total zoom)
        - Motion wheel: 17% static, 8% pan, rest alternating zoom-in/zoom-out
        """
        fps = self.fps
        W, H = self.W, self.H
        n = max(1, int(round(dur * fps)))
        N1 = max(1, n - 1)

        per_sec = self.zoom_per_sec
        z = min(0.20, max(0.012, per_sec * dur)) if per_sec > 0 else 0.04
        move = motion_wheel(num, static_share=0.17, pan_share=0.08)

        grade = (self.look["graphic_grade"] if is_graphic
                 else _join(self.look["postcard_eq"] if postcard else "",
                            self.look["grade"]))

        # Face-friendly crop: for portrait sources scaled up to fill 16:9, the
        # default center-crop chops off the head. Bias the vertical crop toward
        # the top 30% of the source frame so faces survive.
        _crop_y = "(ih-oh)*0.15"

        if z <= 0.001 or move == 'static':
            fit = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                   f"crop={W}:{H}:(iw-ow)/2:{_crop_y},setsar=1")
            return _join(fit, grade, self._fades(dur))

        # CW must be multiple of 16
        CW = int(round(W * (1.0 + z) / 16.0) * 16)
        CH = int(round(CW * H / float(W)))

        if move in ('in', 'out'):
            ax = (CW - W) / 2.0 / N1
            ay = (CH - H) / 2.0 / N1
            p = "on" if move == 'in' else f"({N1}-on)"
            L = f"{ax:.4f}*{p}"
            T = f"{ay:.4f}*{p}"
            R = f"{CW}-{ax:.4f}*{p}"
            B = f"{CH}-{ay:.4f}*{p}"
        else:
            # pan
            sx = (CW - W) / float(N1)
            ty = (CH - H) / 2.0
            p = f"({N1}-on)" if (num % 2) else "on"
            L = f"{sx:.4f}*{p}"
            T = f"{ty:.4f}"
            R = f"{sx:.4f}*{p}+{W}"
            B = f"{ty + H:.4f}"

        persp = (f"perspective=eval=frame:sense=source:interpolation=cubic:"
                 f"x0='{L}':y0='{T}':x1='{R}':y1='{T}':x2='{L}':y2='{B}':x3='{R}':y3='{B}'")

        fit = (f"scale={CW}:{CH}:force_original_aspect_ratio=increase,"
               f"crop={CW}:{CH}:(iw-ow)/2:(ih-oh)*0.15")
        scale_out = f"scale={W}:{H}:flags=lanczos,setsar=1"

        return _join(fit, persp, scale_out, grade, self._fades(dur))

    # -------------------------------------------------- commentator panel

    def _panel_bg_path(self):
        """Generate (once per work_dir) the commentator panel background PNG."""
        if self._panel_bg and os.path.exists(self._panel_bg):
            return self._panel_bg
        out = os.path.join(self.work_dir, "panel_bg.png")
        if not os.path.exists(out):
            make_panel_background(out, width=self.W, height=self.H)
            log(f"Panel background generated: {out}")
        self._panel_bg = out
        return out

    def _render_commentator_segment(self, seg):
        """RULE 46: render one commentator/quote segment inside the
        frosted-glow panel on dark navy. Returns (index, path, ok, elapsed,
        error) like _render_segment."""
        idx = seg["index"]
        out_file = os.path.join(self.segments_dir, f"seg_{idx:04d}.mp4")
        dur = float(seg["duration"])
        src = seg.get("file")
        started = time.time()

        if not src or not os.path.exists(src):
            return idx, out_file, False, 0.0, f"source missing: {src}"
        try:
            fg_kind = detect_fg_kind(src)
        except ValueError:
            fg_kind = "video" if seg.get("type") == "clip" else "image"

        bg = self._panel_bg_path()
        fc = build_panel_filter(fg_kind=fg_kind, duration=dur, fps=self.fps)
        tail = _join(self.look["grade"], self._fades(dur), "format=yuv420p")
        if tail:
            fc = f"{fc};[vout]{tail}[v]"
            outlabel = "[v]"
        else:
            outlabel = "[vout]"
        if fg_kind == "image":
            fg_args = ["-loop", "1", "-framerate", str(self.fps), "-i", src]
        else:
            fg_args = self._decode_args() + ["-ss", "0", "-t", str(dur),
                                             "-i", src]
        cmd = (["ffmpeg", "-y", "-loop", "1", "-framerate", str(self.fps),
                "-i", bg] + fg_args +
               ["-filter_complex", fc, "-map", outlabel,
                "-t", str(dur)] + self._gpu_encode_args() + [out_file])
        try:
            res = subprocess.run(cmd, capture_output=True, text=True,
                                 errors="replace", timeout=120)
            elapsed = time.time() - started
            if res.returncode != 0 or not self._segment_ok(out_file):
                tail_err = (res.stderr or "").strip().splitlines()[-3:]
                if os.path.exists(out_file):
                    try:
                        os.remove(out_file)
                    except OSError:
                        pass
                return idx, out_file, False, elapsed, " | ".join(tail_err) or "ffmpeg failed"
            return idx, out_file, True, elapsed, None
        except Exception as e:
            return idx, out_file, False, time.time() - started, f"worker exc: {e}"

    # -------------------------------------------------------------- segments

    def _render_segment(self, seg):
        """Render one segment. Returns (index, path, ok, elapsed, error)."""
        idx = seg["index"]
        out_file = os.path.join(self.segments_dir, f"seg_{idx:04d}.mp4")
        dur = float(seg["duration"])
        src = seg.get("file")
        started = time.time()

        if not src or not os.path.exists(src):
            return idx, out_file, False, 0.0, f"source missing: {src}"

        gpu = self._gpu_encode_args()
        stype = seg.get("type")

        # RULE 46: commentator/quote/expert segments render inside the
        # frosted-glow panel (takes precedence over the RULE 14 grid-card
        # framing for comp_ clips).
        if seg.get("style") == "commentator" and self.commentator_panel and _STYLE_OK:
            return self._render_commentator_segment(seg)

        if stype == "headline":
            vf = _join(
                self._fit(self.W, self.H),
                f"drawbox=x=0:y=0:w=iw:h=ih:"
                f"color={self.look['border_color']}@0.95:t=4",
                self.look["grade"], self._fades(dur))
            cmd = ["ffmpeg", "-y", "-ss", "0", "-t", str(dur), "-i", src,
                   "-vf", vf] + gpu + [out_file]
        elif stype == "image":
            png = self._to_png(src)
            n_frames = max(1, int(round(dur * self.fps)))
            vf = self._ken_burns(idx, dur,
                                 is_graphic=(seg.get("section") == "custom_graphic"),
                                 postcard=bool(seg.get("postcard")))
            # Use -framerate (not just -loop 1) and -frames:v N (not -t dur)
            # to prevent frame doubling and ensure exact frame count
            cmd = ["ffmpeg", "-y", "-loop", "1", "-framerate", str(self.fps),
                   "-i", png, "-vf", vf, "-frames:v", str(n_frames)] + gpu + [out_file]
        elif stype == "clip":
            # RULE 14: competitor-sourced clips (filename prefix "comp_") play
            # inside a rotating grid/sparkle backdrop with a bordered box, so
            # reused footage reads as an original composite. Native royal_clips
            # keep the plain full-frame path.
            fname = os.path.basename(src)
            has_backdrops = any(self._backdrop_pool().values())
            is_intro_native = (seg.get("section") == "opening_intro_native")
            if is_intro_native:
                # RULE 34: the intro plays FULL-FRAME (no framing card) with
                # aggressive top+bottom crop to strip any channel logo /
                # lower-third watermark. Audio is muted here — build_audio_matrix
                # extracts the source clip's own audio track separately for the
                # first `lead_s` seconds so the viewer hears the found footage
                # before the narrator's voiceover kicks in.
                vf = _join(
                    "crop=iw:ih*0.70:0:ih*0.12",           # 12% top + 18% bottom
                    f"scale={self.W}:{self.H}:force_original_aspect_ratio=increase,"
                    f"crop={self.W}:{self.H}",
                    self._fades(dur),
                )
                cmd = (["ffmpeg", "-y"] + self._decode_args() + ["-ss", "0",
                        "-t", str(dur), "-i", src, "-vf", vf] + gpu + [out_file])
            elif fname.startswith("comp_") and has_backdrops:
                # Even idx -> grid card look; odd -> sparkle card look.
                style = "sparkle" if (idx % 2 == 1) else "grid"
                bg = self._pick_backdrop_for(idx, style)
                inner_w = int(self.W * (0.62 if style == "sparkle" else 0.78))
                inner_h = int(self.H * (0.72 if style == "sparkle" else 0.78))
                inner_w -= inner_w % 2; inner_h -= inner_h % 2
                border = 8
                # Source-clip prep BEFORE the framing crop:
                #  * drop the top 12% (channel logo / handle in the header) AND
                #    the bottom 18% (burned-in captions / lower-third watermark)
                #    of the source frame — keep only the middle 70%.
                #  * cover-crop the remaining region to the card box.
                clip_chain = (f"[1:v]crop=iw:ih*0.70:0:ih*0.12,"
                              f"scale={inner_w}:{inner_h}:force_original_aspect_ratio=increase,"
                              f"crop={inner_w}:{inner_h},"
                              f"pad={inner_w + 2*border}:{inner_h + 2*border}:{border}:{border}:color=white[card]")
                bg_chain = f"[0:v]scale={self.W}:{self.H}:force_original_aspect_ratio=increase,crop={self.W}:{self.H}"
                if style == "sparkle":
                    bg_chain += ",gblur=sigma=2"
                bg_chain += "[bg]"
                ox = (self.W - inner_w - 2*border) // 2
                oy = (self.H - inner_h - 2*border) // 2
                grade_and_fades = _join(self.look["grade"], self._fades(dur))
                fc = f"{bg_chain};{clip_chain};[bg][card]overlay={ox}:{oy}:format=auto[ov]"
                if grade_and_fades:
                    fc += f";[ov]{grade_and_fades}[vout]"
                    outlabel = "[vout]"
                else:
                    outlabel = "[ov]"
                cmd = (["ffmpeg", "-y",
                        "-loop", "1", "-framerate", str(self.fps), "-i", bg,
                        "-ss", "0", "-t", str(dur), "-i", src,
                        "-filter_complex", fc,
                        "-map", outlabel,
                        "-t", str(dur)] + gpu + [out_file])
            else:
                vf = _join(self._fit(self.W, self.H), self.look["grade"],
                           self._fades(dur))
                # The timeline sizes clip segments to each clip's native length
                # (<= its real duration), so a plain -t trim fills the slot with
                # continuous footage. No -stream_loop: looping a 2-3s clip to a
                # longer slot created a jump-cut seam every loop that read as shake.
                cmd = (["ffmpeg", "-y"] + self._decode_args() + ["-ss", "0",
                        "-t", str(dur), "-i", src, "-vf", vf] + gpu + [out_file])
        else:
            return idx, out_file, False, 0.0, f"unknown segment type: {stype!r}"

        # Wrap the whole subprocess flow so NO exception escapes the worker —
        # a timeout in one segment must never crash the pool of 400+ segments.
        try:
            try:
                res = subprocess.run(cmd, capture_output=True, text=True,
                                     errors="replace", timeout=90)
            except subprocess.TimeoutExpired:
                elapsed = time.time() - started
                log(f"Segment {idx} FFmpeg timed out (>90s), retrying simple libx264 render...")
                # Fallback: software libx264 (avoids NVENC session contention
                # under high worker concurrency) with plain scale+crop, no
                # perspective / grade — a "just get something on disk" pass.
                fallback_vf = f"scale={self.W}:{self.H}:force_original_aspect_ratio=increase,crop={self.W}:{self.H}"
                sw = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                      "-pix_fmt", "yuv420p", "-r", str(self.fps), "-an"]
                if stype == "image":
                    fallback_cmd = ["ffmpeg", "-y", "-loop", "1",
                                    "-framerate", str(self.fps),
                                    "-i", png, "-vf", fallback_vf,
                                    "-frames:v", str(n_frames)] + sw + [out_file]
                elif stype == "clip":
                    fallback_cmd = ["ffmpeg", "-y", "-ss", "0", "-t", str(dur),
                                    "-i", src, "-vf", fallback_vf] + sw + [out_file]
                else:
                    fallback_cmd = ["ffmpeg", "-y", "-i", src,
                                    "-vf", fallback_vf, "-t", str(dur)] + sw + [out_file]
                try:
                    subprocess.run(fallback_cmd, capture_output=True, text=True,
                                   errors="replace", timeout=45)
                except subprocess.TimeoutExpired:
                    pass
                good = self._segment_ok(out_file)
                if not good and os.path.exists(out_file):
                    try: os.remove(out_file)
                    except OSError: pass
                return idx, out_file, good, elapsed, None if good else "timed out (both)"
            elapsed = time.time() - started
            if res.returncode != 0 or not self._segment_ok(out_file):
                tail = (res.stderr or "").strip().splitlines()[-3:]
                if os.path.exists(out_file):
                    try: os.remove(out_file)
                    except OSError: pass
                return idx, out_file, False, elapsed, " | ".join(tail) or "ffmpeg failed"
            return idx, out_file, True, elapsed, None
        except Exception as e:
            return idx, out_file, False, time.time() - started, f"worker exc: {e}"

    def render_segments(self, segments, resume=True):
        """Render all segments in parallel. Returns (ok, failures, seconds)."""
        os.makedirs(self.segments_dir, exist_ok=True)

        ok, todo = {}, []
        for s in segments:
            path = os.path.join(self.segments_dir, f"seg_{s['index']:04d}.mp4")
            if resume and self._segment_ok(path):
                ok[s["index"]] = path
            else:
                # Drop any partial/corrupt file so the retry starts clean.
                if os.path.exists(path):
                    try: os.remove(path)
                    except OSError: pass
                todo.append(s)

        if ok:
            log(f"Reusing {len(ok)} segments already on disk.")
        log(f"Rendering {len(todo)} segments on {self.encoder} "
            f"at {self.W}x{self.H}@{self.fps} with {self.workers} workers...")

        failures, times = [], []
        started = time.time()

        if todo:
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                futures = {pool.submit(self._render_segment, s): s for s in todo}
                done = 0
                for fut in as_completed(futures):
                    idx, path, good, elapsed, err = fut.result()
                    done += 1
                    times.append(elapsed)
                    if good:
                        ok[idx] = path
                    else:
                        failures.append((idx, err))
                    if done % 50 == 0 or done == len(todo):
                        avg = sum(times) / max(1, len(times))
                        log(f"  {done}/{len(todo)} segments (avg {avg:.3f}s/seg, "
                            f"{len(failures)} failed).")

        total = time.time() - started
        log(f"Segment rendering finished in {total:.2f}s ({total / 60:.2f} min).")
        return ok, failures, total

    # ------------------------------------------------------------- assembly

    def concat_segments(self, segments, ok, silent_path):
        """Losslessly concatenate rendered segments in timeline order."""
        concat_txt = os.path.join(self.work_dir, "segments_concat.txt")
        written = 0
        with open(concat_txt, "w", encoding="utf-8") as f:
            for seg in segments:
                path = ok.get(seg["index"])
                if not path:
                    continue
                # ffmpeg's concat demuxer resolves relative paths against the
                # concat file's dir, NOT CWD. Passing an absolute POSIX-style
                # path avoids the "doubled prefix" bug when the pipeline is
                # invoked from a parent directory.
                abs_path = os.path.abspath(path).replace("\\", "/")
                f.write("file '%s'\n" % abs_path.replace("'", "'\\''"))
                written += 1

        if written == 0:
            raise RuntimeError("No segments rendered successfully; nothing to concatenate.")

        log(f"Concatenating {written} segments into {os.path.basename(silent_path)}...")
        started = time.time()
        # Re-encode on concat so mixed codec params across segment types (image
        # NVENC vs framed_clip NVENC filter_complex vs libx264 fallback) don't
        # cause the demuxer to silently drop 80% of the timeline (RULE 15 fix).
        # RULE 18: switch the FINAL encode to NVENC HQ mode (p5 + cq=21) so
        # the exported file is 30-45% smaller than the fast p1 segments at the
        # same perceived quality.
        # Linux-port (2026-09-20): CPU fallback uses libx264 CRF instead of
        # NVENC-only flags.
        if self.cpu_mode:
            vcodec = ["-c:v", "libx264", "-preset", "medium", "-crf", "21",
                      "-profile:v", "high",
                      "-pix_fmt", "yuv420p",
                      "-r", str(self.fps), "-an"]
        else:
            vcodec = ["-c:v", self.encoder, "-preset", "p5", "-rc", "vbr",
                      "-cq", "21", "-b:v", "0",
                      "-maxrate", "4500k", "-bufsize", "9000k",
                      "-profile:v", "high", "-bf", "3",
                      "-spatial-aq", "1", "-aq-strength", "8",
                      "-pix_fmt", "yuv420p",
                      "-r", str(self.fps), "-an"]
        res = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt]
            + vcodec + [silent_path],
            capture_output=True, text=True, errors="replace")
        if res.returncode != 0:
            raise RuntimeError(f"Concat failed:\n{res.stderr[-2000:]}")
        return time.time() - started

    def build_audio_matrix(self, silent_path, master_mp3, opening_clip,
                           lead_s, video_duration, final_path):
        """Mux opening soundbite + boosted voiceover + ducked BGM onto the video."""
        inputs = ["-i", silent_path]
        filters = []
        mix = []
        next_idx = 1

        if opening_clip and lead_s > 0 and os.path.exists(opening_clip):
            inputs += ["-ss", "0", "-t", str(lead_s), "-i", opening_clip]
            filters.append(
                f"[{next_idx}:a]volume={self.opening_volume},"
                f"apad=whole_dur={video_duration:.3f}[head_a]")
            mix.append("[head_a]")
            next_idx += 1

        inputs += ["-i", master_mp3]
        delay_ms = int(round(lead_s * 1000))
        vo_chain = f"[{next_idx}:a]"
        if delay_ms > 0:
            vo_chain += f"adelay={delay_ms}|{delay_ms},"
        vo_chain += f"volume={self.vo_volume}[vo]"
        filters.append(vo_chain)
        mix.append("[vo]")
        next_idx += 1

        if self.bgm_path:
            inputs += ["-stream_loop", "-1", "-i", self.bgm_path]
            filters.append(
                f"[{next_idx}:a]volume={self.bgm_volume},"
                f"atrim=0:{video_duration:.3f},asetpts=N/SR/TB[bgm]")
            mix.append("[bgm]")
            next_idx += 1

        if len(mix) > 1:
            # normalize=0 keeps the boosted voiceover at its intended level;
            # amix otherwise divides every input by the number of streams.
            filters.append(
                f"{''.join(mix)}amix=inputs={len(mix)}:duration=longest:"
                f"dropout_transition=0:normalize=0[mixed]")
            out_label = "[mixed]"
        else:
            out_label = mix[0]

        if self.limiter_ceiling > 0:
            # A boosted voiceover summed with BGM overshoots 0 dBFS and clips.
            # level=disabled stops the limiter making up gain afterwards.
            filters.append(
                f"{out_label}alimiter=limit={self.limiter_ceiling}:level=disabled[aout]")
            out_label = "[aout]"

        # Style-upgrade finishing chain (RULES 43-45): styled word captions
        # burned from the voiceover .ass when supplied, then the signature
        # grade, then the channel badge — applied once here at the final mux
        # instead of per segment. The concatenated video starts at t=0 and
        # subtitle timestamps are absolute from the same origin, so caption
        # alignment is exact (RULE 6). Requires a video re-encode, so we drop
        # -c:v copy whenever any treatment is on.
        mux_cwd = None
        vlabel = "0:v"
        if self.subtitle_path:
            subs_name, mux_cwd = self._stage_subtitle()
            filters.append(f"[{vlabel}]subtitles={subs_name}[vsub]")
            vlabel = "vsub"
        if self.signature_grade and _STYLE_OK and grade_filter:
            filters.append(
                f"[{vlabel}]{grade_filter(height=self.H, grain=self.grade_grain)}[vgrade]")
            vlabel = "vgrade"
        if self.watermark and self.badge_path and _STYLE_OK and watermark_filter:
            filters.append(watermark_filter(
                self.badge_path, margin=self.badge_margin_px,
                badge_px=self.badge_display_px, main_label=f"[{vlabel}]"))
            vlabel = "vwm"
        if vlabel == "0:v":
            video_map = "0:v"
            video_codec = ["-c:v", "copy"]
        elif self.cpu_mode:
            # libx264 has no p1/vbr NVENC presets — plain software encode.
            video_map = f"[{vlabel}]"
            video_codec = ["-c:v", "libx264", "-preset", "veryfast",
                           "-crf", "21", "-pix_fmt", "yuv420p"]
        else:
            video_map = f"[{vlabel}]"
            video_codec = ["-c:v", self.encoder, "-preset", self.preset, "-rc", "vbr",
                           "-b:v", self.bitrate, "-maxrate", self.maxrate,
                           "-bufsize", self.bufsize, "-pix_fmt", "yuv420p"]

        cmd = (["ffmpeg", "-y"] + inputs +
               ["-filter_complex", ";".join(filters),
                "-map", video_map, "-map", out_label]
               + video_codec +
               # RULE 18: 128k AAC is transparent for spoken-word dialogue;
               # saves ~5-10 MB per 30-min video vs 192k with no audible change.
               ["-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                "-movflags", "+faststart", "-shortest", final_path])

        log(f"Muxing audio matrix -> {final_path}")
        started = time.time()
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                             cwd=mux_cwd)
        if res.returncode != 0:
            raise RuntimeError(f"Audio mux failed:\n{res.stderr[-2000:]}")
        return time.time() - started

    # ------------------------------------------------------------ entrypoint

    def render_and_mux(self, timeline_json, master_mp3, final_video_path,
                       resume=True):
        """Full stage 3+4: render every segment, concatenate, mux audio."""
        with open(timeline_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        segments = data["segments"]
        lead_s = float(data.get("opening_lead_s", 0.0))

        os.makedirs(os.path.dirname(os.path.abspath(final_video_path)), exist_ok=True)

        log("=" * 60)
        log(f"GPU RENDER: {len(segments)} segments -> {os.path.basename(final_video_path)}")
        log(f"{self.W}x{self.H}@{self.fps} | {self.encoder}/{self.preset} @ "
            f"{self.bitrate} | fill={self.look['fill_mode']}")
        log(f"VO x{self.vo_volume} | BGM "
            f"{'x%s' % self.bgm_volume if self.bgm_path else 'none'} | "
            f"limiter {self.limiter_ceiling or 'off'}")
        log("=" * 60)

        ok, failures, render_t = self.render_segments(segments, resume=resume)

        if failures:
            log(f"WARNING: {len(failures)} of {len(segments)} segments failed to render.")
            for idx, err in failures[:10]:
                log(f"  seg {idx:04d}: {err}")
            if len(ok) < len(segments) * 0.9:
                raise RuntimeError(
                    f"Too many segment failures ({len(failures)}/{len(segments)}); aborting.")

        silent_path = os.path.join(self.work_dir, "video_silent.mp4")
        concat_t = self.concat_segments(segments, ok, silent_path)

        video_duration = probe_duration(silent_path)
        if video_duration <= 0:
            raise RuntimeError(f"Could not probe duration of {silent_path}")

        opening_clip = segments[0]["file"] if segments and segments[0].get("has_audio") else None
        mux_t = self.build_audio_matrix(
            silent_path, master_mp3, opening_clip, lead_s, video_duration, final_video_path)

        size_mb = os.path.getsize(final_video_path) / (1024 * 1024)
        log("=" * 60)
        log(f"EXPORTED: {final_video_path}")
        log(f"Duration {video_duration / 60:.2f} min | Size {size_mb:.2f} MB")
        log(f"Render {render_t:.1f}s | Concat {concat_t:.1f}s | Mux {mux_t:.1f}s")
        log("=" * 60)

        benchmarks = {
            "total_segments": len(segments),
            "segments_rendered": len(ok),
            "segments_failed": len(failures),
            "resolution": f"{self.W}x{self.H}",
            "fps": self.fps,
            "encoder": self.encoder,
            "bitrate": self.bitrate,
            "fill_mode": self.look["fill_mode"],
            "voice_volume": self.vo_volume,
            "bgm": os.path.basename(self.bgm_path) if self.bgm_path else None,
            "bgm_volume": self.bgm_volume if self.bgm_path else None,
            "render_time_sec": round(render_t, 2),
            "concat_time_sec": round(concat_t, 2),
            "mux_time_sec": round(mux_t, 2),
            "final_duration_sec": round(video_duration, 2),
            "final_video_mb": round(size_mb, 2),
            "final_video_path": final_video_path,
        }
        with open(os.path.join(self.work_dir, "render_benchmarks.json"), "w",
                  encoding="utf-8") as f:
            json.dump(benchmarks, f, indent=2)
        return benchmarks
