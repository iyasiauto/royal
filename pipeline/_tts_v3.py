"""One-shot TTS driver for Video 3 — writes voiceover.mp3 + voiceover.srt
into the video's temp_render_workspace. Path contains an apostrophe which
breaks inline python -c invocations; a dedicated file avoids that."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from voiceover_engine import VoiceoverEngine

V3 = ("C:\\Users\\ninja\\Downloads\\X Colab Automation\\Royal\\"
      "Video 3 (Charles LOCKS Harry Out on Elizabeth's Death Anniversary "
      "\u2014 No Meeting, No Mercy, No Return!)")
work = os.path.join(V3, "temp_render_workspace")
os.makedirs(work, exist_ok=True)
script = open(os.path.join(V3, "script.txt"), encoding="utf-8-sig").read()

eng = VoiceoverEngine(
    api_key=os.environ.get("VOICEOVER_API_KEY",
                           "sk_lt0ubul6ppc3iud75xj48ehkpx2bma4u6q82srfrvdsbkzum"),
    voice_id="elevenlabs_SAz9YHcvj6GT2YYXdXww",
    speed=0.95,
    base_url="https://api.ai33.pro",
    provider="ai33pro",
)
out_mp3 = os.path.join(work, "voiceover.mp3")
_, dur = eng.synthesize(script, work, out_mp3)
print(f"TTS DONE: mp3={out_mp3} duration={dur:.1f}s")
