"""Word-level styled caption formatter for the Royal pipeline.

Converts the pipeline's word-level SRT (one entry per spoken word, produced
alongside the voiceover) into a styled ASS file used for burn-in.

Caption look (workstream C of the editing-style upgrade, superseding
PIPELINE_RULES.md RULE 8 "No Burned-In Captions"): white BOLD SERIF text,
1-3 words per caption event, bottom-center, on a semi-transparent dark
rounded pill, word-timed to the narration.

ASS has no true rounded-rectangle primitive, so the pill is approximated
with BorderStyle=4 (opaque box drawn only behind the text) plus a
semi-transparent black BackColour and a soft shadow. On render this reads
as a dark pill behind each caption line.

The standalone word-level SRT (voiceover.srt) is untouched by this module;
it only derives the burn-in ASS from it. Signature of convert_srt_to_ass
is stable: the renderer calls convert_srt_to_ass(srt_path, ass_output_path).
"""
import importlib.util
import os
import re
from pathlib import Path


def _load_style_module():
    """Load pipeline/style/styled_captions.py by file path.

    Deliberately bypasses ``import style...``: the ``style`` package's
    ``__init__`` pulls in signature_grade/watermark with package-mode
    imports, which fails when this module is imported bare with only the
    pipeline dir on sys.path (unit tests, CLI use). Loading by file path
    works identically in every run mode.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "style", "styled_captions.py")
    spec = importlib.util.spec_from_file_location("royal_styled_captions", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


styled_captions = _load_style_module()
CAPTION_STYLE = styled_captions.CAPTION_STYLE
STYLE_FIELD_ORDER = styled_captions.STYLE_FIELD_ORDER
MAX_WORDS_PER_EVENT = styled_captions.MAX_WORDS_PER_EVENT
MAX_EVENT_DURATION_S = styled_captions.MAX_EVENT_DURATION_S
PLAY_RES_X = styled_captions.PLAY_RES_X
PLAY_RES_Y = styled_captions.PLAY_RES_Y


def srt_timestamp_to_ass(ts_str):
    """Converts SRT timestamp '00:00:04,500' to ASS format '0:00:04.50'"""
    ts_str = ts_str.strip().replace(',', '.')
    parts = ts_str.split(':')
    if len(parts) == 3:
        h = int(parts[0])
        m = parts[1]
        s_parts = parts[2].split('.')
        s = s_parts[0]
        ms = s_parts[1][:2] if len(s_parts) > 1 else "00"
        return f"{h}:{m}:{s}.{ms}"
    return ts_str


def srt_timestamp_to_seconds(ts_str):
    """Converts SRT timestamp '00:00:04,500' to float seconds (4.5)."""
    ts_str = ts_str.strip().replace(',', '.')
    h, m, rest = ts_str.split(':')
    s, _, ms = rest.partition('.')
    total = int(h) * 3600 + int(m) * 60 + int(s)
    if ms:
        total += int(ms) / (10 ** len(ms))
    return total


def raw_seconds_to_ass(sec):
    """Converts seconds float (e.g. 4.5) to ASS format '0:00:04.50'"""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    if cs >= 100:
        s += 1
        cs = 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def highlight_keywords(text):
    """Highlights key dramatic keywords in yellow for YouTube retention style.

    Kept for backward compatibility; the word-level caption style (workstream C)
    intentionally renders plain white text, so convert_srt_to_ass no longer
    applies this.
    """
    keywords = [
        "King Charles", "Prince William", "Camilla", "Princess Diana", "Queen",
        "Clarence House", "Highgrove", "Ray Mill House", "Balmoral", "Buckingham",
        "Windsor", "dispatch box", "vellum", "oxblood folder", "Devizes",
        "document", "secret", "settlement", "annexure", "signature", "signed",
        "silence", "truth", "revelation", "ultimatum", "Crown", "royal"
    ]
    for kw in keywords:
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        text = pattern.sub(lambda m: f"{{\\c&H0000FFFF&}}{m.group(0)}{{\\c&H00FFFFFF&}}", text)
    return text


def parse_srt(srt_path):
    """Parses SRT file into a list of subtitle entries.

    Each entry: {'start', 'end' (ASS-format strings), 'start_s', 'end_s'
    (float seconds), 'text'}.
    """
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read()

    blocks = re.split(r'\n\s*\n', content.strip())
    entries = []
    for block in blocks:
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if len(lines) >= 3:
            time_line = lines[1]
            if '-->' in time_line:
                start_str, end_str = time_line.split('-->')
                text = " ".join(lines[2:])
                if not text:
                    continue
                entries.append({
                    'start': srt_timestamp_to_ass(start_str),
                    'end': srt_timestamp_to_ass(end_str),
                    'start_s': srt_timestamp_to_seconds(start_str),
                    'end_s': srt_timestamp_to_seconds(end_str),
                    'text': text,
                })
    return entries


def group_words(entries, max_words=MAX_WORDS_PER_EVENT,
                max_duration_s=MAX_EVENT_DURATION_S):
    """Groups consecutive word entries into caption events.

    Greedy: keep appending words while the group stays within max_words and
    the span from the first word's start to the candidate word's end stays
    within max_duration_s. Caption timing spans first word start -> last
    word end, so events are exactly word-timed to the narration.
    """
    groups = []
    current = []
    for entry in entries:
        if current and (len(current) >= max_words
                        or (entry['end_s'] - current[0]['start_s']) > max_duration_s):
            groups.append(current)
            current = []
        current.append(entry)
    if current:
        groups.append(current)
    return groups


def convert_srt_to_ass(srt_path, ass_output_path):
    """Generates word-level styled ASS captions from a word-level SRT.

    Signature is stable: called by the renderer as
    convert_srt_to_ass(srt_path, ass_output_path). The source SRT
    (voiceover.srt) is only read, never modified.
    """
    entries = parse_srt(srt_path)
    groups = group_words(entries)

    style_line = "Style: " + ",".join(
        str(CAPTION_STYLE[field]) for field in STYLE_FIELD_ORDER)

    ass_header = f"""[Script Info]
Title: Royal Documentary Word Captions
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: None
PlayResX: {PLAY_RES_X}
PlayResY: {PLAY_RES_Y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style_line}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dialogues = []
    for group in groups:
        start = raw_seconds_to_ass(group[0]['start_s'])
        end = raw_seconds_to_ass(group[-1]['end_s'])
        text = " ".join(entry['text'] for entry in group).strip()
        dialogues.append(
            f"Dialogue: 0,{start},{end},Caption,,0,0,0,,{text}")

    with open(ass_output_path, 'w', encoding='utf-8') as f:
        f.write(ass_header + "\n".join(dialogues))

    print(f"[+] Successfully created styled ASS subtitles: {ass_output_path} "
          f"({len(dialogues)} caption events from {len(entries)} words)")
    return ass_output_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        srt_file = sys.argv[1]
        ass_file = Path(srt_file).with_suffix('.ass')
        convert_srt_to_ass(srt_file, ass_file)
