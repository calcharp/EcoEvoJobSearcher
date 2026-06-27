import re
from collections import Counter

from jobboards.db import connect, get_meta

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

_phrase_pattern_cache: re.Pattern[str] | None = None
_term_counts_cache: dict | None = None


def clear_subject_cache() -> None:
    global _phrase_pattern_cache, _term_counts_cache
    _phrase_pattern_cache = None
    _term_counts_cache = None


def _phrase_pattern() -> re.Pattern[str]:
    global _phrase_pattern_cache
    if _phrase_pattern_cache is not None:
        return _phrase_pattern_cache
    parts = sorted((re.escape(p) for p in BUILTIN_PHRASES), key=len, reverse=True)
    _phrase_pattern_cache = re.compile("|".join(parts), re.I) if parts else re.compile(r"(?!x)")
    return _phrase_pattern_cache


def _clean_segment(segment: str) -> str:
    text = PAREN_SUFFIX.sub("", segment.strip(" -–—"))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _display_term(term: str) -> str:
    if term in BUILTIN_PHRASES:
        return term.title()
    for phrase in BUILTIN_PHRASES:
        if phrase.lower() == term:
            return phrase.title()
    return term.title()


def _is_valid_term(term: str) -> bool:
    if len(term) < 3:
        return False
    lower = term.lower()
    if lower in STOP_TERMS:
        return False
    if lower.endswith(" position") or lower.endswith(" scientist"):
        return False
    return True


def extract_terms(subject_area: str, phrase_re: re.Pattern[str]) -> set[str]:
    text = (subject_area or "").strip()
    if not text:
        return set()

    terms: set[str] = set()
    lower = text.lower()
    found_phrases = False

    for match in phrase_re.finditer(lower):
        terms.add(match.group(0).lower())
        found_phrases = True

    scratch = phrase_re.sub(" ", lower)
    segments = [_clean_segment(s) for s in SEGMENT_SPLIT.split(text)]
    segments = [s for s in segments if s]

    if len(segments) > 1:
        for segment in segments:
            if _is_valid_term(segment):
                terms.add(segment.lower())
    elif found_phrases:
        for part in RESIDUE_SPLIT.split(scratch):
            part = _clean_segment(part)
            if _is_valid_term(part):
                terms.add(part.lower())
    elif len(segments) == 1 and _is_valid_term(segments[0]):
        terms.add(segments[0].lower())

    return terms


def subject_term_counts(min_count: int = 1) -> list[dict[str, int | str]]:
    global _term_counts_cache

    cache_key = (min_count, get_meta("last_fetched_at"))
    if _term_counts_cache and _term_counts_cache["key"] == cache_key:
        return _term_counts_cache["items"]

    phrase_re = _phrase_pattern()

    with connect() as conn:
        rows = conn.execute(
            "SELECT subject_area FROM jobs WHERE subject_area IS NOT NULL AND subject_area != ''"
        ).fetchall()

    counter: Counter[str] = Counter()
    for row in rows:
        for term in extract_terms(row["subject_area"], phrase_re):
            counter[term] += 1

    items: list[dict[str, int | str]] = []
    for key, count in counter.items():
        if count >= min_count:
            items.append({"term": _display_term(key), "count": count})

    items.sort(key=lambda item: (-item["count"], str(item["term"]).lower()))
    _term_counts_cache = {"key": cache_key, "items": items}
    return items
