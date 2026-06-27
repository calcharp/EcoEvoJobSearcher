"""Deep links back to the original listing on each job source."""

from typing import Optional

from jobboards.config import (
    ECOEVO_FACULTY_GID,
    ECOEVO_POSTDOC_GID,
    ECOEVO_SHEET_ID,
    EVOLDIR_DETAIL_BASE,
)

ECOEVO_NOTES_COL = {"faculty": "J", "postdoc": "I"}


def ecoevo_sheet_gid(tab: Optional[str]) -> str:
    return ECOEVO_FACULTY_GID if tab == "faculty" else ECOEVO_POSTDOC_GID


def ecoevo_sheet_url(job: dict, *, focus_notes: bool = False) -> Optional[str]:
    """Link to the ecoevojobs Google Sheet row (Notes column when focus_notes)."""
    if job.get("source") != "ecoevojobs":
        return None
    tab = job.get("source_tab") or "faculty"
    gid = ecoevo_sheet_gid(tab)
    base = (
        f"https://docs.google.com/spreadsheets/d/{ECOEVO_SHEET_ID}/edit"
        f"?gid={gid}#gid={gid}"
    )
    row = (job.get("source_slug") or "").strip()
    if not row.isdigit():
        return base
    if focus_notes:
        col = ECOEVO_NOTES_COL.get(tab, "J")
        range_spec = f"{col}{row}"
    else:
        range_spec = f"A{row}"
    return f"{base}&range={range_spec}"


def evoldir_archive_url(job: dict) -> Optional[str]:
    slug = (job.get("source_slug") or "").strip()
    if job.get("source") != "evoldir" or not slug:
        return None
    return EVOLDIR_DETAIL_BASE + slug


def source_discussion_url(job: dict) -> Optional[str]:
    """Where users can read or add community discussion for this listing."""
    if job.get("source") == "ecoevojobs":
        return ecoevo_sheet_url(job, focus_notes=True)
    if job.get("source") == "evoldir":
        return evoldir_archive_url(job)
    return None


def source_discussion_links(siblings: list[dict]) -> list[dict[str, str]]:
    """Discussion/archive links for every source row sharing a posting URL."""
    links: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for s in siblings:
        url = source_discussion_url(s)
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        label = source_discussion_label(s)
        if not label:
            continue
        links.append({"url": url, "label": label, "source": s.get("source") or ""})
    order = {"ecoevojobs": 0, "evoldir": 1, "sciencecareers": 2}
    links.sort(key=lambda item: order.get(item["source"], 9))
    return links


def discussion_siblings_for_job(
    job: dict,
    source_rows_by_url: Optional[dict[str, list[dict]]] = None,
) -> list[dict]:
    """Collect per-source rows needed to build discussion links for a job."""
    norm = job.get("url_normalized")
    siblings: list[dict] = list((source_rows_by_url or {}).get(norm or "", []))
    primary = {
        "source": job.get("source"),
        "source_tab": job.get("source_tab"),
        "source_slug": job.get("source_slug"),
    }
    replaced = False
    for i, s in enumerate(siblings):
        if s.get("source") == primary["source"]:
            siblings[i] = {
                **s,
                "source_tab": primary.get("source_tab") or s.get("source_tab"),
                "source_slug": primary.get("source_slug") or s.get("source_slug"),
            }
            replaced = True
            break
    if not replaced and primary.get("source"):
        siblings.append(primary)
    if not siblings and primary.get("source"):
        siblings = [primary]
    return siblings


def source_discussion_label(job: dict) -> Optional[str]:
    if job.get("source") == "ecoevojobs":
        return "Discuss on ecoevojobs"
    if job.get("source") == "evoldir":
        return "View on EvolDir"
    return None
