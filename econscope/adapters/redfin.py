"""Redfin adapter — US housing market data (prices, inventory, days on market).

Data center: https://www.redfin.com/news/data-center/

No key required. Direct CSV downloads from S3.
Updated weekly. Metro/county/city/ZIP level granularity.
"""

from __future__ import annotations

import csv
import gzip
import io
from typing import Optional
from urllib.request import urlopen

from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


# Redfin data files on S3
REDFIN_FILES = {
    "national": {
        "url": "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/us_national_market_tracker.tsv000.gz",
        "title": "US National Housing Market Tracker",
    },
    "state": {
        "url": "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/state_market_tracker.tsv000.gz",
        "title": "State-Level Housing Market Tracker",
    },
    "metro": {
        "url": "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/redfin_metro_market_tracker.tsv000.gz",
        "title": "Metro-Level Housing Market Tracker",
    },
}

# Key metrics to extract
VALUE_FIELDS = {
    "median_sale_price": "Median Sale Price",
    "homes_sold": "Homes Sold",
    "inventory": "Inventory",
    "days_on_market": "Days on Market",
    "sale_to_list": "Sale-to-List Price",
    "new_listings": "New Listings",
}


class RedfinAdapter(BaseAdapter):
    source_id = "redfin"
    source_name = "Redfin"
    key_env_var = ""
    requests_per_minute = 5  # be polite to S3

    def __init__(self):
        pass

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull Redfin housing data.

        series_id: "national", "state", "metro"
        Optionally filter: "national:median_sale_price"
        """
        parts = series_id.split(":")
        level = parts[0]
        metric_filter = parts[1] if len(parts) > 1 else None

        if level not in REDFIN_FILES:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=f"Unknown level: '{level}'. Use: national, state, metro",
            )

        rf = REDFIN_FILES[level]
        title = rf["title"]

        try:
            raw = urlopen(rf["url"]).read()
            text = gzip.decompress(raw).decode("utf-8")
        except Exception as e:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        reader = csv.DictReader(io.StringIO(text), delimiter="\t")

        observations = []
        for row in reader:
            period_begin = row.get("period_begin", "")
            if not period_begin:
                continue

            # Date filtering
            if start and period_begin < start:
                continue
            if end and period_begin > end:
                continue

            # Determine which value to use
            if metric_filter and metric_filter in ("median_sale_price",):
                raw_val = row.get("median_sale_price", "")
            elif metric_filter == "homes_sold":
                raw_val = row.get("homes_sold", "")
            elif metric_filter == "inventory":
                raw_val = row.get("inventory", "")
            elif metric_filter == "days_on_market":
                raw_val = row.get("median_dom", "")
            elif metric_filter == "new_listings":
                raw_val = row.get("new_listings", "")
            else:
                raw_val = row.get("median_sale_price", "")

            try:
                value = float(str(raw_val).replace(",", "").replace("$", ""))
            except (ValueError, TypeError):
                continue

            obs = {"date": period_begin, "value": value}

            region = row.get("region", "")
            if region:
                obs["geo_name"] = region

            observations.append(obs)

        observations.sort(key=lambda x: (x["date"], x.get("geo_name", "")))

        metric_label = VALUE_FIELDS.get(metric_filter, "Median Sale Price")
        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"{title}: {metric_label}",
            frequency="Weekly", units="USD" if "price" in (metric_filter or "price") else "",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        query_lower = query.lower()
        results = []
        for level, rf in REDFIN_FILES.items():
            if query_lower in rf["title"].lower() or query_lower in level:
                results.append(SeriesMetadata(
                    source=self.source_id, series_id=level,
                    title=rf["title"], frequency="Weekly",
                ))
        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        level = series_id.split(":")[0]
        if level in REDFIN_FILES:
            return SeriesMetadata(
                source=self.source_id, series_id=series_id,
                title=REDFIN_FILES[level]["title"], frequency="Weekly",
            )
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            # Just check the national file is accessible (HEAD-like: read first bytes)
            raw = urlopen(REDFIN_FILES["national"]["url"]).read(1024)
            if raw:
                return True, "Redfin: S3 data accessible (no key needed)"
            return False, "Redfin: no data returned"
        except Exception as e:
            return False, f"Redfin: {e}"
