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


# --- Sales switch ---
# Paid checkouts are OFF until Nic confirms his visa allows selling (2026-10-06).
# Free trials, testers and the app keep working. To open sales: put
# SALES_PAUSED=0 in /etc/staalwag-licensing.env and restart the service.
SALES_PAUSED = os.environ.get("SALES_PAUSED", "1").strip().lower() not in ("0", "false", "no", "off")


def card_enabled():
    """True once a card provider is configured (keys present in the env)."""
    return bool(STRIPE_SECRET_KEY)


# --- PayPal — inert until these are set ---
# Create a REST app at developer.paypal.com -> Apps & Credentials (Live), copy the
# Client ID + Secret into the service env, then add a webhook at that same page
# pointing to <PUBLIC_BASE_URL>/paypal_ipn (event: PAYMENT.CAPTURE.COMPLETED) and
# copy its Webhook ID:
#   PAYPAL_CLIENT_ID=...    PAYPAL_SECRET=...    PAYPAL_WEBHOOK_ID=...
# Use the live API by default; set PAYPAL_API to the sandbox host while testing.
PAYPAL_API = os.environ.get("PAYPAL_API", "https://api-m.paypal.com").rstrip("/")
PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "")
PAYPAL_SECRET = os.environ.get("PAYPAL_SECRET", "")
PAYPAL_WEBHOOK_ID = os.environ.get("PAYPAL_WEBHOOK_ID", "")


def paypal_enabled():
    """True once PayPal is configured (client id + secret present)."""
    return bool(PAYPAL_CLIENT_ID and PAYPAL_SECRET)

# --- this service's public base (for IPN callback + return links) ---
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://pay.178.104.88.38.sslip.io").rstrip("/")

# --- licensing behaviour ---
SIGNING_SECRET = os.environ.get("LICENSE_SIGNING_SECRET", "")   # signs rolling tokens
GRACE_HOURS = _int("GRACE_HOURS", 4)        # access removed this long after a lapse
APP_TRIAL_DAYS = _int("APP_TRIAL_DAYS", 7)  # free STAALCALIBUR App trial length (0 = trials off)
APP_PROMO_NOTE = os.environ.get("APP_PROMO_NOTE", "Launch price — limited time only")  # shown on the storefront while the App promo price is live
REFERRAL_REWARD_DAYS = _int("REFERRAL_REWARD_DAYS", 30)  # free days a referrer earns per paid referral
PARTNER_REWARD_DAYS = _int("PARTNER_REWARD_DAYS", 30)    # reward (in App-days) an external banner partner earns per paid referral
SITE_URL = os.environ.get("SITE_URL", "https://staalwag.com").rstrip("/")

# --- Trader Quiz monthly winner (auto-announced on the 1st) ---
QUIZ_AUTO_WINNER = os.environ.get("QUIZ_AUTO_WINNER", "1") not in ("0", "false", "False", "")
QUIZ_REWARD = os.environ.get("QUIZ_REWARD", "1 month free VIP — we'll be in touch to set it up")
# --- App update rhythm (shown on the in-app Ideas board + drives the digests) ---
# Bugs: fixed weekly (bug list every Monday). Small ideas: every 2 weeks, counted
# from RELEASE_ANCHOR (top ideas sent the Monday before). Big ideas: the 1st of
# each month.
RELEASE_ANCHOR = os.environ.get("RELEASE_ANCHOR", "2026-10-17")
DIGEST_HOUR_UTC = _int("DIGEST_HOUR_UTC", 7)
TOKEN_TTL_HOURS = _int("TOKEN_TTL_HOURS", 6)  # how long a rolling token is trusted offline
RENEW_NOTICE_DAYS = _int("RENEW_NOTICE_DAYS", 3)  # warn client this many days before expiry

# --- admin (manual issue / comp) ---
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

# --- HQ health monitor: systemd units to watch (space-separated) ---
HQ_UNITS = os.environ.get("HQ_UNITS", "caddy wolf-desk staalwag-licensing staalwag-desktop").split()

# --- notifications (optional) ---
LICENSE_BOT_TOKEN = os.environ.get("LICENSE_BOT_TOKEN", "")  # Telegram bot for client notices
LICENSE_ADMIN_CHAT = os.environ.get("LICENSE_ADMIN_CHAT", "")  # your own chat id for copies
# Google Play closed test: Google needs TESTER_GOAL people opted in for 14 days
# before the app can go public. Sign-ups at staalwag.com/testers. Paste the Play
# Console opt-in link into PLAY_OPTIN_URL once Google approves the test release;
# the page then shows it. TESTER_REWARD is the line promising testers a thank-you.
TESTER_GOAL = _int("TESTER_GOAL", 12)
PLAY_OPTIN_URL = os.environ.get("PLAY_OPTIN_URL", "")
TESTER_REWARD = os.environ.get("TESTER_REWARD", "Stay installed 14 days and get a free month of the app.")

# Nightly off-server backup of licenses.db, sent as a file by the licensing bot
# (licensing/backup.py). Defaults to the owner's admin chat. Hour is UTC.
BACKUP_CHAT = os.environ.get("BACKUP_CHAT", "") or LICENSE_ADMIN_CHAT
BACKUP_HOUR_UTC = _int("BACKUP_HOUR_UTC", 2)
UPDATES_CHAT = os.environ.get("UPDATES_CHAT", "")  # private "STAALWAG Updates" channel (deploy/updates-channel-setup.sh)
UPDATES_BOT_TOKEN = os.environ.get("UPDATES_BOT_TOKEN", "")  # its own bot, separate from signals + licensing
# Read/post token for the automated Monday build (GET /digest, POST /ready). Can
# only read the weekly bug/idea list and post a "ready to approve" link to a PR
# in the Wolf-Desk repo — nothing else. Blank = both endpoints off.
DIGEST_TOKEN = os.environ.get("DIGEST_TOKEN", "")
UPDATES_REPO_URL = os.environ.get("UPDATES_REPO_URL", "https://github.com/NicVen/Wolf-Desk")
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
    "APP":       {"name": "STAALCALIBUR App", "price_solo": 14.99, "price_vip": 14.99, "price_regular": 25, "period_days": 30, "type": "app", "vip": False},
    # --- STAALWAG mobile toolkit (prices set by Nic, 5 Oct 2026) ---
    # Add-ons ride on the trader's App key: buying one with `attach` = their App
    # key makes that same key unlock it (see server.start_checkout / _verify).
    # TOOLKIT is one key that unlocks everything in `includes`.
    # Each stays in LOCKED below until its feature is live in the app.
    "GUARDIAN":  {"name": "Guardian", "price_solo": 24.99, "price_vip": 24.99, "price_regular": 35, "period_days": 30, "type": "app_addon", "vip": False},
    "HOURS":     {"name": "Prime Hours", "price_solo": 7.99, "price_vip": 7.99, "price_regular": 10, "period_days": 30, "type": "app_addon", "vip": False},
    "TOOLKIT":   {"name": "STAALWAG Toolkit (App + Guardian + Prime Hours)", "price_solo": 39.99, "price_vip": 39.99, "price_regular": 55, "period_days": 30, "type": "app_bundle", "vip": False,
                  "includes": ["APP", "GUARDIAN", "HOURS"]},
    # --- VIP membership: $40/mo. Unlocks every vip=True product ---
    "VIP":       {"name": "VIP Membership", "price_solo": 40, "price_vip": 40, "period_days": 30, "type": "bundle", "vip": False},
}


# Nothing but the App is for sale until it has a proven public record (Nic,
# 4 Oct 2026). Locked products can't be bought or trialled; keys already issued
# (Nic's own testing) keep working. To open one: remove it from LOCKED.
LOCKED = {c for c in PRODUCTS if c != "APP"}
LOCKED_NOTE = "In testing - not for sale until it passes its public track-record test."


def product(code):
    return PRODUCTS.get((code or "").upper())


def unlocks(holder, wanted):
    """True if a key for product `holder` also opens product `wanted`
    (a bundle like TOOLKIT, or VIP for vip=True products)."""
    holder, wanted = (holder or "").upper(), (wanted or "").upper()
    if holder == wanted:
        return True
    h, w = product(holder), product(wanted)
    if h and wanted in (h.get("includes") or []):
        return True
    return holder == "VIP" and bool(w and w.get("vip"))
