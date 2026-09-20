import os
import subprocess
import math
from pathlib import Path
from pipeline.config import VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS
from pipeline.subtitle_formatter import convert_srt_to_ass

def get_audio_duration(audio_file):
    """Returns audio duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_file)
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        return float(res.stdout.strip())
    except ValueError:
        return 0.0

def assemble_royal_video(video_dir, output_filename="final_video.mp4", use_gpu=True):
    """
    GPU-Accelerated video assembly pipeline:
    1. Checks voiceover.mp3 and duration
    2. Converts voiceover.srt to voiceover.ass
    3. Finds B-roll images in broll/
    4. Generates motion clips with NVIDIA NVENC GPU acceleration (h264_nvenc)
    5. Concatenates video clips
    6. Combines audio + video + burned-in styled subtitles into 1080p MP4 via NVENC GPU
    """
    video_dir = Path(video_dir).resolve()
    audio_path = video_dir / "voiceover.mp3"
    srt_path = video_dir / "voiceover.srt"
    ass_path = video_dir / "voiceover.ass"
    broll_dir = video_dir / "broll"
    temp_dir = video_dir / "temp_clips"
    output_path = video_dir / output_filename

    if not audio_path.exists():
        raise FileNotFoundError(f"voiceover.mp3 not found in {video_dir}")

    total_duration = get_audio_duration(audio_path)
    print(f"[*] Voiceover duration: {total_duration:.2f} seconds ({total_duration/60:.2f} minutes)")

    # 1. Convert SRT to ASS if ASS doesn't exist
    if srt_path.exists() and not ass_path.exists():
        convert_srt_to_ass(srt_path, ass_path)

    # 2. Get B-roll images
    images = list(broll_dir.glob("*.jpg")) + list(broll_dir.glob("*.png"))
    if not images:
        from pipeline.asset_fetcher import fetch_broll_images
        print("[!] No B-roll images found. Fetching automatically...")
        images = fetch_broll_images(broll_dir)

    if not images:
        raise RuntimeError("No visual assets available for video generation!")

    temp_dir.mkdir(exist_ok=True)
    clip_duration = 5.0  # seconds per image
    num_clips_needed = math.ceil(total_duration / clip_duration)
    
    print(f"[*] GPU Check: Generating {num_clips_needed} motion clips using NVIDIA NVENC...")

    selected_images = [images[i % len(images)] for i in range(num_clips_needed)]
    clip_files = []

    # Choose encoder: h264_nvenc (NVIDIA GPU) or libx264 (CPU fallback)
    v_encoder = "h264_nvenc" if use_gpu else "libx264"
    preset = "p1" if use_gpu else "fast"  # p1 = fastest NVENC preset

    for idx, img in enumerate(selected_images):
        clip_file = temp_dir / f"clip_{idx:04d}.mp4"
        clip_files.append(clip_file)

        if not clip_file.exists() or clip_file.stat().st_size == 0:
            if idx % 2 == 0:
                zoom_filter = "zoompan=z='min(zoom+0.0015,1.25)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=150:s=1920x1080:fps=30"
            else:
                zoom_filter = "zoompan=z='max(1.25-0.0015*on,1.0)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=150:s=1920x1080:fps=30"

            cmd = [
                "ffmpeg", "-y", "-loop", "1", "-i", str(img),
                "-vf", f"{zoom_filter},format=yuv420p",
                "-c:v", v_encoder, "-preset", preset,
                "-t", str(clip_duration),
                "-r", str(VIDEO_FPS), str(clip_file)
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 3. Create concat list
    concat_list_path = temp_dir / "concat.txt"
    with open(concat_list_path, 'w', encoding='utf-8') as f:
        for c in clip_files:
            f.write(f"file '{c.name}'\n")

    # 4. Concat motion clips
    raw_video = temp_dir / "concatenated.mp4"
    print("[*] Concatenating motion clips...")
    concat_cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "concat.txt",
        "-c", "copy", "concatenated.mp4"
    ]
    subprocess.run(concat_cmd, cwd=str(temp_dir), check=True)

    print(f"[*] Merging audio & burning ASS subtitles with GPU Acceleration ({v_encoder})...")
    
    # 5. Final Render with GPU (h264_nvenc) + Subtitle Burn-In
    render_cmd = [
        "ffmpeg", "-y",
        "-i", str(raw_video.relative_to(video_dir)),
        "-i", "voiceover.mp3",
        "-vf", "subtitles=voiceover.ass",
        "-c:v", v_encoder, "-preset", preset, "-rc", "cbr", "-b:v", "6M",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(total_duration),
        output_filename
    ]

    res = subprocess.run(render_cmd, cwd=str(video_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        print("[!] GPU Subtitle notice, rendering GPU clean video with audio track...")
        fallback_cmd = [
            "ffmpeg", "-y",
            "-i", str(raw_video.relative_to(video_dir)),
            "-i", "voiceover.mp3",
            "-c:v", v_encoder, "-preset", preset, "-b:v", "6M",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(total_duration),
            output_filename
        ]
        subprocess.run(fallback_cmd, cwd=str(video_dir), check=True)

    print(f"[SUCCESS] GPU Ultra-Fast 1080p Video exported to: {output_path}")
    return output_path

if __name__ == "__main__":
    import sys
    v_dir = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\ninja\Downloads\X Colab Automation\Royal\Video 1 (King Charles Just Signed The One Document About Camilla's Future Nobody Saw Coming)"
    assemble_royal_video(v_dir)
