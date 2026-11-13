"""Anonymous usage stats for the STAALCALIBUR app and the staalwag.com pages.

Privacy by design (Nic: "everything about the app but no personal details"):
  * no IP address, no user agent, no licence key, no name/email is stored;
  * the phone's random install id (sc_dev) is hashed with a server-only salt
    before it touches disk, so the stored value can't be matched to anything;
  * country comes from the browser's own time zone ("Pacific/Auckland" -> NZ),
    looked up in tz_country.json; no IP geolocation;
  * only counts leave this module (stats.json has no ids at all).

Events (POST /hit, JSON):  {"e": kind, "k": key, "tz": "...", "d": install id, "app": 1}
  view  - a page on staalwag.com was opened          (k = page name)
  play  - a "Get it on Google Play" button was tapped (k = page name)
  open  - the app was opened                          (app=1 when it runs installed)
  tool  - a tool inside the app was opened            (k = tool name)

Deterministic, free, no third-party service. Nothing here can stop the app or
site working: callers wrap it in try/except.
"""
import datetime
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("APP_STATS_DB", os.path.join(HERE, "data", "app_stats.db"))
KINDS = ("view", "play", "open", "tool")
QUIET_DAYS = 30          # an installed phone not seen for 30 days = probably uninstalled
KEEP_DAYS = 400          # daily rows older than this are pruned
_LOCK = threading.Lock()
_KEY_RE = re.compile(r"[^a-z0-9-]")

with open(os.path.join(HERE, "tz_country.json"), encoding="utf-8") as _f:
    _TZ = json.load(_f)
TZ_COUNTRY, COUNTRY_NAMES = _TZ["tz"], _TZ["names"]


def country(tz):
    """Two-letter country from an IANA time zone name, '??' when unknown."""
    return TZ_COUNTRY.get(str(tz or "")[:64], "??")


def clean_key(k):
    return _KEY_RE.sub("", str(k or "").lower())[:40] or "unknown"


def today(now=None):
    return (now or datetime.datetime.utcnow()).strftime("%Y-%m-%d")


def _conn():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, timeout=10)
    c.executescript("""
        CREATE TABLE IF NOT EXISTS daily(day TEXT, kind TEXT, key TEXT, cc TEXT, n INTEGER DEFAULT 0,
                                         PRIMARY KEY(day, kind, key, cc));
        CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, first_day TEXT, last_day TEXT,
                                           cc TEXT, app INTEGER DEFAULT 0, opens INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS active(day TEXT, id TEXT, PRIMARY KEY(day, id));
        CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
    """)
    return c


def _salt(c):
    row = c.execute("SELECT v FROM meta WHERE k='salt'").fetchone()
    if row:
        return row[0]
    s = secrets.token_hex(16)
    c.execute("INSERT INTO meta(k, v) VALUES('salt', ?)", (s,))
    return s


def _dev_id(c, raw):
    raw = str(raw or "")[:64]
    if len(raw) < 4:
        return None
    return hashlib.sha256((_salt(c) + raw).encode()).hexdigest()[:20]


def record(event, now=None):
    """Store one event. Returns True when counted, False when ignored."""
    if not isinstance(event, dict):
        return False
    kind = event.get("e")
    if kind not in KINDS:
        return False
    key = clean_key(event.get("k") or ("app" if kind == "open" else ""))
    cc = country(event.get("tz"))
    day = today(now)
    with _LOCK:
        c = _conn()
        try:
            c.execute("INSERT INTO daily(day, kind, key, cc, n) VALUES(?,?,?,?,1) "
                      "ON CONFLICT(day, kind, key, cc) DO UPDATE SET n=n+1", (day, kind, key, cc))
            if kind in ("open", "tool"):
                did = _dev_id(c, event.get("d"))
                if did:
                    app = 1 if event.get("app") else 0
                    c.execute("INSERT INTO devices(id, first_day, last_day, cc, app, opens) "
                              "VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET last_day=excluded.last_day, "
                              "app=MAX(app, excluded.app), opens=opens+excluded.opens, "
                              "cc=CASE WHEN excluded.cc!='??' THEN excluded.cc ELSE cc END",
                              (did, day, day, cc, app, 1 if kind == "open" else 0))
                    c.execute("INSERT OR IGNORE INTO active(day, id) VALUES(?, ?)", (day, did))
            c.commit()
        finally:
            c.close()
    return True


def _days_back(n, now=None):
    base = now or datetime.datetime.utcnow()
    return [(base - datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n - 1, -1, -1)]


def prune(now=None):
    cut = _days_back(KEEP_DAYS, now)[0]
    with _LOCK:
        c = _conn()
        try:
            c.execute("DELETE FROM daily WHERE day<?", (cut,))
            c.execute("DELETE FROM active WHERE day<?", (cut,))
            c.commit()
        finally:
            c.close()


def _name(cc):
    return COUNTRY_NAMES.get(cc, "Unknown")


def stats(now=None):
    """Everything the dashboard shows. Counts only, never ids."""
    d30 = _days_back(30, now)
    d7, d1 = d30[-7:], d30[-1]
    quiet_cut = _days_back(QUIET_DAYS + 1, now)[0]
    with _LOCK:
        c = _conn()
        try:
            one = lambda sql, *a: c.execute(sql, a).fetchone()[0] or 0
            installs = one("SELECT COUNT(*) FROM devices WHERE app=1")
            browser_users = one("SELECT COUNT(*) FROM devices WHERE app=0")
            new7 = one("SELECT COUNT(*) FROM devices WHERE app=1 AND first_day>=?", d7[0])
            quiet = one("SELECT COUNT(*) FROM devices WHERE app=1 AND last_day<?", quiet_cut)
            act = lambda since: one("SELECT COUNT(DISTINCT id) FROM active WHERE day>=?", since)
            active = {"today": act(d1), "7d": act(d7[0]), "30d": act(d30[0])}

            def daily_counts(kind):
                rows = c.execute("SELECT day, SUM(n) FROM daily WHERE kind=? AND day>=? GROUP BY day",
                                 (kind, d30[0])).fetchall()
                m = dict(rows)
                return [m.get(d, 0) for d in d30]

            act_rows = dict(c.execute("SELECT day, COUNT(*) FROM active WHERE day>=? GROUP BY day",
                                      (d30[0],)).fetchall())
            new_rows = dict(c.execute("SELECT first_day, COUNT(*) FROM devices WHERE app=1 AND first_day>=? "
                                      "GROUP BY first_day", (d30[0],)).fetchall())
            chart = [{"day": d, "active": act_rows.get(d, 0), "new_installs": new_rows.get(d, 0),
                      "views": v, "play_taps": p}
                     for d, v, p in zip(d30, daily_counts("view"), daily_counts("play"))]

            def by(kind, col, since):
                return c.execute("SELECT %s, SUM(n) FROM daily WHERE kind=? AND day>=? GROUP BY %s "
                                 "ORDER BY SUM(n) DESC" % (col, col), (kind, since)).fetchall()

            def total(kind, since):
                return one("SELECT SUM(n) FROM daily WHERE kind=? AND day>=?", kind, since)

            tools = [{"tool": k, "uses": n} for k, n in by("tool", "key", d30[0])]
            views_7 = dict(by("view", "key", d7[0]))
            play_7 = dict(by("play", "key", d7[0]))
            pages = sorted(set(views_7) | set(play_7), key=lambda k: -views_7.get(k, 0))
            page_rows = [{"page": k, "views": views_7.get(k, 0), "play_taps": play_7.get(k, 0)} for k in pages]

            inst_cc = dict(c.execute("SELECT cc, COUNT(*) FROM devices WHERE app=1 GROUP BY cc").fetchall())
            act_cc = dict(c.execute("SELECT d.cc, COUNT(DISTINCT a.id) FROM active a JOIN devices d ON d.id=a.id "
                                    "WHERE a.day>=? GROUP BY d.cc", (d7[0],)).fetchall())
            view_cc = dict(by("view", "cc", d30[0]))
            play_cc = dict(by("play", "cc", d30[0]))
            ccs = set(inst_cc) | set(act_cc) | set(view_cc) | set(play_cc)
            countries = sorted(({"cc": k, "country": _name(k), "installs": inst_cc.get(k, 0),
                                 "active_7d": act_cc.get(k, 0), "views_30d": view_cc.get(k, 0),
                                 "play_taps_30d": play_cc.get(k, 0)} for k in ccs),
                               key=lambda r: (-r["installs"], -r["active_7d"], -r["views_30d"]))
            return {
                "generated": (now or datetime.datetime.utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "app": {"installs_seen": installs, "new_installs_7d": new7, "browser_users": browser_users,
                        "active": active, "probably_uninstalled": quiet, "quiet_days": QUIET_DAYS,
                        "opens_today": one("SELECT SUM(n) FROM daily WHERE kind='open' AND day=?", d1),
                        "opens_7d": total("open", d7[0])},
                "site": {"views_today": one("SELECT SUM(n) FROM daily WHERE kind='view' AND day=?", d1),
                         "views_7d": total("view", d7[0]), "views_30d": total("view", d30[0]),
                         "play_taps_7d": total("play", d7[0]), "play_taps_30d": total("play", d30[0])},
                "chart": chart, "tools_30d": tools, "pages_7d": page_rows, "countries": countries,
            }
        finally:
            c.close()
