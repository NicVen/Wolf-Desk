"""THE WOLF — watchdog: in-process health monitor + admin alerts.

Watches every moving part of the desk from one place:

  refresh    auto-refresh pipeline loop  — heartbeat per cycle (serve.py)
  gate_bot   VIP login bot polling loop  — heartbeat per poll  (gate_bot.py)
  data:<cls> opportunities_<cls>.json freshness on disk (covers wolf_post/cron
             indirectly: if nothing regenerates the files, they go stale here)

Enforcement, not just observation:
  * Threads registered via register_thread() are RESTARTED if they die
    (crash-looping ones back off; restart count is reported).
  * Problems are pushed to ADMIN_IDS on Telegram with a cooldown so a broken
    component pings you, not spams you. Recovery is announced once.
  * status() feeds the dashboard's /health endpoint — 200 when green, 503 when
    anything is down, so any free uptime pinger can watch the watcher.

Env:
  WATCHDOG_MIN     check interval, minutes            (default 5)
  STALE_DATA_MIN   data considered stale after this   (default 3x REFRESH_MIN)
  ADMIN_IDS        comma-sep Telegram ids to alert    (shared with gate_bot)
  TELEGRAM_BOT_TOKEN  used to send the alerts
  ALERT_COOLDOWN_MIN  min gap between repeat alerts per issue (default 30)
"""
import os, json, time, datetime, threading

try:
    import truststore; truststore.inject_into_ssl()
except Exception:
    pass
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

CHECK_MIN    = int(os.environ.get("WATCHDOG_MIN", "5"))
REFRESH_MIN  = int(os.environ.get("REFRESH_MIN", "20"))
STALE_MIN    = int(os.environ.get("STALE_DATA_MIN", str(max(REFRESH_MIN, 20) * 3)))
COOLDOWN     = int(os.environ.get("ALERT_COOLDOWN_MIN", "30")) * 60
TOKEN        = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMINS       = [a.strip() for a in os.environ.get("ADMIN_IDS", "").split(",") if a.strip()]
CLASSES      = ("commodities", "fx", "indices", "stocks")

# heartbeat stall thresholds (seconds) per component
_STALL = {
    "refresh":  REFRESH_MIN * 3 * 60,   # 3 missed cycles = stalled
    "gate_bot": 5 * 60,                 # long-poll is 60s; 5 min silent = dead
    "marketer": 10 * 60,                # ticks every 60s; 10 min silent = dead
}

_LOCK     = threading.Lock()
_HB       = {}   # name -> {"ts": last beat, "ok": bool, "err": str}
_THREADS  = {}   # name -> {"factory": fn, "thread": Thread, "restarts": int}
_ALERTED  = {}   # issue key -> last alert ts (cooldown) / cleared on recovery
_STARTED  = time.time()


# ------------------------------------------------------------------ heartbeats
def beat(name, ok=True, err=""):
    """Components call this each cycle. ok=False records the error but still
    counts as a beat (the loop is alive, the work failed)."""
    with _LOCK:
        _HB[name] = {"ts": time.time(), "ok": bool(ok), "err": str(err)[:300]}


def register_thread(name, factory):
    """Start a daemon thread for `factory` and keep it alive: the watchdog
    restarts it if it ever dies. Returns the thread."""
    t = threading.Thread(target=factory, daemon=True, name=name)
    t.start()
    with _LOCK:
        _THREADS[name] = {"factory": factory, "thread": t, "restarts": 0}
    return t


# ------------------------------------------------------------------ checks
def _data_age_min(cls):
    """Minutes since opportunities_<cls>.json was generated, or None."""
    try:
        with open(os.path.join(DATA, f"opportunities_{cls}.json"), encoding="utf-8") as f:
            gen = json.load(f).get("generated", "")
        dt = datetime.datetime.strptime(gen, "%Y-%m-%d %H:%M UTC")
        return (datetime.datetime.utcnow() - dt).total_seconds() / 60.0
    except Exception:
        return None


def _problems():
    """Return {issue_key: human message} for everything currently unhealthy."""
    now = time.time()
    out = {}
    with _LOCK:
        hb = dict(_HB)
        th = {k: (v["thread"].is_alive(), v["restarts"]) for k, v in _THREADS.items()}
    # dead registered threads (restart handled by the loop, still report)
    for name, (alive, restarts) in th.items():
        if not alive:
            out["thread:" + name] = f"{name} thread DIED (restarts so far: {restarts})"
    # stalled / erroring heartbeats
    for name, limit in _STALL.items():
        h = hb.get(name)
        if h is None:
            continue   # component not running in this process (e.g. RUN_BOT=0)
        age = now - h["ts"]
        if age > limit:
            out["stall:" + name] = f"{name} silent for {age/60:.0f} min (limit {limit/60:.0f})"
        elif not h["ok"]:
            out["err:" + name] = f"{name} last cycle FAILED: {h['err']}"
    # stale data on disk
    for cls in CLASSES:
        age = _data_age_min(cls)
        if age is None:
            out["data:" + cls] = f"data/opportunities_{cls}.json missing/unreadable"
        elif age > STALE_MIN:
            out["data:" + cls] = f"{cls} data stale: {age:.0f} min old (limit {STALE_MIN})"
    return out


def status():
    """Full health report for /health. {"ok": bool, ...} — feed to a pinger."""
    with _LOCK:
        hb = {k: {"ok": v["ok"], "age_sec": int(time.time() - v["ts"]),
                  "err": v["err"]} for k, v in _HB.items()}
        th = {k: {"alive": v["thread"].is_alive(), "restarts": v["restarts"]}
              for k, v in _THREADS.items()}
    data = {}
    for cls in CLASSES:
        age = _data_age_min(cls)
        data[cls] = {"age_min": (round(age, 1) if age is not None else None),
                     "stale": (age is None or age > STALE_MIN)}
    probs = _problems()
    return {"ok": not probs, "problems": sorted(probs.values()),
            "heartbeats": hb, "threads": th, "data": data,
            "uptime_min": round((time.time() - _STARTED) / 60, 1),
            "checked": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}


# ------------------------------------------------------------------ alerts
def _send_admins(text):
    if not (TOKEN and ADMINS):
        print("WATCHDOG (no admin alert configured):", text)
        return
    for a in ADMINS:
        try:
            requests.post("https://api.telegram.org/bot%s/sendMessage" % TOKEN,
                          json={"chat_id": a, "text": text,
                                "disable_web_page_preview": True}, timeout=15)
        except Exception as e:
            print("WATCHDOG: alert send error:", e)


# ------------------------------------------------------------------ main loop
def _tick():
    # restart any dead registered thread (with restart counter)
    with _LOCK:
        dead = [(k, v) for k, v in _THREADS.items() if not v["thread"].is_alive()]
    for name, rec in dead:
        rec["restarts"] += 1
        print(f"WATCHDOG: restarting dead thread '{name}' (#{rec['restarts']})")
        t = threading.Thread(target=rec["factory"], daemon=True, name=name)
        t.start()
        with _LOCK:
            rec["thread"] = t
        _send_admins("🐺🔧 WOLF watchdog: restarted dead %s thread (restart #%d)."
                     % (name, rec["restarts"]))

    # alert on problems (cooldown per issue), announce recoveries once
    probs = _problems()
    now = time.time()
    for key, msg in probs.items():
        last = _ALERTED.get(key, 0)
        if now - last > COOLDOWN:
            _ALERTED[key] = now
            _send_admins("🐺⚠️ WOLF watchdog: " + msg)
    for key in [k for k in _ALERTED if k not in probs]:
        del _ALERTED[key]
        _send_admins("🐺✅ WOLF watchdog: recovered — %s is healthy again." % key)


def main():
    print(f"WOLF watchdog up. check every {CHECK_MIN}m, data stale after "
          f"{STALE_MIN}m, alerts -> {ADMINS or '(console only)'}")
    beat("watchdog")
    while True:
        try:
            _tick()
            beat("watchdog")
        except Exception as e:
            print("WATCHDOG: tick error:", e)
        time.sleep(CHECK_MIN * 60)


if __name__ == "__main__":
    main()
