"""Tests for RULE 49 - extraction-time auto-tagging.

After each competitor clip is sliced, the pipeline samples 7 representative
frames and upserts a skeleton entry in <clips_dir>/clip_tags_new.json
(persons pre-seeded from default_entity, confidence "unverified").
Tagging failures must never break clip writing.

Stdlib unittest only - pytest is not installed on this box.
ffmpeg and scenedetect are both mocked, so no real media is needed.
Run:  cd pipeline && ~/workspace/royal/venv/bin/python -m unittest tests.test_extraction_tags -v
"""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fresh_assets
from fresh_assets import (FRAME_FRACTIONS, FRAME_NAMES, NEW_TAGS_MANIFEST,
                          slice_competitor_clips, tag_extracted_clip)


class _FakeTime:
    def __init__(self, seconds):
        self._s = seconds

    def get_seconds(self):
        return self._s


class _FakeSceneManager:
    # Set per-test: list of (start_s, end_s) shot boundaries.
    scenes = []

    def add_detector(self, detector):
        pass

    def detect_scenes(self, video, show_progress=False):
        pass

    def get_scene_list(self):
        return [(_FakeTime(a), _FakeTime(b)) for a, b in self.scenes]


def _install_fake_scenedetect():
    scenedetect = types.ModuleType("scenedetect")
    scenedetect.open_video = lambda path: object()
    scenedetect.SceneManager = _FakeSceneManager
    detectors = types.ModuleType("scenedetect.detectors")
    detectors.ContentDetector = lambda **kw: object()
    sys.modules["scenedetect"] = scenedetect
    sys.modules["scenedetect.detectors"] = detectors


class _Call:
    """Record of one mocked subprocess.run invocation."""
    def __init__(self, cmd):
        self.cmd = cmd

    @property
    def out_path(self):
        return self.cmd[-1]


class _Completed:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


class FakeRunner:
    """Mock for fresh_assets.subprocess.run.

    write_fail_for / frame_fail_for: sets of clip basenames whose clip-write
    or frame-sampling calls should fail. All other calls create their output
    file (21000 bytes for clips so the >20000 size gate passes).
    """
    def __init__(self):
        self.calls = []
        self.write_fail_for = set()
        self.frame_fail_for = set()

    def __call__(self, cmd, **kwargs):
        call = _Call(cmd)
        self.calls.append(call)
        is_frame = "-frames:v" in cmd
        if is_frame:
            clip_name = os.path.basename(cmd[cmd.index("-i") + 1])
        else:
            clip_name = os.path.basename(call.out_path)
        out = Path(call.out_path)
        if is_frame and clip_name in self.frame_fail_for:
            return _Completed(returncode=1)
        if not is_frame and clip_name in self.write_fail_for:
            return _Completed(returncode=1)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\0" * 21000)
        return _Completed(returncode=0)

    def frame_calls(self):
        return [c for c in self.calls if "-frames:v" in c.cmd]

    def ss_values(self):
        return [float(c.cmd[c.cmd.index("-ss") + 1])
                for c in self.frame_calls()]


class TestExtractionTagging(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clips_dir = Path(self.tmp.name) / "clips"
        self.video = Path(self.tmp.name) / "competitor.mp4"
        self.video.write_bytes(b"\0" * 100)

        _install_fake_scenedetect()
        self.addCleanup(lambda: sys.modules.pop("scenedetect", None))
        self.addCleanup(lambda: sys.modules.pop("scenedetect.detectors", None))
        # Each scene is 5 s: sliced clip is (s=0.15, e=4.85) -> dur 4.7 s.
        _FakeSceneManager.scenes = [(0.0, 5.0), (5.0, 10.0), (10.0, 15.0)]

        self.runner = FakeRunner()
        self.patcher = mock.patch.object(fresh_assets.subprocess, "run",
                                         self.runner)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _run(self, **kwargs):
        return slice_competitor_clips(self.video, self.clips_dir, **kwargs)

    def _manifest(self):
        return json.loads((self.clips_dir / NEW_TAGS_MANIFEST)
                          .read_text(encoding="utf-8"))

    def test_frames_sampled_per_written_clip(self):
        written = self._run(default_entity="Meghan_Markle")
        self.assertEqual(written, 3)
        frames = self.runner.frame_calls()
        # 7 frames per clip, 3 clips.
        self.assertEqual(len(frames), 21)
        per_clip = [self.runner.ss_values()[i * 7:(i + 1) * 7]
                    for i in range(3)]
        for ss in per_clip:
            expected = [round(f * 4.7, 3) for f in FRAME_FRACTIONS]
            self.assertEqual([round(v, 3) for v in ss], expected)

    def test_frame_files_and_dirs_named_per_spec(self):
        self._run(default_entity="meghan markle")
        entries = self._manifest()
        for name, entry in entries.items():
            frames_root = self.clips_dir / entry["frames_dir"]
            self.assertEqual(frames_root.name.split("_")[0], "clip")
            self.assertTrue((self.clips_dir / "frames" / entry["src"]
                             / frames_root.name).is_dir())
            got = sorted(p.name for p in frames_root.iterdir())
            self.assertEqual(got, sorted(FRAME_NAMES))

    def test_manifest_upsert_persons_clip_type_confidence(self):
        self._run(default_entity="Meghan_Markle")
        data = self._manifest()
        self.assertEqual(set(data),
                         {"comp_0000.mp4", "comp_0001.mp4", "comp_0002.mp4"})
        for name, entry in data.items():
            self.assertEqual(entry["persons"], ["meghan markle"])
            self.assertEqual(entry["topics"], [])
            self.assertEqual(entry["clip_type"], "other")
            self.assertEqual(entry["confidence"], "unverified")
            self.assertTrue(entry["src"].startswith("src_"))
            self.assertEqual(len(entry["src"]), 4 + 16)
            self.assertEqual(entry["frames_dir"],
                             f"frames/{entry['src']}/{entry['frames_dir'].split('/')[-1]}")

    def test_no_default_entity_means_empty_persons(self):
        self._run()
        for entry in self._manifest().values():
            self.assertEqual(entry["persons"], [])

    def test_manifest_upsert_is_incremental(self):
        # Pre-existing entries are kept and stale ones refreshed.
        manifest = self.clips_dir / NEW_TAGS_MANIFEST
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({
            "comp_0000.mp4": {"src": "src_old", "frames_dir": "frames/old/x",
                              "persons": ["prince harry"], "topics": [],
                              "clip_type": "other",
                              "confidence": "unverified"},
            "hand_tagged.mp4": {"persons": ["king charles"]},
        }), encoding="utf-8")
        self._run(default_entity="meghan markle")
        data = self._manifest()
        # Stale comp_0000 entry refreshed with new persons + real frame dir.
        self.assertEqual(data["comp_0000.mp4"]["persons"], ["meghan markle"])
        self.assertNotEqual(data["comp_0000.mp4"]["frames_dir"],
                            "frames/old/x")
        # Unrelated entries survive.
        self.assertEqual(data["hand_tagged.mp4"]["persons"],
                         ["king charles"])
        self.assertEqual(set(data),
                         {"comp_0000.mp4", "comp_0001.mp4", "comp_0002.mp4",
                          "hand_tagged.mp4"})

    def test_clip_write_failure_does_not_break_loop(self):
        self.runner.write_fail_for = {"comp_0001.mp4"}
        written = self._run(default_entity="meghan markle")
        self.assertEqual(written, 2)
        data = self._manifest()
        self.assertIn("comp_0000.mp4", data)
        self.assertIn("comp_0002.mp4", data)
        self.assertNotIn("comp_0001.mp4", data)
        # No frames sampled for the failed clip.
        self.assertEqual(len(self.runner.frame_calls()), 14)

    def test_frame_sampling_failure_does_not_break_loop(self):
        self.runner.frame_fail_for = {"comp_0001.mp4"}
        written = self._run(default_entity="meghan markle")
        self.assertEqual(written, 3)
        # Frames for the other two clips still sampled.
        self.assertEqual(len(self.runner.frame_calls()), 21)
        # Manifest is still upserted for the failed clip.
        data = self._manifest()
        self.assertEqual(data["comp_0001.mp4"]["confidence"], "unverified")
        self.assertEqual(data["comp_0001.mp4"]["persons"], ["meghan markle"])

    def test_tag_extracted_clip_never_raises_on_frame_failure(self):
        # Frames fail AND manifest dir is unusable -> still no exception.
        self.runner.frame_fail_for = {"comp_0001.mp4"}
        clip = self.clips_dir / "comp_0001.mp4"
        clip.parent.mkdir(parents=True, exist_ok=True)
        clip.write_bytes(b"\0" * 21000)
        tag_extracted_clip(self.video, self.clips_dir, clip, 4.7,
                           "Meghan_Markle")  # must not raise
        data = self._manifest()
        self.assertEqual(data["comp_0001.mp4"]["persons"],
                         ["meghan markle"])

    def test_signature_is_backwards_compatible(self):
        # Old call style (no new kwargs) still works.
        import inspect
        sig = inspect.signature(slice_competitor_clips)
        self.assertIn("default_entity", sig.parameters)
        self.assertIsNone(sig.parameters["default_entity"].default)
        written = slice_competitor_clips(self.video, self.clips_dir)
        self.assertEqual(written, 3)


if __name__ == "__main__":
    unittest.main()
