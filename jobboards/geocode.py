import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

from jobboards.db import connect, make_id

PHOTON_URL = "https://photon.komoot.io/api/"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "EcoEvoJobSearcher/1.0 (github.com/calcharp/EcoEvoJobSearcher)"
GEOCODE_WORKERS = 12
GEOCODE_BATCH_SIZE = 200
NOMINATIM_DELAY_SEC = 1.05

US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "district of columbia", "florida", "georgia",
    "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire",
    "new jersey", "new mexico", "new york", "north carolina", "north dakota",
    "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
}

CANADIAN_PROVINCES = {
    "alberta", "british columbia", "manitoba", "new brunswick",
    "newfoundland and labrador", "northwest territories", "nova scotia",
    "nunavut", "ontario", "prince edward island", "quebec", "saskatchewan",
    "yukon",
}

AU_STATES = {
    "new south wales", "queensland", "south australia", "tasmania",
    "victoria", "western australia", "australian capital territory",
    "northern territory",
}

US_STATE_ABBREV = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}

PAREN_COUNTRY = {
    "US": "USA", "USA": "USA", "UK": "UK", "GB": "UK", "CA": "Canada",
    "CN": "China", "CH": "Switzerland", "DE": "Germany", "FR": "France",
    "AT": "Austria", "JP": "Japan", "HK": "Hong Kong", "SG": "Singapore",
    "MO": "Macau", "KR": "South Korea", "AU": "Australia", "NL": "Netherlands",
    "BE": "Belgium", "DK": "Denmark", "SE": "Sweden", "NO": "Norway",
    "FI": "Finland", "ES": "Spain", "IT": "Italy", "PT": "Portugal",
    "IE": "Ireland", "PL": "Poland", "TW": "Taiwan", "IN": "India",
    "BR": "Brazil", "MX": "Mexico", "IL": "Israel", "NZ": "New Zealand",
}

CAMPUS_TYPES = {
    "university", "college", "museum", "research_institute", "school",
    "hospital", "library", "zoo", "aquarium",
}


def init_geo_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS geo_cache (
            place_key TEXT PRIMARY KEY,
            institution TEXT NOT NULL,
            location TEXT,
            query TEXT NOT NULL,
            lat REAL,
            lon REAL,
            precision TEXT,
            display_name TEXT,
            geocoded_at TEXT,
            error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_geo_cache_coords ON geo_cache(lat, lon);
        """
    )


def place_key(institution: str, location: Optional[str]) -> str:
    inst = re.sub(r"\s+", " ", (institution or "").strip().lower())
    loc = re.sub(r"\s+", " ", (location or "").strip().lower())
    return make_id("geo", inst, loc)


def normalize_location(location: Optional[str]) -> str:
    if not location:
        return ""
    loc = re.sub(r"\s+", " ", location.strip())

    paren = re.match(r"^(.+?)\s*\(([A-Za-z]{2,3})\)\s*$", loc)
    paren_country = None
    if paren:
        loc = paren.group(1).strip()
        paren_country = PAREN_COUNTRY.get(paren.group(2).upper())

    abbrev = re.match(r"^(.+),\s*([A-Z]{2})\s*$", loc)
    if abbrev:
        city = abbrev.group(1).strip()
        state = US_STATE_ABBREV.get(abbrev.group(2))
        if state:
            return f"{city}, {state}, USA"

    if "," in loc:
        parts = [p.strip() for p in loc.split(",")]
        if len(parts) >= 2 and parts[-1].lower() in US_STATES:
            return f"{', '.join(parts)}, USA"

    loc_lower = loc.lower()
    if loc_lower in US_STATES or loc_lower == "district of columbia":
        region = "Washington, DC, USA" if loc_lower == "district of columbia" else f"{loc}, USA"
        return region

    if loc_lower in CANADIAN_PROVINCES:
        return f"{loc}, Canada"

    if loc_lower in AU_STATES:
        return f"{loc}, Australia"

    if re.search(r"(?:shire|england|scotland|wales)\b", loc, re.I):
        if "united kingdom" not in loc_lower and loc_lower != "uk":
            return f"{loc}, UK"

    if paren_country:
        return f"{loc}, {paren_country}" if loc else paren_country

    return loc


def _institution_geo_candidates(institution: str) -> list[str]:
    inst = re.sub(r"\s+", " ", (institution or "").strip())
    if not inst:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        value = re.sub(r"\s+", " ", value.strip())
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            candidates.append(value)

    add(inst)

    m = re.match(r"^Department of [^,]+,\s*(.+)$", inst, re.I)
    if m:
        add(m.group(1))

    m = re.match(r"^([^,]+),\s*(?:Department|Dept\.?|School) of .+$", inst, re.I)
    if m:
        add(m.group(1))

    m = re.match(r"^(University of [^,/]+)", inst, re.I)
    if m:
        add(m.group(1))

    m = re.match(r"^(University of [^,]+?)(?:\s+Department\b.*)?$", inst, re.I)
    if m:
        add(m.group(1))

    m = re.match(r"^([^,]*University[^,]*)", inst, re.I)
    if m:
        add(m.group(1))

    m = re.match(r"^(.+?)\s+School of Medicine$", inst, re.I)
    if m:
        add(m.group(1))

    m = re.match(r"^(.+?)\s+Health Sciences Center\b.*$", inst, re.I)
    if m:
        add(m.group(1))

    return candidates


def _geocode_queries(institution: str, location: Optional[str]) -> list[str]:
    norm_loc = normalize_location(location)
    raw_loc = re.sub(r"\s+", " ", (location or "").strip())
    queries: list[str] = []
    seen: set[str] = set()

    def add(query: str) -> None:
        query = re.sub(r"\s+", " ", query.strip())
        key = query.lower()
        if query and key not in seen:
            seen.add(key)
            queries.append(query)

    for inst in _institution_geo_candidates(institution):
        if norm_loc:
            add(build_geo_query(inst, norm_loc))
        if raw_loc and raw_loc != norm_loc:
            add(build_geo_query(inst, raw_loc))

    if norm_loc:
        add(norm_loc)
    elif raw_loc:
        add(raw_loc)

    if not institution and raw_loc:
        add(build_geo_query("", raw_loc))

    return queries


def build_geo_query(institution: str, location: Optional[str]) -> str:
    inst = re.sub(r"\s+", " ", (institution or "").strip())
    loc = normalize_location(location)
    loc_lower = loc.lower()

    if not inst:
        return loc

    if loc_lower in US_STATES or loc_lower == "district of columbia":
        region = "Washington, DC, USA" if loc_lower == "district of columbia" else f"{loc}, USA"
        return f"{inst}, {region}"

    if loc_lower in CANADIAN_PROVINCES:
        return f"{inst}, {loc}, Canada"

    if loc_lower in AU_STATES:
        return f"{inst}, {loc}, Australia"

    country_aliases = {
        "united kingdom": "UK",
        "uk": "UK",
        "usa": "USA",
        "u.s.a.": "USA",
        "u.s.": "USA",
        "united states": "USA",
        "south korea": "South Korea",
        "new zealand": "New Zealand",
        "south africa": "South Africa",
        "costa rica": "Costa Rica",
        "hong kong": "Hong Kong",
        "united arab emirates": "UAE",
    }
    if loc_lower in country_aliases:
        return f"{inst}, {country_aliases[loc_lower]}"

    if loc_lower in {
        "germany", "france", "sweden", "norway", "denmark", "finland", "netherlands",
        "belgium", "austria", "switzerland", "spain", "italy", "portugal", "ireland",
        "poland", "czech republic", "hungary", "japan", "china", "taiwan", "india",
        "brazil", "mexico", "chile", "argentina", "israel", "singapore", "iceland",
        "greece", "turkey", "russia", "ukraine", "romania", "croatia", "slovenia",
        "australia", "canada",
    }:
        return f"{inst}, {loc}"

    if loc:
        return f"{inst}, {loc}"
    return inst


def _classify_photon_precision(props: dict[str, Any]) -> str:
    typ = (props.get("type") or props.get("osm_value") or "").lower()
    if typ in CAMPUS_TYPES or any(
        word in (props.get("name") or "").lower()
        for word in ("university", "college", "museum", "institute", "zoo")
    ):
        return "campus"
    if typ in {"city", "town", "village", "hamlet", "locality"}:
        return "city"
    if typ in {"state", "region", "county", "administrative"}:
        return "region"
    if typ == "country":
        return "country"
    return "city"


def _classify_nominatim_precision(result: dict[str, Any]) -> str:
    typ = (result.get("type") or "").lower()
    category = (result.get("category") or "").lower()
    name = (result.get("display_name") or "").lower()
    importance = float(result.get("importance") or 0)

    if typ in CAMPUS_TYPES or category in CAMPUS_TYPES:
        return "campus"
    if any(word in name for word in ("university", "college", "museum", "institute", "zoo")):
        return "campus"
    if typ in {"city", "town", "village", "hamlet"}:
        return "city"
    if typ in {"state", "region", "county", "administrative"}:
        return "region"
    if typ == "country":
        return "country"
    if importance >= 0.45:
        return "campus"
    if importance >= 0.2:
        return "city"
    return "region"


def _geocode_photon(query: str) -> Optional[dict[str, Any]]:
    try:
        resp = requests.get(
            PHOTON_URL,
            params={"q": query, "limit": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=12,
        )
        resp.raise_for_status()
        features = resp.json().get("features") or []
        if not features:
            return None
        hit = features[0]
        coords = hit.get("geometry", {}).get("coordinates") or []
        if len(coords) < 2:
            return None
        lon, lat = float(coords[0]), float(coords[1])
        props = hit.get("properties") or {}
        parts = [
            props.get("name"),
            props.get("city"),
            props.get("state"),
            props.get("country"),
        ]
        display_name = ", ".join(p for p in parts if p)
        return {
            "lat": lat,
            "lon": lon,
            "precision": _classify_photon_precision(props),
            "display_name": display_name or query,
        }
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None


def _geocode_nominatim(query: str) -> Optional[dict[str, Any]]:
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={
                "q": query,
                "format": "json",
                "limit": 1,
                "addressdetails": 1,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json()
        if not results:
            return None
        hit = results[0]
        return {
            "lat": float(hit["lat"]),
            "lon": float(hit["lon"]),
            "precision": _classify_nominatim_precision(hit),
            "display_name": hit.get("display_name"),
        }
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None


def geocode_query(query: str) -> Optional[dict[str, Any]]:
    result = _geocode_photon(query)
    if result:
        return result
    time.sleep(NOMINATIM_DELAY_SEC)
    return _geocode_nominatim(query)


def save_geo_cache(
    key: str,
    institution: str,
    location: Optional[str],
    query: str,
    result: Optional[dict[str, Any]],
    error: Optional[str] = None,
) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO geo_cache (
                place_key, institution, location, query, lat, lon,
                precision, display_name, geocoded_at, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(place_key) DO UPDATE SET
                query=excluded.query,
                lat=excluded.lat,
                lon=excluded.lon,
                precision=excluded.precision,
                display_name=excluded.display_name,
                geocoded_at=excluded.geocoded_at,
                error=excluded.error
            """,
            (
                key,
                institution,
                location or "",
                query,
                result["lat"] if result else None,
                result["lon"] if result else None,
                result["precision"] if result else None,
                result.get("display_name") if result else None,
                now,
                error,
            ),
        )


def _cached_location_fallback(location: Optional[str]) -> Optional[tuple[str, dict[str, Any]]]:
    norm = normalize_location(location)
    if not norm:
        return None
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT location, query, lat, lon, precision, display_name
            FROM geo_cache
            WHERE lat IS NOT NULL
            """
        ).fetchall()
    best = None
    best_score = 99
    for row in rows:
        if normalize_location(row["location"]) != norm:
            continue
        score = {"campus": 0, "city": 1, "region": 2, "country": 3}.get(
            row["precision"] or "", 4
        )
        if score < best_score:
            best_score = score
            best = row
    if not best:
        return None
    return best["query"], {
        "lat": best["lat"],
        "lon": best["lon"],
        "precision": best["precision"] or "city",
        "display_name": best["display_name"] or norm,
    }


def geocode_place(institution: str, location: Optional[str]) -> dict[str, Any]:
    key = place_key(institution, location)
    queries = _geocode_queries(institution, location)
    for query in queries:
        result = geocode_query(query)
        if result:
            save_geo_cache(key, institution, location, query, result)
            return {"place_key": key, "ok": True, **result}
    cached = _cached_location_fallback(location)
    if cached:
        query, result = cached
        save_geo_cache(key, institution, location, query, result)
        return {"place_key": key, "ok": True, **result}
    fallback = queries[0] if queries else build_geo_query(institution, location)
    save_geo_cache(key, institution, location, fallback, None, error="not found")
    return {"place_key": key, "ok": False}


def repair_geo_cache_location_fallbacks() -> int:
    """Fill failed geo_cache rows from successful rows with the same normalized location."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT place_key, institution, location, lat, query, lon, precision, display_name
            FROM geo_cache
            """
        ).fetchall()

    success_by_norm: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["lat"] is None:
            continue
        norm = normalize_location(row["location"])
        if not norm:
            continue
        score = {"campus": 0, "city": 1, "region": 2, "country": 3}.get(
            row["precision"] or "", 4
        )
        prev = success_by_norm.get(norm)
        if prev is None or score < prev["_score"]:
            success_by_norm[norm] = {**dict(row), "_score": score}

    if not success_by_norm:
        return 0

    fixed = 0
    for row in rows:
        if row["lat"] is not None:
            continue
        norm = normalize_location(row["location"])
        src = success_by_norm.get(norm or "")
        if not src:
            continue
        save_geo_cache(
            row["place_key"],
            row["institution"],
            row["location"],
            src["query"],
            {
                "lat": src["lat"],
                "lon": src["lon"],
                "precision": src["precision"] or "city",
                "display_name": src["display_name"] or norm,
            },
        )
        fixed += 1
    return fixed


def get_pending_places(limit: int = 100) -> list[tuple[str, str, str]]:
    """Places that have never been geocoded (no geo_cache row)."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT j.institution, COALESCE(j.location, '') AS location
            FROM jobs j
            LEFT JOIN geo_cache g
              ON g.institution = j.institution
             AND COALESCE(g.location, '') = COALESCE(j.location, '')
            WHERE COALESCE(j.institution, '') != ''
              AND g.place_key IS NULL
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [(place_key(r["institution"], r["location"]), r["institution"], r["location"]) for r in rows]


def get_failed_places(limit: int = 100) -> list[tuple[str, str, str]]:
    """Places geocoded before but with no coordinates (for optional local retry)."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT j.institution, COALESCE(j.location, '') AS location
            FROM jobs j
            INNER JOIN geo_cache g
              ON g.institution = j.institution
             AND COALESCE(g.location, '') = COALESCE(j.location, '')
            WHERE COALESCE(j.institution, '') != ''
              AND g.lat IS NULL
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [(place_key(r["institution"], r["location"]), r["institution"], r["location"]) for r in rows]


def geo_stats() -> dict[str, int]:
    with connect() as conn:
        total_places = conn.execute(
            """
            SELECT COUNT(*) AS c FROM (
                SELECT DISTINCT institution, COALESCE(location, '') FROM jobs
                WHERE COALESCE(institution, '') != ''
            )
            """
        ).fetchone()["c"]
        cached = conn.execute(
            "SELECT COUNT(*) AS c FROM geo_cache WHERE lat IS NOT NULL"
        ).fetchone()["c"]
        failed = conn.execute(
            "SELECT COUNT(*) AS c FROM geo_cache WHERE lat IS NULL"
        ).fetchone()["c"]
    pending = max(total_places - cached - failed, 0)
    return {
        "total_places": total_places,
        "cached": cached,
        "failed": failed,
        "pending": pending,
    }


def get_place_map_status(institution: str, location: Optional[str] = None) -> str:
    """Return mapped | unresolved | pending | no_institution."""
    if not (institution or "").strip():
        return "no_institution"
    key = place_key(institution, location or "")
    with connect() as conn:
        row = conn.execute(
            "SELECT lat FROM geo_cache WHERE place_key = ?",
            (key,),
        ).fetchone()
    if not row:
        return "pending"
    if row["lat"] is not None:
        return "mapped"
    return "unresolved"


def map_coverage_summary() -> dict[str, int]:
    """Job- and place-level map coverage for the static site."""
    stats = geo_stats()
    with connect() as conn:
        jobs_on_map = conn.execute(
            """
            SELECT COUNT(*) AS c FROM jobs j
            INNER JOIN geo_cache g
              ON g.institution = j.institution
             AND COALESCE(g.location, '') = COALESCE(j.location, '')
            WHERE COALESCE(j.institution, '') != ''
              AND g.lat IS NOT NULL
            """
        ).fetchone()["c"]
        jobs_unresolved = conn.execute(
            """
            SELECT COUNT(*) AS c FROM jobs j
            INNER JOIN geo_cache g
              ON g.institution = j.institution
             AND COALESCE(g.location, '') = COALESCE(j.location, '')
            WHERE COALESCE(j.institution, '') != ''
              AND g.lat IS NULL
            """
        ).fetchone()["c"]
        jobs_pending = conn.execute(
            """
            SELECT COUNT(*) AS c FROM jobs j
            LEFT JOIN geo_cache g
              ON g.institution = j.institution
             AND COALESCE(g.location, '') = COALESCE(j.location, '')
            WHERE COALESCE(j.institution, '') != ''
              AND g.place_key IS NULL
            """
        ).fetchone()["c"]
        total_jobs = conn.execute(
            "SELECT COUNT(*) AS c FROM jobs WHERE COALESCE(institution, '') != ''"
        ).fetchone()["c"]
    return {
        "jobs_total": total_jobs,
        "jobs_on_map": jobs_on_map,
        "jobs_unmapped": total_jobs - jobs_on_map,
        "jobs_unresolved": jobs_unresolved,
        "jobs_pending": jobs_pending,
        "places_total": stats["total_places"],
        "places_mapped": stats["cached"],
        "places_unresolved": stats["failed"],
        "places_pending": stats["pending"],
    }


def get_geo_for_keys(keys: list[str]) -> dict[str, dict[str, Any]]:
    if not keys:
        return {}
    unique = list(dict.fromkeys(keys))
    placeholders = ",".join("?" for _ in unique)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT place_key, lat, lon, precision, display_name
            FROM geo_cache
            WHERE place_key IN ({placeholders}) AND lat IS NOT NULL
            """,
            unique,
        ).fetchall()
    return {
        row["place_key"]: {
            "lat": row["lat"],
            "lon": row["lon"],
            "geo_precision": row["precision"],
            "geo_label": row["display_name"],
        }
        for row in rows
    }


def get_job_geo(institution: str, location: Optional[str] = None) -> Optional[dict[str, Any]]:
    key = place_key(institution, location or "")
    return get_geo_for_keys([key]).get(key)


def list_map_jobs(
    source: Optional[str] = None,
    search: Optional[str] = None,
    terms: Optional[list[str]] = None,
    sort: str = "posted_at",
    order: str = "desc",
    bbox: Optional[tuple[float, float, float, float]] = None,
    date_field: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> tuple[list[dict[str, Any]], int]:
    from jobboards.db import list_jobs

    jobs = list_jobs(
        source=source,
        search=search,
        terms=terms,
        sort=sort,
        order=order,
        date_field=date_field,
        date_from=date_from,
        date_to=date_to,
    )
    if not jobs:
        return [], 0

    keys = [place_key(j.get("institution", ""), j.get("location", "")) for j in jobs]
    geo_map = get_geo_for_keys(keys)

    mapped: list[dict[str, Any]] = []
    for job, key in zip(jobs, keys):
        geo = geo_map.get(key)
        if not geo:
            continue
        mapped.append({
            "id": job["id"],
            "institution": job.get("institution"),
            "location": job.get("location"),
            "subject_area": job.get("subject_area"),
            "apply_by": job.get("apply_by"),
            "posted_at": job.get("posted_at"),
            "source": job.get("source"),
            "lat": geo["lat"],
            "lon": geo["lon"],
            "geo_precision": geo["geo_precision"],
            "geo_label": geo["geo_label"],
        })

    if bbox:
        south, west, north, east = bbox
        mapped = [
            j for j in mapped
            if south <= j["lat"] <= north and west <= j["lon"] <= east
        ]

    return mapped, len(jobs) - sum(1 for key in keys if key in geo_map)


def run_geocode_batch(max_places: int = GEOCODE_BATCH_SIZE) -> int:
    return _run_geocode_batch(get_pending_places, max_places)


def run_geocode_retry_batch(max_places: int = GEOCODE_BATCH_SIZE) -> int:
    return _run_geocode_batch(get_failed_places, max_places)


def _run_geocode_batch(fetch_places, max_places: int) -> int:
    pending = fetch_places(limit=max_places)
    if not pending:
        return 0
    with ThreadPoolExecutor(max_workers=GEOCODE_WORKERS) as pool:
        futures = [
            pool.submit(geocode_place, inst, loc or None)
            for _, inst, loc in pending
        ]
        for future in as_completed(futures):
            future.result()
    return len(pending)


def run_geocode_all(max_total: Optional[int] = None) -> int:
    """Geocode places not yet in geo_cache. max_total=None means no limit."""
    return _run_geocode_loop(run_geocode_batch, max_total)


def run_geocode_retry_all(max_total: Optional[int] = None) -> int:
    """Retry places that previously failed to geocode (local use)."""
    return _run_geocode_loop(run_geocode_retry_batch, max_total)


def _run_geocode_loop(batch_fn, max_total: Optional[int]) -> int:
    total = 0
    while True:
        if max_total is not None and total >= max_total:
            break
        batch_limit = GEOCODE_BATCH_SIZE
        if max_total is not None:
            batch_limit = min(batch_limit, max_total - total)
        done = batch_fn(max_places=batch_limit)
        if done == 0:
            break
        total += done
    return total


def export_geo_cache(path: Path) -> int:
    """Write all geo_cache rows to JSON for seeding CI builds."""
    import json

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT place_key, institution, location, query, lat, lon,
                   precision, display_name, geocoded_at, error
            FROM geo_cache
            ORDER BY place_key
            """
        ).fetchall()
    entries = [dict(row) for row in rows]
    payload = {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "entries": entries,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(entries)


def import_geo_cache(path: Path) -> int:
    """Merge geo_cache rows from a JSON seed file into the local database."""
    import json

    if not path.is_file():
        return 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("entries") or []
    if not entries:
        return 0
    with connect() as conn:
        for row in entries:
            conn.execute(
                """
                INSERT INTO geo_cache (
                    place_key, institution, location, query, lat, lon,
                    precision, display_name, geocoded_at, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(place_key) DO UPDATE SET
                    query=excluded.query,
                    lat=excluded.lat,
                    lon=excluded.lon,
                    precision=excluded.precision,
                    display_name=excluded.display_name,
                    geocoded_at=excluded.geocoded_at,
                    error=excluded.error
                """,
                (
                    row["place_key"],
                    row["institution"],
                    row.get("location") or "",
                    row["query"],
                    row.get("lat"),
                    row.get("lon"),
                    row.get("precision"),
                    row.get("display_name"),
                    row.get("geocoded_at"),
                    row.get("error"),
                ),
            )
    return len(entries)
