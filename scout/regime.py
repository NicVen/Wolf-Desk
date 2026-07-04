"""Observable Markov regime from a price series.

Labels each bar Bull / Bear / Sideways by its rolling return, builds a
transition matrix (stride-sampled to avoid the fake persistence overlapping
windows create), and reports the current state plus its stickiness — the
probability the regime stays put next step.

Honest by construction: no forecasting claims beyond the matrix, and the
threshold/window are explicit. Used to add a regime line to the daily post.
"""
from __future__ import annotations

BULL, BEAR, SIDE = "BULL", "BEAR", "SIDE"


def _label(r: float, thr: float) -> str:
    if r > thr:
        return BULL
    if r < -thr:
        return BEAR
    return SIDE


def regime(closes: list[float], window: int = 20, thr: float = 0.005,
           stride: int | None = None) -> dict:
    """closes: oldest->newest. Returns {state, persist, next, n}."""
    stride = stride or window
    if not closes or len(closes) < window + stride * 2:
        return {"state": None, "persist": None, "next": None, "n": 0}

    # per-bar regime labels from rolling return
    labels = []
    for i in range(window, len(closes)):
        base = closes[i - window]
        if base <= 0:
            continue
        labels.append(_label(closes[i] / base - 1.0, thr))
    if len(labels) < stride * 2:
        return {"state": labels[-1] if labels else None, "persist": None,
                "next": None, "n": 0}

    # stride-sample so overlapping windows don't manufacture persistence
    sampled = labels[::stride]
    states = (BULL, BEAR, SIDE)
    trans = {a: {b: 0 for b in states} for a in states}
    for a, b in zip(sampled[:-1], sampled[1:]):
        trans[a][b] += 1

    current = labels[-1]
    row = trans[current]
    total = sum(row.values())
    if total == 0:
        return {"state": current, "persist": None, "next": None,
                "n": len(sampled)}
    persist = round(row[current] / total, 2)
    nxt = max(states, key=lambda s: row[s])
    return {"state": current, "persist": persist, "next": nxt,
            "n": len(sampled)}


def market_read(regimes: list[dict]) -> dict:
    """Aggregate several asset regimes into one market state (majority vote)."""
    votes = {BULL: 0, BEAR: 0, SIDE: 0}
    for r in regimes:
        s = r.get("state")
        if s in votes:
            votes[s] += 1
    if not any(votes.values()):
        return {"state": None, "votes": votes}
    state = max(votes, key=votes.get)
    return {"state": state, "votes": votes}
