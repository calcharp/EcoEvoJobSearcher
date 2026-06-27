"""Job posting preview helpers for static export."""

from typing import Optional

from jobboards.config import EVOLDIR_DETAIL_BASE


def preview_target(job: dict) -> tuple[Optional[str], Optional[str]]:
    """Return (fetch_url, open_url) for the job posting preview."""
    open_url = job.get("url")
    fetch_url = open_url

    if job.get("source") == "evoldir" and job.get("source_slug"):
        evoldir_url = EVOLDIR_DETAIL_BASE + job["source_slug"]
        fetch_url = evoldir_url
        open_url = open_url or evoldir_url

    return fetch_url, open_url


def can_preview(job: dict) -> bool:
    fetch_url, _ = preview_target(job)
    return bool(fetch_url or job.get("description_raw"))
