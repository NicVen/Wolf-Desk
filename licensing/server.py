"""STAALWAG licensing service.

Endpoints
  GET  /verify   ?key=&account=&machine=&product=   -> EA/indicator check-in
  POST /ipn                                          -> NOWPayments webhook (crypto)
  POST /card_ipn                                     -> Stripe webhook (card)
  POST /checkout (product, contact)                  -> create a payment, get pay URL
  GET  /buy?product=CODE                             -> minimal hosted buy page
  POST /admin/issue  (X-Admin-Token)                 -> manually create/extend a license
  GET  /  /thanks  /cancelled                        -> info / return pages

Run:  python -m licensing.server     (BIND_ADDR/PORT from env; sits behind Caddy)
"""
import json
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import cardpay, config, nowpayments, notify, store, tokens

DAY = 86400


# ---------------------------------------------------------------------------
# core license operations
# ---------------------------------------------------------------------------
def new_license_key(product):
    return "%s-%s" % (product.upper(), secrets.token_hex(4).upper())


def _new_ref_code():
    # short, unambiguous, unique referral code
    import string
    alpha = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    for _ in range(20):
        code = "".join(secrets.choice(alpha) for _ in range(6))
        if not store.get_by_ref_code(code):
            return code
    return secrets.token_hex(4).upper()


def ensure_ref_code(lic):
    """Return this license's share code, creating one if needed."""
    if lic.get("ref_code"):
        return lic["ref_code"]
    code = _new_ref_code()
    store.update(lic["license_key"], ref_code=code)
    return code


def ref_link(code):
    return "%s/buy?product=APP&ref=%s" % (config.PUBLIC_BASE_URL, code)


def price_for(code, contact):
    """Returns (price, note). price<=0 means don't charge; note explains why."""
    p = config.product(code)
    if not p:
        return 0, "unknown product"
    if p.get("free"):
        return 0, "This is free — just Subscribe on the desk."
    if p.get("tbd"):
        return 0, "Pricing for this product is coming soon."
    if code.upper() == "VIP":
        return p["price_solo"], None            # the membership itself
    if store.has_active_vip(contact):
        if p.get("vip"):
            return 0, "Included free in your VIP membership — already unlocked."
        return p.get("price_vip", 0), None       # VIP add-on price
    return p.get("price_solo", 0), None          # non-VIP solo price


def start_checkout(product_code, contact, method="crypto", ref=""):
    p = config.product(product_code)
    if not p:
        return None, "unknown product"
    price, note = price_for(product_code, contact)
    if price <= 0:
        return None, note or "nothing to charge for this item"
    key = new_license_key(product_code)
    store.create(key, product_code.upper(), contact, order_id=key, status="pending")
    # attribute the referral if a valid code was passed (can't refer yourself —
    # not the same license and not the same contact)
    if ref:
        r = store.get_by_ref_code(ref)
        if (r and r["license_key"] != key
                and (not contact or (r.get("contact") or "") != contact)):
            store.update(key, referred_by=ref)
    desc = "%s — %d days" % (p["name"], p["period_days"])
    if method == "card":
        url, ref = cardpay.create_checkout(price, order_id=key, description=desc)
    else:
        url, ref = nowpayments.create_invoice(price, order_id=key, order_description=desc)
    if not url:
        return None, "payment provider error: %s" % ref
    return {"invoice_url": url, "license_key": key}, None


def apply_payment(order_id, payment_id):
    lic = store.get_by_order(order_id) or store.get(order_id)
    if not lic:
        notify.admin("paid order %s has no license row" % order_id)
        return
    p = config.product(lic["product"])
    period = (p["period_days"] if p else 30) * DAY
    base = max(store.now(), lic.get("paid_until") or 0)
    paid_until = base + period
    store.update(lic["license_key"], status="active", paid_until=paid_until,
                 revoke_at=None, notified=0, last_payment=payment_id)
    when = time.strftime("%Y-%m-%d", time.gmtime(paid_until))
    notify.client(lic["contact"],
                  "Payment received. Your %s access is active until %s (UTC).\n"
                  "Activation key: %s\nEnter this key in the product to unlock it."
                  % (lic["product"], when, lic["license_key"]))
    notify.admin("payment ok: %s -> active until %s" % (lic["license_key"], when))
    _reward_referrer(lic)


def _reward_referrer(lic):
    """First paid activation of a referred license credits the referrer with
    free days. Runs once per referred license."""
    code = lic.get("referred_by")
    if not code or lic.get("ref_rewarded"):
        return
    ref = store.get_by_ref_code(code)
    if not ref or ref["license_key"] == lic["license_key"]:
        return
    days = config.REFERRAL_REWARD_DAYS
    base = max(store.now(), ref.get("paid_until") or 0)
    store.update(ref["license_key"], status="active", paid_until=base + days * DAY,
                 revoke_at=None, notified=0)
    store.update(lic["license_key"], ref_rewarded=1)
    until = time.strftime("%Y-%m-%d", time.gmtime(base + days * DAY))
    notify.client(ref.get("contact"),
                  "🎉 A referral of yours just subscribed — you've earned %d free days! "
                  "Your access now runs to %s (UTC). Keep sharing your link." % (days, until))
    notify.admin("referral reward: %s credited %dd (referred %s)"
                 % (ref["license_key"], days, lic["license_key"]))


def check_access(lic):
    """Return (allowed, reason)."""
    now = store.now()
    if lic["status"] == "revoked":
        return False, "revoked"
    if lic["status"] == "pending":
        return False, "unpaid"
    if lic.get("paid_until") and now <= lic["paid_until"]:
        return True, "active"
    if lic.get("revoke_at") and now < lic["revoke_at"]:
        return True, "grace"      # lapsed but inside the 4h window
    return False, "expired"


# ---------------------------------------------------------------------------
# background sweeper: pre-expiry reminders, lapse -> past_due, revoke after grace
# ---------------------------------------------------------------------------
def sweeper():
    while True:
        try:
            now = store.now()
            for lic in store.all_active_or_pastdue():
                key, paid_until = lic["license_key"], lic.get("paid_until") or 0
                if lic["status"] == "active":
                    if now >= paid_until:
                        revoke_at = paid_until + config.GRACE_HOURS * 3600
                        store.update(key, status="past_due", revoke_at=revoke_at, notified=2)
                        notify.client(lic["contact"],
                                      "Your %s subscription has lapsed. Renew now — access "
                                      "will be removed in %d hours if payment isn't received."
                                      % (lic["product"], config.GRACE_HOURS))
                        notify.admin("lapsed: %s (grace %dh)" % (key, config.GRACE_HOURS))
                    elif now >= paid_until - config.RENEW_NOTICE_DAYS * DAY and not lic.get("notified"):
                        store.update(key, notified=1)
                        notify.client(lic["contact"],
                                      "Your %s subscription renews soon. Pay before it "
                                      "expires to keep uninterrupted access." % lic["product"])
                elif lic["status"] == "past_due":
                    if lic.get("revoke_at") and now >= lic["revoke_at"]:
                        store.update(key, status="revoked")
                        notify.client(lic["contact"],
                                      "Your %s access has been removed for non-payment. "
                                      "Renew any time to restore it." % lic["product"])
                        notify.admin("revoked: %s" % key)
        except Exception as e:  # noqa: BLE001
            notify.admin("sweeper error: %s" % e)
        time.sleep(60)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")  # buy flow runs on wolf.* desk
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        # CORS preflight for the cross-origin /checkout POST from the desk
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-Token")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(n) if n else b""

    # ---- GET ----
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        one = lambda k: (q.get(k) or [""])[0]

        if u.path == "/verify":
            self._verify(one("key"), one("account"), one("machine"), one("product"))
        elif u.path == "/reflink":
            self._reflink(one("key"))
        elif u.path == "/admin/list":
            self._admin_list()
        elif u.path == "/buy":
            self._buy_page(one("product"))
        elif u.path == "/thanks":
            self._send(200, "<h2>Thank you — your activation key is on its way.</h2>", "text/html")
        elif u.path == "/cancelled":
            self._send(200, "<h2>Payment cancelled.</h2>", "text/html")
        elif u.path in ("/", "/health"):
            self._send(200, {"service": "staalwag-licensing", "ok": True,
                             "products": list(config.PRODUCTS.keys())})
        else:
            self._send(404, {"error": "not found"})

    # ---- POST ----
    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/ipn":
            self._ipn()
        elif u.path == "/card_ipn":
            self._card_ipn()
        elif u.path == "/checkout":
            self._checkout()
        elif u.path == "/admin/issue":
            self._admin_issue()
        elif u.path == "/admin/revoke":
            self._admin_revoke()
        elif u.path == "/admin/extend":
            self._admin_extend()
        elif u.path == "/admin/reset_device":
            self._admin_reset_device()
        elif u.path == "/admin/announce":
            self._admin_announce()
        elif u.path == "/subscribe":
            self._subscribe()
        else:
            self._send(404, {"error": "not found"})

    # ---- admin auth ----
    def _admin_ok(self):
        return bool(config.ADMIN_TOKEN) and self.headers.get("X-Admin-Token") == config.ADMIN_TOKEN

    # ---- handlers ----
    def _verify(self, key, account, machine, product):
        if not key:
            return self._send(400, {"valid": False, "reason": "no_key"})
        lic = store.get(key)
        if not lic:
            return self._send(200, {"valid": False, "reason": "unknown"})

        # admin master key: unlocks any product, any device, never expires.
        if lic.get("admin"):
            store.update(key, last_seen=store.now(), last_account=account or machine or "")
            prod = (product or lic["product"]).upper()
            token = tokens.issue(key, prod, lic.get("paid_until") or (store.now() + 3650 * DAY))
            return self._send(200, {"valid": True, "reason": "admin", "product": prod,
                                    "expires_at": lic.get("paid_until"), "server_time": store.now(),
                                    "token": token, "recheck_in": config.TOKEN_TTL_HOURS * 3600})

        if product and lic["product"].upper() != product.upper():
            # a VIP membership unlocks every product flagged vip=True
            reqp = config.product(product)
            if not (lic["product"] == "VIP" and reqp and reqp.get("vip")):
                return self._send(200, {"valid": False, "reason": "wrong_product"})

        # bind to first account/machine seen; block others (anti-sharing).
        # no_bind licenses (e.g. multi-device comps) skip this entirely.
        if not lic.get("no_bind"):
            if lic.get("bind_account"):
                if account and (account != lic["bind_account"] or
                                (lic.get("bind_machine") and machine and machine != lic["bind_machine"])):
                    return self._send(200, {"valid": False, "reason": "bound_to_other"})
            elif account and lic["status"] in ("active", "past_due"):
                store.update(key, bind_account=account, bind_machine=machine)
                lic["bind_account"] = account

        allowed, reason = check_access(lic)
        if not allowed:
            return self._send(200, {"valid": False, "reason": reason,
                                    "product": lic["product"]})
        store.update(key, last_seen=store.now(), last_account=account or machine or "")
        token = tokens.issue(key, lic["product"], lic["paid_until"])
        self._send(200, {"valid": True, "reason": reason, "product": lic["product"],
                         "expires_at": lic["paid_until"], "server_time": store.now(),
                         "token": token, "recheck_in": config.TOKEN_TTL_HOURS * 3600})

    def _ipn(self):
        raw = self._body()
        sig = self.headers.get("x-nowpayments-sig", "")
        if not nowpayments.verify_ipn(raw, sig):
            return self._send(401, {"error": "bad signature"})
        try:
            d = json.loads(raw)
        except Exception:  # noqa: BLE001
            return self._send(400, {"error": "bad json"})
        status = (d.get("payment_status") or "").lower()
        order_id = d.get("order_id") or ""
        payment_id = str(d.get("payment_id") or d.get("id") or "")
        if status in ("finished", "confirmed"):
            if payment_id and store.payment_seen(payment_id):
                return self._send(200, {"ok": True, "dup": True})
            apply_payment(order_id, payment_id)
        elif status == "partially_paid":
            notify.admin("PARTIAL payment on order %s — check manually" % order_id)
        # NOWPayments just wants a 200
        self._send(200, {"ok": True})

    def _card_ipn(self):
        raw = self._body()
        sig = self.headers.get("Stripe-Signature", "")
        if not cardpay.verify_webhook(raw, sig):
            return self._send(401, {"error": "bad signature"})
        try:
            d = json.loads(raw)
        except Exception:  # noqa: BLE001
            return self._send(400, {"error": "bad json"})
        if (d.get("type") or "") == "checkout.session.completed":
            obj = (d.get("data") or {}).get("object") or {}
            if (obj.get("payment_status") or "") == "paid":
                order_id = ((obj.get("metadata") or {}).get("order_id")
                            or obj.get("client_reference_id") or "")
                payment_id = str(obj.get("payment_intent") or obj.get("id") or "")
                if payment_id and store.payment_seen(payment_id):
                    return self._send(200, {"ok": True, "dup": True})
                apply_payment(order_id, payment_id)
        self._send(200, {"ok": True})

    def _checkout(self):
        ct = self.headers.get("Content-Type", "")
        raw = self._body()
        if "application/json" in ct:
            data = json.loads(raw or b"{}")
        else:
            data = {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode()).items()}
        res, err = start_checkout(data.get("product", ""), data.get("contact", ""),
                                  method=(data.get("method") or "crypto"),
                                  ref=(data.get("ref") or ""))
        if err:
            return self._send(400, {"error": err})
        self._send(200, res)

    def _reflink(self, key):
        """Return the caller's personal referral link + stats. Any known,
        non-revoked key can share (admin keys too)."""
        lic = store.get(key)
        if not lic:
            return self._send(200, {"ok": False, "reason": "unknown key"})
        if lic["status"] == "revoked":
            return self._send(200, {"ok": False, "reason": "inactive"})
        code = ensure_ref_code(lic)
        self._send(200, {"ok": True, "code": code, "link": ref_link(code),
                         "referrals": store.count_referrals(code),
                         "reward_days": config.REFERRAL_REWARD_DAYS})

    def _admin_issue(self):
        if not self._admin_ok():
            return self._send(403, {"error": "forbidden"})
        data = json.loads(self._body() or b"{}")
        p = config.product(data.get("product", ""))
        if not p:
            return self._send(400, {"error": "unknown product"})
        is_admin = bool(data.get("admin"))
        no_bind = 1 if (is_admin or data.get("no_bind")) else 0
        days = int(data.get("days", 3650 if is_admin else p["period_days"]))
        key = data.get("license_key") or new_license_key(data["product"])
        lic = store.get(key)
        if not lic:
            store.create(key, data["product"].upper(), data.get("contact", ""),
                         order_id=key, status="pending")
            lic = store.get(key)
        base = max(store.now(), lic.get("paid_until") or 0)
        store.update(key, status="active", paid_until=base + days * DAY,
                     revoke_at=None, notified=0, no_bind=no_bind,
                     admin=1 if is_admin else 0)
        row = store.get(key)
        self._send(200, {"license_key": key, "status": "active",
                         "paid_until": row["paid_until"],
                         "admin": bool(row.get("admin")), "no_bind": bool(row.get("no_bind"))})

    def _admin_list(self):
        if not self._admin_ok():
            return self._send(403, {"error": "forbidden"})
        now = store.now()
        out = []
        for l in store.all_licenses():
            if l.get("admin"):
                access = "admin"
            else:
                _, access = check_access(l)
            pu = l.get("paid_until") or 0
            out.append({
                "key": l["license_key"], "product": l["product"], "contact": l.get("contact"),
                "status": l["status"], "access": access,
                "days_left": round((pu - now) / DAY, 1) if pu else None,
                "admin": bool(l.get("admin")), "no_bind": bool(l.get("no_bind")),
                "bound": l.get("bind_account") or None,
                "last_seen": l.get("last_seen"),
            })
        # order: problems first (past_due/pending), then by days_left ascending
        self._send(200, {"count": len(out), "server_time": now, "licenses": out})

    def _admin_revoke(self):
        if not self._admin_ok():
            return self._send(403, {"error": "forbidden"})
        key = json.loads(self._body() or b"{}").get("key", "")
        if not store.get(key):
            return self._send(404, {"error": "unknown key"})
        store.update(key, status="revoked", revoke_at=None)
        notify.admin("manually revoked: %s" % key)
        self._send(200, {"license_key": key, "status": "revoked"})

    def _admin_extend(self):
        if not self._admin_ok():
            return self._send(403, {"error": "forbidden"})
        data = json.loads(self._body() or b"{}")
        key, days = data.get("key", ""), int(data.get("days", 30))
        lic = store.get(key)
        if not lic:
            return self._send(404, {"error": "unknown key"})
        base = max(store.now(), lic.get("paid_until") or 0)
        store.update(key, status="active", paid_until=base + days * DAY,
                     revoke_at=None, notified=0)
        self._send(200, {"license_key": key, "status": "active",
                         "paid_until": store.get(key)["paid_until"]})

    def _admin_reset_device(self):
        if not self._admin_ok():
            return self._send(403, {"error": "forbidden"})
        key = json.loads(self._body() or b"{}").get("key", "")
        if not store.get(key):
            return self._send(404, {"error": "unknown key"})
        store.update(key, bind_account=None, bind_machine=None)
        self._send(200, {"license_key": key, "reset": True})

    def _admin_announce(self):
        """Message every active renter of a product about a new version."""
        if not self._admin_ok():
            return self._send(403, {"error": "forbidden"})
        d = json.loads(self._body() or b"{}")
        product = (d.get("product") or "APP").upper()
        version = d.get("version") or ""
        title = d.get("title") or "Update available"
        notes = d.get("notes") or []
        p = config.product(product)
        pname = p["name"] if p else product
        lines = ["%s — v%s: %s" % (pname, version, title)]
        for n in notes:
            lines.append("• " + str(n))
        lines.append("\nOpen the app and tap “Update now” to install it.")
        msg = "\n".join(lines)
        sent = 0
        for contact in store.active_contacts(product):
            notify.client(contact, msg)
            sent += 1
        notify.admin("announce %s v%s -> %d renter(s)" % (product, version, sent))
        self._send(200, {"product": product, "version": version, "notified": sent})

    def _subscribe(self):
        """Free intel-desk subscription. Consent is signed once; after that the
        Telegram id is remembered and no consent is asked again."""
        data = json.loads(self._body() or b"{}")
        tg = str(data.get("telegram_id", "")).strip()
        consent = bool(data.get("consent"))
        if not tg:
            return self._send(400, {"error": "telegram id or email required"})
        if store.subscriber_exists(tg):
            return self._send(200, {"status": "known", "subscribed": True})
        if consent:
            store.add_subscriber(tg)
            notify.admin("new free subscriber: %s" % tg)
            return self._send(200, {"status": "new", "subscribed": True})
        return self._send(200, {"status": "need_consent", "subscribed": False})

    def _buy_page(self, product_code):
        p = config.product(product_code)
        if not p:
            return self._send(404, "<h2>Unknown product.</h2>", "text/html")
        html = """<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Rent %(name)s</title>
<style>body{font-family:system-ui;max-width:460px;margin:40px auto;padding:0 20px;
color:#1a2230}h1{font-size:20px}input,button{font-size:16px;padding:10px;width:100%%;
box-sizing:border-box;margin:6px 0;border:1px solid #ccc;border-radius:8px}
button{background:#111a2b;color:#fff;border:0;cursor:pointer}small{color:#667}</style>
<h1>%(name)s</h1>
<p><b>$%(price)d USD / %(days)d days</b> — pay with crypto, get your activation key by
message the moment payment confirms.</p>
<label>Your Telegram chat id or email (so we can send your key + renewal reminders)</label>
<input id=contact placeholder="e.g. 123456789 or you@email.com">
<div id=refnote style="display:none;background:#eef4ff;border:1px solid #cfe0ff;border-radius:8px;padding:10px;font-size:13px;color:#26406b">Referred by a friend — subscribe below and they'll earn free time too.</div>
<button onclick="go('crypto')">Pay with crypto</button>
%(card_btn)s
<small>Access renews automatically on payment; lapses are removed %(grace)dh
after a reminder.</small>
<script>
var REF = new URLSearchParams(location.search).get('ref') || '';
if(REF){ document.getElementById('refnote').style.display='block'; }
function go(method){
 fetch('/checkout',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({product:'%(code)s',method:method,ref:REF,contact:document.getElementById('contact').value})})
 .then(r=>r.json()).then(d=>{if(d.invoice_url)location=d.invoice_url;else alert(d.error||'error')})
 .catch(e=>alert(e));
}
</script>""" % {"name": p["name"], "price": p.get("price_solo", 0), "days": p["period_days"],
               "code": product_code.upper(), "grace": config.GRACE_HOURS,
               "card_btn": ('<button onclick="go(\'card\')">Pay with card</button>'
                            if config.card_enabled() else "")}
        self._send(200, html, "text/html")


def main():
    threading.Thread(target=sweeper, daemon=True).start()
    srv = ThreadingHTTPServer((config.BIND_ADDR, config.PORT), H)
    print("[licensing] serving on %s:%d (grace %dh)" %
          (config.BIND_ADDR, config.PORT, config.GRACE_HOURS), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
