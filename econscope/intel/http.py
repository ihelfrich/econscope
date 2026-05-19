"""Shared HTTP layer for the intel module.

Every external HTTP call from intel/ goes through this layer. It provides:

- Exponential backoff with jitter for transient failures (5xx, 429, network errors)
- Per-host rate-limit awareness (reads the `Retry-After` header, falls back to backoff)
- Optional file-cache for idempotent GETs (keyed by URL + headers)
- A single consistent user-agent (so we don't get banned for looking like a bot pool)
- Sane defaults for timeouts (45s connect, 45s read)

The point of this layer is that when the SEC, Wikidata, or GDELT briefly hiccup,
we don't lose hours of analysis. We retry with backoff and only surface an error
once the upstream has been unreachable for ~2 minutes.

The previous design used urllib.request directly, which silently raised on the
first 429 from Wikidata. That cost us a Burkle expansion during the Soho House
pull. This module exists so that doesn't happen again.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# ── Configuration ────────────────────────────────────────────────────────────

USER_AGENT = "ECONSCOPE-research/0.2 (ian.helfrich@barcelonagse.eu)"
DEFAULT_TIMEOUT = 45  # seconds
DEFAULT_MAX_RETRIES = 5
DEFAULT_INITIAL_BACKOFF = 1.5  # seconds
DEFAULT_BACKOFF_MULT = 2.0
DEFAULT_MAX_BACKOFF = 60.0
RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}

CACHE_ROOT = Path.home() / ".cache" / "econscope" / "http"


# ── Errors ────────────────────────────────────────────────────────────────────

class RetryableHTTPError(Exception):
    """Raised when all retries are exhausted but the failure is still transient.

    Distinct from a permanent error (e.g. 404 not found) so callers can decide
    whether to retry later, swap upstream, or fail loudly.
    """

    def __init__(self, url: str, status: int, message: str, attempts: int):
        super().__init__(f"{status} after {attempts} attempts: {url} ({message})")
        self.url = url
        self.status = status
        self.attempts = attempts


class PermanentHTTPError(Exception):
    """A 4xx (non-rate-limit) error that won't be helped by retrying."""

    def __init__(self, url: str, status: int, message: str):
        super().__init__(f"{status}: {url} ({message})")
        self.url = url
        self.status = status


# ── Cache layer ──────────────────────────────────────────────────────────────

def _cache_key(url: str, headers: Optional[dict] = None) -> str:
    """Stable key from URL + headers."""
    h = hashlib.sha1()
    h.update(url.encode("utf-8"))
    if headers:
        for k in sorted(headers):
            h.update(f"\n{k}={headers[k]}".encode("utf-8"))
    return h.hexdigest()


def _cache_path(key: str) -> Path:
    # Two-level sharding to keep directory sizes reasonable.
    return CACHE_ROOT / key[:2] / key[2:4] / f"{key}.gz"


def _cache_read(key: str, max_age_seconds: Optional[int]) -> Optional[bytes]:
    p = _cache_path(key)
    if not p.exists():
        return None
    if max_age_seconds is not None:
        age = time.time() - p.stat().st_mtime
        if age > max_age_seconds:
            return None
    try:
        with gzip.open(p, "rb") as f:
            return f.read()
    except Exception:
        return None


def _cache_write(key: str, data: bytes) -> None:
    p = _cache_path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        with gzip.open(p, "wb") as f:
            f.write(data)
    except Exception:
        # Cache failure should never break the actual fetch.
        pass


# ── Fetch ─────────────────────────────────────────────────────────────────────

@dataclass
class FetchResult:
    url: str
    status: int
    body: bytes
    headers: dict
    from_cache: bool
    attempts: int

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding, errors="replace")

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


def fetch(
    url: str,
    *,
    headers: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_backoff: float = DEFAULT_INITIAL_BACKOFF,
    backoff_mult: float = DEFAULT_BACKOFF_MULT,
    max_backoff: float = DEFAULT_MAX_BACKOFF,
    cache_max_age: Optional[int] = None,
    cache_force_refresh: bool = False,
) -> FetchResult:
    """Fetch a URL with retry, backoff, and optional file cache.

    Parameters
    ----------
    url : str
        The URL to fetch.
    headers : dict, optional
        Additional request headers. User-Agent is added automatically.
    timeout : float
        Per-attempt socket timeout in seconds.
    max_retries : int
        Maximum retry attempts. Total tries = max_retries (initial counts).
    initial_backoff : float
        Seconds to wait before the second attempt.
    backoff_mult : float
        Multiplier applied to backoff between attempts.
    max_backoff : float
        Upper bound on backoff (seconds), regardless of multiplier growth.
    cache_max_age : int, optional
        If set, read cached response when younger than this many seconds.
    cache_force_refresh : bool
        If True, skip cache read but still write fresh response to cache.

    Returns
    -------
    FetchResult
        Container with status, body, headers, attempts, from_cache flag.

    Raises
    ------
    RetryableHTTPError
        When all retries exhausted and last failure was transient (5xx, 429, network).
    PermanentHTTPError
        When the upstream returned a 4xx that won't be helped by retry.
    """
    req_headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    if headers:
        req_headers.update(headers)

    # Cache read
    cache_k = _cache_key(url, req_headers)
    if not cache_force_refresh and cache_max_age is not None:
        cached = _cache_read(cache_k, cache_max_age)
        if cached is not None:
            return FetchResult(
                url=url, status=200, body=cached, headers={}, from_cache=True, attempts=0
            )

    backoff = initial_backoff
    last_error: Optional[str] = None
    last_status = 0

    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                # Auto-decompress gzip
                if resp.headers.get("Content-Encoding") == "gzip":
                    try:
                        raw = gzip.decompress(raw)
                    except Exception:
                        pass

                result = FetchResult(
                    url=url, status=resp.status, body=raw,
                    headers=dict(resp.headers), from_cache=False, attempts=attempt,
                )
                if cache_max_age is not None:
                    _cache_write(cache_k, raw)
                return result

        except urllib.error.HTTPError as e:
            last_status = e.code
            last_error = e.reason
            # Read body before deciding whether to retry (some servers explain in body)
            try:
                err_body = e.read()
            except Exception:
                err_body = b""

            if e.code not in RETRYABLE_STATUSES:
                raise PermanentHTTPError(
                    url, e.code, f"{e.reason}: {err_body[:200].decode('utf-8', errors='replace')}"
                )

            # Respect Retry-After if present
            retry_after = e.headers.get("Retry-After") if e.headers else None
            if retry_after:
                try:
                    sleep_for = float(retry_after)
                except ValueError:
                    sleep_for = backoff
            else:
                sleep_for = backoff

        except (urllib.error.URLError, TimeoutError, ConnectionResetError) as e:
            last_status = 0
            last_error = str(e)
            sleep_for = backoff

        # Add jitter to avoid thundering herd on shared rate limits
        sleep_for = min(sleep_for + random.uniform(0, 0.5), max_backoff)
        if attempt < max_retries:
            time.sleep(sleep_for)
            backoff = min(backoff * backoff_mult, max_backoff)

    raise RetryableHTTPError(url, last_status, last_error or "unknown", max_retries)


def fetch_json(url: str, **kwargs) -> Any:
    """Convenience wrapper: fetch and parse JSON in one call."""
    headers = kwargs.pop("headers", {}) or {}
    headers.setdefault("Accept", "application/json")
    return fetch(url, headers=headers, **kwargs).json()


# ── Utilities ────────────────────────────────────────────────────────────────

def cache_size() -> dict:
    """Report cache size and entry count."""
    if not CACHE_ROOT.exists():
        return {"entries": 0, "bytes": 0, "path": str(CACHE_ROOT)}
    total = 0
    count = 0
    for p in CACHE_ROOT.rglob("*.gz"):
        try:
            total += p.stat().st_size
            count += 1
        except OSError:
            pass
    return {"entries": count, "bytes": total, "path": str(CACHE_ROOT)}


def cache_clear() -> int:
    """Delete the entire HTTP cache. Returns number of files removed."""
    if not CACHE_ROOT.exists():
        return 0
    n = 0
    for p in CACHE_ROOT.rglob("*.gz"):
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    return n
