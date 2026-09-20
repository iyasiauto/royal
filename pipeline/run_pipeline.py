import os
import sys
import argparse
from pathlib import Path
from pipeline.subtitle_formatter import convert_srt_to_ass
from pipeline.asset_fetcher import fetch_broll_images
from pipeline.thumbnail_builder import create_royal_thumbnail
from pipeline.video_assembler import assemble_royal_video

def main():
    parser = argparse.ArgumentParser(description="Royal Niche Video Automation Pipeline")
    parser.add_argument("--video_dir", type=str, required=True, help="Path to video folder containing script.txt, voiceover.mp3, voiceover.srt")
    parser.add_argument("--skip_broll", action="store_true", help="Skip downloading B-roll images if broll/ already has files")
    parser.add_argument("--render_thumbnail", action="store_true", help="Generate thumbnail variant")
    
    args = parser.parse_args()
    video_dir = Path(args.video_dir)

    if not video_dir.exists():
        print(f"[ERROR] Directory not found: {video_dir}")
        return

    print("=" * 60)
    print("ROYAL FAMILY DRAMA AUTOMATION PIPELINE")
    print(f"Target Directory: {video_dir.name}")
    print("=" * 60)

    # Step 1: Subtitle formatting
    srt_path = video_dir / "voiceover.srt"
    ass_path = video_dir / "voiceover.ass"
    if srt_path.exists():
        print("\n[STEP 1] Formatting & styling ASS subtitles...")
        convert_srt_to_ass(srt_path, ass_path)

    # Step 2: B-Roll Image Acquisition
    broll_dir = video_dir / "broll"
    existing_broll = list(broll_dir.glob("*.jpg")) if broll_dir.exists() else []
    if not existing_broll or not args.skip_broll:
        print("\n[STEP 2] Acquiring & cropping HD B-roll images...")
        fetch_broll_images(broll_dir)

    # Step 3: Thumbnail Variant Generation
    if args.render_thumbnail:
        print("\n[STEP 3] Generating thumbnail variant per Playbook Section 7...")
        ref_thumbs = list(Path(r"C:\Users\ninja\Downloads\X Colab Automation\Royal\Thumbnail refrence").glob("*.png"))
        if len(ref_thumbs) >= 2:
            out_thumb = video_dir / "thumbnail_variant.png"
            create_royal_thumbnail(str(ref_thumbs[0]), str(ref_thumbs[1]), str(out_thumb))

    # Step 4: Video Assembly & Subtitle Burn-In
    print("\n[STEP 4] Assembling full 1080p documentary video...")
    final_mp4 = assemble_royal_video(video_dir)

    print("=" * 60)
    print("PIPELINE EXECUTION COMPLETE!")
    print(f"Final Video: {final_mp4}")
    print("=" * 60)

if __name__ == "__main__":
    main()
