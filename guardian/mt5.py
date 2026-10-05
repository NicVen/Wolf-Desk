"""Guardian for the MT5 EA (guardian/ea/Guardian.mq5).

The EA runs inside the trader's own MT5, so no password ever leaves their PC.
It sees each new trade, measures it with the broker's own tick value and
posts it here. The answer is plain text so the EA can read it without a JSON
parser:

    line 1   NO | CAREFUL | OK | ERROR
    line 2   the phone push (MT5 caps these at 255 characters)
    line 3+  one line per reason, for the pop-up on the PC
"""
from guardian import rules

PUSH_MAX = 255
ICON = {"NO": "⛔", "CAREFUL": "⚠️", "OK": "✅"}
HEAD = {"NO": "NO. Sit this out.", "CAREFUL": "Careful.", "OK": "You're good."}


def _dict(x):
    return x if isinstance(x, dict) else {}


def answer(body, events=(), hours_for=lambda sym: None, now=None):
    """Judge the EA's trade; returns the plain-text reply described above."""
    trade, account = _dict(body.get("trade")), _dict(body.get("account"))
    sym = str(trade.get("sym") or "")
    if not sym:
        return "ERROR\nGuardian: no symbol sent."
    t = {"sym": sym, "lots": trade.get("lots"), "stop": trade.get("stop") or 0,
         "per_lot": trade.get("per_lot")}
    acc = {k: account.get(k) for k in ("equity", "risk_pct", "open_trades", "open_risk", "open_no_stop")}
    ch = _dict(account.get("challenge"))
    if ch.get("on"):
        acc["challenge"] = ch
    v = rules.check(t, acc, now=now, events=events, hours=hours_for(sym))
    if v.get("error"):
        return "ERROR\nGuardian: " + v["error"]
    order = {"NO": 0, "CAREFUL": 1, "OK": 2}
    bad = sorted((c for c in v["checks"] if c["level"] != "OK"), key=lambda c: order[c["level"]])
    what = "%s %s %g lots" % (sym, str(trade.get("side") or "").upper(), float(trade.get("lots") or 0))
    what = " ".join(what.split())
    head = "%s GUARDIAN %s %s" % (ICON[v["verdict"]], HEAD[v["verdict"]], what)
    push = head
    for i, c in enumerate(bad):
        part = (" %s: %s" % (c["title"], c["text"])) if i == 0 else (" | " + c["title"])
        if len(push) + len(part) > PUSH_MAX:
            break
        push += part
    lines = ["%s %s: %s" % (ICON[c["level"]], c["title"], c["text"]) for c in bad]
    return "\n".join([v["verdict"], push[:PUSH_MAX]] + lines)
