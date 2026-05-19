"""OpenSanctions adapter — local FtM entity graph (sanctions, PEPs, companies, vessels).

Data: 4.28M entities from entities.ftm.json (FollowTheMoney schema).
Downloaded bulk dump, no API needed. Supports search by name, schema filtering,
dataset filtering, and entity lookup by ID.

This adapter doesn't fit the time-series model — it's entity-centric. We adapt:
  - search() → find entities by name/caption
  - pull_series() → given an entity ID, return its properties as observations
  - get_metadata() → entity schema and dataset info
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


# Default path to the bulk FtM dump
DEFAULT_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "opensanctions" / "entities.ftm.json"

# Entity schemas worth surfacing
ENTITY_SCHEMAS = {
    "Person", "Company", "Organization", "LegalEntity",
    "Vessel", "Airplane", "PublicBody", "Address",
}

# Relationship schemas (connect entities)
RELATION_SCHEMAS = {
    "Occupancy", "Ownership", "Directorship", "Family",
    "Succession", "Employment", "Representation", "Associate",
    "UnknownLink", "Documentation",
}

# Interesting datasets to highlight
KEY_DATASETS = {
    "us_ofac_sdn": "US OFAC SDN List",
    "eu_fsf": "EU Financial Sanctions",
    "un_sc_sanctions": "UN Security Council Sanctions",
    "gb_hmt_sanctions": "UK HMT Sanctions",
    "ru_rupep": "Russian PEPs (RuPEP)",
    "ua_nsdc_sanctions": "Ukraine NSDC Sanctions",
    "wd_peps": "Wikidata PEPs",
    "opencorporates": "OpenCorporates",
    "icij_offshoreleaks": "ICIJ Offshore Leaks",
    "worldbank_debarred": "World Bank Debarred Firms",
}


class OpenSanctionsAdapter(BaseAdapter):
    source_id = "opensanctions"
    source_name = "OpenSanctions"
    key_env_var = ""  # Local data, no key
    requests_per_minute = 9999  # Local file, no rate limit

    def __init__(self, data_path: str = None):
        self.data_path = Path(data_path) if data_path else DEFAULT_DATA_PATH
        self._index = None  # Lazy-loaded in-memory index

    def _ensure_index(self, max_entities: int = None):
        """Build a lightweight in-memory index for search.

        Only indexes entity schemas (Person, Company, etc.), not relationships.
        Stores: id, caption, schema, datasets, target flag.
        """
        if self._index is not None:
            return

        if not self.data_path.exists():
            self._index = []
            return

        index = []
        count = 0
        with open(self.data_path, "r") as f:
            for line in f:
                obj = json.loads(line)
                schema = obj.get("schema", "")
                if schema not in ENTITY_SCHEMAS:
                    continue
                caption = obj.get("caption", "")
                if not caption:
                    continue
                index.append({
                    "id": obj["id"],
                    "caption": caption,
                    "schema": schema,
                    "datasets": obj.get("datasets", []),
                    "target": obj.get("target", False),
                })
                count += 1
                if max_entities and count >= max_entities:
                    break
        self._index = index

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull entity details by ID.

        series_id: an OpenSanctions entity ID (e.g., "NK-2229ydxkHNa5AcDp9d6jt3")
        or a search query prefixed with "search:" (e.g., "search:putin")

        Returns properties as observations: [{date: property_name, value: property_value}]
        This is an unconventional use of the observations field — we encode
        entity properties as key-value pairs since there's no time dimension.
        """
        if series_id.startswith("search:"):
            query = series_id[7:]
            results = self.search(query, limit=50)
            observations = []
            for i, r in enumerate(results):
                observations.append({
                    "date": f"result_{i:04d}",
                    "value": 0,
                    "entity_id": r.series_id,
                    "caption": r.title,
                    "schema": r.frequency,  # We store schema in frequency field
                    "datasets": r.notes,
                })
            meta = SeriesMetadata(
                source=self.source_id, series_id=series_id,
                title=f"Search: {query}", notes=f"{len(results)} entities found",
            )
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=meta, observations=observations,
            )

        # Direct entity lookup by ID
        entity = self._find_entity_by_id(series_id)
        if not entity:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=f"Entity not found: {series_id}",
            )

        observations = []
        props = entity.get("properties", {})
        for prop_name, values in props.items():
            for val in values:
                observations.append({
                    "date": prop_name,
                    "value": 0,
                    "property": prop_name,
                    "property_value": str(val),
                })

        meta = SeriesMetadata(
            source=self.source_id,
            series_id=series_id,
            title=entity.get("caption", series_id),
            frequency=entity.get("schema", ""),
            notes=f"Datasets: {', '.join(entity.get('datasets', [])[:5])}",
            last_updated=entity.get("last_change", ""),
        )
        if entity.get("first_seen"):
            meta.observation_start = entity["first_seen"][:10]
        if entity.get("last_seen"):
            meta.observation_end = entity["last_seen"][:10]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations,
        )

    def _find_entity_by_id(self, entity_id: str) -> Optional[dict]:
        """Scan the file for a specific entity ID. Returns full entity dict."""
        if not self.data_path.exists():
            return None
        with open(self.data_path, "r") as f:
            for line in f:
                obj = json.loads(line)
                if obj.get("id") == entity_id:
                    return obj
        return None

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        """Search entities by caption (name).

        Supports filters:
          - "schema:Person putin" → only Person entities matching "putin"
          - "dataset:us_ofac_sdn" → only entities in OFAC SDN
          - "target:true gazprom" → only sanctions targets
        """
        self._ensure_index(max_entities=500_000)

        query_lower = query.lower()
        schema_filter = None
        dataset_filter = None
        target_filter = None

        # Parse filters
        parts = query_lower.split()
        search_terms = []
        for part in parts:
            if part.startswith("schema:"):
                schema_filter = part[7:]
            elif part.startswith("dataset:"):
                dataset_filter = part[8:]
            elif part.startswith("target:"):
                target_filter = part[7:] == "true"
            else:
                search_terms.append(part)
        query_text = " ".join(search_terms)

        results = []
        for ent in self._index:
            # Apply filters
            if schema_filter and ent["schema"].lower() != schema_filter:
                continue
            if dataset_filter and dataset_filter not in [d.lower() for d in ent["datasets"]]:
                continue
            if target_filter is not None and ent["target"] != target_filter:
                continue

            # Text match on caption
            if query_text and query_text not in ent["caption"].lower():
                continue

            ds_str = ", ".join(ent["datasets"][:3])
            target_tag = " [TARGET]" if ent["target"] else ""
            results.append(SeriesMetadata(
                source=self.source_id,
                series_id=ent["id"],
                title=f"{ent['caption']}{target_tag}",
                frequency=ent["schema"],
                notes=ds_str,
            ))
            if len(results) >= limit:
                break

        return results

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        entity = self._find_entity_by_id(series_id)
        if entity:
            return SeriesMetadata(
                source=self.source_id,
                series_id=series_id,
                title=entity.get("caption", ""),
                frequency=entity.get("schema", ""),
                notes=f"Datasets: {', '.join(entity.get('datasets', [])[:5])}",
                last_updated=entity.get("last_change", ""),
            )
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        if not self.data_path.exists():
            return False, f"OpenSanctions: data file not found at {self.data_path}"
        size_mb = self.data_path.stat().st_size / (1024 * 1024)
        # Quick line count estimate
        with open(self.data_path) as f:
            sample = 0
            for _ in range(1000):
                f.readline()
                sample += 1
        return True, f"OpenSanctions: {size_mb:.0f} MB FtM dump found ({sample}+ entities sampled)"

    def stats(self) -> dict:
        """Return summary statistics about the local dump."""
        if not self.data_path.exists():
            return {"error": "data file not found"}

        from collections import Counter
        schemas = Counter()
        datasets = Counter()
        targets = 0
        total = 0

        with open(self.data_path) as f:
            for line in f:
                obj = json.loads(line)
                total += 1
                schemas[obj.get("schema", "")] += 1
                if obj.get("target"):
                    targets += 1
                for d in obj.get("datasets", []):
                    datasets[d] += 1

        return {
            "total_entities": total,
            "sanctions_targets": targets,
            "schemas": dict(schemas.most_common(20)),
            "top_datasets": dict(datasets.most_common(20)),
        }
