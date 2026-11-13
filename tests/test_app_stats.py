"""Anonymous app/site stats: counts work, and no personal data is stored.

Run:  python -m unittest discover -s tests -v
"""
import datetime
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import app_stats  # noqa: E402
import serve  # noqa: E402

DAY = datetime.datetime(2026, 11, 14, 12, 0)


class AppStatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app_stats.DB = os.path.join(self.tmp.name, "s.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_country_from_time_zone(self):
        self.assertEqual(app_stats.country("Pacific/Auckland"), "NZ")
        self.assertEqual(app_stats.country("Africa/Johannesburg"), "ZA")
        self.assertEqual(app_stats.country("Asia/Calcutta"), "IN")   # old alias
        self.assertEqual(app_stats.country("Mars/Base"), "??")

    def test_counts_installs_usage_and_countries(self):
        r = app_stats.record
        r({"e": "open", "d": "phone-aaa", "tz": "Pacific/Auckland", "app": 1}, DAY)
        r({"e": "open", "d": "phone-aaa", "tz": "Pacific/Auckland", "app": 1}, DAY)
        r({"e": "tool", "k": "risk-sizer", "d": "phone-aaa", "tz": "Pacific/Auckland", "app": 1}, DAY)
        r({"e": "open", "d": "phone-bbb", "tz": "Africa/Johannesburg", "app": 1},
          DAY - datetime.timedelta(days=40))
        r({"e": "open", "d": "browser-ccc", "tz": "Europe/London"}, DAY)
        r({"e": "view", "k": "margin-calculator", "tz": "Europe/London"}, DAY)
        r({"e": "play", "k": "margin-calculator", "tz": "Europe/London"}, DAY)
        s = app_stats.stats(DAY)
        a = s["app"]
        self.assertEqual(a["installs_seen"], 2)
        self.assertEqual(a["browser_users"], 1)
        self.assertEqual(a["active"]["today"], 2)          # aaa + ccc
        self.assertEqual(a["probably_uninstalled"], 1)     # bbb, quiet 40 days
        self.assertEqual(a["opens_today"], 3)
        self.assertEqual(s["tools_30d"], [{"tool": "risk-sizer", "uses": 1}])
        self.assertEqual(s["pages_7d"], [{"page": "margin-calculator", "views": 1, "play_taps": 1}])
        cc = {c["cc"]: c for c in s["countries"]}
        self.assertEqual(cc["NZ"]["installs"], 1)
        self.assertEqual(cc["GB"]["play_taps_30d"], 1)
        self.assertEqual(cc["ZA"]["country"], "South Africa")

    def test_ignores_junk(self):
        self.assertFalse(app_stats.record({"e": "hack", "k": "x"}))
        self.assertFalse(app_stats.record("nope"))
        app_stats.record({"e": "view", "k": "<script>alert(1)</script>"}, DAY)
        self.assertEqual(app_stats.stats(DAY)["pages_7d"][0]["page"], "scriptalert1script")

    def test_no_personal_data_on_disk(self):
        app_stats.record({"e": "open", "d": "my-phone-id-123", "tz": "Pacific/Auckland", "app": 1}, DAY)
        c = sqlite3.connect(app_stats.DB)
        dump = "\n".join(c.iterdump())
        c.close()
        self.assertNotIn("my-phone-id-123", dump)
        self.assertNotIn("Pacific/Auckland", dump)
        self.assertNotIn("my-phone-id-123", json.dumps(app_stats.stats(DAY)))


class StatsEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        app_stats.DB = os.path.join(cls.tmp.name, "s.db")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def req(self, path, data=None):
        r = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=data,
                                   headers={"Host": "staalwag.com"})
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, resp.read().decode()

    def test_hit_then_stats(self):
        code, _ = self.req("/hit", json.dumps({"e": "view", "k": "home", "tz": "Europe/Berlin"}).encode())
        self.assertEqual(code, 204)
        code, body = self.req("/stats.json")
        self.assertEqual(code, 200)
        d = json.loads(body)
        self.assertGreaterEqual(d["site"]["views_today"], 1)
        self.assertIn("play_clicks", d)
        self.assertIn("google_play", d)

    def test_dashboard_is_installable_and_private(self):
        code, body = self.req("/stats")
        self.assertEqual(code, 200)
        self.assertIn('rel="manifest" href="/stats.webmanifest"', body)
        self.assertIn('name="robots" content="noindex', body)
        m = json.loads(self.req("/stats.webmanifest")[1])
        self.assertEqual(m["start_url"], "/stats")
        self.assertIn("Disallow: /stats", self.req("/robots.txt")[1])

    def test_pages_load_counter(self):
        for p in ("/", "/margin-calculator", "/lot-size-calculator"):
            self.assertIn('src="/hit.js"', self.req(p)[1])


if __name__ == "__main__":
    unittest.main()
