import os
import re
import json
from pathlib import Path

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
    """Highlights key dramatic keywords in yellow for YouTube retention style."""
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
    """Parses SRT file into a list of subtitle entries (start, end, text)."""
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
                entries.append({
                    'start': srt_timestamp_to_ass(start_str),
                    'end': srt_timestamp_to_ass(end_str),
                    'text': text
                })
    return entries

def convert_srt_to_ass(srt_path, ass_output_path):
    """Generates styled ASS file from SRT file."""
    entries = parse_srt(srt_path)

    ass_header = """[Script Info]
Title: Royal Documentary Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: None
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,52,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3,2,2,100,100,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dialogues = []
    for entry in entries:
        styled_text = highlight_keywords(entry['text'])
        dialogues.append(f"Dialogue: 0,{entry['start']},{entry['end']},Default,,0,0,0,,{styled_text}")

    with open(ass_output_path, 'w', encoding='utf-8') as f:
        f.write(ass_header + "\n".join(dialogues))

    print(f"[+] Successfully created styled ASS subtitles: {ass_output_path}")
    return ass_output_path

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        srt_file = sys.argv[1]
        ass_file = Path(srt_file).with_suffix('.ass')
        convert_srt_to_ass(srt_file, ass_file)
