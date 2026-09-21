"""Unit tests for the word-level styled captions (workstream C).

stdlib unittest only. Run from the pipeline dir:
    python -m unittest discover -s tests -v
"""
import inspect
import os
import re
import sys
import tempfile
import unittest

PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PIPELINE_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_DIR)

import subtitle_formatter as sf

FULL_SRT = os.path.expanduser(
    "~/workspace/royal/videos/video19/temp_render_workspace/voiceover.srt")


def make_word_srt(path, words):
    """Write a synthetic word-level SRT. words = [(start_s, end_s, text), ...]."""
    def ts(sec):
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int(round((sec - int(sec)) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    with open(path, "w", encoding="utf-8") as f:
        for i, (a, b, w) in enumerate(words, 1):
            f.write(f"{i}\n{ts(a)} --> {ts(b)}\n{w}\n\n")


def parse_dialogues(ass_text):
    """Return list of (start, end, text) for Dialogue lines."""
    out = []
    for line in ass_text.splitlines():
        if line.startswith("Dialogue:"):
            parts = line.split(",", 9)
            out.append((parts[1], parts[2], parts[9]))
    return out


def get_style_fields(ass_text):
    for line in ass_text.splitlines():
        if line.startswith("Style: Caption,"):
            return line.split("Style: ", 1)[1].split(",")
    return None


class TestWordGrouping(unittest.TestCase):
    def test_never_exceeds_three_words(self):
        # 10 evenly spaced words; greedy grouping must cap at 3 per event.
        words = [(i * 0.3, i * 0.3 + 0.25, f"word{i}") for i in range(10)]
        with tempfile.TemporaryDirectory() as tmp:
            srt = os.path.join(tmp, "w.srt")
            ass = os.path.join(tmp, "w.ass")
            make_word_srt(srt, words)
            sf.convert_srt_to_ass(srt, ass)
            with open(ass, encoding="utf-8") as f:
                dialogues = parse_dialogues(f.read())
        for _, _, text in dialogues:
            self.assertLessEqual(len(text.split()), 3,
                                 f"event exceeded 3 words: {text!r}")
        self.assertEqual([len(t.split()) for _, _, t in dialogues],
                         [3, 3, 3, 1])

    def test_long_gaps_split_events(self):
        # Words far apart must not be merged even if <= 3 words.
        words = [(0.0, 0.4, "alpha"), (2.0, 2.4, "beta"), (4.0, 4.4, "gamma")]
        with tempfile.TemporaryDirectory() as tmp:
            srt = os.path.join(tmp, "w.srt")
            ass = os.path.join(tmp, "w.ass")
            make_word_srt(srt, words)
            sf.convert_srt_to_ass(srt, ass)
            with open(ass, encoding="utf-8") as f:
                dialogues = parse_dialogues(f.read())
        self.assertEqual(len(dialogues), 3)
        self.assertEqual([t for _, _, t in dialogues],
                         ["alpha", "beta", "gamma"])


class TestCaptionTiming(unittest.TestCase):
    def test_start_end_match_word_timestamps(self):
        words = [(0.5, 0.75, "one"), (0.8, 1.05, "two"), (1.1, 1.4, "three"),
                 (3.0, 3.3, "four")]
        with tempfile.TemporaryDirectory() as tmp:
            srt = os.path.join(tmp, "w.srt")
            ass = os.path.join(tmp, "w.ass")
            make_word_srt(srt, words)
            sf.convert_srt_to_ass(srt, ass)
            with open(ass, encoding="utf-8") as f:
                dialogues = parse_dialogues(f.read())
            entries = sf.parse_srt(srt)
            groups = sf.group_words(entries)
        self.assertEqual(len(dialogues), len(groups))
        for (start, end, _), group in zip(dialogues, groups):
            self.assertEqual(start, sf.raw_seconds_to_ass(group[0]["start_s"]))
            self.assertEqual(end, sf.raw_seconds_to_ass(group[-1]["end_s"]))
        # first event: "one two three" spans 0.5 -> 1.4
        self.assertEqual(dialogues[0][0], "0:00:00.50")
        self.assertEqual(dialogues[0][1], "0:00:01.40")
        self.assertEqual(dialogues[0][2], "one two three")
        # every event has positive duration
        for start, end, _ in dialogues:
            self.assertLess(start, end)


class TestCaptionStyle(unittest.TestCase):
    def test_ass_contains_reference_style_line(self):
        words = [(0.0, 0.3, "hello"), (0.35, 0.6, "world")]
        with tempfile.TemporaryDirectory() as tmp:
            srt = os.path.join(tmp, "w.srt")
            ass = os.path.join(tmp, "w.ass")
            make_word_srt(srt, words)
            sf.convert_srt_to_ass(srt, ass)
            with open(ass, encoding="utf-8") as f:
                text = f.read()
        fields = get_style_fields(text)
        self.assertIsNotNone(fields, "no 'Style: Caption,...' line found")
        # Field order per [V4+ Styles] Format line:
        # Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,
        # OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,
        # ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,
        # Alignment, MarginL, MarginR, MarginV, Encoding
        self.assertEqual(fields[0], "Caption")
        self.assertEqual(fields[1], "DejaVu Serif")   # bold serif font
        self.assertEqual(fields[7], "1")              # Bold
        self.assertEqual(fields[15], "4")             # BorderStyle=4 pill box
        self.assertEqual(fields[18], "2")             # bottom-center alignment
        self.assertTrue(fields[6].upper().startswith("&H8"),
                        f"BackColour not semi-transparent: {fields[6]}")
        # dialogues actually use the Caption style
        for line in text.splitlines():
            if line.startswith("Dialogue:"):
                self.assertIn(",Caption,", line)

    def test_style_constants_exposed(self):
        self.assertEqual(sf.MAX_WORDS_PER_EVENT, 3)
        self.assertAlmostEqual(sf.MAX_EVENT_DURATION_S, 1.2)
        self.assertEqual(sf.CAPTION_STYLE["Fontname"], "DejaVu Serif")


class TestSignatureStability(unittest.TestCase):
    def test_convert_signature_unchanged(self):
        params = list(inspect.signature(sf.convert_srt_to_ass).parameters)
        self.assertEqual(params, ["srt_path", "ass_output_path"])


class TestFullVoiceover(unittest.TestCase):
    def test_full_srt_converts_without_error(self):
        if not os.path.exists(FULL_SRT):
            self.skipTest(f"sample SRT not found: {FULL_SRT}")
        entries = sf.parse_srt(FULL_SRT)
        self.assertGreater(len(entries), 5000)  # word-level: ~5074 words
        with tempfile.TemporaryDirectory() as tmp:
            ass = os.path.join(tmp, "voiceover.ass")
            sf.convert_srt_to_ass(FULL_SRT, ass)
            with open(ass, encoding="utf-8") as f:
                text = f.read()
        dialogues = parse_dialogues(text)
        # sane event count: grouped 1-3 words per event
        self.assertGreaterEqual(len(dialogues), len(entries) // 3 - 50)
        self.assertLessEqual(len(dialogues), len(entries))
        for _, _, t in dialogues:
            self.assertLessEqual(len(t.split()), 3,
                                 f"event exceeded 3 words: {t!r}")


if __name__ == "__main__":
    unittest.main()
