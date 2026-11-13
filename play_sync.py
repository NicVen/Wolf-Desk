"""Pull the STAALCALIBUR numbers from Google Play into staalwag.com/stats.

Google Play writes daily install reports (installs, uninstalls, active devices,
per country) as CSV files into the developer account's private Cloud Storage
bucket ("Download reports > Statistics" in Play Console). This module reads
them with a read-only Google service account and writes data/play_stats.json,
which /stats.json serves. Free: no paid API, no extra Python packages (the JWT
is signed with the system's `openssl`).

Setup (once, see deploy/play-stats-setup.sh): the service account's JSON key,
with an extra "bucket" field, at /etc/staalwag-play.json (owner wolf, mode 600).
No key = this module does nothing. Nothing here can stop the site: serve.py
runs it in a background thread and swallows errors.

Google's numbers are already totals per day/country: no personal data.
"""
import base64
import csv
import datetime
import io
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.environ.get("PLAY_SA_KEY", "/etc/staalwag-play.json")
OUT = os.environ.get("PLAY_STATS_FILE", os.path.join(HERE, "data", "play_stats.json"))
PACKAGE = "com.staalwag.staalcalibur"
SCOPE = "https://www.googleapis.com/auth/devstorage.read_only"
EVERY = 6 * 3600


# ---- auth -------------------------------------------------------------------
def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _sign_rs256(private_key_pem, data):
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".pem") as f:
        os.chmod(f.name, 0o600)
        f.write(private_key_pem)
        path = f.name
    try:
        return subprocess.run(["openssl", "dgst", "-sha256", "-sign", path], input=data,
                              capture_output=True, check=True, timeout=20).stdout
    finally:
        os.unlink(path)


def access_token(key):
    now = int(time.time())
    head = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claim = _b64(json.dumps({"iss": key["client_email"], "scope": SCOPE,
                             "aud": "https://oauth2.googleapis.com/token",
                             "iat": now, "exp": now + 3600}).encode())
    unsigned = ("%s.%s" % (head, claim)).encode()
    jwt = unsigned.decode() + "." + _b64(_sign_rs256(key["private_key"], unsigned))
    body = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                   "assertion": jwt}).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", body, timeout=30) as r:
        return json.loads(r.read())["access_token"]


def clean_bucket(b):
    """Accept what Play Console's 'Copy Cloud Storage URI' gives: gs://pubsite_prod_123/stats/..."""
    b = str(b or "").strip()
    if b.startswith("gs://"):
        b = b[5:]
    return b.split("/")[0]


def _get(url, token):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def fetch_report(bucket, token, month, dim):
    name = "stats/installs/installs_%s_%s_%s.csv" % (PACKAGE, month, dim)
    url = "https://storage.googleapis.com/storage/v1/b/%s/o/%s?alt=media" % (
        urllib.parse.quote(bucket, safe=""), urllib.parse.quote(name, safe=""))
    try:
        return _get(url, token)
    except urllib.error.HTTPError as e:
        if e.code == 404:           # month not written yet
            return None
        raise


# ---- parsing (pure, tested) -------------------------------------------------
def decode_csv(raw):
    """Play writes these as UTF-16 with a BOM; fall back to UTF-8."""
    if raw is None:
        return []
    for enc in ("utf-16", "utf-8-sig"):
        try:
            text = raw.decode(enc)
            if "Date" in text[:200]:
                return list(csv.DictReader(io.StringIO(text)))
        except UnicodeError:
            continue
    return []


def _num(row, *names):
    for n in names:
        v = row.get(n)
        if v not in (None, ""):
            try:
                return int(float(v))
            except ValueError:
                pass
    return 0


def _row(r):
    return {"installs": _num(r, "Daily Device Installs", "Install events"),
            "uninstalls": _num(r, "Daily Device Uninstalls", "Uninstall events"),
            "active": _num(r, "Active Device Installs"),
            "total_users": _num(r, "Total User Installs")}


def summarise(overview_rows, country_rows, synced=None):
    daily = {}
    for r in overview_rows:
        d = (r.get("Date") or "").strip()
        if d:
            daily[d] = _row(r)
    days = sorted(daily)
    last30 = days[-30:]
    latest = daily[days[-1]] if days else {}
    cc_latest_day = max((r.get("Date", "") for r in country_rows), default="")
    month_days = set(last30)
    countries = {}
    for r in country_rows:
        cc = (r.get("Country") or "").strip() or "??"
        row = _row(r)
        c = countries.setdefault(cc, {"cc": cc, "active": 0, "installs_30d": 0, "uninstalls_30d": 0})
        if r.get("Date") in month_days:
            c["installs_30d"] += row["installs"]
            c["uninstalls_30d"] += row["uninstalls"]
        if r.get("Date") == cc_latest_day:
            c["active"] = row["active"]
    return {
        "synced": synced or datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest_day": days[-1] if days else None,
        "active_devices": latest.get("active", 0),
        "total_user_installs": latest.get("total_users", 0),
        "installs_30d": sum(daily[d]["installs"] for d in last30),
        "uninstalls_30d": sum(daily[d]["uninstalls"] for d in last30),
        "first_day": days[0] if days else None,
        "installs_all": sum(daily[d]["installs"] for d in days),
        "uninstalls_all": sum(daily[d]["uninstalls"] for d in days),
        "daily": [dict(day=d, **daily[d]) for d in days],     # full history (closed test included)
        "countries": sorted(countries.values(), key=lambda c: (-c["active"], -c["installs_30d"])),
    }


# ---- run --------------------------------------------------------------------
FIRST_MONTH = (2026, 9)   # app created in Play Console before the Oct 2026 closed test


def _months(now=None):
    """Every month from the app's first one, so closed testing shows too."""
    t = now or datetime.datetime.utcnow()
    y, m, out = FIRST_MONTH[0], FIRST_MONTH[1], []
    while (y, m) <= (t.year, t.month):
        out.append("%04d%02d" % (y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def sync_once():
    if not os.path.exists(KEY_FILE):
        return None
    with open(KEY_FILE, encoding="utf-8") as f:
        key = json.load(f)
    bucket = clean_bucket(key.get("bucket"))
    if not bucket:
        raise ValueError("no 'bucket' in %s" % KEY_FILE)
    token = access_token(key)
    overview, country = [], []
    for m in _months():
        overview += decode_csv(fetch_report(bucket, token, m, "overview"))
        country += decode_csv(fetch_report(bucket, token, m, "country"))
    out = summarise(overview, country)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f)
    os.replace(tmp, OUT)
    return out


def load():
    """What /stats.json shows: the last good sync, or why there is none."""
    try:
        with open(OUT, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = None
    status = _STATUS.copy()
    if data is None and not os.path.exists(KEY_FILE):
        status["state"] = "not_set_up"
    return {"data": data, "status": status}


_STATUS = {"state": "waiting", "error": None, "last_try": None}


def loop():
    while True:
        _STATUS["last_try"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            r = sync_once()
            _STATUS.update(state="ok" if r else "not_set_up", error=None)
        except Exception as e:  # noqa: BLE001
            _STATUS.update(state="error", error=str(e)[:200])
        time.sleep(EVERY)


if __name__ == "__main__":
    # Manual test on the VPS:  sudo -u wolf python3 play_sync.py
    r = sync_once()
    print(json.dumps(r, indent=1)[:2000] if r else "No key at %s yet." % KEY_FILE)
