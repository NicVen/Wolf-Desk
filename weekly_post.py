"""THE WOLF — weekly Telegram posts (backed by Nico's Trading Desk analysis).

  Monday    -> WEEKLY OUTLOOK   : the week ahead (regime, per-desk watchlist, key events)
  Wednesday -> WEEKLY PROGRESS  : how the week is tracking (signals + pips so far)

Brand map: STAALWAG (firm) / STAALWAG HQ (admin-only) / THE WOLF Intraday Intel
Desk (public, this poster) / signals = STAALWAG Gold, VELDRIN Forex, Markov 18-pair.

Reuses wolf_post's brand + section engine, posts to the same channels.

Run:  python weekly_post.py             # auto: posts outlook Mon, progress Wed
      python weekly_post.py --outlook   # force outlook
      python weekly_post.py --progress  # force progress
No TELEGRAM_BOT_TOKEN = DRY RUN (prints instead of sending).
"""
import os
import sys
import json
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wolf_post as W

try:
    import truststore; truststore.inject_into_ssl()
except Exception:
    pass
import urllib.request
import requests

RI = W._REG_ICON

# Verified pip track records (this-week stats for the progress post)
TRACK = {
    "gold": ("STAALWAG Gold", os.getenv(
        "STAALWAG_TRACK", "https://worker-production-d88c.up.railway.app/track_record.json")),
    "fx":   ("VELDRIN Forex", os.getenv(
        "VELDRIN_TRACK", "https://veldrin-desk-production.up.railway.app/track_record.json")),
}
MARKOV_URL = os.getenv("MARKOV_BOT_URL",
                       "https://npx-railwaycli-up-production-6365.up.railway.app").rstrip("/")


def _fetch(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _iso_week(ts):
    try:
        return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).isocalendar()[:2]
    except Exception:
        return None


def _this_week():
    return datetime.datetime.utcnow().isocalendar()[:2]


def week_stats(outcomes):
    """(n, wins, losses, net_pips) for outcomes closed in the current ISO week."""
    wk = _this_week()
    n = w = l = 0
    pips = 0.0
    for o in outcomes or []:
        if _iso_week(o.get("ts")) != wk:
            continue
        n += 1
        pips += float(o.get("pips") if o.get("pips") is not None else (o.get("pnl_usd") or 0) or 0)
        res = (o.get("result") or "").upper()
        if res == "WIN":
            w += 1
        elif res == "LOSS":
            l += 1
    return n, w, l, round(pips, 1)


def markov_week_count():
    d = _fetch(MARKOV_URL + "/signals.json")
    sigs = (d or {}).get("signals", []) if isinstance(d, dict) else (d or [])
    wk = _this_week()
    return sum(1 for s in sigs if _iso_week(s.get("time") or s.get("ts")) == wk)


def calendar_high(n=3):
    """Top high-impact events this week (free faireconomy feed)."""
    try:
        r = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
        out, seen = [], set()
        for e in r.json():
            if e.get("impact") != "High":
                continue
            key = (e.get("country", ""), e.get("title", ""))
            if key in seen:
                continue
            seen.add(key)
            out.append("%s %s" % (e.get("country", ""), e.get("title", "")))
            if len(out) >= n:
                break
        return out
    except Exception:
        return []


def compose_outlook(brand, sections):
    mon = datetime.datetime.utcnow().strftime("%d %b %Y")
    shown, body = [], []
    for label, clskey, nf, num in sections:
        ops = W.section_ops(clskey, nf, num)
        if not ops:
            continue
        shown += ops
        body.append("")
        body.append(label)
        for o in ops:
            body.append(W.line(o))
    L = [W.FIRM, W.BY, brand, W.TAGLINE, "━━━━━━━━━━━━━━",
         f"🗓 <b>WEEKLY OUTLOOK</b> · week of {mon}", ""]
    try:
        from scout.regime import market_read
        mk = market_read([o.get("regime") or {} for o in shown])
        if mk.get("state"):
            v = mk["votes"]
            L.append(f"📊 <b>Week regime: {RI.get(mk['state'],'')} {mk['state']}</b>"
                     f"  <i>(Bull {v['BULL']} / Bear {v['BEAR']} / Side {v['SIDE']})</i>")
    except Exception:
        pass
    L.append("<b>What we're watching this week:</b>")
    L += body
    ev = calendar_high(3)
    if ev:
        L.append("")
        L.append("📅 <b>Key events:</b> " + " · ".join(ev))
    L.append("")
    L.append("<b>The plan:</b> trade with the regime, bank at target, cut fast. "
             "Backed by our desk's weekly analysis.")
    return L


def compose_progress(brand, trackkey):
    today = datetime.datetime.utcnow().strftime("%d %b %Y")
    L = [W.FIRM, W.BY, brand, W.TAGLINE, "━━━━━━━━━━━━━━",
         f"📊 <b>WEEKLY PROGRESS</b> · {today}", "",
         "<i>How the week is tracking so far — every call logged in the open.</i>", ""]
    # firm-wide pips this week across the pip desks
    fn = fw = fl = 0
    fp = 0.0
    for key, (label, url) in TRACK.items():
        d = _fetch(url)
        n, w, l, pips = week_stats((d or {}).get("outcomes", []))
        fn += n; fw += w; fl += l; fp = round(fp + pips, 1)
        tag = "🥇" if key == "gold" else "💱"
        if n:
            L.append(f"{tag} <b>{label}</b>: {n} closed · "
                     f"{'+' if pips >= 0 else ''}{pips} pips ({w}W/{l}L)")
        else:
            L.append(f"{tag} <b>{label}</b>: no closes yet this week")
    mk = markov_week_count()
    L.append(f"🎲 <b>Markov 18-pair</b>: {mk} new setups this week")
    L.append("")
    dec = fw + fl
    wr = round(100 * fw / dec, 0) if dec else 0
    L.append(f"<b>Week so far:</b> {fn} closed · "
             f"{'+' if fp >= 0 else ''}{fp} pips · {wr:.0f}% win")
    return L


def _finish(L, vip, trackkey):
    if vip:
        L.append("Full case files + exact levels + management → <b>VIP</b>.")
        L.append(f'👉 <a href="{vip}">Join</a>')
    else:
        L.append("We log every call publicly — <b>follow the record build in the open.</b>")
    L.append(f'📈 <a href="{W.WOLF_URL}/l?c={trackkey}">Open the live board →</a>')
    L.append("")
    L.append("━━━━━━━━━━━━━━")
    L.append("🐺 <b>THE WOLF</b> · a STAALWAG desk · Read the market like a wolf.")
    L.append("<i>Research/education, not financial advice. Trade your own plan.</i>")
    return "\n".join(L)


def main():
    force = "--outlook" if "--outlook" in sys.argv else (
        "--progress" if "--progress" in sys.argv else None)
    wd = datetime.datetime.utcnow().weekday()  # Mon=0 Wed=2
    kind = force[2:] if force else ("outlook" if wd == 0 else "progress" if wd == 2 else None)
    if not kind:
        print("weekly_post: not Mon/Wed and no --outlook/--progress flag; nothing to do.")
        return

    print("WOLF weekly: refreshing data for %s post ..." % kind)
    try:
        import run
        run.main()
    except Exception as e:  # noqa: BLE001
        print("weekly_post: data refresh skipped (%s)" % e)

    for ch_env, vip_env, brand, sections, trackkey in W.DESKS:
        channel = os.environ.get(ch_env, "")
        vip = os.environ.get(vip_env, "")
        L = compose_outlook(brand, sections) if kind == "outlook" \
            else compose_progress(brand, trackkey)
        msg = _finish(L, vip, trackkey)
        if not W.TOKEN or not channel:
            print("\n--- DRY RUN [%s / %s] ---\n" % (ch_env or trackkey, kind))
            print(msg.replace("<b>", "").replace("</b>", "").replace("<i>", "")
                     .replace("</i>", "").replace("&amp;", "&"))
            continue
        ok, err = W.send(channel, msg)
        print("WOLF weekly: %s -> %s %s" % (ch_env, "posted" if ok else "FAILED", err))


if __name__ == "__main__":
    main()
