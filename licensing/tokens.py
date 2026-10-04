"""Rolling activation token.

Every successful /verify hands back a fresh, signed, short-lived token. It's the
"revolving activation code": it changes on every check-in and every renewal, so a
copied token dies quickly and a lapsed license can't keep trading offline forever.

Format (before base64url):  key|product|expires_at|token_exp|nonce|sig
  expires_at = when the paid period ends (access hard stop)
  token_exp  = when this token must be refreshed (paid_until capped by TTL)
  sig        = HMAC-SHA256(signing_secret, everything-before-sig)
"""
import base64
import hashlib
import hmac
import os
import time

from . import config


def _sign(msg):
    return hmac.new(config.SIGNING_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()


def issue(license_key, product, expires_at):
    token_exp = min(int(expires_at), int(time.time()) + config.TOKEN_TTL_HOURS * 3600)
    nonce = os.urandom(6).hex()
    body = "%s|%s|%d|%d|%s" % (license_key, product, int(expires_at), token_exp, nonce)
    raw = body + "|" + _sign(body)
    return base64.urlsafe_b64encode(raw.encode()).decode()


def verify(token):
    """Validate a token offline (used if you ever check tokens server-side).
    Returns dict or None."""
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        body, sig = raw.rsplit("|", 1)
        if not hmac.compare_digest(sig, _sign(body)):
            return None
        key, product, expires_at, token_exp, _nonce = body.split("|")
        if int(token_exp) < int(time.time()):
            return None
        return {"license_key": key, "product": product,
                "expires_at": int(expires_at), "token_exp": int(token_exp)}
    except Exception:
        return None
