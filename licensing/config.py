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

# --- NOWPayments (crypto) ---
NOWPAYMENTS_API = os.environ.get("NOWPAYMENTS_API", "https://api.nowpayments.io/v1")
NOWPAYMENTS_API_KEY = os.environ.get("NOWPAYMENTS_API_KEY", "")
NOWPAYMENTS_IPN_SECRET = os.environ.get("NOWPAYMENTS_IPN_SECRET", "")

# --- Card payments (Stripe) — inert until these are set ---
# Sign up at stripe.com, then put the keys in the service env file and restart:
#   STRIPE_SECRET_KEY=sk_live_...        (or sk_test_... while testing)
#   STRIPE_WEBHOOK_SECRET=whsec_...      (from the webhook you point at /card_ipn)
STRIPE_API = os.environ.get("STRIPE_API", "https://api.stripe.com/v1")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")


def card_enabled():
    """True once a card provider is configured (keys present in the env)."""
    return bool(STRIPE_SECRET_KEY)

# --- this service's public base (for IPN callback + return links) ---
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://pay.178.104.88.38.sslip.io").rstrip("/")

# --- licensing behaviour ---
SIGNING_SECRET = os.environ.get("LICENSE_SIGNING_SECRET", "")   # signs rolling tokens
GRACE_HOURS = _int("GRACE_HOURS", 4)        # access removed this long after a lapse
APP_TRIAL_DAYS = _int("APP_TRIAL_DAYS", 7)  # free STAALCALIBUR App trial length (0 = trials off)
APP_PROMO_NOTE = os.environ.get("APP_PROMO_NOTE", "Launch price — limited time only")  # shown on the storefront while the App promo price is live
REFERRAL_REWARD_DAYS = _int("REFERRAL_REWARD_DAYS", 30)  # free days a referrer earns per paid referral
SITE_URL = os.environ.get("SITE_URL", "https://staalwag.com").rstrip("/")

# --- Trader Quiz monthly winner (auto-announced on the 1st) ---
QUIZ_AUTO_WINNER = os.environ.get("QUIZ_AUTO_WINNER", "1") not in ("0", "false", "False", "")
QUIZ_REWARD = os.environ.get("QUIZ_REWARD", "1 month free VIP — we'll be in touch to set it up")
TOKEN_TTL_HOURS = _int("TOKEN_TTL_HOURS", 6)  # how long a rolling token is trusted offline
RENEW_NOTICE_DAYS = _int("RENEW_NOTICE_DAYS", 3)  # warn client this many days before expiry

# --- admin (manual issue / comp) ---
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

# --- HQ health monitor: systemd units to watch (space-separated) ---
HQ_UNITS = os.environ.get("HQ_UNITS", "caddy wolf-desk staalwag-licensing staalwag-desktop").split()

# --- notifications (optional) ---
LICENSE_BOT_TOKEN = os.environ.get("LICENSE_BOT_TOKEN", "")  # Telegram bot for client notices
LICENSE_ADMIN_CHAT = os.environ.get("LICENSE_ADMIN_CHAT", "")  # your own chat id for copies
LICENSE_BOT_USERNAME = os.environ.get("LICENSE_BOT_USERNAME", "")  # e.g. @StaalwagBot (shown on the buy page)

# ---------------------------------------------------------------------------
# Product catalog — the EAs and indicators you rent. Prices in USD; period in
# days. Edit freely, then `systemctl restart staalwag-licensing`.
# `kind` is just a label (ea / indicator). `key` is the code clients see, e.g.
# STAAL-GOLD-XXXXXXXX.
# ---------------------------------------------------------------------------
# Two-tier pricing:
#   price_solo = monthly rental for a (free-tier) subscriber, NOT on VIP
#   price_vip  = monthly cost for a VIP member (0 = included free with VIP)
#   vip=True   = auto-unlocked by an active VIP membership (no separate purchase)
#   vip=False  = NOT auto-included; a VIP member pays price_vip as an add-on
# type: ea -> LicenseOK() gate · signal -> Telegram+copier · tradingview -> invite (manual)
#       bundle -> VIP membership itself
PRODUCTS = {
    # --- MT5 Expert Advisors: $30 solo, free on VIP ---
    "GOLD":      {"name": "STAALWAG Gold EA",   "price_solo": 30, "price_vip": 0, "period_days": 30, "type": "ea", "file": "STAALWAG_GOLD.mq5",   "vip": True},
    "FX":        {"name": "STAALWAG FX EA",     "price_solo": 30, "price_vip": 0, "period_days": 30, "type": "ea", "file": "STAALWAG_FX.mq5",     "vip": True},
    "CRYPTO":    {"name": "STAALWAG Crypto EA", "price_solo": 30, "price_vip": 0, "period_days": 30, "type": "ea", "file": "STAALWAG_CRYPTO.mq5", "vip": True},
    "PROP":      {"name": "STAALWAG PROP EA",   "price_solo": 30, "price_vip": 0, "period_days": 30, "type": "ea", "file": "STAALWAG_PROP.mq5",   "vip": True},
    # GOUDBREUK: $30 solo, $10 add-on even for VIP (NOT auto-included)
    "GOUDBREUK": {"name": "GOUDBREUK EA",       "price_solo": 30, "price_vip": 10, "period_days": 30, "type": "ea", "file": "GOUDBREUK.mq5",      "vip": False},
    # --- MT5 Signals ---
    "SIG_GOLD":    {"name": "STAALWAG Gold Desk — signals", "price_solo": 20, "price_vip": 0,  "period_days": 30, "type": "signal", "channel": "@staalwagsignals", "vip": True},   # free on VIP
    "SIG_VELDRIN": {"name": "VELDRIN FX Desk — signals",    "price_solo": 20, "price_vip": 20, "period_days": 30, "type": "signal", "channel": "@veldrinforex",    "vip": False},  # $20 add-on on VIP
    "SIG_M18":     {"name": "Markov 18-pair — signals",     "price_solo": 0,  "price_vip": 0,  "period_days": 30, "type": "signal", "free": True},  # FREE with the free subscription
    # --- TradingView bots + indicators (prices set next) ---
    "TV_CLAUDEBOT": {"name": "Claude Trading Bot",    "price_solo": 0, "price_vip": 0, "period_days": 30, "type": "tradingview", "vip": False, "tbd": True},
    "TV_MARKOVBOT": {"name": "Markov Signal Bot",     "price_solo": 0, "price_vip": 0, "period_days": 30, "type": "tradingview", "vip": False, "tbd": True},
    "TV_EDGE13":    {"name": "STAALCALIBUR Edge V13", "price_solo": 0, "price_vip": 0, "period_days": 30, "type": "tradingview", "vip": False, "tbd": True},
    "TV_SCALP":     {"name": "Markov Scalper",        "price_solo": 0, "price_vip": 0, "period_days": 30, "type": "tradingview", "vip": False, "tbd": True},
    # Markov 2 Gate — a chart add-on (supplementary info, any pair/timeframe), FREE with the free subscription
    "TV_2GATE":     {"name": "Markov 2 Gate — chart add-on", "price_solo": 0, "price_vip": 0, "period_days": 30, "type": "addon", "vip": False, "free": True},
    # --- STAALCALIBUR mobile app: rental only (not bundled in VIP) ---
    # Launch promo: charged price is $9.99/mo; price_regular ($25) is the "was"
    # price shown struck-through. To END the promo: set price_solo/price_vip back
    # to 25 (the storefront then drops the strike-through + "limited time" badge
    # automatically). price_regular is display-only; it is never charged.
    "APP":       {"name": "STAALCALIBUR App", "price_solo": 9.99, "price_vip": 9.99, "price_regular": 25, "period_days": 30, "type": "app", "vip": False},
    # --- VIP membership: $40/mo. Unlocks every vip=True product ---
    "VIP":       {"name": "VIP Membership", "price_solo": 40, "price_vip": 40, "period_days": 30, "type": "bundle", "vip": False},
}


def product(code):
    return PRODUCTS.get((code or "").upper())
