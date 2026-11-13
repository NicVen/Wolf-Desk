"""Google Play report sync: parsing, history, setup state (no network).

Run:  python -m unittest discover -s tests -v
"""
import datetime
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import play_sync  # noqa: E402

HEAD = ("Date,Package Name,Daily Device Installs,Daily Device Uninstalls,Daily Device Upgrades,"
        "Total User Installs,Daily User Installs,Daily User Uninstalls,Active Device Installs,"
        "Install events,Update events,Uninstall events\n")
OVERVIEW = HEAD + (
    "2026-10-09,com.staalwag.staalcalibur,12,0,0,12,12,0,12,12,0,0\n"
    "2026-10-28,com.staalwag.staalcalibur,20,1,0,32,20,1,31,20,0,1\n"
    "2026-11-12,com.staalwag.staalcalibur,3,2,0,35,3,2,32,3,0,2\n")
COUNTRY = ("Date,Package Name,Country,Daily Device Installs,Daily Device Uninstalls,Daily Device Upgrades,"
           "Total User Installs,Daily User Installs,Daily User Uninstalls,Active Device Installs,"
           "Install events,Update events,Uninstall events\n"
           "2026-11-12,com.staalwag.staalcalibur,NZ,2,1,0,20,2,1,18,2,0,1\n"
           "2026-11-12,com.staalwag.staalcalibur,ZA,1,1,0,15,1,1,14,1,0,1\n")


class PlaySyncTest(unittest.TestCase):
    def test_reads_utf16_reports_and_keeps_testing_history(self):
        ov = play_sync.decode_csv(OVERVIEW.encode("utf-16"))
        cc = play_sync.decode_csv(COUNTRY.encode("utf-16"))
        s = play_sync.summarise(ov, cc, synced="x")
        self.assertEqual(s["first_day"], "2026-10-09")      # closed-test install day kept
        self.assertEqual(s["latest_day"], "2026-11-12")
        self.assertEqual(s["active_devices"], 32)
        self.assertEqual(s["total_user_installs"], 35)
        self.assertEqual(s["installs_all"], 35)
        self.assertEqual(s["uninstalls_all"], 3)
        self.assertEqual(len(s["daily"]), 3)
        self.assertEqual([c["cc"] for c in s["countries"]], ["NZ", "ZA"])
        self.assertEqual(s["countries"][0]["active"], 18)

    def test_utf8_and_empty(self):
        self.assertEqual(len(play_sync.decode_csv(OVERVIEW.encode("utf-8"))), 3)
        self.assertEqual(play_sync.decode_csv(None), [])
        self.assertEqual(play_sync.summarise([], [])["active_devices"], 0)

    def test_bucket_from_copied_uri(self):
        self.assertEqual(play_sync.clean_bucket("gs://pubsite_prod_123/stats/installs/"), "pubsite_prod_123")
        self.assertEqual(play_sync.clean_bucket(" pubsite_prod_rev_9 "), "pubsite_prod_rev_9")

    def test_months_start_before_closed_test(self):
        m = play_sync._months(datetime.datetime(2026, 11, 14))
        self.assertEqual(m, ["202609", "202610", "202611"])
        self.assertEqual(play_sync._months(datetime.datetime(2027, 1, 2))[-2:], ["202612", "202701"])

    def test_not_set_up_does_nothing(self):
        old = play_sync.KEY_FILE, play_sync.OUT
        with tempfile.TemporaryDirectory() as d:
            play_sync.KEY_FILE = os.path.join(d, "none.json")
            play_sync.OUT = os.path.join(d, "out.json")
            try:
                self.assertIsNone(play_sync.sync_once())
                self.assertEqual(play_sync.load()["status"]["state"], "not_set_up")
            finally:
                play_sync.KEY_FILE, play_sync.OUT = old

    def test_jwt_signature_verifies(self):
        with tempfile.TemporaryDirectory() as d:
            key = os.path.join(d, "k.pem"); pub = os.path.join(d, "p.pem"); sig = os.path.join(d, "s")
            subprocess.run(["openssl", "genrsa", "-out", key, "2048"], check=True, capture_output=True)
            subprocess.run(["openssl", "rsa", "-in", key, "-pubout", "-out", pub], check=True, capture_output=True)
            open(sig, "wb").write(play_sync._sign_rs256(open(key).read(), b"hello.world"))
            r = subprocess.run(["openssl", "dgst", "-sha256", "-verify", pub, "-signature", sig],
                               input=b"hello.world", capture_output=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
