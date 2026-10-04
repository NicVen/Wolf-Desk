"""Play closed-test sign-up: Gmail only, no duplicates, admin gets the list."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

import test_money_path  # noqa: F401  (sets the throwaway DB + env first)
from licensing import config, notify, server


class Testers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def setUp(self):
        self.pings = []
        p = mock.patch.object(notify, "admin", self.pings.append)
        p.start()
        self.addCleanup(p.stop)

    def req(self, method, path, body=None, headers=None):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        r = urllib.request.Request(self.base + path, method=method, headers=h,
                                   data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_signup_flow(self):
        _, before = self.req("GET", "/testers")
        self.assertEqual(before["goal"], config.TESTER_GOAL)

        code, res = self.req("POST", "/testers/join", {"email": " Tester.One@Gmail.com ",
                                                       "telegram": "@one"})
        self.assertEqual(code, 200)
        self.assertTrue(res["new"])
        self.assertEqual(res["count"], before["count"] + 1)
        self.assertTrue(any("tester.one@gmail.com" in m for m in self.pings))

        _, again = self.req("POST", "/testers/join", {"email": "tester.one@gmail.com"})
        self.assertFalse(again["new"])
        self.assertEqual(again["count"], res["count"])
        self.assertEqual(len(self.pings), 1)        # no second ping for a repeat

    def test_non_gmail_is_refused(self):
        for bad in ("someone@yahoo.com", "not-an-email", "", "a@gmail.com.evil.io"):
            code, res = self.req("POST", "/testers/join", {"email": bad})
            self.assertEqual(code, 400, bad)
            self.assertEqual(res["error"], "gmail_required")

    def test_admin_list_needs_token(self):
        self.req("POST", "/testers/join", {"email": "tester.two@gmail.com"})
        code, _ = self.req("GET", "/admin/testers")
        self.assertEqual(code, 403)
        code, res = self.req("GET", "/admin/testers", headers={"X-Admin-Token": "test-admin"})
        self.assertEqual(code, 200)
        self.assertIn("tester.two@gmail.com", res["paste_into_play_console"])


if __name__ == "__main__":
    unittest.main()
