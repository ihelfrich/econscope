"""LBMA / African gold adapter — daily benchmark gold and gold priced in African currencies.

Sources (all keyless except FRED):
  * LBMA daily AM/PM gold price in USD, GBP, EUR — https://prices.lbma.org.uk/json/gold_{am,pm}.json
    (from 1968; this replaced FRED's GOLDAMGBD228NLBM / GOLDPMGBD228NLBM, which FRED removed)
  * Yahoo Finance chart API for USD/<African currency> daily quotes (mostly 2001–2003 onward)
    and JSE-listed gold instruments (GLD.JO, ANG.JO, HAR.JO, GFI.JO, DRD.JO), quoted in ZAc
  * FRED DEXSFUS (rand) / DEXUSEU (euro, for the CFA-franc pegs) via the FRED adapter
  * IMF IFS monthly official rates via DBnomics, for the pre-daily backfill

Series IDs understood by pull_series():
  gold_usd | gold_usd_am | gold_gbp | gold_eur          LBMA benchmark (PM fix unless _am)
  fx:<CUR>                                             local units per USD, daily (Yahoo, despiked)
  gold:<CUR>                                           LBMA PM (USD) x fx:<CUR>, local per troy oz
  jse:<TICKER>                                         JSE close in ZAR (e.g. jse:GLD.JO)
  ifs:<ISO2>                                           IMF IFS monthly period-average rate

The full 1996– panel with monthly backfill, quality flags and coverage table is built by
scripts/build_african_gold.py from the raw pulls of scripts/pull_african_gold_raw.py; load_panel()
reads that processed file.
"""

from __future__ import annotations

import datetime as _dt
import json
import time
from pathlib import Path
from urllib.parse import quote, urlencode

from econscope.config import DATA_DIR
from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata

LBMA_JSON = "https://prices.lbma.org.uk/json/{name}.json"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
DBNOMICS_IFS = "https://api.db.nomics.world/v22/series/IMF/IFS/M.{area}.ENDA_XDC_USD_RATE?observations=1"

AFRICAN_FX = {
    "ZAR": "South African rand", "EGP": "Egyptian pound", "NGN": "Nigerian naira", "GHS": "Ghanaian cedi",
    "KES": "Kenyan shilling", "MAD": "Moroccan dirham", "TND": "Tunisian dinar", "DZD": "Algerian dinar",
    "XOF": "West African CFA franc", "XAF": "Central African CFA franc", "ETB": "Ethiopian birr",
    "UGX": "Ugandan shilling", "TZS": "Tanzanian shilling", "ZMW": "Zambian kwacha", "BWP": "Botswana pula",
    "MUR": "Mauritian rupee", "NAD": "Namibian dollar", "MZN": "Mozambican metical", "RWF": "Rwandan franc",
    "SDG": "Sudanese pound", "LYD": "Libyan dinar", "CDF": "Congolese franc", "MWK": "Malawian kwacha",
    "SZL": "Swazi lilangeni", "LSL": "Lesotho loti", "GMD": "Gambian dalasi", "SLL": "Sierra Leonean leone (old)",
    "LRD": "Liberian dollar", "GNF": "Guinean franc", "MGA": "Malagasy ariary", "MRU": "Mauritanian ouguiya",
    "CVE": "Cape Verdean escudo", "SCR": "Seychellois rupee", "DJF": "Djiboutian franc", "SOS": "Somali shilling",
    "BIF": "Burundian franc", "KMF": "Comorian franc",
}
JSE_GOLD = {"GLD.JO": "NewGold ETF (physical gold)", "ANG.JO": "AngloGold Ashanti", "HAR.JO": "Harmony Gold",
            "GFI.JO": "Gold Fields", "DRD.JO": "DRDGOLD"}
PROCESSED = DATA_DIR / "processed" / "african_gold"


class AfricanGoldAdapter(BaseAdapter):
    source_id = "african_gold"
    source_name = "LBMA / African gold"
    key_env_var = ""
    requests_per_minute = 30

    BASE = "https://prices.lbma.org.uk"

    # ---------- raw fetchers ----------
    def _lbma(self, fix: str = "pm") -> list[dict]:
        raw = self._http_get(LBMA_JSON.format(name=f"gold_{fix}"), cache_max_age=6 * 3600)
        return [{"date": r["d"], "usd": r["v"][0], "gbp": r["v"][1], "eur": r["v"][2]}
                for r in json.loads(raw) if r.get("v") and r["v"][0]]

    def _yahoo(self, ticker: str) -> tuple[dict, list[dict]]:
        q = urlencode({"period1": 0, "period2": int(time.time()), "interval": "1d", "events": "history"})
        raw = self._http_get(YAHOO_CHART.format(ticker=quote(ticker)) + "?" + q,
                             headers={"User-Agent": "Mozilla/5.0"}, cache_max_age=6 * 3600)
        r = json.loads(raw)["chart"]["result"][0]
        close = r["indicators"]["quote"][0]["close"]
        rows = [{"date": _dt.datetime.utcfromtimestamp(t).date().isoformat(), "value": c}
                for t, c in zip(r["timestamp"], close) if c is not None and c > 0]
        return r["meta"], rows

    @staticmethod
    def _despike(rows: list[dict], thresh: float = 0.25, window: int = 11) -> list[dict]:
        """Drop isolated Yahoo quote errors: values > thresh from a centred rolling median,
        unless the deviation persists (a real devaluation)."""
        vals = [r["value"] for r in rows]
        n, half = len(vals), window // 2
        bad = []
        for i, v in enumerate(vals):
            w = sorted(vals[max(0, i - half): i + half + 1])
            med = w[len(w) // 2]
            bad.append(abs(v / med - 1) > thresh if med else False)
        # runs longer than 5 days are level shifts – keep them
        i = 0
        while i < n:
            if bad[i]:
                j = i
                while j < n and bad[j]:
                    j += 1
                if j - i > 5:
                    for k in range(i, j):
                        bad[k] = False
                i = j
            else:
                i += 1
        out, last = [], None
        for r, b in zip(rows, bad):
            if b and last is not None:
                out.append({"date": r["date"], "value": last, "flag": "spike_replaced_ffill"})
            else:
                last = r["value"]
                out.append(r)
        return out

    # ---------- BaseAdapter interface ----------
    def pull_series(self, series_id: str, start: str = None, end: str = None) -> PullResult:
        meta = self.get_metadata(series_id)
        try:
            kind, _, arg = series_id.partition(":")
            if kind.startswith("gold_"):
                fix = "am" if kind.endswith("_am") else "pm"
                ccy = {"gold_usd": "usd", "gold_usd_am": "usd", "gold_gbp": "gbp", "gold_eur": "eur"}[kind]
                obs = [{"date": r["date"], "value": r[ccy]} for r in self._lbma(fix) if r[ccy] is not None]
            elif kind == "fx":
                _, rows = self._yahoo(f"{arg.upper()}=X")
                obs = self._despike(rows)
            elif kind == "gold":
                gold = {r["date"]: r["usd"] for r in self._lbma("pm")}
                _, rows = self._yahoo(f"{arg.upper()}=X")
                obs = [{"date": r["date"], "value": gold[r["date"]] * r["value"], "fx": r["value"],
                        "gold_usd": gold[r["date"]]} for r in self._despike(rows) if r["date"] in gold]
            elif kind == "jse":
                m, rows = self._yahoo(arg.upper())
                scale = 0.01 if m.get("currency") == "ZAc" else 1.0
                obs = [{"date": r["date"], "value": r["value"] * scale} for r in rows]
            elif kind == "ifs":
                d = json.loads(self._http_get(DBNOMICS_IFS.format(area=arg.upper()), cache_max_age=24 * 3600))
                s = d["series"]["docs"][0]
                obs = [{"date": p + "-01", "value": float(v)} for p, v in zip(s["period"], s["value"])
                       if v not in (None, "NA")]
            else:
                raise ValueError(f"unknown series id {series_id!r}")
        except Exception as e:
            return PullResult(source=self.source_id, series_id=series_id, metadata=meta, error=str(e))
        if start:
            obs = [o for o in obs if o["date"] >= start]
        if end:
            obs = [o for o in obs if o["date"] <= end]
        if obs:
            meta.observation_start, meta.observation_end = obs[0]["date"], obs[-1]["date"]
        return PullResult(source=self.source_id, series_id=series_id, metadata=meta, observations=obs)

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        terms = query.lower().split()
        cands = [("gold_usd", "LBMA gold PM fix, USD/oz"), ("gold_usd_am", "LBMA gold AM fix, USD/oz"),
                 ("gold_gbp", "LBMA gold PM fix, GBP/oz"), ("gold_eur", "LBMA gold PM fix, EUR/oz")]
        cands += [(f"fx:{c}", f"{n} per USD, daily") for c, n in AFRICAN_FX.items()]
        cands += [(f"gold:{c}", f"Gold in {n}, per troy oz") for c, n in AFRICAN_FX.items()]
        cands += [(f"jse:{t}", f"{n}, JSE close in ZAR") for t, n in JSE_GOLD.items()]
        out = [SeriesMetadata(source=self.source_id, series_id=s, title=t, frequency="daily")
               for s, t in cands if all(k in f"{s} {t}".lower() for k in terms)]
        return out[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        hits = {m.series_id: m for m in self.search(series_id.split(":")[-1], limit=500)}
        m = hits.get(series_id) or SeriesMetadata(source=self.source_id, series_id=series_id, frequency="daily")
        kind = series_id.split(":")[0]
        m.units = {"gold": "local currency per troy ounce", "fx": "local currency units per USD",
                   "jse": "ZAR", "ifs": "local currency units per USD, monthly average"}.get(kind, "USD per troy ounce")
        m.notes = ("LBMA prices.lbma.org.uk" if kind.startswith("gold_") else
                   "Yahoo Finance chart API; isolated quote errors replaced by previous value" if kind in ("fx", "gold", "jse") else
                   "IMF IFS via DBnomics")
        return m

    def verify_key(self) -> tuple[bool, str]:
        try:
            n = len(self._lbma("pm"))
            return True, f"{self.source_name}: LBMA feed OK ({n} PM fixes)"
        except Exception as e:
            return False, f"{self.source_name}: {e}"

    # ---------- processed panel ----------
    @staticmethod
    def load_panel(name: str = "gold_africa_daily"):
        """Load a processed file built by scripts/build_african_gold.py (needs pandas)."""
        import pandas as pd
        p = PROCESSED / f"{name}.parquet"
        if not p.exists():
            p = PROCESSED / f"{name}.csv"
            return pd.read_csv(p, parse_dates=["date"])
        return pd.read_parquet(p)
