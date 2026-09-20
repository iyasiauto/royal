"""
Semantic asset matching.

Answers one question for every timeline slot: given what the narration is saying
between t0 and t1, which photograph or clip belongs on screen?

Labels come from three sources, most reliable first:

  1. Folder name   - "porter-wagoner/dolly_0007.jpg" is a Porter Wagoner photo
                     regardless of how uninformative the filename is.
  2. Filename      - "002-dolly-parton-patriotic-portrait.jpg" contributes real
                     keywords; "dolly_0002.webp" contributes nothing.
  3. Tags JSON     - hand-written or generated overrides, keyed by path.

Scoring is IDF-weighted so terms that appear in almost every asset (like "dolly"
in a Dolly Parton library) carry no weight, while rare, specific terms do.
"""

import os
import re
import json
import math
import glob
from collections import Counter, defaultdict

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".m4v")

# Folder-name suffixes that describe the container, not the subject.
FOLDER_NOISE = {"clips", "clip", "images", "image", "photos", "photo", "pics",
                "pictures", "data", "real", "assets", "media", "footage", "raw"}

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "at", "by", "for", "with",
    "about", "into", "through", "during", "before", "after", "above", "below",
    "to", "from", "up", "down", "in", "out", "on", "off", "over", "under",
    "again", "then", "once", "here", "there", "when", "where", "why", "how",
    "all", "any", "both", "each", "few", "more", "most", "other", "some",
    "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too",
    "very", "can", "will", "just", "should", "now", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "having", "do", "does", "did",
    "doing", "would", "could", "shall", "may", "might", "must", "that", "this",
    "these", "those", "it", "its", "he", "she", "his", "her", "they", "them",
    "their", "we", "our", "you", "your", "i", "my", "me", "him", "who", "whom",
    "which", "what", "as", "because", "while", "until", "one", "two", "first",
    "last", "new", "old", "years", "year", "time", "way", "day", "man", "woman",
    "people", "life", "world", "never", "always", "still", "even", "also",
    "jpg", "jpeg", "png", "webp", "bmp", "mp4", "mov", "mkv", "webm",
}

TOKEN_RE = re.compile(r"[a-z]{3,}")


def _stem(token):
    """Fold obvious plurals so "mugshot" and "mugshots" are the same term.

    Deliberately crude: both the script and the asset labels go through this,
    so the two sides always agree even when the fold is linguistically wrong.
    """
    if len(token) > 4:
        if token.endswith("ies"):
            return token[:-3] + "y"
        if token.endswith("sses") or token.endswith("shes") or token.endswith("ches"):
            return token[:-2]
        if token.endswith("s") and not token.endswith("ss"):
            return token[:-1]
    return token


def tokenize(text):
    """Lowercase word tokens of 3+ letters, stopwords removed, plurals folded."""
    return [_stem(t) for t in TOKEN_RE.findall(str(text).lower())
            if t not in STOPWORDS]


def folder_entity(dir_path):
    """Turn a directory name into an entity phrase, dropping container words."""
    raw = os.path.basename(os.path.normpath(dir_path))
    parts = [p for p in re.split(r"[\s\-_]+", raw.lower()) if p]
    parts = [p for p in parts if p not in FOLDER_NOISE and not p.isdigit()]
    return " ".join(parts)


class Asset:
    """One photo or clip plus everything known about what it depicts."""

    __slots__ = ("path", "kind", "entity", "entity_tokens", "tokens", "source_id")

    def __init__(self, path, kind, entity, tokens, source_id):
        self.path = path
        self.kind = kind
        self.entity = entity
        self.entity_tokens = set(entity.split()) if entity else set()
        self.tokens = tokens
        self.source_id = source_id

    def __repr__(self):
        return f"<Asset {os.path.basename(self.path)} entity={self.entity!r}>"


class AssetIndex:
    """A searchable pool of assets with IDF weights over their vocabulary."""

    def __init__(self):
        self.assets = []
        self._seen = set()
        self.idf = {}
        self.entities = {}

    def add_dir(self, dir_path, kind, entity=None, recursive=False):
        """Index one directory. Entity defaults to the folder name."""
        if not dir_path or not os.path.isdir(dir_path):
            return 0
        exts = IMAGE_EXTS if kind == "image" else VIDEO_EXTS
        ent = entity if entity is not None else folder_entity(dir_path)
        pattern = "**/*.*" if recursive else "*.*"

        added = 0
        for path in glob.glob(os.path.join(dir_path, pattern), recursive=recursive):
            if not path.lower().endswith(exts):
                continue
            # yt-dlp'd competitor source lives in the clips folder as the
            # slicer's input — it must never be picked as a timeline asset
            # (the raw video carries the source channel's logo/watermark and
            # the render engine has no framing path for a non-comp_ filename).
            if os.path.basename(path).lower().startswith("competitor_source"):
                continue
            key = os.path.normcase(os.path.abspath(path))
            if key in self._seen:
                continue
            self._seen.add(key)

            name = os.path.splitext(os.path.basename(path))[0]
            tokens = set(tokenize(name)) | set(ent.split() if ent else [])
            # The cooldown exists to stop two sub-clips of the same source video
            # appearing close together. Photographs have no such relationship,
            # so each one is its own source - otherwise a shared filename prefix
            # (dolly_0001, dolly_0002, ...) would lock the whole pool at once.
            source_id = path if kind == "image" else name.split("_")[0]
            self.assets.append(Asset(path, kind, ent, tokens, source_id))
            added += 1

        if ent and added:
            self.entities.setdefault(ent, 0)
            self.entities[ent] += added
        return added

    def apply_tags(self, tags):
        """Merge a {path_or_basename: [tags]} mapping onto the indexed assets."""
        if not tags:
            return 0
        by_base = defaultdict(list)
        by_abs = {}
        for a in self.assets:
            by_base[os.path.basename(a.path).lower()].append(a)
            by_abs[os.path.normcase(os.path.abspath(a.path))] = a

        applied = 0
        for key, values in tags.items():
            if isinstance(values, str):
                values = [values]
            extra = set()
            for v in values:
                extra.update(tokenize(v))
            if not extra:
                continue

            target = by_abs.get(os.path.normcase(os.path.abspath(key)))
            targets = [target] if target else by_base.get(os.path.basename(key).lower(), [])
            for a in targets:
                a.tokens |= extra
                applied += 1
        return applied

    def build_idf(self):
        """Inverse document frequency, so library-wide terms score near zero."""
        n = max(1, len(self.assets))
        df = Counter()
        for a in self.assets:
            df.update(a.tokens)
        self.idf = {t: math.log((n + 1) / (c + 1)) for t, c in df.items()}
        return self.idf

    def describable(self):
        """How many assets carry any term rarer than 20% of the library."""
        if not self.idf:
            self.build_idf()
        floor = math.log((len(self.assets) + 1) / (len(self.assets) * 0.2 + 1))
        return sum(1 for a in self.assets
                   if any(self.idf.get(t, 0) > floor for t in a.tokens))

    def stats(self):
        kinds = Counter(a.kind for a in self.assets)
        return {"total": len(self.assets),
                "images": kinds.get("image", 0),
                "clips": kinds.get("clip", 0),
                "entities": len(self.entities),
                "describable": self.describable()}


class ScriptTimeline:
    """Maps wall-clock time in the finished video back to script text."""

    def __init__(self, spans):
        # spans: list of (start, end, text)
        self.spans = spans

    @classmethod
    def from_manifest(cls, manifest, lead=0.0, span_words=15):
        """Exact per-chunk timing recorded by the voiceover engine."""
        spans = []
        t = float(lead)
        for chunk in manifest:
            dur = float(chunk["duration"])
            spans.extend(cls._split_chunk(chunk["text"], t, t + dur, span_words))
            t += dur
        return cls(spans)

    @classmethod
    def from_srt(cls, srt_path_or_content, lead=0.0, span_words=12):
        """Build exact fine-grained script spans directly from voiceover SRT subtitle file."""
        spans = []
        if os.path.exists(str(srt_path_or_content)):
            with open(srt_path_or_content, "r", encoding="utf-8-sig", errors="ignore") as f:
                content = f.read()
        else:
            content = str(srt_path_or_content)

        blocks = re.split(r"\n\s*\n", content.strip())
        for b in blocks:
            lines = [l.strip() for l in b.strip().splitlines() if l.strip()]
            if len(lines) >= 3:
                time_line = lines[1]
                text = " ".join(lines[2:])
                m = re.match(r"(\d+):(\d+):(\d+)[,\.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,\.](\d+)", time_line)
                if m:
                    h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, m.groups())
                    t1 = float(lead) + h1 * 3600 + m1 * 60 + s1 + ms1 / 1000.0
                    t2 = float(lead) + h2 * 3600 + m2 * 60 + s2 + ms2 / 1000.0
                    spans.extend(cls._split_chunk(text, t1, t2, target_words=span_words))
        return cls(spans)

    @classmethod
    def from_text(cls, text, total_duration, lead=0.0, span_words=15):
        """Even words-per-second estimate when no manifest exists."""
        return cls(cls._split_chunk(text, float(lead),
                                    float(lead) + float(total_duration), span_words))

    @staticmethod
    def _split_chunk(text, start, end, target_words=45):
        """Subdivide a chunk into sentence groups, timed by word count."""
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", str(text)) if s.strip()]
        if not sentences:
            return []

        groups, current, count = [], [], 0
        for s in sentences:
            current.append(s)
            count += len(s.split())
            if count >= target_words:
                groups.append(" ".join(current))
                current, count = [], 0
        if current:
            if groups:
                groups[-1] += " " + " ".join(current)
            else:
                groups.append(" ".join(current))

        total_words = sum(len(g.split()) for g in groups) or 1
        spans, t = [], start
        for g in groups:
            share = (end - start) * len(g.split()) / total_words
            spans.append((t, t + share, g))
            t += share
        return spans

    def text_between(self, start, end):
        """Every script span overlapping the window, joined."""
        out = [txt for (a, b, txt) in self.spans if b > start and a < end]
        if not out:
            nearest = min(self.spans, key=lambda s: abs(s[0] - start), default=None)
            return nearest[2] if nearest else ""
        return " ".join(out)


class SemanticMatcher:
    """Picks the asset that best fits what the narration is saying."""

    def __init__(self, index, script_timeline, entity_boost=6.0,
                 context_seconds=8.0, cooldown=15, entity_cooldown=4,
                 default_entity=None, partial_threshold=0.5):
        self.index = index
        self.script = script_timeline
        self.entity_boost = float(entity_boost)
        self.context_seconds = float(context_seconds)
        self.cooldown = int(cooldown)
        self.entity_cooldown = int(entity_cooldown)
        self.default_entity = (default_entity or "").lower().replace("_", " ") or None
        self.partial_threshold = float(partial_threshold)

        if not index.idf:
            index.build_idf()

        self.by_kind = defaultdict(list)
        for a in index.assets:
            self.by_kind[a.kind].append(a)

        # Folder names are topic buckets, not just people: "keffe d courtroom
        # verdict" and "crime scene las vegas" are as meaningful as "tupac
        # shakur". Every folder stays matchable; a name that never appears
        # contiguously in the narration simply never scores a full match.
        self._entity_phrases = sorted(index.entities, key=len, reverse=True)
        # Match entity words the same way script words are tokenised, or an
        # initial like the "D" in "Keffe D" would be a word that can never be
        # matched and would drag every partial score down.
        self._entity_tokens = {e: set(tokenize(e)) for e in index.entities}
        self.used_paths = set()
        self.used_sources = {}
        self.used_entities = {}
        self.match_log = []

    def entities_in(self, text):
        """Which indexed entities the narration names in this window."""
        low = " " + re.sub(r"[^a-z ]+", " ", text.lower()) + " "
        low = re.sub(r"\s+", " ", low)
        # Contiguous phrase only. Matching on scattered tokens made unrelated
        # people match whenever their first names appeared anywhere nearby.
        return [p for p in self._entity_phrases if p and f" {p} " in low]

    def partial_entity(self, entity, token_counts):
        """Fraction of a folder name's words the narration is currently using.

        "crime scene las vegas" should still pull its folder when the script
        says "the Las Vegas crime scene" in a different word order.
        """
        want = self._entity_tokens.get(entity) or set()
        if len(want) < 2:
            return 0.0
        hit = sum(1 for t in want if t in token_counts)
        return hit / len(want)

    def query(self, start, end):
        """Tokens and time-weighted entities for the narration around a slot.

        Surrounding context is included so a slot is not starved of keywords,
        but a name mentioned several seconds away must not outrank the one
        being spoken over this segment - otherwise wide windows make every
        nearby subject equally eligible and the picks become arbitrary.
        """
        pad = self.context_seconds
        mid = (start + end) / 2.0
        reach = max(1e-6, pad + (end - start))

        tokens = Counter()
        seg_tokens = Counter()  # words spoken inside this segment only
        weights = defaultdict(float)
        for (a, b, txt) in self.script.spans:
            if b <= start - pad or a >= end + pad:
                continue
            if a <= mid <= b:
                w = 1.0
            else:
                gap = (a - mid) if a > mid else (mid - b)
                w = max(0.0, 1.0 - gap / reach)
            tw = tokenize(txt)
            for t in tw:
                tokens[t] += w
            # Entity inference is strictly segment-scoped: a name from a
            # neighbouring segment must not make its assets eligible here
            # (that caused Diana/Doria pictures on Meghan lines).
            if b > start and a < end:
                for t in tw:
                    seg_tokens[t] += w
                for e in self.entities_in(txt):
                    weights[e] = max(weights[e], 1.0)

        if not tokens and self.script.spans:
            nearest = min(self.script.spans, key=lambda s: abs(s[0] - start))
            tokens.update(tokenize(nearest[2]))
            for e in self.entities_in(nearest[2]):
                weights[e] = max(weights[e], 0.5)

        # A folder like "crime scene las vegas" rarely appears as that exact
        # phrase, but "the crime scene at the Las Vegas intersection" is plainly
        # about it. Credit the overlap so topical folders compete fairly with
        # plain personal names.
        for entity, want in self._entity_tokens.items():
            if len(want) < 2 or weights.get(entity, 0.0) >= 1.0:
                continue
            # Weight the overlap by IDF, not by raw word count. "stella parton"
            # must not count as matched just because the narration said
            # "Parton" - the distinctive half of the name has to be present.
            total = sum(self.idf_of(t) for t in want)
            if total <= 0:
                continue
            # Partial overlap is scored against the segment's own words only, so a
            # name spoken in a neighbouring segment cannot leak in via the
            # padded context tokens.
            frac = sum(self.idf_of(t) for t in want if t in seg_tokens) / total
            if frac >= self.partial_threshold:
                weights[entity] = max(weights[entity], frac * 0.9)

        return tokens, dict(weights), None

    def score(self, asset, tokens, entities, position):
        """Higher is better; -inf means unusable at this position."""
        if asset.path in self.used_paths:
            return float("-inf")

        last_src = self.used_sources.get(asset.source_id)
        if last_src is not None and position - last_src < self.cooldown:
            return float("-inf")

        s = 0.0
        for t, n in tokens.items():
            if t in asset.tokens:
                s += self.idf_of(t) * (1.0 + math.log1p(n))

        weight = entities.get(asset.entity, 0.0) if asset.entity else 0.0
        if weight > 0:
            s += self.entity_boost * weight
            last_ent = self.used_entities.get(asset.entity)
            if last_ent is not None and position - last_ent < self.entity_cooldown:
                s -= self.entity_boost * 0.5
            return s

        if asset.entity and asset.entity != self.default_entity and weight == 0.0:
            s -= self.entity_boost * 1.5
        return s

    def idf_of(self, token):
        return self.index.idf.get(token, 0.0)

    def pick(self, start, end, kind, position):
        """Best asset for this slot, or None if the pool is exhausted."""
        pool = self.by_kind.get(kind) or []
        if not pool:
            return None, 0.0, []

        tokens, entities, _ = self.query(start, end)

        # Include all entities named in the narration (including default_entity)
        named = list(entities.keys())
        candidates = pool
        had_subject_asset = False
        if named:
            top = max(entities[e] for e in named)
            dominant = [e for e in named if entities[e] >= top - 1e-9]
            usable = [a for a in pool
                      if self.score(a, tokens, entities, position) > float("-inf")]

            # Tier 1 - footage of the person actually being discussed.
            preferred = [a for a in usable if a.entity in dominant]
            had_subject_asset = bool(preferred)

            if preferred:
                candidates = preferred
            else:
                # Tier 2 - fallback to default entity (main subject) or neutral footage
                default_safe = [a for a in usable if a.entity == self.default_entity]
                safe = [a for a in usable
                        if not a.entity
                        or a.entity == self.default_entity
                        or entities.get(a.entity, 0.0) > 0]
                candidates = default_safe or safe or usable
            named = dominant
        else:
            # No entity explicitly named in script span - prefer default_entity over secondary entity folders
            usable = [a for a in pool
                      if self.score(a, tokens, entities, position) > float("-inf")]
            default_safe = [a for a in usable if a.entity == self.default_entity]
            candidates = default_safe or usable

        best, best_score = None, float("-inf")
        for a in candidates:
            sc = self.score(a, tokens, entities, position)
            if sc > best_score:
                best, best_score = a, sc

        if best is None or best_score == float("-inf"):
            # Cooldown locked everything out; take any unused asset.
            for a in pool:
                if a.path not in self.used_paths:
                    best, best_score = a, 0.0
                    break

        if best is None and pool:
            # Pool exhausted; clear used paths for this kind so semantic matching recycles gracefully
            for a in pool:
                self.used_paths.discard(a.path)
            best, best_score = pool[position % len(pool)], 0.0

        if best is None:
            return None, 0.0, entities

        self.used_paths.add(best.path)
        self.used_sources[best.source_id] = position
        if best.entity:
            self.used_entities[best.entity] = position
        self.match_log.append({
            "position": position, "start": round(start, 2), "kind": kind,
            "file": os.path.basename(best.path), "entity": best.entity,
            "score": round(best_score, 3),
            "entities_in_script": {e: round(w, 2) for e, w in
                                   sorted(entities.items(), key=lambda kv: -kv[1])},
            "named_subjects": named,
            "subject_asset_available": had_subject_asset,
        })
        return best, best_score, entities

    def release_all(self):
        """Allow reuse once the pool has been fully consumed."""
        self.used_paths.clear()

    def has_assets_for(self, entity, kind, unused_only=False):
        """Whether the library holds any asset of this kind for an entity."""
        pool = self.by_kind.get(kind, [])
        if unused_only:
            return any(a.entity == entity and a.path not in self.used_paths
                       for a in pool)
        return any(a.entity == entity for a in pool)

    def coverage(self):
        """Report accuracy where it is actually measurable.

        The meaningful question is not "did we match an entity" (the subject of
        the documentary is named constantly), but: when the narration named
        *someone else*, did we show them - and if not, did the library even
        contain footage of them?
        """
        if not self.match_log:
            return {"picks": 0}

        named = [m for m in self.match_log if m["named_subjects"]]
        correct = missed = unavailable = wrong_person = 0
        for m in named:
            if m["entity"] in m["named_subjects"]:
                correct += 1
            elif not m["subject_asset_available"]:
                # Nothing of that person was left to show. Falling back to the
                # documentary's own subject is correct; showing a different
                # named person is the one outcome that actually looks wrong.
                unavailable += 1
                # Only count it as the wrong person if whoever is on screen is
                # not named anywhere in this window. When the narration covers
                # two people and the library has nothing for the more dominant
                # one, showing the other is a reasonable choice, not an error.
                if (m["entity"] and m["entity"] != self.default_entity
                        and m["entities_in_script"].get(m["entity"], 0.0) <= 0):
                    wrong_person += 1
            else:
                missed += 1

        return {
            "picks": len(self.match_log),
            "scored": sum(1 for m in self.match_log if m["score"] > 0),
            "named_subject_slots": len(named),
            "named_correct": correct,
            "named_missed_despite_available": missed,
            "named_none_left_to_show": unavailable,
            "wrong_person_shown": wrong_person,
        }


def load_tags(path):
    """Read a tags JSON: {"file.jpg": ["keyword", ...], ...}"""
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    return data.get("tags", data) if isinstance(data, dict) else {}
