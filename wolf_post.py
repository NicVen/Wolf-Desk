"""THE WOLF — daily Telegram auto-post.

Builds fresh data, composes a branded teaser of the top picks across all asset
classes, and posts it to your FREE Telegram channel (to funnel toward VIP).

Env:
  TELEGRAM_BOT_TOKEN   bot token from @BotFather (bot must be admin of channel)
  TELEGRAM_CHANNEL     @yourchannel  or  -100xxxxxxxxxx (channel id)
  WOLF_VIP_LINK        invite/join link shown as the call-to-action (optional)

No token set = DRY RUN: prints the post instead of sending (safe to test).

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

TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHANNEL = os.environ.get("TELEGRAM_CHANNEL", "")
VIP     = os.environ.get("WOLF_VIP_LINK", "")

EMO = {"commodities": "🛢️", "fx": "💱", "indices": "📈", "stocks": "📊"}


def load(cls):
    p = os.path.join(C.DATA_DIR, f"opportunities_{cls}.json")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def compose():
    today = datetime.datetime.utcnow().strftime("%d %b %Y")
    per_class, allrows = [], []
    for key in C.ASSET_CLASSES:
        data = load(key)
        ops = data.get("opportunities", [])
        if not ops:
            continue
        top = ops[0]
        per_class.append((key, data.get("asset", key), top))
        for o in ops:
            o["_class"] = data.get("asset", key)
            allrows.append(o)
    allrows.sort(key=lambda r: r["score"], reverse=True)

    L = []
    L.append("🐺 <b>THE WOLF — Daily Market Read</b>")
    L.append(f"<i>{today} · scouted across Commodities · FX · Indices · Stocks</i>")
    L.append("")
    L.append("<b>🎯 Top 3 opportunities right now:</b>")
    for o in allrows[:3]:
        v = o.get("analysis", {}).get("verdict", "")
        L.append(f"• <b>{o['name']}</b> ({o['_class']}) — {v} · score <b>{o['score']}</b>")
        L.append(f"   <i>{o.get('trend_desc','')}</i>")
    L.append("")
    L.append("<b>By desk:</b>")
    for key, label, top in per_class:
        v = top.get("analysis", {}).get("verdict", "")
        L.append(f"{EMO.get(key,'•')} {label}: <b>{top['name']}</b> ({v} {top['score']})")
    L.append("")
    L.append("Full case files, the live intel desk + trade signals → <b>VIP</b>.")
    if VIP:
        L.append(f"👉 <a href=\"{VIP}\">Join the pack</a>")
    L.append("")
    L.append("<i>Research/education, not financial advice. Trade your own plan.</i>")
    return "\n".join(L)


def main():
    print("WOLF: refreshing data for daily post ...")
    run.main()                      # rebuild all classes fresh
    msg = compose()
    if not TOKEN or not CHANNEL:
        print("\n--- DRY RUN (no TELEGRAM_BOT_TOKEN/CHANNEL set) ---\n")
        print(msg.replace("<b>", "").replace("</b>", "").replace("<i>", "")
                 .replace("</i>", "").replace("&amp;", "&"))
        print("\n--- set the env vars to actually post ---")
        return
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json={"chat_id": CHANNEL, "text": msg, "parse_mode": "HTML",
                            "disable_web_page_preview": True}, timeout=20)
    ok = r.status_code == 200 and r.json().get("ok")
    print("WOLF: posted to Telegram" if ok else f"WOLF: post failed {r.status_code} {r.text[:200]}")


if __name__ == "__main__":
    main()
