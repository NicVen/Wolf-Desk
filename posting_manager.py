"""STAALWAG — daily posting manager (freestanding).

One on-brand process, two jobs:

  1) POST    — fires the daily WOLF read on a schedule. It reuses wolf_post, so
               it inherits the weekend crypto-only rule AND the per-pair change
               dedup (a pair is only re-posted when the market actually changes).

  2) ANSWER  — a Telegram bot that answers questions about the signals we post,
               both in DMs and in a channel's linked discussion group. Answers
               are RULE-BASED, built from our own scored data + the case file
               compiler already produces (compiler/analysis.py). No external AI,
               no API cost, always on — and it stays cleanly "research/education,
               not financial advice".

Freestanding: `python posting_manager.py` runs both loops. It does not need to
be wired into serve.py, and it can run on any host (Railway not required).

Test offline (no Telegram needed):
  python posting_manager.py --ask "why is EUR/USD a sell?"
  python posting_manager.py --ask "today's reads"
  python posting_manager.py --post            # fire one posting run now

Env:
  POSTING_TIMES       comma-sep UTC HH:MM to post daily   (default "07:00")
  MANAGER_BOT_TOKEN   Q&A bot token. IMPORTANT: Telegram allows only ONE
                      getUpdates consumer per token, and gate_bot.py already
                      uses TELEGRAM_BOT_TOKEN — so give the manager its OWN bot
                      here (recommended), or run it instead of gate_bot. Falls
                      back to TELEGRAM_BOT_TOKEN if unset.
  DISCUSSION_GROUPS   comma-sep chat ids of linked discussion group(s) to answer
                      in (optional). Empty = answer in any group the bot is in.
  QA_ENABLED          "0" to run posting only (no Q&A loop). Default on.
  ADMIN_IDS           comma-sep Telegram ids (shared) — pinged on post runs.
  TELEGRAM_BOT_TOKEN, STAALWAG_CHANNEL, VELDRIN_CHANNEL, ...  used by wolf_post
                      for the actual posting (unchanged).

No MANAGER token = Q&A prints a warning and only the posting scheduler runs.
"""
import os
import re
import sys
import time
import html
import datetime
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import wolf_post as W

try:
    import truststore; truststore.inject_into_ssl()
except Exception:
    pass
import requests

# ------------------------------------------------------------------ config
POSTING_TIMES = [t.strip() for t in os.environ.get("POSTING_TIMES", "07:00").split(",") if t.strip()]
QA_TOKEN      = os.environ.get("MANAGER_BOT_TOKEN", "") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
QA_ENABLED    = os.environ.get("QA_ENABLED", "1") != "0"
GROUPS        = set(g.strip() for g in os.environ.get("DISCUSSION_GROUPS", "").split(",") if g.strip())
ADMINS        = [a.strip() for a in os.environ.get("ADMIN_IDS", "").split(",") if a.strip()]
API           = "https://api.telegram.org/bot%s/" % QA_TOKEN

BRAND = "🐺 <b>STAALWAG</b> · WOLF Intel Desk"
DISC  = "<i>Research/education, not financial advice. Trade your own plan.</i>"


# ------------------------------------------------------------------ data + pair index
def _classes():
    return list(C.ASSET_CLASSES.keys())


def load_all():
    """{clskey: {pair_name: opportunity}} from the latest opportunities_*.json."""
    out = {}
    for cls in _classes():
        try:
            ops = W.load(cls).get("opportunities", [])
            out[cls] = {o["name"]: o for o in ops}
        except Exception:
            out[cls] = {}
    return out


# curated trader shorthand -> canonical pair name (per asset class name in config)
_EXTRA_ALIASES = {
    # metals / energy
    "gold": "Gold", "xau": "Gold", "xauusd": "Gold",
    "silver": "Silver", "xag": "Silver", "xagusd": "Silver",
    "oil": "WTI Crude", "wti": "WTI Crude", "crude": "WTI Crude", "brent": "Brent",
    "natgas": "Natural Gas", "gas": "Natural Gas",
    # indices
    "sp500": "S&P 500", "spx": "S&P 500", "us500": "S&P 500", "spy": "S&P 500",
    "nasdaq": "Nasdaq 100", "ndx": "Nasdaq 100", "us100": "Nasdaq 100", "nas100": "Nasdaq 100",
    "dow": "Dow Jones", "djia": "Dow Jones", "us30": "Dow Jones",
    "russell": "Russell 2000", "rut": "Russell 2000", "us2000": "Russell 2000",
    "dax": "DAX", "ger40": "DAX", "de40": "DAX",
    "ftse": "FTSE 100", "uk100": "FTSE 100",
    "stoxx": "Euro Stoxx 50", "eu50": "Euro Stoxx 50",
    "nikkei": "Nikkei 225", "jp225": "Nikkei 225",
    "hangseng": "Hang Seng", "hk50": "Hang Seng",
    "asx": "ASX 200", "asx200": "ASX 200", "au200": "ASX 200",
    # fx nicknames
    "cable": "GBP/USD", "fiber": "EUR/USD",
    # crypto
    "btc": "BTC/USD", "bitcoin": "BTC/USD", "xbt": "BTC/USD",
    "eth": "ETH/USD", "ether": "ETH/USD", "ethereum": "ETH/USD",
    "sol": "SOL/USD", "solana": "SOL/USD",
    "xrp": "XRP/USD", "ripple": "XRP/USD",
    "bnb": "BNB/USD", "ada": "ADA/USD", "cardano": "ADA/USD",
    "doge": "DOGE/USD", "dogecoin": "DOGE/USD",
    "avax": "AVAX/USD", "link": "LINK/USD", "chainlink": "LINK/USD",
    "ltc": "LTC/USD", "litecoin": "LTC/USD",
    # stocks
    "nvidia": "NVIDIA", "nvda": "NVIDIA", "amd": "AMD",
    "broadcom": "Broadcom", "avgo": "Broadcom",
    "microsoft": "Microsoft", "msft": "Microsoft",
    "apple": "Apple", "aapl": "Apple", "meta": "Meta", "facebook": "Meta",
    "amazon": "Amazon", "amzn": "Amazon",
    "alphabet": "Alphabet", "google": "Alphabet", "googl": "Alphabet",
    "tesla": "Tesla", "tsla": "Tesla", "palantir": "Palantir", "pltr": "Palantir",
}


def build_index():
    """alias(lowercased) -> canonical pair name. Auto forms from config names
    (e.g. 'EUR/USD' -> 'eurusd', 'eur/usd') plus curated shorthand."""
    idx = {}
    for cls in _classes():
        for name in C.ASSET_CLASSES[cls]["universe"]:
            low = name.lower()
            forms = {low, low.replace(" ", ""), low.replace("/", ""),
                     low.replace("/", "").replace(" ", "")}
            for f in forms:
                idx[f] = name
    # curated aliases win / add
    idx.update({k: v for k, v in _EXTRA_ALIASES.items()})
    return idx


_INDEX = build_index()
# match longest aliases first so 'ethereum' beats 'eth', 'nas100' beats nothing partial
_ALIASES_SORTED = sorted(_INDEX.keys(), key=len, reverse=True)


def find_pair(text, data=None):
    """Return (clskey, opportunity) for the first pair named in text, or None."""
    data = data or load_all()
    t = text.lower()
    for alias in _ALIASES_SORTED:
        # word-ish boundary so 'sol' doesn't fire inside 'solve', 'gold' not 'golden'
        pat = r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])"
        if re.search(pat, t):
            name = _INDEX[alias]
            for cls, pairs in data.items():
                if name in pairs:
                    return cls, pairs[name]
    return None


# ------------------------------------------------------------------ intent
_INTENTS = [
    ("levels",   ("level", "entry", "stop", "target", "sl", "tp", "take profit",
                  "take-profit", "price target", "where do i enter", "where to enter")),
    ("score",    ("score", "breakdown", "rating", "points", "how strong")),
    ("regime",   ("regime", "markov", "trending", "ranging", "range")),
    ("volatility", ("volatility", "atr", "how volatile", "risky", "risk")),
    ("trend",    ("trend", "momentum", "direction", "moving average", "ma")),
    ("catalyst", ("catalyst", "news", "event", "fundamental", "why now", "data")),
    ("broker",   ("broker", "where can i trade", "which broker", "prop", "leverage", "coverage")),
    ("fresh",    ("when", "how old", "updated", "how often", "fresh", "last update")),
    ("why",      ("why", "reason", "explain", "case", "rationale", "bull", "bear")),
    ("verdict",  ("buy", "sell", "long", "short", "verdict", "signal", "call")),
    ("digest",   ("today", "reads", "watchlist", "what's on", "whats on", "picks",
                  "opportunities", "overview")),
    ("help",     ("help", "commands", "what can you", "how do i use", "start")),
]


def detect_intent(text):
    t = text.lower()
    for intent, kws in _INTENTS:
        if any(k in t for k in kws):
            return intent
    return "summary"


# ------------------------------------------------------------------ answer building
def _verdict_badge(op):
    v = op.get("analysis", {}).get("verdict", "WATCH")
    icon = "🟢" if v.startswith("BUY") else "🔴" if v == "SELL" else "🟡"
    return f"{icon} <b>{v}</b>"


def _head(op):
    return f"<b>{html.escape(op['name'])}</b> — {_verdict_badge(op)} · score <b>{op.get('score')}</b>"


def _regime_txt(op):
    r = op.get("regime") or {}
    st = r.get("state")
    if not st:
        return "Regime: not available."
    persist = r.get("persist")
    tail = f" ({int(persist*100)}% chance it stays)" if isinstance(persist, (int, float)) else ""
    meaning = {"BULL": "up-bias regime", "BEAR": "down-bias regime",
               "SIDE": "sideways / range regime"}.get(st, st)
    return f"Markov regime: <b>{st}</b> — {meaning}{tail}."


def _wrap(body):
    return f"{BRAND}\n\n{body}\n\n{DISC}"


def _answer_pair(cls, op, intent):
    a = op.get("analysis", {})
    if intent == "why":
        bull = a.get("bull") or []
        bear = a.get("bear") or []
        L = [_head(op), "", html.escape(a.get("summary", "")), ""]
        if bull:
            L.append("✅ <b>For it:</b> " + html.escape(bull[0]))
        if bear:
            L.append("⚠️ <b>Against it:</b> " + html.escape(bear[0]))
        L += ["", "<i>" + html.escape(a.get("price_reasoning", "")) + "</i>"]
        return _wrap("\n".join(x for x in L if x is not None))

    if intent == "score":
        return _wrap(_head(op) + "\n\n" + html.escape(a.get("score_reasoning", "")))

    if intent == "levels":
        price = op.get("price")
        pl = f"Last price we have: <b>{price}</b>. " if price is not None else ""
        return _wrap(
            _head(op) + "\n\n"
            + pl + "This desk publishes <b>scored reads</b> (direction + conviction), "
            "not exact entries/stops in the free channel. Exact levels + trade "
            "management live in the <b>VIP</b> case files.\n\n"
            + f"<i>{html.escape(op.get('trend_desc',''))}</i>")

    if intent == "regime":
        return _wrap(_head(op) + "\n\n" + _regime_txt(op))

    if intent == "volatility":
        atr = op.get("atr_pct")
        vd = op.get("volfit_desc", "")
        band = ("very high — size down" if (atr or 0) > 5 else
                "healthy/tradeable" if (atr or 0) >= 1 else "low/quiet") if atr is not None else "n/a"
        return _wrap(_head(op) + f"\n\nVolatility: <b>{vd}</b> — {band}.")

    if intent == "trend":
        return _wrap(_head(op) + "\n\n" + html.escape(a.get("price_reasoning", "")
                     or op.get("trend_desc", "")))

    if intent == "catalyst":
        note = op.get("note") or ""
        bd = op.get("breakdown", {})
        cat = bd.get("catalyst")
        extra = f" (catalyst score {cat:.0f}/{C.W_CATALYST})" if isinstance(cat, (int, float)) else ""
        body = ("Near-term driver: " + html.escape(note)) if note else \
               "No strong near-term catalyst flagged — this is more of a trend/structure read."
        return _wrap(_head(op) + "\n\n" + body + extra)

    if intent == "broker":
        cov = op.get("coverage") or []
        if cov:
            names = ", ".join(html.escape(b.get("name", "")) for b in cov[:8])
            return _wrap(_head(op) + f"\n\nOffered by {len(cov)} venue(s) we track: {names}."
                         "\n<i>Verify the symbol, spread and leverage with the broker before trading.</i>")
        return _wrap(_head(op) + "\n\nNo broker coverage recorded for this one in our table yet.")

    if intent == "verdict":
        return _wrap(_head(op) + f"\n\n{html.escape(a.get('summary',''))}")

    # summary / fallback for a known pair
    L = [_head(op), "",
         f"<i>{html.escape(op.get('trend_desc',''))}</i>",
         _regime_txt(op), "",
         html.escape(a.get("summary", "")),
         "", "Ask me <b>why</b>, <b>score</b>, <b>levels</b>, <b>regime</b>, "
         "<b>volatility</b>, <b>catalyst</b> or <b>where to trade</b> it."]
    return _wrap("\n".join(L))


def _answer_digest(data=None):
    """Today's live reads across the desks that are open today."""
    data = data or load_all()
    weekend = W.is_weekend()
    desks = W.weekend_desks() if weekend else W.weekday_desks()
    L = [f"📊 <b>Today's STAALWAG reads</b> — {datetime.datetime.utcnow():%d %b %Y} "
         f"{'(weekend — crypto only)' if weekend else ''}".strip(), ""]
    seen = set()
    for _ch, _vip, _hdr, sections, _tk in desks:
        for label, clskey, nf, n in sections:
            ops = W.section_ops(clskey, nf, n)
            if not ops:
                continue
            L.append(re.sub(r"<[^>]+>", "", label) + ":")
            for o in ops:
                if o["name"] in seen:
                    continue
                seen.add(o["name"])
                L.append(f"  • {html.escape(o['name'])} — {_verdict_badge(o)} · "
                         f"score {o.get('score')}")
            L.append("")
    L.append("Ask about any pair by name for the full read.")
    return _wrap("\n".join(L).strip())


def _answer_help():
    return _wrap(
        "I answer questions about the signals we post — free, from our own "
        "scored data.\n\n"
        "Try:\n"
        "• <b>why is EUR/USD a sell?</b>\n"
        "• <b>gold score</b> / <b>gold breakdown</b>\n"
        "• <b>btc regime</b> · <b>nasdaq trend</b> · <b>xauusd volatility</b>\n"
        "• <b>where can I trade gold?</b>\n"
        "• <b>today's reads</b>\n\n"
        "Name the pair (EURUSD, XAUUSD, US30, BTC, NVDA …) and what you want to know.")


def answer(text):
    """Rule-based answer to a question, or None if nothing to say (so the bot can
    stay quiet in a busy group)."""
    if not text or not text.strip():
        return None
    intent = detect_intent(text)
    if intent == "help":
        return _answer_help()
    data = load_all()
    if intent == "digest":
        return _answer_digest(data)
    hit = find_pair(text, data)
    if hit:
        cls, op = hit
        return _answer_pair(cls, op, intent)
    # no pair recognised
    t = text.lower()
    if "?" in text or any(k in t for k in ("signal", "read", "trade", "buy", "sell",
                                           "what", "which", "how", "gold", "fx", "crypto")):
        return _wrap("I couldn't spot which market you mean. Name a pair — e.g. "
                     "<b>EURUSD</b>, <b>XAUUSD</b>, <b>US30</b>, <b>BTC</b>, "
                     "<b>NVDA</b> — or ask for <b>today's reads</b>.")
    return None


# ------------------------------------------------------------------ telegram
_ME = {"username": None}


def _get(method, **params):
    try:
        r = requests.get(API + method, params=params, timeout=60)
        return r.json()
    except Exception as e:
        print("posting_manager: get error:", e)
        return {}


def _post(method, payload):
    try:
        r = requests.post(API + method, json=payload, timeout=25)
        return r.status_code == 200 and r.json().get("ok")
    except Exception as e:
        print("posting_manager: post error:", e)
        return False


def bot_username():
    if _ME["username"] is None:
        _ME["username"] = (_get("getMe").get("result", {}) or {}).get("username", "") or ""
    return _ME["username"]


def send(chat_id, text, reply_to=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
               "disable_web_page_preview": True}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    return _post("sendMessage", payload)


def _should_answer_group(msg, text):
    """In groups, only answer when clearly addressed: bot mentioned, a reply to
    the linked-channel post, or a question that names a pair. Keeps us quiet in
    chatter."""
    chat_id = str(msg.get("chat", {}).get("id", ""))
    if GROUPS and chat_id not in GROUPS:
        return False
    uname = bot_username().lower()
    if uname and ("@" + uname) in text.lower():
        return True
    # reply to an auto-forwarded channel post (Telegram links these in groups)
    reply = msg.get("reply_to_message") or {}
    if reply.get("is_automatic_forward") or reply.get("forward_from_chat"):
        return True
    # otherwise require an actual question about a known pair
    return ("?" in text) and (find_pair(text) is not None)


def handle_update(msg):
    text = msg.get("text") or msg.get("caption") or ""
    if not text:
        return
    chat = msg.get("chat", {})
    ctype = chat.get("type", "")
    # in a reply, also consider the replied-to (channel post) text for pair context
    reply = msg.get("reply_to_message") or {}
    ctx = text
    if reply.get("text") or reply.get("caption"):
        ctx = text + "\n" + (reply.get("text") or reply.get("caption") or "")

    if ctype == "private":
        ans = answer(ctx) or _answer_help()
        send(chat["id"], ans)
        return

    if ctype in ("group", "supergroup"):
        if not _should_answer_group(msg, text):
            return
        ans = answer(ctx)
        if ans:
            send(chat["id"], ans, reply_to=msg.get("message_id"))


def qa_loop():
    if not QA_TOKEN:
        print("posting_manager: no MANAGER_BOT_TOKEN/TELEGRAM_BOT_TOKEN — Q&A OFF.")
        return
    try:
        import watchdog
    except Exception:
        watchdog = None
    print("posting_manager: Q&A up as @%s (groups: %s)"
          % (bot_username() or "?", ", ".join(GROUPS) or "any"))
    offset = None
    while True:
        try:
            r = _get("getUpdates", timeout=50, offset=offset,
                     allowed_updates='["message"]')
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                if "message" in u:
                    try:
                        handle_update(u["message"])
                    except Exception as e:
                        print("posting_manager: handle error:", e)
            if watchdog:
                watchdog.beat("posting_manager")
        except Exception as e:
            print("posting_manager: qa loop error:", e)
            if watchdog:
                watchdog.beat("posting_manager", ok=False, err=e)
            time.sleep(5)


# ------------------------------------------------------------------ posting scheduler
def _ping_admins(text):
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not (tok and ADMINS):
        print("posting_manager (admins):", text)
        return
    for a in ADMINS:
        try:
            requests.post("https://api.telegram.org/bot%s/sendMessage" % tok,
                          json={"chat_id": a, "text": text,
                                "disable_web_page_preview": True}, timeout=15)
        except Exception as e:
            print("posting_manager: admin ping error:", e)


def post_now():
    """Fire one posting run (data refresh + change-only posts + X), via wolf_post."""
    import io, contextlib
    print("posting_manager: firing posting run ...")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            W.main()
        tail = "\n".join(buf.getvalue().strip().splitlines()[-6:])
        print(buf.getvalue().strip())
        _ping_admins("📣 STAALWAG posting run:\n" + (tail or "(done)"))
        return True
    except Exception as e:  # noqa: BLE001
        _ping_admins("⚠️ STAALWAG posting run FAILED: %s" % e)
        print("posting_manager: post run failed:", e)
        return False


def scheduler_loop():
    try:
        import watchdog
    except Exception:
        watchdog = None
    print("posting_manager: scheduler up. posting at %s UTC daily."
          % (", ".join(POSTING_TIMES) or "(none)"))
    fired = {}  # "HH:MM" -> "YYYYMMDD" already fired
    while True:
        try:
            now = datetime.datetime.utcnow()
            slot = now.strftime("%H:%M")
            day = now.strftime("%Y%m%d")
            if slot in POSTING_TIMES and fired.get(slot) != day:
                fired[slot] = day
                post_now()
            if watchdog:
                watchdog.beat("posting_sched")
        except Exception as e:
            print("posting_manager: scheduler error:", e)
        time.sleep(20)


# ------------------------------------------------------------------ entrypoint
def main():
    # CLI helpers (offline-friendly)
    if "--ask" in sys.argv:
        i = sys.argv.index("--ask")
        q = " ".join(sys.argv[i + 1:]) or "help"
        ans = answer(q) or "(no answer)"
        # readable in a terminal
        print(re.sub(r"<[^>]+>", "", ans))
        return
    if "--post" in sys.argv:
        post_now()
        return

    print("STAALWAG posting manager up.")
    # scheduler in a background thread; Q&A long-poll on the main thread
    threading.Thread(target=scheduler_loop, daemon=True, name="posting_sched").start()
    if QA_ENABLED:
        qa_loop()
    else:
        # posting-only mode: keep the process alive for the scheduler thread
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
