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
import calendar
import datetime
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import backup, cardpay, config, moderation, nowpayments, notify, paypal, quiz, store, tokens


def _today():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")


def _period():
    return datetime.datetime.utcnow().strftime("%Y-%m")


def _days_left():
    n = datetime.datetime.utcnow()
    return calendar.monthrange(n.year, n.month)[1] - n.day

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
    if code.upper() in config.LOCKED:
        return 0, config.LOCKED_NOTE
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


def start_checkout(product_code, contact, method="crypto", ref="", attach=""):
    p = config.product(product_code)
    if not p:
        return None, "unknown product"
    price, note = price_for(product_code, contact)
    if price <= 0:
        return None, note or "nothing to charge for this item"
    order = None
    if p.get("type") == "app_addon":
        # an add-on rides on the trader's existing App key: that key unlocks it
        parent = store.get((attach or "").strip())
        if (not parent or parent["status"] == "pending"
                or not config.unlocks(parent["product"], "APP")):
            return None, "Enter the app key you want to add this to."
        contact = contact or parent.get("contact") or ""
        old = store.addon_for(parent["license_key"], product_code)
        if old:                                   # renewal: extend the same row
            key = old["license_key"]
            order = "%s-%s" % (key, secrets.token_hex(3).upper())
            store.update(key, order_id=order)
        else:
            key = new_license_key(product_code)
            order = key
            store.create(key, product_code.upper(), contact, order_id=key, status="pending")
            store.update(key, attach_to=parent["license_key"], no_bind=1)
    else:
        key = new_license_key(product_code)
        order = key
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
        url, ref = cardpay.create_checkout(price, order_id=order, description=desc)
    elif method == "paypal":
        url, ref = paypal.create_checkout(price, order_id=order, description=desc)
    else:
        url, ref = nowpayments.create_invoice(price, order_id=order, order_description=desc)
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
    if not lic.get("paid_since"):              # the first payment: the app's tools unlock from this day
        store.update(lic["license_key"], paid_since=store.now())
    when = time.strftime("%Y-%m-%d", time.gmtime(paid_until))
    if lic.get("attach_to"):
        notify.client(lic["contact"],
                      "Payment received. %s is now unlocked on your app key %s until %s (UTC).\n"
                      "Open the app and it's ready, no new key needed."
                      % ((p or {}).get("name", lic["product"]), lic["attach_to"], when))
    else:
        notify.client(lic["contact"],
                      "Payment received. Your %s access is active until %s (UTC).\n"
                      "Activation key: %s\nEnter this key in the product to unlock it."
                      % (lic["product"], when, lic["license_key"]))
    notify.admin("payment ok: %s -> active until %s" % (lic["license_key"], when))
    _reward_referrer(lic)


def _reward_referrer(lic):
    """First paid activation of a referred license may credit the referrer with
    a free month. Rules: only ONE referral free month active at a time — no
    stacking, no banking. If the referrer is already inside a free-month window,
    this referral is acknowledged but grants nothing; they can earn again only
    after the current free month ends. Runs once per referred license."""
    code = lic.get("referred_by")
    if not code or lic.get("ref_rewarded"):
        return
    ref = store.get_by_ref_code(code)
    if not ref or ref["license_key"] == lic["license_key"]:
        # Not a customer's referral code -> treat it as an external PARTNER banner
        # tag. Count the conversion, then grant a reward window ONLY if the partner
        # isn't already inside one -> NO STACKING, no banking (mirrors the customer
        # free-month rule). Self-referral codes fall here too and are harmless.
        if code and not ref:
            pr = store.partner_touch(code)
            store.update(lic["license_key"], ref_rewarded=3)
            if pr:
                now = store.now(); days = config.PARTNER_REWARD_DAYS
                active_until = pr.get("reward_until") or 0
                if now < active_until:
                    when = time.strftime("%Y-%m-%d", time.gmtime(active_until))
                    notify.admin("PARTNER (no-stack): tag '%s' converted (paid_refs=%d) but "
                                 "already in a reward window to %s — not extended."
                                 % (code, pr["paid_refs"], when))
                else:
                    store.partner_open_window(code, days)
                    when = time.strftime("%Y-%m-%d", time.gmtime(now + days * DAY))
                    notify.admin("PARTNER reward: tag '%s' earned a %d-day window (to %s, no-stack); "
                                 "paid_refs=%d. Settle via /admin/partner_settle."
                                 % (code, days, when, pr["paid_refs"]))
        return
    now = store.now()
    days = config.REFERRAL_REWARD_DAYS
    active_until = ref.get("ref_reward_until") or 0

    if now < active_until:
        # already in a free-month window — acknowledge, don't stack.
        store.update(lic["license_key"], ref_rewarded=2)
        when = time.strftime("%Y-%m-%d", time.gmtime(active_until))
        notify.client(ref.get("contact"),
                      "A referral of yours just subscribed 🙌 — but you already have a free "
                      "month running (until %s UTC). Free months don't stack; refer again "
                      "after that date to earn the next one." % when)
        notify.admin("referral (no-stack): %s already covered to %s" % (ref["license_key"], when))
        return

    # grant a fresh free month
    base = max(now, ref.get("paid_until") or 0)
    reward_until = now + days * DAY
    store.update(ref["license_key"], status="active", paid_until=base + days * DAY,
                 revoke_at=None, notified=0, ref_reward_until=reward_until)
    store.update(lic["license_key"], ref_rewarded=1)
    until = time.strftime("%Y-%m-%d", time.gmtime(base + days * DAY))
    notify.client(ref.get("contact"),
                  "🎉 A referral of yours just subscribed — you've earned %d free days! "
                  "Your access now runs to %s (UTC). (One free month at a time — refer "
                  "again once this one ends to earn another.)" % (days, until))
    notify.admin("referral reward: %s credited %dd (referred %s)"
                 % (ref["license_key"], days, lic["license_key"]))


def _load_rewards():
    """The rotating reward pool. Editable at licensing/quiz_rewards.json, or via
    the QUIZ_REWARDS env (pipe-separated); falls back to the single QUIZ_REWARD."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quiz_rewards.json")
    try:
        with open(path) as f:
            r = json.load(f)
        pool = [str(x).strip() for x in r if str(x).strip()]
        if pool:
            return pool
    except Exception:  # noqa: BLE001
        pass
    env = os.environ.get("QUIZ_REWARDS", "")
    if env.strip():
        return [s.strip() for s in env.split("|") if s.strip()]
    return [config.QUIZ_REWARD]


def peek_reward():
    """Next reward without advancing the rotation (for previews)."""
    pool = _load_rewards()
    idx = int(store.meta_get("quiz_reward_idx", "0") or "0")
    return pool[idx % len(pool)]


def next_reward():
    """Next reward AND advance the rotation so the following month differs."""
    pool = _load_rewards()
    idx = int(store.meta_get("quiz_reward_idx", "0") or "0")
    store.meta_set("quiz_reward_idx", str((idx + 1) % 1000000))
    return pool[idx % len(pool)]


def announce_quiz_winner(period, reward=None, public=True):
    """Decide + announce the Trader Quiz winner for a period. Winner gets a
    private DM with the reward; everyone else gets a public message naming only
    the winner's anonymous id. When reward is None the rotating pool is used and
    advanced. Returns a result dict."""
    board = store.quiz_leaderboard(period, 1)
    if not board:
        return {"ok": False, "reason": "no quiz plays in %s" % period}
    if reward is None:
        reward = next_reward()
    anon, pts, wkey = board[0]
    wlic = store.get(wkey)
    notify.client(wlic.get("contact") if wlic else None,
                  "🏆 You WON the STAALCALIBUR Trader Quiz for %s with %d points!\n"
                  "Reward: %s.\nYour public winner id is %s — we only ever announce that, "
                  "never your identity." % (period, pts, reward, anon))
    sent = 0
    if public:
        msg = ("🏆 STAALCALIBUR Trader Quiz — %s winner: %s with %d points! "
               "Congratulations. Play the daily quiz to top next month's board." % (period, anon, pts))
        for contact in store.active_contacts("APP"):
            notify.client(contact, msg)
            sent += 1
    notify.admin("quiz winner %s: %s (%d pts) — %s — announced to %d" % (period, anon, pts, reward, sent))
    store.meta_set("quiz_winner_last", period)   # so it won't be announced twice
    return {"ok": True, "period": period, "winner_anon": anon, "points": pts,
            "reward": reward, "notified": sent}


def _prev_period():
    first = datetime.datetime.utcnow().replace(day=1)
    return (first - datetime.timedelta(days=1)).strftime("%Y-%m")


def _age(lic):
    """How long this key has been a paying one: the app reveals its tools over
    the first days after purchase. A trial key reports trial=True."""
    return {"trial": bool(lic.get("trial")), "since": lic.get("paid_since") or lic.get("created"),
            "for_sale": [c for c in TOOL_REVEAL if c not in config.LOCKED]}


# The app shows its tools step by step after purchase (app_tools.py in the
# app). The app itself sells nothing (Google Play), so when a tool becomes
# available the customer is told here, on Telegram, once per tool.
TOOL_REVEAL = {"HOURS": 7, "GUARDIAN": 12}          # add-on -> day after first payment
TOOL_PITCH = {"HOURS": "See the hours each market really moves, in your own time zone, and the dead zones to sit out.",
              "GUARDIAN": "It watches every trade you open in MT5 and warns you on your phone when one is too big, "
                          "badly timed, or puts your prop-firm challenge at risk."}


def tool_notices(lic, now):
    """[(level, text)] still owed to this paying App key: one message per
    add-on once its day has come, it is for sale, and the key doesn't have it."""
    if (lic.get("status") != "active" or lic.get("trial") or lic.get("attach_to")
            or not config.unlocks(lic["product"], "APP") or not lic.get("paid_since")):
        return []
    days = (now - lic["paid_since"]) / DAY
    told, out = int(lic.get("tools_told") or 0), []
    for level, (code, day) in enumerate(sorted(TOOL_REVEAL.items(), key=lambda x: x[1]), 1):
        if level <= told or days < day or code in config.LOCKED or config.unlocks(lic["product"], code):
            continue
        addon = store.addon_for(lic["license_key"], code)
        if addon and check_access(addon)[0]:
            continue
        p = config.product(code)
        out.append((level, "New in STAALCALIBUR: %s is ready for your app.\n%s\n\nAdd it to your key %s at "
                           "staalwag.com/store for $%s/month (launch price, regular $%s)."
                    % (p["name"], TOOL_PITCH[code], lic["license_key"], p["price_solo"], p.get("price_regular") or p["price_solo"])))
    return out


# Google Play's reviewers must be able to open the app. They use one key that
# works on any device; it is made once, on first start, and sent to the admin
# chat so the owner can paste it into Play Console (App content -> App access).
REVIEW_CONTACT = "google-play-review"


def ensure_review_key():
    """Return (key, made_now)."""
    key = store.meta_get("review_key")
    if key and store.get(key):
        return key, False
    key = new_license_key("APP")
    now = store.now()
    store.create(key, "APP", REVIEW_CONTACT, order_id=key, status="pending")
    store.update(key, status="active", paid_until=now + 3650 * DAY, revoke_at=None,
                 no_bind=1, paid_since=now - 30 * DAY, tools_told=len(TOOL_REVEAL))
    store.meta_set("review_key", key)
    notify.admin("Google Play reviewer key: %s\n\nPlay Console -> App content -> App access -> "
                 "'All or some functionality is restricted' -> Add instructions. Name: Activation key. "
                 "Paste the key, and write: Open the app, type this key into the activation box, "
                 "tap Unlock. Works on any device." % key)
    return key, True


def delete_request(key, contact):
    """The public 'delete my data' form. A matching key + contact is erased at
    once; anything else goes to the admin chat to be done by hand. The answer
    never says whether a key exists."""
    key, contact = (key or "").strip().upper()[:60], (contact or "").strip()[:120]
    lic = store.get(key) if key else None
    match = bool(lic and contact and (lic.get("contact") or "").strip().lower() == contact.lower()
                 and not lic.get("admin") and lic.get("contact") != REVIEW_CONTACT)
    erased = store.erase_license(key) if match else []
    gone = store.forget_contact(contact)
    if match:
        notify.admin("Data deleted on request: %s (%s)" % (", ".join(erased), contact))
    else:
        notify.admin("Deletion request to do by hand (key %s, contact %s). %d tester/subscriber "
                     "rows removed automatically." % (key or "-", contact or "-", gone))
    return {"ok": True, "erased": erased}


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
# Ideas board: release rhythm, one-tap review links, owner digests
# ---------------------------------------------------------------------------
CAT_LABELS = {"signals": "Signals", "charts": "Charts", "alerts": "Alerts",
              "quiz": "Quiz", "bug": "Bug", "other": "Other"}


def next_release(today=None):
    """Next biweekly small-update date (on or after today)."""
    today = today or datetime.datetime.utcnow().date()
    try:
        anchor = datetime.date.fromisoformat(config.RELEASE_ANCHOR)
    except ValueError:
        anchor = today
    if today <= anchor:
        return anchor
    return anchor + datetime.timedelta(days=-(-(today - anchor).days // 14) * 14)


def next_big_release(today=None):
    """Big updates ship on the 1st of the month."""
    today = today or datetime.datetime.utcnow().date()
    if today.day == 1:
        return today
    return (today.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)


def _fmt_day(d):
    return "%d %s" % (d.day, d.strftime("%b"))


def apply_idea_status(sid, status, size=None):
    """Set an idea's status and tell the right people in the app:
    built -> everyone who voted; duplicate -> the person who sent it."""
    before = store.get_suggestion(sid)
    store.set_suggestion_status(sid, status, size)
    if not before or before["status"] == status:
        return
    short = before["text"] if len(before["text"]) <= 80 else before["text"][:77] + "…"
    if status == "built":
        for k in store.idea_voters(sid):
            store.add_notice(k, "🎉 You asked, we built it: “%s”. Update the app to get it." % short)
    elif status == "duplicate":
        store.add_notice(before.get("license_key"),
                         "👍 Good news: “%s” is already in the app. See Built ✅ on the Ideas board." % short)


_STOP = set("the and for with please add can you app would like have that this make more should "
             "could when what from into also want need".split())


def _words(t):
    return {w[:-1] if w.endswith("s") else w
            for w in re.findall(r"[a-z0-9]+", (t or "").lower()) if len(w) > 2 and w not in _STOP}


def similar_idea(text, threshold=0.6):
    """Plain word-overlap match (same rule the app uses while typing) against
    ideas on the board. Returns the best match or None. No AI involved."""
    a, best, score = _words(text), None, 0.0
    if not a:
        return None
    for x in store.public_ideas():
        b = _words(x["text"])
        if b:
            v = len(a & b) / min(len(a), len(b))
            if v > score:
                best, score = x, v
    return best if score >= threshold else None


def _idea_lines(rows):
    return ["%d. [%s] %s — 👍 %d" % (i, CAT_LABELS.get(x["category"], "Other"), x["text"][:120], x["votes"])
            for i, x in enumerate(rows, 1)]


def send_weekly_digest(include_ideas):
    """The ONE message the owner gets each week (Monday). Bugs every week; the
    top-voted ideas only in the week of a 2-weekly update."""
    bugs = store.open_bugs()
    lines = ["📋 STAALCALIBUR weekly"]
    if bugs:
        lines.append("\n🐞 Fix this week (%d bug report%s):" % (len(bugs), "" if len(bugs) == 1 else "s"))
        lines += ["• %s" % b["text"][:160] for b in bugs[:15]]
    else:
        lines.append("\n🐞 No open bug reports.")
    if include_ideas:
        small, big = store.top_ideas("small", 5), store.top_ideas("big", 3)
        lines.append("\n💡 Build for the %s update (most votes first):" % _fmt_day(next_release()))
        lines += _idea_lines(small) or ["(no ideas on the board yet)"]
        if big:
            lines.append("\n🏗 Big ideas for %s:" % _fmt_day(next_big_release()))
            lines += _idea_lines(big)
    if config.DIGEST_TOKEN:
        lines.append("\n🔧 Being built now. You'll get a ✅ Approve button here when it's ready.")
    else:
        lines.append("\nForward this to your developer to get it built.")
    notify.updates("\n".join(lines))


def digest_data(today=None):
    """What the automated Monday build works from (GET /digest)."""
    today = today or datetime.datetime.utcnow().date()
    release_week = (next_release(today) - today).days <= 6
    return {
        "date": today.isoformat(),
        "release_week": release_week,
        "next_update": next_release(today).isoformat(),
        "next_big_update": next_big_release(today).isoformat(),
        "bugs": [{"id": b["id"], "text": b["text"]} for b in store.open_bugs()],
        "ideas": store.top_ideas("small", 5) if release_week else [],
        "big_ideas": store.top_ideas("big", 3),
    }


def run_digests(now_dt=None):
    """Called from the sweeper. Mondays after DIGEST_HOUR_UTC, once per day."""
    n = now_dt or datetime.datetime.utcnow()
    if n.weekday() != 0 or n.hour < config.DIGEST_HOUR_UTC:
        return
    today = n.date().isoformat()
    if store.meta_get("digest_last") == today:
        return
    store.meta_set("digest_last", today)
    send_weekly_digest(include_ideas=(next_release(n.date()) - n.date()).days <= 6)


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
            for lic in store.all_active_or_pastdue():          # tools revealed after purchase
                for level, text in tool_notices(lic, now):
                    notify.client(lic["contact"], text)
                    store.update(lic["license_key"], tools_told=level)
            # Monthly Trader Quiz winner — announce the previous month once, when
            # the month has rolled over. Runs wherever the service runs; no cron.
            if config.QUIZ_AUTO_WINNER:
                prev = _prev_period()
                if store.meta_get("quiz_winner_last") != prev:
                    try:
                        announce_quiz_winner(prev)   # None reward -> rotating pool
                    except Exception as e:  # noqa: BLE001
                        notify.admin("auto quiz-winner error: %s" % e)
                    store.meta_set("quiz_winner_last", prev)   # mark done either way
            run_digests()
        except Exception as e:  # noqa: BLE001
            notify.admin("sweeper error: %s" % e)
        try:
            backup.maybe_daily()      # own try: a sweeper bug must not stop backups
        except Exception as e:  # noqa: BLE001
            notify.admin("backup error: %s" % e)
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
        self.send_header("Cache-Control", "no-store")          # always serve fresh (HQ/pages)
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

        host = (self.headers.get("Host", "") or "").lower()
        if host.startswith("hq.") and u.path in ("/", "/index.html"):
            return self._admin_page()

        if u.path == "/verify":
            self._verify(one("key"), one("account"), one("machine"), one("product"))
        elif u.path == "/reflink":
            self._reflink(one("key"))
        elif u.path == "/quiz":
            self._quiz(one("key"))
        elif u.path == "/ideas":
            self._ideas(one("key"))
        elif u.path == "/notices":
            self._notices(one("key"))
        elif u.path == "/digest":
            self._digest(one("token"))
        elif u.path == "/testers":
            self._testers_status()
        elif u.path == "/admin/testers":
            self._admin_testers()
        elif u.path == "/admin/review_key":
            if not self._admin_ok():
                return self._send(403, {"error": "forbidden"})
            self._send(200, {"license_key": ensure_review_key()[0]})
        elif u.path == "/admin/list":
            self._admin_list()
        elif u.path == "/admin/app_stats":
            self._admin_app_stats()
        elif u.path == "/admin/suggestions":
            self._admin_suggestions()
        elif u.path == "/admin/quiz_stats":
            self._admin_quiz_stats()
        elif u.path == "/admin/health":
            self._admin_health()
        elif u.path == "/admin/partners":
            self._admin_partners()
        elif u.path == "/admin/daily_plan":
            self._admin_daily_plan()
        elif u.path in ("/admin", "/admin/"):
            self._admin_page()
        elif u.path == "/pricing":
            self._pricing()
        elif u.path == "/buy":
            self._buy_page(one("product"))
        elif u.path == "/paypal_return":
            self._paypal_return(one("token"))
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
        elif u.path == "/paypal_ipn":
            self._paypal_ipn()
        elif u.path == "/checkout":
            self._checkout()
        elif u.path == "/trial":
            self._trial()
        elif u.path == "/admin/issue":
            self._admin_issue()
        elif u.path == "/admin/partner_settle":
            self._admin_partner_settle()
        elif u.path == "/admin/revoke":
            self._admin_revoke()
        elif u.path == "/admin/extend":
            self._admin_extend()
        elif u.path == "/admin/reset_device":
            self._admin_reset_device()
        elif u.path == "/admin/announce":
            self._admin_announce()
        elif u.path == "/admin/quiz_winner":
            self._admin_quiz_winner()
        elif u.path == "/suggest":
            self._suggest()
        elif u.path == "/ideas/vote":
            self._ideas_vote()
        elif u.path == "/ready":
            self._ready()
        elif u.path == "/quiz/answer":
            self._quiz_answer()
        elif u.path == "/admin/suggestion":
            self._admin_suggestion_update()
        elif u.path == "/subscribe":
            self._subscribe()
        elif u.path == "/delete_request":
            try:
                data = json.loads(self._body() or b"{}")
            except Exception:  # noqa: BLE001
                data = {}
            if not (str(data.get("key") or "").strip() or str(data.get("contact") or "").strip()):
                return self._send(400, {"error": "key_or_contact_required"})
            self._send(200, delete_request(data.get("key"), data.get("contact")))
        elif u.path == "/testers/join":
            self._testers_join()
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
            return self._send(200, {"valid": True, "reason": "admin", "product": prod, **_age(lic),
                                    "expires_at": lic.get("paid_until"), "server_time": store.now(),
                                    "token": token, "recheck_in": config.TOKEN_TTL_HOURS * 3600})

        if product and not config.unlocks(lic["product"], product):
            # an add-on bought onto this key (e.g. Guardian on an App key)
            addon = store.addon_for(key, product)
            ok, why = check_access(addon) if addon else (False, "")
            if not ok or lic["status"] == "revoked":
                return self._send(200, {"valid": False, "reason": "wrong_product"})
            if (not lic.get("no_bind") and lic.get("bind_account") and account
                    and account != lic["bind_account"]):
                return self._send(200, {"valid": False, "reason": "bound_to_other"})
            store.update(key, last_seen=store.now(), last_account=account or machine or "")
            token = tokens.issue(key, addon["product"], addon["paid_until"])
            return self._send(200, {"valid": True, "reason": why, "product": addon["product"], **_age(lic),
                                    "expires_at": addon["paid_until"], "server_time": store.now(),
                                    "token": token, "recheck_in": config.TOKEN_TTL_HOURS * 3600})

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
        self._send(200, {"valid": True, "reason": reason, "product": lic["product"], **_age(lic),
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

    def _paypal_return(self, paypal_order_id):
        """Buyer came back from PayPal — capture the order and activate."""
        if not paypal_order_id:
            return self._send(400, "<h2>Missing PayPal order.</h2>", "text/html")
        our_id, capture_id, ok, err = paypal.capture_order(paypal_order_id)
        if ok and our_id:
            # Dedupe on the capture id: the webhook for this same payment uses it too.
            pay_id = capture_id or paypal_order_id
            if not store.payment_seen(pay_id):
                apply_payment(our_id, pay_id)
            return self._send(200, "<h2>Thank you — your activation key is on its way.</h2>",
                              "text/html")
        notify.admin("paypal capture not completed for %s: %s" % (paypal_order_id, err or ok))
        self._send(200, "<h2>Payment not completed. If you were charged, contact support.</h2>",
                   "text/html")

    def _paypal_ipn(self):
        raw = self._body()
        if not paypal.verify_webhook(self.headers, raw):
            return self._send(401, {"error": "bad signature"})
        try:
            d = json.loads(raw)
        except Exception:  # noqa: BLE001
            return self._send(400, {"error": "bad json"})
        if (d.get("event_type") or "") == "PAYMENT.CAPTURE.COMPLETED":
            res = d.get("resource") or {}
            order_id = res.get("custom_id") or ""
            payment_id = str(res.get("id") or "")
            if not order_id:
                # fall back to the order's supplementary data if custom_id is absent
                sd = (res.get("supplementary_data") or {}).get("related_ids") or {}
                order_id = sd.get("order_id") or ""
            if payment_id and store.payment_seen(payment_id):
                return self._send(200, {"ok": True, "dup": True})
            if order_id:
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
                                  ref=(data.get("ref") or ""),
                                  attach=(data.get("attach") or ""))
        if err:
            return self._send(400, {"error": err})
        self._send(200, res)

    def _pricing(self):
        """Public: what the storefront needs to render the offer. No secrets —
        just the App price, trial length, and which pay rails are live."""
        p = config.product("APP") or {}
        crypto_on = bool(getattr(config, "NOWPAYMENTS_API_KEY", ""))
        card_on = config.card_enabled()
        paypal_on = config.paypal_enabled()
        price = p.get("price_solo", 25)
        regular = p.get("price_regular", price)
        promo = regular > price          # only a promo while live price is below the "was" price
        self._send(200, {
            "product": "APP",
            "name": p.get("name", "STAALCALIBUR App"),
            "price": price,
            "price_regular": regular,
            "promo": promo,
            "promo_note": config.APP_PROMO_NOTE if promo else "",
            "period_days": p.get("period_days", 30),
            "trial_days": config.APP_TRIAL_DAYS,
            "crypto": crypto_on,
            "card": card_on,
            "paypal": paypal_on,
        })

    def _trial(self):
        """Public: issue a free App trial key. One per contact; length from
        config.APP_TRIAL_DAYS. Abuse-guarded, no payment, no card."""
        days = config.APP_TRIAL_DAYS
        if days <= 0:
            return self._send(403, {"error": "trials_off"})
        raw = self._body()
        try:
            data = json.loads(raw or b"{}")
        except Exception:  # noqa: BLE001
            data = {}
        contact = (data.get("contact") or "").strip()[:120]
        if len(contact) < 3:
            return self._send(400, {"error": "contact_required"})
        if store.trial_used(contact, "APP"):
            return self._send(200, {"error": "trial_used"})
        ref = "".join(ch for ch in (data.get("ref") or "") if ch.isalnum() or ch in "-_")[:40]
        key = new_license_key("APP")
        store.create(key, "APP", contact, order_id=key, status="pending")
        store.update(key, status="active", paid_until=store.now() + days * DAY,
                     revoke_at=None, notified=0, trial=1)
        if ref:
            store.update(key, referred_by=ref)   # remembered if the trial later converts
        row = store.get(key)
        try:
            notify.admin("New APP trial: %s (%d days)" % (contact, days))
        except Exception:  # noqa: BLE001
            pass
        self._send(200, {"license_key": key, "status": "active",
                         "paid_until": row["paid_until"], "trial": True,
                         "trial_days": days})

    def _reflink(self, key):
        """Return the caller's personal referral link + stats. Any known,
        non-revoked key can share (admin keys too)."""
        lic = store.get(key)
        if not lic:
            return self._send(200, {"ok": False, "reason": "unknown key"})
        if lic["status"] == "revoked":
            return self._send(200, {"ok": False, "reason": "inactive"})
        code = ensure_ref_code(lic)
        total, granted = store.count_referrals(code)
        active_until = lic.get("ref_reward_until") or 0
        reward_active = store.now() < active_until
        self._send(200, {"ok": True, "code": code, "link": ref_link(code),
                         "referrals": total, "free_months": granted,
                         "reward_days": config.REFERRAL_REWARD_DAYS,
                         "reward_active": reward_active,
                         "reward_until": active_until if reward_active else 0})

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

    def _admin_partners(self):
        if not self._admin_ok():
            return self._send(403, {"error": "forbidden"})
        now = store.now()
        rows = store.partner_list()
        for r in rows:
            ru = r.get("reward_until") or 0
            r["reward_active"] = now < ru
            r["reward_days_left"] = max(0, round((ru - now) / DAY, 1)) if ru else 0
        self._send(200, {"partners": rows, "reward_days_each": config.PARTNER_REWARD_DAYS,
                         "policy": "no stacking — one reward window per partner at a time"})

    def _admin_partner_settle(self):
        """Pay out a partner's current reward as App access. Body:
        {tag, contact?, days?}. NO STACKING: if the partner's App license is
        already active, its expiry is only pushed out to cover the reward window,
        never extended on top of existing paid time. Sets/updates the partner's
        contact so future payouts can target the same license."""
        if not self._admin_ok():
            return self._send(403, {"error": "forbidden"})
        data = json.loads(self._body() or b"{}")
        tag = (data.get("tag") or "").strip()
        p = store.partner_get(tag)
        if not p:
            return self._send(404, {"error": "unknown partner tag"})
        contact = (data.get("contact") or p.get("contact") or "").strip()
        if not contact:
            return self._send(400, {"error": "no contact on file — pass contact to pay this partner"})
        days = int(data.get("days", config.PARTNER_REWARD_DAYS))
        if days <= 0:
            return self._send(400, {"error": "days must be positive"})
        # find the partner's own App license by contact, or make one
        key = data.get("license_key") or ""
        lic = store.get(key) if key else None
        if not lic:
            for l in store.all_active_or_pastdue():
                if l["product"] == "APP" and (l.get("contact") or "") == contact:
                    lic, key = l, l["license_key"]; break
        if not lic:
            key = new_license_key("APP")
            store.create(key, "APP", contact, order_id=key, status="pending")
            lic = store.get(key)
        now = store.now()
        target = now + days * DAY
        # no stacking: cover the window, don't add on top of existing paid time
        paid_until = max(lic.get("paid_until") or 0, target)
        store.update(key, status="active", paid_until=paid_until, revoke_at=None,
                     notified=0, contact=contact)
        store.partner_set_contact(tag, contact)
        until = time.strftime("%Y-%m-%d", time.gmtime(paid_until))
        notify.admin("PARTNER payout: '%s' -> App key %s for %s active to %s (no-stack)"
                     % (tag, key, contact, until))
        self._send(200, {"ok": True, "tag": tag, "license_key": key,
                         "contact": contact, "active_until": paid_until,
                         "days_granted": days})

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

    def _admin_quiz_winner(self):
        """Decide + announce the Trader Quiz winner for a period. Winner is DM'd
        privately with the reward; everyone else gets a public message that names
        only the winner's anonymous id (privacy by design)."""
        if not self._admin_ok():
            return self._send(403, {"error": "forbidden"})
        d = json.loads(self._body() or b"{}")
        period = d.get("period") or _prev_period()   # default: previous calendar month
        reward = d.get("reward")   # None -> use the rotating pool
        if d.get("dry_run"):
            board = store.quiz_leaderboard(period, 1)
            if not board:
                return self._send(200, {"ok": False, "reason": "no quiz plays in %s" % period})
            anon, pts, _ = board[0]
            return self._send(200, {"ok": True, "dry_run": True, "period": period,
                                    "winner_anon": anon, "points": pts,
                                    "would_reward": reward or peek_reward()})
        self._send(200, announce_quiz_winner(period, reward))

    def _suggest(self):
        """A subscriber submits an app idea or bug. Screened for abusive content
        before it is ever stored. Runs itself, no owner taps needed:
          - bug  -> stored privately, listed in the Monday message
          - idea matching one already built -> sender is told it's already there
          - idea matching one on the board  -> counted as a vote for that one
          - new idea -> straight onto the public board"""
        d = json.loads(self._body() or b"{}")
        key = d.get("key", "")
        text = (d.get("text") or "").strip()
        category = (d.get("category") or "other").lower()
        if category not in CAT_LABELS:
            category = "other"
        lic = store.get(key)
        if not lic or lic["status"] == "revoked":
            return self._send(200, {"ok": False, "reason": "You need an active app key to send a suggestion."})
        ok, reason = moderation.screen(text)
        if not ok:
            # never stored, never shown to admin — the user gets the notice.
            return self._send(200, {"ok": False, "reason": reason})
        if category == "bug":
            store.add_suggestion(lic.get("contact") or key, text, category, key)
            return self._send(200, {"ok": True, "bug": True})
        match = similar_idea(text)
        if match and match["status"] == "built":
            return self._send(200, {"ok": True, "dup": "built", "text": match["text"]})
        if match:
            if key not in store.idea_voters(match["id"]):
                store.toggle_vote(match["id"], key)
            return self._send(200, {"ok": True, "dup": "open", "text": match["text"]})
        sid = store.add_suggestion(lic.get("contact") or key, text, category, key)
        store.set_suggestion_status(sid, "open", "small")
        self._send(200, {"ok": True})

    def _ideas_lic(self, key):
        lic = store.get(key) if key else None
        return lic if lic and lic["status"] != "revoked" else None

    def _ideas(self, key):
        if not self._ideas_lic(key):
            return self._send(200, {"ok": False, "reason": "You need an active app key to see the ideas board."})
        self._send(200, {"ok": True, "ideas": store.public_ideas(key),
                         "next_update": next_release().isoformat(),
                         "next_big_update": next_big_release().isoformat(),
                         "categories": CAT_LABELS})

    def _digest_ok(self, token):
        return bool(config.DIGEST_TOKEN) and hmac.compare_digest(token or "", config.DIGEST_TOKEN)

    def _digest(self, token):
        if not self._digest_ok(token):
            return self._send(403, {"error": "forbidden"})
        self._send(200, digest_data())

    def _ready(self):
        """The Monday build says a PR is ready: post it to the updates channel
        with an Approve button. Only links to a PR in our own repo."""
        try:
            d = json.loads(self._body() or b"{}")
        except ValueError:
            d = {}
        if not self._digest_ok(d.get("token")):
            return self._send(403, {"error": "forbidden"})
        pr = (d.get("pr_url") or "").strip()
        if not re.fullmatch(re.escape(config.UPDATES_REPO_URL) + r"/pull/\d+", pr, re.I):
            return self._send(400, {"error": "pr_url must be a pull request in %s" % config.UPDATES_REPO_URL})
        summary = (d.get("summary") or "").strip()[:1500]
        notify.updates("🔔 Ready for your approval\n\n%s\n\nTap the button, check it, then tap Merge. "
                       "It goes live in the app within 5 minutes." % summary,
                       button=("✅ Review & approve", pr))
        self._send(200, {"ok": True})

    def _notices(self, key):
        if not self._ideas_lic(key):
            return self._send(200, {"ok": False, "notices": []})
        self._send(200, {"ok": True, "notices": store.pop_notices(key)})

    def _ideas_vote(self):
        d = json.loads(self._body() or b"{}")
        key = d.get("key", "")
        if not self._ideas_lic(key):
            return self._send(200, {"ok": False, "reason": "You need an active app key to vote."})
        try:
            ok, voted, n = store.toggle_vote(int(d.get("id")), key)
        except (TypeError, ValueError):
            ok, voted, n = False, False, 0
        if not ok:
            return self._send(200, {"ok": False, "reason": "That idea isn't open for votes."})
        self._send(200, {"ok": True, "voted": voted, "votes": n})

    def _player_ok(self, lic):
        if not lic or lic["status"] == "revoked":
            return False
        if lic.get("admin"):
            return True
        allowed, _ = check_access(lic)
        return allowed

    def _quiz_state(self, lic, extra=None):
        key = lic["license_key"]
        period, today = _period(), _today()
        anon = store.ensure_anon(key)
        pts = store.quiz_month_points(key, period)
        rank, total = store.quiz_rank(key, period)
        board = [{"anon": a, "points": p} for (a, p, k) in store.quiz_leaderboard(period, 10)]
        out = {"ok": True, "anon_id": anon, "month_points": pts, "rank": rank,
               "players": total, "days_left": _days_left(), "leaderboard": board}
        if extra:
            out.update(extra)
        return out

    def _quiz_day_qids(self, key, today):
        """The exact 5 questions served to this player today. Picks fresh
        never-seen ones on first request and persists them (so GET and the
        later POST agree, and questions are never repeated). Returns [] when the
        player has exhausted the whole bank."""
        play = store.quiz_get_play(key, today)
        if play and play.get("qids"):
            return play["qids"], play.get("score")
        qids = quiz.pick_unseen(key, today, store.quiz_seen_ids(key))
        if not qids:
            return [], None
        store.quiz_start_play(key, today, qids)
        return qids, None

    def _quiz(self, key):
        lic = store.get(key)
        if not self._player_ok(lic):
            return self._send(200, {"ok": False, "reason": "Active subscription required to play."})
        today = _today()
        play = store.quiz_get_play(key, today)
        if play and play.get("score") is not None:
            return self._send(200, self._quiz_state(lic, {"played": True, "score_today": play["score"]}))
        qids, _ = self._quiz_day_qids(key, today)
        if not qids:
            return self._send(200, self._quiz_state(lic, {"played": False, "exhausted": True, "questions": []}))
        return self._send(200, self._quiz_state(lic, {"played": False,
                                                      "questions": quiz.client_questions(qids)}))

    def _quiz_answer(self):
        d = json.loads(self._body() or b"{}")
        key = d.get("key", "")
        answers = d.get("answers") or {}
        lic = store.get(key)
        if not self._player_ok(lic):
            return self._send(200, {"ok": False, "reason": "Active subscription required to play."})
        today = _today()
        play = store.quiz_get_play(key, today)
        if play and play.get("score") is not None:
            return self._send(200, {"ok": False, "reason": "already_played",
                                    "state": self._quiz_state(lic, {"played": True, "score_today": play["score"]})})
        qids, _ = self._quiz_day_qids(key, today)
        if not qids:
            return self._send(200, {"ok": False, "reason": "exhausted"})
        score, results = quiz.score_answers(qids, answers)
        store.quiz_set_score(key, today, score)
        pairs = [(r["id"], r["chosen"]) for r in results if r["chosen"] is not None and r["chosen"] >= 0]
        if pairs:
            store.quiz_bump_votes(pairs)
        for r in results:
            r["poll"] = store.quiz_poll(r["id"], len(r["options"]))
        return self._send(200, self._quiz_state(lic, {"played": True, "score_today": score,
                                                      "total": len(qids), "results": results}))

    def _admin_app_stats(self):
        if not self._admin_ok():
            return self._send(403, {"error": "forbidden"})
        self._send(200, store.app_stats())

    def _admin_suggestions(self):
        if not self._admin_ok():
            return self._send(403, {"error": "forbidden"})
        self._send(200, {"suggestions": store.list_suggestions()})

    def _admin_quiz_stats(self):
        if not self._admin_ok():
            return self._send(403, {"error": "forbidden"})
        s = store.quiz_stats(_period(), _today())
        s["next_reward"] = peek_reward()
        self._send(200, s)

    def _admin_health(self):
        if not self._admin_ok():
            return self._send(403, {"error": "forbidden"})
        services = []
        for u in config.HQ_UNITS:
            try:
                r = subprocess.run(["systemctl", "is-active", u],
                                   capture_output=True, text=True, timeout=2)
                st = (r.stdout or "").strip().splitlines()[0].strip() if r.stdout else ""
            except Exception:  # noqa: BLE001
                st = ""
            if st not in ("active", "inactive", "failed", "activating", "deactivating", "reloading"):
                st = "unknown"
            services.append({"unit": u, "status": st})
        host = {}
        try:
            t, u2, f = shutil.disk_usage("/")
            host["disk_used_pct"] = round(u2 / t * 100, 1)
            host["disk_free_gb"] = round(f / 1e9, 1)
        except Exception:  # noqa: BLE001
            pass
        try:
            with open("/proc/uptime") as fp:
                host["uptime_days"] = round(float(fp.read().split()[0]) / 86400, 1)
            with open("/proc/loadavg") as fp:
                host["load"] = fp.read().split()[0]
        except Exception:  # noqa: BLE001
            pass
        self._send(200, {"services": services, "host": host, "server_time": store.now()})

    def _admin_suggestion_update(self):
        if not self._admin_ok():
            return self._send(403, {"error": "forbidden"})
        d = json.loads(self._body() or b"{}")
        apply_idea_status(d.get("id"), d.get("status", "done"), d.get("size"))
        self._send(200, {"ok": True})

    def _admin_daily_plan(self):
        """On-demand daily trade plan: live gold + top estate signals + one
        Gemini reasoning pass. The estate itself stays AI-free; this is the only
        place an AI is called, and only when the HQ button is pressed."""
        if not self._admin_ok():
            return self._send(403, {"error": "forbidden"})
        try:
            from compiler.dayplan import build_day_plan
            self._send(200, build_day_plan())
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": "plan_failed", "detail": str(e)})

    def _admin_page(self):
        self._send(200, ADMIN_HTML, "text/html; charset=utf-8")

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

    # ---- Play closed-test testers ----
    _GMAIL = re.compile(r"^[a-z0-9.+_-]+@(gmail|googlemail)\.com$")

    def _testers_status(self):
        """Public: progress toward Google's tester minimum + the opt-in link."""
        self._send(200, {"count": len(store.list_testers()), "goal": config.TESTER_GOAL,
                         "optin_url": config.PLAY_OPTIN_URL, "reward": config.TESTER_REWARD})

    def _testers_join(self):
        """Public: a tester leaves the Gmail they use on their Android phone
        (Play only lets listed Google accounts into a closed test)."""
        try:
            data = json.loads(self._body() or b"{}")
        except Exception:  # noqa: BLE001
            data = {}
        email = str(data.get("email", "")).strip().lower()[:120]
        if not self._GMAIL.match(email):
            return self._send(400, {"error": "gmail_required"})
        tg = re.sub(r"[^A-Za-z0-9_@]", "", str(data.get("telegram", "")))[:40]
        new = store.add_tester(email, tg)
        n = len(store.list_testers())
        if new:
            notify.admin("New app tester %d/%d: %s%s. Add them in Play Console > Testing > "
                         "Closed testing > Testers (or GET /admin/testers for the full list)."
                         % (n, config.TESTER_GOAL, email, (" (%s)" % tg) if tg else ""))
        self._send(200, {"ok": True, "new": new, "count": n, "goal": config.TESTER_GOAL,
                         "optin_url": config.PLAY_OPTIN_URL})

    def _admin_testers(self):
        """Admin: every tester, plus one comma-separated line to paste into the
        Play Console email list."""
        if not self._admin_ok():
            return self._send(403, {"error": "forbidden"})
        rows = store.list_testers()
        self._send(200, {"count": len(rows), "goal": config.TESTER_GOAL,
                         "paste_into_play_console": ", ".join(r["email"] for r in rows),
                         "testers": rows})

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
<details style="margin:2px 0 8px"><summary style="cursor:pointer;color:#26558c;font-size:13px">How do I get my Telegram chat id?</summary>
<div style="font-size:13px;color:#556;line-height:1.5;margin-top:6px">
1. In Telegram, open <b>@userinfobot</b> and tap <b>Start</b> — it replies with your numeric id (that's your chat id).<br>
2. Then open our notices bot <b>%(bot)s</b> and tap <b>Start</b> so we're allowed to message you.<br>
3. Paste the numeric id above. (An email also works, but Telegram gets your key instantly.)
</div></details>
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
                            if config.card_enabled() else ""),
               "bot": config.LICENSE_BOT_USERNAME or "our Telegram bot"}
        self._send(200, html, "text/html")


ADMIN_HTML = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<meta name=theme-color content="#0a0e15">
<title>STAALWAG HQ</title>
<style>
:root{--bg:#0a0e15;--card:#131a26;--card2:#18212f;--line:#1e2a3a;--fg:#e7edf3;--mut:#7d8a9c;
 --steel:#8aa0b4;--accent:#6ea8fe;--buy:#2ecc71;--sell:#ff5b5b;--watch:#f2c14e}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:20px 16px 70px}
h1{font-size:22px;font-weight:900;letter-spacing:1px;margin:0}
h1 .a{color:var(--steel)}
.sub{color:var(--mut);font-size:13px;margin:2px 0 16px}
.gate{max-width:340px;margin:60px auto;text-align:center}
input{width:100%;padding:13px;border:1px solid var(--line);border-radius:10px;background:var(--card);
 color:var(--fg);font-size:15px;text-align:center}
button{cursor:pointer;font-family:inherit}
.btn{background:var(--accent);color:#04122b;border:0;border-radius:10px;padding:12px 16px;font-weight:800;font-size:14px}
.muted{color:var(--mut);font-size:13px}
.top{display:flex;align-items:center;gap:12px;margin-bottom:12px}
.top .sp{flex:1}
.top img{width:34px;height:34px;border-radius:9px}
.rbtn{background:var(--card);border:1px solid var(--line);color:var(--chrome,#c7d2dd);border-radius:9px;padding:8px 12px;font-weight:700;font-size:13px}
.tabs{display:flex;gap:6px;overflow-x:auto;border-bottom:1px solid var(--line);margin-bottom:18px}
.tab{background:none;border:0;color:var(--mut);padding:11px 14px;font-weight:800;font-size:13px;border-bottom:2px solid transparent;white-space:nowrap}
.tab.on{color:var(--fg);border-bottom-color:var(--accent)}
.pane{display:none}.pane.on{display:block}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:6px 0 20px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px}
.tile b{display:block;font-size:28px;font-weight:900}
.tile span{color:var(--mut);font-size:11.5px;letter-spacing:.4px}
.tile.hot b{color:var(--accent)}
.sec{font-size:12px;letter-spacing:2px;text-transform:uppercase;color:var(--steel);margin:18px 0 10px}
.svc{display:flex;align-items:center;gap:12px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:8px 0}
.dot{width:11px;height:11px;border-radius:50%;background:var(--mut);flex:none}
.dot.ok{background:var(--buy)}.dot.bad{background:var(--sell)}
.svc .u{flex:1;font-weight:700;font-family:ui-monospace,Menlo,monospace;font-size:13px}
.svc .st{font-size:12px;font-weight:800;text-transform:uppercase}
.links{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
a.card{display:block;text-decoration:none;color:inherit;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;transition:.12s}
a.card:hover{border-color:var(--accent);background:var(--card2)}
a.card .ic{font-size:22px}
a.card .nm{font-weight:800;margin:8px 0 3px}
a.card .ds{color:var(--mut);font-size:12.5px;line-height:1.45}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line)}
th{color:var(--steel);font-size:11px;text-transform:uppercase;letter-spacing:.5px}
td .k{font-family:ui-monospace,Menlo,monospace}
.act{background:var(--card2);border:1px solid var(--line);color:var(--chrome,#c7d2dd);border-radius:7px;padding:4px 8px;font-size:11px;font-weight:700;margin-right:4px}
.qb{display:flex;gap:10px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 12px;margin:6px 0;font-size:13px}
.qb .rk{color:var(--mut);font-weight:800;width:34px}.qb .aid{flex:1;font-weight:700;font-family:ui-monospace,Menlo,monospace}.qb .pts{color:var(--steel);font-weight:800}
.sg{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:13px;margin:8px 0}
.sg .m{color:var(--mut);font-size:11px;margin-bottom:5px}.sg .t{font-size:14px;line-height:1.5}
.sg .done{background:transparent;border:1px solid var(--line);color:var(--steel);border-radius:8px;padding:6px 12px;font-size:12px;font-weight:700;margin-top:8px}
.map h3{font-size:14px;margin:16px 0 6px}
.map p,.map li{font-size:13px;color:var(--chrome,#c7d2dd);line-height:1.55}
.map code{background:var(--card);border:1px solid var(--line);border-radius:5px;padding:1px 6px;font-size:12px;font-family:ui-monospace,Menlo,monospace}
.map .box{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:6px 16px;margin:8px 0}
</style></head><body>
<script>
window.showDiag=function(m){try{var b=document.getElementById('diag');if(!b){b=document.createElement('div');b.id='diag';b.style.cssText='position:fixed;top:0;left:0;right:0;background:#7a1f1f;color:#fff;font:13px monospace;padding:10px;z-index:99999;white-space:pre-wrap';document.body.appendChild(b);}b.textContent=m;}catch(_){}}
window.addEventListener('error',function(e){window.showDiag('JS ERROR: '+(e.message||e.type||'')+' @ '+(e.filename||'')+':'+(e.lineno||''));});
window.addEventListener('unhandledrejection',function(e){window.showDiag('PROMISE: '+((e.reason&&e.reason.message)||e.reason||''));});
</script>
<div class="wrap">
<div id=gate class=gate>
 <h1>STAALWAG <span class=a>HQ</span></h1><div class=sub>Central command center</div>
 <input id=tok type=text placeholder="Admin token" autocomplete=off autocapitalize=off autocorrect=off spellcheck=false>
 <button class=btn style=width:100% onclick=unlock()>Unlock</button>
 <div id=gerr class=muted style="margin-top:10px;min-height:16px"></div>
</div>
<div id=hq style=display:none>
 <div class=top>
  <img src="/icon-192.png" alt="" onerror="this.style.display='none'">
  <div><h1>STAALWAG <span class=a>HQ</span></h1><div class=sub id=hsub>Central command center</div></div>
  <div class=sp></div>
  <button class=rbtn onclick=loadAll()>&#8635; Refresh</button>
 </div>
 <div class=tabs>
  <button class="tab on" data-p=overview onclick=tab('overview')>Overview</button>
  <button class=tab data-p=plan onclick=tab('plan')>Daily Plan</button>
  <button class=tab data-p=desks onclick=tab('desks')>Desks &amp; links</button>
  <button class=tab data-p=app onclick=tab('app')>App</button>
  <button class=tab data-p=lic onclick=tab('lic')>Licenses</button>
  <button class=tab data-p=map onclick=tab('map')>Map</button>
 </div>

 <div id=p-overview class="pane on">
  <div class=sec>Service health</div><div id=svc></div>
  <div class=sec>Server</div><div class=tiles id=htiles></div>
  <div class=sec>At a glance</div><div class=tiles id=gtiles></div>
 </div>

 <div id=p-plan class=pane>
  <div class=sec>Today's trade plan</div>
  <button class=btn id=planbtn onclick=getPlan()>Get today's plan</button>
  <div id=planout class=muted style="margin-top:12px">Press the button to pull live gold + the estate's top signals and generate today's plan. One free Gemini call, on demand.</div>
 </div>

 <div id=p-desks class=pane>
  <div class=sec>Open any desk (new tab)</div><div class=links id=links></div>
 </div>

 <div id=p-app class=pane>
  <div class=sec>Mobile app</div><div class=tiles id=atiles></div>
  <div class=sec>Trader Quiz &#183; this month <span id=qperiod class=muted></span></div>
  <div class=tiles id=qtiles></div><div id=qreward class=muted style="margin:2px 0 12px"></div><div id=qboard></div>
  <div class=sec>Suggestions</div><div id=sugs></div>
 </div>

 <div id=p-lic class=pane>
  <div class=sec>All licenses</div>
  <div style=overflow-x:auto><table id=lictbl><thead><tr><th>Key<th>Product<th>Status<th>Days<th>Flags<th>Actions</tr></thead><tbody></tbody></table></div>
 </div>

 <div id=p-map class="pane map">
  <div class=sec>Where everything lives</div>
  <div class=box>
   <h3>Live services (systemd on the VPS)</h3>
   <ul>
    <li><code>caddy</code> &#8212; the web front door (HTTPS, routes every subdomain)</li>
    <li><code>wolf-desk</code> &#8212; the WOLF intel desk + the mobile app + the marketing site (port 8777)</li>
    <li><code>staalwag-licensing</code> &#8212; licensing, payments, referrals, quiz, THIS HQ (port 8790)</li>
    <li><code>staalwag-desktop</code> &#8212; the cloud desktop (noVNC)</li>
   </ul>
   <h3>Fix a service (in PowerShell)</h3>
   <div class=box><code>ssh root@178.104.88.38 "systemctl restart wolf-desk"</code></div>
   <p>Swap in <code>caddy</code>, <code>staalwag-licensing</code> or <code>staalwag-desktop</code>. See why one failed:</p>
   <div class=box><code>ssh root@178.104.88.38 "journalctl -u wolf-desk -n 40 --no-pager"</code></div>
   <h3>Deploy code changes</h3>
   <div class=box><code>ssh root@178.104.88.38 "cd /opt/wolf-desk &amp;&amp; sudo -u wolf git pull &amp;&amp; sudo systemctl restart wolf-desk staalwag-licensing"</code></div>
   <p>Rebuild the market data (after ticker/universe changes): add <code>sudo -u wolf python3 run.py</code> before the restart.</p>
   <h3>Where files live on the VPS</h3>
   <ul>
    <li>Code: <code>/opt/wolf-desk</code> (this repo)</li>
    <li>App + site + desk pages: <code>/opt/wolf-desk/dashboard</code></li>
    <li>Licensing/quiz/referrals code: <code>/opt/wolf-desk/licensing</code></li>
    <li>Market data JSON: <code>/opt/wolf-desk/data</code></li>
    <li>Licence database: <code>/var/lib/staalwag-licensing/licenses.db</code></li>
    <li>Secrets/config: <code>/etc/staalwag-licensing.env</code></li>
    <li>Caddy config: <code>/etc/caddy/Caddyfile</code></li>
   </ul>
   <h3>Common admin commands</h3>
   <div class=box><code>python3 -m licensing.adminctl list</code> &#8212; every key<br>
    <code>python3 -m licensing.adminctl admin-key</code> &#8212; your master key<br>
    <code>python3 -m licensing.adminctl announce</code> &#8212; tell renters about an update<br>
    <code>python3 -m licensing.adminctl quiz-winner --dry-run</code> &#8212; preview the quiz winner</div>
   <p class=muted>Run these after <code>ssh root@178.104.88.38</code> then <code>cd /opt/wolf-desk</code>.</p>
  </div>
 </div>
</div>
<script>
function T(){try{return localStorage.getItem("hq_tok")||""}catch(e){return""}}
function H(){return {"X-Admin-Token":T()}}
function esc(x){return (x==null?"":String(x)).replace(/[&<>]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;"}[c]})}
function unlock(){var t=document.getElementById("tok").value.trim();if(!t)return;try{localStorage.setItem("hq_tok",t)}catch(e){}loadAll();}
function tab(p){var ts=document.querySelectorAll(".tab");for(var i=0;i<ts.length;i++)ts[i].className="tab"+(ts[i].getAttribute("data-p")===p?" on":"");
 var ps=document.querySelectorAll(".pane");for(var j=0;j<ps.length;j++)ps[j].className="pane"+(ps[j].id==="p-"+p?" on":"");}
function tile(v,l,hot){return '<div class="tile'+(hot?' hot':'')+'"><b>'+v+'</b><span>'+l+'</span></div>';}
function getPlan(){
 var b=document.getElementById("planbtn"),o=document.getElementById("planout");
 if(!T()){o.innerHTML='<span style="color:#f66">Unlock HQ first (admin token).</span>';return;}
 b.disabled=true;var old=b.textContent;b.textContent="Working… pulling data + reasoning";
 o.textContent="Fetching live gold, ranking signals, and reasoning… (a few seconds)";
 fetch("/admin/daily_plan",{headers:H()}).then(function(r){return r.json()}).then(function(d){
  b.disabled=false;b.textContent=old;
  if(d.error){o.innerHTML='<span style="color:#f66">Error: '+esc(d.detail||d.error)+'</span>';return;}
  var s=d.setup||{};
  var h='<div style="font-weight:800;font-size:15px;margin:6px 0">'+esc(d.date)+' &#183; Gold plan</div>';
  h+='<table style="margin:8px 0">'
   +'<tr><th>Bias<td><b>'+esc(s.bias)+'</b> on XAUUSD'
   +'<tr><th>Entry zone<td>'+esc(s.entry_low)+' &#8211; '+esc(s.entry_high)
   +'<tr><th>Stop<td>'+esc(s.stop)
   +'<tr><th>Target 1<td>'+esc(s.t1)
   +'<tr><th>Target 2<td>'+esc(s.t2)
   +'<tr><th>R:R<td>1 : '+esc(s.rr)+' (risk '+esc(s.risk_pct)+'%)'
   +'<tr><th>Live / regime<td>'+esc(s.last)+' &#183; '+esc(s.regime)+' (ATR '+esc(s.atr)+')</table>';
  h+='<div class=sec>Reasoning &amp; findings</div><div style="white-space:pre-wrap;line-height:1.55">'+esc(d.reasoning)+'</div>';
  if(d.top_signals&&d.top_signals.length){
   h+='<div class=sec>Top estate signals</div><div style=overflow-x:auto><table><thead><tr><th>Market<th>Class<th>Score<th>Trend</tr></thead><tbody>';
   for(var i=0;i<d.top_signals.length;i++){var t=d.top_signals[i];
    h+='<tr><td>'+esc(t.name)+'<td>'+esc(t["class"])+'<td>'+esc(t.score)+'<td>'+esc(t.trend);}
   h+='</tbody></table></div>';}
  h+='<div class=muted style="margin-top:10px">Live gold quote + estate findings, reasoned once by Gemini (free). Generated '+esc(d.generated_utc)+(d.data_asof?' &#183; findings as of '+esc(d.data_asof):'')+'.</div>';
  o.innerHTML=h;
 }).catch(function(e){b.disabled=false;b.textContent=old;o.innerHTML='<span style="color:#f66">Request failed — check you are unlocked and the service is up.</span>';});
}
function base(){var h=location.hostname;var p=h.split(".");return p.length>2?p.slice(1).join("."):h;}
function sub(s){return location.protocol+"//"+s+"."+base();}
function loadAll(){
 var g=document.getElementById("gerr");if(g)g.textContent="Checking…";
 var code=0;
 fetch("/admin/app_stats",{headers:H()}).then(function(r){code=r.status;if(r.status==403)throw 0;if(!r.ok)throw 1;return r.json()}).then(function(s){
  if(g)g.textContent="";
  document.getElementById("gate").style.display="none";document.getElementById("hq").style.display="";
  document.getElementById("gtiles").innerHTML=tile(s.installed,"App keys")+tile(s.subscribed,"Active subs",1)+tile(s.active_7d,"Using (7d)")+tile(s.suggestions_new,"New suggestions");
  loadHealth();loadApp();loadLic();renderLinks();
 }).catch(function(e){var m=(e===0?"Wrong token (403).":"Couldn't reach HQ (status "+code+").");if(g)g.textContent=m;if(window.showDiag)window.showDiag("Login failed: "+m+" token len="+(T()||"").length);});
}
function loadHealth(){
 var box=document.getElementById("svc");if(box)box.innerHTML='<div class=muted>Checking services…</div>';
 fetch("/admin/health",{headers:H()}).then(function(r){return r.json()}).then(function(d){renderHealth(d)})
  .catch(function(){if(box)box.innerHTML='<div class=muted>Health check unavailable.</div>';});
}
function renderHealth(d){
 var s=d.services||[];
 document.getElementById("svc").innerHTML=s.map(function(x){
  var ok=x.status==="active";return '<div class=svc><span class="dot '+(ok?"ok":"bad")+'"></span><span class=u>'+esc(x.unit)+'</span><span class=st style="color:'+(ok?"var(--buy)":"var(--sell)")+'">'+esc(x.status)+'</span></div>';
 }).join("");
 var h=d.host||{};
 document.getElementById("htiles").innerHTML=
  tile((h.disk_used_pct!=null?h.disk_used_pct+"%":"?"),"Disk used")+
  tile((h.disk_free_gb!=null?h.disk_free_gb+" GB":"?"),"Disk free")+
  tile((h.uptime_days!=null?h.uptime_days+"d":"?"),"Uptime")+
  tile((h.load!=null?h.load:"?"),"Load (1m)");
}
function loadApp(){
 fetch("/admin/app_stats",{headers:H()}).then(function(r){return r.json()}).then(function(s){
  document.getElementById("atiles").innerHTML=
   tile(s.installed,"Installed")+tile(s.subscribed,"Active",1)+tile(s.active_7d,"Using 7d")+
   tile(s.active_24h,"Using 24h")+tile(s.promoters,"Promoting")+tile(s.referrals,"Referrals")+
   tile(s.free_months_granted,"Free months")+tile(s.suggestions_new,"New ideas");
 });
 fetch("/admin/quiz_stats",{headers:H()}).then(function(r){return r.json()}).then(function(s){
  document.getElementById("qperiod").textContent="("+(s.period||"")+")";
  var lead=s.leader?(s.leader.anon+" &#183; "+s.leader.points+" pts"):"&#8212;";
  document.getElementById("qtiles").innerHTML=tile(s.players,"Players")+tile(s.plays_today,"Plays today")+
   tile(s.plays_month,"Plays month")+tile(s.avg_score,"Avg /5")+'<div class="tile hot"><b style=font-size:15px>'+lead+'</b><span>Leader</span></div>';
  document.getElementById("qreward").innerHTML="&#127873; Next reward: <b style=color:var(--fg)>"+esc(s.next_reward||"")+"</b> (rotates monthly)";
  var b=s.leaderboard||[];document.getElementById("qboard").innerHTML=b.length?b.map(function(r,i){
   return '<div class=qb><span class=rk>#'+(i+1)+'</span><span class=aid>'+esc(r.anon)+'</span><span class=pts>'+r.points+' pts</span></div>';}).join(""):'<div class=muted>No plays yet.</div>';
 });
 fetch("/admin/suggestions",{headers:H()}).then(function(r){return r.json()}).then(function(d){
  var a=d.suggestions||[];document.getElementById("sugs").innerHTML=a.length?a.map(function(s){
   var dt=new Date((s.created||0)*1000).toLocaleString(),bug=s.category==="bug",b=[];
   function btn(lbl,st,sz){b.push('<button class=done data-i='+s.id+' data-s='+st+' data-z='+(sz||"")+' onclick=markB(this)>'+lbl+'</button>');}
   if(bug){ if(s.status==="new") btn("Mark fixed","done"); }
   else if(s.status==="new"){ btn("Approve","open","small"); btn("Approve as big","open","big"); btn("Reject","rejected"); btn("Already done","duplicate"); }
   else if(s.status==="open"){ btn("Mark built","built"); btn(s.size==="big"?"Make small":"Make big","open",s.size==="big"?"small":"big"); btn("Hide","rejected"); }
   return '<div class=sg><div class=m>'+dt+' &#183; '+esc(s.category||"other")+(bug?'':' &#183; '+esc(s.size||"small")+' &#183; &#128077; '+(s.votes||0))+
    ' &#183; '+esc(s.status)+' &#183; '+esc(s.contact)+'</div><div class=t>'+esc(s.text)+'</div>'+b.join(" ")+'</div>';}).join(""):'<div class=muted>No suggestions yet.</div>';
 });
}
function markB(e){mark(e.dataset.i,e.dataset.s,e.dataset.z);}
function mark(id,st,sz){fetch("/admin/suggestion",{method:"POST",headers:Object.assign({"Content-Type":"application/json"},H()),body:JSON.stringify({id:id,status:st||"done",size:sz||null})}).then(loadApp);}
function loadLic(){
 fetch("/admin/list",{headers:H()}).then(function(r){return r.json()}).then(function(d){
  var rows=(d.licenses||[]).map(function(l){
   var flags=[];if(l.admin)flags.push("ADMIN");if(l.no_bind)flags.push("no-bind");if(l.bound)flags.push("bound");
   var dl=l.days_left==null?"":l.days_left;var k=esc(l.key);
   var act='<button class=act data-k="'+k+'" data-a="extend">+30d</button>'+
     '<button class=act data-k="'+k+'" data-a="revoke">Revoke</button>'+
     '<button class=act data-k="'+k+'" data-a="reset">Unbind</button>';
   return '<tr><td class=k>'+k+'<td>'+esc(l.product)+'<td>'+esc(l.status)+'<td>'+dl+'<td>'+flags.join(" ")+'<td>'+act+'</tr>';
  }).join("");
  var tb=document.querySelector("#lictbl tbody");
  tb.innerHTML=rows||'<tr><td colspan=6 class=muted>No licenses yet.</td></tr>';
  tb.onclick=function(e){var b=e.target.closest?e.target.closest("button[data-a]"):null;if(b)lact(b.getAttribute("data-k"),b.getAttribute("data-a"));};
 });
}
function lact(key,what){
 if(what==="revoke"&&!confirm("Revoke "+key+"?"))return;
 var url=what==="extend"?"/admin/extend":what==="revoke"?"/admin/revoke":"/admin/reset_device";
 var body=what==="extend"?{key:key,days:30}:{key:key};
 fetch(url,{method:"POST",headers:Object.assign({"Content-Type":"application/json"},H()),body:JSON.stringify(body)}).then(loadLic);
}
function renderLinks(){
 var L=[
  {ic:"&#127760;",nm:"HQ Hub",u:location.protocol+"//"+base()+"/",ds:"The public command-centre landing."},
  {ic:"&#128058;",nm:"WOLF Intel Desk",u:sub("wolf")+"/?admin=1",ds:"Intraday intel desk (admin view)."},
  {ic:"&#128241;",nm:"STAALCALIBUR App",u:sub("app")+"/",ds:"The mobile app (unlock with a key)."},
  {ic:"&#11015;",nm:"App Download",u:sub("app")+"/download",ds:"Install page + APK."},
  {ic:"&#127760;",nm:"Marketing Site",u:"https://staalwag.com",ds:"Public shop front."},
  {ic:"&#128421;",nm:"Cloud Desktop",u:sub("desk")+"/",ds:"Your remote desktop (incognito)."},
  {ic:"&#128206;",nm:"Paperclip",u:sub("paperclip")+"/",ds:"Nico's Trading Desk cockpit (admin)."},
  {ic:"&#9876;",nm:"EA Forge",u:sub("forge")+"/",ds:"Build & prove EAs."},
  {ic:"&#128176;",nm:"Buy / Rent",u:sub("pay")+"/buy?product=APP",ds:"The hosted buy page."}
 ];
 document.getElementById("links").innerHTML=L.map(function(x){
  return '<a class=card target=_blank rel=noopener href="'+x.u+'"><div class=ic>'+x.ic+'</div><div class=nm>'+x.nm+'</div><div class=ds>'+x.ds+'</div></a>';
 }).join("");
}
// one-click login: open hq...?tok=YOURTOKEN once; it's saved and stripped from the URL.
(function(){try{var p=new URLSearchParams(location.search).get("tok");
 if(p){localStorage.setItem("hq_tok",p);history.replaceState({},"",location.pathname);}}catch(e){}})();
if(T()) loadAll();
</script></div></body></html>"""


def main():
    try:
        ensure_review_key()
    except Exception as e:  # noqa: BLE001
        print("[licensing] review key: %s" % e, flush=True)
    threading.Thread(target=sweeper, daemon=True).start()
    srv = ThreadingHTTPServer((config.BIND_ADDR, config.PORT), H)
    print("[licensing] serving on %s:%d (grace %dh)" %
          (config.BIND_ADDR, config.PORT, config.GRACE_HOURS), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
