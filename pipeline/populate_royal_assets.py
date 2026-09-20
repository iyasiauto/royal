import os
import sys
import shutil
from pathlib import Path

# Add current dir and parent dir to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from index_retriever import IndexRetriever

ROYAL_DIR = Path(r"C:\Users\ninja\Downloads\X Colab Automation\Royal")
IMAGES_DIR = ROYAL_DIR / "royal_images"
CLIPS_DIR = ROYAL_DIR / "royal_clips"

ENTITY_MAPPING = {
    "king charles": ("King Charles III", "King_Charles_III"),
    "queen camilla": ("Queen Camilla", "Queen_Camilla"),
    "prince william": ("Prince William", "Prince_William"),
    "princess diana": ("Princess Diana", "Princess_Diana"),
    "princess catherine": ("Princess Catherine", "Princess_Catherine"),
    "prince harry": ("Prince Harry", "Prince_Harry"),
    "meghan markle": ("Meghan Markle", "Meghan_Markle"),
    "prince george": ("Prince George", "Prince_George"),
    "princess charlotte": ("Princess Charlotte", "Princess_Charlotte"),
    "prince louis": ("Prince Louis", "Prince_Louis"),
    "charles spencer": ("Charles Spencer", "Charles_Spencer"),
    "princess anne": ("Princess Anne", "Princess_Anne"),
    "carole middleton": ("Carole Middleton", "Carole_Middleton"),
    "tom parker bowles": ("Tom Parker Bowles", "Tom_Parker_Bowles"),
    "laura lopes": ("Laura Lopes", "Laura_Lopes"),
}

# How many images to pull per entity (index has 130-195 usable for the main subjects).
# High count kills the "named subject had none left in the library" fallback that shows
# the wrong person during narration.
IMAGES_PER_ENTITY = 150

BROLL_QUERIES = [
    "King Charles III waving to crowd",
    "King Charles III speaking",
    "King Charles III walking",
    "Queen Camilla smiling",
    "Queen Camilla royal engagement",
    "King Charles and Queen Camilla together",
    "Prince William",
    "Princess Catherine",
    "Princess Diana",
    "coronation ceremony",
    "royal procession carriage",
    "Westminster Abbey",
    "Buckingham Palace exterior",
    "royal family balcony",
    "royal walkabout meeting public",
    "crowd waving union jack flags",
    "royal motorcade state car",
    "military guards ceremony",
]

def populate_royal_assets():
    print("=" * 60)
    print("[*] POPULATING ROYAL ASSETS FROM D:\\Royal Data V3 INDEX")
    print("=" * 60)

    retriever = IndexRetriever()
    
    # Clean output directories completely
    if IMAGES_DIR.exists():
        shutil.rmtree(IMAGES_DIR)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Populate entity images
    for entity_key, (search_query, folder_name) in ENTITY_MAPPING.items():
        ent_dir = IMAGES_DIR / entity_key
        ent_dir.mkdir(parents=True, exist_ok=True)

        print(f"[*] Processing entity '{entity_key}'...")
        results = retriever.search_images(search_query, max_count=IMAGES_PER_ENTITY, folder=folder_name)
        if not results:
            results = retriever.search_images(search_query, max_count=IMAGES_PER_ENTITY)

        copied = 0
        for item in results:
            src_path = item.get("abs_path")
            if not src_path or not os.path.exists(src_path):
                continue

            fname = os.path.basename(src_path)
            dest_path = ent_dir / fname
            if not dest_path.exists():
                try:
                    shutil.copy2(src_path, dest_path)
                    copied += 1
                except Exception as e:
                    print(f"  [-] Failed to copy {src_path}: {e}")

        print(f"  [+] Copied {copied} indexed images to {ent_dir.name}")

    # 2. Extract B-roll video clips
    print("\n[*] Fetching & Extracting Indexed Video Clips into royal_clips...")
    clips = retriever.fetch_and_populate_clips(BROLL_QUERIES, CLIPS_DIR, max_clips=70)
    print(f"[+] Total {len(clips)} video clips ready in {CLIPS_DIR}")

    # 3. Stabilize clips + quarantine any that stay shaky (RULE 9). Guarded so a
    #    clip is only replaced when jitter actually drops; unfixable ones move to
    #    _shaky/ and are excluded from the render pool.
    print("\n[*] Stabilizing clips (two-pass vidstab, guarded + quarantine)...")
    try:
        import subprocess, sys as _sys
        subprocess.run([_sys.executable, "-u",
                        os.path.join(os.path.dirname(os.path.abspath(__file__)), "stabilize_clips.py"),
                        "--workers", "4"], check=False)
    except Exception as e:
        print(f"  [-] stabilization step failed (clips left as-is): {e}")
    print("=" * 60)

if __name__ == "__main__":
    populate_royal_assets()
