import html
import re
from typing import Optional

import requests

from jobboards.config import EVOLDIR_DETAIL_BASE

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "JobBoards/0.1 (local academic job aggregator)"})


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


def render_preview(job: dict) -> tuple[str, int]:
    fetch_url, open_url = preview_target(job)

    if fetch_url:
        try:
            resp = SESSION.get(fetch_url, timeout=20)
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "")
            if "html" in content_type or resp.text.lstrip().startswith("<"):
                body = inject_base(resp.text, fetch_url)
            else:
                body = text_page(resp.text, title=open_url or fetch_url)
            return body, 200
        except requests.RequestException:
            if job.get("description_raw"):
                return description_page(job["description_raw"], open_url), 200
            return error_page(open_url or fetch_url), 502

    if job.get("description_raw"):
        return description_page(job["description_raw"], open_url), 200

    return error_page(None), 404


def inject_base(page_html: str, base_url: str) -> str:
    base_tag = f'<base target="_blank" href="{html.escape(base_url, quote=True)}">'
    if re.search(r"<head[^>]*>", page_html, re.I):
        return re.sub(r"(<head[^>]*>)", r"\1" + base_tag, page_html, count=1, flags=re.I)
    return (
        f"<!DOCTYPE html><html><head>{base_tag}"
        f'<meta charset="utf-8"></head><body>{page_html}</body></html>'
    )


def description_page(text: str, open_url: Optional[str]) -> str:
    link = ""
    if open_url:
        safe = html.escape(open_url, quote=True)
        link = f'<p style="margin:0 0 1rem"><a href="{safe}" target="_blank" rel="noopener">Open official posting ↗</a></p>'
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        "<style>body{font:14px/1.6 system-ui,sans-serif;margin:1rem;color:#1a1a1a;"
        "pre{white-space:pre-wrap;word-break:break-word;margin:0}a{color:#2563eb}</style>"
        "</head><body>"
        f"{link}<pre>{html.escape(text)}</pre></body></html>"
    )


def text_page(text: str, title: str) -> str:
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        "<style>body{font:14px/1.6 system-ui,sans-serif;margin:1rem;color:#1a1a1a;"
        "pre{white-space:pre-wrap;word-break:break-word;margin:0}</style>"
        "</head><body>"
        f"<pre>{html.escape(text)}</pre></body></html>"
    )


def error_page(open_url: Optional[str]) -> str:
    link = ""
    if open_url:
        link = (
            f'<p><a href="{html.escape(open_url, quote=True)}" target="_blank" rel="noopener">'
            "Open posting in browser ↗</a></p>"
        )
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        "<style>body{font:14px/1.6 system-ui,sans-serif;margin:1rem;color:#444;"
        "a{color:#2563eb}</style></head><body>"
        "<p>Could not load a preview for this posting.</p>"
        f"{link}</body></html>"
    )
