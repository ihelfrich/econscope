"""Base adapter interface. Every data source adapter implements this."""

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from econscope.intel.http import DEFAULT_TIMEOUT, fetch

# Per-source rate limiting: earliest allowed start time of the next request,
# keyed by source_id so all instances of an adapter share the budget.
_RATE_LOCK = threading.Lock()
_NEXT_REQUEST_AT: dict = {}


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

    def _throttle(self) -> None:
        """Enforce requests_per_minute as a minimum interval between requests."""
        rpm = self.requests_per_minute
        if not rpm or rpm <= 0:
            return
        interval = 60.0 / rpm
        key = self.source_id or type(self).__name__
        with _RATE_LOCK:
            now = time.monotonic()
            start_at = max(_NEXT_REQUEST_AT.get(key, now), now)
            _NEXT_REQUEST_AT[key] = start_at + interval
        wait = start_at - now
        if wait > 0:
            time.sleep(wait)

    def _http_get(self, url: str, headers: dict = None,
                  timeout: float = DEFAULT_TIMEOUT) -> bytes:
        """GET via the shared HTTP layer (timeout, retry/backoff, shared UA)."""
        self._throttle()
        return fetch(url, headers=headers, timeout=timeout).body

    def _http_post(self, url: str, data: bytes, headers: dict = None,
                   timeout: float = DEFAULT_TIMEOUT) -> bytes:
        """POST via the shared HTTP layer (timeout, retry/backoff, shared UA)."""
        self._throttle()
        return fetch(url, headers=headers, data=data, timeout=timeout).body

    def verify_key(self) -> tuple[bool, str]:
        """Test whether the API key works. Returns (success, message)."""
        try:
            results = self.search("GDP", limit=1)
            if results:
                return True, f"{self.source_name}: key valid ({len(results)} results)"
            return False, f"{self.source_name}: key returned no results"
        except Exception as e:
            return False, f"{self.source_name}: {e}"
