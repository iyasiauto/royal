"""Workstream B+G+H tests: pacing cap, irrelevant-visual guard, motion target.

stdlib unittest only. Everything runs against synthetic segment dicts and a
fake matcher — no asset scanning, no rendering.
"""

import unittest

from timeline_engine import TimelineEngine


class FakeAsset:
    def __init__(self, path, entity=None, source_id="src"):
        self.path = path
        self.entity = entity
        self.source_id = source_id


class FakeMatcher:
    """Mimics SemanticMatcher.pick: (asset, score, entities)."""

    def __init__(self, paths, score=5.0, scores=None):
        self.paths = list(paths)
        self.default_score = score
        self.scores = scores or {}
        self.i = 0
        self.used_paths = set()

    def pick(self, start, end, kind, position):
        p = self.paths[self.i % len(self.paths)]
        self.i += 1
        self.used_paths.add(p)
        return FakeAsset(p), self.scores.get(p, self.default_score), []


def make_seg(i, start, dur, kind="image", section="body", file=None):
    return {
        "index": i,
        "start": round(start, 2),
        "end": round(start + dur, 2),
        "duration": round(dur, 2),
        "type": kind,
        "file": file or "/pool/%s_%02d.dat" % (kind, i),
        "motion": "zoomin" if kind == "image" else "none",
        "postcard": False,
        "has_audio": False,
        "section": section,
    }


def make_engine(**cfg_overrides):
    cfg = {"relevance_threshold": 1.0}
    cfg.update(cfg_overrides)
    return TimelineEngine([], [], [], topic_config=cfg)


class PacingTest(unittest.TestCase):
    def test_no_hold_exceeds_max_after_pacing(self):
        eng = make_engine()
        eng.matcher = None
        segs = [
            make_seg(0, 0, 12.0, "image"),                       # -> 4 x 3.0s
            make_seg(1, 12, 4.0, "clip"),                        # untouched
            make_seg(2, 16, 15.0, "image"),                      # -> 5 x 3.0s
            make_seg(3, 31, 9.0, "image",
                     section="opening_intro_native"),            # exempt
            make_seg(4, 40, 9.0, "image", section="datetime_card"),  # exempt
        ]
        curated = ["/pool/c%d.jpg" % k for k in range(1, 4)]
        out = eng._apply_pacing_pass(segs, graphics=["/gfx/card1.jpg"],
                                     curated=curated)

        total_in = sum(s["duration"] for s in segs)
        total_out = sum(s["duration"] for s in out)
        self.assertAlmostEqual(total_out, total_in, places=6)

        for s in out:
            if s["section"] in ("opening_intro_native", "datetime_card"):
                continue  # exempt by design (never split)
            self.assertLessEqual(s["duration"], 6.0)
            if s.get("pacing_split"):
                self.assertGreaterEqual(s["duration"], 2.0)
                self.assertLessEqual(s["duration"], 4.0)

        # continuity: sub-shots tile the parent's [start, end] exactly
        for prev, cur in zip(out, out[1:]):
            self.assertAlmostEqual(cur["start"], prev["end"], places=6)

        # 4 + 1 + 5 + 1 + 1 = 12 segments
        self.assertEqual(len(out), 12)
        self.assertEqual(eng._pacing_splits, 2)

        # exempt sections keep their original visual untouched
        intro = [s for s in out if s["section"] == "opening_intro_native"]
        dtc = [s for s in out if s["section"] == "datetime_card"]
        self.assertEqual(len(intro), 1)
        self.assertEqual(intro[0]["duration"], 9.0)
        self.assertNotIn("pacing_split", intro[0])
        self.assertEqual(len(dtc), 1)
        self.assertEqual(dtc[0]["duration"], 9.0)

    def test_split_shot_counts(self):
        eng = make_engine()
        self.assertEqual(eng._pacing_subshots(6.01), 2)
        self.assertEqual(eng._pacing_subshots(8.0), 3)
        self.assertEqual(eng._pacing_subshots(12.0), 4)
        self.assertEqual(eng._pacing_subshots(15.0), 5)
        self.assertEqual(eng._pacing_subshots(20.0), 7)
        for dur in (6.5, 9.0, 12.0, 15.0, 25.0):
            n = eng._pacing_subshots(dur)
            self.assertGreaterEqual(dur / n, 2.0)
            self.assertLessEqual(dur / n, 4.0)

    def test_splits_use_distinct_visuals(self):
        eng = make_engine()
        paths = ["/m/img%02d.jpg" % k for k in range(50)]
        eng.matcher = FakeMatcher(paths, score=5.0)
        segs = [make_seg(0, 0, 12.0, "image", file="/pool/original.jpg")]
        out = eng._apply_pacing_pass(segs, graphics=[], curated=[])

        self.assertEqual(len(out), 4)
        files = [s["file"] for s in out]
        # never the same asset twice in a row, and never the parent's frame
        for a, b in zip(files, files[1:]):
            self.assertNotEqual(a, b)
        self.assertNotIn("/pool/original.jpg", files)
        self.assertEqual(len(set(files)), 4)
        # motions vary too (no identical static frame stretched)
        motions = [s["motion"] for s in out]
        for a, b in zip(motions, motions[1:]):
            self.assertNotEqual(a, b)

    def test_splits_without_matcher_use_curated_pool(self):
        eng = make_engine()
        eng.matcher = None
        curated = ["/pool/c1.jpg", "/pool/c2.jpg", "/pool/c3.jpg"]
        segs = [make_seg(0, 0, 9.0, "image", file="/pool/orig.jpg")]
        out = eng._apply_pacing_pass(segs, graphics=[], curated=curated)
        files = [s["file"] for s in out]
        for a, b in zip(files, files[1:]):
            self.assertNotEqual(a, b)
        for f in files:
            self.assertIn(f, curated)


class GuardTest(unittest.TestCase):
    def test_below_threshold_pick_is_replaced(self):
        eng = make_engine()
        asset = FakeAsset("/m/weak.jpg")
        f, replaced, cur = eng._relevance_gate(asset, 0.0,
                                              ["/gfx/card1.jpg"], 0)
        self.assertTrue(replaced)
        self.assertEqual(f, "/gfx/card1.jpg")
        self.assertEqual(cur, 1)
        self.assertEqual(eng._guard_replacements, 1)

    def test_above_threshold_pick_is_kept(self):
        eng = make_engine()
        asset = FakeAsset("/m/strong.jpg")
        f, replaced, cur = eng._relevance_gate(asset, 5.0,
                                              ["/gfx/card1.jpg"], 0)
        self.assertFalse(replaced)
        self.assertEqual(f, "/m/strong.jpg")
        self.assertEqual(cur, 0)
        self.assertEqual(eng._guard_replacements, 0)

    def test_threshold_is_configurable(self):
        eng = make_engine(relevance_threshold=10.0)
        asset = FakeAsset("/m/mid.jpg")
        f, replaced, _ = eng._relevance_gate(asset, 5.0,
                                            ["/gfx/card1.jpg"], 0)
        self.assertTrue(replaced)
        self.assertEqual(f, "/gfx/card1.jpg")

    def test_no_graphics_keeps_original_pick(self):
        eng = make_engine()
        asset = FakeAsset("/m/weak.jpg")
        f, replaced, _ = eng._relevance_gate(asset, 0.0, [], 0)
        self.assertFalse(replaced)
        self.assertEqual(f, "/m/weak.jpg")

    def test_pacing_applies_guard_to_subshots(self):
        eng = make_engine()
        # every matcher pick scores 0.0 -> all sub-shots become cards
        eng.matcher = FakeMatcher(["/m/weak.jpg"], score=0.0)
        segs = [make_seg(0, 0, 12.0, "image")]
        out = eng._apply_pacing_pass(segs,
                                     graphics=["/gfx/c1.jpg", "/gfx/c2.jpg"],
                                     curated=[])
        self.assertEqual(len(out), 4)
        for s in out:
            self.assertEqual(s["section"], "guard_fallback")
            self.assertIn(s["file"], ["/gfx/c1.jpg", "/gfx/c2.jpg"])
        self.assertEqual(eng._guard_replacements, 4)


class MotionTargetTest(unittest.TestCase):
    def _timeline(self, n=40):
        segs = []
        t = 0.0
        for i in range(n):
            # odd indices are images -> they land on the wheel's static slots
            kind = "image" if i % 2 == 1 else "clip"
            dur = round(2.0 + (i * 0.37) % 3.8, 2)
            segs.append(make_seg(i, t, dur, kind))
            t = round(t + dur, 2)
        return segs

    def test_static_share_detects_wheel_static_slots(self):
        eng = make_engine()
        segs = self._timeline()
        share = eng._static_share(segs)
        # images sit on idx%12 in {3,9} -> measurably static
        self.assertGreater(share, 0.0)

    def test_static_share_within_target_after_steering(self):
        eng = make_engine()
        segs = self._timeline()
        eng._renumber_for_motion(segs)
        share = eng._static_share(segs)
        self.assertLessEqual(share, 0.20)

        # indices stay unique and ordered
        idxs = [s["index"] for s in segs]
        self.assertEqual(len(set(idxs)), len(idxs))
        self.assertEqual(idxs, sorted(idxs))

        # no image lands on a static wheel slot
        slots = eng._wheel_static_slots()
        for s in segs:
            if s["type"] == "image":
                self.assertNotIn(s["index"] % 12, slots)

    def test_wheel_slots_match_renderer(self):
        from render_engine import motion_wheel
        eng = make_engine()
        expected = {i for i in range(12) if motion_wheel(i) == "static"}
        self.assertEqual(eng._wheel_static_slots(), expected)
        self.assertTrue(expected)  # the wheel really does have static slots


if __name__ == "__main__":
    unittest.main()
