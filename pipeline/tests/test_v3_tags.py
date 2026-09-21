"""Tests for V3 corpus tags (RULE 41/49): subject normalization, tag-file
loading for both tag JSONs, and Tier-0 preference with a v3 william clip.

Stdlib unittest only - pytest is not installed on this box.
Run:  cd ~/workspace/royal/repo && ~/workspace/royal/venv/bin/python -m unittest discover -s pipeline/tests
"""
import json
import os
import sys
import unittest
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from semantic_matcher import Asset, AssetIndex, SemanticMatcher, load_tags
from v3_subjects import (normalize_subjects, normalize_topics,
                         normalize_shot_type, tag_entry, v3_basename)

CONFIGS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "configs")


class TestV3Normalization(unittest.TestCase):
    def test_canonical_map(self):
        p = tag_entry('King Charles III', '["Queen Camilla","unknown person"]',
                      'royal walkabout', 'outdoors', 'Medium shot')['persons']
        self.assertEqual(p, ['king charles', 'queen camilla'])

    def test_uncertain_prefix_stripped_name_kept(self):
        p = tag_entry('uncertain: Emma Watson', None, None, 'unknown',
                      'Close-up')['persons']
        self.assertEqual(p, ['emma watson'])

    def test_combo_split(self):
        p = tag_entry('Prince William and Princess Anne', None, None,
                      None, None)['persons']
        self.assertEqual(p, ['prince william', 'princess anne'])

    def test_non_persons_dropped_honest_empty(self):
        e = tag_entry('unknown person', '["crowd"]', 'unknown', 'unknown', None)
        self.assertEqual(e, {'persons': [], 'topics': [], 'clip_type': 'other'})

    def test_title_variants_merge(self):
        self.assertEqual(
            normalize_subjects('Sophie, Duchess of Edinburgh', None),
            ['sophie, duchess of edinburgh'])
        self.assertEqual(
            normalize_subjects('Princess Sophie (Duchess of Edinburgh)', None),
            ['sophie, duchess of edinburgh'])
        self.assertEqual(
            normalize_subjects('Prince Edward, Duke of Edinburgh', None),
            ['prince edward'])

    def test_topics_drop_unknown(self):
        self.assertEqual(normalize_topics('royal walkabout', 'unknown'),
                         ['royal walkabout'])
        self.assertEqual(normalize_topics('unknown', 'unknown'), [])

    def test_shot_type_normalized(self):
        self.assertEqual(normalize_shot_type('Medium shot'), 'medium_shot')
        self.assertEqual(normalize_shot_type('Split-screen close-up'),
                         'split_screen_close_up')
        self.assertEqual(normalize_shot_type(''), 'other')

    def test_basename_scheme(self):
        self.assertEqual(
            v3_basename('src_abae9a6ca7a46e68', 'clip_071c64291a026893'),
            'v3_abae9a6c_071c6429.mp4')


class TestTagFilesLoad(unittest.TestCase):
    def _load(self, name):
        path = os.path.join(CONFIGS, name)
        self.assertTrue(os.path.exists(path), f"missing {name}")
        return load_tags(path)

    def test_clip_tags_json_schema(self):
        tags = self._load("clip_tags.json")
        self.assertEqual(len(tags), 189)
        for key, val in tags.items():
            self.assertIsInstance(val, dict)
            self.assertIn("persons", val)
            self.assertTrue(all(p == p.lower() for p in val["persons"]),
                            f"not lowercase: {key}")
            self.assertNotIn("unknown", val["persons"], key)

    def test_clip_tags_v3_json_schema(self):
        tags = self._load("clip_tags_v3.json")
        self.assertEqual(len(tags), 3319)
        n_persons = 0
        for key, val in tags.items():
            self.assertTrue(key.startswith("v3_") and key.endswith(".mp4"), key)
            self.assertIsInstance(val, dict)
            self.assertIn("persons", val)
            self.assertTrue(all(p == p.lower() for p in val["persons"]),
                            f"not lowercase: {key}")
            self.assertFalse(any("unknown" in p or "uncertain" in p
                                 for p in val["persons"]), key)
            self.assertFalse(any(t == "unknown" for t in val["topics"]), key)
            n_persons += bool(val["persons"])
        # The vast majority of V3 clips must carry a person tag.
        self.assertGreater(n_persons / len(tags), 0.95)

    def test_both_files_apply_to_matcher(self):
        idx = AssetIndex()
        v3_tags = self._load("clip_tags_v3.json")
        william_key = next(k for k, v in v3_tags.items()
                           if "prince william" in v["persons"])
        idx.assets.append(Asset(f"/pool/v3_clips/{william_key}", "clip",
                                None, set(), "t"))
        applied = idx.apply_tags(v3_tags)
        self.assertEqual(applied, 1)
        self.assertIn("prince william", idx.assets[0].persons)


class TestTier0V3(unittest.TestCase):
    def test_william_segment_prefers_v3_william_clip(self):
        idx = AssetIndex()
        v3_tags = load_tags(os.path.join(CONFIGS, "clip_tags_v3.json"))
        william_key = next(k for k, v in v3_tags.items()
                           if "prince william" in v["persons"])
        idx.assets.append(Asset(f"/pool/v3_clips/{william_key}", "clip",
                                None, set(), "t"))
        idx.assets.append(Asset("/pool/clips/comp_0000.mp4", "clip",
                                None, set(), "t"))
        idx.apply_tags(v3_tags)
        idx.build_idf()
        m = SemanticMatcher(idx, script_timeline=None,
                            default_entity="meghan markle")
        m.query = lambda s, e: (Counter({"prince": 1, "william": 3}),
                                {"prince william": 5.0}, None)
        asset, score, _ = m.pick(0, 5, "clip", 0.5)
        self.assertIn("prince william", asset.persons,
                      f"Tier-0 failed, picked {asset.path}")
        self.assertTrue(os.path.basename(asset.path).startswith("v3_"))


class TestDefaultTagFiles(unittest.TestCase):
    """Regression: default_tag_files() must resolve to the shipped repo tags
    on every OS. It previously used config.PIPELINE_DIR (a hardcoded Windows
    path), so on Linux the tag files silently failed to load and Tier-0
    person matching never fired in production."""

    def test_default_tag_files_exist_in_repo(self):
        import pipeline as P
        files = P.default_tag_files()
        self.assertEqual(len(files), 2)
        for p in files:
            self.assertTrue(os.path.isabs(p), p)
            self.assertTrue(os.path.exists(p), f"default tag file missing: {p}")
            self.assertTrue(
                os.path.dirname(p).endswith("configs"),
                f"not under repo configs/: {p}")

    def test_load_all_tags_picks_up_defaults(self):
        import pipeline as P
        tags = P.load_all_tags(None)
        self.assertGreater(len(tags), 3000,
                           "default tag files did not load — Tier-0 is dead")
        self.assertTrue(any(k.startswith("v3_") for k in tags))
        self.assertTrue(any(k.startswith("comp_") for k in tags))


if __name__ == "__main__":
    unittest.main()
