"""Build the tidy African gold-price dataset from the raw pulls in raw/.

Outputs (in out/):
  gold_africa_daily.csv / .parquet     long format: one row per (date, currency)
  gold_benchmark_daily.csv / .parquet  LBMA AM/PM USD-GBP-EUR + COMEX front month
  fx_africa_daily.csv / .parquet       the cleaned FX panel used for conversion
  jse_gold_equities_daily.csv / .parquet  JSE-listed gold instruments (ZAR)
  coverage.csv                          per-currency coverage / source summary
"""
import json, os
import numpy as np
import pandas as pd

RAW, OUT = "raw", "out"
os.makedirs(OUT, exist_ok=True)
START, END = "1996-01-01", None
TROY_OZ_G = 31.1034768

# currency -> (name, countries using it)
CURRENCIES = {
    "ZAR": ("South African rand", "ZA (also legal tender in LS, NA, SZ)"),
    "EGP": ("Egyptian pound", "EG"), "NGN": ("Nigerian naira", "NG"), "GHS": ("Ghanaian cedi", "GH"),
    "KES": ("Kenyan shilling", "KE"), "MAD": ("Moroccan dirham", "MA"), "TND": ("Tunisian dinar", "TN"),
    "DZD": ("Algerian dinar", "DZ"), "XOF": ("West African CFA franc", "BJ BF CI GW ML NE SN TG"),
    "XAF": ("Central African CFA franc", "CM CF TD CG GQ GA"), "ETB": ("Ethiopian birr", "ET"),
    "UGX": ("Ugandan shilling", "UG"), "TZS": ("Tanzanian shilling", "TZ"), "ZMW": ("Zambian kwacha", "ZM"),
    "BWP": ("Botswana pula", "BW"), "MUR": ("Mauritian rupee", "MU"), "NAD": ("Namibian dollar", "NA"),
    "MZN": ("Mozambican metical", "MZ"), "RWF": ("Rwandan franc", "RW"), "SDG": ("Sudanese pound", "SD"),
    "LYD": ("Libyan dinar", "LY"), "CDF": ("Congolese franc", "CD"), "MWK": ("Malawian kwacha", "MW"),
    "SZL": ("Swazi lilangeni", "SZ"), "LSL": ("Lesotho loti", "LS"), "GMD": ("Gambian dalasi", "GM"),
    "SLE": ("Sierra Leonean leone (new leone; old SLL/1000)", "SL"), "LRD": ("Liberian dollar", "LR"), "GNF": ("Guinean franc", "GN"),
    "MGA": ("Malagasy ariary", "MG"), "MRU": ("Mauritanian ouguiya", "MR"), "CVE": ("Cape Verdean escudo", "CV"),
    "SCR": ("Seychellois rupee", "SC"), "DJF": ("Djiboutian franc", "DJ"), "SOS": ("Somali shilling", "SO"),
    "BIF": ("Burundian franc", "BI"), "KMF": ("Comorian franc", "KM"), "AOA": ("Angolan kwanza", "AO"),
    "ERN": ("Eritrean nakfa", "ER"), "SSP": ("South Sudanese pound", "SS"),
    "STN": ("São Tomé and Príncipe dobra", "ST"), "ZWL": ("Zimbabwe dollar (IFS units, treat with care)", "ZW"),
}
# IFS REF_AREA to use for each currency's monthly backfill (one representative economy)
IFS_AREA = {"XOF": "SN", "XAF": "CM"}
EUR_PEG = {"XOF": 655.957, "XAF": 655.957, "KMF": 491.96775, "CVE": 110.265}  # fixed pegs to the euro
ZAR_PEG = {"NAD", "LSL", "SZL"}   # Common Monetary Area, 1:1 with the rand
# Yahoo quotes Sierra Leone in old leones (SLL); IMF IFS is in new leones (SLE = SLL/1000, since 2022).
# The dataset is expressed in SLE throughout.
YAHOO_SCALE = {"SLE": 1 / 1000}
YAHOO_TICKER = {"SLE": "SLL"}


def load_json_obs(path, **kw):
    d = json.load(open(path))
    df = pd.DataFrame(d["observations"])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index(), d


# ---------------- benchmark gold ----------------
am, _ = load_json_obs(f"{RAW}/lbma_gold_am.json")
pm, _ = load_json_obs(f"{RAW}/lbma_gold_pm.json")
gc, _ = load_json_obs(f"{RAW}/yahoo_GC_F.json")
bench = pd.DataFrame({
    "lbma_am_usd": am["usd"], "lbma_am_gbp": am["gbp"], "lbma_am_eur": am["eur"],
    "lbma_pm_usd": pm["usd"], "lbma_pm_gbp": pm["gbp"], "lbma_pm_eur": pm["eur"],
    "comex_front_month_close_usd": gc["close"],
}).loc[START:]
bench = bench[bench.index.dayofweek < 5]
bench = bench.dropna(subset=["lbma_am_usd", "lbma_pm_usd"], how="all")
bench.index.name = "date"
# gold_usd: PM fix, falling back to AM fix when PM is missing (rare)
bench["gold_usd_oz"] = bench["lbma_pm_usd"].fillna(bench["lbma_am_usd"])
bench["gold_usd_source"] = np.where(bench["lbma_pm_usd"].notna(), "LBMA_PM", "LBMA_AM")
bench.reset_index().to_csv(f"{OUT}/gold_benchmark_daily.csv", index=False, float_format="%.6g")
bench.reset_index().to_parquet(f"{OUT}/gold_benchmark_daily.parquet", index=False)
cal = bench.index  # master calendar = LBMA fixing days
print("benchmark", len(bench), cal.min().date(), cal.max().date())

# ---------------- FX ----------------
fred_zar, _ = load_json_obs(f"{RAW}/fred_DEXSFUS.json")
fred_eur, _ = load_json_obs(f"{RAW}/fred_DEXUSEU.json")
ifs = pd.read_csv(f"{RAW}/imf_ifs_monthly_fx.csv")
ifs_avg = ifs[ifs.indicator == "ENDA_XDC_USD_RATE"].copy()
ifs_avg["month"] = pd.PeriodIndex(ifs_avg["period"], freq="M")


def yahoo_fx(cur):
    p = f"{RAW}/yahoo_{YAHOO_TICKER.get(cur, cur)}_X.json"
    if not os.path.exists(p):
        return None
    df, _ = load_json_obs(p)
    s = df["close"].astype(float) * YAHOO_SCALE.get(cur, 1.0)
    s = s[(s > 0) & s.notna()]
    return s if len(s) > 30 else None


def despike(s, thresh=0.25, window=11, rev=0.08, agree=0.05, passes=2):
    """Flag Yahoo bad prints. A day is a spike when EITHER it sits > `thresh` from a centred
    rolling median OR it jumps > `rev` against both neighbours — AND its two neighbours agree
    with each other within `agree` (so a genuine step, where prev != next, is never flagged).
    Runs of > 5 flagged days are level shifts and are kept. Flagged days are forward-filled."""
    s = s.copy()
    bad_all = pd.Series(False, index=s.index)
    for _ in range(passes):
        med = s.rolling(window, center=True, min_periods=3).median()
        prev, nxt = s.shift(1), s.shift(-1)
        far_med = (s / med - 1).abs() > thresh
        far_nb = ((s / prev - 1).abs() > rev) & ((s / nxt - 1).abs() > rev)
        nb_agree = (prev / nxt - 1).abs() < agree
        bad = (far_med | far_nb) & nb_agree
        runs = bad.astype(int).groupby((bad != bad.shift()).cumsum()).transform("size")
        bad &= runs <= 5
        if not bad.any():
            break
        bad_all |= bad
        s = s.mask(bad).ffill()
    return s, bad_all


rows, cov = [], []
for cur, (name, countries) in CURRENCIES.items():
    fx = pd.Series(np.nan, index=cal, dtype=float)
    src = pd.Series("", index=cal, dtype=object)
    qual = pd.Series("", index=cal, dtype=object)
    n_spikes = 0

    if cur == "ZAR":
        z = fred_zar["value"].reindex(cal)
        zf = z.ffill(limit=5)                     # US holidays: carry H.10 rather than mix in Yahoo
        fx.loc[z.notna()] = z[z.notna()]; src.loc[z.notna()] = "FED_H10_DEXSFUS"
        g = z.isna() & zf.notna()
        fx.loc[g] = zf[g]; src.loc[g] = "FED_H10_DEXSFUS_ffill"; qual.loc[g] = "ffill_gap_le5d"
    if cur in ZAR_PEG:   # Common Monetary Area: pegged 1:1 to the rand -> identical to the ZAR series
        z = ZAR_SERIES
        fx.loc[z.notna()] = z[z.notna()]; src.loc[z.notna()] = "ZAR_PEG_1to1_x_" + ZAR_SRC[z.notna()]
        qual.loc[z.notna()] = ZAR_QUAL[z.notna()]
    if cur in EUR_PEG:
        eu = fred_eur["value"].reindex(cal)
        euf = eu.ffill(limit=5)
        e = EUR_PEG[cur] / euf                    # local per USD = peg / (USD per EUR)
        m = e.notna() & fx.isna()
        fx.loc[m] = e[m]; src.loc[m] = "EUR_PEG_x_FED_H10_DEXUSEU"
        g = m & eu.isna()
        src.loc[g] = "EUR_PEG_x_FED_H10_DEXUSEU_ffill"; qual.loc[g] = "ffill_gap_le5d"

    y = yahoo_fx(cur)
    if y is not None:
        yc, bad = despike(y)
        n_spikes = int(bad.sum())
        yc = yc.reindex(cal)
        m = yc.notna() & fx.isna()
        fx.loc[m] = yc[m]; src.loc[m] = "YAHOO_FX"
        badc = bad.reindex(cal).fillna(False).astype(bool) & (src == "YAHOO_FX")
        qual.loc[badc] = "spike_replaced_ffill"
        n_spikes = int(badc.sum())

    # forward-fill within a daily-source stretch: benchmark trades on days some FX feeds skip
    daily_mask = src != ""
    if daily_mask.any():
        first_daily = fx[daily_mask].index.min()
        ff = fx.loc[first_daily:].ffill(limit=5)
        gap = fx.loc[first_daily:].isna() & ff.notna()
        fx.loc[first_daily:] = ff
        src.loc[gap[gap].index] = "ffill_from_prev_daily"
        qual.loc[gap[gap].index] = "ffill_gap_le5d"

    # monthly IFS backfill wherever still missing
    area = IFS_AREA.get(cur, countries.split()[0][:2])
    mo = ifs_avg[ifs_avg.iso2 == area].set_index("month")["value"]
    if len(mo):
        month_of = pd.PeriodIndex(cal, freq="M")
        mv = pd.Series(mo.reindex(month_of).values, index=cal)
        m = fx.isna() & mv.notna()
        fx.loc[m] = mv[m]; src.loc[m] = f"IMF_IFS_MONTHLY_AVG_{area}"; qual.loc[m] = "monthly_rate_repeated_daily"

    # monthly cross-check of the daily sources vs IFS (flag months >30% apart)
    if len(mo):
        month_of = pd.PeriodIndex(cal, freq="M")
        daily_month_mean = fx[daily_mask].groupby(month_of[daily_mask]).mean()
        ratio = (daily_month_mean / mo.reindex(daily_month_mean.index) - 1).abs()
        off = ratio[ratio > 0.30].index
        if len(off):
            mm = daily_mask & pd.Series(month_of.isin(off), index=cal)
            qual.loc[mm] = np.where(qual.loc[mm] == "", "daily_vs_ifs_gt30pct", qual.loc[mm] + "|daily_vs_ifs_gt30pct")

    if cur == "ZAR":
        ZAR_SERIES, ZAR_SRC, ZAR_QUAL = fx.copy(), src.copy(), qual.copy()
    have = fx.notna()
    df = pd.DataFrame({"date": cal, "currency": cur, "fx_local_per_usd": fx.values,
                       "fx_source": src.values, "fx_quality": qual.replace("", "ok").values})[have.values]
    rows.append(df)
    dsrc = df[~df.fx_source.str.startswith("IMF")]
    cov.append({"currency": cur, "currency_name": name, "countries": countries,
                "first_date": df.date.min().date() if len(df) else None,
                "last_date": df.date.max().date() if len(df) else None,
                "n_days": len(df),
                "first_daily_source_date": dsrc.date.min().date() if len(dsrc) else None,
                "n_daily_source_days": len(dsrc),
                "n_monthly_backfill_days": int(df.fx_source.str.startswith("IMF").sum()),
                "n_yahoo_spikes_replaced": n_spikes,
                "n_days_flagged_vs_ifs": int(df.fx_quality.str.contains("gt30").sum()),
                "sources": "; ".join(sorted(set(df.fx_source.str.replace(r"_[A-Z]{2}$", "", regex=True))))})

fx_long = pd.concat(rows, ignore_index=True)
fx_long.to_csv(f"{OUT}/fx_africa_daily.csv", index=False, float_format="%.8g")
fx_long.to_parquet(f"{OUT}/fx_africa_daily.parquet", index=False)
coverage = pd.DataFrame(cov)
coverage.to_csv(f"{OUT}/coverage.csv", index=False)
print(coverage[["currency", "first_date", "first_daily_source_date", "n_days", "n_monthly_backfill_days", "n_yahoo_spikes_replaced", "n_days_flagged_vs_ifs"]].to_string())

# ---------------- gold in local currency ----------------
g = bench[["gold_usd_oz", "gold_usd_source", "lbma_am_usd", "lbma_pm_usd"]].reset_index()
gold = fx_long.merge(g, on="date", how="inner")
gold["gold_local_per_oz"] = gold["gold_usd_oz"] * gold["fx_local_per_usd"]
gold["gold_local_per_gram"] = gold["gold_local_per_oz"] / TROY_OZ_G
gold["gold_local_am_per_oz"] = gold["lbma_am_usd"] * gold["fx_local_per_usd"]
gold["gold_local_pm_per_oz"] = gold["lbma_pm_usd"] * gold["fx_local_per_usd"]
gold = gold[["date", "currency", "gold_usd_oz", "gold_usd_source", "fx_local_per_usd", "fx_source", "fx_quality",
             "gold_local_per_oz", "gold_local_per_gram", "gold_local_am_per_oz", "gold_local_pm_per_oz"]]
gold = gold.sort_values(["currency", "date"]).reset_index(drop=True)
gold.to_csv(f"{OUT}/gold_africa_daily.csv", index=False, float_format="%.8g")
gold.to_parquet(f"{OUT}/gold_africa_daily.parquet", index=False)
print("gold_africa_daily", gold.shape, gold.date.min().date(), gold.date.max().date(), gold.currency.nunique(), "currencies")

# ---------------- JSE gold instruments ----------------
JSE = {"GLD.JO": "NewGold ETF (1 unit ≈ 1/100 oz physical gold)", "ANG.JO": "AngloGold Ashanti",
       "HAR.JO": "Harmony Gold Mining", "GFI.JO": "Gold Fields", "DRD.JO": "DRDGOLD"}
jrows = []
for t, nm in JSE.items():
    df, d = load_json_obs(f"{RAW}/yahoo_{t}.json")
    cur = d["meta"].get("currency", "ZAc")
    scale = 0.01 if cur == "ZAc" else 1.0   # JSE quotes in cents
    df = df[["open", "high", "low", "close", "adjclose", "volume"]].astype(float)
    df[["open", "high", "low", "close", "adjclose"]] *= scale
    df["ticker"], df["name"] = t, nm
    df["currency"] = "ZAR"
    jrows.append(df.reset_index())
jse = pd.concat(jrows, ignore_index=True)
jse = jse[["date", "ticker", "name", "currency", "open", "high", "low", "close", "adjclose", "volume"]]
jse = jse.merge(bench[["gold_usd_oz"]].reset_index(), on="date", how="left")
zar = fx_long[fx_long.currency == "ZAR"][["date", "fx_local_per_usd"]].rename(columns={"fx_local_per_usd": "usdzar"})
jse = jse.merge(zar, on="date", how="left")
jse["gold_zar_per_oz"] = jse["gold_usd_oz"] * jse["usdzar"]
jse.to_csv(f"{OUT}/jse_gold_equities_daily.csv", index=False, float_format="%.8g")
jse.to_parquet(f"{OUT}/jse_gold_equities_daily.parquet", index=False)
print("jse", jse.shape, jse.groupby("ticker").date.agg(["min", "max", "count"]).to_string())
