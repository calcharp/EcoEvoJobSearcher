import csv
import io
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

import requests

from jobboards.config import ECOEVO_FACULTY_GID, ECOEVO_POSTDOC_GID, ECOEVO_SHEET_ID
from jobboards.dates import parse_ecoevo_date, parse_ecoevo_datetime
from jobboards.db import make_id, normalize_url, upsert_job

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "JobBoards/0.1 (local academic job aggregator)"})


def _export_url(gid: str) -> str:
    return (
        f"https://docs.google.com/spreadsheets/d/{ECOEVO_SHEET_ID}"
        f"/export?format=csv&gid={gid}"
    )


def iter_tab_jobs(gid: str, tab_name: str, scraped_at: str) -> Iterator[dict[str, Any]]:
    resp = SESSION.get(_export_url(gid), timeout=120)
    resp.raise_for_status()
    reader = csv.reader(io.StringIO(resp.text))
    next(reader, None)
    next(reader, None)

    for row in reader:
        if not row or not row[0].strip():
            continue
        if not parse_ecoevo_datetime(row[0]):
            continue
        if tab_name == "faculty":
            job = _parse_faculty_row(row, scraped_at)
        else:
            job = _parse_postdoc_row(row, scraped_at)
        if job:
            yield job


def fetch_tab(gid: str, tab_name: str, scraped_at: str) -> list[dict[str, Any]]:
    return list(iter_tab_jobs(gid, tab_name, scraped_at))


def _parse_faculty_row(row: list[str], scraped_at: str) -> Optional[dict[str, Any]]:
    while len(row) < 12:
        row.append("")
    ts, institution, location, subject, review_date, url, rank, pos_type, last_up, notes = row[:10]
    number_applied = row[10] if len(row) > 10 else ""

    posted = parse_ecoevo_datetime(ts)
    if not institution.strip():
        return None

    num = int(number_applied.strip()) if number_applied.strip().isdigit() else None

    return {
        "id": make_id("ecoevojobs", "faculty", institution, url or ts, rank),
        "source": "ecoevojobs",
        "source_tab": "faculty",
        "source_slug": None,
        "institution": institution.strip(),
        "location": location.strip(),
        "subject_area": subject.strip(),
        "rank_or_pi": rank.strip() or None,
        "position_type": pos_type.strip() or None,
        "title": rank.strip() or institution.strip(),
        "url": url.strip() or None,
        "url_normalized": normalize_url(url.strip() or None),
        "urls_json": None,
        "contact_email": None,
        "posted_at": posted,
        "apply_by": parse_ecoevo_date(review_date),
        "updated_at": parse_ecoevo_datetime(last_up),
        "start_date": None,
        "notes_raw": notes.strip() or None,
        "notes_thread_json": None,
        "description_raw": None,
        "number_applied": num,
        "post_size": None,
        "is_multi_job": 0,
        "parent_post_id": None,
        "fetch_status": "ok",
        "scraped_at": scraped_at,
    }


def _parse_postdoc_row(row: list[str], scraped_at: str) -> Optional[dict[str, Any]]:
    while len(row) < 10:
        row.append("")
    ts, institution, location, subject, pi, review_date, url, last_up, notes = row[:9]

    posted = parse_ecoevo_datetime(ts)
    if not institution.strip():
        return None

    return {
        "id": make_id("ecoevojobs", "postdoc", institution, url or ts, pi),
        "source": "ecoevojobs",
        "source_tab": "postdoc",
        "source_slug": None,
        "institution": institution.strip(),
        "location": location.strip(),
        "subject_area": subject.strip(),
        "rank_or_pi": pi.strip() or None,
        "position_type": "Postdoc",
        "title": pi.strip() or institution.strip(),
        "url": url.strip() or None,
        "url_normalized": normalize_url(url.strip() or None),
        "urls_json": None,
        "contact_email": None,
        "posted_at": posted,
        "apply_by": parse_ecoevo_date(review_date),
        "updated_at": parse_ecoevo_datetime(last_up),
        "start_date": None,
        "notes_raw": notes.strip() or None,
        "notes_thread_json": None,
        "description_raw": None,
        "number_applied": None,
        "post_size": None,
        "is_multi_job": 0,
        "parent_post_id": None,
        "fetch_status": "ok",
        "scraped_at": scraped_at,
    }


def scrape_ecoevo(
    conn,
    state: Any = None,
    scraped_at: Optional[str] = None,
) -> int:
    scraped_at = scraped_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    count = 0
    known_total = 0

    for gid, tab in ((ECOEVO_FACULTY_GID, "faculty"), (ECOEVO_POSTDOC_GID, "postdoc")):
        if state:
            state.update(message=f"Downloading ecoevojobs {tab}…", phase="ecoevojobs")

        tab_count = 0
        for job in iter_tab_jobs(gid, tab, scraped_at):
            upsert_job(conn, job)
            count += 1
            tab_count += 1
            if state and (count == 1 or count % 25 == 0):
                state.update(
                    ecoevo_done=count,
                    ecoevo_total=max(known_total + tab_count, count),
                    message=f"ecoevojobs {count}",
                )
            if count % 100 == 0:
                conn.commit()

        known_total += tab_count
        if state:
            state.update(ecoevo_total=known_total, ecoevo_done=count)

    conn.commit()
    return count
