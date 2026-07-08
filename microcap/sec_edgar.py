"""SEC EDGAR client: rate-limited, cached, provenance-friendly.

All raw JSON pulls are cached under data/raw/ so re-runs never re-hit EDGAR
unnecessarily (SPEC hard rule 7) and so any figure can be traced back to the
exact bytes it came from. Network errors retry with exponential backoff;
HTTP 4xx (including 404 for companies with no XBRL facts) are returned to the
caller as "no data" rather than crashing the run.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

from . import config

_last_request_ts = 0.0


def _throttle() -> None:
    """Block until we are allowed to make the next request (< SEC ceiling)."""
    global _last_request_ts
    min_gap = 1.0 / config.SEC_MAX_REQUESTS_PER_SEC
    now = time.monotonic()
    wait = min_gap - (now - _last_request_ts)
    if wait > 0:
        time.sleep(wait)
    _last_request_ts = time.monotonic()


_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": config.SEC_USER_AGENT,
                "Accept-Encoding": "gzip, deflate",
            }
        )
        _session = s
    return _session


def _fetch_json(url: str, cache_path: Path, *, refresh: bool = False) -> dict[str, Any] | None:
    """Fetch and cache a JSON document.

    Returns the parsed JSON, or None if the resource does not exist (404) or a
    non-retryable client error occurred. Raises on repeated network failure so
    the caller can decide whether a partial run is acceptable.
    """
    if cache_path.exists() and not refresh:
        # A cached empty-marker means "known-absent" — do not re-fetch.
        text = cache_path.read_text()
        if text == "":
            return None
        return json.loads(text)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    session = _get_session()

    backoff = 2.0
    last_err: Exception | None = None
    for attempt in range(config.SEC_MAX_RETRIES):
        _throttle()
        try:
            resp = session.get(url, timeout=config.SEC_TIMEOUT_SECONDS)
        except requests.RequestException as exc:  # network-level failure
            # A proxy/egress policy denial (403/407 on CONNECT) is not transient —
            # surface it immediately instead of burning retries.
            msg = str(exc)
            if "403 Forbidden" in msg or "407 " in msg or "Tunnel connection failed" in msg:
                raise PermissionError(
                    f"Access to {url} denied by egress policy ({exc}). "
                    "Run where SEC EDGAR (www.sec.gov, data.sec.gov) is reachable."
                ) from exc
            last_err = exc
            time.sleep(backoff)
            backoff *= 2
            continue

        if resp.status_code == 200:
            cache_path.write_text(resp.text)
            return resp.json()
        if resp.status_code == 404:
            cache_path.write_text("")  # remember absence
            return None
        if resp.status_code in (403, 407):
            # Egress-policy / access denial — do not retry or route around it.
            raise PermissionError(
                f"Access to {url} denied by policy (HTTP {resp.status_code}). "
                "Run where SEC EDGAR is reachable."
            )
        if 400 <= resp.status_code < 500:
            cache_path.write_text("")
            return None
        # 5xx — retry with backoff.
        last_err = requests.HTTPError(f"HTTP {resp.status_code} for {url}")
        time.sleep(backoff)
        backoff *= 2

    raise RuntimeError(f"Failed to fetch {url} after {config.SEC_MAX_RETRIES} tries: {last_err}")


def fetch_tickers_exchange(*, refresh: bool = False) -> dict[str, Any]:
    """The ticker/CIK/exchange master map (SPEC 3.1)."""
    cache = config.RAW_DIR / "company_tickers_exchange.json"
    data = _fetch_json(config.TICKERS_EXCHANGE_URL, cache, refresh=refresh)
    if data is None:
        raise RuntimeError("company_tickers_exchange.json unavailable — cannot build universe.")
    return data


def fetch_companyfacts(cik: int, *, refresh: bool = False) -> dict[str, Any] | None:
    """XBRL company facts for one CIK. None if EDGAR has no facts (404)."""
    cik10 = f"{int(cik):010d}"
    url = config.COMPANYFACTS_URL.format(cik10=cik10)
    cache = config.RAW_DIR / "companyfacts" / f"CIK{cik10}.json"
    return _fetch_json(url, cache, refresh=refresh)


def fetch_submissions(cik: int, *, refresh: bool = False) -> dict[str, Any] | None:
    """Filing history + metadata (SIC, addresses, form list) for one CIK."""
    cik10 = f"{int(cik):010d}"
    url = config.SUBMISSIONS_URL.format(cik10=cik10)
    cache = config.RAW_DIR / "submissions" / f"CIK{cik10}.json"
    return _fetch_json(url, cache, refresh=refresh)
