"""Build static RSS feeds for GitHub Pages."""

from __future__ import annotations

import html
import os
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


def site_origin() -> str:
    return (os.environ.get("SITE_ORIGIN") or "https://calcharp.github.io").rstrip("/")


def absolute_base(base_path: str) -> str:
    path = base_path or "/"
    if path in (".", "./"):
        path = "/EcoEvoJobSearcher/"
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"
    return f"{site_origin()}{path}"


def _xml(text: Any) -> str:
    return escape(str("" if text is None else text), {"\"": "&quot;", "'": "&apos;"})


def _rfc822(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        if "T" in iso:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(iso[:10]).replace(tzinfo=timezone.utc)
        return format_datetime(dt)
    except ValueError:
        return ""


def _posted_day(job: dict[str, Any]) -> str | None:
    raw = job.get("posted_at") or ""
    if not raw:
        return None
    return raw[:10]


def _is_open(job: dict[str, Any]) -> bool:
    days = job.get("days_until")
    return days is None or days >= 0


def _within_last_week(job: dict[str, Any], today: date | None = None) -> bool:
    day = _posted_day(job)
    if not day:
        return False
    today = today or date.today()
    cutoff = (today - timedelta(days=6)).isoformat()
    return cutoff <= day <= today.isoformat()


def _job_title(job: dict[str, Any]) -> str:
    return job.get("subject_area") or job.get("title") or job.get("institution") or "Job listing"


def _job_link(job: dict[str, Any], base: str) -> str:
    if job.get("url"):
        return str(job["url"])
    return f"{base}job.html?id={html.escape(str(job.get('id') or ''), quote=True)}"


def _job_summary(job: dict[str, Any]) -> str:
    bits = [
        job.get("institution"),
        job.get("location"),
        job.get("rank_or_pi") or job.get("position_type"),
    ]
    apply = job.get("apply_display") or job.get("apply_by")
    if apply and apply != "—":
        bits.append(f"Apply by {apply}")
    posted = job.get("posted_display")
    if posted and posted != "—":
        bits.append(f"Posted {posted}")
    return " · ".join(str(b) for b in bits if b)


def build_rss(
    jobs: list[dict[str, Any]],
    *,
    title: str,
    description: str,
    channel_link: str,
    base: str,
    built_at: str | None = None,
) -> str:
    last_build = _rfc822(built_at) or format_datetime(datetime.now(timezone.utc))
    items: list[str] = []
    for job in jobs:
        pub = _rfc822(job.get("posted_at") or job.get("updated_at"))
        job_id = str(job.get("id") or "")
        items.append(
            "    <item>\n"
            f"      <title>{_xml(_job_title(job))}</title>\n"
            f"      <link>{_xml(_job_link(job, base))}</link>\n"
            f"      <guid isPermaLink=\"false\">{_xml(job_id)}</guid>\n"
            + (f"      <pubDate>{_xml(pub)}</pubDate>\n" if pub else "")
            + f"      <description>{_xml(_job_summary(job))}</description>\n"
            "    </item>"
        )
    body = "\n".join(items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        "  <channel>\n"
        f"    <title>{_xml(title)}</title>\n"
        f"    <link>{_xml(channel_link)}</link>\n"
        f"    <description>{_xml(description)}</description>\n"
        f"    <lastBuildDate>{_xml(last_build)}</lastBuildDate>\n"
        "    <docs>https://www.rssboard.org/rss-specification</docs>\n"
        f"{body}\n"
        "  </channel>\n"
        "</rss>\n"
    )


def write_feeds(
    out_dir: Path,
    jobs: list[dict[str, Any]],
    *,
    base_path: str,
    built_at: str | None = None,
) -> dict[str, int]:
    base = absolute_base(base_path)
    open_jobs = [j for j in jobs if _is_open(j)]
    week_jobs = [j for j in open_jobs if _within_last_week(j)]

    week_xml = build_rss(
        week_jobs,
        title="Eco & Evo Jobs — New this Week",
        description="Open ecology & evolution jobs posted in the last 7 days.",
        channel_link=f"{base}index.html?open=1&recent=1&sort=posted_at&order=desc",
        base=base,
        built_at=built_at,
    )
    all_xml = build_rss(
        open_jobs,
        title="Eco & Evo Jobs — All time",
        description="All open ecology & evolution job listings.",
        channel_link=f"{base}index.html?open=1&sort=posted_at&order=desc",
        base=base,
        built_at=built_at,
    )

    (out_dir / "feed-week.xml").write_text(week_xml, encoding="utf-8")
    (out_dir / "feed-all.xml").write_text(all_xml, encoding="utf-8")
    return {"week": len(week_jobs), "all": len(open_jobs)}
