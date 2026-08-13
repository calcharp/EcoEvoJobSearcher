"""Scrape ecoevojobs.net Google Sheets with discovery + header-based parsing."""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from typing import Any, Iterator, Optional
from urllib.parse import urlparse

import requests

from jobboards.config import (
    ECOEVO_ARCHIVE_SHEET_IDS,
    ECOEVO_FACULTY_GID,
    ECOEVO_HUB_URL,
    ECOEVO_POSTDOC_GID,
    ECOEVO_SHEET_ID,
    HTTP_HEADERS,
    http_timeout,
)
from jobboards.dates import parse_ecoevo_date, parse_ecoevo_datetime
from jobboards.db import get_meta, make_id, normalize_url, upsert_job

SESSION = requests.Session()
SESSION.headers.update(HTTP_HEADERS)

SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
TAB_PUSH_RE = re.compile(
    r'items\.push\(\{name:\s*"((?:\\.|[^"\\])*)".*?gid=(\d+)',
    re.DOTALL,
)

# Header aliases: first match wins left-to-right across columns.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "timestamp": ("add job timestamp", "timestamp"),
    "institution": ("institution",),
    "location": ("location",),
    "subject": ("subject area", "subject"),
    "pi": ("pi", "advisor", "supervisor"),
    "review": ("review date", "deadline", "apply by", "closing date"),
    "url": ("url", "link"),
    "rank": ("rank",),
    "position_type": ("position type",),
    "last_update": ("last update", "last updated"),
    "notes": ("notes",),
    "number_applied": ("number applied", "# applied", "num applied"),
}


def _timeout() -> float:
    return max(http_timeout(), 30)


def discover_sheet_id(hub_url: str = ECOEVO_HUB_URL) -> str:
    """Resolve the live workbook ID from ecoevojobs.net (season rollovers)."""
    try:
        resp = SESSION.get(hub_url, timeout=_timeout(), allow_redirects=True)
        resp.raise_for_status()
        candidates = SHEET_ID_RE.findall(resp.url or "") + SHEET_ID_RE.findall(resp.text or "")
        for sheet_id in candidates:
            if sheet_id and sheet_id != "edit":
                return sheet_id
    except Exception:
        pass
    return ECOEVO_SHEET_ID


def _unescape_js_string(value: str) -> str:
    return value.replace("\\/", "/").replace('\\"', '"').replace("\\n", "\n")


def discover_tabs(sheet_id: str) -> list[tuple[str, str]]:
    """Return [(tab_name, gid), ...] from the spreadsheet htmlview page."""
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/htmlview"
    resp = SESSION.get(url, timeout=_timeout())
    resp.raise_for_status()
    tabs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_name, gid in TAB_PUSH_RE.findall(resp.text or ""):
        if gid in seen:
            continue
        seen.add(gid)
        tabs.append((_unescape_js_string(raw_name), gid))
    return tabs


def _pick_tab(tabs: list[tuple[str, str]], kind: str, fallback_gid: str) -> tuple[str, str]:
    for name, gid in tabs:
        low = name.lower()
        if kind == "faculty":
            if "postdoc" in low:
                continue
            if "faculty" in low or "permanent" in low:
                return name, gid
        elif kind == "postdoc":
            if "postdoc" in low:
                return name, gid
    return "unknown", fallback_gid


def resolve_job_tabs(sheet_id: str) -> dict[str, str]:
    """Map logical tab keys -> gid, discovering names when possible."""
    tabs: list[tuple[str, str]] = []
    try:
        tabs = discover_tabs(sheet_id)
    except Exception:
        tabs = []

    faculty_name, faculty_gid = _pick_tab(tabs, "faculty", ECOEVO_FACULTY_GID)
    postdoc_name, postdoc_gid = _pick_tab(tabs, "postdoc", ECOEVO_POSTDOC_GID)

    if not tabs:
        faculty_gid, postdoc_gid = ECOEVO_FACULTY_GID, ECOEVO_POSTDOC_GID

    return {
        "faculty": faculty_gid,
        "postdoc": postdoc_gid,
        "faculty_name": faculty_name,
        "postdoc_name": postdoc_name,
    }


def _export_csv_url(sheet_id: str, gid: str) -> str:
    return (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        f"/gviz/tq?tqx=out:csv&gid={gid}"
    )


def _norm_header_cell(raw: str) -> str:
    text = (raw or "").replace("\xa0", " ").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _header_matches(norm: str, alias: str) -> bool:
    if norm == alias:
        return True
    # Description cells often end with the real column label, e.g. "... Institution".
    if norm.endswith(" " + alias) or norm.endswith(alias):
        return True
    return False


def map_headers(headers: list[str]) -> dict[str, int]:
    """Map logical field -> column index using header aliases."""
    norms = [_norm_header_cell(h) for h in headers]
    mapping: dict[str, int] = {}
    used: set[int] = set()
    for field, aliases in FIELD_ALIASES.items():
        for idx, norm in enumerate(norms):
            if idx in used or not norm:
                continue
            if any(_header_matches(norm, alias) for alias in aliases):
                mapping[field] = idx
                used.add(idx)
                break
    return mapping


def _cell(row: list[str], mapping: dict[str, int], field: str) -> str:
    idx = mapping.get(field)
    if idx is None or idx >= len(row):
        return ""
    return (row[idx] or "").strip()


def _col_letter(index: int) -> str:
    """0-based index -> Excel-style column letter (supports > Z)."""
    n = index + 1
    letters = []
    while n:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(65 + rem))
    return "".join(reversed(letters))


def _parse_row(
    row: list[str],
    mapping: dict[str, int],
    *,
    tab_name: str,
    scraped_at: str,
    sheet_row: int,
    sheet_id: str,
    gid: str,
) -> Optional[dict[str, Any]]:
    ts = _cell(row, mapping, "timestamp")
    posted = parse_ecoevo_datetime(ts)
    if not posted:
        return None

    institution = _cell(row, mapping, "institution")
    if not institution:
        return None

    url = _cell(row, mapping, "url")
    subject = _cell(row, mapping, "subject")
    location = _cell(row, mapping, "location")
    review = _cell(row, mapping, "review")
    last_up = _cell(row, mapping, "last_update")
    notes = _cell(row, mapping, "notes")
    source_slug = f"{sheet_id}/{gid}/{sheet_row}"

    if tab_name == "faculty":
        rank = _cell(row, mapping, "rank")
        pos_type = _cell(row, mapping, "position_type")
        num_raw = _cell(row, mapping, "number_applied")
        num = int(num_raw) if num_raw.isdigit() else None
        return {
            "id": make_id("ecoevojobs", "faculty", institution, url or ts, rank),
            "source": "ecoevojobs",
            "source_tab": "faculty",
            "source_slug": source_slug,
            "institution": institution,
            "location": location,
            "subject_area": subject,
            "rank_or_pi": rank or None,
            "position_type": pos_type or None,
            "title": rank or institution,
            "url": url or None,
            "url_normalized": normalize_url(url or None),
            "urls_json": None,
            "contact_email": None,
            "posted_at": posted,
            "apply_by": parse_ecoevo_date(review),
            "updated_at": parse_ecoevo_datetime(last_up),
            "start_date": None,
            "notes_raw": notes or None,
            "notes_thread_json": None,
            "description_raw": None,
            "number_applied": num,
            "post_size": None,
            "is_multi_job": 0,
            "parent_post_id": None,
            "fetch_status": "ok",
            "scraped_at": scraped_at,
        }

    pi = _cell(row, mapping, "pi")
    return {
        "id": make_id("ecoevojobs", "postdoc", institution, url or ts, pi),
        "source": "ecoevojobs",
        "source_tab": "postdoc",
        "source_slug": source_slug,
        "institution": institution,
        "location": location,
        "subject_area": subject,
        "rank_or_pi": pi or None,
        "position_type": "Postdoc",
        "title": pi or institution,
        "url": url or None,
        "url_normalized": normalize_url(url or None),
        "urls_json": None,
        "contact_email": None,
        "posted_at": posted,
        "apply_by": parse_ecoevo_date(review),
        "updated_at": parse_ecoevo_datetime(last_up),
        "start_date": None,
        "notes_raw": notes or None,
        "notes_thread_json": None,
        "description_raw": None,
        "number_applied": None,
        "post_size": None,
        "is_multi_job": 0,
        "parent_post_id": None,
        "fetch_status": "ok",
        "scraped_at": scraped_at,
    }


def iter_tab_jobs(
    sheet_id: str,
    gid: str,
    tab_name: str,
    scraped_at: str,
) -> Iterator[dict[str, Any]]:
    resp = SESSION.get(_export_csv_url(sheet_id, gid), timeout=_timeout())
    resp.raise_for_status()
    reader = csv.reader(io.StringIO(resp.text))
    headers = next(reader, None)
    if not headers:
        return
    mapping = map_headers(headers)
    if "timestamp" not in mapping or "institution" not in mapping:
        raise RuntimeError(
            f"ecoevojobs {tab_name} headers missing required columns "
            f"(have {list(mapping)}; raw={headers[:8]!r})"
        )

    for sheet_row, row in enumerate(reader, start=2):
        if not row or not any((c or "").strip() for c in row):
            continue
        job = _parse_row(
            row,
            mapping,
            tab_name=tab_name,
            scraped_at=scraped_at,
            sheet_row=sheet_row,
            sheet_id=sheet_id,
            gid=gid,
        )
        if job:
            yield job


def sheets_to_scrape() -> tuple[str, list[str]]:
    """Return (current_sheet_id, all_sheet_ids) including prior-season archives."""
    current = discover_sheet_id()
    ordered: list[str] = [current]
    seen = {current}

    archives = list(ECOEVO_ARCHIVE_SHEET_IDS)
    prev = get_meta("ecoevo_sheet_id")
    if prev and prev not in seen:
        archives.insert(0, prev)

    for sheet_id in archives:
        if sheet_id and sheet_id not in seen:
            seen.add(sheet_id)
            ordered.append(sheet_id)
    return current, ordered


def _persist_sheet_meta(
    conn,
    sheet_id: str,
    gids: dict[str, str],
    header_maps: dict[str, dict[str, int]],
    archive_ids: list[str],
) -> None:
    rows = [
        ("ecoevo_sheet_id", sheet_id),
        ("ecoevo_faculty_gid", gids["faculty"]),
        ("ecoevo_postdoc_gid", gids["postdoc"]),
        ("ecoevo_archive_sheet_ids", ",".join(archive_ids)),
    ]
    for tab in ("faculty", "postdoc"):
        notes_idx = header_maps.get(tab, {}).get("notes")
        if notes_idx is not None:
            rows.append((f"ecoevo_{tab}_notes_col", _col_letter(notes_idx)))
    for key, value in rows:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def _scrape_one_sheet(
    conn,
    sheet_id: str,
    scraped_at: str,
    *,
    state: Any = None,
    label: str = "ecoevojobs",
    count_start: int = 0,
) -> tuple[int, dict[str, str], dict[str, dict[str, int]]]:
    gids = resolve_job_tabs(sheet_id)
    count = count_start
    sheet_count = 0
    header_maps: dict[str, dict[str, int]] = {}

    for tab in ("faculty", "postdoc"):
        gid = gids[tab]
        if state:
            state.update(message=f"Downloading {label} {tab}…", phase="ecoevojobs")

        resp = SESSION.get(_export_csv_url(sheet_id, gid), timeout=_timeout())
        resp.raise_for_status()
        rows = list(csv.reader(io.StringIO(resp.text)))
        if not rows:
            continue
        mapping = map_headers(rows[0])
        header_maps[tab] = mapping
        if "timestamp" not in mapping or "institution" not in mapping:
            raise RuntimeError(
                f"ecoevojobs {tab} ({sheet_id[:8]}…) headers missing required columns "
                f"(have {list(mapping)}; raw={rows[0][:8]!r})"
            )

        for sheet_row, row in enumerate(rows[1:], start=2):
            if not row or not any((c or "").strip() for c in row):
                continue
            job = _parse_row(
                row,
                mapping,
                tab_name=tab,
                scraped_at=scraped_at,
                sheet_row=sheet_row,
                sheet_id=sheet_id,
                gid=gid,
            )
            if not job:
                continue
            upsert_job(conn, job)
            count += 1
            sheet_count += 1
            if state and (count == 1 or count % 25 == 0):
                state.update(
                    ecoevo_done=count,
                    ecoevo_total=max(count, sheet_count),
                    message=f"ecoevojobs {count}",
                )
            if count % 100 == 0:
                conn.commit()

    return sheet_count, gids, header_maps


def scrape_ecoevo(
    conn,
    state: Any = None,
    scraped_at: Optional[str] = None,
) -> int:
    scraped_at = scraped_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    current_id, sheet_ids = sheets_to_scrape()
    archives = [sid for sid in sheet_ids if sid != current_id]

    if state:
        host = urlparse(ECOEVO_HUB_URL).netloc or "ecoevojobs.net"
        extra = f" + {len(archives)} prior season{'s' if len(archives) != 1 else ''}" if archives else ""
        state.update(
            message=f"Downloading ecoevojobs ({host} → {current_id[:8]}…{extra})…",
            phase="ecoevojobs",
        )

    total = 0
    current_gids: dict[str, str] = {}
    current_headers: dict[str, dict[str, int]] = {}

    for idx, sheet_id in enumerate(sheet_ids):
        is_current = sheet_id == current_id
        label = "ecoevojobs" if is_current else f"ecoevojobs archive {idx}"
        try:
            n, gids, headers = _scrape_one_sheet(
                conn,
                sheet_id,
                scraped_at,
                state=state,
                label=label,
                count_start=total,
            )
        except Exception as exc:
            if is_current:
                raise
            # Prior-season sheet missing/blocked should not fail the whole scrape.
            if state:
                state.update(message=f"Skipping ecoevo archive {sheet_id[:8]}… ({exc})")
            continue
        total += n
        if is_current:
            current_gids, current_headers = gids, headers
        if state:
            state.update(ecoevo_total=total, ecoevo_done=total)

    if not current_gids:
        # Fallback if current somehow failed before raise — shouldn't happen.
        current_gids = resolve_job_tabs(current_id)

    _persist_sheet_meta(conn, current_id, current_gids, current_headers, archives)
    conn.commit()
    return total


def ecoevo_purge_is_safe(conn, new_count: int, scrape_started: str) -> tuple[bool, str]:
    """Avoid wiping the catalog on season rollover or a broken parse."""
    if new_count <= 0:
        return False, "ecoevojobs returned 0 rows; keeping previous listings"

    stale_row = conn.execute(
        "SELECT COUNT(*) AS n FROM jobs WHERE source = 'ecoevojobs' AND scraped_at < ?",
        (scrape_started,),
    ).fetchone()
    stale = int(stale_row["n"] or 0) if stale_row else 0
    if stale == 0:
        return True, ""

    total = new_count + stale
    # If purging would drop most of the ecoevo catalog, keep the older rows
    # (typical when the community opens a new season workbook).
    if total >= 100 and new_count < max(40, int(total * 0.45)):
        return (
            False,
            f"ecoevojobs would drop from {total} to {new_count} listings; "
            "skipping purge to keep prior-season rows",
        )
    return True, ""
