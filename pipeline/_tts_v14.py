"""One-shot TTS driver for Video 14."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: F401
from voiceover_engine import VoiceoverEngine

V14 = r"C:\Users\ninja\Downloads\X Colab Automation\Royal\Video 14"
work = os.path.join(V14, "temp_render_workspace")
os.makedirs(work, exist_ok=True)
script = open(os.path.join(V14, "script.txt"), encoding="utf-8-sig").read()

eng = VoiceoverEngine(
    api_key=os.environ.get("VOICEOVER_API_KEY"),
    voice_id="elevenlabs_RNnkVeW25AwKYxZgnHBH",
    speed=0.95,
    base_url="https://api.ai33.pro",
    provider="ai33pro",
)
out_mp3 = os.path.join(work, "voiceover.mp3")
_, dur = eng.synthesize(script, work, out_mp3)

import shutil
top_mp3 = os.path.join(V14, "voiceover.mp3")
top_srt = os.path.join(V14, "voiceover.srt")
shutil.copy2(out_mp3, top_mp3)
srt_src = os.path.splitext(out_mp3)[0] + ".srt"
if os.path.exists(srt_src):
    shutil.copy2(srt_src, top_srt)
print(f"TTS DONE: mp3={top_mp3} duration={dur:.1f}s ({dur/60:.2f} min)")
