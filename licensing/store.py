"""SQLite store for licenses. Single-file, thread-safe (one connection + lock).

A license row is the whole truth for one client's access to one product:
  status:      pending -> active -> past_due -> revoked  (or back to active on pay)
  paid_until:  epoch seconds the current paid period ends
  revoke_at:   epoch seconds access is cut (paid_until + GRACE_HOURS) while unpaid
  bind_*:      the MT5 account + machine the license locked onto (anti-sharing)
"""
import os
import sqlite3
import threading
import time

from . import config

_LOCK = threading.Lock()
_CONN = None


def _conn():
    global _CONN
    if _CONN is None:
        os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
        _CONN = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _CONN.row_factory = sqlite3.Row
        _CONN.execute("PRAGMA journal_mode=WAL")
        _init(_CONN)
    return _CONN


def _init(c):
    c.execute("""
        CREATE TABLE IF NOT EXISTS licenses (
            license_key   TEXT PRIMARY KEY,
            product       TEXT NOT NULL,
            contact       TEXT,
            status        TEXT NOT NULL,
            paid_until    INTEGER,
            revoke_at     INTEGER,
            bind_account  TEXT,
            bind_machine  TEXT,
            order_id      TEXT,
            last_payment  TEXT,
            notified      INTEGER DEFAULT 0,
            created       INTEGER,
            updated       INTEGER
        )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_order ON licenses(order_id)")
    # migrations: add columns that may not exist on older databases.
    for col, ddl in (("no_bind", "INTEGER DEFAULT 0"),
                     ("admin", "INTEGER DEFAULT 0"),
                     ("last_seen", "INTEGER"),
                     ("last_account", "TEXT"),
                     ("ref_code", "TEXT"),
                     ("referred_by", "TEXT"),
                     ("ref_rewarded", "INTEGER DEFAULT 0"),
                     ("ref_reward_until", "INTEGER"),
                     ("anon_id", "TEXT"),
                     ("trial", "INTEGER DEFAULT 0")):
        try:
            c.execute("ALTER TABLE licenses ADD COLUMN %s %s" % (col, ddl))
        except sqlite3.OperationalError:
            pass  # already exists
    c.execute("""
        CREATE TABLE IF NOT EXISTS processed_payments (
            payment_id   TEXT PRIMARY KEY,
            processed_at INTEGER
        )""")
    c.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            telegram_id  TEXT PRIMARY KEY,
            consented_at INTEGER
        )""")
    c.execute("""
        CREATE TABLE IF NOT EXISTS suggestions (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            contact  TEXT,
            text     TEXT,
            status   TEXT DEFAULT 'new',
            created  INTEGER
        )""")
    c.execute("""
        CREATE TABLE IF NOT EXISTS quiz_plays (
            license_key TEXT,
            day         TEXT,
            qids        TEXT,
            score       INTEGER,
            created     INTEGER,
            PRIMARY KEY (license_key, day)
        )""")
    try:
        c.execute("ALTER TABLE quiz_plays ADD COLUMN qids TEXT")
    except sqlite3.OperationalError:
        pass
    c.execute("""
        CREATE TABLE IF NOT EXISTS quiz_seen (
            license_key TEXT,
            qid         TEXT,
            seen_at     INTEGER,
            PRIMARY KEY (license_key, qid)
        )""")
    c.execute("""
        CREATE TABLE IF NOT EXISTS quiz_votes (
            qid   TEXT,
            opt   INTEGER,
            n     INTEGER DEFAULT 0,
            PRIMARY KEY (qid, opt)
        )""")
    c.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    c.execute("""
        CREATE TABLE IF NOT EXISTS partners (
            tag           TEXT PRIMARY KEY,
            name          TEXT,
            contact       TEXT,
            paid_refs     INTEGER DEFAULT 0,
            reward_until  INTEGER,
            created       INTEGER,
            last_ref      INTEGER
        )""")
    # migration: add reward_until to a partners table created by an earlier build
    try:
        c.execute("ALTER TABLE partners ADD COLUMN reward_until INTEGER")
    except sqlite3.OperationalError:
        pass  # already exists
    # Ideas board: suggestions gain a category, a size tag and votes.
    # status: new (awaiting owner review) -> open (public, votable) -> built
    #         | rejected.  Bugs stay private: new -> done.  Older 'done' rows were
    #         never reviewed for the public board, so they stay private too.
    for col, ddl in (("category", "TEXT DEFAULT 'other'"),
                     ("size", "TEXT DEFAULT 'small'"),
                     ("license_key", "TEXT"),
                     ("built_at", "INTEGER")):
        try:
            c.execute("ALTER TABLE suggestions ADD COLUMN %s %s" % (col, ddl))
        except sqlite3.OperationalError:
            pass
    c.execute("""
        CREATE TABLE IF NOT EXISTS suggestion_votes (
            sid          INTEGER,
            license_key  TEXT,
            created      INTEGER,
            PRIMARY KEY (sid, license_key)
        )""")
    # one-off in-app messages to a subscriber ("already built", "we built it")
    c.execute("""
        CREATE TABLE IF NOT EXISTS app_notices (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            license_key  TEXT,
            text         TEXT,
            created      INTEGER,
            seen         INTEGER DEFAULT 0
        )""")
    c.commit()


def now():
    return int(time.time())


def create(license_key, product, contact, order_id, status="pending"):
    with _LOCK:
        c = _conn()
        t = now()
        c.execute(
            "INSERT OR REPLACE INTO licenses (license_key, product, contact, status, "
            "order_id, created, updated, notified) VALUES (?,?,?,?,?,?,?,0)",
            (license_key, product, contact, status, order_id, t, t))
        c.commit()


def get(license_key):
    with _LOCK:
        r = _conn().execute("SELECT * FROM licenses WHERE license_key=?", (license_key,)).fetchone()
        return dict(r) if r else None


def get_by_order(order_id):
    with _LOCK:
        r = _conn().execute("SELECT * FROM licenses WHERE order_id=?", (order_id,)).fetchone()
        return dict(r) if r else None


def is_ref_code(code):
    """True if `code` belongs to a customer license (a customer referral),
    as opposed to an external partner banner tag."""
    return bool(get_by_ref_code(code))


def partner_get(tag):
    with _LOCK:
        r = _conn().execute("SELECT * FROM partners WHERE tag=?",
                            ((tag or "").strip()[:40],)).fetchone()
        return dict(r) if r else None


def partner_touch(tag, name="", contact=""):
    """Record one paid referral for an external partner banner tag: bump the
    conversion counter and stamp it. Does NOT grant a reward window — that is
    gated separately so rewards never stack. Returns the partner dict."""
    tag = (tag or "").strip()[:40]
    if not tag:
        return None
    t = now()
    with _LOCK:
        c = _conn()
        row = c.execute("SELECT * FROM partners WHERE tag=?", (tag,)).fetchone()
        if row:
            c.execute("UPDATE partners SET paid_refs=paid_refs+1, last_ref=?, "
                      "name=COALESCE(NULLIF(?,''),name), "
                      "contact=COALESCE(NULLIF(?,''),contact) WHERE tag=?",
                      (t, name, contact, tag))
        else:
            c.execute("INSERT INTO partners (tag,name,contact,paid_refs,reward_until,"
                      "created,last_ref) VALUES (?,?,?,1,0,?,?)",
                      (tag, name, contact, t, t))
        c.commit()
        return dict(c.execute("SELECT * FROM partners WHERE tag=?", (tag,)).fetchone())


def partner_open_window(tag, days):
    """Open a fresh no-stack reward window for the partner: reward_until = now +
    days. Callers must check the partner is NOT already inside a window first."""
    with _LOCK:
        c = _conn()
        c.execute("UPDATE partners SET reward_until=? WHERE tag=?",
                  (now() + int(days) * 86400, (tag or "").strip()[:40]))
        c.commit()


def partner_set_contact(tag, contact):
    with _LOCK:
        c = _conn()
        c.execute("UPDATE partners SET contact=? WHERE tag=?",
                  (contact, (tag or "").strip()[:40]))
        c.commit()


def partner_list():
    with _LOCK:
        rows = _conn().execute(
            "SELECT * FROM partners ORDER BY paid_refs DESC, last_ref DESC").fetchall()
        return [dict(r) for r in rows]


def trial_used(contact, product):
    """True if this contact already claimed a free trial for this product.
    Keeps the public trial endpoint from being farmed for endless free keys."""
    if not contact:
        return False
    with _LOCK:
        r = _conn().execute(
            "SELECT 1 FROM licenses WHERE contact=? AND product=? AND trial=1 LIMIT 1",
            (contact, product.upper())).fetchone()
        return bool(r)


def update(license_key, **fields):
    if not fields:
        return
    fields["updated"] = now()
    cols = ", ".join("%s=?" % k for k in fields)
    with _LOCK:
        c = _conn()
        c.execute("UPDATE licenses SET %s WHERE license_key=?" % cols,
                  tuple(fields.values()) + (license_key,))
        c.commit()


def all_active_or_pastdue():
    with _LOCK:
        rows = _conn().execute(
            "SELECT * FROM licenses WHERE status IN ('active','past_due')").fetchall()
        return [dict(r) for r in rows]


def all_licenses():
    """Every license row, newest activity first (for the admin control view)."""
    with _LOCK:
        rows = _conn().execute("SELECT * FROM licenses ORDER BY updated DESC").fetchall()
        return [dict(r) for r in rows]


def get_by_ref_code(code):
    """The license that owns this referral code, or None."""
    if not code:
        return None
    with _LOCK:
        r = _conn().execute("SELECT * FROM licenses WHERE ref_code=? LIMIT 1", (code,)).fetchone()
        return dict(r) if r else None


def count_referrals(code):
    """(total_paid_referrals, free_months_granted) for this referral code."""
    if not code:
        return 0, 0
    with _LOCK:
        c = _conn()
        total = c.execute("SELECT COUNT(*) n FROM licenses WHERE referred_by=? AND ref_rewarded IN (1,2)",
                          (code,)).fetchone()["n"]
        granted = c.execute("SELECT COUNT(*) n FROM licenses WHERE referred_by=? AND ref_rewarded=1",
                            (code,)).fetchone()["n"]
        return total, granted


def active_contacts(product):
    """Distinct contacts holding a live (active/past_due) license for `product`."""
    with _LOCK:
        rows = _conn().execute(
            "SELECT DISTINCT contact FROM licenses WHERE product=? "
            "AND status IN ('active','past_due') AND contact IS NOT NULL AND contact!=''",
            (product.upper(),)).fetchall()
        return [r["contact"] for r in rows]


def has_active_vip(contact):
    """True if this contact holds a live VIP membership (for add-on pricing)."""
    if not contact:
        return False
    with _LOCK:
        r = _conn().execute(
            "SELECT 1 FROM licenses WHERE contact=? AND product='VIP' "
            "AND status='active' AND paid_until>? LIMIT 1", (contact, now())).fetchone()
        return bool(r)


def subscriber_exists(telegram_id):
    with _LOCK:
        r = _conn().execute("SELECT 1 FROM subscribers WHERE telegram_id=?", (telegram_id,)).fetchone()
        return bool(r)


def add_subscriber(telegram_id):
    with _LOCK:
        c = _conn()
        c.execute("INSERT OR IGNORE INTO subscribers (telegram_id, consented_at) VALUES (?,?)",
                  (telegram_id, now()))
        c.commit()


IDEA_CATEGORIES = ("signals", "charts", "alerts", "quiz", "bug", "other")


def add_suggestion(contact, text, category="other", license_key=""):
    """Store a suggestion; the sender's own vote counts as the first. Returns id."""
    category = category if category in IDEA_CATEGORIES else "other"
    with _LOCK:
        c = _conn()
        cur = c.execute("INSERT INTO suggestions (contact, text, status, created, category, license_key) "
                        "VALUES (?,?, 'new', ?, ?, ?)",
                        (contact or "", text, now(), category, license_key or ""))
        sid = cur.lastrowid
        if license_key and category != "bug":
            c.execute("INSERT OR IGNORE INTO suggestion_votes (sid, license_key, created) VALUES (?,?,?)",
                      (sid, license_key, now()))
        c.commit()
        return sid


_VOTES_SQL = "(SELECT COUNT(*) FROM suggestion_votes v WHERE v.sid=s.id)"


def list_suggestions(limit=200, status=None):
    with _LOCK:
        c = _conn()
        sql = "SELECT s.*, %s AS votes FROM suggestions s" % _VOTES_SQL
        if status:
            rows = c.execute(sql + " WHERE s.status=? ORDER BY s.created DESC LIMIT ?",
                             (status, limit)).fetchall()
        else:
            rows = c.execute(sql + " ORDER BY s.created DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


def get_suggestion(sid):
    with _LOCK:
        r = _conn().execute("SELECT s.*, %s AS votes FROM suggestions s WHERE s.id=?" % _VOTES_SQL,
                            (int(sid),)).fetchone()
        return dict(r) if r else None


def set_suggestion_status(sid, status, size=None):
    with _LOCK:
        c = _conn()
        if status == "built":
            c.execute("UPDATE suggestions SET status=?, built_at=? WHERE id=?", (status, now(), int(sid)))
        elif status:
            c.execute("UPDATE suggestions SET status=? WHERE id=?", (status, int(sid)))
        if size in ("small", "big"):
            c.execute("UPDATE suggestions SET size=? WHERE id=?", (size, int(sid)))
        c.commit()


def public_ideas(license_key="", built_days=365):
    """What every subscriber sees: approved ideas with live vote counts, plus
    recently built ones. Never names, never bugs, never unreviewed ideas."""
    cutoff = now() - built_days * 86400
    with _LOCK:
        rows = _conn().execute(
            "SELECT s.id, s.text, s.category, s.size, s.status, s.built_at, %s AS votes, "
            "EXISTS(SELECT 1 FROM suggestion_votes v WHERE v.sid=s.id AND v.license_key=?) AS mine "
            "FROM suggestions s WHERE s.category!='bug' AND "
            "(s.status='open' OR (s.status='built' AND s.built_at>=?)) "
            "ORDER BY votes DESC, s.created ASC" % _VOTES_SQL,
            (license_key or "", cutoff)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["mine"] = bool(d["mine"])
        out.append(d)
    return out


def toggle_vote(sid, license_key):
    """One vote per subscriber per idea; tapping again takes it back.
    Returns (ok, voted, count)."""
    with _LOCK:
        c = _conn()
        r = c.execute("SELECT status, category FROM suggestions WHERE id=?", (int(sid),)).fetchone()
        if not r or r["status"] != "open" or r["category"] == "bug":
            return False, False, 0
        had = c.execute("SELECT 1 FROM suggestion_votes WHERE sid=? AND license_key=?",
                        (int(sid), license_key)).fetchone()
        if had:
            c.execute("DELETE FROM suggestion_votes WHERE sid=? AND license_key=?", (int(sid), license_key))
        else:
            c.execute("INSERT INTO suggestion_votes (sid, license_key, created) VALUES (?,?,?)",
                      (int(sid), license_key, now()))
        c.commit()
        n = c.execute("SELECT COUNT(*) FROM suggestion_votes WHERE sid=?", (int(sid),)).fetchone()[0]
        return True, not had, n


def idea_voters(sid):
    with _LOCK:
        rows = _conn().execute("SELECT license_key FROM suggestion_votes WHERE sid=?", (int(sid),)).fetchall()
        return [r["license_key"] for r in rows]


def add_notice(license_key, text):
    if not license_key:
        return
    with _LOCK:
        c = _conn()
        c.execute("INSERT INTO app_notices (license_key, text, created) VALUES (?,?,?)",
                  (license_key, text, now()))
        c.commit()


def pop_notices(license_key):
    """Unseen in-app messages for this subscriber; marks them seen."""
    with _LOCK:
        c = _conn()
        rows = c.execute("SELECT id, text FROM app_notices WHERE license_key=? AND seen=0 ORDER BY id",
                         (license_key,)).fetchall()
        if rows:
            c.execute("UPDATE app_notices SET seen=1 WHERE license_key=? AND seen=0", (license_key,))
            c.commit()
        return [r["text"] for r in rows]


def open_bugs():
    with _LOCK:
        rows = _conn().execute("SELECT * FROM suggestions WHERE category='bug' AND status='new' "
                               "ORDER BY created ASC").fetchall()
        return [dict(r) for r in rows]


def top_ideas(size, limit=5):
    with _LOCK:
        rows = _conn().execute(
            "SELECT s.id, s.text, s.category, %s AS votes FROM suggestions s "
            "WHERE s.status='open' AND s.category!='bug' AND COALESCE(s.size,'small')=? "
            "ORDER BY votes DESC, s.created ASC LIMIT ?" % _VOTES_SQL, (size, limit)).fetchall()
        return [dict(r) for r in rows]


def app_stats(active_days=7):
    """Metrics for the STAALCALIBUR mobile app (product APP)."""
    cutoff = now() - active_days * 86400
    cutoff1 = now() - 86400
    with _LOCK:
        c = _conn()
        q = lambda sql, *a: c.execute(sql, a).fetchone()[0]
        installed = q("SELECT COUNT(*) FROM licenses WHERE product='APP'")
        subscribed = q("SELECT COUNT(*) FROM licenses WHERE product='APP' AND status IN ('active','past_due')")
        active7 = q("SELECT COUNT(*) FROM licenses WHERE product='APP' AND last_seen>=?", cutoff)
        active1 = q("SELECT COUNT(*) FROM licenses WHERE product='APP' AND last_seen>=?", cutoff1)
        sharers = q("SELECT COUNT(*) FROM licenses WHERE product='APP' AND ref_code IS NOT NULL AND ref_code!=''")
        promoters = q("SELECT COUNT(DISTINCT referred_by) FROM licenses "
                      "WHERE referred_by IS NOT NULL AND referred_by!='' AND ref_rewarded IN (1,2)")
        referrals = q("SELECT COUNT(*) FROM licenses WHERE referred_by IS NOT NULL AND referred_by!='' AND ref_rewarded IN (1,2)")
        free_granted = q("SELECT COUNT(*) FROM licenses WHERE ref_rewarded=1")
        suggestions_new = q("SELECT COUNT(*) FROM suggestions WHERE status='new'")
    return {
        "installed": installed, "subscribed": subscribed,
        "active_7d": active7, "active_24h": active1,
        "sharers": sharers, "promoters": promoters,
        "referrals": referrals, "free_months_granted": free_granted,
        "suggestions_new": suggestions_new, "active_days": active_days,
    }


import secrets as _secrets


def ensure_anon(license_key):
    """Random, unlinkable public id for a subscriber (privacy in leaderboards)."""
    lic = get(license_key)
    if not lic:
        return None
    if lic.get("anon_id"):
        return lic["anon_id"]
    for _ in range(20):
        aid = "SC-" + _secrets.token_hex(3).upper()
        with _LOCK:
            exists = _conn().execute("SELECT 1 FROM licenses WHERE anon_id=?", (aid,)).fetchone()
        if not exists:
            update(license_key, anon_id=aid)
            return aid
    return "SC-" + _secrets.token_hex(4).upper()


def quiz_get_play(license_key, day):
    """Today's play row: {qids:[...], score:int|None} or None."""
    with _LOCK:
        r = _conn().execute("SELECT qids, score FROM quiz_plays WHERE license_key=? AND day=?",
                            (license_key, day)).fetchone()
    if not r:
        return None
    import json as _json
    try:
        qids = _json.loads(r["qids"]) if r["qids"] else []
    except Exception:
        qids = []
    return {"qids": qids, "score": r["score"]}


def quiz_seen_ids(license_key):
    with _LOCK:
        rows = _conn().execute("SELECT qid FROM quiz_seen WHERE license_key=?", (license_key,)).fetchall()
        return {r["qid"] for r in rows}


def quiz_start_play(license_key, day, qids):
    """Create today's row with the served questions and mark them permanently
    seen for this player (so they're never asked again)."""
    import json as _json
    t = now()
    with _LOCK:
        c = _conn()
        c.execute("INSERT OR IGNORE INTO quiz_plays (license_key, day, qids, score, created) "
                  "VALUES (?,?,?,NULL,?)", (license_key, day, _json.dumps(qids), t))
        for qid in qids:
            c.execute("INSERT OR IGNORE INTO quiz_seen (license_key, qid, seen_at) VALUES (?,?,?)",
                      (license_key, qid, t))
        c.commit()


def quiz_set_score(license_key, day, score):
    with _LOCK:
        c = _conn()
        c.execute("UPDATE quiz_plays SET score=? WHERE license_key=? AND day=?",
                  (score, license_key, day))
        c.commit()


def quiz_bump_votes(pairs):
    """pairs: list of (qid, opt) — increment each option's tally."""
    with _LOCK:
        c = _conn()
        for qid, opt in pairs:
            c.execute("INSERT INTO quiz_votes (qid, opt, n) VALUES (?,?,1) "
                      "ON CONFLICT(qid,opt) DO UPDATE SET n=n+1", (qid, int(opt)))
        c.commit()


def quiz_poll(qid, n_opts):
    with _LOCK:
        rows = _conn().execute("SELECT opt, n FROM quiz_votes WHERE qid=?", (qid,)).fetchall()
    counts = [0] * n_opts
    for r in rows:
        if 0 <= r["opt"] < n_opts:
            counts[r["opt"]] = r["n"]
    return counts


def quiz_month_points(license_key, period):
    with _LOCK:
        r = _conn().execute(
            "SELECT COALESCE(SUM(score),0) p FROM quiz_plays WHERE license_key=? AND substr(day,1,7)=?",
            (license_key, period)).fetchone()
        return r["p"] or 0


def quiz_leaderboard(period, limit=10):
    """[(anon_id, points, license_key)] for a period, best first."""
    with _LOCK:
        rows = _conn().execute(
            "SELECT p.license_key k, COALESCE(SUM(p.score),0) pts, l.anon_id aid "
            "FROM quiz_plays p LEFT JOIN licenses l ON l.license_key=p.license_key "
            "WHERE substr(p.day,1,7)=? GROUP BY p.license_key ORDER BY pts DESC, MIN(p.created) ASC "
            "LIMIT ?", (period, limit)).fetchall()
        return [(r["aid"] or "SC-?????", r["pts"], r["k"]) for r in rows]


def quiz_stats(period, day):
    """Live quiz metrics for the admin console."""
    with _LOCK:
        c = _conn()
        one = lambda sql, *a: c.execute(sql, a).fetchone()[0]
        players = one("SELECT COUNT(DISTINCT license_key) FROM quiz_plays WHERE substr(day,1,7)=? AND score IS NOT NULL", period)
        plays_month = one("SELECT COUNT(*) FROM quiz_plays WHERE substr(day,1,7)=? AND score IS NOT NULL", period)
        plays_today = one("SELECT COUNT(*) FROM quiz_plays WHERE day=? AND score IS NOT NULL", day)
        avg = one("SELECT COALESCE(ROUND(AVG(score),1),0) FROM quiz_plays WHERE substr(day,1,7)=? AND score IS NOT NULL", period)
    lb = quiz_leaderboard(period, 10)
    return {"period": period, "players": players, "plays_month": plays_month,
            "plays_today": plays_today, "avg_score": avg,
            "leader": ({"anon": lb[0][0], "points": lb[0][1]} if lb else None),
            "leaderboard": [{"anon": a, "points": p} for (a, p, k) in lb]}


def quiz_rank(license_key, period):
    """(rank, total_players) for this key in the period; rank None if no plays."""
    with _LOCK:
        rows = _conn().execute(
            "SELECT license_key k, COALESCE(SUM(score),0) pts FROM quiz_plays "
            "WHERE substr(day,1,7)=? GROUP BY license_key ORDER BY pts DESC", (period,)).fetchall()
    total = len(rows)
    for i, r in enumerate(rows, 1):
        if r["k"] == license_key:
            return i, total
    return None, total


def count_licenses():
    with _LOCK:
        return _conn().execute("SELECT COUNT(*) FROM licenses").fetchone()[0]


def meta_get(k, default=None):
    with _LOCK:
        r = _conn().execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r["v"] if r else default


def meta_set(k, v):
    with _LOCK:
        c = _conn()
        c.execute("INSERT INTO meta (k, v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=?", (k, v, v))
        c.commit()


def payment_seen(payment_id):
    """True if we already processed this NOWPayments payment id (idempotency)."""
    with _LOCK:
        c = _conn()
        r = c.execute("SELECT 1 FROM processed_payments WHERE payment_id=?", (payment_id,)).fetchone()
        if r:
            return True
        c.execute("INSERT INTO processed_payments (payment_id, processed_at) VALUES (?,?)",
                  (payment_id, now()))
        c.commit()
        return False
