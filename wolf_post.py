"""WOLF — daily Telegram auto-post (tailored per channel).

BRAND MAP (canonical — keep public copy consistent):
  STAALWAG                = the firm / overall brand
  STAALWAG HQ             = admin-only command centre (NEVER in public copy)
  WOLF Intraday Intel Desk = the PUBLIC product (free reads; VIP = rentals,
                            full signals, market news). This poster speaks AS it.
  Telegram signals        = STAALWAG Gold · VELDRIN Forex · Markov 18-pair

  STAALWAG channel  <-  Gold + Indices    VELDRIN channel  <-  Forex

Builds fresh data, composes a WOLF-branded post per desk, posts to each channel.

Env:
  TELEGRAM_BOT_TOKEN   bot token (@BotFather); bot must be ADMIN of each channel
  STAALWAG_CHANNEL     @handle or -100id   (gold/commodities)
  VELDRIN_CHANNEL      @handle or -100id   (FX)
  STAALWAG_VIP         join/CTA link (optional)
  VELDRIN_VIP          join/CTA link (optional)

Noise control (only post a pair when its signal actually changed):
  SIGNAL_CHANGED_ONLY  "1" (default) posts a pair only when the market gives a
                       different opportunity; "0" = old always-post behaviour.
  SIGNAL_SCORE_BAND    points; a score move smaller than this isn't "a change"
                       (default 5).
  SIGNAL_STATE_FILE    where the last-posted signals are remembered (default:
                       next to GROWTH_DB / the Railway volume, so it survives
                       restarts).

No token = DRY RUN: prints both posts instead of sending.
Run:  python wolf_post.py
"""
import os, sys, json, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import run

try:
    import truststore; truststore.inject_into_ssl()
except Exception:
    pass
import requests

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# Public brand roles: STAALWAG is the PUBLISHER (it posts everything);
# WOLF is the VENUE — the free-subscriber community + VIP benefits inside.
# Only "HQ" (STAALWAG HQ, the admin cockpit) must never appear publicly.
FIRM    = "<b>STAALWAG</b>"                         # the poster / the firm
BY      = "🐺 <i>WOLF — Intraday Intel Desk · free reads &amp; VIP</i>"  # the venue
TAGLINE = "<i>Read the market like a wolf.</i>"

# Base URL of the WOLF server (for tracked CTA links -> /l?c=<key> counts clicks)
WOLF_URL = os.environ.get("WOLF_URL", "https://wolf-desk-production.up.railway.app").rstrip("/")
# STAALWAG is the publisher, so its steel emblem heads every post (the logo brand).
STAALWAG_IMG = os.environ.get("STAALWAG_IMG", WOLF_URL + "/staalwag.png")

# desk -> (env channel, env vip, sub-desk header, [sections], track key)
# section = (label, asset-class key, name filter tuple or None, top N)
#   STAALWAG channel  ->  Gold + Indices    VELDRIN channel  ->  Forex
DESKS = [
    ("STAALWAG_CHANNEL", "STAALWAG_VIP", "🥇 <b>Gold &amp; Indices desk</b>",
     [("🥇 <b>GOLD</b>",    "commodities", ("Gold",), 1),
      ("📈 <b>INDICES</b>", "indices",     None,      3)], "gold"),
    ("VELDRIN_CHANNEL",  "VELDRIN_VIP",  "💱 <b>VELDRIN · FX Desk</b>",
     [("💱 <b>FOREX</b>",   "fx",          None,      4)], "fx"),
]

# Weekend desk. FX, gold/XAUUSD, metals and indices are all shut on Sat/Sun;
# crypto is the only market that trades 24/7. So on weekends we skip the closed
# desks and post ONLY crypto — no XAUUSD/FX/indices signals go out.
#
# TODO(channel): a DEDICATED crypto channel is planned. Until it exists, crypto
# rides the VELDRIN channel (which would otherwise sit silent with FX dark).
# When the new channel is ready this needs NO code change — just set the env
# vars CRYPTO_CHANNEL / CRYPTO_VIP (and optionally CRYPTO_HEADER) and posts
# route there automatically (see weekend_desks() below).
def weekend_desks():
    """Resolve the weekend (crypto) desk. Prefers a dedicated CRYPTO_CHANNEL /
    CRYPTO_VIP if configured, else falls back to the VELDRIN channel/VIP.
    Same tuple shape as DESKS: (channel env, vip env, header, [sections], key)."""
    ch_env  = "CRYPTO_CHANNEL" if os.environ.get("CRYPTO_CHANNEL") else "VELDRIN_CHANNEL"
    vip_env = "CRYPTO_VIP"     if os.environ.get("CRYPTO_VIP")     else "VELDRIN_VIP"
    dedicated = ch_env == "CRYPTO_CHANNEL"
    header = os.environ.get(
        "CRYPTO_HEADER",
        "🪙 <b>STAALWAG · Crypto Desk</b>" if dedicated
        else "🪙 <b>VELDRIN · Crypto Desk</b>")
    return [(ch_env, vip_env, header,
             [("🪙 <b>CRYPTO</b>", "crypto", None, 6)], "crypto")]


WEEKEND_NOTE = ("🗓 <i>Weekend — FX, gold/metals &amp; indices are closed. "
                "Crypto trades 24/7, so it's the only desk live today.</i>")


def is_weekend(now=None):
    """True when the traditional markets are shut for the weekend (UTC Sat/Sun).

    The daily post fires once per day, so calendar day is the right resolution:
    FX reopens ~21:00 UTC Sunday but gold/indices stay closed into the Sunday
    evening CME reopen, so we treat the whole of Sat & Sun as crypto-only."""
    now = now or datetime.datetime.utcnow()
    return now.weekday() >= 5  # Mon=0 ... Sat=5, Sun=6


def load(cls):
    with open(os.path.join(C.DATA_DIR, f"opportunities_{cls}.json"), "r", encoding="utf-8") as f:
        return json.load(f)


_REG_ICON = {"BULL": "🟢", "BEAR": "🔴", "SIDE": "🟡"}


def regfmt(o):
    """Short Markov-regime tag for an opportunity line, or '' if unknown."""
    r = o.get("regime") or {}
    st = r.get("state")
    if not st:
        return ""
    persist = r.get("persist")
    tail = f", {int(persist*100)}% stay" if isinstance(persist, (int, float)) else ""
    return f" {_REG_ICON.get(st,'')} {st}{tail}"


def line(o):
    v = o.get("analysis", {}).get("verdict", "")
    return (f"• <b>{o['name']}</b> — {v} · score <b>{o['score']}</b>{regfmt(o)}\n"
            f"   <i>{o.get('trend_desc','')}</i>")


def section_ops(clskey, namefilter, n):
    ops = load(clskey).get("opportunities", [])
    if namefilter:
        ops = [o for o in ops if o["name"] in namefilter]
    return ops[:n]


# --------------------------------------------------------------- signal dedup
# Only post a pair when the MARKET gives a different opportunity. We remember
# the last signal posted for each pair and skip any pair whose signal hasn't
# materially changed since — otherwise a poster fired every N minutes floods
# the channel with the same read (pure noise). This also makes the poster
# idempotent: two runs in the same market state post nothing the second time,
# so a redundant cron can't double-post.
#
# CHANGED_ONLY = "0" restores the old always-post behaviour.
# SCORE_BAND    = points; a score move smaller than the band isn't "a change".
# State lives next to the growth DB (the Railway volume) so it survives
# restarts; override with SIGNAL_STATE_FILE.
CHANGED_ONLY = os.environ.get("SIGNAL_CHANGED_ONLY", "1") != "0"
SCORE_BAND   = float(os.environ.get("SIGNAL_SCORE_BAND", "5"))
_DB_DIR      = os.path.dirname(os.environ.get("GROWTH_DB", "")) or C.DATA_DIR
SIGNAL_STATE_FILE = os.environ.get("SIGNAL_STATE_FILE",
                                   os.path.join(_DB_DIR, "last_signals.json"))


def fingerprint(o):
    """Compact signature of a pair's actionable signal. Same fingerprint =
    'no material change' => don't repost. Captures verdict, a coarse score
    band (so score jitter isn't a 'change'), and Markov regime state."""
    v = o.get("analysis", {}).get("verdict", "")
    try:
        band = round(float(o.get("score") or 0) / SCORE_BAND) if SCORE_BAND > 0 else o.get("score")
    except (TypeError, ValueError):
        band = o.get("score")
    reg = (o.get("regime") or {}).get("state") or ""
    return f"{v}|{band}|{reg}"


def load_state():
    try:
        with open(SIGNAL_STATE_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_state(state):
    try:
        d = os.path.dirname(SIGNAL_STATE_FILE)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(SIGNAL_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:  # noqa: BLE001
        print("WOLF: could not save signal state:", e)


def compose(brand, sections, vip, trackkey="site", note=None,
            state=None, changed_only=CHANGED_ONLY):
    """Build the desk post. Returns (msg, posted_fps).

    When `changed_only`, each pair is compared against `state` (its last posted
    fingerprint) and only pairs whose signal changed are included; if nothing
    changed the whole desk is skipped and msg is None (no noise post).
    `posted_fps` maps the included pairs' names to their new fingerprint so the
    caller can persist them after a successful send."""
    today = datetime.datetime.utcnow().strftime("%d %b %Y")
    state = state or {}
    # build each asset section; collect shown ops for the regime vote and the
    # fingerprints of the pairs we actually include (post)
    shown, body, posted_fps = [], [], {}
    for label, clskey, nf, n in sections:
        ops = section_ops(clskey, nf, n)
        if not ops:
            continue
        rows = []
        for o in ops:
            fp = fingerprint(o)
            if changed_only and state.get(o["name"]) == fp:
                continue  # same signal as last post -> not a new opportunity
            rows.append(o)
            posted_fps[o["name"]] = fp
        if not rows:
            continue
        shown += rows
        body.append("")
        body.append(label)
        for o in rows:
            body.append(line(o))
    if changed_only and not posted_fps:
        return None, posted_fps  # nothing changed since last post -> skip desk
    L = [FIRM, brand, BY, TAGLINE, "━━━━━━━━━━━━━━",
         f"<i>{today} · STAALWAG intel read</i>", ""]
    if note:
        L.append(note)
        L.append("")
    # Markov market regime — majority vote across everything shown today
    try:
        from scout.regime import market_read
        mk = market_read([o.get("regime") or {} for o in shown])
        if mk.get("state"):
            v = mk["votes"]
            L.append(f"📊 <b>Regime: {_REG_ICON.get(mk['state'],'')} {mk['state']}</b>"
                     f"  <i>(Bull {v['BULL']} / Bear {v['BEAR']} / Side {v['SIDE']})</i>")
    except Exception:
        pass
    L += body
    L.append("")
    if vip:
        # VIP is live: full signals behind the paywall
        L.append("Full case files + exact levels + trade management → <b>VIP</b>.")
        L.append(f"👉 <a href=\"{vip}\">Join</a>")
    else:
        # No VIP yet: draw with transparency, not a promise we can't back
        L.append("We post our read every day and log every call publicly —")
        L.append("<b>follow to watch the track record build in the open.</b>")
    # tracked CTA -> counts clicks via the WOLF server's /l endpoint
    L.append(f'📈 <a href="{WOLF_URL}/l?c={trackkey}">Open the live board →</a>')
    L.append("")
    L.append("━━━━━━━━━━━━━━")
    L.append("<b>STAALWAG</b> · 🐺 WOLF Intel Desk · Read the market like a wolf.")
    L.append("<i>Research/education, not financial advice. Trade your own plan.</i>")
    return "\n".join(L), posted_fps


def _api(method, payload):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}",
                      json=payload, timeout=25)
    ok = r.status_code == 200 and r.json().get("ok")
    return ok, (r.text[:200] if not ok else "")


def send(channel, msg):
    """Lead every post with the STAALWAG emblem so the logo brand rides on it.
    Telegram captions cap at 1024 chars; longer reads send the emblem + branded
    head as a photo, then the rest as a follow-up. Splitting on line boundaries
    keeps each line's HTML tags balanced across the two messages."""
    if len(msg) <= 1024:
        return _api("sendPhoto", {"chat_id": channel, "photo": STAALWAG_IMG,
                                  "caption": msg, "parse_mode": "HTML"})
    lines = msg.split("\n"); head = []; n = 0
    for ln in lines:
        if head and n + len(ln) + 1 > 1000:
            break
        head.append(ln); n += len(ln) + 1
    rest = "\n".join(lines[len(head):]).strip()
    ok1, e1 = _api("sendPhoto", {"chat_id": channel, "photo": STAALWAG_IMG,
                                 "caption": "\n".join(head), "parse_mode": "HTML"})
    ok2, e2 = (True, "")
    if rest:
        ok2, e2 = _api("sendMessage", {"chat_id": channel, "text": rest,
                                       "parse_mode": "HTML", "disable_web_page_preview": True})
    return (ok1 and ok2), (e1 or e2)


def main():
    print("WOLF: refreshing data for daily posts ...")
    run.main()
    # Weekends: markets are shut except crypto (24/7), so post only the crypto
    # desk. Weekdays: the normal gold/indices + FX desks.
    weekend = is_weekend()
    desks = weekend_desks() if weekend else DESKS
    note = WEEKEND_NOTE if weekend else None
    print(f"WOLF: {'weekend — crypto desk only' if weekend else 'weekday desks'}"
          f"{' · changed-signals-only' if CHANGED_ONLY else ''}")

    state = load_state() if CHANGED_ONLY else {}
    any_posted = False
    for ch_env, vip_env, brand, sections, trackkey in desks:
        channel = os.environ.get(ch_env, "")
        vip = os.environ.get(vip_env, "")
        msg, posted_fps = compose(brand, sections, vip, trackkey, note, state)
        if msg is None:
            print(f"WOLF: no new signals for {ch_env} — skipping (nothing changed)")
            continue
        if not TOKEN or not channel:
            print(f"\n--- DRY RUN [{ch_env}] ---\n")
            plain = (msg.replace("<b>", "").replace("</b>", "").replace("<i>", "")
                        .replace("</i>", "").replace("&amp;", "&"))
            print(plain)
            state.update(posted_fps); any_posted = True
            continue
        ok, err = send(channel, msg)
        print(f"WOLF: {'posted' if ok else 'FAILED'} -> {ch_env} {err}")
        if ok:
            # only remember what actually went out, so a failed send retries next run
            state.update(posted_fps); any_posted = True

    if CHANGED_ONLY and any_posted:
        save_state(state)

    # X (Twitter) discovery post — cold-audience top of funnel. Only fire it when
    # a channel signal actually changed, so a frequent cron doesn't flood X either.
    # Dry-runs harmlessly if the 4 X_* keys aren't set yet.
    if any_posted or not CHANGED_ONLY:
        try:
            import promo_x
            okx, infox = promo_x.post(promo_x.compose_daily())
            print(f"WOLF: X {'posted' if okx else 'dry-run/FAILED'} {infox}")
        except Exception as e:  # noqa: BLE001
            print("WOLF: X error", e)
    else:
        print("WOLF: X skipped — no signal change")


if __name__ == "__main__":
    main()
