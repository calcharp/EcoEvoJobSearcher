import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import unquote

import requests

from jobboards.config import (
    EVOLDIR_DETAIL_BASE,
    EVOLDIR_INDEX,
    EVOLDIR_PARALLEL_WORKERS,
    HTTP_HEADERS,
    JOB_URL_PATTERNS,
    http_timeout,
)
from jobboards.dates import parse_deadline_from_slug, parse_deadline_from_text, parse_evoldir_posted
from jobboards.db import make_id, normalize_url, upsert_job

SESSION = requests.Session()
SESSION.headers.update(HTTP_HEADERS)

INDEX_PATTERN = re.compile(
    r'<a href="(/brian/evoldir/Jobs//[^"]+)">([^<]+)</a>\s+'
    r'([\d.]+\s*(?:bytes|KB))\s+'
    r'([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2})'
)

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")

JOB_TYPE_TOKENS = {
    "assistantprofessor": "Assistant Professor",
    "fullprofessor": "Full Professor",
    "facultyposition": "Faculty",
    "lecturer": "Lecturer",
    "resassist": "Research Assistant",
    "restech": "Research Technician",
    "labtech": "Lab Technician",
    "curator": "Curator",
    "postdoc": "Postdoc",
    "instructor": "Instructor",
    "teachingfaculty": "Teaching Faculty",
    "researcher": "Researcher",
    "director": "Director",
    "fellow": "Fellow",
}


def fetch_index() -> list[dict[str, str]]:
    resp = SESSION.get(EVOLDIR_INDEX, timeout=http_timeout())
    resp.raise_for_status()
    entries = []
    for m in INDEX_PATTERN.finditer(resp.text):
        href, slug, size, posted = m.groups()
        entries.append({
            "href": href,
            "slug": slug.strip(),
            "size": size.strip(),
            "posted_raw": posted.strip(),
        })
    return entries


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


def _remove_footer(text: str) -> str:
    return re.split(r"\(to subscribe/unsubscribe", text, maxsplit=1)[0].strip()


def _score_url(url: str) -> int:
    lower = url.lower()
    for i, pat in enumerate(JOB_URL_PATTERNS):
        if pat in lower:
            return 100 - i
    if "wordpress" in lower or "github" in lower:
        return 10
    return 50


def _pick_best_url(urls: list[str]) -> Optional[str]:
    if not urls:
        return None
    return max(urls, key=_score_url)


def _parse_slug(slug: str) -> dict[str, Optional[str]]:
    decoded = unquote(slug.replace("_", "."))
    parts = re.split(r"[._]", decoded)
    institution = parts[0] if parts else slug
    location = None
    rank = None
    subject = None

    for p in parts[1:]:
        low = p.lower()
        if low in ("usa", "germany", "canada", "uk", "france", "australia", "norway", "austria", "taiwan", "uae"):
            location = p
        elif any(tok in low for tok in JOB_TYPE_TOKENS):
            for tok, label in JOB_TYPE_TOKENS.items():
                if tok in low:
                    rank = label
                    break
        elif len(p) > 3 and p not in (institution,):
            subject = p if not subject else f"{subject} {p}"

    return {
        "institution": institution,
        "location": location,
        "rank_or_pi": rank,
        "subject_area": subject,
    }


def _extract_title(text: str) -> str:
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return "Job posting"
    first = lines[0]
    if len(first) > 200:
        first = first[:197] + "…"
    return first


def _split_multi_jobs(text: str, slug: str) -> list[str]:
    if re.search(r"\n---+\n", text) or slug.lower().startswith(("three.", "two.")):
        parts = re.split(r"\n---+\n", text)
        return [p.strip() for p in parts if p.strip()]
    return [text]


def fetch_detail(slug: str) -> tuple[str, str]:
    url = EVOLDIR_DETAIL_BASE + slug
    resp = SESSION.get(url, timeout=http_timeout())
    resp.raise_for_status()
    return url, resp.text


def parse_detail(
    slug: str,
    html: str,
    posted_raw: str,
    size: str,
    scraped_at: str,
    part_index: int = 0,
    parent_id: Optional[str] = None,
) -> dict[str, Any]:
    text = _remove_footer(_strip_html(html))
    meta = _parse_slug(slug)
    urls = list(dict.fromkeys(URL_RE.findall(text)))
    best_url = _pick_best_url(urls)
    emails = EMAIL_RE.findall(text)
    contact = emails[0] if emails and "evoldir" not in emails[0] and "mcmaster" not in emails[0] else None

    apply_by = parse_deadline_from_text(text) or parse_deadline_from_slug(slug)
    title = _extract_title(text)
    posted = parse_evoldir_posted(posted_raw)

    job_id = make_id("evoldir", slug, str(part_index))
    if parent_id is None and part_index == 0:
        parent_id = job_id

    return {
        "id": job_id,
        "source": "evoldir",
        "source_tab": None,
        "source_slug": slug,
        "institution": meta["institution"] or slug,
        "location": meta["location"] or "",
        "subject_area": meta["subject_area"] or "",
        "rank_or_pi": meta["rank_or_pi"],
        "position_type": meta["rank_or_pi"],
        "title": title,
        "url": best_url,
        "url_normalized": normalize_url(best_url),
        "urls_json": json.dumps(urls) if urls else None,
        "contact_email": contact,
        "posted_at": posted,
        "apply_by": apply_by,
        "updated_at": None,
        "start_date": None,
        "notes_raw": None,
        "notes_thread_json": "[]",
        "description_raw": text,
        "number_applied": None,
        "post_size": size,
        "is_multi_job": 1 if part_index > 0 or parent_id != job_id else 0,
        "parent_post_id": parent_id if parent_id != job_id else None,
        "fetch_status": "ok",
        "scraped_at": scraped_at,
    }


def _fetch_entry_jobs(entry: dict[str, str], scraped_at: str) -> list[dict[str, Any]]:
    slug = entry["slug"]
    try:
        _, html = fetch_detail(slug)
        text = _remove_footer(_strip_html(html))
        parts = _split_multi_jobs(text, slug)
        parent_id = make_id("evoldir", slug, "0")
        jobs: list[dict[str, Any]] = []
        for pi, part in enumerate(parts):
            part_html = html if len(parts) == 1 else f"<pre>{part}</pre>"
            job = parse_detail(
                slug, part_html, entry["posted_raw"], entry["size"], scraped_at,
                part_index=pi,
                parent_id=parent_id,
            )
            if len(parts) > 1:
                job["is_multi_job"] = 1
                job["description_raw"] = part
                job["title"] = _extract_title(part)
            jobs.append(job)
        return jobs
    except Exception:
        return [{
            "id": make_id("evoldir", slug, "err"),
            "source": "evoldir",
            "source_tab": None,
            "source_slug": slug,
            "institution": _parse_slug(slug)["institution"] or slug,
            "location": "",
            "subject_area": "",
            "rank_or_pi": None,
            "position_type": None,
            "title": slug,
            "url": None,
            "url_normalized": None,
            "urls_json": None,
            "contact_email": None,
            "posted_at": parse_evoldir_posted(entry["posted_raw"]),
            "apply_by": parse_deadline_from_slug(slug),
            "updated_at": None,
            "start_date": None,
            "notes_raw": None,
            "notes_thread_json": "[]",
            "description_raw": None,
            "number_applied": None,
            "post_size": entry["size"],
            "is_multi_job": 0,
            "parent_post_id": None,
            "fetch_status": "error",
            "scraped_at": scraped_at,
        }]


def scrape_evoldir(
    conn,
    state: Any = None,
    scraped_at: Optional[str] = None,
    max_jobs: Optional[int] = None,
    entries: Optional[list[dict[str, str]]] = None,
) -> int:
    scraped_at = scraped_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if entries is None:
        entries = fetch_index()
    if max_jobs:
        entries = entries[:max_jobs]

    total = len(entries)

    count = 0
    done = 0
    pending = 0
    workers = min(EVOLDIR_PARALLEL_WORKERS, max(total, 1))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_entry_jobs, entry, scraped_at): entry
            for entry in entries
        }
        for fut in as_completed(futures):
            jobs = fut.result()
            for job in jobs:
                upsert_job(conn, job)
                count += 1
            done += 1
            pending += 1
            if pending >= 5 or done == total:
                conn.commit()
                pending = 0
            if state and total and (done == 1 or done == total or done % 5 == 0):
                state.update(
                    evoldir_done=done,
                    message=f"EvolDir {done}/{total}",
                )

    conn.commit()
    return count
