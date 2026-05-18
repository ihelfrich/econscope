"""Base adapter interface. Every data source adapter implements this."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


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

    def verify_key(self) -> tuple[bool, str]:
        """Test whether the API key works. Returns (success, message)."""
        try:
            results = self.search("GDP", limit=1)
            if results:
                return True, f"{self.source_name}: key valid ({len(results)} results)"
            return False, f"{self.source_name}: key returned no results"
        except Exception as e:
            return False, f"{self.source_name}: {e}"
