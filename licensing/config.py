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
# PRICES ARE PLACEHOLDERS — set the real ones, then restart the service.
# type:  ea  -> LicenseOK() HTTP gate (automated)
#        signal -> Telegram channel access + copier token (automated via bots)
#        tradingview -> invite-only, activated by hand for now
#        bundle -> VIP: grants every product with vip=True
# vip:   True products are included in the VIP membership.
PRODUCTS = {
    # --- MT5 Expert Advisors ---
    "GOLD":      {"name": "STAALWAG Gold EA",   "price_usd": 40, "period_days": 30, "type": "ea", "file": "STAALWAG_GOLD.mq5",   "vip": True},
    "FX":        {"name": "STAALWAG FX EA",     "price_usd": 40, "period_days": 30, "type": "ea", "file": "STAALWAG_FX.mq5",     "vip": True},
    "CRYPTO":    {"name": "STAALWAG Crypto EA", "price_usd": 40, "period_days": 30, "type": "ea", "file": "STAALWAG_CRYPTO.mq5", "vip": True},
    "PROP":      {"name": "STAALWAG PROP EA",   "price_usd": 40, "period_days": 30, "type": "ea", "file": "STAALWAG_PROP.mq5",   "vip": True},
    "GOUDBREUK": {"name": "GOUDBREUK EA",       "price_usd": 40, "period_days": 30, "type": "ea", "file": "GOUDBREUK.mq5",       "vip": True},
    # --- MT5 Signals (Telegram + copier) ---
    "SIG_GOLD":    {"name": "STAALWAG Gold Desk — signals", "price_usd": 30, "period_days": 30, "type": "signal", "channel": "@staalwagsignals", "vip": True},
    "SIG_VELDRIN": {"name": "VELDRIN FX Desk — signals",    "price_usd": 30, "period_days": 30, "type": "signal", "channel": "@veldrinforex",    "vip": True},
    # Markov 18-pair is FREE (free-tier perk) — not sold individually here.
    # --- TradingView bots + indicators (invite-only; manual activation for now) ---
    "TV_CLAUDEBOT": {"name": "Claude Trading Bot",    "price_usd": 30, "period_days": 30, "type": "tradingview", "vip": False},
    "TV_MARKOVBOT": {"name": "Markov Signal Bot",     "price_usd": 30, "period_days": 30, "type": "tradingview", "vip": False},
    "TV_EDGE13":    {"name": "STAALCALIBUR Edge V13", "price_usd": 30, "period_days": 30, "type": "tradingview", "vip": False},
    "TV_SCALP":     {"name": "Markov Scalper",        "price_usd": 30, "period_days": 30, "type": "tradingview", "vip": False},
    "TV_2GATE":     {"name": "Markov 2 Gate",         "price_usd": 30, "period_days": 30, "type": "tradingview", "vip": False},
    # --- VIP bundle: everything with vip=True (all EAs + all signals; NOT TradingView) ---
    "VIP":       {"name": "VIP Membership — all EAs + signals", "price_usd": 149, "period_days": 30, "type": "bundle", "vip": False},
}


def product(code):
    return PRODUCTS.get((code or "").upper())
