"""News scout — pulls recent headlines per instrument from Google News RSS
(free, no key) and derives a crude bull/bear news tilt from keywords.

A small on-disk cache (data/news_cache.json, TTL a few hours) means a rebuild
only fetches instruments whose news has gone stale, so builds stay fast and we
don't hammer the feed across 100+ symbols.
"""
import warnings, re, html, json, os, time
warnings.filterwarnings("ignore")
try:
    import truststore; truststore.inject_into_ssl()
except Exception:
    pass
import requests
import xml.etree.ElementTree as ET

_CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "news_cache.json")
NEWS_TTL = int(os.environ.get("NEWS_TTL", 6 * 3600))   # seconds a headline set stays fresh
_CACHE = None


def _cache():
    global _CACHE
    if _CACHE is None:
        try:
            with open(_CACHE_PATH) as f:
                _CACHE = json.load(f)
        except Exception:
            _CACHE = {}
    return _CACHE


def _save_cache():
    try:
        with open(_CACHE_PATH, "w") as f:
            json.dump(_CACHE, f)
    except Exception:
        pass

_HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_RSS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"

# better search phrasing per commodity name
QUERY = {
    "WTI Crude": "WTI crude oil price", "Brent": "Brent crude oil price",
    "Natural Gas": "natural gas price", "Corn": "corn futures price",
    "Wheat": "wheat futures price", "Soybeans": "soybean futures price",
}

BULL = ["deficit","shortage","surge","surges","rally","rallies","jump","jumps","soar","soars",
        "rises","rise","gains","gain","tight","supply cut","output cut","bullish","record high",
        "demand","squeeze","spike","climbs","rebound","upside"]
BEAR = ["glut","surplus","slump","slumps","falls","fall","drops","drop","plunge","plunges",
        "oversupply","weak demand","bearish","sell-off","selloff","decline","declines","tumble",
        "downside","slips","slide","cools"]


def _clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def headlines(name, n=5):
    # serve from cache while fresh (keeps big builds fast + polite to the feed)
    c = _cache()
    hit = c.get(name)
    if hit and (time.time() - hit.get("ts", 0)) < NEWS_TTL:
        return hit.get("headlines", [])[:n], hit.get("tilt", "no news")
    q = QUERY.get(name, f"{name} price").replace(" ", "%20")
    try:
        r = requests.get(_RSS.format(q=q), headers=_HDR, timeout=12)
        root = ET.fromstring(r.content)
    except Exception:
        if hit:  # stale but better than nothing
            return hit.get("headlines", [])[:n], hit.get("tilt", "no news")
        return [], "no news"
    items = root.findall(".//item")[:n]
    out = []
    for it in items:
        title = _clean(it.findtext("title"))
        link  = (it.findtext("link") or "").strip()
        src_el = it.find("{*}source") or it.find("source")
        src   = _clean(src_el.text) if src_el is not None else ""
        pub   = (it.findtext("pubDate") or "")[:16]
        if title:
            out.append({"title": title, "source": src, "date": pub, "link": link})

    blob = " ".join(h["title"].lower() for h in out)
    b = sum(blob.count(w) for w in BULL)
    s = sum(blob.count(w) for w in BEAR)
    if not out:           tilt = "no recent news"
    elif b - s >= 2:      tilt = "bullish news flow"
    elif s - b >= 2:      tilt = "bearish news flow"
    else:                 tilt = "mixed news flow"
    c[name] = {"ts": int(time.time()), "headlines": out, "tilt": tilt}
    _save_cache()
    return out, tilt
