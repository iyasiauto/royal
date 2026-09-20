"""
Graphic card compositor.

Five card layouts built from the project's own photographs. Every layout is
expressed as a proportion of the target frame, so the same styles compose
correctly at 1920x1080, at 1080x1920 for vertical, or at any other size.
"""

import os

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
COUR_BOLD = os.path.join(FONT_DIR, "courbd.ttf")
ARIAL_BOLD = os.path.join(FONT_DIR, "arialbd.ttf")
GEORGIA_BOLD = os.path.join(FONT_DIR, "georgiab.ttf")

BASE_W, BASE_H = 1920, 1080


def load_photo_trimmed(path):
    """Open a photo and strip any uniform near-white border baked in by the
    postcard conversion (many source images are a portrait centred on a white
    1920x1080 canvas). Without this the white leaks into every card frame."""
    import numpy as np
    im = Image.open(path).convert("RGB")
    arr = np.asarray(im)
    # near-white mask: all channels bright
    nonwhite = ~np.all(arr > 244, axis=2)
    rows = np.where(nonwhite.any(axis=1))[0]
    cols = np.where(nonwhite.any(axis=0))[0]
    if rows.size == 0 or cols.size == 0:
        return im  # entirely white/blank — leave as-is
    y0, y1 = rows[0], rows[-1] + 1
    x0, x1 = cols[0], cols[-1] + 1
    # Only trim if a real border exists; ignore tiny trims and refuse to trim
    # away almost everything (protects legit light backgrounds).
    h, w = arr.shape[:2]
    trimmed_frac = ((x1 - x0) * (y1 - y0)) / float(w * h)
    if trimmed_frac < 0.98 and trimmed_frac > 0.15:
        return im.crop((int(x0), int(y0), int(x1), int(y1)))
    return im


def get_font(path, size):
    try:
        return ImageFont.truetype(path, max(8, int(size)))
    except Exception:
        return ImageFont.load_default()


def _scale(w, h):
    """Uniform scale factor relative to the 1920x1080 design grid."""
    return min(w / BASE_W, h / BASE_H)


def round_corners(image, radius):
    mask = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), image.size], radius=radius, fill=255)
    result = Image.new("RGBA", image.size, (0, 0, 0, 0))
    result.paste(image.convert("RGBA"), (0, 0), mask=mask)
    return result


def add_drop_shadow(image, offset=(0, 8), blur=15, shadow_color=(0, 0, 0, 180)):
    w, h = image.size
    pad = blur * 2
    shadow_layer = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))

    alpha = image.split()[3]
    shadow_mask = Image.new("RGBA", image.size, shadow_color)
    shadow_mask.putalpha(alpha)

    shadow_layer.paste(shadow_mask, (pad + offset[0], pad + offset[1]))
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(blur))
    shadow_layer.paste(image, (pad, pad), mask=image)
    return shadow_layer, pad


def _wrap(draw, text, font, max_width):
    """Break text into lines that fit inside max_width."""
    words = str(text).split()
    if not words:
        return [""]
    lines, current = [], words[0]
    for word in words[1:]:
        trial = current + " " + word
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_block(draw, lines, font, cx, cy, fill, outline=None, outline_px=0):
    """Draw centred, wrapped lines around (cx, cy)."""
    heights = [draw.textbbox((0, 0), ln, font=font)[3] -
               draw.textbbox((0, 0), ln, font=font)[1] for ln in lines]
    gap = int(font.size * 0.35)
    total = sum(heights) + gap * (len(lines) - 1)
    y = cy - total // 2
    for ln, lh in zip(lines, heights):
        bbox = draw.textbbox((0, 0), ln, font=font)
        x = cx - (bbox[2] - bbox[0]) // 2
        if outline and outline_px:
            for ox in range(-outline_px, outline_px + 1):
                for oy in range(-outline_px, outline_px + 1):
                    if ox or oy:
                        draw.text((x + ox, y + oy), ln, font=font, fill=outline)
        draw.text((x, y), ln, font=font, fill=fill)
        y += lh + gap


def generate_grid_background(width=BASE_W, height=BASE_H, grid_size=40,
                             line_color=(40, 40, 40, 255), bg_color=(18, 18, 18, 255)):
    """Generate dark background with a subtle grid pattern."""
    img = Image.new("RGBA", (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    for x in range(0, width, grid_size):
        draw.line([(x, 0), (x, height)], fill=line_color, width=1)
    for y in range(0, height, grid_size):
        draw.line([(0, y), (width, y)], fill=line_color, width=1)
    return img


class GraphicCompositor:
    """Five card layouts, each rendered at an arbitrary frame size."""

    @staticmethod
    def _load_backdrop(path, width, height, blur=0):
        """Load a backdrop image (grid / sparkle) fitted to the frame; fall back
        to a generated dark grid if the file is missing or unreadable."""
        try:
            if path and os.path.exists(path):
                bg = ImageOps.fit(Image.open(path).convert("RGB"), (width, height),
                                  Image.Resampling.LANCZOS).convert("RGBA")
                if blur:
                    bg = bg.filter(ImageFilter.GaussianBlur(blur))
                return bg
        except Exception:
            pass
        return generate_grid_background(width, height)

    @staticmethod
    def style1_rounded_card_on_grid(photo_path, grid_path, output_path,
                                    width=BASE_W, height=BASE_H, card_ratio=0.82,
                                    title_text=None):
        """Central rounded photo card with a shadow over a grid background.
        Uses the real grid image at grid_path (assets/grids/*) when available,
        else a generated dark grid."""
        bg = GraphicCompositor._load_backdrop(grid_path, width, height)
        cw = int(width * card_ratio)
        ch = int(height * card_ratio)
        s = _scale(width, height)
        radius = max(8, int(24 * s))

        photo = ImageOps.fit(load_photo_trimmed(photo_path), (cw, ch),
                             Image.Resampling.LANCZOS)
        rounded = round_corners(photo, radius)
        draw_r = ImageDraw.Draw(rounded)
        draw_r.rounded_rectangle([(0, 0), (cw - 1, ch - 1)], radius=radius,
                                 outline=(255, 255, 255, 255), width=max(2, int(4 * s)))

        card, pad = add_drop_shadow(rounded, offset=(0, int(10 * s)),
                                    blur=max(4, int(20 * s)),
                                    shadow_color=(0, 0, 0, 200))
        card_x = (width - cw) // 2
        card_y = (height - ch) // 2 - int(15 * s) if title_text else (height - ch) // 2
        bg.paste(card, (card_x - pad, card_y - pad), mask=card)

        if title_text:
            draw = ImageDraw.Draw(bg)
            font = get_font(ARIAL_BOLD, int(40 * s))
            text = str(title_text).upper()
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            banner_pw = int(36 * s)
            banner_ph = int(12 * s)
            bw = tw + banner_pw * 2
            bh = th + banner_ph * 2
            bx = (width - bw) // 2
            by = card_y + ch + int(16 * s)
            draw.rectangle([(bx + int(3*s), by + int(3*s)), (bx + bw + int(3*s), by + bh + int(3*s))], fill=(0, 0, 0, 150))
            draw.rectangle([(bx, by), (bx + bw, by + bh)], fill=(198, 40, 40, 255))
            draw.text((bx + banner_pw, by + banner_ph - int(3 * s)), text, font=font, fill=(255, 255, 255, 255))

        bg.convert("RGB").save(output_path, quality=95)
        return output_path

    @staticmethod
    def style_sparkle_card(photo_path, sparkle_path, output_path,
                           width=BASE_W, height=BASE_H, card_ratio=0.62):
        """Single portrait framed with a white border + drop shadow, centred over a
        sparkle/particle background (assets/sparkle-backgrounds/*). Portrait-friendly:
        the card keeps the photo's aspect so faces are never cropped hard."""
        s = _scale(width, height)
        bg = GraphicCompositor._load_backdrop(sparkle_path, width, height)

        src = load_photo_trimmed(photo_path)
        # Fit the photo inside a centred box, preserving aspect (no hard face crop).
        box_h = int(height * 0.86)
        box_w = int(width * card_ratio)
        fitted = ImageOps.contain(src, (box_w, box_h), Image.Resampling.LANCZOS)
        border = max(4, int(10 * s))
        framed = ImageOps.expand(fitted, border=border, fill="white")
        card, pad = add_drop_shadow(framed.convert("RGBA"),
                                    offset=(0, int(12 * s)),
                                    blur=max(6, int(24 * s)),
                                    shadow_color=(0, 0, 0, 210))
        cx = (width - framed.width) // 2
        cy = (height - framed.height) // 2
        bg.paste(card, (cx - pad, cy - pad), mask=card)
        bg.convert("RGB").save(output_path, quality=95)
        return output_path

    @staticmethod
    def style2_triptych_overlay(bg_photo_path, three_photos, output_path,
                                width=BASE_W, height=BASE_H):
        """Three framed photos side by side over a warm blurred background."""
        s = _scale(width, height)
        bg = ImageOps.fit(Image.open(bg_photo_path).convert("RGB"), (width, height),
                          Image.Resampling.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(max(2, int(12 * s))))
        bg = Image.alpha_composite(
            bg.convert("RGBA"), Image.new("RGBA", (width, height), (20, 10, 30, 90)))

        spacing = int(35 * s)
        w_slot = int((width * 0.885 - 2 * spacing) / 3)
        h_slot = int(w_slot * 2 / 3)
        start_x = (width - (3 * w_slot + 2 * spacing)) // 2
        y_pos = (height - h_slot) // 2
        border = max(2, int(4 * s))

        for i, p_path in enumerate(list(three_photos)[:3]):
            im = ImageOps.fit(load_photo_trimmed(p_path), (w_slot, h_slot),
                              Image.Resampling.LANCZOS)
            im = ImageOps.expand(im, border=border, fill="white")
            card, pad = add_drop_shadow(im.convert("RGBA"),
                                        offset=(0, int(8 * s)),
                                        blur=max(3, int(14 * s)),
                                        shadow_color=(0, 0, 0, 180))
            bg.paste(card, (start_x + i * (w_slot + spacing) - pad, y_pos - pad),
                     mask=card)

        bg.convert("RGB").save(output_path, quality=95)
        return output_path

    @staticmethod
    def style3_split_typography_card(photo_path, grid_path, main_title, subtitle,
                                     output_path, width=BASE_W, height=BASE_H):
        """Photo card beside bold typography with a red accent rule.

        Below 4:3 the frame is too narrow to sit text next to a photo, so the
        layout stacks instead of splitting.
        """
        s = _scale(width, height)
        bg = generate_grid_background(width, height)
        draw = ImageDraw.Draw(bg)
        stacked = (width / height) < 1.34

        if stacked:
            card_w = int(width * 0.80)
            card_h = int(height * 0.42)
            card_x = (width - card_w) // 2
            card_y = int(height * 0.12)
            text_cx = width // 2
            text_top = card_y + card_h + int(height * 0.07)
            text_w = int(width * 0.86)
        else:
            card_w = int(width * 0.375)
            card_h = int(height * 0.796)
            card_x = int(width * 0.052)
            card_y = int(height * 0.102)
            text_cx = int(width * 0.66)
            text_top = int(height * 0.40)
            text_w = int(width * 0.31)

        photo = ImageOps.fit(Image.open(photo_path).convert("RGB"), (card_w, card_h),
                             Image.Resampling.LANCZOS)
        rounded = round_corners(photo, max(6, int(28 * s)))
        card, pad = add_drop_shadow(rounded, offset=(0, int(8 * s)),
                                    blur=max(4, int(18 * s)),
                                    shadow_color=(0, 0, 0, 190))
        bg.paste(card, (card_x - pad, card_y - pad), mask=card)

        font_title = get_font(ARIAL_BOLD, 74 * s)
        font_sub = get_font(ARIAL_BOLD, 30 * s)

        title_lines = _wrap(draw, main_title, font_title, text_w)
        y = text_top
        for ln in title_lines:
            bbox = draw.textbbox((0, 0), ln, font=font_title)
            x = text_cx - (bbox[2] - bbox[0]) // 2 if stacked else text_cx - text_w // 2
            draw.text((x, y), ln, font=font_title, fill="white")
            y += int(font_title.size * 1.18)

        rule_w = int(text_w * 0.92)
        rule_x = text_cx - rule_w // 2 if stacked else text_cx - text_w // 2
        y += int(10 * s)
        draw.line([(rule_x, y), (rule_x + rule_w, y)], fill=(220, 38, 38, 255),
                  width=max(2, int(5 * s)))

        y += int(20 * s)
        for ln in _wrap(draw, str(subtitle).upper(), font_sub, text_w):
            bbox = draw.textbbox((0, 0), ln, font=font_sub)
            x = text_cx - (bbox[2] - bbox[0]) // 2 if stacked else text_cx - text_w // 2
            draw.text((x, y), ln, font=font_sub, fill=(200, 200, 200, 255))
            y += int(font_sub.size * 1.3)

        bg.convert("RGB").save(output_path, quality=95)
        return output_path

    @staticmethod
    def style4_centered_headline(photo_path, headline_text, output_path,
                                 width=BASE_W, height=BASE_H):
        """Archival photo, desaturated, with a bold centred typewriter title."""
        s = _scale(width, height)
        im = ImageOps.fit(Image.open(photo_path).convert("RGB"), (width, height),
                          Image.Resampling.LANCZOS)
        im = ImageOps.grayscale(im).convert("RGB")
        draw = ImageDraw.Draw(im)
        font = get_font(COUR_BOLD, 72 * s)
        lines = _wrap(draw, headline_text, font, int(width * 0.86))
        _draw_block(draw, lines, font, width // 2, height // 2,
                    fill=(255, 255, 255), outline=(0, 0, 0),
                    outline_px=max(1, int(3 * s)))
        im.save(output_path, quality=95)
        return output_path

    @staticmethod
    def style5_quote_caption(photo_path, quote_text, output_path,
                             width=BASE_W, height=BASE_H):
        """Moody photo with a centred typewriter quote."""
        s = _scale(width, height)
        im = ImageOps.fit(Image.open(photo_path).convert("RGB"), (width, height),
                          Image.Resampling.LANCZOS)
        im = ImageOps.grayscale(im).convert("RGB")
        draw = ImageDraw.Draw(im)
        font = get_font(COUR_BOLD, 52 * s)
        lines = _wrap(draw, quote_text, font, int(width * 0.82))
        _draw_block(draw, lines, font, width // 2, height // 2,
                    fill=(245, 245, 245), outline=(0, 0, 0),
                    outline_px=max(1, int(2 * s)))
        im.save(output_path, quality=95)
        return output_path
