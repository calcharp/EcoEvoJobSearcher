import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from jobboards.config import db_path
from jobboards.notes import parse_notes_thread


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_tab TEXT,
    source_slug TEXT,
    institution TEXT,
    location TEXT,
    subject_area TEXT,
    rank_or_pi TEXT,
    position_type TEXT,
    title TEXT,
    url TEXT,
    url_normalized TEXT,
    urls_json TEXT,
    contact_email TEXT,
    posted_at TEXT,
    apply_by TEXT,
    updated_at TEXT,
    start_date TEXT,
    notes_raw TEXT,
    notes_thread_json TEXT,
    description_raw TEXT,
    number_applied INTEGER,
    post_size TEXT,
    is_multi_job INTEGER DEFAULT 0,
    parent_post_id TEXT,
    fetch_status TEXT DEFAULT 'ok',
    scraped_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_apply_by ON jobs(apply_by);
CREATE INDEX IF NOT EXISTS idx_jobs_posted_at ON jobs(posted_at);
CREATE INDEX IF NOT EXISTS idx_jobs_url_norm ON jobs(url_normalized);
CREATE INDEX IF NOT EXISTS idx_jobs_scraped_at ON jobs(scraped_at);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def normalize_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = url.strip().rstrip("/")
    try:
        p = urlparse(url)
        qs = parse_qs(p.query, keep_blank_values=True)
        for key in list(qs.keys()):
            if key.lower().startswith("utm_") or key in ("rcm", "pagetype"):
                del qs[key]
        query = urlencode({k: v[0] for k, v in qs.items()}, doseq=False) if qs else ""
        return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", query, ""))
    except Exception:
        return url.lower()


def make_id(*parts: str) -> str:
    raw = "|".join(p for p in parts if p)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@contextmanager
def connect():
    conn = sqlite3.connect(db_path(), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)
        from jobboards.geocode import init_geo_schema
        from jobboards.user_data import init_user_schema
        init_geo_schema(conn)
        init_user_schema(conn)


def clear_source(conn: sqlite3.Connection, source: str):
    conn.execute("DELETE FROM jobs WHERE source = ?", (source,))


def purge_stale(conn: sqlite3.Connection, source: str, scrape_started: str):
    """Remove listings not updated in the current scrape batch."""
    conn.execute(
        "DELETE FROM jobs WHERE source = ? AND scraped_at < ?",
        (source, scrape_started),
    )


def upsert_job(conn: sqlite3.Connection, job: dict[str, Any]):
    cols = [
        "id", "source", "source_tab", "source_slug", "institution", "location",
        "subject_area", "rank_or_pi", "position_type", "title", "url", "url_normalized",
        "urls_json", "contact_email", "posted_at", "apply_by", "updated_at", "start_date",
        "notes_raw", "notes_thread_json", "description_raw", "number_applied", "post_size",
        "is_multi_job", "parent_post_id", "fetch_status", "scraped_at",
    ]
    values = [job.get(c) for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")
    conn.execute(
        f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        values,
    )


def set_meta(key: str, value: str):
    with connect() as conn:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def get_meta(key: str, default: Optional[str] = None) -> Optional[str]:
    with connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


LIST_JOB_COLUMNS = (
    "id", "source", "source_tab", "source_slug", "institution", "location",
    "subject_area", "rank_or_pi", "position_type", "title", "url", "url_normalized",
    "contact_email", "posted_at", "apply_by", "updated_at", "start_date",
    "notes_thread_json", "number_applied", "post_size",
    "is_multi_job", "parent_post_id", "fetch_status", "scraped_at",
)


def row_to_dict(row: sqlite3.Row, *, parse_notes: bool = True) -> dict[str, Any]:
    d = dict(row)
    notes_raw = d.get("notes_raw")
    if parse_notes and notes_raw:
        d["notes_thread"] = parse_notes_thread(notes_raw)
    elif notes_raw and re.search(r"(?<=\S)\s+(?:\d+|OP)\)\s*", notes_raw):
        d["notes_thread"] = parse_notes_thread(notes_raw)
    elif d.get("notes_thread_json"):
        try:
            d["notes_thread"] = json.loads(d["notes_thread_json"])
        except json.JSONDecodeError:
            d["notes_thread"] = []
    else:
        d["notes_thread"] = []
    d["has_notes_thread"] = bool(d.pop("has_notes_thread", 0))
    if d.get("urls_json"):
        try:
            d["urls"] = json.loads(d["urls_json"])
        except json.JSONDecodeError:
            d["urls"] = []
    d["is_multi_job"] = bool(d.get("is_multi_job"))
    return d


def list_jobs(
    source: Optional[str] = None,
    search: Optional[str] = None,
    terms: Optional[list[str]] = None,
    sort: str = "posted_at",
    order: str = "desc",
    limit: Optional[int] = None,
    date_field: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    view: str = "all",
) -> list[dict[str, Any]]:
    from jobboards.user_data import get_dismissed_job_ids, get_saved_job_ids

    allowed_sort = {"apply_by", "posted_at", "updated_at", "institution"}
    sort_col = sort if sort in allowed_sort else "apply_by"
    order_sql = "DESC" if order.lower() == "desc" else "ASC"

    clauses = []
    params: list[Any] = []
    if source and source != "all":
        clauses.append("source = ?")
        params.append(source)

    if view == "saved":
        saved_ids = get_saved_job_ids()
        if not saved_ids:
            return []
        placeholders = ", ".join("?" for _ in saved_ids)
        clauses.append(f"id IN ({placeholders})")
        params.extend(saved_ids)
        dismissed_ids = get_dismissed_job_ids()
        if dismissed_ids:
            placeholders = ", ".join("?" for _ in dismissed_ids)
            clauses.append(f"id NOT IN ({placeholders})")
            params.extend(dismissed_ids)
    elif view == "dismissed":
        dismissed_ids = get_dismissed_job_ids()
        if not dismissed_ids:
            return []
        placeholders = ", ".join("?" for _ in dismissed_ids)
        clauses.append(f"id IN ({placeholders})")
        params.extend(dismissed_ids)
    else:
        dismissed_ids = get_dismissed_job_ids()
        if dismissed_ids:
            placeholders = ", ".join("?" for _ in dismissed_ids)
            clauses.append(f"id NOT IN ({placeholders})")
            params.extend(dismissed_ids)

    all_terms: list[str] = []
    if terms:
        all_terms.extend(t.strip() for t in terms if t and t.strip())
    if search and search.strip():
        s = search.strip()
        if s.lower() not in {t.lower() for t in all_terms}:
            all_terms.insert(0, s)

    for term in all_terms:
        q = f"%{term.lower()}%"
        clauses.append(
            "(LOWER(institution) LIKE ? OR LOWER(subject_area) LIKE ? OR "
            "LOWER(title) LIKE ? OR LOWER(location) LIKE ? OR LOWER(notes_raw) LIKE ? OR "
            "LOWER(description_raw) LIKE ?)"
        )
        params.extend([q] * 6)

    if date_field in {"posted_at", "apply_by"} and (date_from or date_to):
        clauses.append(f"({date_field} IS NOT NULL AND {date_field} != '')")
        if date_field == "posted_at":
            if date_from:
                clauses.append(f"substr({date_field}, 1, 10) >= ?")
                params.append(date_from)
            if date_to:
                clauses.append(f"substr({date_field}, 1, 10) <= ?")
                params.append(date_to)
        else:
            if date_from:
                clauses.append(f"{date_field} >= ?")
                params.append(date_from)
            if date_to:
                clauses.append(f"{date_field} <= ?")
                params.append(date_to)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cols = ", ".join(LIST_JOB_COLUMNS)
    sql = f"""
        SELECT {cols},
            CASE WHEN notes_raw IS NOT NULL AND (
                notes_raw LIKE '% OP)%' OR notes_raw LIKE '% 2)%'
            ) THEN 1 ELSE 0 END AS has_notes_thread
        FROM jobs {where}
        ORDER BY
            CASE WHEN {sort_col} IS NULL OR {sort_col} = '' THEN 1 ELSE 0 END,
            {sort_col} {order_sql}
    """
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    jobs = [row_to_dict(r, parse_notes=False) for r in rows]
    _attach_merge_info(jobs)
    return jobs


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return None
    job = row_to_dict(row)
    _attach_merge_info([job])
    return job


def _attach_merge_info(jobs: list[dict[str, Any]]):
    url_map: dict[str, set[str]] = {}
    for job in jobs:
        norm = job.get("url_normalized")
        if norm:
            url_map.setdefault(norm, set()).add(job["source"])

    for job in jobs:
        norm = job.get("url_normalized")
        sources = {job["source"]}
        if norm and norm in url_map:
            sources = url_map[norm]
        job["sources"] = sorted(sources)


def job_stats(since: Optional[str] = None) -> dict[str, Any]:
    with connect() as conn:
        if since:
            row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN scraped_at >= ? THEN 1 ELSE 0 END) AS total,
                    SUM(CASE WHEN source = 'ecoevojobs' AND scraped_at >= ? THEN 1 ELSE 0 END) AS ecoevo,
                    SUM(CASE WHEN source = 'evoldir' AND scraped_at >= ? THEN 1 ELSE 0 END) AS evoldir,
                    SUM(CASE WHEN source = 'sciencecareers' AND scraped_at >= ? THEN 1 ELSE 0 END) AS sciencecareers,
                    SUM(CASE WHEN apply_by IS NOT NULL AND apply_by != '' AND scraped_at >= ? THEN 1 ELSE 0 END) AS with_deadline
                FROM jobs
                """,
                (since, since, since, since, since),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN source = 'ecoevojobs' THEN 1 ELSE 0 END) AS ecoevo,
                    SUM(CASE WHEN source = 'evoldir' THEN 1 ELSE 0 END) AS evoldir,
                    SUM(CASE WHEN source = 'sciencecareers' THEN 1 ELSE 0 END) AS sciencecareers,
                    SUM(CASE WHEN apply_by IS NOT NULL AND apply_by != '' THEN 1 ELSE 0 END) AS with_deadline
                FROM jobs
                """
            ).fetchone()
        last = conn.execute("SELECT value FROM meta WHERE key = 'last_fetched_at'").fetchone()
    return {
        "total": row["total"] or 0,
        "ecoevojobs": row["ecoevo"] or 0,
        "evoldir": row["evoldir"] or 0,
        "sciencecareers": row["sciencecareers"] or 0,
        "with_deadline": row["with_deadline"] or 0,
        "last_fetched_at": last["value"] if last else None,
    }


def job_date_bounds() -> dict[str, Any]:
    with connect() as conn:
        posted = conn.execute(
            """
            SELECT MIN(posted_at) AS mn, MAX(posted_at) AS mx
            FROM jobs WHERE posted_at IS NOT NULL AND posted_at != ''
            """
        ).fetchone()
        apply = conn.execute(
            """
            SELECT MIN(apply_by) AS mn, MAX(apply_by) AS mx
            FROM jobs WHERE apply_by IS NOT NULL AND apply_by != ''
            """
        ).fetchone()
        posted_daily = conn.execute(
            """
            SELECT substr(posted_at, 1, 10) AS day, COUNT(*) AS cnt
            FROM jobs
            WHERE posted_at IS NOT NULL AND posted_at != ''
            GROUP BY substr(posted_at, 1, 10)
            ORDER BY day
            """
        ).fetchall()
        apply_daily = conn.execute(
            """
            SELECT apply_by AS day, COUNT(*) AS cnt
            FROM jobs
            WHERE apply_by IS NOT NULL AND apply_by != ''
            GROUP BY apply_by
            ORDER BY apply_by
            """
        ).fetchall()

    def _day_part(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        return value[:10]

    def _daily_rows(rows) -> list[dict[str, int | str]]:
        return [{"day": r["day"], "count": r["cnt"]} for r in rows]

    return {
        "posted_at": {
            "min": _day_part(posted["mn"]),
            "max": _day_part(posted["mx"]),
            "daily": _daily_rows(posted_daily),
        },
        "apply_by": {
            "min": apply["mn"],
            "max": apply["mx"],
            "daily": _daily_rows(apply_daily),
        },
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
