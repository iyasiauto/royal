import os
import re
import random
import time
import requests
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from pipeline.config import ROYAL_ENTITIES

SERPER_API_KEY = os.getenv("SERPER_API_KEY", "28890f9421ea0ccff876e66fb8ec00d938927cd7")

DEFAULT_QUERIES = [
    "King Charles III official portrait",
    "Prince William Prince of Wales portrait",
    "Queen Camilla royal family",
    "Princess Diana archival photo",
    "Clarence House London exterior",
    "Highgrove House estate Wiltshire",
    "Ray Mill House Lacock Wiltshire",
    "Balmoral Castle Scotland exterior",
    "Buckingham Palace front gates",
    "Red leather dispatch box royal UK",
    "Westminster Abbey royal ceremony"
]

def fetch_images_via_serper(query, count=3):
    """Fetches image URLs using Google Serper API."""
    url = "https://google.serper.dev/images"
    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {"q": query, "num": count}
    image_urls = []
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=8)
        if res.status_code == 200:
            data = res.json()
            for item in data.get("images", []):
                img_link = item.get("imageUrl") or item.get("image")
                if img_link:
                    image_urls.append(img_link)
    except Exception as e:
        print(f"  [-] Serper query failed for '{query}': {e}")
    return image_urls

def generate_fallback_card(output_path, title_text, index):
    """Generates a high-resolution cinematic text/gradient fallback slide if images fail."""
    canvas = Image.new('RGB', (1920, 1080), (15, 20, 32))
    draw = ImageDraw.Draw(canvas)
    
    # Draw subtle background vignette/borders
    draw.rectangle([40, 40, 1880, 1040], outline=(212, 175, 55), width=4) # Gold border
    
    try:
        font = ImageFont.truetype("arialbd.ttf", 64)
        sub_font = ImageFont.truetype("arial.ttf", 36)
    except IOError:
        font = ImageFont.load_default()
        sub_font = ImageFont.load_default()

    draw.text((960, 480), f"ROYAL ARCHIVE #{index:02d}", fill=(212, 175, 55), font=font, anchor="mm")
    draw.text((960, 560), title_text.upper(), fill=(240, 240, 240), font=sub_font, anchor="mm")
    canvas.save(output_path, "JPEG", quality=90)
    print(f"  [+] Created fallback card: {output_path.name}")

def fetch_broll_images(output_dir, queries=None, count_per_query=2, min_total=15):
    """Downloads HD images for B-roll visuals and resizes them to 1920x1080."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not queries:
        queries = DEFAULT_QUERIES

    downloaded_files = []
    img_index = 1

    print(f"[*] Fetching B-roll images via Serper API for {len(queries)} search terms...")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    for query in queries:
        urls = fetch_images_via_serper(query, count=count_per_query * 2)
        for url in urls:
            try:
                resp = requests.get(url, headers=headers, timeout=6)
                if resp.status_code == 200 and len(resp.content) > 15000:
                    target_file = output_dir / f"broll_{img_index:03d}.jpg"
                    with open(target_file, 'wb') as f:
                        f.write(resp.content)

                    # Standardize image to 1920x1080 crop/resize
                    try:
                        with Image.open(target_file) as img:
                            img = img.convert('RGB')
                            img_ratio = img.width / img.height
                            target_ratio = 1920 / 1080
                            
                            if img_ratio > target_ratio:
                                new_width = int(img.height * target_ratio)
                                offset = (img.width - new_width) // 2
                                img = img.crop((offset, 0, offset + new_width, img.height))
                            else:
                                new_height = int(img.width / target_ratio)
                                offset = (img.height - new_height) // 2
                                img = img.crop((0, offset, img.width, offset + new_height))
                            
                            img = img.resize((1920, 1080), Image.Resampling.LANCZOS)
                            img.save(target_file, "JPEG", quality=90)
                            downloaded_files.append(target_file)
                            print(f"  [+] Saved & cropped: {target_file.name} ({query})")
                            img_index += 1
                            if len(downloaded_files) >= count_per_query * len(queries):
                                break
                    except Exception:
                        if target_file.exists():
                            target_file.unlink()
            except Exception:
                continue

    # Fallback: copy reference images or generate fallback cards if needed
    if len(downloaded_files) < min_total:
        ref_dir = Path(r"C:\Users\ninja\Downloads\X Colab Automation\Royal\Thumbnail refrence")
        ref_imgs = list(ref_dir.glob("*.png"))
        for ref_img in ref_imgs:
            try:
                target_file = output_dir / f"broll_{img_index:03d}.jpg"
                with Image.open(ref_img) as img:
                    img = img.convert('RGB').resize((1920, 1080), Image.Resampling.LANCZOS)
                    img.save(target_file, "JPEG", quality=90)
                    downloaded_files.append(target_file)
                    img_index += 1
            except Exception:
                pass

    # Final guarantee: create visual slides if under min_total
    while len(downloaded_files) < min_total:
        target_file = output_dir / f"broll_{img_index:03d}.jpg"
        title = DEFAULT_QUERIES[(img_index - 1) % len(DEFAULT_QUERIES)]
        generate_fallback_card(target_file, title, img_index)
        downloaded_files.append(target_file)
        img_index += 1

    print(f"[+] Total {len(downloaded_files)} B-roll images ready in {output_dir}")
    return downloaded_files

if __name__ == "__main__":
    import sys
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "./test_broll"
    fetch_broll_images(out_dir)
