"""Lightweight content screening for user-submitted suggestions.

Rejects profanity, slurs and insults before anything is stored or shown to the
admin. Deterministic wordlist + light obfuscation-normalisation (leetspeak,
symbol swaps, repeated letters). Returns (ok, reason); reason is a polite,
user-facing notice when rejected.

This is a first-line filter, not a guarantee — but it keeps the obvious abuse
out of the inbox.
"""
import re

# profanity / slurs / insults (kept blunt on purpose; word-boundary matched)
_BLOCK = {
    "fuck", "fucking", "fucker", "motherfucker", "shit", "bullshit", "bitch",
    "bastard", "asshole", "arsehole", "dick", "dickhead", "prick", "cunt",
    "wanker", "twat", "bollocks", "pussy", "cock", "slut", "whore", "faggot",
    "fag", "retard", "retarded", "nigger", "nigga", "spic", "chink", "kike",
    "coon", "idiot", "moron", "imbecile", "stupid", "dumbass", "jackass",
    "scam", "scammer", "fraud", "thief", "crook", "loser", "trash", "garbage",
    "useless", "pathetic", "clown", "clowns", "shitty", "crap", "crappy",
    "damn", "goddamn", "piss", "pissed", "screwed", "suck", "sucks", "sucker",
    "hate", "kill", "die", "shove", "stfu", "gtfo", "wtf",
}

# common obfuscation swaps so "sh1t", "f@ck", "a$$hole" still get caught
_SWAP = {"@": "a", "4": "a", "$": "s", "5": "s", "0": "o", "1": "i", "!": "i",
         "3": "e", "7": "t", "|": "i", "*": ""}


def _normalise(s):
    s = s.lower()
    s = "".join(_SWAP.get(ch, ch) for ch in s)
    s = re.sub(r"(.)\1{2,}", r"\1\1", s)      # collapse loooong repeats
    s = re.sub(r"[^a-z ]", " ", s)
    return s


# strong profanity roots — matched as substrings (catches plurals, spacing,
# "a$$holes", "f u c k"). Kept long enough to avoid innocent-word false hits.
_ROOTS = ("fuck", "shit", "cunt", "asshole", "arsehole", "bitch", "bastard",
          "nigger", "nigga", "faggot", "whore", "dickhead", "motherfuck",
          "wanker", "retard", "bollock", "wtf", "stfu")

_REJECT = ("Your suggestion couldn't be submitted because it contains "
           "language we don't allow. Please rephrase it respectfully and try "
           "again — we genuinely want your ideas.")


def screen(text):
    """(ok, reason). reason is a user-facing message when rejected."""
    t = (text or "").strip()
    if len(t) < 6:
        return False, "Please add a little more detail so we can act on it."
    if len(t) > 1000:
        return False, "That's a bit long — please keep it under 1000 characters."
    norm = _normalise(t)
    # word match (plus singular stem so plurals/verb forms are caught)
    words = set(norm.split())
    words |= {w[:-1] for w in words if len(w) > 4 and w.endswith("s")}
    words |= {w[:-3] for w in words if len(w) > 6 and w.endswith("ing")}
    if words & _BLOCK:
        return False, _REJECT
    # substring match against strong roots on the space-stripped text
    joined = norm.replace(" ", "")
    if any(root in joined for root in _ROOTS):
        return False, _REJECT
    # crude shouting/aggression check: mostly caps and long
    letters = [c for c in t if c.isalpha()]
    if len(letters) >= 15 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        return False, ("Please submit your suggestion in normal case (not all "
                       "capitals) and keep it civil, then try again.")
    return True, ""
