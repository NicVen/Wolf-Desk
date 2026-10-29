"""Search-visibility tests: robots.txt, sitemap.xml, www -> apex, page heads.

Run:  python -m unittest discover -s tests -v
"""
import json
import os
import re
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import serve  # noqa: E402


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class SeoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.opener = urllib.request.build_opener(_NoRedirect)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def get(self, path, host="staalwag.com"):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path),
                                     headers={"Host": host})
        try:
            r = self.opener.open(req)
            return r.status, dict(r.headers), r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode("utf-8")

    def test_robots_on_main_site_points_to_sitemap(self):
        code, hdrs, body = self.get("/robots.txt")
        self.assertEqual(code, 200)
        self.assertTrue(hdrs["Content-Type"].startswith("text/plain"))
        self.assertIn("Allow: /", body)
        self.assertIn("Sitemap: https://staalwag.com/sitemap.xml", body)
        self.assertNotIn("Disallow: /store", body)
        self.assertNotIn("Disallow: /proof", body)

    def test_robots_blocks_duplicate_hosts(self):
        for host in ("app.staalwag.com", "178.104.88.38.sslip.io",
                     "wolf-desk-production.up.railway.app"):
            code, _, body = self.get("/robots.txt", host)
            self.assertEqual(code, 200)
            self.assertIn("Disallow: /\n", body, host)

    def test_sitemap_lists_public_pages(self):
        code, hdrs, body = self.get("/sitemap.xml")
        self.assertEqual(code, 200)
        self.assertIn("xml", hdrs["Content-Type"])
        locs = re.findall(r"<loc>(.*?)</loc>", body)
        self.assertIn("https://staalwag.com/", locs)
        self.assertIn("https://staalwag.com/store", locs)
        for loc in locs:   # every listed page must actually load
            code, _, _ = self.get(loc[len("https://staalwag.com"):])
            self.assertEqual(code, 200, loc)

    def test_www_redirects_to_apex(self):
        code, hdrs, _ = self.get("/store?ref=x", "www.staalwag.com")
        self.assertEqual(code, 301)
        self.assertEqual(hdrs["Location"], "https://staalwag.com/store?ref=x")

    def test_homepage_head(self):
        _, _, body = self.get("/")
        self.assertIn('<link rel="canonical" href="https://staalwag.com/"', body)
        self.assertIn("STAALCALIBUR", re.search(r"<title>(.*?)</title>", body).group(1))
        self.assertIn('href="/store"', body)
        ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', body, re.S)
        graph = json.loads(ld.group(1))["@graph"]
        names = {g["name"] for g in graph}
        self.assertTrue({"STAALWAG", "STAALCALIBUR"} <= names)
        self.assertNotRegex(body, r'og:image" content="/')

    def test_store_head(self):
        _, _, body = self.get("/store")
        self.assertIn('<link rel="canonical" href="https://staalwag.com/store"', body)
        json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', body, re.S).group(1))


if __name__ == "__main__":
    unittest.main()
