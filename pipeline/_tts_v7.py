"""One-shot TTS driver for Video 7 — writes voiceover.mp3 + voiceover.srt
into the video's root folder so pipeline.py can reuse it via --voiceover."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: F401 — triggers dotenv load for VOICEOVER_API_KEY
from voiceover_engine import VoiceoverEngine

V7 = ("C:\\Users\\ninja\\Downloads\\X Colab Automation\\Royal\\"
      "Video 7 (Meghan SPOTTED at Soho Farmhouse "
      "\u2014 Beckham Drama EXPLODES Into Full-Blown War!)")
work = os.path.join(V7, "temp_render_workspace")
os.makedirs(work, exist_ok=True)
script = open(os.path.join(V7, "script.txt"), encoding="utf-8-sig").read()

eng = VoiceoverEngine(
    api_key=os.environ.get("VOICEOVER_API_KEY"),
    voice_id="elevenlabs_SAz9YHcvj6GT2YYXdXww",
    speed=0.95,
    base_url="https://api.ai33.pro",
    provider="ai33pro",
)
out_mp3 = os.path.join(work, "voiceover.mp3")
_, dur = eng.synthesize(script, work, out_mp3)

import shutil
top_mp3 = os.path.join(V7, "voiceover.mp3")
top_srt = os.path.join(V7, "voiceover.srt")
shutil.copy2(out_mp3, top_mp3)
srt_src = os.path.splitext(out_mp3)[0] + ".srt"
if os.path.exists(srt_src):
    shutil.copy2(srt_src, top_srt)
print(f"TTS DONE: mp3={top_mp3} duration={dur:.1f}s ({dur/60:.2f} min)")
if os.path.exists(top_srt):
    print(f"          srt={top_srt}")
