"""
YouTube Upload Metadata Generator.
Generates human-written titles, character-counted alt titles, descriptions with timestamps, tags, hashtags, and checklists.
"""

import os

class MetadataEngine:
    @staticmethod
    def generate_metadata(title, alt_titles, description, chapters, tags, hashtags, out_path):
        content = [
            "======================================================================",
            "YOUTUBE UPLOAD METADATA",
            "======================================================================",
            "",
            "=== TITLE ===",
            title,
            "",
            "=== ALT TITLES (no em-dash, <100 chars, TV/homepage-safe — A/B test these) ==="
        ]
        for alt in alt_titles:
            content.append(f"[{len(alt)}] {alt}")

        content.extend([
            "",
            "=== DESCRIPTION ===",
            description,
            "",
            "Video CHAPTERS:"
        ])
        for ch in chapters:
            content.append(ch)

        content.extend([
            "",
            f"Hashtags: {' '.join(hashtags)}",
            "",
            "=== TAGS (comma-separated) ===",
            ", ".join(tags),
            "",
            "=== THUMBNAILS file name===",
            "thumb_01.jpg",
            "thumb_02.jpg",
            "",
            "=== UPLOAD CHECKLIST ===",
            f"[ ] Upload final video: {title}.mp4",
            "[ ] Paste title above",
            "[ ] Paste description with chapters at top",
            "[ ] Add tags",
            "[ ] Set thumbnail (pick thumb_1 or thumb_2)",
            "[ ] Category: Entertainment / Documentary",
            "[ ] Language: English",
            "[ ] Made for kids: No",
            "[ ] Save as Draft or Publish",
            "======================================================================"
        ])

        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(content) + "\n")
        return out_path
