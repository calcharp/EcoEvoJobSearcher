"""Build a client-side search suggestion index from subject phrases + related groups."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from jobboards.db import connect, get_meta
from jobboards.subjects import (
    _display_term,
    _phrase_pattern,
    extract_terms,
    subject_term_counts,
)

# Explicit related-phrase clusters. Short aliases (ai, ml) are not cloud terms
# but should still expand to the longer phrases.
RELATED_GROUPS: list[dict[str, list[str]]] = [
    {
        "aliases": ["ai", "a.i.", "ml"],
        "terms": [
            "artificial intelligence",
            "machine learning",
            "deep learning",
            "computational biology",
            "bioinformatics",
        ],
    },
    {
        "aliases": ["gis"],
        "terms": ["remote sensing", "geospatial analysis", "landscape ecology"],
    },
    {
        "aliases": [],
        "terms": [
            "conservation genomics",
            "population genomics",
            "genome assembly",
            "genomics",
            "molecular biology",
        ],
    },
    {
        "aliases": [],
        "terms": [
            "climate change",
            "global change",
            "global change biology",
            "earth system science",
        ],
    },
    {
        "aliases": [],
        "terms": [
            "conservation biology",
            "conservation science",
            "biodiversity science",
            "restoration ecology",
        ],
    },
    {
        "aliases": ["evo", "evo bio"],
        "terms": ["evolutionary biology", "evolutionary ecology"],
    },
    {
        "aliases": [],
        "terms": ["phylogenetic comparative methods", "comparative methods"],
    },
    {
        "aliases": [],
        "terms": [
            "behavioral ecology",
            "behavioural ecology",
            "animal behavior",
        ],
    },
    {
        "aliases": [],
        "terms": ["marine ecology", "marine science", "aquatic ecology", "fish ecology"],
    },
    {
        "aliases": [],
        "terms": ["plant ecology", "plant biology", "seed biology"],
    },
    {
        "aliases": [],
        "terms": ["disease ecology", "microbial ecology", "invasion biology"],
    },
    {
        "aliases": [],
        "terms": ["community ecology", "population ecology", "quantitative ecology"],
    },
    {
        "aliases": ["stats", "statistical"],
        "terms": ["quantitative ecology", "bioinformatics"],
    },
]

_suggest_cache: dict | None = None


def _norm(s: str) -> str:
    text = str(s or "").lower().replace(".", "")
    return " ".join(text.replace("-", " ").split())


def _label(term: str) -> str:
    if len(term) <= 3:
        return term.upper()
    return _display_term(term)


def _groups_for_key() -> dict[str, set[str]]:
    by_key: dict[str, set[str]] = defaultdict(set)
    for group in RELATED_GROUPS:
        members = {_norm(x) for x in (group.get("aliases") or []) + (group.get("terms") or [])}
        members.discard("")
        for m in members:
            by_key[m] |= members
    return by_key


def _cooccurrence(min_count: int = 2, per_term: int = 5) -> dict[str, list[str]]:
    phrase_re = _phrase_pattern()
    pair_counts: Counter[tuple[str, str]] = Counter()
    with connect() as conn:
        rows = conn.execute(
            "SELECT subject_area FROM jobs WHERE subject_area IS NOT NULL AND subject_area != ''"
        ).fetchall()
    for row in rows:
        terms = sorted(extract_terms(row["subject_area"], phrase_re))
        for i, a in enumerate(terms):
            for b in terms[i + 1 :]:
                pair_counts[(a, b)] += 1
    related: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for (a, b), n in pair_counts.items():
        if n < min_count:
            continue
        related[a].append((n, b))
        related[b].append((n, a))
    out: dict[str, list[str]] = {}
    for key, scored in related.items():
        scored.sort(key=lambda x: (-x[0], x[1]))
        out[key] = [term for _, term in scored[:per_term]]
    return out


def search_suggest_index(min_count: int = 2) -> dict[str, Any]:
    """Terms, aliases, and related phrases for the search dropdown."""
    global _suggest_cache
    cache_key = (min_count, get_meta("last_fetched_at"))
    if _suggest_cache and _suggest_cache["key"] == cache_key:
        return _suggest_cache["payload"]

    counts = { _norm(item["term"]): int(item["count"]) for item in subject_term_counts(min_count=1) }
    group_map = _groups_for_key()
    cooccur = _cooccurrence()

    keys = set(counts)
    for group in RELATED_GROUPS:
        keys.update(_norm(x) for x in (group.get("aliases") or []) + (group.get("terms") or []))
    keys.discard("")

    # Keep cloud terms that meet min_count, plus every alias/group member.
    cloud_keys = {_norm(item["term"]) for item in subject_term_counts(min_count=min_count)}
    alias_keys = set()
    for group in RELATED_GROUPS:
        alias_keys.update(_norm(x) for x in group.get("aliases") or [])
        alias_keys.update(_norm(x) for x in group.get("terms") or [])

    keep = {k for k in keys if k in cloud_keys or k in alias_keys}

    terms_out = []
    for key in sorted(keep, key=lambda k: (-counts.get(k, 0), k)):
        related = []
        seen = {key}
        for extra in list(group_map.get(key, [])) + cooccur.get(key, []):
            extra = _norm(extra)
            if extra in seen or extra not in keep:
                continue
            seen.add(extra)
            related.append(_label(extra))
            if len(related) >= 6:
                break
        terms_out.append({
            "term": _label(key),
            "key": key,
            "count": counts.get(key, 0),
            "related": related,
        })

    aliases = {}
    for group in RELATED_GROUPS:
        canonical = _norm((group.get("terms") or [""])[0])
        for alias in group.get("aliases") or []:
            aliases[_norm(alias)] = canonical

    payload = {"terms": terms_out, "aliases": aliases}
    _suggest_cache = {"key": cache_key, "payload": payload}
    return payload
