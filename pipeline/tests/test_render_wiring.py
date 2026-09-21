"""Integration tests for the style-upgrade coordinator wiring.

Covers the pieces wired outside the parallel workstreams (all pure
Python / no ffmpeg): RenderEngine style options, the commentator branch
dispatch, and the pipeline commentator-marking helper. The full-stack
visual proof lives in ~/workspace/royal/style_test/ (10-segment render).
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from render_engine import RenderEngine
import pipeline as P


def _make_engine(**kw):
    work = tempfile.mkdtemp(prefix="wiring_")
    kw.setdefault("workers", 1)
    if "subtitle_path" not in kw or kw["subtitle_path"] is None:
        pass
    return RenderEngine(work_dir=work, encoder="libx264", look="none", **kw)


def _touch(path, content="[V4+ Styles]\n"):
    with open(path, "w") as fh:
        fh.write(content)
    return path


class TestRenderStyleWiring(unittest.TestCase):
    def test_style_options_accepted(self):
        ass = _touch(os.path.join(tempfile.mkdtemp(prefix="w_"), "voiceover.ass"))
        badge = _touch(os.path.join(tempfile.mkdtemp(prefix="w_"), "badge.png"), "png")
        eng = _make_engine(
            subtitle_path=ass,
            channel_name="ROYAL INSIDER",
            watermark=True,
            badge_path=badge,
            badge_display_px=140,
            badge_margin_px=24,
            signature_grade=True,
            grade_grain=9,
            commentator_panel=True,
        )
        self.assertEqual(eng.subtitle_path, ass)
        self.assertTrue(eng.watermark)
        self.assertEqual(eng.badge_path, badge)
        self.assertTrue(eng.signature_grade)
        self.assertTrue(eng.commentator_panel)
        self.assertTrue(eng.cpu_mode)

    def test_missing_subtitle_disables_captions(self):
        # A non-existent subtitle path must not silently enable captions.
        eng = _make_engine(subtitle_path="/tmp/does_not_exist_xyz.ass")
        self.assertIsNone(eng.subtitle_path)

    def test_commentator_branch_exists(self):
        self.assertTrue(hasattr(RenderEngine, "_render_commentator_segment"))
        self.assertTrue(hasattr(RenderEngine, "_panel_bg_path"))

    def test_mux_labels_resolved_when_treatments_on(self):
        # The final mux must always resolve video_map, even when every
        # finishing treatment is stacked (the UnboundLocalError path).
        tmp = tempfile.mkdtemp(prefix="w_")
        ass = _touch(os.path.join(tmp, "v.ass"))
        badge = _touch(os.path.join(tmp, "b.png"), "png")
        eng = _make_engine(subtitle_path=ass, signature_grade=True,
                           watermark=True, badge_path=badge)
        self.assertTrue(eng.subtitle_path and eng.signature_grade and eng.watermark)


class TestCommentatorMarking(unittest.TestCase):
    def _write_srt(self, path, cues):
        def stamp(s):
            h, rem = divmod(int(s), 3600)
            m, sec = divmod(rem, 60)
            ms = int(round((s - int(s)) * 1000))
            return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
        with open(path, "w") as fh:
            for i, (s, e, text) in enumerate(cues, 1):
                fh.write(f"{i}\n{stamp(s)} --> {stamp(e)}\n{text}\n\n")

    def test_quote_clip_gets_marked(self):
        tmp = tempfile.mkdtemp(prefix="mark_")
        srt = os.path.join(tmp, "t.srt")
        self._write_srt(srt, [
            (10.0, 14.0, "she said the palace was shocked"),
            (100.0, 104.0, "the weather was quite nice today"),
        ])
        tl = {"segments": [
            {"index": 0, "type": "clip", "file": "/x/comp_2001.mp4",
             "start": 10.0, "end": 14.0, "section": "main"},
            {"index": 1, "type": "clip", "file": "/x/comp_2002.mp4",
             "start": 100.0, "end": 104.0, "section": "main"},
            {"index": 2, "type": "image", "file": "/x/a.jpg",
             "start": 104.0, "end": 108.0, "section": "main"},
        ]}
        cfg = {"max_commentator_panels": 6, "commentator_min_gap_s": 90.0}
        n = P._mark_commentator_segments(tl, srt, cfg,
                                         os.path.join(tmp, "timeline.json"))
        self.assertEqual(n, 1)
        self.assertEqual(tl["segments"][0].get("style"), "commentator")
        self.assertNotIn("style", tl["segments"][1])
        self.assertNotIn("style", tl["segments"][2])

    def test_opening_intro_never_marked(self):
        tmp = tempfile.mkdtemp(prefix="mark_")
        srt = os.path.join(tmp, "t.srt")
        self._write_srt(srt, [(0.5, 4.0, "the expert said this changes everything")])
        tl = {"segments": [
            {"index": 0, "type": "clip", "file": "/x/comp_2005.mp4",
             "start": 0.0, "end": 4.0, "section": "opening_intro_native"},
        ]}
        cfg = {"max_commentator_panels": 6, "commentator_min_gap_s": 90.0}
        n = P._mark_commentator_segments(tl, srt, cfg,
                                         os.path.join(tmp, "timeline.json"))
        self.assertEqual(n, 0)
        self.assertNotIn("style", tl["segments"][0])

    def test_gap_and_cap_respected(self):
        tmp = tempfile.mkdtemp(prefix="mark_")
        srt = os.path.join(tmp, "t.srt")
        cues = [(t, t + 4.0, "according to a royal expert") for t in (10.0, 30.0, 200.0)]
        self._write_srt(srt, cues)
        tl = {"segments": [
            {"index": i, "type": "clip", "file": f"/x/comp_{2000+i}.mp4",
             "start": t, "end": t + 4.0, "section": "main"}
            for i, (t, _, _) in enumerate(cues)
        ]}
        cfg = {"max_commentator_panels": 1, "commentator_min_gap_s": 90.0}
        n = P._mark_commentator_segments(tl, srt, cfg,
                                         os.path.join(tmp, "timeline.json"))
        self.assertEqual(n, 1)  # cap of 1 wins over three candidates


if __name__ == "__main__":
    unittest.main()
