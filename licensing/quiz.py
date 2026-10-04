"""The Trader Quiz 'brain' — lives on the VPS.

Picks 5 questions per player per day (deterministic per key+day so a refresh
doesn't reshuffle), scores answers server-side (correct answers are NEVER sent
to the client before they submit), and exposes the community poll per question.

Question bank: quiz_bank.json (intermediate/advanced). Scoring/logging live in
store.py; monthly winners are decided from the accumulated scores.
"""
import hashlib
import json
import os
import random

_BANK = None
_BY_ID = None
DAILY = 5


def _load():
    global _BANK, _BY_ID
    if _BANK is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quiz_bank.json")
        with open(path) as f:
            _BANK = json.load(f)
        _BY_ID = {q["id"]: q for q in _BANK}
    return _BANK


def _seed(key, day):
    h = hashlib.sha256(("%s|%s" % (key, day)).encode()).hexdigest()
    return int(h[:12], 16)


def all_ids():
    _load()
    return [q["id"] for q in _BANK]


def pick_unseen(key, day, seen, n=DAILY):
    """Up to `n` question ids this player has NEVER been served before.
    Deterministic per key+day so the same GET/POST agree within a day."""
    ids = [i for i in all_ids() if i not in (seen or set())]
    random.Random(_seed(key, day)).shuffle(ids)
    return ids[:min(n, len(ids))]


def client_questions(qids):
    """Questions safe to send to the client — NO correct answer included."""
    _load()
    out = []
    for qid in qids:
        q = _BY_ID.get(qid)
        if not q:
            continue
        out.append({"id": q["id"], "level": q.get("level", ""),
                    "q": q["q"], "options": q["options"]})
    return out


def correct_index(qid):
    _load()
    q = _BY_ID.get(qid)
    return q["answer"] if q else None


def n_options(qid):
    _load()
    q = _BY_ID.get(qid)
    return len(q["options"]) if q else 0


def score_answers(qids, answers):
    """answers: {qid: chosen_index}. Returns (score, results) where results has,
    per question, the chosen + correct index (revealed AFTER submission)."""
    _load()
    score = 0
    results = []
    for qid in qids:
        q = _BY_ID.get(qid)
        if not q:
            continue
        chosen = answers.get(qid)
        try:
            chosen = int(chosen)
        except (TypeError, ValueError):
            chosen = -1
        ok = (chosen == q["answer"])
        if ok:
            score += 1
        results.append({"id": qid, "q": q["q"], "options": q["options"],
                        "chosen": chosen, "correct": q["answer"], "ok": ok})
    return score, results
