"""Observable Markov regime from a price series.

Labels each bar Bull / Bear / Sideways by its rolling return, builds a
transition matrix (stride-sampled to avoid the fake persistence overlapping
windows create), and reports the current state plus its stickiness — the
probability the regime stays put next step.

Sample-size discipline
----------------------
The transition matrix is only as trustworthy as the number of stride-sampled
points (``n``) behind it. Two gates make that explicit instead of trusting a
persistence figure built on a handful of samples:

  MIN_N_VOTE  (8)   below this the regime is too thinly sampled to count in the
                    market-wide majority vote — ``market_read`` drops it.
  MIN_N_TRUST (15)  at/above this the persistence estimate is treated as solid
                    ("high"); between the two the regime still votes but is
                    flagged ("medium").

Every regime therefore carries a ``confidence`` label ("high"/"medium"/"low")
and a ``vote`` flag, so the market read, the daily post, and any client can
suppress or downgrade thin signals rather than showing them as if solid.

Honest by construction: no forecasting claims beyond the matrix, and the
threshold / window / sample-size gates are all explicit.
"""
from __future__ import annotations

BULL, BEAR, SIDE = "BULL", "BEAR", "SIDE"

# Sample-size gates on the transition matrix (count of stride-sampled points).
MIN_N_VOTE = 8    # fewer sampled points than this: excluded from the market vote
MIN_N_TRUST = 15  # at/above this: persistence treated as high-confidence


def _label(r: float, thr: float) -> str:
    if r > thr:
        return BULL
    if r < -thr:
        return BEAR
    return SIDE


def _confidence(n: int) -> str:
    if n >= MIN_N_TRUST:
        return "high"
    if n >= MIN_N_VOTE:
        return "medium"
    return "low"


def _result(state, persist, nxt, n: int) -> dict:
    """Uniform regime dict with derived confidence + vote gate."""
    return {"state": state, "persist": persist, "next": nxt, "n": n,
            "confidence": _confidence(n),
            "vote": bool(state) and n >= MIN_N_VOTE}


def regime(closes: list[float], window: int = 20, thr: float = 0.005,
           stride: int | None = None) -> dict:
    """closes: oldest->newest. Returns
    {state, persist, next, n, confidence, vote}."""
    stride = stride or window
    if not closes or len(closes) < window + stride * 2:
        return _result(None, None, None, 0)

    # per-bar regime labels from rolling return
    labels = []
    for i in range(window, len(closes)):
        base = closes[i - window]
        if base <= 0:
            continue
        labels.append(_label(closes[i] / base - 1.0, thr))
    if len(labels) < stride * 2:
        return _result(labels[-1] if labels else None, None, None, 0)

    # stride-sample so overlapping windows don't manufacture persistence
    sampled = labels[::stride]
    states = (BULL, BEAR, SIDE)
    trans = {a: {b: 0 for b in states} for a in states}
    for a, b in zip(sampled[:-1], sampled[1:]):
        trans[a][b] += 1

    current = labels[-1]
    n = len(sampled)
    row = trans[current]
    total = sum(row.values())
    if total == 0:
        # current state only ever appears as the final sample — no observed
        # transition out of it, so persistence is unknown (but state stands).
        return _result(current, None, None, n)
    persist = round(row[current] / total, 2)
    nxt = max(states, key=lambda s: row[s])
    return _result(current, persist, nxt, n)


def market_read(regimes: list[dict]) -> dict:
    """Aggregate several asset regimes into one market state (majority vote).

    Only regimes that clear the sample-size gate are counted, so a handful of
    thin reads can't swing the market call. Honors each regime's ``vote`` flag
    when present, and falls back to the ``n`` threshold for older payloads that
    predate the flag. ``counted`` reports how many regimes actually voted.
    """
    votes = {BULL: 0, BEAR: 0, SIDE: 0}
    counted = 0
    for r in regimes:
        s = r.get("state")
        if s not in votes:
            continue
        can_vote = r.get("vote")
        if can_vote is None:                      # older payload: derive from n
            can_vote = (r.get("n") or 0) >= MIN_N_VOTE
        if not can_vote:
            continue
        votes[s] += 1
        counted += 1
    if counted == 0:
        return {"state": None, "votes": votes, "counted": 0}
    state = max(votes, key=votes.get)
    return {"state": state, "votes": votes, "counted": counted}
