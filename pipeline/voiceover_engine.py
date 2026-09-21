"""
Universal Multi-Provider Voiceover Engine.
Supports:
1. 'edge-tts'  -> 100% FREE, ZERO Credits, Unlimited, Microsoft Azure Neural Voices (Guy, Christopher, Eric).
2. 'twospeaker' -> ElevenLabs Multi-threaded Async Burst TTS API.
"""

import os, sys, time, json, urllib.request, subprocess, asyncio
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

class VoiceoverEngine:
    def __init__(self, api_key=None, voice_id="en-US-GuyNeural", speed=0.95, base_url="https://api.twospeaker.com", provider="edge-tts"):
        self.api_key = api_key
        self.voice_id = voice_id
        self.speed = speed
        self.base_url = base_url
        self.provider = provider  # "edge-tts" (FREE 0 CREDITS) or "twospeaker"

    def log(self, msg):
        print(f"[{time.strftime('%H:%M:%S')}] [TTS-{self.provider.upper()}] {msg}", flush=True)

    def chunk_script(self, text, min_words=260, max_words=380):
        paras = [p.strip() for p in text.split("\n\n") if p.strip()]
        # If the script uses single-\n between paragraphs (bad format), the
        # split above returns 1-2 giant paragraphs that blow past ai33pro's
        # per-request text limit. Fall back to single-\n splitting when any
        # paragraph is longer than 2x max_words.
        if paras and max(len(p.split()) for p in paras) > 2 * max_words:
            paras = [p.strip() for p in text.split("\n") if p.strip()]
        chunks = []
        curr = []
        curr_words = 0
        for p in paras:
            w_count = len(p.split())
            if curr_words + w_count > max_words and curr_words >= min_words:
                chunks.append("\n\n".join(curr))
                curr = []
                curr_words = 0
            curr.append(p)
            curr_words += w_count
        if curr:
            if curr_words < 60 and chunks:
                chunks[-1] += "\n\n" + "\n\n".join(curr)
            else:
                chunks.append("\n\n".join(curr))
        return chunks

    def download_audio(self, url, out_path, extra_headers=None):
        # Linux-port hardening (2026-09-20): ai33pro's CDN truncates plain
        # urllib reads from this network (IncompleteRead). Stream via
        # requests with retries + Range resume instead.
        headers = {"User-Agent": UA}
        if extra_headers:
            headers.update(extra_headers)
        for attempt in range(4):
            try:
                start = os.path.getsize(out_path) if os.path.exists(out_path) else 0
                h = dict(headers)
                if start:
                    h["Range"] = f"bytes={start}-"
                with requests.get(url, headers=h, timeout=60, stream=True) as r:
                    if start and r.status_code == 200:
                        start = 0  # server ignored Range; restart clean
                    r.raise_for_status()
                    mode = "ab" if (start and r.status_code == 206) else "wb"
                    with open(out_path, mode) as f:
                        for chunk in r.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                if os.path.getsize(out_path) > 10000:
                    return
            except Exception as e:
                self.log(f"download_audio attempt {attempt + 1}/4 failed: {e}")
                time.sleep(2 * (attempt + 1))
        raise Exception(f"download_audio failed after 4 attempts: {url}")

    async def _generate_edge_chunk(self, text, voice_name, out_path, rate_str):
        import edge_tts
        communicate = edge_tts.Communicate(text, voice_name, rate=rate_str)
        await communicate.save(out_path)

    def process_chunk_edge_tts(self, text, chunk_idx, total_chunks, voice_chunks_dir):
        mp3_path = os.path.join(voice_chunks_dir, f"chunk_{chunk_idx:03d}.mp3")
        c_words = len(text.split())
        if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 10000:
            dur = self.get_duration(mp3_path)
            self.log(f"Chunk {chunk_idx}/{total_chunks} cached ({dur:.1f}s).")
            return chunk_idx, mp3_path, c_words, dur, 0.0

        t0 = time.time()
        # Edge TTS rate calculation: speed=0.95 -> -5%
        pct_diff = int(round((self.speed - 1.0) * 100))
        rate_str = f"{pct_diff:+d}%" if pct_diff != 0 else "+0%"
        
        voice_name = self.voice_id if "Neural" in self.voice_id else "en-US-GuyNeural"
        asyncio.run(self._generate_edge_chunk(text, voice_name, mp3_path, rate_str))
        dur = self.get_duration(mp3_path)
        tot_t = time.time() - t0
        self.log(f"Chunk {chunk_idx}/{total_chunks} generated (100% FREE, 0 Credits!) in {tot_t:.1f}s ({dur:.1f}s audio).")
        return chunk_idx, mp3_path, c_words, dur, tot_t

    def process_chunk_ai33pro(self, text, chunk_idx, total_chunks, voice_chunks_dir):
        """ai33pro v3 TTS with word-level SRT transcript (RULE 6 compliance).
        Submits FormData, polls the task endpoint, downloads MP3 + SRT."""
        import requests
        mp3_path = os.path.join(voice_chunks_dir, f"chunk_{chunk_idx:03d}.mp3")
        srt_path = os.path.join(voice_chunks_dir, f"chunk_{chunk_idx:03d}.srt")
        c_words = len(text.split())
        if (os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 10000
                and os.path.exists(srt_path) and os.path.getsize(srt_path) > 20):
            dur = self.get_duration(mp3_path)
            self.log(f"Chunk {chunk_idx}/{total_chunks} cached ({dur:.1f}s, SRT present).")
            return chunk_idx, mp3_path, c_words, dur, 0.0

        t0 = time.time()
        base = self.base_url.rstrip("/")
        submit_url = f"{base}/v3/text-to-speech"
        headers = {"xi-api-key": self.api_key}
        data = {
            "text": text,
            "voice_id": self.voice_id,
            "speed": str(self.speed),
            "with_transcript": "true",
        }
        # Submit, retrying on transient failures + rate limits. Uses a longer
        # exponential-ish backoff so a burst of 5xx / concurrency errors during
        # a many-chunk parallel submission doesn't dead-end after ~30s.
        task_id = None
        for attempt in range(10):
            try:
                r = requests.post(submit_url, headers=headers, data=data, timeout=90)
                if r.status_code == 429:
                    time.sleep(5.0 + attempt * 4.0); continue
                r.raise_for_status()
                j = r.json()
                task_id = j.get("task_id") or (j.get("data") or {}).get("id")
                if task_id: break
            except Exception as e:
                self.log(f"Chunk {chunk_idx} submit retry {attempt+1}: {e}")
                time.sleep(min(60.0, 3.0 + attempt * 3.0))
        if not task_id:
            raise Exception(f"ai33pro chunk {chunk_idx} submit failed after retries")

        # Poll GET /v3/task/{id}
        poll_url = f"{base}/v3/task/{task_id}"
        audio_url = srt_url = None
        for _ in range(120):  # up to ~6 min per chunk
            time.sleep(3.0)
            try:
                pr = requests.get(poll_url, headers=headers, timeout=30)
                if pr.status_code != 200:
                    continue
                pj = pr.json().get("data", {})
                if pj.get("status") == "done":
                    md = pj.get("metadata", {})
                    audio_url = md.get("audio_url")
                    srt_url = md.get("srt_url")
                    break
                if pj.get("status") in ("failed", "error"):
                    raise Exception(f"ai33pro task {task_id} status={pj.get('status')}")
            except Exception:
                time.sleep(2.0); continue
        if not audio_url:
            raise Exception(f"ai33pro chunk {chunk_idx} never returned audio_url")

        # Download mp3
        self.download_audio(audio_url, mp3_path)
        # Download SRT (word-level per ai33pro spec)
        if srt_url:
            try:
                self.download_audio(srt_url, srt_path)
            except Exception as e:
                self.log(f"Chunk {chunk_idx} SRT download failed: {e}")

        dur = self.get_duration(mp3_path)
        tot_t = time.time() - t0
        self.log(f"Chunk {chunk_idx}/{total_chunks} ai33pro ready in {tot_t:.1f}s ({dur:.1f}s audio, SRT={os.path.exists(srt_path)}).")
        return chunk_idx, mp3_path, c_words, dur, tot_t

    def _apply_speed(self, mp3_path):
        """Apply the configured speech rate to a TTS chunk via ffmpeg atempo.

        FameSpeak's API accepts no speed parameter, so without this the
        configured speed was silently ignored and every FameSpeak voiceover
        rendered at 1.0x. Returns the path to use downstream (a cached
        speed-adjusted sibling, so the adjustment is applied exactly once).
        """
        try:
            speed = float(self.speed or 1.0)
        except (TypeError, ValueError):
            speed = 1.0
        if abs(speed - 1.0) < 1e-6:
            return mp3_path
        adj_path = os.path.splitext(mp3_path)[0] + f".s{speed:g}.mp3"
        if not (os.path.exists(adj_path) and os.path.getsize(adj_path) > 10000):
            # atempo only accepts 0.5-2.0 per instance; chain for extremes.
            filters, s = [], speed
            while s < 0.5:
                filters.append("atempo=0.5")
                s /= 0.5
            while s > 2.0:
                filters.append("atempo=2.0")
                s /= 2.0
            filters.append(f"atempo={s:.6g}")
            subprocess.run(
                ["ffmpeg", "-y", "-i", mp3_path, "-filter:a",
                 ",".join(filters), "-b:a", "128k", adj_path],
                capture_output=True, check=True)
            self.log(f"Speech rate x{speed:g} applied -> "
                     f"{os.path.basename(adj_path)}")
        return adj_path

    def process_chunk_famespeak(self, text, chunk_idx, total_chunks, voice_chunks_dir):
        """FameSpeak ElevenLabs TTS (temporary provider while ai33pro credits
        are exhausted). Submits JSON, polls the statusUrl, downloads MP3.
        The API returns the bare ElevenLabs voice ID (no 'elevenlabs_'
        prefix) and provides no word timestamps, so the word-level SRT for
        RULE 6 is produced afterwards by local forced alignment
        (faster-whisper) over the merged voiceover."""
        import requests
        mp3_path = os.path.join(voice_chunks_dir, f"chunk_{chunk_idx:03d}.mp3")
        c_words = len(text.split())
        tot_t = 0.0
        if not (os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 10000):
            t0 = time.time()
            base = (self.base_url or "https://famespeak.online").rstrip("/")
            # FameSpeak needs the bare ElevenLabs voice ID, e.g. the configured
            # "elevenlabs_SAz9YHcvj6GT2YYXdXww" becomes "SAz9YHcvj6GT2YYXdXww".
            vid = (self.voice_id or "").replace("elevenlabs_", "")
            headers = {"Authorization": f"Bearer {self.api_key}"}

            job_id = status_url = None
            for attempt in range(8):
                try:
                    r = requests.post(
                        f"{base}/api/v1/eleven-labs/generations",
                        headers=headers,
                        json={"voiceId": vid, "text": text},
                        timeout=90,
                    )
                    if r.status_code == 429:
                        time.sleep(5.0 + attempt * 5.0); continue
                    if r.status_code == 202:
                        j = r.json()
                        job_id, status_url = j.get("id"), j.get("statusUrl")
                        if job_id and status_url: break
                    else:
                        self.log(f"Chunk {chunk_idx} submit HTTP {r.status_code}: {r.text[:120]}")
                        time.sleep(min(60.0, 4.0 + attempt * 4.0))
                except Exception as e:
                    self.log(f"Chunk {chunk_idx} submit retry {attempt+1}: {e}")
                    time.sleep(min(60.0, 4.0 + attempt * 4.0))
            if not job_id:
                raise Exception(f"famespeak chunk {chunk_idx} submit failed after retries")

            # Poll the statusUrl until COMPLETED.
            audio_rel = None
            for _ in range(120):  # up to ~10 min per chunk
                time.sleep(5.0)
                try:
                    pr = requests.get(f"{base}{status_url}", headers=headers, timeout=30)
                    if pr.status_code != 200:
                        continue
                    pj = pr.json()
                    st = (pj.get("status") or "").upper()
                    if st == "COMPLETED":
                        audio_rel = pj.get("audioUrl")
                        break
                    if st in ("FAILED", "ERROR"):
                        raise Exception(f"famespeak job {job_id} status={st}: {pj.get('error')}")
                except Exception:
                    time.sleep(2.0); continue
            if not audio_rel:
                raise Exception(f"famespeak chunk {chunk_idx} never completed")

            self.download_audio(f"{base}{audio_rel}", mp3_path,
                                extra_headers={"Authorization": f"Bearer {self.api_key}"})
            tot_t = time.time() - t0
            self.log(f"Chunk {chunk_idx}/{total_chunks} famespeak downloaded in {tot_t:.1f}s.")
        # FameSpeak API takes no speed parameter: apply the configured
        # speech rate locally so cfg speed is honoured (was silently 1.0x).
        mp3_path = self._apply_speed(mp3_path)
        dur = self.get_duration(mp3_path)
        self.log(f"Chunk {chunk_idx}/{total_chunks} ready ({dur:.1f}s audio).")
        return chunk_idx, mp3_path, c_words, dur, tot_t

    def _transcribe_word_srt(self, mp3_path, srt_path):
        """Local word-level alignment for the FameSpeak provider (which has
        no transcript API): faster-whisper with word timestamps over the
        merged voiceover, written as a word-level SRT for RULE 6."""
        from faster_whisper import WhisperModel
        self.log("FameSpeak provides no word timestamps; aligning locally with faster-whisper...")
        # Prefer a locally pre-downloaded model (the sandbox proxy breaks
        # huggingface_hub's downloader); fall back to the HF hub id.
        model_ref = os.environ.get(
            "FAMESPEAK_WHISPER_MODEL",
            os.path.expanduser("~/workspace/royal/models/faster-whisper-base"),
        )
        if not os.path.isdir(model_ref):
            model_ref = "base"
        model = WhisperModel(model_ref, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(mp3_path, word_timestamps=True,
                                           language="en", beam_size=5)
        def ts(s):
            h = int(s // 3600); m = int((s % 3600) // 60)
            sec = int(s % 60); ms = int(round((s - int(s)) * 1000))
            return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
        n = 0
        with open(srt_path, "w", encoding="utf-8") as f:
            for seg in segments:
                for w in (seg.words or []):
                    n += 1
                    f.write(f"{n}\n{ts(w.start)} --> {ts(w.end)}\n{w.word.strip()}\n\n")
        self.log(f"Word-level SRT written: {srt_path} ({n} words).")
        return n

    def process_chunk_omnivoice(self, text, chunk_idx, total_chunks, voice_chunks_dir, ref_voice=None):
        mp3_path = os.path.join(voice_chunks_dir, f"chunk_{chunk_idx:03d}.mp3")
        c_words = len(text.split())
        if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 10000:
            dur = self.get_duration(mp3_path)
            self.log(f"Chunk {chunk_idx}/{total_chunks} cached ({dur:.1f}s).")
            return chunk_idx, mp3_path, c_words, dur, 0.0

        t0 = time.time()
        url = "http://127.0.0.1:8001/api/tts"
        import requests
        data = {
            "text": text,
            "language": "English",
            "format": "mp3",
            "steps": 16,
            "speed": self.speed
        }
        files = {}
        ref = ref_voice or getattr(self, "ref_voice_path", None)
        if ref and os.path.exists(ref):
            files["voice"] = open(ref, "rb")

        resp = requests.post(url, data=data, files=files if files else None, timeout=120)
        if resp.status_code != 200:
            raise Exception(f"OmniVoice error {resp.status_code}: {resp.text}")
        with open(mp3_path, "wb") as f:
            f.write(resp.content)

        dur = self.get_duration(mp3_path)
        tot_t = time.time() - t0
        self.log(f"Chunk {chunk_idx}/{total_chunks} synthesized on local RTX 3070 Ti (0 CREDITS) in {tot_t:.1f}s ({dur:.1f}s audio).")
        return chunk_idx, mp3_path, c_words, dur, tot_t

    def submit_twospeaker(self, text, chunk_idx):
        body = {
            "text": text,
            "voice_id": self.voice_id,
            "speed": self.speed
        }
        req = urllib.request.Request(f"{self.base_url}/api/v1/eleven-multilingual-v2", data=json.dumps(body).encode("utf-8"), headers={
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": UA
        })
        for attempt in range(8):
            try:
                with urllib.request.urlopen(req, timeout=45) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    jid = res.get("request_id") or res.get("job_id") or res.get("id")
                    if jid: return jid
            except Exception:
                time.sleep(2.0 + attempt * 1.5)
        raise Exception(f"Failed to submit chunk {chunk_idx}")

    def process_chunk_twospeaker(self, text, chunk_idx, total_chunks, voice_chunks_dir):
        mp3_path = os.path.join(voice_chunks_dir, f"chunk_{chunk_idx:03d}.mp3")
        c_words = len(text.split())
        if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 10000:
            dur = self.get_duration(mp3_path)
            self.log(f"Chunk {chunk_idx}/{total_chunks} cached ({dur:.1f}s).")
            return chunk_idx, mp3_path, c_words, dur, 0.0

        for retry in range(4):
            t0 = time.time()
            try:
                jid = self.submit_twospeaker(text, chunk_idx)
                self.log(f"Chunk {chunk_idx}/{total_chunks} submitted (Job: {jid}, attempt {retry+1}).")
                for _ in range(90):
                    time.sleep(3.0)
                    p_req = urllib.request.Request(f"{self.base_url}/api/v1/predictions/{jid}/result", headers={
                        "X-API-Key": self.api_key,
                        "User-Agent": UA
                    })
                    try:
                        with urllib.request.urlopen(p_req, timeout=30) as presp:
                            pdata = json.loads(presp.read().decode("utf-8"))
                            st = pdata.get("status")
                            if st == "completed":
                                url = pdata.get("output_url") or pdata.get("output", {}).get("url")
                                self.download_audio(url, mp3_path)
                                dur = self.get_duration(mp3_path)
                                tot_t = time.time() - t0
                                self.log(f"Chunk {chunk_idx}/{total_chunks} ready in {tot_t:.1f}s ({dur:.1f}s audio).")
                                return chunk_idx, mp3_path, c_words, dur, tot_t
                            elif st in ["failed", "error"]:
                                break
                    except Exception:
                        time.sleep(3)
                        continue
            except Exception:
                time.sleep(4.0)
        raise Exception(f"Chunk {chunk_idx} permanently failed after 4 retries.")

    @staticmethod
    def _srt_time_to_sec(ts):
        h, m, s = ts.split(":"); s, ms = s.split(",")
        return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000.0

    @staticmethod
    def _sec_to_srt_time(t):
        if t < 0: t = 0
        h = int(t // 3600); t -= h*3600
        m = int(t // 60);   t -= m*60
        s = int(t); ms = int(round((t - s) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _shift_srt(self, srt_path, offset, start_cue):
        """Return merged SRT lines with times shifted by offset seconds; renumbers
        cues starting from start_cue. Also returns the next cue number."""
        import re
        raw = open(srt_path, "r", encoding="utf-8-sig", errors="replace").read()
        blocks = re.split(r"\r?\n\r?\n", raw.strip())
        out = []
        cue = start_cue
        ts_re = re.compile(r"(\d\d:\d\d:\d\d,\d{3})\s*-->\s*(\d\d:\d\d:\d\d,\d{3})(.*)")
        for b in blocks:
            lines = [ln for ln in b.splitlines() if ln.strip()]
            if not lines:
                continue
            # drop the first line if it's a cue number
            if lines[0].strip().isdigit():
                lines = lines[1:]
            if not lines:
                continue
            m = ts_re.match(lines[0])
            if not m:
                continue
            a = self._srt_time_to_sec(m.group(1)) + offset
            c = self._srt_time_to_sec(m.group(2)) + offset
            ts_line = f"{self._sec_to_srt_time(a)} --> {self._sec_to_srt_time(c)}{m.group(3)}"
            text_lines = lines[1:]
            out.append(str(cue))
            out.append(ts_line)
            out.extend(text_lines)
            out.append("")
            cue += 1
        return out, cue

    def get_duration(self, audio_file):
        res = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", audio_file
        ], capture_output=True, text=True)
        return float(res.stdout.strip())

    def synthesize(self, full_script, work_dir, output_mp3, benchmarks_file=None):
        voice_chunks_dir = os.path.join(work_dir, "voice_chunks")
        os.makedirs(voice_chunks_dir, exist_ok=True)
        
        chunks = self.chunk_script(full_script)
        total_words = len(full_script.split())
        self.log(f"Total script words: {total_words} across {len(chunks)} chunks.")
        
        t_start = time.time()
        results = {}
        
        if self.provider == "ai33pro":
            self.log(f"Using ai33pro v3 TTS (Voice: {self.voice_id}, Speed: {self.speed}) -> auto SRT for RULE 6 alignment.")
            with ThreadPoolExecutor(max_workers=6) as pool:
                futures = {
                    pool.submit(self.process_chunk_ai33pro, c, i, len(chunks), voice_chunks_dir): i
                    for i, c in enumerate(chunks, 1)
                }
                for future in as_completed(futures):
                    idx, mp3_p, c_words, dur, tot_t = future.result()
                    results[idx] = {"chunk": idx, "path": mp3_p, "words": c_words, "audio_seconds": dur, "api_latency_sec": round(tot_t, 2)}
        elif self.provider == "famespeak":
            self.log(f"Using FameSpeak ElevenLabs TTS (Voice: {self.voice_id}) -> word SRT via local alignment.")
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {
                    pool.submit(self.process_chunk_famespeak, c, i, len(chunks), voice_chunks_dir): i
                    for i, c in enumerate(chunks, 1)
                }
                for future in as_completed(futures):
                    idx, mp3_p, c_words, dur, tot_t = future.result()
                    results[idx] = {"chunk": idx, "path": mp3_p, "words": c_words, "audio_seconds": dur, "api_latency_sec": round(tot_t, 2)}
        elif self.provider == "omnivoice":
            self.log("Using Local OmniVoice Studio (RTX 3070 Ti GPU) -> 0 CREDITS CONSUMED (100% FREE FOREVER)!")
            for i, c in enumerate(chunks, 1):
                idx, mp3_p, c_words, dur, tot_t = self.process_chunk_omnivoice(c, i, len(chunks), voice_chunks_dir)
                results[idx] = {"chunk": idx, "path": mp3_p, "words": c_words, "audio_seconds": dur, "api_latency_sec": round(tot_t, 2)}
        elif self.provider == "edge-tts":
            self.log(f"Using Microsoft Azure Neural Speech ({self.voice_id}) -> 0 CREDITS CONSUMED (100% FREE FOREVER)!")
            with ThreadPoolExecutor(max_workers=5) as pool:
                futures = {
                    pool.submit(self.process_chunk_edge_tts, c, i, len(chunks), voice_chunks_dir): i
                    for i, c in enumerate(chunks, 1)
                }
                for future in as_completed(futures):
                    idx, mp3_p, c_words, dur, tot_t = future.result()
                    results[idx] = {"chunk": idx, "path": mp3_p, "words": c_words, "audio_seconds": dur, "api_latency_sec": round(tot_t, 2)}
        else:
            self.log(f"Using TwoSpeaker ElevenLabs API (Voice: {self.voice_id}, Speed: {self.speed})...")
            with ThreadPoolExecutor(max_workers=5) as pool:
                futures = {
                    pool.submit(self.process_chunk_twospeaker, c, i, len(chunks), voice_chunks_dir): i
                    for i, c in enumerate(chunks, 1)
                }
                for future in as_completed(futures):
                    idx, mp3_p, c_words, dur, tot_t = future.result()
                    results[idx] = {"chunk": idx, "path": mp3_p, "words": c_words, "audio_seconds": dur, "api_latency_sec": round(tot_t, 2)}

        sorted_chunks = [results[i]["path"] for i in range(1, len(chunks) + 1)]
        self.log(f"All {len(sorted_chunks)} audio chunks ready! Merging into master audio...")
        
        concat_list = os.path.join(work_dir, "voice_concat.txt")
        with open(concat_list, "w", encoding="utf-8") as f:
            for cf in sorted_chunks:
                # ffmpeg concat format: wrap in single quotes, escape ' as '\''
                cf_clean = cf.replace("\\", "/").replace("'", r"'\''")
                f.write(f"file '{cf_clean}'\n")
                
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_list, "-c", "copy", output_mp3
        ], capture_output=True, check=True)

        total_vo_dur = self.get_duration(output_mp3)

        # RULE 6: concatenate per-chunk SRTs (from ai33pro) into ONE voiceover.srt
        # beside the mp3, shifting each chunk's timestamps by the running audio offset.
        # This preserves word-level timing across the whole voiceover so the semantic
        # matcher can place named-subject visuals to the exact spoken word.
        srt_out = os.path.splitext(output_mp3)[0] + ".srt"
        merged_lines = []
        cue_no = 1
        running_offset = 0.0
        wrote_any = False
        for i in range(1, len(chunks) + 1):
            chunk_mp3 = results[i]["path"]
            chunk_srt = os.path.splitext(chunk_mp3)[0] + ".srt"
            chunk_dur = self.get_duration(chunk_mp3)
            if os.path.exists(chunk_srt) and os.path.getsize(chunk_srt) > 20:
                wrote_any = True
                shifted, cue_no = self._shift_srt(chunk_srt, running_offset, cue_no)
                merged_lines.extend(shifted)
            running_offset += chunk_dur
        if wrote_any:
            with open(srt_out, "w", encoding="utf-8") as f:
                f.write("\n".join(merged_lines))
            self.log(f"Merged SRT written to {srt_out}")
        else:
            self.log("No per-chunk SRTs found; skipping SRT merge.")
        if self.provider == "famespeak":
            # FameSpeak has no transcript API: build the RULE 6 word-level SRT
            # by local alignment over the merged voiceover.
            try:
                self._transcribe_word_srt(output_mp3, srt_out)
            except Exception as e:
                self.log(f"WARNING: local word alignment failed ({e}); continuing without word SRT.")
        vo_mins = total_vo_dur / 60.0
        total_tts_time = time.time() - t_start
        
        self.log(f"Master Voiceover generated: {output_mp3}")
        self.log(f"Total Duration: {total_vo_dur:.2f} seconds ({vo_mins:.2f} MINUTES!) in {total_tts_time:.2f}s.")

        if benchmarks_file:
            with open(benchmarks_file, "w", encoding="utf-8") as f:
                json.dump({
                    "provider": self.provider,
                    "voice_id": self.voice_id,
                    "credits_consumed": 0 if self.provider in ["edge-tts", "omnivoice"] else total_words * 6.5,
                    "total_words": total_words,
                    "chunks_count": len(chunks),
                    "total_audio_seconds": total_vo_dur,
                    "total_audio_minutes": vo_mins,
                    "total_tts_time_sec": total_tts_time,
                    "chunks": [results[i] for i in range(1, len(chunks) + 1)]
                }, f, indent=2)
                
        return output_mp3, total_vo_dur
