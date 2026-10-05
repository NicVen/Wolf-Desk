"""Guardian watcher: reads a linked MT5 account and warns on Telegram.

Every few seconds it asks MetaApi (read-only, investor password) for the open
trades and pending orders. Each NEW one is judged with guardian/rules.py,
using the broker's own figures (equity, $ per tick for that symbol, the other
open trades), and a NO or CAREFUL goes straight to Telegram with the reasons.
It never places, changes or closes anything; it only reads.

Settings: /etc/guardian.env (deploy/guardian-setup.sh writes it).
  METAAPI_TOKEN, METAAPI_ACCOUNT    the MetaApi token and account id
  METAAPI_REGION                    optional, found automatically
  GUARDIAN_BOT_TOKEN, GUARDIAN_CHAT  where warnings go
  RISK_PCT=1                         the trader's risk per trade plan
  CHALLENGE_START, DAILY_PCT, MAX_PCT  optional prop-firm limits
  STATE_FILE, HOURS_FILE, CALENDAR_URL

Run:  python -m guardian.watch
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from guardian import rules

PROV = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai"
CLIENT = "https://mt-client-api-v1.{region}.agiliumtrade.ai"
POLL = int(os.environ.get("POLL_SECONDS", "10"))


def env(k, d=""):
    return os.environ.get(k, d).strip()


def http_json(url, token=None, data=None, timeout=20):
    hdr = {"Accept": "application/json", "User-Agent": "staalwag-guardian"}
    if token:
        hdr["auth-token"] = token
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        hdr["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=hdr, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


class MetaApi:
    """The few read-only MetaApi calls Guardian needs."""

    def __init__(self, token, account, region="", get=http_json):
        self.token, self.account, self.get = token, account, get
        self.region = region or self._region()
        self.base = CLIENT.format(region=self.region) + "/users/current/accounts/" + account
        self._spec = {}

    def _region(self):
        try:
            return self.get(PROV + "/users/current/accounts/" + self.account, self.token).get("region") or "new-york"
        except Exception:
            return "new-york"

    def _q(self, path):
        return self.get(self.base + path, self.token)

    def info(self):
        return self._q("/account-information")

    def positions(self):
        return self._q("/positions") or []

    def orders(self):
        return self._q("/orders") or []

    def per_lot(self, symbol, distance):
        """Account-currency loss on 1.00 lot over a price `distance`."""
        q = urllib.parse.quote(symbol, safe="")
        spec = self._spec.get(symbol)
        if spec is None:
            spec = self._spec[symbol] = self._q("/symbols/%s/specification" % q)
        price = self._q("/symbols/%s/current-price" % q)
        tick = float(spec.get("tickSize") or 0)
        tv = float(price.get("lossTickValue") or price.get("profitTickValue") or 0)
        if tick <= 0 or tv <= 0:
            return None
        return distance / tick * tv


def describe(item):
    """BUY/SELL from a MetaApi position or order type."""
    t = str(item.get("type", ""))
    side = "BUY" if "BUY" in t else "SELL" if "SELL" in t else ""
    for kind in ("STOP_LIMIT", "LIMIT", "STOP"):
        if t.endswith("_" + kind):
            return "%s %s order" % (side, kind.replace("_", " ").lower())
    return side


def risk_of(api, item):
    """$ lost on this trade if its stop is hit; None when it has no stop."""
    sl, op = item.get("stopLoss"), item.get("openPrice")
    if not sl or not op:
        return None, None
    dist = abs(float(op) - float(sl))
    pl = api.per_lot(item["symbol"], dist)
    return (None if pl is None else pl * float(item.get("volume") or 0)), dist


def judge(api, item, others, equity, settings, now, events, hours_for):
    """Rules verdict for one new trade/order, with the rest of the book as context."""
    open_risk, naked = 0.0, 0
    for o in others:
        r, _ = risk_of(api, o)
        if r is None:
            naked += 1
        else:
            open_risk += r
    risk, dist = risk_of(api, item)
    vol = float(item.get("volume") or 0)
    trade = {"sym": item["symbol"], "lots": vol, "stop": dist or 0,
             "per_lot": (risk / vol) if (risk is not None and vol) else None}
    account = {"equity": equity, "risk_pct": settings["risk_pct"], "open_trades": len(others),
               "open_risk": open_risk, "open_no_stop": naked, "challenge": settings.get("challenge")}
    return rules.check(trade, account, now=now, events=events, hours=hours_for(item["symbol"]))


ICON = {"NO": "⛔", "CAREFUL": "⚠️", "OK": "✅"}
HEAD = {"NO": "NO. Sit this out.", "CAREFUL": "Careful.", "OK": "You're good."}


def message(item, verdict):
    lines = ["🛡️ <b>GUARDIAN</b> · %s <b>%s</b>" % (ICON[verdict["verdict"]], HEAD[verdict["verdict"]]),
             "%s %s %g lots" % (_esc(item["symbol"]), describe(item), float(item.get("volume") or 0)), ""]
    order = {"NO": 0, "CAREFUL": 1, "OK": 2}
    for c in sorted(verdict["checks"], key=lambda c: order[c["level"]]):
        if c["level"] != "OK":
            lines.append("%s <b>%s</b>: %s" % (ICON[c["level"]], _esc(c["title"]), _esc(c["text"])))
    lines += ["", "<i>Your call. Guardian only watches, it never touches your trades.</i>"]
    return "\n".join(lines)


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send(bot, chat, text):
    url = "https://api.telegram.org/bot%s/sendMessage" % bot
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    urllib.request.urlopen(url, data=data, timeout=15).read()


class Watcher:
    def __init__(self, api, settings, notify, state_file, events=lambda: [], hours=lambda sym: None):
        self.api, self.settings, self.notify = api, settings, notify
        self.state_file, self.events, self.hours = state_file, events, hours
        try:
            with open(state_file) as f:
                self.state = json.load(f)
        except Exception:
            self.state = {}
        self.first = "seen" not in self.state
        self.state.setdefault("seen", [])

    def _save(self):
        tmp = self.state_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f)
        os.replace(tmp, self.state_file)

    def tick(self, now=None):
        """One look at the account. Returns the warnings sent."""
        now = now or datetime.now(timezone.utc)
        info = self.api.info() or {}
        equity = float(info.get("equity") or info.get("balance") or 0)
        day = now.strftime("%Y-%m-%d")
        if self.state.get("day") != day:              # the trading day's starting equity
            self.state["day"], self.state["day_start"] = day, equity
        settings = dict(self.settings)
        ch = settings.get("challenge")
        if ch and ch.get("on"):
            settings["challenge"] = dict(ch, today_pl=equity - float(self.state.get("day_start") or equity))
        book = [dict(p, _kind="pos") for p in self.api.positions()] + [dict(o, _kind="ord") for o in self.api.orders()]
        # MT5 gives a filled pending order's position the order's ticket, so
        # one ticket = one warning, whether it was an order first or not.
        ids = [str(b.get("id")) for b in book]
        seen = set(self.state["seen"])
        sent = []
        if not self.first:
            evs = None
            for b, i in zip(book, ids):
                if i in seen:
                    continue
                if evs is None:
                    evs = self.events()
                others = [x for x in book if x is not b and x["_kind"] == "pos"]
                v = judge(self.api, b, others, equity, settings, now, evs, self.hours)
                if v.get("error"):
                    continue
                if v["verdict"] != "OK" or self.settings.get("send_ok"):
                    try:
                        self.notify(message(b, v))
                        sent.append(v)
                    except Exception as e:
                        print("guardian: telegram failed:", e, flush=True)
        self.first = False
        self.state["seen"] = ids                      # closed trades drop out; a reused id is new again
        self._save()
        return sent


def _settings():
    ch = None
    if env("CHALLENGE_START"):
        ch = {"on": True, "start": float(env("CHALLENGE_START")),
              "daily_pct": float(env("DAILY_PCT", "5")), "max_pct": float(env("MAX_PCT", "10"))}
    return {"risk_pct": float(env("RISK_PCT", "1")), "challenge": ch, "send_ok": env("SEND_OK") == "1"}


def _calendar():
    url = env("CALENDAR_URL", "http://127.0.0.1:8777/calendar")
    try:
        return http_json(url, timeout=30).get("events", [])
    except Exception as e:
        print("guardian: calendar unavailable:", e, flush=True)
        return []


def _hours(symbol):
    yahoo = rules.meta(symbol)[2]
    if not yahoo:
        return None
    try:
        with open(env("HOURS_FILE", "data/prime_hours.json")) as f:
            return json.load(f).get("symbols", {}).get(yahoo)
    except Exception:
        return None


def main():
    token, account = env("METAAPI_TOKEN"), env("METAAPI_ACCOUNT")
    bot, chat = env("GUARDIAN_BOT_TOKEN"), env("GUARDIAN_CHAT")
    if not (token and account and bot and chat):
        sys.exit("guardian: set METAAPI_TOKEN, METAAPI_ACCOUNT, GUARDIAN_BOT_TOKEN, GUARDIAN_CHAT")
    api = MetaApi(token, account, env("METAAPI_REGION"))
    w = Watcher(api, _settings(), lambda t: send(bot, chat, t),
                env("STATE_FILE", "/var/lib/guardian/state.json"), _calendar, _hours)
    print("guardian: watching account %s (%s), every %ss" % (account, api.region, POLL), flush=True)
    fails = 0
    while True:
        try:
            for v in w.tick():
                print("guardian: sent", v["verdict"], flush=True)
            fails = 0
        except Exception as e:
            fails += 1
            print("guardian: poll failed:", e, flush=True)
            if fails == 30:                           # ~5 min of failures: say so once
                try:
                    send(bot, chat, "🛡️ Guardian can't reach your MT5 account right now. "
                                    "Warnings are paused until it reconnects.")
                except Exception:
                    pass
        time.sleep(POLL if fails < 30 else 60)


if __name__ == "__main__":
    main()
