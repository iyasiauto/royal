"""
Universal Multi-Provider Voiceover Engine.
Supports:
1. 'edge-tts'  -> 100% FREE, ZERO Credits, Unlimited, Microsoft Azure Neural Voices (Guy, Christopher, Eric).
2. 'twospeaker' -> ElevenLabs Multi-threaded Async Burst TTS API.
"""

import os, sys, time, json, urllib.request, subprocess, asyncio
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

    def download_audio(self, url, out_path):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as resp:
            content = resp.read()
            with open(out_path, "wb") as f:
                f.write(content)

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
