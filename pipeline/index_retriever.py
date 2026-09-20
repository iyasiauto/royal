import os
import sys
import json
import subprocess
from pathlib import Path

VIDEO_INDEX_SCRIPT = r"D:\Royal Data\Royal News Data\_index\retrieve_index3.py"
VIDEO_NEWS_DIR = r"D:\Royal Data\Royal News Data"
IMAGE_INDEX_SCRIPT = r"D:\Royal Data\Royal Images Data\_index\retrieve_images.py"

class IndexRetriever:
    """Wrapper for D:\\Royal Data V3 semantic index retrievers."""

    def __init__(self, news_index_script=VIDEO_INDEX_SCRIPT, image_index_script=IMAGE_INDEX_SCRIPT):
        self.news_index_script = news_index_script
        self.image_index_script = image_index_script

    def search_images(self, query, max_count=35, folder=None, min_confidence=0.55):
        """Runs retrieve_images.py with --json and returns list of result dicts."""
        cmd = [sys.executable, self.image_index_script, query, "--max", str(max_count), "--max-per-folder", str(max_count), "--json"]
        if folder:
            cmd.extend(["--folder", folder, "--folder-match-only"])

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return json.loads(res.stdout)
        except Exception as e:
            print(f"  [-] Image search failed for query '{query}': {e}")
            return []

    def search_video_clips(self, query, max_count=10, min_confidence=0.55, subject=None):
        """Runs retrieve_index3.py with --json and returns list of result dicts."""
        cmd = [sys.executable, self.news_index_script, query, "--max", str(max_count), "--min-confidence", str(min_confidence), "--json"]
        if subject:
            cmd.extend(["--subject", subject])

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return json.loads(res.stdout)
        except Exception as e:
            print(f"  [-] Video search failed for query '{query}': {e}")
            return []

    def extract_clip(self, source_filename, start_ms, end_ms, output_path):
        """Extracts a frame-accurate clip from D:\\Royal Data\\Royal News Data source video using FFmpeg."""
        source_path = os.path.join(VIDEO_NEWS_DIR, source_filename)
        if not os.path.exists(source_path):
            print(f"  [-] Source video missing: {source_path}")
            return False

        start_sec = start_ms / 1000.0
        duration_sec = (end_ms - start_ms) / 1000.0

        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start_sec:.3f}",
            "-i", source_path,
            "-t", f"{duration_sec:.3f}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            str(output_path)
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except Exception as e:
            print(f"  [-] FFmpeg clip extraction failed for {source_filename}: {e}")
            try:
                if os.path.exists(output_path):
                    os.remove(output_path)
            except OSError:
                pass
            return False
        # Verify the written file actually decodes — a killed ffmpeg can leave a
        # truncated .mp4 that later aborts the render. Remove it if invalid.
        if not self._is_valid_clip(output_path):
            print(f"  [-] Extracted clip is corrupt, discarding: {os.path.basename(str(output_path))}")
            try:
                os.remove(output_path)
            except OSError:
                pass
            return False
        return True

    @staticmethod
    def _is_valid_clip(path):
        try:
            if not os.path.exists(path) or os.path.getsize(path) < 10000:
                return False
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_name,duration", "-of", "csv=p=0", str(path)],
                capture_output=True, text=True)
            return probe.returncode == 0 and bool(probe.stdout.strip())
        except Exception:
            return False

    def fetch_and_populate_clips(self, queries, output_dir, max_clips=20):
        """Performs queries, extracts clips, and saves them to output_dir."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        extracted = []
        seen_clips = set()

        for q in queries:
            if len(extracted) >= max_clips:
                break
            results = self.search_video_clips(q, max_count=5)
            for item in results:
                clip_id = item.get("clip_id")
                if not clip_id or clip_id in seen_clips:
                    continue
                seen_clips.add(clip_id)

                source_fn = item.get("source_filename")
                start_ms = item.get("start_ms")
                end_ms = item.get("end_ms")
                if not source_fn or start_ms is None or end_ms is None:
                    continue

                out_path = output_dir / f"{clip_id}.mp4"
                if out_path.exists() and self._is_valid_clip(out_path):
                    extracted.append(out_path)
                    print(f"  [=] Reusing existing clip: {out_path.name}")
                    continue

                print(f"  [*] Extracting indexed clip {clip_id} ({source_fn} {start_ms/1000:.1f}s-{end_ms/1000:.1f}s)...")
                if self.extract_clip(source_fn, start_ms, end_ms, out_path):
                    extracted.append(out_path)
                    print(f"  [+] Saved clip: {out_path.name}")

                if len(extracted) >= max_clips:
                    break

        return extracted

if __name__ == "__main__":
    retriever = IndexRetriever()
    imgs = retriever.search_images("King Charles", max_count=3)
    print("Found images:", len(imgs))
    clips = retriever.search_video_clips("King Charles", max_count=3)
    print("Found clips:", len(clips))
