import json
import re
from collections import Counter

from jobboards.db import connect, get_meta, set_meta

META_WATCH = "subject_phrases_watch"
META_IGNORE = "subject_phrases_ignore"

# Longest phrases first so we match multi-word terms before splitting.
BUILTIN_PHRASES = sorted(
    [
        "phylogenetic comparative methods",
        "comparative methods",
        "artificial intelligence",
        "machine learning",
        "deep learning",
        "remote sensing",
        "geospatial analysis",
        "conservation genomics",
        "population genomics",
        "molecular biology",
        "cell biology",
        "developmental biology",
        "evolutionary biology",
        "evolutionary ecology",
        "community ecology",
        "population ecology",
        "landscape ecology",
        "quantitative ecology",
        "global change biology",
        "global change",
        "climate change",
        "marine ecology",
        "aquatic ecology",
        "wetland ecology",
        "wildlife biology",
        "wildlife ecology",
        "fish ecology",
        "fisheries science",
        "conservation biology",
        "conservation science",
        "environmental science",
        "earth system science",
        "earth sciences",
        "marine science",
        "marine geology",
        "invasion biology",
        "invasion science",
        "plant ecology",
        "plant biology",
        "animal behavior",
        "behavioural ecology",
        "behavioral ecology",
        "functional ecology",
        "restoration ecology",
        "disease ecology",
        "microbial ecology",
        "systems biology",
        "structural biology",
        "computational biology",
        "bioinformatics",
        "multiomics",
        "genome assembly",
        "seed biology",
        "stress biology",
        "fish ecophysiology",
        "human anatomy",
        "anatomy and physiology",
        "anatomy & physiology",
        "biodiversity science",
    ],
    key=len,
    reverse=True,
)

SEGMENT_SPLIT = re.compile(
    r"[,;/|]|(?:\s+and/or\s+)|(?:\s+and\s+)|(?:\s+&\s+)|(?:\s+or\s+)",
    re.I,
)

RESIDUE_SPLIT = re.compile(r"\s+for\s+|\s+in\s+|\s+of\s+|\s+-\s+", re.I)

PAREN_SUFFIX = re.compile(r"\s*\([^)]*\)\s*$")

STOP_TERMS = {
    "and",
    "or",
    "the",
    "biology",
    "science",
    "sciences",
    "general",
    "research",
    "position",
    "positions",
    "faculty",
    "postdoc",
    "postdoctoral",
    "assistant professor",
    "professor",
    "lecturer",
    "instructor",
    "scientist",
    "manager",
    "lab manager",
    "teaching",
    "academic",
    "interdisciplinary",
    "foundational sciences",
    "other",
    "miscellaneous",
    "job",
    "jobs",
    "hire",
    "hiring",
    "open",
    "available",
    "americas",
    "usa",
    "uk",
    "canada",
}


def normalize_phrase(phrase: str) -> str:
    return re.sub(r"\s+", " ", (phrase or "").strip())


def get_phrase_prefs() -> dict[str, list[str]]:
    watch = json.loads(get_meta(META_WATCH) or "[]")
    ignore = json.loads(get_meta(META_IGNORE) or "[]")
    return {
        "watch": _dedupe_phrases(watch),
        "ignore": _dedupe_phrases(ignore),
    }


def save_phrase_prefs(watch: list[str], ignore: list[str]) -> None:
    set_meta(META_WATCH, json.dumps(_dedupe_phrases(watch)))
    set_meta(META_IGNORE, json.dumps(_dedupe_phrases(ignore)))


def _dedupe_phrases(phrases: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for phrase in phrases:
        clean = normalize_phrase(phrase)
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def _ignore_keys(prefs: dict[str, list[str]]) -> set[str]:
    return {p.lower() for p in prefs["ignore"]}


def _watch_keys(prefs: dict[str, list[str]]) -> set[str]:
    return {p.lower() for p in prefs["watch"]}


def active_phrases(prefs: dict[str, list[str]] | None = None) -> list[str]:
    prefs = prefs or get_phrase_prefs()
    ignore = _ignore_keys(prefs)
    combined: list[str] = []
    seen: set[str] = set()

    for phrase in prefs["watch"] + BUILTIN_PHRASES:
        key = phrase.lower()
        if key in ignore or key in seen:
            continue
        seen.add(key)
        combined.append(phrase)

    return sorted(combined, key=len, reverse=True)


def update_phrase_prefs(action: str, phrase: str) -> dict[str, list[str]]:
    clean = normalize_phrase(phrase)
    if not clean:
        raise ValueError("phrase required")

    prefs = get_phrase_prefs()
    watch = list(prefs["watch"])
    ignore = list(prefs["ignore"])
    key = clean.lower()

    if action == "watch":
        ignore = [p for p in ignore if p.lower() != key]
        if key not in {p.lower() for p in watch}:
            watch.append(clean)
    elif action == "ignore":
        watch = [p for p in watch if p.lower() != key]
        if key not in {p.lower() for p in ignore}:
            ignore.append(clean)
    elif action == "unwatch":
        watch = [p for p in watch if p.lower() != key]
    elif action == "unignore":
        ignore = [p for p in ignore if p.lower() != key]
    else:
        raise ValueError("unknown action")

    save_phrase_prefs(watch, ignore)
    clear_subject_cache()
    return get_phrase_prefs()


_phrase_pattern_cache: tuple[tuple[str, ...], re.Pattern[str]] | None = None
_term_counts_cache: dict | None = None


def clear_subject_cache() -> None:
    global _phrase_pattern_cache, _term_counts_cache
    _phrase_pattern_cache = None
    _term_counts_cache = None


def _phrase_pattern(phrases: list[str]) -> re.Pattern[str]:
    global _phrase_pattern_cache
    key = tuple(p.lower() for p in phrases)
    if _phrase_pattern_cache and _phrase_pattern_cache[0] == key:
        return _phrase_pattern_cache[1]
    parts = sorted((re.escape(p) for p in phrases), key=len, reverse=True)
    pattern = re.compile("|".join(parts), re.I) if parts else re.compile(r"(?!x)")
    _phrase_pattern_cache = (key, pattern)
    return pattern


def _clean_segment(segment: str) -> str:
    text = PAREN_SUFFIX.sub("", segment.strip(" -–—"))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _display_term(term: str, watch_phrases: list[str], watch_keys: set[str]) -> str:
    if term in watch_keys:
        for phrase in watch_phrases:
            if phrase.lower() == term:
                return phrase
    if term in BUILTIN_PHRASES:
        return term.title()
    for phrase in BUILTIN_PHRASES:
        if phrase.lower() == term:
            return phrase.title()
    return term.title()


def _is_valid_term(term: str, ignore_keys: set[str]) -> bool:
    if len(term) < 3:
        return False
    lower = term.lower()
    if lower in ignore_keys or lower in STOP_TERMS:
        return False
    if lower.endswith(" position") or lower.endswith(" scientist"):
        return False
    return True


def extract_terms(
    subject_area: str,
    phrase_re: re.Pattern[str],
    ignore_keys: set[str],
) -> set[str]:
    text = (subject_area or "").strip()
    if not text:
        return set()

    terms: set[str] = set()
    lower = text.lower()
    found_phrases = False

    for match in phrase_re.finditer(lower):
        key = match.group(0).lower()
        if key not in ignore_keys:
            terms.add(key)
            found_phrases = True

    scratch = phrase_re.sub(" ", lower)
    segments = [_clean_segment(s) for s in SEGMENT_SPLIT.split(text)]
    segments = [s for s in segments if s]

    if len(segments) > 1:
        for segment in segments:
            if _is_valid_term(segment, ignore_keys):
                terms.add(segment.lower())
    elif found_phrases:
        for part in RESIDUE_SPLIT.split(scratch):
            part = _clean_segment(part)
            if _is_valid_term(part, ignore_keys):
                terms.add(part.lower())
    elif len(segments) == 1 and _is_valid_term(segments[0], ignore_keys):
        terms.add(segments[0].lower())

    return terms


def subject_term_counts(min_count: int = 1) -> list[dict[str, int | str | bool]]:
    global _term_counts_cache

    prefs = get_phrase_prefs()
    ignore_keys = _ignore_keys(prefs)
    watch_keys = _watch_keys(prefs)
    phrases = active_phrases(prefs)
    cache_key = (
        tuple(prefs["watch"]),
        tuple(prefs["ignore"]),
        min_count,
        get_meta("last_fetched_at"),
    )
    if _term_counts_cache and _term_counts_cache["key"] == cache_key:
        return _term_counts_cache["items"]

    phrase_re = _phrase_pattern(phrases)

    with connect() as conn:
        rows = conn.execute(
            "SELECT subject_area FROM jobs WHERE subject_area IS NOT NULL AND subject_area != ''"
        ).fetchall()

    counter: Counter[str] = Counter()

    for row in rows:
        for term in extract_terms(row["subject_area"], phrase_re, ignore_keys):
            counter[term] += 1

    display: dict[str, str] = {}
    watched: dict[str, bool] = {}

    for key, count in counter.items():
        if key in ignore_keys:
            continue
        display[key] = _display_term(key, prefs["watch"], watch_keys)
        watched[key] = key in watch_keys

    for phrase in prefs["watch"]:
        key = phrase.lower()
        if key in ignore_keys:
            continue
        display[key] = phrase
        watched[key] = True

    items: list[dict[str, int | str | bool]] = []
    for key, label in display.items():
        count = counter.get(key, 0)
        threshold = 0 if key in watch_keys else min_count
        if count >= threshold:
            items.append({"term": label, "count": count, "watch": watched.get(key, False)})

    items.sort(key=lambda item: (-item["count"], str(item["term"]).lower()))
    _term_counts_cache = {"key": cache_key, "items": items}
    return items
