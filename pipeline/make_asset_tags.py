"""
Starter generator for an asset tags JSON.

Folder names and filenames already label most of a library. This walks the same
pools the timeline engine indexes, works out which assets the matcher can
already describe, and writes a JSON skeleton listing the ones it cannot - so the
only assets you tag by hand are the ones that actually need it.

    python make_asset_tags.py --topic-config configs/dolly_parton.json --out configs/dolly_tags.json

Then edit the file: put real keywords in the empty lists, delete what you do not
care about, and pass it back with --asset-tags.
"""

import os
import sys
import json
import math
import argparse
from collections import defaultdict

from semantic_matcher import AssetIndex, folder_entity


def build_index(cfg, cli):
    index = AssetIndex()
    default_entity = (cli.default_entity or cfg.get("default_entity") or "").lower() or None

    images = cli.images_dir or cfg.get("images_dir")
    clips = cli.clips_dir or cfg.get("clips_dir")
    if images:
        index.add_dir(images, "image", entity=default_entity)
    if clips:
        index.add_dir(clips, "clip", entity=default_entity)

    root = cli.entity_root or cfg.get("entity_root")
    if root and os.path.isdir(root):
        skip = {s.lower() for s in cfg.get("entity_root_skip", [])}
        owned = {os.path.normcase(os.path.abspath(d))
                 for d in (images, clips, cfg.get("grid_dir")) if d}
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if not os.path.isdir(path) or name.lower() in skip:
                continue
            if os.path.normcase(os.path.abspath(path)) in owned:
                continue
            entity = folder_entity(path)
            if entity:
                index.add_dir(path, "image", entity=entity)
                index.add_dir(path, "clip", entity=entity)

    index.build_idf()
    return index, default_entity


def main():
    p = argparse.ArgumentParser(description="Generate a starter asset tags JSON")
    p.add_argument("--topic-config", default=None)
    p.add_argument("--out", required=True)
    p.add_argument("--images-dir", dest="images_dir", default=None)
    p.add_argument("--clips-dir", dest="clips_dir", default=None)
    p.add_argument("--entity-root", dest="entity_root", default=None)
    p.add_argument("--default-entity", dest="default_entity", default=None)
    p.add_argument("--rarity", type=float, default=0.2,
                   help="A term is 'useful' if it appears in fewer than this "
                        "fraction of the library (default 0.2)")
    p.add_argument("--limit-per-folder", type=int, default=0,
                   help="Only list this many untagged files per folder (0 = all)")
    args = p.parse_args()

    cfg = {}
    if args.topic_config:
        if not os.path.exists(args.topic_config):
            sys.exit(f"ERROR: topic config not found: {args.topic_config}")
        with open(args.topic_config, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)

    index, default_entity = build_index(cfg, args)
    if not index.assets:
        sys.exit("ERROR: no assets found. Pass --images-dir/--clips-dir or a topic config.")

    n = len(index.assets)
    floor = math.log((n + 1) / (n * args.rarity + 1))

    described, needs_tags = [], defaultdict(list)
    for a in index.assets:
        useful = sorted({t for t in a.tokens if index.idf.get(t, 0) > floor})
        if useful:
            described.append(a)
        else:
            needs_tags[os.path.dirname(a.path)].append(a)

    tags = {}
    for folder in sorted(needs_tags):
        assets = needs_tags[folder]
        if args.limit_per_folder:
            assets = assets[:args.limit_per_folder]
        for a in assets:
            # Pre-seed with the folder entity so the file is never unlabelled;
            # add scene keywords ("childhood", "stage", "1974") by hand.
            tags[a.path] = [a.entity] if a.entity else []

    payload = {
        "_readme": ("Add keywords to each list, then pass this file with "
                    "--asset-tags. Keys may be full paths or bare filenames. "
                    "Delete entries you do not need - anything absent simply "
                    "keeps its folder and filename labels."),
        "_stats": {
            "assets_indexed": n,
            "already_described": len(described),
            "need_tags": sum(len(v) for v in needs_tags.values()),
            "listed_here": len(tags),
            "entities_from_folders": len(index.entities),
        },
        "tags": tags,
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"Assets indexed          : {n}")
    print(f"Already describable     : {len(described)} "
          f"({100 * len(described) / n:.0f}%)")
    print(f"Would benefit from tags : {payload['_stats']['need_tags']}")
    print(f"Entities from folders   : {len(index.entities)}")
    print(f"Written                 : {args.out} ({len(tags)} entries)")
    print()
    print("Folders with the most untagged assets:")
    for folder, assets in sorted(needs_tags.items(), key=lambda kv: -len(kv[1]))[:10]:
        print(f"  {len(assets):5d}  {folder}")


if __name__ == "__main__":
    main()
