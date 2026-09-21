"""Tests for the signature grade + channel watermark (workstream D+E).

stdlib unittest only.
"""

import os
import shutil
import tempfile
import unittest

from PIL import Image

from style.signature_grade import grade_filter, preview
from style.watermark import make_badge, watermark_filter


class TestGradeFilter(unittest.TestCase):
    def test_returns_nonempty_string(self):
        vf = grade_filter()
        self.assertIsInstance(vf, str)
        self.assertTrue(vf.strip(), "grade_filter() must not be empty")

    def test_contains_rgb_shift_and_noise(self):
        vf = grade_filter()
        self.assertIn("rgbashift", vf, "must shift RGB channels")
        self.assertIn("noise=", vf, "must add film grain")

    def test_shift_is_subtle_and_scaled(self):
        vf_1080 = grade_filter(height=1080)
        vf_720 = grade_filter(height=720)
        # ~1-2px at 1080p: rh/bh offsets must be small integers.
        for token in vf_1080.replace(",", " ").split():
            for key in ("rh=", "bh="):
                if token.startswith(key):
                    self.assertLessEqual(abs(int(token[len(key):])), 2)
        # 720p must not exceed the 1080p shift (resolution-independent).
        def shift_of(vf):
            for token in vf.replace(",", " ").split():
                if token.startswith("rh="):
                    return int(token[3:])
            return 0
        self.assertLessEqual(shift_of(vf_720), shift_of(vf_1080))

    def test_grain_can_be_disabled(self):
        vf = grade_filter(grain=0)
        self.assertIn("rgbashift", vf)
        self.assertNotIn("noise=", vf)

    def test_no_heavy_filters(self):
        vf = grade_filter()
        for heavy in ("gblur", "boxblur", "unsharp", "hqdn3d", "deflate"):
            self.assertNotIn(heavy, vf)


class TestMakeBadge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="badge_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _path(self, name="badge.png"):
        return os.path.join(self.tmp, name)

    def test_creates_png_of_requested_size_with_alpha(self):
        out = make_badge("ROYAL INSIDER", self._path(), size=200)
        self.assertTrue(os.path.isfile(out))
        with Image.open(out) as img:
            self.assertEqual(img.size, (200, 200))
            self.assertEqual(img.mode, "RGBA", "badge must have an alpha channel")
            self.assertEqual(img.format, "PNG")

    def test_badge_is_circular_with_transparent_corners(self):
        out = make_badge("ROYAL INSIDER", self._path(), size=200)
        with Image.open(out) as img:
            # Corners of the canvas must be fully transparent (circle, not square).
            for corner in [(0, 0), (0, 199), (199, 0), (199, 199)]:
                self.assertEqual(img.getpixel(corner)[3], 0)
            # Center must be opaque (the navy disc).
            self.assertEqual(img.getpixel((100, 100))[3], 255)

    def test_badge_has_visible_text(self):
        out = make_badge("ROYAL INSIDER", self._path(), size=200)
        img = Image.open(out).convert("RGB")
        # The white serif text must differ from the navy background
        # somewhere in the middle band of the disc.
        navy = (13, 27, 54)
        found = False
        for y in range(70, 130, 4):
            for x in range(50, 150, 4):
                px = img.getpixel((x, y))
                if sum(abs(a - b) for a, b in zip(px, navy)) > 120:
                    found = True
                    break
            if found:
                break
        self.assertTrue(found, "no legible text found on the badge")

    def test_different_names_produce_different_badges(self):
        a = make_badge("ROYAL INSIDER", self._path("a.png"))
        b = make_badge("PALACE INSIDER", self._path("b.png"))
        with open(a, "rb") as f:
            bytes_a = f.read()
        with open(b, "rb") as f:
            bytes_b = f.read()
        self.assertNotEqual(bytes_a, bytes_b)

    def test_regeneration_is_deterministic(self):
        a = make_badge("ROYAL INSIDER", self._path("a.png"))
        b = make_badge("ROYAL INSIDER", self._path("b.png"))
        with open(a, "rb") as f:
            bytes_a = f.read()
        with open(b, "rb") as f:
            bytes_b = f.read()
        self.assertEqual(bytes_a, bytes_b,
                         "same inputs must produce identical badge bytes")

    def test_single_word_name(self):
        out = make_badge("ROYALS", self._path(), size=200)
        self.assertTrue(os.path.isfile(out))
        with Image.open(out) as img:
            self.assertEqual(img.size, (200, 200))


class TestWatermarkFilter(unittest.TestCase):
    def test_references_badge_path_and_top_right(self):
        vf = watermark_filter("/tmp/work/badge.png")
        self.assertIn("/tmp/work/badge.png", vf)
        self.assertIn("overlay", vf)
        # Top-right: x pinned to W-w-margin, y small.
        self.assertIn("W-w-", vf)
        self.assertIn("y=", vf)

    def test_badge_scaled_to_badge_px(self):
        vf = watermark_filter("b.png", badge_px=140)
        self.assertIn("scale=140:140", vf)

    def test_custom_margin(self):
        vf = watermark_filter("b.png", margin=32)
        self.assertIn("W-w-32", vf)

    def test_path_escaping(self):
        vf = watermark_filter("/tmp/a,b/c:d.png")
        # Comma/colon must be backslash-escaped for the movie filter.
        self.assertIn("movie=", vf)
        self.assertIn("/tmp/a\\,b/c\\:d.png", vf)
        self.assertNotIn("/tmp/a,b/c:d.png", vf)


class TestPreviewHelper(unittest.TestCase):
    def test_preview_missing_input_raises(self):
        with self.assertRaises(FileNotFoundError):
            preview("/nonexistent/input.jpg",
                    os.path.join(tempfile.gettempdir(), "x.mp4"))

    def test_preview_signature(self):
        import inspect
        sig = inspect.signature(preview)
        self.assertIn("input_path", sig.parameters)
        self.assertIn("out_path", sig.parameters)
        self.assertEqual(sig.parameters["seconds"].default, 3)


if __name__ == "__main__":
    unittest.main()
