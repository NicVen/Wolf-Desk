"""Thin NOWPayments client: create an invoice, and verify IPN webhooks.

Only stdlib. The IPN signature check follows NOWPayments' documented method:
sort the JSON body by keys (recursively), compact-encode it, then HMAC-SHA512
with your IPN secret; compare to the `x-nowpayments-sig` header.
"""
import hashlib
import hmac
import json
import urllib.request

from . import config


def create_invoice(price_usd, order_id, order_description):
    """Create a hosted payment page; returns (invoice_url, invoice_id) or (None, err)."""
    payload = json.dumps({
        "price_amount": price_usd,
        "price_currency": "usd",
        "order_id": order_id,
        "order_description": order_description,
        "ipn_callback_url": config.PUBLIC_BASE_URL + "/ipn",
        "success_url": config.PUBLIC_BASE_URL + "/thanks",
        "cancel_url": config.PUBLIC_BASE_URL + "/cancelled",
    }).encode()
    req = urllib.request.Request(
        config.NOWPAYMENTS_API + "/invoice", data=payload, method="POST",
        headers={"x-api-key": config.NOWPAYMENTS_API_KEY,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        return data.get("invoice_url"), data.get("id")
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def _canonical(data):
    # Recursively sort keys, compact separators — matches NOWPayments' ksort+json_encode.
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def verify_ipn(raw_body, signature):
    """True if the webhook body is authentically from NOWPayments."""
    if not signature or not config.NOWPAYMENTS_IPN_SECRET:
        return False
    try:
        data = json.loads(raw_body)
    except Exception:  # noqa: BLE001
        return False
    digest = hmac.new(config.NOWPAYMENTS_IPN_SECRET.encode(),
                      _canonical(data).encode(), hashlib.sha512).hexdigest()
    return hmac.compare_digest(digest, signature)
