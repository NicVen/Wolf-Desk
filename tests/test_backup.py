"""Nightly licence-database backup: the file is a real, restorable copy, and
it goes out once a day (with an hourly retry after a failure)."""
import datetime
import gzip
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import test_money_path  # noqa: F401  (sets the throwaway DB + env first)
from licensing import backup, config, notify, store


class Backup(unittest.TestCase):
    def setUp(self):
        self.sent = []
        for p in (mock.patch.object(backup, "_send_document",
                                    lambda chat, name, data, cap: self.sent.append((chat, name, data))),
                  mock.patch.object(config, "LICENSE_BOT_TOKEN", "tok"),
                  mock.patch.object(config, "BACKUP_CHAT", "12345"),
                  mock.patch.object(notify, "admin", lambda *a: None)):
            p.start()
            self.addCleanup(p.stop)
        store.meta_set("backup_last", "")
        store.meta_set("backup_try", "0")

    def test_snapshot_restores_the_licences(self):
        store.create("APP-BACKUP1", "APP", "keep@example.com", order_id="APP-BACKUP1", status="active")
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(os.remove, path)
        with open(path, "wb") as f:
            f.write(gzip.decompress(backup.snapshot()))
        row = sqlite3.connect(path).execute(
            "SELECT contact FROM licenses WHERE license_key='APP-BACKUP1'").fetchone()
        self.assertEqual(row[0], "keep@example.com")

    def test_sends_once_a_day_after_the_hour(self):
        early = datetime.datetime(2026, 10, 5, config.BACKUP_HOUR_UTC - 1, 30) \
            if config.BACKUP_HOUR_UTC > 0 else None
        if early:
            self.assertFalse(backup.maybe_daily(early))
        night = datetime.datetime(2026, 10, 5, config.BACKUP_HOUR_UTC, 1)
        self.assertTrue(backup.maybe_daily(night))
        self.assertFalse(backup.maybe_daily(night + datetime.timedelta(hours=3)))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][:2], ("12345", "licenses-2026-10-05.db.gz"))

    def test_failure_retries_later_not_every_minute(self):
        with mock.patch.object(backup, "_send_document", side_effect=RuntimeError("down")):
            night = datetime.datetime(2026, 10, 6, config.BACKUP_HOUR_UTC, 1)
            self.assertFalse(backup.maybe_daily(night))
        self.assertFalse(backup.maybe_daily(night))           # inside the retry hour
        store.meta_set("backup_try", "0")                      # an hour later
        self.assertTrue(backup.maybe_daily(night))


if __name__ == "__main__":
    unittest.main()
