"""WOLF — X (Twitter) auto-poster. FREE tier friendly.

X API v2 free tier allows posting (~1,500 tweets/month) at no cost — you
only need a free developer app for the 4 keys. This posts WOLF content to
X to funnel people to the free Telegram channels (safe, legal "volume").

Uses:
  - promo_x.post(text)          one-off / admin /tweet
  - promo_x.compose_daily()     builds a digest tweet from today's WOLF data
  - `python promo_x.py`         posts the daily digest (schedule via Railway cron)

Env (all free from developer.x.com):
  X_API_KEY  X_API_SECRET  X_ACCESS_TOKEN  X_ACCESS_SECRET
  PUBLIC_HANDLE_GOLD (default @staalwagsignals)
  PUBLIC_HANDLE_FX   (default @veldrinforex)
No keys set => dry run (prints the tweet instead of posting).
"""
import os, json, glob

try:
    import truststore; truststore.inject_into_ssl()
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CK = os.getenv("X_API_KEY", ""); CS = os.getenv("X_API_SECRET", "")
AT = os.getenv("X_ACCESS_TOKEN", ""); AS = os.getenv("X_ACCESS_SECRET", "")
H_GOLD = os.getenv("PUBLIC_HANDLE_GOLD", "@staalwagsignals")
H_FX   = os.getenv("PUBLIC_HANDLE_FX", "@veldrinforex")


def enabled() -> bool:
    return all([CK, CS, AT, AS])


def post(text: str):
    """Post a tweet. Returns (ok, info). Dry-run prints if keys are missing."""
    text = text[:280]
    if not enabled():
        print("[X dry-run]\n" + text + "\n")
        return True, "dry-run"
    try:
        from requests_oauthlib import OAuth1Session
        oauth = OAuth1Session(CK, CS, AT, AS)
        r = oauth.post("https://api.twitter.com/2/tweets", json={"text": text}, timeout=20)
        ok = r.status_code in (200, 201)
        return ok, (r.json().get("data", {}).get("id") if ok else r.text[:200])
    except Exception as e:
        return False, str(e)


def _top(cls, n=3):
    try:
        d = json.load(open(os.path.join(DATA, "opportunities_%s.json" % cls), encoding="utf-8"))
        return d.get("opportunities", [])[:n]
    except Exception:
        return []


def compose_daily() -> str:
    """A punchy digest tweet from today's WOLF intel, funneling to Telegram."""
    lines = ["STAALWAG · 🐺 WOLF Intel Desk · Read the market like a wolf."]
    picks = []
    for cls, tag in (("fx", ""), ("commodities", "")):
        for o in _top(cls, 2):
            v = o.get("analysis", {}).get("verdict", "")
            if v in ("BUY", "SELL"):
                picks.append("%s %s (%s)" % (o["name"], v, o["score"]))
    if picks:
        lines.append("Reads: " + " · ".join(picks[:4]))
    lines.append("Free daily reads + public track record: %s (gold) %s (fx)" % (H_GOLD, H_FX))
    lines.append("#forex #gold #trading #XAUUSD")
    return "\n".join(lines)[:280]


if __name__ == "__main__":
    ok, info = post(compose_daily())
    print("X:", "posted" if ok else "FAILED", info)
