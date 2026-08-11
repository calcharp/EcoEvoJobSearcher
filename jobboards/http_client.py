"""HTTP helpers with browser impersonation for bot-sensitive sites."""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

import requests

from jobboards.config import HTTP_HEADERS, http_timeout, is_github_actions

_IMPERSONATE_CANDIDATES = (
    "chrome131",
    "chrome124",
    "chrome120",
    "chrome116",
    "safari17_0",
)
_RETRYABLE = {403, 429, 500, 502, 503, 504}

_BROWSER_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-CH-UA": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": HTTP_HEADERS["User-Agent"],
}

_thread_local = threading.local()
_warmup_lock = threading.Lock()
_warmed_origins: set[str] = set()


def _proxy_url() -> Optional[str]:
    return (
        os.environ.get("SCIENCE_CAREERS_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or None
    )


def _proxy_dict() -> Optional[dict[str, str]]:
    proxy = _proxy_url()
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def fetch_text(
    url: str,
    *,
    session: Optional[requests.Session] = None,
    headers: Optional[dict[str, str]] = None,
    timeout: Optional[float] = None,
    referer: Optional[str] = None,
    warmup_origin: Optional[str] = None,
) -> str:
    timeout = timeout if timeout is not None else http_timeout()
    req_headers = dict(_BROWSER_HEADERS)
    req_headers.update(headers or {})
    if referer:
        req_headers["Referer"] = referer
        req_headers["Sec-Fetch-Site"] = "same-origin"
    else:
        req_headers["Sec-Fetch-Site"] = "none"

    if warmup_origin:
        _warmup(warmup_origin, timeout=timeout)

    errors: list[str] = []
    for attempt in range(3):
        try:
            return _fetch_once(
                url,
                session=session,
                headers=req_headers,
                timeout=timeout,
                impersonate=_IMPERSONATE_CANDIDATES[attempt % len(_IMPERSONATE_CANDIDATES)],
            )
        except Exception as exc:
            errors.append(str(exc))
            status = _error_status(exc)
            if status not in _RETRYABLE and attempt == 0 and not is_github_actions():
                break
            if attempt < 2:
                time.sleep(1.25 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {'; '.join(errors[-3:])}")


def _error_status(exc: Exception) -> Optional[int]:
    resp = getattr(exc, "response", None)
    if resp is not None:
        return getattr(resp, "status_code", None)
    text = str(exc)
    for code in _RETRYABLE:
        if str(code) in text:
            return code
    return None


def _warmup(origin: str, *, timeout: float) -> None:
    origin = origin.rstrip("/")
    with _warmup_lock:
        if origin in _warmed_origins:
            return
        try:
            _fetch_once(
                origin + "/",
                session=None,
                headers={
                    **_BROWSER_HEADERS,
                    "Sec-Fetch-Site": "none",
                    "Referer": "",
                },
                timeout=timeout,
                impersonate=_IMPERSONATE_CANDIDATES[0],
            )
        except Exception:
            # Warmup is best-effort; listing fetch still retries.
            pass
        _warmed_origins.add(origin)


def _curl_session(impersonate: str):
    key = f"curl:{impersonate}:{_proxy_url() or ''}"
    sessions = getattr(_thread_local, "curl_sessions", None)
    if sessions is None:
        sessions = {}
        _thread_local.curl_sessions = sessions
    sess = sessions.get(key)
    if sess is not None:
        return sess
    from curl_cffi import requests as curl_requests

    sess = curl_requests.Session(impersonate=impersonate)
    proxy = _proxy_url()
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    sessions[key] = sess
    return sess


def _fetch_once(
    url: str,
    *,
    session: Optional[requests.Session],
    headers: dict[str, str],
    timeout: float,
    impersonate: str,
) -> str:
    try:
        curl_session = _curl_session(impersonate)
        resp = curl_session.get(
            url,
            headers={k: v for k, v in headers.items() if v},
            timeout=timeout,
            allow_redirects=True,
        )
        resp.raise_for_status()
        return resp.text
    except ImportError:
        if is_github_actions():
            raise RuntimeError(
                "curl_cffi is required on GitHub Actions to scrape Science Careers"
            ) from None

    req_headers = {k: v for k, v in headers.items() if v}
    proxies = _proxy_dict()
    if session is not None:
        resp = session.get(url, headers=req_headers, timeout=timeout, proxies=proxies)
    else:
        resp = requests.get(url, headers=req_headers, timeout=timeout, proxies=proxies)
    resp.raise_for_status()
    return resp.text
