"""Thin PayPal client: create a hosted Checkout order, capture it, verify webhooks.

Only stdlib. Inert until PAYPAL_CLIENT_ID + PAYPAL_SECRET are set — create_checkout
returns an error and the buy page hides the PayPal button, so nothing breaks
before you have credentials. The rest of the licensing flow (apply_payment,
sweeper) is unchanged.

Flow (PayPal Orders v2, intent=CAPTURE):
  1. create_checkout() -> an approval URL we redirect the buyer to. We stamp our
     own licence order_id onto the order as custom_id.
  2. buyer approves on PayPal, returns to /paypal_return?token=<paypal order id>.
  3. capture_order() finalises the money and hands back our order_id -> the server
     calls apply_payment(). A PAYMENT.CAPTURE.COMPLETED webhook is the backup path
     for a buyer who closes the tab before returning.
"""
import base64
import json
import urllib.parse
import urllib.request

from . import config


def _api(path, method="GET", token=None, body=None, basic=False):
    headers = {"Content-Type": "application/json"}
    if basic:
        raw = (config.PAYPAL_CLIENT_ID + ":" + config.PAYPAL_SECRET).encode()
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif token:
        headers["Authorization"] = "Bearer " + token
    data = body if isinstance(body, bytes) else (body.encode() if body else None)
    req = urllib.request.Request(config.PAYPAL_API + path, data=data,
                                 method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"{}")


def _token():
    d = _api("/v1/oauth2/token", "POST", basic=True,
             body="grant_type=client_credentials")
    return d.get("access_token")


def create_checkout(price_usd, order_id, description):
    """Create a hosted PayPal order; returns (approval_url, paypal_order_id) or (None, err)."""
    if not config.paypal_enabled():
        return None, "paypal not configured"
    try:
        tok = _token()
        if not tok:
            return None, "paypal auth failed"
        body = json.dumps({
            "intent": "CAPTURE",
            "purchase_units": [{
                "custom_id": order_id,
                "description": description[:127],
                "amount": {"currency_code": "USD", "value": "%.2f" % float(price_usd)},
            }],
            "application_context": {
                "brand_name": "STAALWAG",
                "user_action": "PAY_NOW",
                "return_url": config.PUBLIC_BASE_URL + "/paypal_return",
                "cancel_url": config.PUBLIC_BASE_URL + "/cancelled",
            },
        })
        d = _api("/v2/checkout/orders", "POST", token=tok, body=body)
        pid = d.get("id")
        for ln in d.get("links", []):
            if ln.get("rel") == "approve":
                return ln.get("href"), pid
        return None, "no approval link in paypal response"
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def capture_order(paypal_order_id):
    """Capture an approved order. Returns (our_order_id, ok, err)."""
    if not config.paypal_enabled():
        return None, False, "paypal not configured"
    try:
        tok = _token()
        d = _api("/v2/checkout/orders/%s/capture" % urllib.parse.quote(paypal_order_id),
                 "POST", token=tok, body="{}")
        status = d.get("status")
        our_id = ""
        for pu in d.get("purchase_units", []):
            our_id = pu.get("custom_id") or our_id
            for cap in (pu.get("payments", {}) or {}).get("captures", []):
                our_id = cap.get("custom_id") or our_id
        return our_id, (status == "COMPLETED"), None
    except Exception as e:  # noqa: BLE001
        return None, False, str(e)


def verify_webhook(headers, raw_body):
    """True if the webhook is authentically from PayPal. Uses PayPal's
    verify-webhook-signature API (needs PAYPAL_WEBHOOK_ID). Fails closed."""
    if not config.PAYPAL_WEBHOOK_ID or not config.paypal_enabled():
        return False
    try:
        tok = _token()
        if not tok:
            return False
        body = json.dumps({
            "auth_algo": headers.get("Paypal-Auth-Algo"),
            "cert_url": headers.get("Paypal-Cert-Url"),
            "transmission_id": headers.get("Paypal-Transmission-Id"),
            "transmission_sig": headers.get("Paypal-Transmission-Sig"),
            "transmission_time": headers.get("Paypal-Transmission-Time"),
            "webhook_id": config.PAYPAL_WEBHOOK_ID,
            "webhook_event": json.loads(raw_body),
        })
        d = _api("/v1/notifications/verify-webhook-signature", "POST", token=tok, body=body)
        return d.get("verification_status") == "SUCCESS"
    except Exception:  # noqa: BLE001
        return False
