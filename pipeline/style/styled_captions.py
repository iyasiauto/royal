"""Style constants for the Royal pipeline's word-level styled captions.

Workstream C of the editing-style upgrade (supersedes PIPELINE_RULES.md
RULE 8 "No Burned-In Captions"): reference look is the competitor
"Palace Insider" caption style — white BOLD SERIF text, 1-3 words at a
time, bottom-center, on a semi-transparent dark rounded pill, word-timed
to the narration.

ASS has no true rounded-rectangle primitive, so the pill is approximated:
BorderStyle=4 (opaque box drawn only behind the text) + semi-transparent
black BackColour + a soft shadow. On render this reads as a dark pill.

All sizes are relative to the 1080p play resolution (PlayResX/Y below);
libass scales them automatically when burning onto other frame sizes.
"""

# ---------------------------------------------------------------- font
FONT_NAME = "DejaVu Serif"          # fontconfig family; bold via CAPTION_STYLE Bold=1
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
FONT_SIZE = 64                      # px at 1080p

# --------------------------------------------------------------- colors
# ASS colours are &HAABBGGRR (AA = alpha, 00 = opaque, FF = transparent)
PRIMARY_COLOUR = "&H00FFFFFF"       # white text
SECONDARY_COLOUR = "&H000019FF"     # karaoke secondary (unused)
OUTLINE_COLOUR = "&H00000000"       # black outline
BACK_COLOUR = "&H80000000"          # semi-transparent black pill background (~50%)

# ------------------------------------------------------------------- box
BORDER_STYLE = 4                    # opaque box (per-text-line background = pill feel)
OUTLINE = 3                         # outline thickness px
SHADOW = 1                          # soft drop shadow px

# ----------------------------------------------------------------- layout
ALIGNMENT = 2                       # bottom-center
MARGIN_L = 100
MARGIN_R = 100
MARGIN_V = 70                       # distance from bottom edge at 1080p

# --------------------------------------------------------------- grouping
MAX_WORDS_PER_EVENT = 3             # never more than 3 words per caption
MAX_EVENT_DURATION_S = 1.2          # aim each caption <= ~1.2s

# ------------------------------------------------------------- resolution
PLAY_RES_X = 1920
PLAY_RES_Y = 1080

# ---------------------------------------------------------- ASS style row
# Field order follows the [V4+ Styles] Format line exactly.
CAPTION_STYLE = {
    "Name": "Caption",
    "Fontname": FONT_NAME,
    "Fontsize": FONT_SIZE,
    "PrimaryColour": PRIMARY_COLOUR,
    "SecondaryColour": SECONDARY_COLOUR,
    "OutlineColour": OUTLINE_COLOUR,
    "BackColour": BACK_COLOUR,
    "Bold": 1,
    "Italic": 0,
    "Underline": 0,
    "StrikeOut": 0,
    "ScaleX": 100,
    "ScaleY": 100,
    "Spacing": 0.5,
    "Angle": 0,
    "BorderStyle": BORDER_STYLE,
    "Outline": OUTLINE,
    "Shadow": SHADOW,
    "Alignment": ALIGNMENT,
    "MarginL": MARGIN_L,
    "MarginR": MARGIN_R,
    "MarginV": MARGIN_V,
    "Encoding": 1,
}

STYLE_FIELD_ORDER = [
    "Name", "Fontname", "Fontsize", "PrimaryColour", "SecondaryColour",
    "OutlineColour", "BackColour", "Bold", "Italic", "Underline",
    "StrikeOut", "ScaleX", "ScaleY", "Spacing", "Angle", "BorderStyle",
    "Outline", "Shadow", "Alignment", "MarginL", "MarginR", "MarginV",
    "Encoding",
]
