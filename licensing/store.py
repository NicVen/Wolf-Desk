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
    c.execute("""
        CREATE TABLE IF NOT EXISTS processed_payments (
            payment_id   TEXT PRIMARY KEY,
            processed_at INTEGER
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
