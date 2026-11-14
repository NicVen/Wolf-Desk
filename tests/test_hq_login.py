"""HQ remembers the admin's device: unlock once, never asked again on it."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import test_money_path  # noqa: F401  (sets the throwaway DB + env first)
from licensing import config, server


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class HQLogin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.opener = urllib.request.build_opener(_NoRedirect)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def req(self, method, path, body=None, headers=None):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        r = urllib.request.Request(self.base + path, method=method, headers=h,
                                   data=json.dumps(body).encode() if body is not None else None)
        try:
            resp = self.opener.open(r, timeout=10)
        except urllib.error.HTTPError as e:
            resp = e
        raw = resp.read()
        return resp.status if hasattr(resp, "status") else resp.code, resp.headers, raw

    def cookie_from(self, headers):
        return headers.get("Set-Cookie", "").split(";")[0]

    def test_unlock_once_then_cookie_is_enough(self):
        code, h, _ = self.req("POST", "/admin/login", {"token": config.ADMIN_TOKEN})
        self.assertEqual(code, 200)
        sc = h.get("Set-Cookie")
        for attr in ("HttpOnly", "Secure", "SameSite=Strict", "Max-Age=34560000"):
            self.assertIn(attr, sc)
        self.assertNotIn(config.ADMIN_TOKEN, sc)            # never the raw token
        cookie = self.cookie_from(h)

        code, _, _ = self.req("GET", "/admin/app_stats", headers={"Cookie": cookie})
        self.assertEqual(code, 200)
        # a stale/wrong token left in the browser doesn't lock a remembered device out
        code, _, _ = self.req("GET", "/admin/app_stats",
                              headers={"Cookie": cookie, "X-Admin-Token": "old"})
        self.assertEqual(code, 200)

    def test_wrong_token_and_forged_cookie_refused(self):
        code, h, _ = self.req("POST", "/admin/login", {"token": "nope"})
        self.assertEqual(code, 403)
        self.assertIsNone(h.get("Set-Cookie"))
        code, _, _ = self.req("GET", "/admin/app_stats", headers={"Cookie": "hq_auth=forged"})
        self.assertEqual(code, 403)
        code, _, _ = self.req("GET", "/admin/app_stats")
        self.assertEqual(code, 403)

    def test_cookie_refused_from_another_site(self):
        _, h, _ = self.req("POST", "/admin/login", {"token": config.ADMIN_TOKEN})
        code, _, _ = self.req("POST", "/admin/revoke", {"key": "x"},
                              headers={"Cookie": self.cookie_from(h),
                                       "Origin": "https://evil.example"})
        self.assertEqual(code, 403)

    def test_rotating_token_signs_devices_out(self):
        _, h, _ = self.req("POST", "/admin/login", {"token": config.ADMIN_TOKEN})
        cookie = self.cookie_from(h)
        old = config.ADMIN_TOKEN
        config.ADMIN_TOKEN = old + "-rotated"
        try:
            code, _, _ = self.req("GET", "/admin/app_stats", headers={"Cookie": cookie})
            self.assertEqual(code, 403)
        finally:
            config.ADMIN_TOKEN = old

    def test_one_click_link_remembers_device(self):
        code, h, _ = self.req("GET", "/?tok=" + config.ADMIN_TOKEN,
                              headers={"Host": "hq.staalwag.com"})
        self.assertEqual(code, 302)
        key = server._hq_cookie_value()
        self.assertEqual(h.get("Location"), "/?k=" + key)   # never the raw token
        self.assertIn("hq_auth=", h.get("Set-Cookie"))
        code, h, _ = self.req("GET", "/?tok=wrong", headers={"Host": "hq.staalwag.com"})
        self.assertEqual(code, 302)
        self.assertIsNone(h.get("Set-Cookie"))

    def test_device_key_address_unlocks_with_storage_wiped(self):
        # login hands back the device key the page puts in its own address
        _, _, raw = self.req("POST", "/admin/login", {"token": config.ADMIN_TOKEN})
        key = json.loads(raw)["key"]
        self.assertNotEqual(key, config.ADMIN_TOKEN)
        # the page turns ?k=KEY into the cookie; that alone is enough
        code, _, _ = self.req("GET", "/admin/app_stats", headers={"Cookie": "hq_auth=" + key})
        self.assertEqual(code, 200)
        code, _, raw = self.req("GET", "/admin/hq_key", headers={"Cookie": "hq_auth=" + key})
        self.assertEqual((code, json.loads(raw)["key"]), (200, key))
        code, _, _ = self.req("GET", "/admin/hq_key")
        self.assertEqual(code, 403)

    def test_trusted_connection_needs_no_storage(self):
        me = {"X-Forwarded-For": "8.8.4.4", "User-Agent": "Edge-Nic"}   # a public address
        code, _, _ = self.req("GET", "/admin/app_stats", headers=me)
        self.assertEqual(code, 403)                 # unknown until unlocked once
        code, _, _ = self.req("POST", "/admin/login", {"token": config.ADMIN_TOKEN}, headers=me)
        self.assertEqual(code, 200)
        # browser wiped everything: no cookie, no token, same connection
        code, _, _ = self.req("GET", "/admin/app_stats", headers=me)
        self.assertEqual(code, 200)
        # another browser, another address, another site's script, a proxy: no
        for h in ({**me, "User-Agent": "Other"}, {**me, "X-Forwarded-For": "8.8.8.8"},
                  {**me, "Origin": "https://evil.example"},
                  {**me, "Sec-Fetch-Site": "cross-site"},
                  {**me, "X-Forwarded-For": "104.16.1.1"}):
            code, _, _ = self.req("GET", "/admin/app_stats", headers=h)
            self.assertEqual(code, 403, h)
        # rotating the token forgets every trusted connection
        old = config.ADMIN_TOKEN
        config.ADMIN_TOKEN = old + "-rotated"
        try:
            code, _, _ = self.req("GET", "/admin/app_stats", headers=me)
            self.assertEqual(code, 403)
        finally:
            config.ADMIN_TOKEN = old

    def test_local_requests_are_never_trusted(self):
        self.req("POST", "/admin/login", {"token": config.ADMIN_TOKEN})
        code, _, _ = self.req("GET", "/admin/app_stats")
        self.assertEqual(code, 403)

    def test_logout_clears_cookie(self):
        code, h, _ = self.req("POST", "/admin/logout", {})
        self.assertEqual(code, 200)
        self.assertIn("Max-Age=0", h.get("Set-Cookie"))


if __name__ == "__main__":
    unittest.main()
