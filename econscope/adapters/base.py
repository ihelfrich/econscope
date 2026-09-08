"""Base adapter interface. Every data source adapter implements this."""

import json
import os
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from econscope.intel.http import (
    DEFAULT_TIMEOUT,
    RateLimitedError,
    cooldown_remaining,
    fetch,
)

# Per-source rate limiting: earliest allowed start time of the next request,
# keyed by source_id so all instances of an adapter share the budget.
_RATE_LOCK = threading.Lock()
_NEXT_REQUEST_AT: dict = {}

# Adaptive spacing. `requests_per_minute` on an adapter is a guess made by
# whoever wrote it, usually from the upstream's published docs, and published
# limits are routinely wrong or apply to a different endpoint than the one we
# are hitting. So we treat it as a starting point: every 429 widens this
# source's interval, every clean run narrows it back toward the configured
# value. The multiplier is shared across instances, like the budget itself.
_INTERVAL_MULT: dict = {}
_MULT_ON_LIMIT = 2.0      # widen aggressively — being throttled is expensive
_MULT_DECAY = 0.9         # narrow slowly — the limit is usually still there
_MULT_MAX = 32.0

# Rolling-window quota state, keyed by source_id: deque of request timestamps
# (wall-clock, so it survives a process restart).
_WINDOW_LOCK = threading.Lock()
_WINDOWS: dict = {}
_QUOTA_DIR = Path.home() / ".cache" / "econscope" / "ratelimit"


class QuotaExhausted(Exception):
    """A rolling-window quota is spent and will not refill soon.

    Raised instead of sleeping when the wait exceeds what a caller should block
    for. `retry_after` is how long until the window admits another request.
    """

    def __init__(self, source: str, window: str, retry_after: float):
        super().__init__(
            f"{source}: {window} quota exhausted, refills in {retry_after:.0f}s"
        )
        self.source = source
        self.window = window
        self.retry_after = retry_after


def _quota_path(key: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
    return _QUOTA_DIR / f"{safe}.json"


def _load_window(key: str) -> deque:
    """Load this source's request timestamps from disk.

    Daily quotas are the reason this is persisted. A 125-requests-per-day
    ceiling is meaningless if the counter resets every time the process
    restarts — you would blow the quota in three runs and not know why.
    """
    if key in _WINDOWS:
        return _WINDOWS[key]
    stamps: deque = deque()
    p = _quota_path(key)
    if p.exists():
        try:
            stamps.extend(float(t) for t in json.loads(p.read_text()))
        except Exception:
            pass
    _WINDOWS[key] = stamps
    return stamps


def _save_window(key: str, stamps: deque) -> None:
    try:
        _QUOTA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _quota_path(key).with_suffix(".tmp")
        tmp.write_text(json.dumps(list(stamps)))
        os.replace(tmp, _quota_path(key))
    except Exception:
        # Losing the quota ledger must never break a fetch.
        pass


@dataclass
class SeriesMetadata:
    source: str
    series_id: str
    title: str = ""
    frequency: str = ""
    units: str = ""
    seasonal_adjustment: str = ""
    last_updated: str = ""
    observation_start: str = ""
    observation_end: str = ""
    notes: str = ""


@dataclass
class PullResult:
    source: str
    series_id: str
    metadata: SeriesMetadata
    observations: list[dict] = field(default_factory=list)
    raw_bytes: bytes = b""
    error: str = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def count(self) -> int:
        return len(self.observations)


class BaseAdapter(ABC):
    """Every adapter must implement these methods."""

    source_id: str = ""
    source_name: str = ""
    key_env_var: str = ""
    requests_per_minute: int = 60

    #: Rolling-window quotas as (max_requests, window_seconds), enforced
    #: together and persisted across processes. `requests_per_minute` only
    #: expresses spacing; it cannot express "50 per hour, 125 per day", which
    #: is the shape most real API quotas actually take. Leave empty to keep
    #: the old spacing-only behaviour.
    rate_limits: list = []

    #: Longest a quota wait may block in-process before QuotaExhausted is
    #: raised instead, so a caller can checkpoint rather than sleep for hours.
    max_quota_wait: float = 120.0

    @abstractmethod
    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        ...

    @abstractmethod
    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        ...

    @abstractmethod
    def get_metadata(self, series_id: str) -> SeriesMetadata:
        ...

    @property
    def _rate_key(self) -> str:
        return self.source_id or type(self).__name__

    def current_interval(self) -> float:
        """The interval actually being enforced right now, in seconds."""
        rpm = self.requests_per_minute
        if not rpm or rpm <= 0:
            return 0.0
        with _RATE_LOCK:
            mult = _INTERVAL_MULT.get(self._rate_key, 1.0)
        return (60.0 / rpm) * mult

    def _widen_interval(self) -> float:
        with _RATE_LOCK:
            key = self._rate_key
            mult = min(_INTERVAL_MULT.get(key, 1.0) * _MULT_ON_LIMIT, _MULT_MAX)
            _INTERVAL_MULT[key] = mult
            return mult

    def _narrow_interval(self) -> None:
        with _RATE_LOCK:
            key = self._rate_key
            mult = _INTERVAL_MULT.get(key, 1.0)
            if mult > 1.0:
                _INTERVAL_MULT[key] = max(1.0, mult * _MULT_DECAY)

    def _check_quota(self) -> None:
        """Block or raise until every rolling window admits one more request."""
        if not self.rate_limits:
            return
        key = self._rate_key
        while True:
            now = time.time()
            with _WINDOW_LOCK:
                stamps = _load_window(key)
                widest = max(w for _, w in self.rate_limits)
                while stamps and now - stamps[0] > widest:
                    stamps.popleft()
                wait = 0.0
                blocking = ""
                for limit, window in self.rate_limits:
                    in_window = sum(1 for t in stamps if now - t <= window)
                    if in_window >= limit:
                        oldest = min(t for t in stamps if now - t <= window)
                        w = (oldest + window) - now
                        if w > wait:
                            wait, blocking = w, f"{limit}/{int(window)}s"
                if wait <= 0:
                    stamps.append(now)
                    _save_window(key, stamps)
                    return
            if wait > self.max_quota_wait:
                raise QuotaExhausted(self.source_id or key, blocking, wait)
            time.sleep(min(wait, self.max_quota_wait) + 0.05)

    def _throttle(self) -> None:
        """Enforce the current interval as a minimum gap between requests."""
        self._check_quota()
        interval = self.current_interval()
        if interval <= 0:
            return
        key = self._rate_key
        with _RATE_LOCK:
            now = time.monotonic()
            start_at = max(_NEXT_REQUEST_AT.get(key, now), now)
            _NEXT_REQUEST_AT[key] = start_at + interval
        wait = start_at - now
        if wait > 0:
            time.sleep(wait)

    def _fetch(self, url: str, **kw):
        """Throttled fetch that learns from 429s. Returns a FetchResult."""
        self._throttle()
        try:
            result = fetch(url, **kw)
        except RateLimitedError:
            mult = self._widen_interval()
            # Do not let the next caller sail straight past the gap we just
            # widened — push the schedule out by the new interval too.
            with _RATE_LOCK:
                key = self._rate_key
                base = 60.0 / self.requests_per_minute if self.requests_per_minute else 0.0
                _NEXT_REQUEST_AT[key] = max(
                    _NEXT_REQUEST_AT.get(key, 0.0), time.monotonic() + base * mult
                )
            raise
        self._narrow_interval()
        return result

    def _http_get(self, url: str, headers: dict = None,
                  timeout: float = DEFAULT_TIMEOUT,
                  cache_max_age: int = None) -> bytes:
        """GET via the shared HTTP layer (timeout, retry/backoff, shared UA).

        `cache_max_age` opts this call into the on-disk HTTP cache. It defaults
        to None (no caching) to preserve existing behaviour, but adapters
        pulling reference data that changes daily or slower should set it — an
        interrupted research pull otherwise re-fetches everything it already
        had, which is both slow and the fastest way to get rate-limited.
        """
        return self._fetch(url, headers=headers, timeout=timeout,
                           cache_max_age=cache_max_age).body

    def _http_post(self, url: str, data: bytes, headers: dict = None,
                   timeout: float = DEFAULT_TIMEOUT) -> bytes:
        """POST via the shared HTTP layer (timeout, retry/backoff, shared UA)."""
        return self._fetch(url, headers=headers, data=data, timeout=timeout).body

    def rate_limit_status(self) -> dict:
        """What the throttle is doing right now — for CLI and diagnostics."""
        base = 60.0 / self.requests_per_minute if self.requests_per_minute else 0.0
        with _RATE_LOCK:
            mult = _INTERVAL_MULT.get(self._rate_key, 1.0)
        out = {
            "source": self.source_id,
            "configured_rpm": self.requests_per_minute,
            "effective_rpm": round(60.0 / (base * mult), 2) if base and mult else None,
            "backoff_multiplier": round(mult, 2),
            "cooling_down_s": round(cooldown_remaining(getattr(self, "BASE", "")), 1),
        }
        if self.rate_limits:
            now = time.time()
            with _WINDOW_LOCK:
                stamps = list(_load_window(self._rate_key))
            out["quotas"] = [
                {
                    "window": f"{limit}/{int(window)}s",
                    "used": sum(1 for t in stamps if now - t <= window),
                    "limit": limit,
                }
                for limit, window in self.rate_limits
            ]
        return out

    def verify_key(self) -> tuple[bool, str]:
        """Test whether the API key works. Returns (success, message)."""
        try:
            results = self.search("GDP", limit=1)
            if results:
                return True, f"{self.source_name}: key valid ({len(results)} results)"
            return False, f"{self.source_name}: key returned no results"
        except Exception as e:
            return False, f"{self.source_name}: {e}"
