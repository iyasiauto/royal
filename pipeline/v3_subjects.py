"""V3 Semantic Visual Index -> pipeline clip-tag normalization.

The V3 corpus (footage-index3.db, VIEW usable_clips) is the approved tagging
source for bulk video corpora. This module holds the subject/topic/shot-type
normalization so future corpora reuse the exact same rules (RULE 49).

Rules (2026-09-21, see CLIP_TAGGING.md "V3 ingestion"):
- persons = normalized union of primary_subject + visible_subjects
- canonical name map applied first (king charles iii -> king charles, ...)
- leading "uncertain:" / "uncertain" stripped
- combos split on " and ", ",", "&"
- non-person tokens dropped (unknown person, crowd, carriage, animals, ...)
- named non-core people kept lowercased, never invented
- empty result stays empty (honest unknown)
"""

from __future__ import annotations

import json
import re

CANONICAL = {
    "king charles iii": "king charles",
    "queen camilla": "queen camilla",
    "prince william": "prince william",
    "princess catherine": "princess catherine",
    "prince george": "prince george",
    "princess charlotte": "princess charlotte",
    "prince louis": "prince louis",
    "prince harry": "prince harry",
    "meghan markle": "meghan markle",
    "princess anne": "princess anne",
    "queen elizabeth ii": "queen elizabeth ii",
    "princess diana": "princess diana",
    "prince philip": "prince philip",
    "sophie, duchess of edinburgh": "sophie, duchess of edinburgh",
    "sophie duchess of edinburgh": "sophie, duchess of edinburgh",
    "princess sophie duchess of edinburgh": "sophie, duchess of edinburgh",
    "prince edward, duke of edinburgh": "prince edward",
    "prince edward duke of edinburgh": "prince edward",
}

# Tokens that are never persons. Compared lowercased, exact match after
# canonicalisation; prefixes "unknown"/"unidentified" also drop.
DROP_EXACT = {
    "unknown", "none", "uncertain", "crowd", "a crowd of spectators",
    "unknown person", "unknown woman", "unknown child", "unknown people",
    "unknown group of young adults", "group of photographers",
    "multiple subjects", "multiple royal subjects",
    "multiple royal family members", "royal family", "royal family group",
    "group of four individuals", "royal carriage with outriders",
    "royal carriage escort", "royal coachmen and outriders",
    "royal coachman", "horse", "lego figures", "police officer",
    "prince", "clergy", "military personnel", "pages of honour",
    "photographers", "dogs", "paddington bear", "santa claus",
}

DROP_PREFIXES = ("unknown", "unidentified")

SPLIT_RE = re.compile(r"\s*(?:\band\b|&|,)\s*", re.IGNORECASE)
UNCERTAIN_RE = re.compile(r"^\s*uncertain\s*:?\s*", re.IGNORECASE)


def _clean_token(raw: str) -> str:
    t = UNCERTAIN_RE.sub("", raw or "").strip().lower()
    return re.sub(r"\s+", " ", t)


def _emit_token(t: str, persons: list, seen: set) -> None:
    if not t or t in DROP_EXACT or t.startswith(DROP_PREFIXES):
        return
    t = CANONICAL.get(t, t)
    if not t or t in DROP_EXACT or t.startswith(DROP_PREFIXES):
        return
    if t not in seen:
        seen.add(t)
        persons.append(t)


def normalize_subjects(primary_subject, visible_subjects) -> list:
    """Return the canonical persons list for one usable_clips row."""
    if isinstance(visible_subjects, str):
        try:
            vis = json.loads(visible_subjects)
        except (ValueError, TypeError):
            vis = [visible_subjects]
    elif visible_subjects:
        vis = list(visible_subjects)
    else:
        vis = []

    persons = []
    seen = set()
    for raw in [primary_subject] + vis:
        if not raw:
            continue
        # Whole-string first: keeps "Sophie, Duchess of Edinburgh" /
        # "Prince Edward, Duke of Edinburgh" intact for the canonical map
        # before comma-splitting can tear them apart.
        whole = _clean_token(re.sub(r"[()]", " ", str(raw)))
        if whole in CANONICAL or whole in DROP_EXACT:
            _emit_token(whole, persons, seen)
            continue
        for piece in SPLIT_RE.split(str(raw)):
            _emit_token(_clean_token(piece), persons, seen)
    return persons


def normalize_topics(event, location) -> list:
    """Topics = [event, location] lowercased; 'unknown'/empties dropped."""
    out = []
    for raw in (event, location):
        if not raw:
            continue
        t = re.sub(r"\s+", " ", str(raw).strip().lower())
        if t and t not in ("unknown", "n/a", "none"):
            out.append(t)
    return out


def normalize_shot_type(shot_type: str) -> str:
    """Shot framing -> clip_type token (matcher coerces unknowns to other)."""
    if not shot_type:
        return "other"
    t = re.sub(r"[\s\-]+", "_", str(shot_type).strip().lower())
    return t or "other"


def tag_entry(primary_subject, visible_subjects, event, location,
               shot_type) -> dict:
    """One clip_tags_v3.json entry from a usable_clips row."""
    return {
        "persons": normalize_subjects(primary_subject, visible_subjects),
        "topics": normalize_topics(event, location),
        "clip_type": normalize_shot_type(shot_type),
    }


def v3_basename(asset_id: str, clip_id: str) -> str:
    """v3_<asset8>_<clipid8>.mp4 key scheme."""
    asset8 = asset_id.split("_", 1)[1][:8]
    clip8 = clip_id.split("_", 1)[1][:8]
    return f"v3_{asset8}_{clip8}.mp4"
