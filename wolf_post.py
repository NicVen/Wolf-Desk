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


def compose(brand, sections, vip, trackkey="site"):
    today = datetime.datetime.utcnow().strftime("%d %b %Y")
    # build each asset section; collect all shown ops for the regime vote
    shown, body = [], []
    for label, clskey, nf, n in sections:
        ops = section_ops(clskey, nf, n)
        if not ops:
            continue
        shown += ops
        body.append("")
        body.append(label)
        for o in ops:
            body.append(line(o))
    L = [FIRM, brand, BY, TAGLINE, "━━━━━━━━━━━━━━",
         f"<i>{today} · STAALWAG intel read</i>", ""]
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
    return "\n".join(L)


def send(channel, msg):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json={"chat_id": channel, "text": msg, "parse_mode": "HTML",
                            "disable_web_page_preview": True}, timeout=20)
    ok = r.status_code == 200 and r.json().get("ok")
    return ok, (r.text[:200] if not ok else "")


def main():
    print("WOLF: refreshing data for daily posts ...")
    run.main()
    for ch_env, vip_env, brand, sections, trackkey in DESKS:
        channel = os.environ.get(ch_env, "")
        vip = os.environ.get(vip_env, "")
        msg = compose(brand, sections, vip, trackkey)
        if not TOKEN or not channel:
            print(f"\n--- DRY RUN [{ch_env or clskey}] ---\n")
            plain = (msg.replace("<b>", "").replace("</b>", "").replace("<i>", "")
                        .replace("</i>", "").replace("&amp;", "&"))
            print(plain)
            continue
        ok, err = send(channel, msg)
        print(f"WOLF: {'posted' if ok else 'FAILED'} -> {ch_env} {err}")

    # X (Twitter) discovery post — cold-audience top of funnel.
    # Dry-runs harmlessly if the 4 X_* keys aren't set yet.
    try:
        import promo_x
        okx, infox = promo_x.post(promo_x.compose_daily())
        print(f"WOLF: X {'posted' if okx else 'dry-run/FAILED'} {infox}")
    except Exception as e:  # noqa: BLE001
        print("WOLF: X error", e)


if __name__ == "__main__":
    main()
