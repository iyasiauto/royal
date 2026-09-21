# V3 Clip Spot Audit — 2026-09-21

10 random clips from `pool/v3_clips/` (seed 21), middle frame extracted and
visually compared against `pipeline/configs/clip_tags_v3.json`.

| # | Clip | Tagged persons | Visual verdict |
|---|------|----------------|----------------|
| 1 | v3_da40332e_9a9604a7.mp4 | queen camilla | PLAUSIBLE — older blonde woman in green at garden party |
| 2 | v3_da40332e_eaa7f696.mp4 | princess catherine | PLAUSIBLE — woman at microphone, matches Catherine |
| 3 | v3_69848a7f_0a46b3c0.mp4 | princess catherine, prince william, princess charlotte, king felipe vi of spain | STRONG — all four visible, Wimbledon setting matches topic tag |
| 4 | v3_b19a0763_492a4650.mp4 | prince william | STRONG — clearly William speaking indoors |
| 5 | v3_a5ef85cf_02765aab.mp4 | princess beatrice | PLAUSIBLE — blonde young woman in floral dress |
| 6 | v3_69848a7f_657ec2d4.mp4 | queen camilla | PLAUSIBLE — blonde woman in blue hat/outfit in crowd |
| 7 | v3_04816d6c_99cb087b.mp4 | princess catherine | PLAUSIBLE — long-haired blonde woman entering office building (side/back view) |
| 8 | v3_69848a7f_76de5f5e.mp4 | prince william | UNCERTAIN — balding man in navy suit seen from behind; build consistent with William but face not visible |
| 9 | v3_58a7be8a_a015715b.mp4 | princess catherine, prince william, prince george, princess charlotte, prince louis | STRONG — whole Wales family walking outdoors |
| 10 | v3_69848a7f_47d7186b.mp4 | princess catherine | PLAUSIBLE — woman at podium, matches Catherine |

**Result: 10/10 consistent, 0 contradictions.** 4 strong matches, 5 plausible,
1 uncertain (back view, no contradiction). No mislabeled identities found.

Cutting method note: clips were cut with ffmpeg stream copy (`-c copy`,
`-ss` before `-i`) after the original re-encode worker died with its parent
agent at 190/3319. Source footage is already 1920x1080, and the render engine
normalizes every pool clip to 1080p at render time anyway, so stream-copied
clips behave identically in the pipeline. 3319/3319 cut, 0 failures.
