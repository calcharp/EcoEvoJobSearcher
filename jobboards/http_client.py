"""HTTP helpers with browser impersonation for bot-sensitive sites."""

from __future__ import annotations

import time
from typing import Optional

import requests

from jobboards.config import HTTP_HEADERS, http_timeout, is_github_actions

_IMPERSONATE = "chrome131"
_RETRYABLE = {403, 429, 500, 502, 503, 504}


def fetch_text(
    url: str,
    *,
    session: Optional[requests.Session] = None,
    headers: Optional[dict[str, str]] = None,
    timeout: Optional[float] = None,
    referer: Optional[str] = None,
) -> str:
    timeout = timeout if timeout is not None else http_timeout()
    req_headers = dict(headers or HTTP_HEADERS)
    if referer:
        req_headers["Referer"] = referer
    req_headers.setdefault(
        "Accept",
        "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    )

    errors: list[str] = []
    for attempt in range(3):
        try:
            return _fetch_once(
                url,
                session=session,
                headers=req_headers,
                timeout=timeout,
            )
        except Exception as exc:
            errors.append(str(exc))
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status not in _RETRYABLE and attempt == 0 and not is_github_actions():
                break
            if attempt < 2:
                time.sleep(0.75 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {'; '.join(errors[-3:])}")


def _fetch_once(
    url: str,
    *,
    session: Optional[requests.Session],
    headers: dict[str, str],
    timeout: float,
) -> str:
    try:
        from curl_cffi import requests as curl_requests

        resp = curl_requests.get(
            url,
            headers=headers,
            timeout=timeout,
            impersonate=_IMPERSONATE,
        )
        resp.raise_for_status()
        return resp.text
    except ImportError:
        if is_github_actions():
            raise RuntimeError(
                "curl_cffi is required on GitHub Actions to scrape Science Careers"
            ) from None

    if session is not None:
        resp = session.get(url, headers=headers, timeout=timeout)
    else:
        resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text
