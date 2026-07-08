"""THE WOLF — daily Telegram auto-post (tailored per channel).

  STAALWAG channel  <-  Gold & Commodities desk
  VELDRIN channel   <-  FX desk

Builds fresh data, composes a branded post per desk, posts to each channel.

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

# Public brand (unified across every channel). NEVER use "HQ" here -- HQ is the
# admin-only command centre, internal monitoring only, never shown publicly.
FIRM    = "🐺 <b>THE WOLF</b> — <i>Intraday Intel Desk</i>"
TAGLINE = "<i>Read the market like a wolf.</i>"

# desk -> (env channel, env vip, asset-class key, sub-desk header, lead name or None)
DESKS = [
    ("STAALWAG_CHANNEL", "STAALWAG_VIP", "commodities",
     "🥇 <b>STAALWAG · Gold &amp; Commodities</b>", "Gold"),
    ("VELDRIN_CHANNEL",  "VELDRIN_VIP",  "fx",
     "💱 <b>VELDRIN · FX Desk</b>", None),
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


def compose(clskey, brand, lead, vip):
    today = datetime.datetime.utcnow().strftime("%d %b %Y")
    ops = load(clskey).get("opportunities", [])
    L = [FIRM, brand, TAGLINE, "━━━━━━━━━━━━━━",
         f"<i>{today} · WOLF intel read</i>", ""]
    # Markov market regime — majority vote across today's assets
    try:
        from scout.regime import market_read
        mk = market_read([o.get("regime") or {} for o in ops])
        if mk.get("state"):
            v = mk["votes"]
            L.append(f"📊 <b>Market regime: {_REG_ICON.get(mk['state'],'')} "
                     f"{mk['state']}</b>  <i>(Bull {v['BULL']} / Bear {v['BEAR']} "
                     f"/ Side {v['SIDE']})</i>")
            L.append("")
    except Exception:
        pass
    if lead:
        led = next((o for o in ops if o["name"] == lead), None)
        if led:
            L.append("<b>Headline:</b>")
            L.append(line(led)); L.append("")
    L.append("<b>Top opportunities today:</b>")
    for o in ops[:3]:
        L.append(line(o))
    L.append("")
    if vip:
        # VIP is live: full signals behind the paywall
        L.append("Full case files + exact levels + trade management → <b>VIP</b>.")
        L.append(f"👉 <a href=\"{vip}\">Join</a>")
    else:
        # No VIP yet: draw with transparency, not a promise we can't back
        L.append("We post our read every day and log every call publicly —")
        L.append("<b>follow to watch the track record build in the open.</b>")
    L.append("")
    L.append("━━━━━━━━━━━━━━")
    L.append("🐺 <b>THE WOLF</b> · Read the market like a wolf.")
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
    for ch_env, vip_env, clskey, brand, lead in DESKS:
        channel = os.environ.get(ch_env, "")
        vip = os.environ.get(vip_env, "")
        msg = compose(clskey, brand, lead, vip)
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
