"""Style layer: reusable visual treatments for Royal renders.

Workstream modules (each self-contained; the coordinator wires them into
render_engine.py):

- commentator_panel  (workstream A/B): styled commentator panel segments
- styled_captions    (workstream C): karaoke/pill caption styling
- signature_grade    (workstream D): subtle RGB-split + grain signature grade
- watermark          (workstream E): circular channel badge burned top-right
"""

from style.commentator_panel import (  # noqa: F401
    build_panel_filter,
    detect_fg_kind,
    make_panel_background,
    render_panel_segment,
)
from style.styled_captions import CAPTION_STYLE  # noqa: F401
from style.signature_grade import grade_filter, preview  # noqa: F401
from style.watermark import make_badge, watermark_filter  # noqa: F401

__all__ = [
    "build_panel_filter",
    "detect_fg_kind",
    "make_panel_background",
    "render_panel_segment",
    "CAPTION_STYLE",
    "grade_filter",
    "preview",
    "make_badge",
    "watermark_filter",
]
