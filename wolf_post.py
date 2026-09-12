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

Daily Desk Playbook (our FLAGSHIP: Gold + top major FX — the markets we trade and
plan in full; honest framing — setups + reasoning + data, not claimed trades.
Weekday only, since Gold & FX are shut on weekends):
  PLAYBOOK_ENABLED     "1" (default) posts the playbook alongside the digest.
  PLAYBOOK_FX_COUNT    how many major FX pairs to feature with Gold (default 2,
                       i.e. Gold + 2 = 3 setups).
  PLAYBOOK_CHANNEL     channel env it posts to (default STAALWAG_CHANNEL).

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
#   We TRADE commodities (Gold) + FX.   STAALWAG -> Gold   VELDRIN -> Forex
_GOLD    = ("🥇 <b>GOLD</b>",    "commodities", ("Gold",), 1)
_INDICES = ("📈 <b>INDICES</b>", "indices",     None,      3)
_FOREX   = ("💱 <b>FOREX</b>",   "fx",          None,      4)


# We trade commodities (Gold) and FX, so those are the only desks we POST.
# Indices are still scored and shown on the Intel desk (dashboard) for context,
# but are NOT posted as signals unless we opt in with a dedicated channel:
# set INDICES_CHANNEL / INDICES_VIP (and optionally INDICES_HEADER) — e.g. if we
# start trading indices later — and an indices desk is added with no other code
# change. Stocks are not covered at all.
def weekday_desks():
    """Resolve the weekday desks we post signals for: Gold (commodities) + FX.
    Indices are display-only (dashboard) and only posted if a dedicated
    INDICES_CHANNEL is configured (falling back to STAALWAG_VIP for the VIP link
    if INDICES_VIP is unset). Tuple: (channel env, vip env, header, [sections], key)."""
    desks = [("STAALWAG_CHANNEL", "STAALWAG_VIP", "🥇 <b>Gold desk</b>", [_GOLD], "gold")]
    if os.environ.get("INDICES_CHANNEL"):
        vip_env = "INDICES_VIP" if os.environ.get("INDICES_VIP") else "STAALWAG_VIP"
        header  = os.environ.get("INDICES_HEADER", "📈 <b>STAALWAG · Indices Desk</b>")
        desks.append(("INDICES_CHANNEL", vip_env, header, [_INDICES], "indices"))
    desks.append(("VELDRIN_CHANNEL", "VELDRIN_VIP", "💱 <b>VELDRIN · FX Desk</b>",
                  [_FOREX], "fx"))
    return desks

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
    Tuple shape: (channel env, vip env, header, [sections], track key)."""
    ch_env  = "CRYPTO_CHANNEL" if os.environ.get("CRYPTO_CHANNEL") else "VELDRIN_CHANNEL"
    vip_env = "CRYPTO_VIP"     if os.environ.get("CRYPTO_VIP")     else "VELDRIN_VIP"
    dedicated = ch_env == "CRYPTO_CHANNEL"
    header = os.environ.get(
        "CRYPTO_HEADER",
        "🪙 <b>STAALWAG · Crypto Desk</b>" if dedicated
        else "🪙 <b>VELDRIN · Crypto Desk</b>")
    return [(ch_env, vip_env, header,
             [("🪙 <b>CRYPTO</b>", "crypto", None, 6)], "crypto")]


WEEKEND_NOTE = ("🗓 <i>Weekend — Gold, FX &amp; indices are closed. Crypto trades "
                "24/7 — data &amp; findings for those who trade it (not a market we "
                "trade ourselves).</i>")


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

# Daily "Desk Playbook" — our FLAGSHIP, comprehensive read for the free channel.
# It covers our focus markets only: Gold + the top major FX pairs (that's what we
# trade and give full trading plans on). Other markets (indices, stocks, crypto)
# stay available on the Intel desk + Q&A, but the deep playbook stays focused so
# the reader isn't overwhelmed. Honest framing: we produce the setup/analysis and
# log it in the open; taking the trade is the reader's call — we never claim live
# trades. Weekday only (Gold & FX are closed on weekends). Posted alongside the
# per-desk digest, once a day (deduped by day + line-up).
PLAYBOOK_ENABLED  = os.environ.get("PLAYBOOK_ENABLED", "1") != "0"
# How many major FX pairs to feature alongside Gold (default 2 -> Gold + 2 = 3).
PLAYBOOK_FX_COUNT = int(os.environ.get("PLAYBOOK_FX_COUNT", "2"))
PLAYBOOK_CHANNEL  = os.environ.get("PLAYBOOK_CHANNEL", "STAALWAG_CHANNEL")


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


def _verdict_icon(v):
    return "🟢" if v.startswith("BUY") else "🔴" if v == "SELL" else "🟡"


def _play_rank(o):
    v = o.get("analysis", {}).get("verdict", "")
    decisive = 0 if v in ("BUY", "SELL") else 1 if v.startswith("BUY") else 2
    return (decisive, -(o.get("score") or 0))


def select_playbook():
    """The flagship playbook covers our FOCUS markets: Gold + the top major FX
    pairs — that's what we trade and give full plans on. Weekday only (Gold & FX
    are closed on weekends). Other markets stay available on the Intel desk + Q&A
    but aren't in the deep playbook. Returns [(clskey, op)], Gold first."""
    if is_weekend():
        return []
    picks = []
    gold = section_ops("commodities", ("Gold",), 1)
    if gold:
        picks.append(("commodities", gold[0]))
    majors = [o for o in load("fx").get("opportunities", [])
              if o.get("category") == "Major"]
    majors.sort(key=_play_rank)
    picks += [("fx", o) for o in majors[:PLAYBOOK_FX_COUNT]]
    return picks


def playbook_fingerprint(picks):
    """Day + the chosen line-up's signals. Changes each new day, or if the
    selection / a pick's signal materially changes intraday."""
    day = datetime.datetime.utcnow().strftime("%Y%m%d")
    return day + "::" + "|".join(f"{o['name']}:{fingerprint(o)}" for _k, o in picks)


def _play_entry(i, clskey, o):
    a = o.get("analysis", {})
    v = a.get("verdict", "WATCH")
    icon = _verdict_icon(v)
    lean = "LONG" if v.startswith("BUY") else "SHORT" if v == "SELL" else "NEUTRAL"
    market = C.ASSET_CLASSES.get(clskey, {}).get("label", clskey.title())
    bull = (a.get("bull") or ["—"])[0]
    bear = (a.get("bear") or ["—"])[0]
    return "\n".join([
        f"<b>{i}. {icon} {o['name']}</b> <i>· {market}</i> — lean <b>{lean}</b> · "
        f"conviction {a.get('conviction','')}{regfmt(o)}",
        f"   <i>Read:</i> {a.get('price_reasoning','')}",
        f"   <i>Edge:</i> {bull}",
        f"   <i>Invalidation:</i> {bear}",
        f"   <i>Data:</i> {a.get('score_reasoning','')}",
    ])


def compose_playbook(picks, vip):
    """The daily Desk Playbook post for the free channel — the best setup in each
    market. Honest framing: setups + reasoning + data; execution is the reader's
    own decision."""
    today = datetime.datetime.utcnow().strftime("%d %b %Y")
    L = [FIRM,
         "🎯 <b>Desk Playbook — Gold &amp; major FX</b>",
         BY, TAGLINE, "━━━━━━━━━━━━━━",
         f"<i>{today} · our focus markets — the read, the reasoning, the data, "
         "the plan</i>", "",
         "<i>Gold and the major FX pairs are what we trade and plan in full. We "
         "produce the setup and the case for it and log it in the open — whether "
         "to take the trade is your call. We don't take every setup ourselves.</i>", ""]
    for i, (clskey, o) in enumerate(picks, 1):
        L.append(_play_entry(i, clskey, o))
        L.append("")
    if vip:
        L.append("Full case files + exact levels + trade management → <b>VIP</b>.")
        L.append(f"👉 <a href=\"{vip}\">Join</a>")
    else:
        L.append("Every call logged publicly — <b>follow the track record build in the open.</b>")
    L.append(f'📈 <a href="{WOLF_URL}/l?c=playbook">Open the live board →</a>')
    L += ["", "━━━━━━━━━━━━━━",
          "<b>STAALWAG</b> · 🐺 WOLF Intraday Intel Desk · Read the market like a wolf.",
          "<i>Research/education, not financial advice. Trade your own plan.</i>"]
    return "\n".join(L)


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
    desks = weekend_desks() if weekend else weekday_desks()
    note = WEEKEND_NOTE if weekend else None
    print(f"WOLF: {'weekend — crypto desk only' if weekend else 'weekday desks'}"
          f"{' · changed-signals-only' if CHANGED_ONLY else ''}")

    state = load_state() if CHANGED_ONLY else {}
    any_posted = False

    # Flagship Desk Playbook — Gold + major FX (our focus), posted alongside the
    # per-desk digest. Weekday only; once a day (deduped by day + line-up).
    if PLAYBOOK_ENABLED and not weekend:
        pb_channel = os.environ.get(PLAYBOOK_CHANNEL, "")
        picks = select_playbook()
        pb_fp = playbook_fingerprint(picks) if picks else ""
        if not picks:
            print("WOLF: playbook — no candidates, skipping")
        elif CHANGED_ONLY and state.get("__playbook__") == pb_fp:
            print("WOLF: playbook already posted for this line-up — skipping")
        else:
            pb_msg = compose_playbook(picks, os.environ.get("STAALWAG_VIP", ""))
            if not TOKEN or not pb_channel:
                print(f"\n--- DRY RUN [PLAYBOOK -> {PLAYBOOK_CHANNEL}] ---\n")
                print(pb_msg.replace("<b>", "").replace("</b>", "")
                            .replace("<i>", "").replace("</i>", "").replace("&amp;", "&"))
                state["__playbook__"] = pb_fp; any_posted = True
            else:
                ok, err = send(pb_channel, pb_msg)
                print(f"WOLF: playbook {'posted' if ok else 'FAILED'} -> {PLAYBOOK_CHANNEL} {err}")
                if ok:
                    state["__playbook__"] = pb_fp; any_posted = True

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
