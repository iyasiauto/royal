"""Unit tests for style/commentator_panel.py (stdlib unittest only)."""
import os
import sys
import tempfile
import unittest

# Load commentator_panel.py directly by file path (not via the style package),
# so sibling workstream modules in style/__init__.py are never imported.
import importlib.util  # noqa: E402

_MOD_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "style", "commentator_panel.py")
_spec = importlib.util.spec_from_file_location("commentator_panel", _MOD_PATH)
_cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cp)

from PIL import Image  # noqa: E402

BG_COLOR = _cp.BG_COLOR
PANEL_GEOMETRY = _cp.PANEL_GEOMETRY
build_panel_filter = _cp.build_panel_filter
detect_fg_kind = _cp.detect_fg_kind
make_panel_background = _cp.make_panel_background
trim_white_border = _cp._trim_white_border


class TestPanelBackground(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="panel_test_")
        self.bg = os.path.join(self.tmp, "bg.png")

    def test_background_is_full_frame_rgb(self):
        out = make_panel_background(self.bg)
        self.assertTrue(os.path.exists(out))
        im = Image.open(out)
        self.assertEqual(im.size, (1920, 1080))
        self.assertIn(im.mode, ("RGB", "RGBA"))

    def test_geometry_panel_inside_frame_with_margins(self):
        (fw, fh) = PANEL_GEOMETRY["frame"]
        (px, py, pw, ph) = PANEL_GEOMETRY["panel"]
        self.assertEqual((fw, fh), (1920, 1080))
        self.assertGreaterEqual(px, 40)
        self.assertGreaterEqual(py, 40)
        self.assertLessEqual(px + pw, fw - 40)
        self.assertLessEqual(py + ph, fh - 40)
        # even dimensions for yuv
        self.assertEqual(pw % 2, 0)
        self.assertEqual(ph % 2, 0)
        # ~72% width, centred
        self.assertAlmostEqual(pw / fw, 0.72, delta=0.01)
        self.assertEqual(px, (fw - pw) // 2)
        self.assertEqual(py, (fh - ph) // 2)
        self.assertGreater(PANEL_GEOMETRY["corner_radius"], 0)

    def test_glow_border_pixels_differ_from_flat_background(self):
        make_panel_background(self.bg)
        im = Image.open(self.bg).convert("RGB")
        (px, py, pw, ph) = PANEL_GEOMETRY["panel"]

        bg_px = im.getpixel((10, 10))
        # flat corner should be (near) the navy background
        self.assertTrue(all(abs(a - b) <= 24 for a, b in zip(bg_px, BG_COLOR)),
                        f"corner pixel {bg_px} is not the navy background")

        # border ring sits just outside the panel slot: sample the top edge
        out = PANEL_GEOMETRY["border_width"] // 2 + 2
        border_px = im.getpixel((px + pw // 2, py - out))
        self.assertTrue(all(c >= 200 for c in border_px),
                        f"border pixel {border_px} is not bright white")
        self.assertNotEqual(border_px, bg_px)

        # glow halo further out: lighter than navy, darker than the border
        halo_px = im.getpixel((px + pw // 2, py - out - 40))
        self.assertNotEqual(halo_px, bg_px)
        self.assertTrue(sum(halo_px) > sum(bg_px))
        self.assertTrue(sum(halo_px) < sum(border_px))

    def test_detect_fg_kind(self):
        self.assertEqual(detect_fg_kind("clip.mp4"), "video")
        self.assertEqual(detect_fg_kind("comp_foo.MOV"), "video")
        self.assertEqual(detect_fg_kind("still.JPG"), "image")
        self.assertEqual(detect_fg_kind("photo.png"), "image")
        with self.assertRaises(ValueError):
            detect_fg_kind("weird.xyz")


    def test_white_border_trim(self):
        # synthetic postcard: red centre on a white canvas
        src = os.path.join(self.tmp, "postcard.png")
        card = Image.new("RGB", (800, 600), (255, 255, 255))
        card.paste(Image.new("RGB", (400, 300), (200, 30, 30)), (200, 150))
        card.save(src)
        trimmed = trim_white_border(src, self.tmp)
        self.assertNotEqual(trimmed, src)
        self.assertEqual(Image.open(trimmed).size, (400, 300))
        # plain photo (no white border) is returned untouched
        plain = os.path.join(self.tmp, "plain.png")
        Image.new("RGB", (400, 300), (30, 60, 120)).save(plain)
        self.assertEqual(trim_white_border(plain, self.tmp), plain)


class TestPanelFilter(unittest.TestCase):
    def test_filter_builder_video(self):
        fc = build_panel_filter(fg_kind="video", duration=4.0)
        (px, py, pw, ph) = PANEL_GEOMETRY["panel"]
        self.assertIsInstance(fc, str)
        self.assertIn("[vout]", fc)
        self.assertIn("[1:v]", fc)          # foreground input label
        self.assertIn("[0:v]", fc)          # background input label
        self.assertIn(f"scale={pw}:{ph}", fc)  # foreground scaled to panel
        self.assertIn(f"overlay={px}:{py}", fc)  # panel region placement
        self.assertIn("yuv420p", fc)

    def test_filter_builder_image_has_pan(self):
        fc = build_panel_filter(fg_kind="image", duration=6.0)
        (px, py, pw, ph) = PANEL_GEOMETRY["panel"]
        self.assertIn(f"crop={pw}:{ph}", fc)
        self.assertIn("t/6.0", fc)          # time-varying drift pan
        self.assertIn(f"overlay={px}:{py}", fc)

    def test_filter_builder_rejects_bad_duration(self):
        with self.assertRaises(ValueError):
            build_panel_filter(duration=0)
        with self.assertRaises(ValueError):
            build_panel_filter(fg_kind="audio", duration=4.0)


if __name__ == "__main__":
    unittest.main()
