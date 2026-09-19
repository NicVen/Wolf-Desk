"""Thin Stripe client: create a hosted Checkout session, and verify webhooks.

Only stdlib. Inert until STRIPE_SECRET_KEY is set — create_checkout returns an
error and the buy page hides the card button, so nothing breaks before you have
a provider. Swap Stripe for another card processor by re-implementing these two
functions; the rest of the licensing flow (apply_payment, sweeper) is unchanged.

Signature check follows Stripe's documented scheme: the Stripe-Signature header
is `t=<ts>,v1=<hex>`; signed_payload = "<ts>.<raw body>"; HMAC-SHA256 with the
webhook signing secret; compare to v1.
"""
import hashlib
import hmac
import time
import urllib.parse
import urllib.request

from . import config


def create_checkout(price_usd, order_id, description):
    """Create a hosted card-payment page; returns (url, session_id) or (None, err)."""
    if not config.card_enabled():
        return None, "card payments not configured"
    # Stripe wants form-encoded params and integer cents.
    params = {
        "mode": "payment",
        "success_url": config.PUBLIC_BASE_URL + "/thanks",
        "cancel_url": config.PUBLIC_BASE_URL + "/cancelled",
        "client_reference_id": order_id,
        "metadata[order_id]": order_id,
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "usd",
        "line_items[0][price_data][unit_amount]": str(int(round(float(price_usd) * 100))),
        "line_items[0][price_data][product_data][name]": description,
    }
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        config.STRIPE_API + "/checkout/sessions", data=data, method="POST",
        headers={"Authorization": "Bearer " + config.STRIPE_SECRET_KEY,
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        import json
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read())
        return d.get("url"), d.get("id")
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def verify_webhook(raw_body, signature, tolerance=300):
    """True if the webhook is authentically from Stripe (and recent)."""
    if not signature or not config.STRIPE_WEBHOOK_SECRET:
        return False
    ts, v1 = None, None
    for part in signature.split(","):
        if "=" not in part:
            continue
        k, val = part.split("=", 1)
        if k == "t":
            ts = val
        elif k == "v1":
            v1 = val
    if not ts or not v1:
        return False
    try:
        if abs(time.time() - int(ts)) > tolerance:   # replay guard
            return False
    except ValueError:
        return False
    if isinstance(raw_body, bytes):
        raw_body = raw_body.decode("utf-8", "replace")
    signed = ("%s.%s" % (ts, raw_body)).encode()
    digest = hmac.new(config.STRIPE_WEBHOOK_SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, v1)
