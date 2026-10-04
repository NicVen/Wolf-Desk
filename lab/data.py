"""Free price history from Yahoo's chart API (no key).

1h bars go back about 730 days; daily bars go back decades. Runs on the GitHub
runner or the VPS (Claude's cloud container can't reach Yahoo).
"""
import json
import urllib.request

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval={iv}"


def bars(sym: str, interval: str = "60m", rng: str = "730d") -> list[dict]:
    req = urllib.request.Request(URL.format(sym=sym, rng=rng, iv=interval),
                                 headers={"User-Agent": "Mozilla/5.0"})
    res = json.load(urllib.request.urlopen(req, timeout=30))["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    vols = q.get("volume") or [0] * len(res["timestamp"])
    for t, o, h, l, c, v in zip(res["timestamp"], q["open"], q["high"], q["low"], q["close"], vols):
        if None in (o, h, l, c):
            continue
        out.append({"t": t, "o": o, "h": h, "l": l, "c": c, "v": v or 0})
    return out


COT_URL = "https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip"


def cot(market_prefix: str, years) -> list[tuple]:
    """CFTC Traders in Financial Futures, weekly, free. Returns
    [(release_ts, lev_net_pct_oi, am_net_pct_oi)] oldest first for the market
    whose name starts with market_prefix (e.g. "EURO FX"). Positions are as of
    Tuesday; the report comes out Friday 15:30 ET, so release_ts = Tuesday + 3
    days 21:00 UTC: a rule may only use it from then on."""
    import csv
    import io
    import zipfile
    from datetime import datetime, timedelta, timezone
    rows = []
    for y in years:
        req = urllib.request.Request(COT_URL.format(year=y), headers={"User-Agent": "Mozilla/5.0"})
        try:
            raw = urllib.request.urlopen(req, timeout=60).read()
        except Exception as e:
            print(f"(COT {y}: {e})")
            continue
        z = zipfile.ZipFile(io.BytesIO(raw))
        for name in z.namelist():
            text = z.read(name).decode("latin-1")
            for r in csv.DictReader(io.StringIO(text)):
                r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
                if not r.get("Market_and_Exchange_Names", "").upper().startswith(market_prefix):
                    continue
                try:
                    d = datetime.strptime(r["Report_Date_as_YYYY-MM-DD"][:10], "%Y-%m-%d")
                    oi = float(r["Open_Interest_All"])
                    lev = (float(r["Lev_Money_Positions_Long_All"]) -
                           float(r["Lev_Money_Positions_Short_All"])) / oi
                    am = (float(r["Asset_Mgr_Positions_Long_All"]) -
                          float(r["Asset_Mgr_Positions_Short_All"])) / oi
                except (KeyError, ValueError, ZeroDivisionError):
                    continue
                rel = (d + timedelta(days=3, hours=21)).replace(tzinfo=timezone.utc).timestamp()
                rows.append((rel, lev, am))
    rows.sort()
    out, last = [], None
    for r in rows:                      # drop duplicate weeks
        if r[0] != last:
            out.append(r)
            last = r[0]
    return out
