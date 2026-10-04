"""Nightly off-server backup of the licence database, via Telegram. Free.

Once a day (after BACKUP_HOUR_UTC) the sweeper takes a consistent snapshot of
licenses.db with SQLite's online-backup API, gzips it, and the licensing bot
sends it as a file to BACKUP_CHAT (defaults to LICENSE_ADMIN_CHAT — the
owner's own chat). If the server is ever lost, the latest file in that chat is
the customer list, keys and paid-until dates.

Restore:  gunzip licenses-YYYY-MM-DD.db.gz
          sudo systemctl stop staalwag-licensing
          sudo cp licenses-YYYY-MM-DD.db /var/lib/staalwag-licensing/licenses.db
          sudo chown wolf:wolf /var/lib/staalwag-licensing/licenses.db
          sudo systemctl start staalwag-licensing
"""
import datetime
import gzip
import json
import os
import sqlite3
import tempfile
import time
import urllib.request
import uuid

from . import config, notify, store

RETRY_SECONDS = 3600     # after a failed send, try again at most hourly


def snapshot():
    """Gzipped bytes of a consistent copy of the live database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        dst = sqlite3.connect(path)
        with store._LOCK:
            store._conn().backup(dst)
        dst.close()
        with open(path, "rb") as f:
            return gzip.compress(f.read())
    finally:
        os.remove(path)


def _send_document(chat_id, filename, data, caption):
    """Telegram sendDocument (multipart, stdlib only). Raises on failure."""
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in (("chat_id", str(chat_id)), ("caption", caption)):
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                      % (boundary, name, value)).encode())
    parts.append(('--%s\r\nContent-Disposition: form-data; name="document"; filename="%s"\r\n'
                  'Content-Type: application/gzip\r\n\r\n' % (boundary, filename)).encode()
                 + data + b"\r\n")
    parts.append(("--%s--\r\n" % boundary).encode())
    req = urllib.request.Request(
        "https://api.telegram.org/bot%s/sendDocument" % config.LICENSE_BOT_TOKEN,
        data=b"".join(parts),
        headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary})
    with urllib.request.urlopen(req, timeout=60) as r:
        res = json.loads(r.read() or b"{}")
    if not res.get("ok"):
        raise RuntimeError("telegram: %s" % res.get("description", res))


def run_backup(today):
    chat = config.BACKUP_CHAT
    if not (config.LICENSE_BOT_TOKEN and chat):
        raise RuntimeError("no LICENSE_BOT_TOKEN / BACKUP_CHAT set")
    data = snapshot()
    n = store.count_licenses()
    _send_document(chat, "licenses-%s.db.gz" % today, data,
                   "STAALWAG licence backup %s: %d licences, %d KB. Keep this chat."
                   % (today, n, max(1, len(data) // 1024)))


def maybe_daily(now_dt=None):
    """Called from the sweeper every minute; does the work once a day."""
    now_dt = now_dt or datetime.datetime.utcnow()
    today = now_dt.strftime("%Y-%m-%d")
    if now_dt.hour < config.BACKUP_HOUR_UTC or store.meta_get("backup_last") == today:
        return False
    if time.time() - float(store.meta_get("backup_try") or 0) < RETRY_SECONDS:
        return False
    store.meta_set("backup_try", str(time.time()))
    try:
        run_backup(today)
    except Exception as e:  # noqa: BLE001
        notify.admin("nightly backup FAILED (will retry in 1h): %s" % e)
        return False
    store.meta_set("backup_last", today)
    return True
