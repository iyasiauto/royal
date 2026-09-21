"""Tests for structured clip tags (persons/topics/clip_type) and the
subject-synced clip picking built on them (workstream A).

Stdlib unittest only - pytest is not installed on this box.
Run:  cd pipeline && python -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from semantic_matcher import (AssetIndex, ScriptTimeline, SemanticMatcher,
                              load_tags, norm_person)
from make_clip_tags import (seed_clip_tags, known_persons_from_entity_root,
                            detect_clip_type)


def _touch(dir_path, *names):
    for n in names:
        open(os.path.join(dir_path, n), "w").close()


def _clip_index(tmpdir, files, entity="meghan markle"):
    """Index empty .mp4 stand-ins as clips (add_dir only globs, never reads)."""
    _touch(tmpdir, *files)
    index = AssetIndex()
    index.add_dir(tmpdir, "clip", entity=entity)
    return index


def _matcher(index, text, default_entity="meghan markle"):
    index.build_idf()
    # Register a second person so entities_in() can detect them in narration.
    index.entities.setdefault("prince harry", 0)
    script = ScriptTimeline([(0.0, 30.0, text)])
    return SemanticMatcher(index, script, default_entity=default_entity)


def _picked_basename(matcher, start=0.0, end=6.0, position=0):
    asset, score, _ = matcher.pick(start, end, "clip", position)
    assert asset is not None, "pick() returned None - pool unexpectedly empty"
    return os.path.basename(asset.path)


class TestTagSchema(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.index = _clip_index(self.tmp.name, ["comp_0001.mp4"])
        self.asset = self.index.assets[0]

    def test_legacy_list_format_still_works(self):
        n = self.index.apply_tags({"comp_0001.mp4": ["wedding", "windsor"]})
        self.assertEqual(n, 1)
        self.assertIn("wedding", self.asset.tokens)
        self.assertIn("windsor", self.asset.tokens)
        self.assertEqual(self.asset.persons, set())
        self.assertIsNone(self.asset.clip_type)

    def test_legacy_single_string_value(self):
        self.index.apply_tags({"comp_0001.mp4": "polo match"})
        self.assertIn("polo", self.asset.tokens)

    def test_dict_format_stores_persons_topics_clip_type(self):
        self.index.apply_tags({"comp_0001.mp4": {
            "persons": ["Meghan Markle"],
            "topics": ["surrogacy case"],
            "clip_type": "interview",
        }})
        self.assertEqual(self.asset.persons, {"meghan markle"})
        self.assertEqual(self.asset.topics, {"surrogacy case"})
        self.assertEqual(self.asset.clip_type, "interview")
        # person/topic words also join the token set for IDF scoring
        self.assertIn("meghan", self.asset.tokens)
        self.assertIn("surrogacy", self.asset.tokens)

    def test_dict_persons_accepts_single_string_and_normalises(self):
        self.index.apply_tags({"comp_0001.mp4": {"persons": "Meghan_Markle"}})
        self.assertEqual(self.asset.persons, {"meghan markle"})

    def test_dict_empty_and_unknown_keys_are_ignored(self):
        n = self.index.apply_tags({"comp_0001.mp4": {"persons": [],
                                                     "bogus_key": "x"}})
        self.assertEqual(n, 0)
        self.assertEqual(self.asset.persons, set())
        self.assertIsNone(self.asset.clip_type)

    def test_dict_unknown_clip_type_becomes_other(self):
        self.index.apply_tags({"comp_0001.mp4": {"clip_type": "documentary"}})
        self.assertEqual(self.asset.clip_type, "other")

    def test_mixed_formats_in_one_file(self):
        n = self.index.apply_tags({
            "comp_0001.mp4": {"persons": ["prince harry"]},
            "missing.mp4": ["ignored, no such asset"],
        })
        self.assertEqual(n, 1)
        self.assertEqual(self.asset.persons, {"prince harry"})

    def test_load_tags_reads_mixed_json_file(self):
        path = os.path.join(self.tmp.name, "tags.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"tags": {
                "a.mp4": ["wedding"],
                "b.mp4": {"persons": ["meghan markle"],
                          "topics": ["custody"],
                          "clip_type": "paparazzi"},
            }}, f)
        tags = load_tags(path)
        self.assertEqual(tags["a.mp4"], ["wedding"])
        self.assertEqual(tags["b.mp4"]["persons"], ["meghan markle"])
        self.assertEqual(tags["b.mp4"]["clip_type"], "paparazzi")

    def test_load_tags_missing_file_returns_empty(self):
        self.assertEqual(load_tags("/no/such/file.json"), {})

    def test_norm_person(self):
        self.assertEqual(norm_person("Meghan_Markle"), "meghan markle")
        self.assertEqual(norm_person("  Prince   Harry "), "prince harry")


class TestPersonBoostedPick(unittest.TestCase):
    """Tier 0: a clip tagged with the named person beats generic pool clips."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.index = _clip_index(
            self.tmp.name,
            ["alpha.mp4", "beta.mp4", "meghan_one.mp4", "harry_one.mp4"])
        self.index.apply_tags({
            "meghan_one.mp4": {"persons": ["Meghan Markle"],
                               "clip_type": "interview"},
            "harry_one.mp4": {"persons": ["prince harry"],
                              "topics": ["polo match"]},
        })

    def test_person_tagged_clip_preferred_over_generic(self):
        m = _matcher(self.index,
                     "Meghan Markle gave an interview about her new brand.")
        self.assertEqual(_picked_basename(m), "meghan_one.mp4")

    def test_correct_person_picked_when_two_are_tagged(self):
        m = _matcher(self.index,
                     "Prince Harry played polo at the charity match.")
        picked = _picked_basename(m)
        self.assertEqual(picked, "harry_one.mp4")

    def test_no_person_named_prefers_default_entity_pool(self):
        # No names in narration: old behaviour (default-entity pool) holds.
        m = _matcher(self.index, "The palace released a statement today.")
        picked = _picked_basename(m)
        self.assertIn(picked, {"alpha.mp4", "beta.mp4",
                               "meghan_one.mp4", "harry_one.mp4"})

    def test_fallback_to_generic_when_nothing_is_tagged(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        index = _clip_index(tmp.name, ["alpha.mp4", "beta.mp4"])  # no tags
        m = _matcher(index, "Meghan Markle arrived at the evening gala.")
        picked = _picked_basename(m)
        self.assertIn(picked, {"alpha.mp4", "beta.mp4"})

    def test_fallback_to_generic_when_person_clip_already_used(self):
        m = _matcher(self.index,
                     "Meghan Markle gave an interview about her new brand.")
        first = _picked_basename(m, position=0)
        self.assertEqual(first, "meghan_one.mp4")
        # The person-tagged clip is now consumed; the next slot naming the
        # same person must fall back to a non-person-matched clip, not None.
        # harry_one is fair game here: its persons tag names someone else,
        # so for this segment it is just another generic pool clip.
        second = _picked_basename(m, position=1)
        self.assertIn(second, {"alpha.mp4", "beta.mp4", "harry_one.mp4"})

    def test_coverage_counts_person_tag_pick_as_correct(self):
        m = _matcher(self.index,
                     "Meghan Markle gave an interview about her new brand.")
        _picked_basename(m, position=0)
        cov = m.coverage()
        self.assertEqual(cov["named_correct"], 1)
        self.assertEqual(cov["wrong_person_shown"], 0)

    def test_pick_signature_stable(self):
        m = _matcher(self.index, "Meghan Markle waved to the crowd.")
        asset, score, entities = m.pick(0.0, 6.0, "clip", 0)
        self.assertIsNotNone(asset)
        self.assertIsInstance(score, float)
        self.assertIsInstance(entities, dict)


class TestClipTagSeeder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.entity_root = os.path.join(self.tmp.name, "images")
        self.clips_dir = os.path.join(self.tmp.name, "clips")
        os.makedirs(os.path.join(self.entity_root, "meghan markle"))
        os.makedirs(os.path.join(self.entity_root, "prince harry"))
        os.makedirs(os.path.join(self.clips_dir, "meghan markle"))
        _touch(self.clips_dir,
               "meghan_markle_interview_01.mp4",
               "comp_0001.mp4",
               "prince-harry-paparazzi-night.mp4")
        _touch(os.path.join(self.clips_dir, "meghan markle"), "comp_0007.mp4")

    def test_known_persons_come_from_entity_folders(self):
        persons = known_persons_from_entity_root(self.entity_root)
        self.assertEqual(persons, ["meghan markle", "prince harry"])

    def test_seed_persons_from_filename_and_folder(self):
        tags, collisions = seed_clip_tags([self.clips_dir],
                                          ["meghan markle", "prince harry"])
        self.assertEqual(collisions, 0)
        self.assertEqual(tags["meghan_markle_interview_01.mp4"]["persons"],
                         ["meghan markle"])
        self.assertEqual(tags["meghan_markle_interview_01.mp4"]["clip_type"],
                         "interview")
        self.assertEqual(tags["prince-harry-paparazzi-night.mp4"]["persons"],
                         ["prince harry"])
        self.assertEqual(tags["prince-harry-paparazzi-night.mp4"]["clip_type"],
                         "paparazzi")
        # folder path names the person even when the filename does not
        self.assertEqual(tags["comp_0007.mp4"]["persons"], ["meghan markle"])
        # opaque filename: nothing invented, left for hand-tagging
        self.assertEqual(tags["comp_0001.mp4"]["persons"], [])
        self.assertEqual(tags["comp_0001.mp4"]["topics"], [])
        self.assertEqual(tags["comp_0001.mp4"]["clip_type"], "other")

    def test_detect_clip_type(self):
        self.assertEqual(detect_clip_type(["red", "carpet", "arrival"]),
                         "redcarpet")
        self.assertEqual(detect_clip_type(["talk", "show", "guest"]),
                         "talkshow")
        self.assertEqual(detect_clip_type(["engagement", "ring"]), "engagement")
        self.assertEqual(detect_clip_type(["comp"]), "other")


if __name__ == "__main__":
    unittest.main()
