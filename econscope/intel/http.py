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

import email.utils
import gzip
import hashlib
import json
import os
import random
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import certifi

# ── Configuration ────────────────────────────────────────────────────────────

USER_AGENT = "ECONSCOPE-research/0.2 (ian.helfrich@barcelonagse.eu)"

# Some upstreams (treasury.gov, usaspending.gov) use cert chains the system
# Python doesn't always trust; certifi's bundle covers them.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
DEFAULT_TIMEOUT = 45  # seconds
DEFAULT_MAX_RETRIES = 5
DEFAULT_INITIAL_BACKOFF = 1.5  # seconds
DEFAULT_BACKOFF_MULT = 2.0
DEFAULT_MAX_BACKOFF = 60.0
RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}

# The longest Retry-After we are willing to sit and sleep through inside a
# single call. Anything longer is surfaced to the caller as RateLimitedError so
# it can checkpoint and come back, instead of blocking a worker for an hour.
DEFAULT_MAX_RETRY_AFTER_SLEEP = 120.0  # seconds

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


class RateLimitedError(Exception):
    """Upstream rate-limited us and asked us to wait longer than we will block.

    Carries the server's own Retry-After so the caller can checkpoint, persist
    what it has, and resume after `retry_after` seconds. This is deliberately
    NOT a subclass of RetryableHTTPError: retrying it immediately is exactly the
    wrong move, and inheriting would let existing `except RetryableHTTPError`
    handlers do that silently.
    """

    def __init__(self, url: str, retry_after: float, message: str = ""):
        super().__init__(
            f"429 rate limited: {url} (retry after {retry_after:.0f}s) {message}".strip()
        )
        self.url = url
        self.status = 429
        self.retry_after = retry_after


class PermanentHTTPError(Exception):
    """A 4xx (non-rate-limit) error that won't be helped by retrying."""

    def __init__(self, url: str, status: int, message: str):
        super().__init__(f"{status}: {url} ({message})")
        self.url = url
        self.status = status


# ── Rate-limit state ─────────────────────────────────────────────────────────

# When a host rate-limits us, every caller should back off — not just the one
# that happened to get the 429. Keyed by host -> monotonic time we may resume.
_COOLDOWN_LOCK = threading.Lock()
_HOST_RESUME_AT: dict = {}


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Parse a Retry-After header. RFC 7231 allows two forms.

    Returns seconds to wait, or None if unparseable. The HTTP-date form is not
    hypothetical — CourtListener and several others use it — and float() on it
    raises, which previously meant the header was silently discarded and we
    retried on the generic backoff instead of the one the server asked for.
    """
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def _host_of(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return url


def note_rate_limited(url: str, retry_after: float) -> None:
    """Record that `url`'s host is rate-limited for `retry_after` seconds."""
    host = _host_of(url)
    with _COOLDOWN_LOCK:
        resume = time.monotonic() + max(0.0, retry_after)
        if resume > _HOST_RESUME_AT.get(host, 0.0):
            _HOST_RESUME_AT[host] = resume


def cooldown_remaining(url: str) -> float:
    """Seconds remaining before this host should be contacted again."""
    host = _host_of(url)
    with _COOLDOWN_LOCK:
        return max(0.0, _HOST_RESUME_AT.get(host, 0.0) - time.monotonic())


def clear_cooldown(url: str) -> None:
    with _COOLDOWN_LOCK:
        _HOST_RESUME_AT.pop(_host_of(url), None)


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
    data: Optional[bytes] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_backoff: float = DEFAULT_INITIAL_BACKOFF,
    backoff_mult: float = DEFAULT_BACKOFF_MULT,
    max_backoff: float = DEFAULT_MAX_BACKOFF,
    cache_max_age: Optional[int] = None,
    cache_force_refresh: bool = False,
    max_retry_after_sleep: float = DEFAULT_MAX_RETRY_AFTER_SLEEP,
    respect_cooldown: bool = True,
) -> FetchResult:
    """Fetch a URL with retry, backoff, and optional file cache.

    Parameters
    ----------
    url : str
        The URL to fetch.
    headers : dict, optional
        Additional request headers. User-Agent is added automatically.
    data : bytes, optional
        Request body. When set, the request is a POST and the cache is bypassed.
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
    max_retry_after_sleep : float
        Longest Retry-After we will sleep through in-process. A server asking
        for longer raises RateLimitedError instead, so the caller can checkpoint
        and resume rather than block.
    respect_cooldown : bool
        If True (default), raise RateLimitedError immediately when this host is
        already known to be cooling down from an earlier 429, without spending
        a request to be told so again.

    Returns
    -------
    FetchResult
        Container with status, body, headers, attempts, from_cache flag.

    Raises
    ------
    RetryableHTTPError
        When all retries exhausted and last failure was transient (5xx, network).
    RateLimitedError
        When the upstream rate-limited us and asked for longer than
        `max_retry_after_sleep`, or when this host is already cooling down.
    PermanentHTTPError
        When the upstream returned a 4xx that won't be helped by retry.
    """
    if respect_cooldown:
        remaining = cooldown_remaining(url)
        if remaining > 0:
            raise RateLimitedError(url, remaining, "(host still cooling down)")

    req_headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    if headers:
        req_headers.update(headers)

    # Cache read (idempotent GETs only)
    if data is not None:
        cache_max_age = None
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

    retry_after_used: Optional[float] = None

    for attempt in range(1, max_retries + 1):
        retry_after_used = None
        try:
            req = urllib.request.Request(url, data=data, headers=req_headers)
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
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

            # Respect Retry-After if present.
            retry_after = _parse_retry_after(
                e.headers.get("Retry-After") if e.headers else None
            )

            retry_after_used = retry_after
            if e.code == 429:
                # A 429 is not a transient hiccup — it is an instruction. Burning
                # the remaining retries against it just deepens the penalty, and
                # clamping the server's Retry-After to max_backoff (which this
                # used to do) guarantees we come back too early every time.
                wait = retry_after if retry_after is not None else backoff
                note_rate_limited(url, wait)
                if retry_after is not None and retry_after > max_retry_after_sleep:
                    raise RateLimitedError(
                        url, retry_after,
                        err_body[:200].decode("utf-8", errors="replace"),
                    )
                sleep_for = wait
            elif retry_after is not None:
                sleep_for = retry_after
            else:
                sleep_for = backoff

        except (urllib.error.URLError, TimeoutError, ConnectionResetError) as e:
            last_status = 0
            retry_after_used = None
            last_error = str(e)
            sleep_for = backoff

        # Add jitter to avoid thundering herd on shared rate limits. The cap is
        # max_backoff for our own invented backoff, but a Retry-After the server
        # actually sent is honored in full — capping it is what made us retry
        # too early and stay rate-limited.
        sleep_for = sleep_for + random.uniform(0, 0.5)
        if last_status != 429 or retry_after_used is None:
            sleep_for = min(sleep_for, max_backoff)
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
