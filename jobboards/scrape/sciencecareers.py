import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import unescape
from typing import Any, Optional
from urllib.parse import urljoin

import requests

from jobboards.config import (
    HTTP_HEADERS,
    SCIENCE_CAREERS_BASE,
    SCIENCE_CAREERS_PARALLEL_WORKERS,
    http_timeout,
    science_careers_fetch_details,
)
from jobboards.dates import parse_sciencecareers_closing
from jobboards.db import make_id, normalize_url, upsert_job

SESSION = requests.Session()
SESSION.headers.update(HTTP_HEADERS)

ITEM_RE = re.compile(
    r'<li class="lister__item[^"]*" id="item-(\d+)">(.*?<ul class="job-actions.*?</ul>)',
    re.S | re.I,
)
TITLE_RE = re.compile(r'lister__header.*?<span>([^<]+)</span>', re.S | re.I)
HREF_RE = re.compile(r'href="\s*(/job/\d+/[^"]+)"', re.I)
LOCATION_RE = re.compile(r'lister__meta-item--location">([^<]+)', re.I)
SALARY_RE = re.compile(r'lister__meta-item--salary">([^<]+)', re.I)
RECRUITER_RE = re.compile(r'lister__meta-item--recruiter">([^<]+)', re.I)
DESC_RE = re.compile(r'lister__description[^>]*>([^<]+)', re.I)
JSON_LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S | re.I)
META_RE = re.compile(r'"([^"]+)":\s*"([^"]*)"')
CLOSING_RE = re.compile(r"Closing date</dt>\s*<dd[^>]*>\s*([^<]+)", re.I)


def _clean(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    text = unescape(re.sub(r"\s+", " ", text)).strip()
    return text or None


def _strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"\r", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _listing_url(page: int) -> str:
    if page <= 1:
        return f"{SCIENCE_CAREERS_BASE}/jobs/"
    return f"{SCIENCE_CAREERS_BASE}/jobs/{page}/"


def fetch_listing_page(page: int) -> str:
    resp = SESSION.get(_listing_url(page), timeout=http_timeout())
    resp.raise_for_status()
    return resp.text


def parse_listing_page(html: str) -> list[dict[str, str]]:
    listings = []
    for m in ITEM_RE.finditer(html):
        block = m.group(2)
        if "lister__item--ads" in m.group(0) or "lister__item--empty" in m.group(0):
            continue
        job_id = m.group(1)
        title_m = TITLE_RE.search(block)
        href_m = HREF_RE.search(block)
        if not title_m or not href_m:
            continue
        path = re.sub(r"\s+", "", href_m.group(1))
        listings.append({
            "job_id": job_id,
            "title": _clean(title_m.group(1)) or "",
            "path": path,
            "location": _clean(LOCATION_RE.search(block).group(1)) if LOCATION_RE.search(block) else "",
            "salary": _clean(SALARY_RE.search(block).group(1)) if SALARY_RE.search(block) else "",
            "institution": _clean(RECRUITER_RE.search(block).group(1)) if RECRUITER_RE.search(block) else "",
            "snippet": _clean(DESC_RE.search(block).group(1)) if DESC_RE.search(block) else "",
        })
    return listings


def fetch_all_listings() -> list[dict[str, str]]:
    page = 1
    seen: set[str] = set()
    all_listings: list[dict[str, str]] = []
    while True:
        html = fetch_listing_page(page)
        listings = parse_listing_page(html)
        if not listings:
            break
        for item in listings:
            if item["job_id"] not in seen:
                seen.add(item["job_id"])
                all_listings.append(item)
        if 'rel="next"' not in html:
            break
        page += 1
    return all_listings


def _parse_meta(html: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for m in META_RE.finditer(html):
        key, value = m.group(1), m.group(2)
        if key in ("Job Type", "Discipline", "Position Type", "JobDatePosted"):
            meta[key] = value
    return meta


def _parse_json_ld(html: str) -> Optional[dict[str, Any]]:
    for m in JSON_LD_RE.finditer(html):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if data.get("@type") == "JobPosting":
            return data
    return None


def fetch_job_detail(path: str) -> dict[str, Any]:
    url = urljoin(SCIENCE_CAREERS_BASE, path)
    resp = SESSION.get(url, timeout=http_timeout())
    resp.raise_for_status()
    html = resp.text
    ld = _parse_json_ld(html) or {}
    meta = _parse_meta(html)
    closing_m = CLOSING_RE.search(html)

    posted = ld.get("datePosted")
    apply_by = ld.get("validThrough")
    if apply_by and "T" in apply_by:
        apply_by = apply_by[:10]
    if closing_m:
        parsed = parse_sciencecareers_closing(closing_m.group(1))
        if parsed:
            apply_by = parsed

    description_html = ld.get("description") or ""
    description = _strip_html(description_html) if description_html else None

    discipline = meta.get("Discipline", "")
    subject = discipline.split(",")[0].strip() if discipline else None

    return {
        "posted_at": posted,
        "apply_by": apply_by,
        "description_raw": description,
        "subject_area": subject,
        "position_type": meta.get("Position Type") or meta.get("Job Type"),
        "fetch_status": "ok",
    }


def _build_job(
    listing: dict[str, str],
    detail: dict[str, Any],
    scraped_at: str,
) -> dict[str, Any]:
    path = listing["path"]
    url = urljoin(SCIENCE_CAREERS_BASE, path)
    job_id = listing["job_id"]
    institution = listing["institution"] or None
    title = listing["title"] or institution or "Science Careers listing"
    snippet = listing["snippet"]
    subject = detail.get("subject_area") or snippet or title

    notes_parts = []
    if listing.get("salary"):
        notes_parts.append(f"Salary: {listing['salary']}")
    if detail.get("position_type"):
        notes_parts.append(f"Type: {detail['position_type']}")

    return {
        "id": make_id("sciencecareers", job_id),
        "source": "sciencecareers",
        "source_tab": None,
        "source_slug": job_id,
        "institution": institution,
        "location": listing.get("location") or None,
        "subject_area": subject,
        "rank_or_pi": title if title != subject else None,
        "position_type": detail.get("position_type"),
        "title": title,
        "url": url,
        "url_normalized": normalize_url(url),
        "urls_json": None,
        "contact_email": None,
        "posted_at": detail.get("posted_at"),
        "apply_by": detail.get("apply_by"),
        "updated_at": None,
        "start_date": None,
        "notes_raw": "\n".join(notes_parts) if notes_parts else None,
        "notes_thread_json": None,
        "description_raw": detail.get("description_raw") or snippet,
        "number_applied": None,
        "post_size": None,
        "is_multi_job": 0,
        "parent_post_id": None,
        "fetch_status": detail.get("fetch_status", "ok"),
        "scraped_at": scraped_at,
    }


def _listing_only_detail(listing: dict[str, str]) -> dict[str, Any]:
    return {
        "posted_at": None,
        "apply_by": None,
        "description_raw": listing.get("snippet"),
        "subject_area": listing.get("snippet") or listing.get("title"),
        "position_type": None,
        "fetch_status": "listing_only",
    }


def _fetch_listing_detail(listing: dict[str, str]) -> tuple[dict[str, str], dict[str, Any]]:
    try:
        detail = fetch_job_detail(listing["path"])
    except Exception:
        detail = {"fetch_status": "error"}
    return listing, detail


def scrape_sciencecareers(
    conn,
    state=None,
    scraped_at: Optional[str] = None,
    listings: Optional[list[dict[str, str]]] = None,
) -> int:
    scraped_at = scraped_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if listings is None:
        listings = fetch_all_listings()

    total = len(listings)
    if state:
        state.update(
            sciencecareers_total=total,
            sciencecareers_done=0,
            message=f"Science Careers 0/{total}",
        )

    count = 0
    if not science_careers_fetch_details():
        for done, listing in enumerate(listings, start=1):
            job = _build_job(listing, _listing_only_detail(listing), scraped_at)
            upsert_job(conn, job)
            count += 1
            if done % 50 == 0:
                conn.commit()
            if state:
                state.update(
                    sciencecareers_done=done,
                    sciencecareers_count=count,
                    message=f"Science Careers {done}/{total} (listings only)",
                )
        conn.commit()
        return count

    workers = min(SCIENCE_CAREERS_PARALLEL_WORKERS, max(total, 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_listing_detail, item): item for item in listings}
        done = 0
        for future in as_completed(futures):
            listing, detail = future.result()
            job = _build_job(listing, detail, scraped_at)
            upsert_job(conn, job)
            count += 1
            done += 1
            if done % 25 == 0:
                conn.commit()
            if state:
                state.update(
                    sciencecareers_done=done,
                    sciencecareers_count=count,
                    message=f"Science Careers {done}/{total}",
                )
    conn.commit()
    return count
