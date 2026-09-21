# Clip Tagging: Person + Topic Tags for Clips

## Why this exists

The #1 viewer complaint: when the narration names a person, the person on
screen is often someone else (or random B-roll). Pool clip filenames are
opaque (`comp_0001.mp4`), so the matcher had no way to know who is actually
in a clip. These tags fix that: you tell the matcher, once per clip, **who
is on screen** and **what the clip is about**, and the matcher then prefers
that clip whenever the narration names that person.

## The schema

`--asset-tags` accepts a JSON file whose `"tags"` map mixes two value
formats freely:

```json
{
  "tags": {
    "comp_0007.mp4": ["wedding", "windsor"],
    "comp_0042.mp4": {
      "persons": ["meghan markle"],
      "topics": ["surrogacy", "custody battle"],
      "clip_type": "interview"
    }
  }
}
```

- **Legacy format** — a keyword list (or a single string). Unchanged behaviour:
  the words are tokenised into the asset's keyword set. Old tags files keep
  working as-is.
- **Structured format** — a dict with three optional fields:
  - `"persons"`: list of canonical person names — lowercase, spaces not
    underscores, e.g. `"meghan markle"`, `"prince harry"`. This is the field
    that drives subject-synced picking. A single string is also accepted.
  - `"topics"`: list of topic keywords/phrases about the clip's subject
    matter, e.g. `"surrogacy"`, `"red carpet"`. These are tokenised into the
    asset's keyword set, so they also help plain keyword scoring.
  - `"clip_type"`: one of `interview` | `redcarpet` | `paparazzi` |
    `talkshow` | `engagement` | `other`. Informational for now (logged with
    the asset); unknown values are stored as `other`.

Keys may be full paths or bare filenames, exactly like the legacy format.

### Canonical person names

Use the folder names under `pool/images/` — they are the channel's
controlled vocabulary (15 people at the time of writing):

> carole middleton, charles spencer, king charles, laura lopes,
> meghan markle, prince george, prince harry, prince louis, prince william,
> princess anne, princess catherine, princess charlotte, princess diana,
> queen camilla, tom parker bowles

The matcher normalises names (`"Meghan_Markle"` → `"meghan markle"`), but
writing them canonical keeps the file clean. **Never invent a name for a
clip you cannot verify** — leave `"persons"` empty instead.

## Generating the skeleton

```bash
cd pipeline
python make_clip_tags.py \
  --clips-dir ~/workspace/royal/pool/clips \
  --clips-dir ~/workspace/royal/pool/competitor \
  --entity-root ~/workspace/royal/pool/images \
  --out configs/clip_tags.json
```

What it does:

1. Derives the known-person list from the `--entity-root` folders (or takes
   `--persons "meghan markle,prince harry"` instead).
2. For each clip, seeds `"persons"` only where the **filename or folder
   path itself names the person** (e.g. `meghan_markle_interview_01.mp4`,
   or `pool/meghan markle/comp_0007.mp4`). `comp_NNNN.mp4` files carry no
   evidence, so they come out with `"persons": []`.
3. Seeds `"clip_type"` from filename tokens (`interview`, `paparazzi`,
   `red carpet`, `talk show`, `engagement`); everything else is `"other"`.
4. Leaves `"topics"` empty everywhere — topics need a human.

The `_stats` block in the output tells you how many clips were auto-tagged
vs. left for you.

## Hand-tagging a clip

1. Open the clip (or check its source context) and identify who is actually
   on screen. If two people appear, list both: `"persons": ["meghan markle",
   "prince harry"]`.
2. Add 1–4 topic keywords for what the clip is *about*, not just who is in
   it: `"topics": ["surrogacy", "court case"]`. Skip generic words
   (`video`, `clip`, `royal`) — they match everything and help nothing.
3. Set `"clip_type"` if the skeleton guessed `"other"` and you can tell:
   an sit-down interview, red-carpet walk, paparazzi chase, talk-show
   appearance, engagement/wedding event.
4. If you genuinely cannot tell who is in the clip, leave it untagged —
   an untagged clip is neutral B-roll; a wrongly tagged clip actively
   misleads the matcher.

## How the matcher uses the tags

In `pipeline/semantic_matcher.py`:

- `AssetIndex.apply_tags()` parses both formats (`_parse_tag_value`).
  Structured values are stored on the asset as `Asset.persons` (canonical
  name set), `Asset.topics` (canonical phrase set) and `Asset.clip_type`;
  person and topic words are additionally merged into the asset's token
  set so ordinary IDF keyword scoring sees them too.
- `SemanticMatcher.pick(start, end, kind, position)` — signature unchanged —
  gains a **Tier 0** for clips: when the current segment's own words name a
  person (the existing segment-scoped `entities_in` machinery), clips whose
  `"persons"` tag includes that person are picked ahead of every other
  candidate. Untagged generic pool clips are only reached when no
  person-tagged clip is usable (all used, or none tagged for that person).
  The tier applies to `kind="clip"` only; image picking is unchanged.
- `SemanticMatcher.coverage()` counts a pick as correct when the clip's
  `"persons"` tag matches a named subject, even if the clip's folder entity
  is the generic pool — so the accuracy report reflects subject syncing,
  not just folder luck.

Pass the file to the pipeline exactly like the old tags file:

```bash
python run_pipeline.py --config configs/royal_config.json \
    --asset-tags configs/clip_tags.json ...
```

`configs/clip_tags.json` (hand-tagged legacy pool clips) and
`configs/clip_tags_v3.json` (V3 corpus, below) now also **load by default**
via `pipeline.load_all_tags()` — an explicit `--asset-tags` / config
`asset_tags` file is merged on top and wins on key conflicts.

## V3 ingestion: bulk corpora from the Semantic Visual Index (primary path)

For large pre-analysed corpora the approved source of tags is the V3
Semantic Visual Index, NOT visual re-tagging. The 2026-09-21 ingestion:

- Source: `/tmp/v3db/footage-index3.db`, VIEW `usable_clips` (status
  `analyzed`, SAFE, confidence 0.6–1.0, mean 0.98) → **3319 clips** from
  11 source videos (13.78 GB) in Drive folder
  `1kK0L33dEr8t7PueF7YcMXTGFO_JIX5L7`.
- Videos downloaded to `~/workspace/royal/v3_corpus/<asset_id>.mp4`
  (manifest: `v3_corpus/manifest.json`); clips cut with
  `ffmpeg -ss start -t dur -vf scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080 -c:v libx264 -preset veryfast -crf 20 -c:a aac -b:a 128k -r 30`
  into `~/workspace/royal/pool/v3_clips/v3_<asset8>_<clipid8>.mp4`
  (asset8/clipid8 = first 8 hex chars of the src/clip hash).
- Tags: `pipeline/configs/clip_tags_v3.json`, keyed by those basenames,
  `{"persons","topics","clip_type"}`. Persons = normalized union of
  `primary_subject` + `visible_subjects` (canonical map, e.g.
  `king charles iii`→`king charles`; combos split on and/,/&;
  `uncertain:` prefix stripped; non-person tokens dropped —
  `unknown person`, `crowd`, `royal carriage escort`, `lego figures`, …;
  named non-core people kept lowercased, never invented).
  Topics = `[event, location]` lowercased, `"unknown"` dropped.
  `clip_type` = normalized `shot_type`. 92 distinct persons; top:
  king charles 1199, queen camilla 1019, princess catherine 961,
  prince william 940. 62 clips (1.9%) honestly empty.
- Spot audit: 10 random clips, middle frame viewed, tagged person
  confirmed visible — see `v3_corpus/spot_audit.md`.
- Pool wiring: `pool/v3_clips` is a second `clips_dir`
  (`make_linux_config.py` sets `clips_dir: [pool/clips, pool/v3_clips]`;
  `_as_dir_list` drops missing dirs). Tags ride the default
  `load_all_tags()` path — no CLI flags needed.
- For the NEXT bulk corpus: repeat the same steps (index DB →
  download → cut → normalize → audit). `clip_tags_v3.json` is the
  single file the matcher reads; keep its key scheme.

## RULE 49: pipeline-sliced clips (ongoing path)

Clips sliced from competitor videos inside the pipeline
(`fresh_assets.slice_competitor_clips`) get 7 sample frames +
a skeleton manifest entry (`<clips_dir>/clip_tags_new.json`,
`"confidence": "unverified"`, persons seeded only from the video
config's `default_entity`) at extraction time — see RULE 49 in
PIPELINE_RULES.md. Nothing enters the pool untagged.
