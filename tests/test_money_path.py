"""Money-path tests: checkout -> payment -> activation -> /verify.

Runs the real licensing HTTP server on a throwaway database. PayPal, NOWPayments
and Telegram are faked, so nothing leaves the machine and no keys are needed.

Run:  python -m unittest discover -s tests -v
"""
import hashlib
import hmac
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="staalwag-test-")
os.environ.update({
    "DB_PATH": os.path.join(_TMP, "licenses.db"),
    "NOWPAYMENTS_API_KEY": "test-np-key",
    "NOWPAYMENTS_IPN_SECRET": "test-ipn-secret",
    "PAYPAL_CLIENT_ID": "test-pp-id",
    "PAYPAL_SECRET": "test-pp-secret",
    "PAYPAL_WEBHOOK_ID": "test-pp-webhook",
    "LICENSE_SIGNING_SECRET": "test-signing",
    "ADMIN_TOKEN": "test-admin",
    "LICENSE_BOT_TOKEN": "", "LICENSE_ADMIN_CHAT": "",
    "UPDATES_BOT_TOKEN": "", "UPDATES_CHAT": "",
})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from licensing import config, nowpayments, notify, paypal, server, store  # noqa: E402

DAY = 86400
APP_PRICE = config.product("APP")["price_solo"]
APP_DAYS = config.product("APP")["period_days"]


class FakePayPal:
    """Stands in for PayPal's REST API (paypal._api)."""
    n = 0                     # shared so ids stay unique across tests, like PayPal's

    def __init__(self):
        self.orders = {}      # paypal order id -> {"custom_id", "value", "captured"}

    def api(self, path, method="GET", token=None, body=None, basic=False):
        if path == "/v1/oauth2/token":
            return {"access_token": "tok"}
        if path == "/v2/checkout/orders" and method == "POST":
            unit = json.loads(body)["purchase_units"][0]
            FakePayPal.n += 1
            pid = "PPORDER%d" % FakePayPal.n
            self.orders[pid] = {"custom_id": unit["custom_id"],
                                "value": unit["amount"]["value"], "captured": False}
            return {"id": pid, "links": [{"rel": "approve",
                                          "href": "https://paypal.test/approve/" + pid}]}
        if path.startswith("/v2/checkout/orders/") and path.endswith("/capture"):
            pid = path.split("/")[4]
            o = self.orders[pid]
            if o["captured"]:
                raise urllib.error.HTTPError(path, 422, "ORDER_ALREADY_CAPTURED", {}, None)
            o["captured"] = True
            return {"status": "COMPLETED", "purchase_units": [{
                "custom_id": o["custom_id"],
                "payments": {"captures": [{"id": "CAP-" + pid, "custom_id": o["custom_id"]}]}}]}
        if path == "/v1/notifications/verify-webhook-signature":
            ok = json.loads(body).get("transmission_sig") == "good"
            return {"verification_status": "SUCCESS" if ok else "FAILURE"}
        raise AssertionError("unexpected PayPal call: %s %s" % (method, path))


class MoneyPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        shutil.rmtree(_TMP, ignore_errors=True)

    def setUp(self):
        self.pp = FakePayPal()
        self.invoices = []
        self.admin_msgs = []
        patches = [
            mock.patch.object(paypal, "_api", self.pp.api),
            mock.patch.object(nowpayments, "create_invoice", self._fake_invoice),
            mock.patch.object(notify, "_telegram", lambda *a, **k: None),
            mock.patch.object(notify, "admin", self.admin_msgs.append),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    # ---- helpers ----
    def _fake_invoice(self, price_usd, order_id, order_description):
        self.invoices.append({"price": price_usd, "order_id": order_id})
        return "https://nowpayments.test/invoice/" + order_id, "INV-" + order_id

    def req(self, method, path, body=None, headers=None):
        data = body if isinstance(body, bytes) else (
            json.dumps(body).encode() if body is not None else None)
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                raw, code = resp.read(), resp.status
        except urllib.error.HTTPError as e:
            raw, code = e.read(), e.code
        try:
            return code, json.loads(raw)
        except ValueError:
            return code, raw.decode()

    def checkout(self, method, contact="buyer@example.com", product="APP"):
        code, res = self.req("POST", "/checkout",
                             {"product": product, "contact": contact, "method": method})
        self.assertEqual(code, 200, res)
        return res["license_key"]

    def crypto_ipn(self, order_id, payment_id, status="finished", sig=None):
        body = {"payment_id": payment_id, "order_id": order_id, "payment_status": status}
        raw = json.dumps(body).encode()
        if sig is None:
            sig = hmac.new(b"test-ipn-secret", nowpayments._canonical(body).encode(),
                           hashlib.sha512).hexdigest()
        return self.req("POST", "/ipn", raw, {"x-nowpayments-sig": sig})

    def paypal_webhook(self, order_id, capture_id, sig="good"):
        body = {"event_type": "PAYMENT.CAPTURE.COMPLETED",
                "resource": {"id": capture_id, "custom_id": order_id}}
        return self.req("POST", "/paypal_ipn", body, {"Paypal-Transmission-Sig": sig})

    def days_paid(self, key):
        lic = store.get(key)
        return round(((lic.get("paid_until") or 0) - store.now()) / DAY)

    def verify(self, key, product="APP"):
        return self.req("GET", "/verify?key=%s&product=%s&account=acc1" % (key, product))[1]

    # ---- crypto (NOWPayments) ----
    def test_only_the_app_is_for_sale(self):
        for code in ("SIG_GOLD", "SIG_VELDRIN", "GOLD", "VIP"):
            status, res = self.req("POST", "/checkout",
                                   {"product": code, "contact": "buyer@example.com", "method": "crypto"})
            self.assertEqual(status, 400, code)
            self.assertIn("In testing", res["error"])
        self.assertTrue(self.checkout("crypto"))       # the App still sells

    def test_crypto_pays_once_and_unlocks(self):
        key = self.checkout("crypto")
        self.assertEqual(self.invoices[-1]["price"], APP_PRICE)
        self.assertEqual(self.verify(key)["reason"], "unpaid")

        self.assertEqual(self.crypto_ipn(key, "NP-1")[0], 200)
        self.assertEqual(self.days_paid(key), APP_DAYS)
        self.assertTrue(self.verify(key)["valid"])
        since = self.verify(key)["since"]                        # tools unlock from the first payment
        self.assertFalse(self.verify(key)["trial"])
        self.assertAlmostEqual(since, store.now(), delta=5)

        # NOWPayments retries webhooks; a repeat must not add more days
        self.crypto_ipn(key, "NP-1")
        self.crypto_ipn(key, "NP-1", status="confirmed")
        self.assertEqual(self.days_paid(key), APP_DAYS)

    def test_crypto_forged_webhook_is_rejected(self):
        key = self.checkout("crypto")
        code, _ = self.crypto_ipn(key, "NP-FAKE", sig="0" * 128)
        self.assertEqual(code, 401)
        self.assertEqual(store.get(key)["status"], "pending")
        self.assertFalse(self.verify(key)["valid"])

    def test_crypto_partial_payment_does_not_unlock(self):
        key = self.checkout("crypto")
        self.crypto_ipn(key, "NP-2", status="partially_paid")
        self.assertEqual(store.get(key)["status"], "pending")
        self.assertTrue(any("PARTIAL" in m for m in self.admin_msgs))

    def test_renewal_adds_a_period_on_top(self):
        key = self.checkout("crypto")
        self.crypto_ipn(key, "NP-3")
        since = store.get(key)["paid_since"]
        self.crypto_ipn(key, "NP-4")          # a second, different payment
        self.assertEqual(self.days_paid(key), 2 * APP_DAYS)
        self.assertEqual(store.get(key)["paid_since"], since)   # a renewal doesn't restart the reveal

    # ---- mobile toolkit: add-ons on the App key, and the TOOLKIT bundle ----
    def _paid_key(self, product="APP", n=[0]):
        n[0] += 1
        key = self.checkout("crypto", contact="tk%d@example.com" % n[0], product=product)
        self.crypto_ipn(key, "NP-TK-%s-%d" % (product, n[0]))
        return key

    def test_toolkit_not_for_sale_until_live(self):
        for code in ("GUARDIAN", "HOURS", "TOOLKIT"):
            status, res = self.req("POST", "/checkout", {"product": code, "contact": "b@example.com",
                                                         "method": "crypto", "attach": "x"})
            self.assertEqual(status, 400, code)
            self.assertIn("In testing", res["error"])

    def test_tools_are_announced_once_each_when_for_sale(self):
        key = self._paid_key()
        lic = lambda: store.get(key)
        now = store.now()
        self.assertEqual(server.tool_notices(lic(), now), [])                 # day 0: nothing yet
        later = lic()["paid_since"] + 8 * DAY
        self.assertEqual(server.tool_notices(lic(), later), [])               # add-ons still locked
        with mock.patch.object(config, "LOCKED", set()):
            n = server.tool_notices(lic(), later)
            self.assertEqual([lvl for lvl, _ in n], [1])                      # day 8: Prime Hours
            self.assertIn("Prime Hours", n[0][1])
            self.assertIn(key, n[0][1])
            store.update(key, tools_told=1)
            self.assertEqual(server.tool_notices(lic(), later), [])           # told once only
            n = server.tool_notices(lic(), lic()["paid_since"] + 13 * DAY)
            self.assertEqual([lvl for lvl, _ in n], [2])                      # day 13: Guardian
            store.update(key, trial=1)
            self.assertEqual(server.tool_notices(lic(), later + 30 * DAY), [])  # trials never

    def test_addon_rides_on_the_app_key(self):
        with mock.patch.object(config, "LOCKED", set()):
            app = self._paid_key()
            self.assertFalse(self.verify(app, "GUARDIAN")["valid"])
            code, res = self.req("POST", "/checkout", {"product": "GUARDIAN", "method": "crypto",
                                                       "contact": "", "attach": app})
            self.assertEqual(code, 200, res)
            self.assertEqual(self.invoices[-1]["price"], config.product("GUARDIAN")["price_solo"])
            addon = res["license_key"]
            self.assertFalse(self.verify(app, "GUARDIAN")["valid"])      # not paid yet
            self.crypto_ipn(self.invoices[-1]["order_id"], "NP-G1")
            v = self.verify(app, "GUARDIAN")
            self.assertTrue(v["valid"]); self.assertEqual(v["product"], "GUARDIAN")
            self.assertTrue(self.verify(app, "APP")["valid"])            # app still opens
            self.assertFalse(self.verify(app, "HOURS")["valid"])         # only what was paid for
            # next month: same add-on row, a second period on top
            code, res = self.req("POST", "/checkout", {"product": "GUARDIAN", "method": "crypto",
                                                       "contact": "", "attach": app})
            self.assertEqual(res["license_key"], addon)
            self.assertNotEqual(self.invoices[-1]["order_id"], addon)
            self.crypto_ipn(self.invoices[-1]["order_id"], "NP-G2")
            self.assertEqual(self.days_paid(addon), 60)

    def test_addon_needs_a_real_paid_app_key(self):
        with mock.patch.object(config, "LOCKED", set()):
            for attach in ("", "APP-NOPE"):
                code, _ = self.req("POST", "/checkout", {"product": "HOURS", "method": "crypto",
                                                         "contact": "c@example.com", "attach": attach})
                self.assertEqual(code, 400)
            unpaid = self.checkout("crypto", contact="unpaid@example.com")
            code, _ = self.req("POST", "/checkout", {"product": "HOURS", "method": "crypto",
                                                     "contact": "", "attach": unpaid})
            self.assertEqual(code, 400)

    def test_toolkit_key_opens_all_three(self):
        with mock.patch.object(config, "LOCKED", set()):
            key = self._paid_key("TOOLKIT")
            self.assertEqual(self.invoices[-1]["price"], 39.99)
            for p in ("APP", "GUARDIAN", "HOURS"):
                self.assertTrue(self.verify(key, p)["valid"], p)
            self.assertFalse(self.verify(key, "GOLD")["valid"])

    # ---- PayPal ----
    def test_paypal_return_then_webhook_credits_once(self):
        key = self.checkout("paypal")
        pid, order = next(iter(self.pp.orders.items()))
        self.assertEqual(order["custom_id"], key)
        self.assertEqual(float(order["value"]), APP_PRICE)

        code, page = self.req("GET", "/paypal_return?token=" + pid)
        self.assertIn("Thank you", page)
        self.assertEqual(self.days_paid(key), APP_DAYS)

        self.paypal_webhook(key, "CAP-" + pid)    # PayPal's backup notice
        self.assertEqual(self.days_paid(key), APP_DAYS)
        self.assertTrue(self.verify(key)["valid"])

    def test_paypal_webhook_then_return_credits_once(self):
        key = self.checkout("paypal")
        pid = next(iter(self.pp.orders))
        self.paypal_webhook(key, "CAP-" + pid)
        self.assertEqual(self.days_paid(key), APP_DAYS)
        _, page = self.req("GET", "/paypal_return?token=" + pid)
        self.assertIn("Thank you", page)
        self.assertEqual(self.days_paid(key), APP_DAYS)

    def test_paypal_forged_webhook_is_rejected(self):
        key = self.checkout("paypal")
        code, _ = self.paypal_webhook(key, "CAP-FAKE", sig="bad")
        self.assertEqual(code, 401)
        self.assertEqual(store.get(key)["status"], "pending")

    # ---- trial + access ----
    def test_trial_is_one_per_contact(self):
        code, res = self.req("POST", "/trial", {"contact": "trial@example.com"})
        self.assertEqual(code, 200)
        self.assertTrue(res["trial"])
        self.assertTrue(self.verify(res["license_key"])["valid"])
        self.assertTrue(self.verify(res["license_key"])["trial"])        # the app shows a trial no tools
        _, again = self.req("POST", "/trial", {"contact": "trial@example.com"})
        self.assertEqual(again.get("error"), "trial_used")

    def test_expired_licence_is_locked(self):
        key = self.checkout("crypto")
        self.crypto_ipn(key, "NP-5")
        store.update(key, paid_until=store.now() - DAY, revoke_at=None)
        self.assertEqual(self.verify(key)["reason"], "expired")

    def test_licence_is_bound_to_first_account(self):
        key = self.checkout("crypto")
        self.crypto_ipn(key, "NP-6")
        self.assertTrue(self.verify(key)["valid"])           # binds to acc1
        _, other = self.req("GET", "/verify?key=%s&product=APP&account=acc2" % key)
        self.assertEqual(other["reason"], "bound_to_other")

    def test_storefront_price_matches_charge(self):
        _, p = self.req("GET", "/pricing")
        self.assertEqual(p["price"], APP_PRICE)
        self.checkout("crypto")
        self.assertEqual(self.invoices[-1]["price"], p["price"])


if __name__ == "__main__":
    unittest.main()
