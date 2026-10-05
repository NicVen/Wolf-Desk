"""Guardian rules: should this trade be taken right now?

Given a trade (symbol, lots, stop), the account (equity, planned risk, open
trades, optional prop-firm challenge limits), the economic calendar and the
symbol's Prime Hours profile, return a verdict:

    NO       sit this out
    CAREFUL  allowed, but something is off
    OK       nothing wrong found

with a plain-English reason for every check. Pure, deterministic maths: no AI,
no network. The same rules will judge trades read from a linked MT5 account.
"""
from datetime import datetime, timezone

# code: (name, contract size, point size, how $ per lot is worked out,
#        stop unit, news currencies, Yahoo ticker for Prime Hours)
# "usd"    quote currency is USD: loss = stop * point * contract
# "base"   USD is the base (USDJPY): divide by the current price
# "custom" the trader gives their broker's $ per point per lot
SYMS = {
    "XAUUSD": ("Gold", 100, 1, "usd", "$", ("USD",), "GC=F"),
    "XAGUSD": ("Silver", 5000, 1, "usd", "$", ("USD",), "SI=F"),
    "EURUSD": ("EURUSD", 100000, 0.0001, "usd", "pips", ("EUR", "USD"), "EURUSD=X"),
    "GBPUSD": ("GBPUSD", 100000, 0.0001, "usd", "pips", ("GBP", "USD"), "GBPUSD=X"),
    "AUDUSD": ("AUDUSD", 100000, 0.0001, "usd", "pips", ("AUD", "USD"), "AUDUSD=X"),
    "NZDUSD": ("NZDUSD", 100000, 0.0001, "usd", "pips", ("NZD", "USD"), "NZDUSD=X"),
    "USDJPY": ("USDJPY", 100000, 0.01, "base", "pips", ("USD", "JPY"), "USDJPY=X"),
    "USDCAD": ("USDCAD", 100000, 0.0001, "base", "pips", ("USD", "CAD"), "USDCAD=X"),
    "USDCHF": ("USDCHF", 100000, 0.0001, "base", "pips", ("USD", "CHF"), "USDCHF=X"),
    "BTCUSD": ("Bitcoin", 1, 1, "usd", "$", ("USD",), "BTC-USD"),
    "OTHER": ("This symbol", 1, 1, "custom", "points", ("USD",), None),
}
CRYPTO = {"BTCUSD"}

# Broker symbols seen on a linked MT5 account (any symbol, any suffix).
_CCY = ("USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF")
_INDEX = {
    "USD": ("NAS100", "USTEC", "US100", "NDX", "US30", "DJ30", "WS30", "US500", "SPX500", "SP500", "US2000"),
    "EUR": ("GER40", "DE40", "DAX40", "GER30", "DE30", "EU50", "EUSTX50", "STOXX50", "FRA40"),
    "GBP": ("UK100", "FTSE100"),
    "JPY": ("JP225", "JPN225", "NIKKEI"),
    "AUD": ("AUS200",),
}
_YAHOO = {
    "XAUUSD": "GC=F", "GOLD": "GC=F", "XAGUSD": "SI=F", "SILVER": "SI=F",
    "NAS100": "^NDX", "USTEC": "^NDX", "US100": "^NDX", "NDX": "^NDX",
    "US30": "^DJI", "DJ30": "^DJI", "WS30": "^DJI", "US500": "^GSPC", "SPX500": "^GSPC", "SP500": "^GSPC",
    "US2000": "^RUT", "GER40": "^GDAXI", "DE40": "^GDAXI", "DAX40": "^GDAXI", "GER30": "^GDAXI",
    "EU50": "^STOXX50E", "EUSTX50": "^STOXX50E", "UK100": "^FTSE", "JP225": "^N225", "JPN225": "^N225",
    "AUS200": "^AXJO", "USOIL": "CL=F", "XTIUSD": "CL=F", "WTI": "CL=F", "UKOIL": "BZ=F", "XBRUSD": "BZ=F",
    "XNGUSD": "NG=F", "NATGAS": "NG=F", "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD",
}


def base_symbol(sym):
    """'NAS100.cash', 'XAUUSDm', 'EURUSD+' -> the plain name."""
    s = "".join(ch for ch in str(sym).upper().split(".")[0] if ch.isalnum())
    for k in sorted(list(_YAHOO) + list(SYMS), key=len, reverse=True):
        if s.startswith(k):
            return k
    if len(s) >= 6 and s[:3] in _CCY and s[3:6] in _CCY:
        return s[:6]
    return s


def meta(sym):
    """(name, news currencies, Yahoo ticker or None, trades at weekends)."""
    b = base_symbol(sym)
    if b in SYMS and b != "OTHER":
        s = SYMS[b]
        return (s[0] if b in ("XAUUSD", "XAGUSD", "BTCUSD") else b), s[5], s[6], b in CRYPTO
    crypto = b.startswith(("BTC", "ETH", "SOL", "XRP", "LTC", "DOGE"))
    if len(b) == 6 and b[:3] in _CCY and b[3:] in _CCY:
        cur = (b[:3], b[3:])
        yahoo = _YAHOO.get(b, b + "=X")
    else:
        cur = next((tuple([c]) for c, names in _INDEX.items() if b in names), ("USD",))
        yahoo = _YAHOO.get(b)
    return b, cur, yahoo, crypto

NO, CAREFUL, OK = "NO", "CAREFUL", "OK"
_RANK = {OK: 0, CAREFUL: 1, NO: 2}

OVERSIZE = 1.5          # risk above 1.5x the plan = NO
HEAT_CAREFUL = 3.0      # % of equity at risk across all open trades
HEAT_NO = 6.0
BUSY = 5                # this many open trades already = CAREFUL
NEWS_NO_BEFORE = 30     # minutes before high-impact news = NO
NEWS_NO_AFTER = 15      # minutes after the release, the whipsaw = NO
NEWS_CAREFUL = 4 * 60   # high-impact news later in this window = CAREFUL
QUIET = 25              # hour scores below this (of 100) count as quiet


def _f(x):
    try:
        v = float(x)
        return v if v == v else None          # NaN -> None
    except (TypeError, ValueError):
        return None


def per_lot(sym, stop, price=None, per_point=None):
    """US dollars lost on 1.00 lot if the stop is hit, or None if unknown."""
    s = SYMS.get(sym)
    if not s or not stop or stop <= 0:
        return None
    if s[3] == "custom":
        return stop * per_point if per_point and per_point > 0 else None
    v = stop * s[2] * s[1]
    if s[3] == "base":
        if not price or price <= 0:
            return None
        v /= price
    return v


def _pct(v):
    return ("%.2f%%" if v < 1 else "%.1f%%") % v


def _money(v):
    return "${:,.2f}".format(v)


def _hm(minutes):
    minutes = int(round(minutes))
    if minutes < 60:
        return "%d min" % minutes
    return "%dh%02d" % (minutes // 60, minutes % 60)


def _in(w, h):
    if not w:
        return False
    s, e = w["start"], w["end"]
    return s <= h < e if s <= e else (h >= s or h < e)


def market_closed(sym, now):
    """FX/metals close Friday 21:00 UTC and reopen Sunday 22:00 UTC."""
    if meta(sym)[3]:
        return False
    wd, h = now.weekday(), now.hour
    return (wd == 4 and h >= 21) or wd == 5 or (wd == 6 and h < 22)


def check(trade, account, now=None, events=(), hours=None):
    """Judge one trade. Returns {"verdict", "checks": [...], "risk_usd",
    "risk_pct", "safe_lots"}; each check is {"kind", "level", "title", "text"}.

    From the app the symbol must be one of SYMS. A linked MT5 account passes
    any broker symbol with "per_lot" (the broker's own $ lost per lot at the
    stop) instead."""
    now = now or datetime.now(timezone.utc)
    sym = str(trade.get("sym") or "").upper()
    linked = "per_lot" in trade
    given = _f(trade.get("per_lot"))
    if sym not in SYMS and not linked:
        return {"error": "unknown symbol"}
    name, currencies = meta(sym)[:2]
    lots = _f(trade.get("lots"))
    stop = _f(trade.get("stop"))
    equity = _f(account.get("equity"))
    plan = _f(account.get("risk_pct")) or 1.0
    if not lots or lots <= 0 or not equity or equity <= 0:
        return {"error": "Fill in your account equity and the lot size."}

    out = []

    def add(kind, level, title, text):
        out.append({"kind": kind, "level": level, "title": title, "text": text})

    # --- size -------------------------------------------------------------
    risk = safe = pct = None
    pl = given if linked else per_lot(sym, stop, _f(trade.get("price")), _f(trade.get("per")))
    if not stop or stop <= 0:
        add("size", NO, "No stop loss",
            "Without a stop the worst case is your whole account. Set a stop first.")
    elif pl is None:
        add("size", CAREFUL, "Size not checked",
            ("Your broker didn't give the value of a price move for this symbol, so the risk couldn't be worked out."
             if linked else "Add the current price (or your broker's $ per point) so the risk can be worked out."))
    else:
        risk = lots * pl
        pct = risk / equity * 100
        safe = int(equity * plan / 100 / pl * 100 + 1e-9) / 100
        msg = "If the stop is hit you lose %s, %s of your account." % (_money(risk), _pct(pct))
        if pct > plan * OVERSIZE:
            add("size", NO, "Too big",
                "%s Your plan is %g%%: the safe size is %.2f lots." % (msg, plan, safe))
        elif pct > plan + 1e-9:
            add("size", CAREFUL, "Bigger than your plan",
                "%s Your plan is %g%%: %.2f lots keeps you on plan." % (msg, plan, safe))
        else:
            add("size", OK, "Size is on plan", msg)

    # --- open trades --------------------------------------------------------
    n_open = int(_f(account.get("open_trades")) or 0)
    open_risk = _f(account.get("open_risk")) or 0.0
    naked = int(_f(account.get("open_no_stop")) or 0)
    if naked:
        add("heat", NO, "Open trades without a stop",
            "%d of your open trades %s no stop. One bad move there can wipe the account, whatever this trade does."
            % (naked, "has" if naked == 1 else "have"))
    if n_open or open_risk:
        total = open_risk + (risk or 0)
        heat = total / equity * 100
        txt = ("Adding this to your %d open trade%s puts %s at risk if every stop is hit (%s of the account)."
               % (n_open, "" if n_open == 1 else "s", _money(total), _pct(heat)))
        if heat > HEAT_NO:
            add("heat", NO, "Too much on at once", txt + " Close or tighten something before adding more.")
        elif heat > HEAT_CAREFUL or n_open >= BUSY:
            add("heat", CAREFUL, "A lot on already", txt)
        elif not naked:                         # "fine" would contradict the no-stop warning
            add("heat", OK, "Open trades are fine", txt)

    # --- prop-firm challenge --------------------------------------------------
    ch = account.get("challenge") or {}
    if ch.get("on"):
        start = _f(ch.get("start")) or equity
        today = _f(ch.get("today_pl")) or 0.0
        daily = _f(ch.get("daily_pct"))
        maxl = _f(ch.get("max_pct"))
        rooms = []
        if "max_floor" in ch:                   # a firm preset: the floors are worked out already
            for k in ("daily_floor", "max_floor"):
                if _f(ch.get(k)) is not None:
                    rooms.append(equity - _f(ch[k]))
        if daily:
            rooms.append(start * daily / 100 + min(today, 0.0))
        if maxl:
            rooms.append(equity - start * (1 - maxl / 100))
        if rooms:
            room = min(rooms)
            at_stake = open_risk + (risk or 0)
            if room <= 0:
                add("challenge", NO, "Limit reached",
                    "You've used up your loss limit. Stop trading this account today.")
            elif at_stake >= room:
                add("challenge", NO, "This could fail your challenge",
                    "You have %s left before the firm's limit. If this and your open trades hit "
                    "their stops (%s), the challenge is over." % (_money(room), _money(at_stake)))
            elif at_stake > room / 2:
                add("challenge", CAREFUL, "Close to the limit",
                    "This uses over half of the %s you have left before the firm's limit." % _money(room))
            else:
                add("challenge", OK, "Inside the firm's limits",
                    "%s left before the limit." % _money(room))

    # --- news -------------------------------------------------------------
    cur = set(currencies)
    soon = None
    for e in events or ():
        ts = e.get("ts")
        if ts is None or str(e.get("impact", "")).lower() != "high" or e.get("currency") not in cur:
            continue
        mins = (ts - now.timestamp()) / 60
        if -NEWS_NO_AFTER <= mins <= NEWS_NO_BEFORE:
            label = "%s %s" % (e["currency"], e.get("title", "news"))
            add("news", NO, "Big news now",
                ("%s is out in %s." % (label, _hm(mins)) if mins > 0 else
                 "%s just came out. Let the whipsaw settle first." % label))
            soon = None
            break
        if 0 < mins <= NEWS_CAREFUL and (soon is None or mins < soon[0]):
            soon = (mins, e)
    else:
        if soon:
            m, e = soon
            add("news", CAREFUL, "News later",
                "%s %s is out in %s. Will your stop survive the spike?" % (e["currency"], e.get("title", ""), _hm(m)))
        elif events:
            add("news", OK, "No big news", "No high-impact %s news in the next 4 hours." % "/".join(currencies))
        else:
            add("news", OK, "News not checked", "The news calendar didn't load. Check it yourself before you trade.")

    # --- time ---------------------------------------------------------------
    h = now.hour
    if market_closed(sym, now):
        add("time", NO, "Market closed", "%s is closed for the weekend. Prices and spreads are not real until it reopens." % name)
    elif hours and hours.get("hours"):
        score = hours["hours"][h]
        if _in(hours.get("dead"), h):
            add("time", CAREFUL, "Dead zone",
                "This is the quietest time of day for %s. Moves are small and spreads are wider." % name)
        elif _in(hours.get("prime"), h):
            add("time", OK, "Prime window", "%s moves most at this time of day." % name)
        elif score < QUIET:
            add("time", CAREFUL, "Quiet hour", "%s barely moves at this time of day." % name)
        else:
            add("time", OK, "Good time", "%s is active at this time of day." % name)

    verdict = max((c["level"] for c in out), key=_RANK.get, default=OK)
    return {"verdict": verdict, "checks": out, "risk_usd": risk, "risk_pct": pct, "safe_lots": safe}


def parse_event_time(s):
    """Calendar time ("2026-10-05T08:30:00-04:00") -> unix seconds, or None."""
    try:
        return datetime.fromisoformat(s).timestamp()
    except (TypeError, ValueError):
        return None
