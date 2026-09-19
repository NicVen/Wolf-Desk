"""Licensing service configuration + product catalog.

Secrets come from the environment (see deploy/licensing.env.example). Product
prices/periods live here so you can edit them in one place — change and restart
the service.
"""
import os


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


# --- network / storage ---
BIND_ADDR = os.environ.get("BIND_ADDR", "127.0.0.1")   # behind Caddy
PORT = _int("PORT", 8790)
DB_PATH = os.environ.get("DB_PATH", "/var/lib/staalwag-licensing/licenses.db")

# --- NOWPayments ---
NOWPAYMENTS_API = os.environ.get("NOWPAYMENTS_API", "https://api.nowpayments.io/v1")
NOWPAYMENTS_API_KEY = os.environ.get("NOWPAYMENTS_API_KEY", "")
NOWPAYMENTS_IPN_SECRET = os.environ.get("NOWPAYMENTS_IPN_SECRET", "")

# --- this service's public base (for IPN callback + return links) ---
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://pay.178.104.88.38.sslip.io").rstrip("/")

# --- licensing behaviour ---
SIGNING_SECRET = os.environ.get("LICENSE_SIGNING_SECRET", "")   # signs rolling tokens
GRACE_HOURS = _int("GRACE_HOURS", 4)        # access removed this long after a lapse
TOKEN_TTL_HOURS = _int("TOKEN_TTL_HOURS", 6)  # how long a rolling token is trusted offline
RENEW_NOTICE_DAYS = _int("RENEW_NOTICE_DAYS", 3)  # warn client this many days before expiry

# --- admin (manual issue / comp) ---
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

# --- notifications (optional) ---
LICENSE_BOT_TOKEN = os.environ.get("LICENSE_BOT_TOKEN", "")  # Telegram bot for client notices
LICENSE_ADMIN_CHAT = os.environ.get("LICENSE_ADMIN_CHAT", "")  # your own chat id for copies

# ---------------------------------------------------------------------------
# Product catalog — the EAs and indicators you rent. Prices in USD; period in
# days. Edit freely, then `systemctl restart staalwag-licensing`.
# `kind` is just a label (ea / indicator). `key` is the code clients see, e.g.
# STAAL-GOLD-XXXXXXXX.
# ---------------------------------------------------------------------------
PRODUCTS = {
    "GOLD":        {"name": "STAALWAG Gold EA",        "price_usd": 40, "period_days": 30, "kind": "ea"},
    "STAALFLITS":  {"name": "STAALFLITS EA",           "price_usd": 40, "period_days": 30, "kind": "ea"},
    "STAALBREUK":  {"name": "STAALBREUK EA",           "price_usd": 40, "period_days": 30, "kind": "ea"},
    "EXCALIBUR13": {"name": "Excalibur Edge V13",      "price_usd": 30, "period_days": 30, "kind": "indicator"},
    "MARKOVSCALP": {"name": "Markov Scalper",          "price_usd": 30, "period_days": 30, "kind": "indicator"},
    "MARKOV2GATE": {"name": "Markov 2 Gate",           "price_usd": 30, "period_days": 30, "kind": "indicator"},
}


def product(code):
    return PRODUCTS.get((code or "").upper())
