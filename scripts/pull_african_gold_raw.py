"""Raw pulls for the African gold-price dataset. Runs on Ian's machine (needs
FRED key from econscope/.env and unblocked access to Yahoo/DBnomics).
Writes JSON/CSV into data/raw/african_gold/ under the econscope repo."""
import csv, datetime, json, os, sys, time, urllib.parse, urllib.request

ROOT = os.environ.get("ECONSCOPE_ROOT", os.path.expanduser("~/mnt/econscope"))
OUT = os.path.join(ROOT, "data", "raw", "african_gold")
os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (econscope african_gold pull)"}


def get(url, headers=None, timeout=90, tries=3):
    h = dict(UA); h.update(headers or {})
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout).read()
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def env_key(name):
    for l in open(os.path.join(ROOT, ".env")):
        if l.startswith(name + "="):
            return l.split("=", 1)[1].strip().strip("\"'")
    return None


# ---------------- FRED ----------------
FRED = {
    # NOTE: FRED's LBMA gold series (GOLDAMGBD228NLBM / GOLDPMGBD228NLBM) were
    # removed from FRED; gold now comes straight from LBMA below.
    "DEXSFUS": "South African rand per USD, Fed H.10 noon buying rate",
    "DEXUSEU": "USD per euro, Fed H.10",
}

# ---------------- LBMA (primary benchmark) ----------------
LBMA = {"gold_am": "https://prices.lbma.org.uk/json/gold_am.json",
        "gold_pm": "https://prices.lbma.org.uk/json/gold_pm.json"}


def pull_lbma():
    for name, url in LBMA.items():
        d = json.loads(get(url))
        obs = [{"date": r["d"], "usd": r["v"][0], "gbp": r["v"][1], "eur": r["v"][2]} for r in d
               if r.get("v") and r["v"][0] not in (None, 0)]
        json.dump({"series_id": name, "source": "LBMA prices.lbma.org.uk", "units": "USD/GBP/EUR per troy ounce",
                   "pulled": datetime.date.today().isoformat(), "observations": obs},
                  open(os.path.join(OUT, f"lbma_{name}.json"), "w"))
        print("LBMA", name, len(obs), obs[0]["date"], obs[-1]["date"])


def pull_fred():
    key = env_key("FRED_API_KEY")
    for sid, title in FRED.items():
        p = os.path.join(OUT, f"fred_{sid}.json")
        q = dict(series_id=sid, api_key=key, file_type="json", observation_start="1995-01-01")
        d = json.loads(get("https://api.stlouisfed.org/fred/series/observations?" + urllib.parse.urlencode(q)))
        obs = [{"date": o["date"], "value": float(o["value"])} for o in d["observations"] if o["value"] != "."]
        json.dump({"series_id": sid, "title": title, "source": "FRED", "pulled": datetime.date.today().isoformat(),
                   "observations": obs}, open(p, "w"))
        print("FRED", sid, len(obs), obs[0]["date"], obs[-1]["date"])


# ---------------- Yahoo Finance ----------------
AFRICAN_FX = ["ZAR", "EGP", "NGN", "GHS", "KES", "MAD", "TND", "DZD", "XOF", "XAF", "ETB", "UGX", "TZS", "ZMW",
              "BWP", "MUR", "NAD", "MZN", "RWF", "SDG", "LYD", "CDF", "MWK", "SZL", "LSL", "GMD", "SLL", "LRD",
              "GNF", "MGA", "MRU", "CVE", "SCR", "DJF", "SOS", "BIF", "KMF", "AOA", "ERN", "SSP", "STN"]
JSE = {"GLD.JO": "NewGold ETF (physical gold, ZAc)", "ANG.JO": "AngloGold Ashanti (ZAc)",
       "HAR.JO": "Harmony Gold (ZAc)", "GFI.JO": "Gold Fields (ZAc)", "DRD.JO": "DRDGOLD (ZAc)"}


def pull_yahoo(ticker):
    now = int(time.time())
    u = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}"
         f"?period1=0&period2={now}&interval=1d&events=history")
    d = json.loads(get(u))
    r = d["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    adj = (r["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    rows = []
    for i, ts in enumerate(r["timestamp"]):
        if q["close"][i] is None:
            continue
        rows.append({"date": datetime.datetime.utcfromtimestamp(ts).date().isoformat(),
                     "open": q["open"][i], "high": q["high"][i], "low": q["low"][i], "close": q["close"][i],
                     "adjclose": adj[i] if adj else None, "volume": q["volume"][i]})
    meta = {k: r["meta"].get(k) for k in ("symbol", "currency", "exchangeName", "longName", "shortName", "exchangeTimezoneName")}
    return meta, rows


def pull_all_yahoo():
    tickers = ["GC=F"] + [f"{c}=X" for c in AFRICAN_FX] + list(JSE)
    for t in tickers:
        p = os.path.join(OUT, "yahoo_" + t.replace("=", "_").replace("^", "") + ".json")
        try:
            meta, rows = pull_yahoo(t)
        except Exception as e:
            print("YAHOO", t, "ERR", e); continue
        json.dump({"ticker": t, "source": "Yahoo Finance chart API", "meta": meta,
                   "pulled": datetime.date.today().isoformat(), "observations": rows}, open(p, "w"))
        print("YAHOO", t, len(rows), rows[0]["date"] if rows else None, rows[-1]["date"] if rows else None)
        time.sleep(0.7)


# ---------------- IMF IFS monthly via DBnomics ----------------
AFRICA_ISO2 = {"DZ": "DZD", "AO": "AOA", "BJ": "XOF", "BW": "BWP", "BF": "XOF", "BI": "BIF", "CV": "CVE", "CM": "XAF",
               "CF": "XAF", "TD": "XAF", "KM": "KMF", "CD": "CDF", "CG": "XAF", "CI": "XOF", "DJ": "DJF", "EG": "EGP",
               "GQ": "XAF", "ER": "ERN", "SZ": "SZL", "ET": "ETB", "GA": "XAF", "GM": "GMD", "GH": "GHS", "GN": "GNF",
               "GW": "XOF", "KE": "KES", "LS": "LSL", "LR": "LRD", "LY": "LYD", "MG": "MGA", "MW": "MWK", "ML": "XOF",
               "MR": "MRU", "MU": "MUR", "MA": "MAD", "MZ": "MZN", "NA": "NAD", "NE": "XOF", "NG": "NGN", "RW": "RWF",
               "ST": "STN", "SN": "XOF", "SC": "SCR", "SL": "SLL", "SO": "SOS", "ZA": "ZAR", "SS": "SSP", "SD": "SDG",
               "TZ": "TZS", "TG": "XOF", "TN": "TND", "UG": "UGX", "ZM": "ZMW", "ZW": "ZWL"}


def pull_ifs():
    """One DBnomics call for every African economy x {period-average, end-of-period}."""
    dims = json.dumps({"FREQ": ["M"], "INDICATOR": ["ENDA_XDC_USD_RATE", "ENDE_XDC_USD_RATE"],
                       "REF_AREA": list(AFRICA_ISO2)})
    u = "https://api.db.nomics.world/v22/series/IMF/IFS?" + urllib.parse.urlencode(
        {"dimensions": dims, "observations": 1, "limit": 1000})
    d = json.loads(get(u, timeout=170))
    out = []
    for s in d["series"]["docs"]:
        _, cc, ind = s["series_code"].split(".")
        for per, val in zip(s["period"], s["value"]):
            if val is None or val == "NA":
                continue
            out.append({"iso2": cc, "currency": AFRICA_ISO2[cc], "indicator": ind, "period": per, "value": float(val)})
        print("IFS", cc, ind, len(s["period"]), s["period"][0], s["period"][-1])
    with open(os.path.join(OUT, "imf_ifs_monthly_fx.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["iso2", "currency", "indicator", "period", "value"]); w.writeheader(); w.writerows(out)
    print("IFS total rows", len(out))


if __name__ == "__main__":
    what = sys.argv[1:] or ["lbma", "fred", "yahoo", "ifs"]
    if "lbma" in what: pull_lbma()
    if "fred" in what: pull_fred()
    if "yahoo" in what: pull_all_yahoo()
    if "ifs" in what: pull_ifs()
