"""
Starter generator for CLIP tags JSON (person + topic tags for clips).

Pool clip filenames are usually opaque (comp_0001.mp4), so unlike images the
matcher cannot tell who is on screen from the filename. This script walks the
clip pools and writes one structured entry per clip, auto-seeding "persons"
and "clip_type" wherever the filename or folder path actually names a person
or scene type, and leaving everything else empty for hand-tagging:

    python make_clip_tags.py --clips-dir ~/workspace/royal/pool/clips \\
        --entity-root ~/workspace/royal/pool/images \\
        --out configs/clip_tags.json

Then hand-fill the empty "persons"/"topics" lists (watch each clip, or check
its source context) and pass the file back with --asset-tags alongside any
existing keyword tags file. Keys are bare filenames, so the file stays valid
if the pool moves.

Nothing is invented: a clip only gets a "persons" tag when its own filename
or folder path names that person. Everything else stays untagged for you.
"""

import os
import sys
import json
import argparse
import glob

from semantic_matcher import tokenize, folder_entity, VIDEO_EXTS, norm_person

# Filename tokens that pin down a clip type. Checked in this order so a file
# named "..._interview_paparazzi_..." is labelled interview (the stronger cue).
CLIP_TYPE_RULES = [
    ("interview", {"interview"}),
    ("paparazzi", {"paparazzi"}),
    ("redcarpet", {"redcarpet"}),
    ("redcarpet", {"red", "carpet"}),
    ("talkshow", {"talkshow"}),
    ("talkshow", {"talk", "show"}),
    ("engagement", {"engagement"}),
]


def known_persons_from_entity_root(entity_root):
    """Canonical person names from the image entity folders.

    The pool/images/<person> folders are the ground truth for who the
    channel covers - no invented names, nothing from outside the pool.
    """
    persons = []
    if entity_root and os.path.isdir(entity_root):
        for name in sorted(os.listdir(entity_root)):
            path = os.path.join(entity_root, name)
            if not os.path.isdir(path):
                continue
            p = norm_person(folder_entity(path) or name)
            if p and p not in persons:
                persons.append(p)
    return persons


def detect_clip_type(file_tokens):
    """Clip type from filename evidence, else "other" (left for hand-tagging)."""
    tokens = set(file_tokens)
    for clip_type, want in CLIP_TYPE_RULES:
        if want <= tokens:
            return clip_type
    return "other"


def seed_persons(clip_path, clips_dir, known_persons):
    """Person names the clip's own filename/folder path supports, else [].

    Matches when a known person's full name equals a path component, or when
    every word of the name appears among a component's filename tokens
    (e.g. "meghan_markle_interview_01.mp4" -> "meghan markle").
    """
    stem = os.path.splitext(os.path.basename(clip_path))[0]
    parts = [stem]
    try:
        rel = os.path.relpath(os.path.dirname(os.path.abspath(clip_path)),
                              os.path.abspath(clips_dir))
    except ValueError:
        rel = ""
    if rel and rel != os.curdir:
        parts.extend(rel.split(os.sep))

    found = []
    for person in known_persons:
        want = set(tokenize(person))
        for part in parts:
            if norm_person(part) == person:
                found.append(person)
                break
            if want and want <= set(tokenize(part)):
                found.append(person)
                break
    return found


def seed_clip_tags(clips_dirs, known_persons):
    """{basename: {"persons": [...], "topics": [], "clip_type": ...}} for clips.

    Pool/comp files named comp_NNNN.mp4 carry no evidence, so they come out
    with empty "persons" and clip_type "other" - ready for hand-tagging.
    """
    tags = {}
    seen = set()
    collisions = 0
    for clips_dir in clips_dirs:
        if not clips_dir or not os.path.isdir(clips_dir):
            continue
        for path in sorted(glob.glob(os.path.join(clips_dir, "**", "*.*"), recursive=True)):
            if not path.lower().endswith(VIDEO_EXTS):
                continue
            if os.path.basename(path).lower().startswith("competitor_source"):
                continue  # raw slicer input, never a timeline asset
            base = os.path.basename(path)
            if base.lower() in seen:
                collisions += 1
                continue
            seen.add(base.lower())
            stem = os.path.splitext(base)[0]
            file_tokens = tokenize(stem)
            tags[base] = {
                "persons": seed_persons(path, clips_dir, known_persons),
                "topics": [],
                "clip_type": detect_clip_type(file_tokens),
            }
    return tags, collisions


def main():
    p = argparse.ArgumentParser(description="Generate a starter clip tags JSON")
    p.add_argument("--clips-dir", dest="clips_dirs", action="append", default=[],
                   help="clip pool dir (repeatable)")
    p.add_argument("--entity-root", dest="entity_root", default=None,
                   help="dir of per-person image folders; person names are "
                        "derived from these (default: none)")
    p.add_argument("--persons", default=None,
                   help="comma-separated canonical person names, used instead "
                        "of --entity-root when given")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    if not args.clips_dirs:
        sys.exit("ERROR: pass at least one --clips-dir")

    if args.persons:
        known = [p for p in (norm_person(x) for x in args.persons.split(","))
                 if p]
    else:
        known = known_persons_from_entity_root(args.entity_root)

    tags, collisions = seed_clip_tags(args.clips_dirs, known)
    if not tags:
        sys.exit("ERROR: no clips found in the given --clips-dir(s)")

    auto_persons = sum(1 for e in tags.values() if e["persons"])
    auto_types = sum(1 for e in tags.values() if e["clip_type"] != "other")

    payload = {
        "_readme": ("One structured entry per clip. Fill in the empty "
                    "\"persons\" and \"topics\" lists by hand (watch the clip "
                    "or check its source context), then pass this file with "
                    "--asset-tags. Keys are bare filenames. \"persons\" uses "
                    "canonical lowercase names (see CLIP_TAGGING.md); "
                    "\"clip_type\" is one of interview|redcarpet|paparazzi|"
                    "talkshow|engagement|other. Delete entries you do not "
                    "care about - absent clips simply keep their folder and "
                    "filename labels."),
        "_stats": {
            "clips_scanned": len(tags),
            "known_persons": len(known),
            "persons_auto_tagged": auto_persons,
            "clip_types_detected": auto_types,
            "basename_collisions_skipped": collisions,
        },
        "tags": tags,
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"Clips scanned           : {len(tags)}")
    print(f"Known persons           : {len(known)}")
    print(f"Persons auto-tagged     : {auto_persons}")
    print(f"Clip types detected     : {auto_types}")
    if collisions:
        print(f"Basename collisions     : {collisions} (first occurrence kept)")
    print(f"Written                 : {args.out}")


if __name__ == "__main__":
    main()
