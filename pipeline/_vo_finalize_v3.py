"""Concat V3 voice chunks into voiceover.mp3 + merge SRTs into voiceover.srt.
Runs with cwd=voice_chunks so ffmpeg concat sees bare filenames (path escape safe)."""
import os, sys, subprocess, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from voiceover_engine import VoiceoverEngine

V3 = os.path.join(
    "C:\\", "Users", "ninja", "Downloads", "X Colab Automation", "Royal",
    "Video 3 (Charles LOCKS Harry Out on Elizabeth's Death Anniversary "
    "\u2014 No Meeting, No Mercy, No Return!)"
)
work = os.path.join(V3, "temp_render_workspace")
chunks_dir = os.path.join(work, "voice_chunks")
mp3s = sorted(glob.glob(os.path.join(chunks_dir, "chunk_*.mp3")))
srts = sorted(glob.glob(os.path.join(chunks_dir, "chunk_*.srt")))
print(f"{len(mp3s)} chunks, {len(srts)} SRTs")

# Write a bare-filename concat list inside chunks_dir and run with cwd=chunks_dir.
concat_path = os.path.join(chunks_dir, "_concat.txt")
with open(concat_path, "w", encoding="utf-8") as f:
    for mp3 in mp3s:
        f.write("file '{}'\n".format(os.path.basename(mp3)))

# Stage the output name inside a plain-ASCII temp dir to sidestep the em-dash /
# apostrophe in the folder name.
import tempfile, shutil
tmp = tempfile.mkdtemp(prefix="vo_v3_")
tmp_mp3 = os.path.join(tmp, "voiceover.mp3")
r = subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", "_concat.txt", "-c", "copy", tmp_mp3],
                   cwd=chunks_dir, capture_output=True, text=True)
if r.returncode != 0:
    print("CONCAT FAILED:", r.stderr[-800:]); sys.exit(1)
shutil.copyfile(tmp_mp3, os.path.join(work, "voiceover.mp3"))
shutil.rmtree(tmp, ignore_errors=True)
os.remove(concat_path)
print("wrote voiceover.mp3")

# Merge per-chunk SRTs with running audio offset.
eng = VoiceoverEngine()
merged = []; cue = 1; offset = 0.0
for i in range(1, len(mp3s) + 1):
    mp3 = os.path.join(chunks_dir, f"chunk_{i:03d}.mp3")
    srt = os.path.join(chunks_dir, f"chunk_{i:03d}.srt")
    dur = eng.get_duration(mp3)
    if os.path.exists(srt):
        lines, cue = eng._shift_srt(srt, offset, cue)
        merged.extend(lines)
    offset += dur
srt_out = os.path.join(work, "voiceover.srt")
with open(srt_out, "w", encoding="utf-8") as f:
    f.write("\n".join(merged))
print(f"wrote voiceover.srt ({os.path.getsize(srt_out)} bytes, offset {offset:.1f}s)")
