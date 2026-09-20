import os
import subprocess
from pathlib import Path

def finalize_production_render():
    video_dir = Path(r"C:\Users\ninja\Downloads\X Colab Automation\Royal\Video 1 (King Charles Just Signed The One Document About Camilla's Future Nobody Saw Coming)")
    work_dir = video_dir / "temp_render_workspace"
    seg_dir = work_dir / "segments"
    out_mp4 = video_dir / "King_Charles_Royal_Documentary_Master.mp4"
    vo_mp3 = video_dir / "voiceover.mp3"
    bgm_mp3 = Path(r"C:\Users\ninja\Downloads\Dolly Parton\Bg music\Dreamland - Aakash Gandhi.mp3")

    concat_txt = work_dir / "concat.txt"
    segs = sorted([s.name for s in seg_dir.glob("seg_*.mp4")])

    print(f"[*] Compiling {len(segs)} rendered segments into final master video...")
    with open(concat_txt, "w", encoding="utf-8") as f:
        for s in segs:
            f.write(f"file 'segments/{s}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", "concat.txt",
        "-i", str(vo_mp3),
        "-i", str(bgm_mp3),
        "-filter_complex", "[1:a]volume=1.75[vo];[2:a]volume=0.08,aloop=loop=-1:size=2e+09[bgm];[vo][bgm]amix=inputs=2:duration=first[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        str(out_mp4)
    ]

    subprocess.run(cmd, cwd=str(work_dir), check=True)
    print(f"[SUCCESS] Final Master Documentary Video exported to: {out_mp4}")
    return out_mp4

if __name__ == "__main__":
    finalize_production_render()
