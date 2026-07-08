"""THE WOLF — marketing bot (in-process): campaign CRM + scheduler + reports.

Runs alongside the desk (serve.py starts it, the watchdog keeps it alive) and
is driven from Telegram through the gate bot. Admin commands:

  /mkt                      help + this week's numbers at a glance
  /addch <code> <@ch> [price] [notes]   track a promo target channel
  /chst  <code> <status>    contacted | agreed | posted | dead
  /channels                 pipeline: every tracked channel + status + joins
  /followup                 who's gone quiet (contacted, no post, 3+ days)
  /report                   full marketing report now (auto every Monday)
  /copy [gold|fx|all]       ad copy variants to paste anywhere

Works with /ad (gate_bot): /addch the channel first, use the same code in
/ad, and the pipeline + join tracking line up automatically.

Scheduler (UTC, all optional):
  WEEKLY_REPORT_DOW / _HOUR  default Monday 08:00 — report to ADMIN_IDS
  DAILY_POST_HOUR            unset = off. Set (e.g. 7) to fire wolf_post
                             daily in-process — remove any Railway cron
                             first or you'll double-post.
"""
import os, io, time, sqlite3, datetime, contextlib

try:
    import truststore; truststore.inject_into_ssl()
except Exception:
    pass
import requests

HERE   = os.path.dirname(os.path.abspath(__file__))
TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMINS = [a.strip() for a in os.environ.get("ADMIN_IDS", "").split(",") if a.strip()]
DB     = os.environ.get("GROWTH_DB", os.path.join(HERE, "growth.db"))
API    = "https://api.telegram.org/bot%s/" % TOKEN

REPORT_DOW  = int(os.environ.get("WEEKLY_REPORT_DOW", "0"))    # 0 = Monday
REPORT_HOUR = int(os.environ.get("WEEKLY_REPORT_HOUR", "8"))
POST_HOUR   = os.environ.get("DAILY_POST_HOUR", "")            # off unless set

STATUSES = ("prospect", "contacted", "agreed", "posted", "dead")

COPY = {
  "gold": ["🐺 THE WOLF — daily gold & commodities reads, scored 0-100 with "
           "full case files. Every call logged publicly. Free channel:",
           "Gold traders: one desk, one daily read — trend, regime, catalyst, "
           "verdict. Track record builds in the open. 🐺 Free:"],
  "fx":   ["🐺 THE WOLF FX desk — majors & JPY crosses read daily: score, "
           "regime, case file. No cherry-picking, every call logged. Free:",
           "Your FX second opinion: daily BUY/SELL reads with the reasoning "
           "shown. 🐺 Watch the record build live. Free:"],
  "all":  ["🐺 THE WOLF — gold, FX, indices & stocks. Daily intel reads, "
           "public track record, full case files. Free:",
           "One desk for the whole tape: daily scored reads on gold, FX, "
           "indices & stocks. 🐺 Logged publicly. Free:"],
}


# ------------------------------------------------------------------ storage
def _db():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS campaigns(
        code TEXT PRIMARY KEY, channel TEXT, price TEXT, notes TEXT,
        status TEXT, added REAL, updated REAL)""")
    c.execute("CREATE TABLE IF NOT EXISTS mkt_state(key TEXT PRIMARY KEY, val TEXT)")
    return c

def _state(c, key, val=None):
    if val is None:
        r = c.execute("SELECT val FROM mkt_state WHERE key=?", (key,)).fetchone()
        return r[0] if r else ""
    c.execute("INSERT OR REPLACE INTO mkt_state(key,val) VALUES(?,?)", (key, val))
    c.commit()

def _joins(c, code):
    try:
        return c.execute("SELECT COUNT(*) FROM members WHERE ref_by=?",
                         ("promo-" + code,)).fetchone()[0]
    except Exception:
        return 0


# ------------------------------------------------------------------ telegram
def _send(chat_id, text):
    try:
        requests.post(API + "sendMessage",
                      json={"chat_id": chat_id, "text": text,
                            "disable_web_page_preview": True}, timeout=15)
    except Exception as e:
        print("marketer: send error:", e)

def _ping_admins(text):
    if not (TOKEN and ADMINS):
        print("MARKETER (no admins configured):\n" + text)
        return
    for a in ADMINS:
        _send(a, text)


# ------------------------------------------------------------------ reports
def _week_numbers():
    c = _db(); now = time.time()
    try:
        total = c.execute("SELECT COUNT(*) FROM members").fetchone()[0]
        new7  = c.execute("SELECT COUNT(*) FROM members WHERE joined>?",
                          (now - 7 * 86400,)).fetchone()[0]
        promo7 = c.execute("""SELECT COUNT(*) FROM members
                              WHERE ref_by LIKE 'promo-%' AND joined>?""",
                           (now - 7 * 86400,)).fetchone()[0]
    except Exception:
        total = new7 = promo7 = 0
    pipe = dict(c.execute("SELECT status, COUNT(*) FROM campaigns GROUP BY status").fetchall())
    c.close()
    return total, new7, promo7, pipe

def compose_report():
    c = _db(); now = time.time()
    total, new7, promo7, pipe = _week_numbers()
    L = ["📈 WOLF MARKETING REPORT — %s" % datetime.datetime.utcnow().strftime("%d %b %Y"),
         "",
         "Members seen: %d  (+%d this week, %d via promos)" % (total, new7, promo7)]
    try:
        rows = c.execute("""SELECT ref_by, COUNT(*) n FROM members
                            WHERE ref_by LIKE 'promo-%' GROUP BY ref_by
                            ORDER BY n DESC LIMIT 8""").fetchall()
    except Exception:
        rows = []
    if rows:
        L += ["", "Promo joins (all time):"]
        L += ["  %s — %d" % (r[0].replace("promo-", "", 1), r[1]) for r in rows]
    camps = c.execute("""SELECT code, channel, price, status FROM campaigns
                         WHERE status!='dead' ORDER BY updated DESC LIMIT 12""").fetchall()
    if camps:
        L += ["", "Pipeline:"]
        for code, ch, price, st in camps:
            L.append("  %s %s — %s%s · %d joins"
                     % ({"prospect": "◻️", "contacted": "✉️", "agreed": "🤝",
                         "posted": "✅"}.get(st, "·"), code, st,
                        (" · %s" % price) if price else "", _joins(c, code)))
    stale = c.execute("""SELECT code FROM campaigns
                         WHERE status='contacted' AND updated<?""",
                      (now - 3 * 86400,)).fetchall()
    if stale:
        L += ["", "⏰ Chase these (contacted 3+ days, no post): "
              + ", ".join(s[0] for s in stale)]
    c.close()
    L += ["", "Next: /channels for the pipeline · /ad <code> for a new ad "
          "· /copy for fresh copy"]
    return "\n".join(L)


# ------------------------------------------------------------------ commands
def handle(low, text, uid, chat_id, send):
    """Admin marketing commands, called from gate_bot. True = handled."""
    parts = text.split()

    if low.startswith("/mkt"):
        total, new7, promo7, pipe = _week_numbers()
        send(chat_id,
             "🐺 MARKETING DESK\n"
             "This week: +%d members (%d via promos) · %d seen total\n"
             "Pipeline: %s\n\n"
             "/addch <code> <@ch> [price] [notes] — track a channel\n"
             "/chst <code> <status> — %s\n"
             "/channels · /followup · /report · /copy [gold|fx|all]\n"
             "/ad <code> [desk] — build the branded ad post"
             % (new7, promo7, total,
                ", ".join("%s %d" % kv for kv in pipe.items()) or "empty",
                "|".join(STATUSES)))
        return True

    if low.startswith("/addch"):
        if len(parts) < 3:
            send(chat_id, "Usage: /addch <code> <@channel> [price] [notes]"); return True
        code, ch = parts[1].lower(), parts[2]
        price = parts[3] if len(parts) > 3 else ""
        notes = " ".join(parts[4:])
        c = _db()
        c.execute("""INSERT OR REPLACE INTO campaigns(code,channel,price,notes,status,added,updated)
                     VALUES(?,?,?,?,?,?,?)""",
                  (code, ch, price, notes, "prospect", time.time(), time.time()))
        c.commit(); c.close()
        send(chat_id, "Tracking %s (%s)%s. Next: DM the admin, then /chst %s contacted"
             % (code, ch, (" at %s" % price) if price else "", code))
        return True

    if low.startswith("/chst"):
        if len(parts) < 3 or parts[2].lower() not in STATUSES:
            send(chat_id, "Usage: /chst <code> <%s>" % "|".join(STATUSES)); return True
        code, st = parts[1].lower(), parts[2].lower()
        c = _db()
        n = c.execute("UPDATE campaigns SET status=?, updated=? WHERE code=?",
                      (st, time.time(), code)).rowcount
        c.commit(); c.close()
        send(chat_id, ("%s -> %s ✔" % (code, st)) if n else
             "Unknown code %s — /addch it first or check /channels" % code)
        return True

    if low.startswith("/channels"):
        c = _db()
        rows = c.execute("""SELECT code, channel, price, status FROM campaigns
                            ORDER BY updated DESC LIMIT 25""").fetchall()
        if not rows:
            send(chat_id, "No channels tracked yet. Start: /addch goldhub24 @somegoldchannel 30usd")
            c.close(); return True
        L = ["📋 Promo pipeline:"]
        for code, ch, price, st in rows:
            L.append("%s %s (%s) — %s%s · %d joins"
                     % ({"prospect": "◻️", "contacted": "✉️", "agreed": "🤝",
                         "posted": "✅", "dead": "☠️"}.get(st, "·"),
                        code, ch, st, (" · %s" % price) if price else "", _joins(c, code)))
        c.close(); send(chat_id, "\n".join(L)); return True

    if low.startswith("/followup"):
        c = _db()
        rows = c.execute("""SELECT code, channel, updated FROM campaigns
                            WHERE status='contacted' AND updated<?""",
                         (time.time() - 3 * 86400,)).fetchall()
        c.close()
        if not rows:
            send(chat_id, "Nobody to chase — pipeline is moving. 🐺"); return True
        L = ["⏰ Chase these (contacted, no post yet):"]
        L += ["  %s (%s) — %d days quiet" % (cd, ch, (time.time() - up) / 86400)
              for cd, ch, up in rows]
        send(chat_id, "\n".join(L)); return True

    if low.startswith("/report"):
        send(chat_id, compose_report()); return True

    if low.startswith("/copy"):
        desk = parts[1].lower() if len(parts) > 1 and parts[1].lower() in COPY else "all"
        send(chat_id, ("✍️ Copy variants [%s] — pair with a tracked link from /ad:\n\n"
                       % desk) + "\n\n".join("%d) %s" % (i + 1, v)
                                             for i, v in enumerate(COPY[desk])))
        return True

    return False


# ------------------------------------------------------------------ scheduler
def _maybe_daily_post(c, now):
    if POST_HOUR == "" or now.hour != int(POST_HOUR):
        return
    if _state(c, "last_post_day") == now.strftime("%Y%m%d"):
        return
    _state(c, "last_post_day", now.strftime("%Y%m%d"))
    print("MARKETER: firing daily posts (wolf_post)")
    try:
        import wolf_post
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            wolf_post.main()
        tail = "\n".join(buf.getvalue().strip().splitlines()[-4:])
        _ping_admins("📣 Daily posts fired:\n" + tail)
    except Exception as e:
        _ping_admins("⚠️ Daily post FAILED: %s" % e)

def _maybe_weekly_report(c, now):
    if now.weekday() != REPORT_DOW or now.hour != REPORT_HOUR:
        return
    if _state(c, "last_report_day") == now.strftime("%Y%m%d"):
        return
    _state(c, "last_report_day", now.strftime("%Y%m%d"))
    _ping_admins(compose_report())

def main():
    try:
        import watchdog
    except Exception:
        watchdog = None
    print("WOLF marketer up. weekly report: dow %d %02d:00 UTC, daily post: %s"
          % (REPORT_DOW, REPORT_HOUR, ("%s:00 UTC" % POST_HOUR) if POST_HOUR else "off"))
    while True:
        try:
            now = datetime.datetime.utcnow()
            c = _db()
            _maybe_weekly_report(c, now)
            _maybe_daily_post(c, now)
            c.close()
            if watchdog:
                watchdog.beat("marketer")
        except Exception as e:
            print("marketer: loop error:", e)
            if watchdog:
                watchdog.beat("marketer", ok=False, err=e)
        time.sleep(60)


if __name__ == "__main__":
    main()
