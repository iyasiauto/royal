import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

def create_royal_thumbnail(
    hero_img_path,
    villain_img_path,
    output_path,
    quote_text='"1 MINUTE AGO"',
    badge_text="BREAKING"
):
    """
    Composites a 1920x1080 thumbnail following Section 7 Thumbnail Rules:
    - Left side (45%): Hero image
    - Right side (55%): Villain scene with 8px bright yellow border
    - Top-left / Bottom-left: Red BREAKING badge
    - Top-right corner: Red circle symbol
    - Bottom (30% height): Pure white bar with MASSIVE quoted black text
    """
    canvas_w, canvas_h = 1920, 1080
    canvas = Image.new('RGB', (canvas_w, canvas_h), (0, 0, 0))

    # 1. Left side (Hero)
    hero_w = int(canvas_w * 0.45)
    if os.path.exists(hero_img_path):
        hero_img = Image.open(hero_img_path).convert('RGB')
        hero_img = hero_img.resize((hero_w, canvas_h), Image.Resampling.LANCZOS)
        canvas.paste(hero_img, (0, 0))

    # 2. Right side (Villain scene) with Yellow Border
    villain_w = canvas_w - hero_w
    border_px = 8
    yellow_color = (255, 213, 0) # #FFD500

    if os.path.exists(villain_img_path):
        villain_img = Image.open(villain_img_path).convert('RGB')
        villain_img = villain_img.resize((villain_w - border_px * 2, canvas_h - border_px * 2), Image.Resampling.LANCZOS)
        
        # Yellow border background
        yellow_bg = Image.new('RGB', (villain_w, canvas_h), yellow_color)
        yellow_bg.paste(villain_img, (border_px, border_px))
        canvas.paste(yellow_bg, (hero_w, 0))

    draw = ImageDraw.Draw(canvas)

    # 3. Red BREAKING Badge (Top Left)
    badge_w, badge_h = 320, 80
    badge_x, badge_y = 20, 20
    draw.rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + badge_h], fill=(227, 0, 0)) # #E30000
    
    # Try loading bold font
    try:
        badge_font = ImageFont.truetype("arialbd.ttf", 48)
        text_font = ImageFont.truetype("impact.ttf", 110)
    except IOError:
        badge_font = ImageFont.load_default()
        text_font = ImageFont.load_default()

    draw.text((badge_x + 35, badge_y + 12), badge_text.upper(), fill=(255, 255, 255), font=badge_font)

    # 4. Red Circle Symbol (Top Right)
    circle_r = 90
    circle_cx, circle_cy = canvas_w - 110, 110
    draw.ellipse(
        [circle_cx - circle_r, circle_cy - circle_r, circle_cx + circle_r, circle_cy + circle_r],
        fill=(227, 0, 0),
        outline=yellow_color,
        width=4
    )

    # 5. Bottom White Bar with Quoted Text (32% height)
    bar_h = int(canvas_h * 0.32)
    bar_y = canvas_h - bar_h
    draw.rectangle([0, bar_y, canvas_w, canvas_h], fill=(255, 255, 255))

    # Clean quote text ensuring double quotes
    if not quote_text.startswith('"'):
        quote_text = f'"{quote_text}"'
        
    bbox = draw.textbbox((0, 0), quote_text.upper(), font=text_font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    text_x = (canvas_w - text_w) // 2
    text_y = bar_y + (bar_h - text_h) // 2 - 10
    draw.text((text_x, text_y), quote_text.upper(), fill=(0, 0, 0), font=text_font)

    canvas.save(output_path, "PNG", quality=95)
    print(f"[+] Royal Thumbnail composite created: {output_path}")
    return output_path

if __name__ == "__main__":
    import sys
    ref_dir = Path(r"C:\Users\ninja\Downloads\X Colab Automation\Royal\Thumbnail refrence")
    imgs = list(ref_dir.glob("*.png"))
    if len(imgs) >= 2:
        out_thumb = ref_dir / "generated_variant.png"
        create_royal_thumbnail(str(imgs[0]), str(imgs[1]), str(out_thumb))
