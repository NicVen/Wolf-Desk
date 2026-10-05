"""Prop-firm challenge rules, so the trader picks their firm and challenge
from a list instead of typing limits in.

Each preset says how the firm measures its two loss limits:

  daily basis   what today's loss limit is counted down from
    balance            the balance at the start of the firm's day
    equity             the equity at the start of the day
    equity_or_balance  whichever of the two was higher
  max type      where the overall loss floor sits
    static             start size minus max %, never moves
    trailing           the highest equity minus max %, keeps rising
    trailing_lock      as trailing, but stops rising once it reaches the start size
    eod_trailing       the highest start-of-day balance minus max %

The % is always of the account's start size (that is how these firms word it).
Guardian follows the stricter reading when a firm is vague: a trailing floor
trails equity, not only closed balance.

Rules as published by each firm, checked 2026-10-05. Firms change them; a
preset marked check=True had conflicting or partial sources, and the app tells
the trader to confirm it on their firm's dashboard. Pure data and maths: no
network, no AI.
"""

CHECKED = "2026-10-05"
SIZES = (5000, 10000, 25000, 50000, 100000, 200000)

# id: (firm, program, daily %, daily basis, max %, max type, targets, sizes, check, source)
_B, _E, _EB = "balance", "equity", "equity_or_balance"
_S, _T, _TL, _EOD = "static", "trailing", "trailing_lock", "eod_trailing"
_SZ8 = (5000, 10000, 15000, 25000, 50000, 100000, 200000, 400000)
PRESETS = {
    "ftmo-2": ("FTMO", "2-Step Challenge", 5, _B, 10, _S, (10, 5), (10000, 25000, 50000, 100000, 200000), False,
               "https://ftmo.com/en/trading-objectives/"),
    "ftmo-1": ("FTMO", "1-Step Challenge", 3, _B, 10, _EOD, (10,), (10000, 25000, 50000, 100000, 200000), False,
               "https://ftmo.com/en/1-step-challenge/"),
    "fxify-1": ("FXIFY", "One Phase", 3, _B, 6, _TL, (10,), _SZ8, False,
                "https://fxify.com/faqs/all-faqs/how-do-you-calculate-the-max-trailing-drawdown/"),
    "fxify-2c": ("FXIFY", "Two Phase Classic", 4, _B, 10, _S, (10, 5), _SZ8, False,
                 "https://fxify.com/faqs/all-faqs/what-are-the-rules-for-the-assessment-account/"),
    "fxify-2s": ("FXIFY", "Two Phase Standard", 4, _B, 10, _TL, (10, 5), _SZ8, True,
                 "https://fxify.com/faqs/all-faqs/how-do-you-calculate-the-max-trailing-drawdown/"),
    # loss limits confirmed on a live FXIFY account (2026-10-05); targets as FXIFY's launch post words them
    "fxify-2p": ("FXIFY", "Two Phase Pro", 4, _B, 8, _S, (4, 8), SIZES, False,
                 "https://fxify.com/blog/introducing-fxify-2-phase-pro/"),
    "fxify-3": ("FXIFY", "Three Phase", 5, _B, 5, _S, (5, 5, 5), _SZ8, True,
                "https://fxify.com/faqs/all-faqs/what-are-the-rules-for-the-assessment-account/"),
    "fxify-l": ("FXIFY", "Lightning Challenge", 3, _B, 4, _T, (5,), SIZES, True,
                "https://fxify.com/programs/lightning-challenge/"),
    "fxify-if": ("FXIFY", "Instant Funding Standard", None, None, 8, _TL, (), (1000, 5000, 10000, 25000, 50000, 100000), False,
                 "https://fxify.com/blog/prop-firms-with-instant-funding/"),
    "fxify-il": ("FXIFY", "Instant Funding Lite", 3, _B, 4, _T, (), (2500, 5000, 10000, 25000, 50000), False,
                 "https://fxify.com/faqs/all-faqs/instant-funding-lite-how-does-the-max-trailing-drawdown-work-how-does-the-payout-affect-it/"),
    "fn-2": ("FundedNext", "Stellar 2-Step", 5, _B, 10, _S, (8, 5), (6000, 15000, 25000, 50000, 100000, 200000), False,
             "https://help.fundednext.com/en/articles/8019811-how-can-i-calculate-the-daily-loss-limit"),
    "fn-1": ("FundedNext", "Stellar 1-Step", 3, _B, 6, _S, (10,), (6000, 15000, 25000, 50000, 100000, 200000), False,
             "https://help.fundednext.com/en/articles/8019914-what-is-the-maximum-daily-loss-limit"),
    "fn-lite": ("FundedNext", "Stellar Lite", 4, _B, 8, _S, (8, 4), SIZES, False,
                "https://help.fundednext.com/en/articles/17253939-stellar-lite-account"),
    "fn-inst": ("FundedNext", "Stellar Instant", None, None, 6, _T, (), SIZES, True,
                "https://help.fundednext.com/en/articles/17253243-stellar-instant-account"),
    "5ers-hs": ("The5ers", "High Stakes (2-Step)", 5, _EB, 10, _S, (8, 5), (2500, 5000, 10000, 25000, 50000, 100000), True,
                "https://help.the5ers.com/what-is-the-drawdown-rule-for-high-stakes/"),
    "5ers-hg": ("The5ers", "Hyper Growth", 3, _EB, 6, _S, (10,), (5000, 10000, 20000), False,
                "https://the5ers.com/hyper-growth/"),
    "5ers-pg": ("The5ers", "Pro Growth", 3, _EB, 6, _S, (10,), SIZES, True,
                "https://the5ers.com/challenge-programs-bootcamp-high-stakes-hyper-growth-explained/"),
    "5ers-bc": ("The5ers", "Bootcamp (3-Step)", 3, _B, 5, _S, (6, 6, 6), (20000, 100000, 250000), True,
                "https://the5ers.com/bootcamp/"),
    "fp-2s": ("Funding Pips", "2-Step Standard", 5, _EB, 10, _S, (8, 5), (5000, 10000, 25000, 50000, 100000), False,
              "https://help.fundingpips.com/hc/en-us/articles/34501809112081-2-Step-Standard"),
    "fp-2p": ("Funding Pips", "2-Step Pro", 3, _EB, 6, _S, (6, 6), (5000, 10000, 25000, 50000, 100000, 200000), False,
              "https://help.fundingpips.com/hc/en-us/articles/34502027344017-2-Step-Pro-Model"),
    "fp-2f": ("Funding Pips", "2-Step Flex", 4, _EB, 12, _S, (10, 6), (5000, 10000, 25000, 50000, 100000), False,
              "https://help.fundingpips.com/hc/en-us/articles/47835196271249-2-Step-Flex"),
    "fp-1f": ("Funding Pips", "1-Step Flex", 3, _EB, 6, _S, (10,), (5000, 10000, 25000, 50000, 100000), True,
              "https://help.fundingpips.com/hc/en-us/articles/34501697434385-1-Step-Flex"),
    "fp-zero": ("Funding Pips", "Zero (instant)", 3, _EB, 5, _T, (), SIZES, True,
                "https://help.fundingpips.com/hc/en-us/articles/34502157694865-FundingPips-Zero"),
    "e8-one": ("E8 Markets", "E8 One (default)", 3, _B, 4, _TL, (6,), (5000, 10000, 25000, 50000, 100000, 200000, 500000), False,
               "https://help.e8markets.com/en/articles/11775980-e8-one"),
    "e8-sig": ("E8 Markets", "E8 Signature (Forex)", None, None, 4, _EOD, (6,), (25000, 50000), True,
               "https://help.e8markets.com/en/articles/11755943-e8-signature-forex"),
    "e8-pro": ("E8 Markets", "E8 Pro (Forex)", 2.5, _B, 8, _S, (8,), SIZES, True,
               "https://help.e8markets.com/en/articles/15274219-e8-pro"),
    "acg-1-6": ("Alpha Capital", "Alpha One 6%", 3, _EB, 4, _T, (6,), SIZES, False,
                "https://help.alphacapitalgroup.uk/en/articles/10097421-alpha-one"),
    "acg-1-10": ("Alpha Capital", "Alpha One 10%", 4, _EB, 6, _T, (10,), SIZES, False,
                 "https://help.alphacapitalgroup.uk/en/articles/10097421-alpha-one"),
    "acg-1-12": ("Alpha Capital", "Alpha One 12%", 5, _EB, 8, _T, (12,), SIZES, True,
                 "https://help.alphacapitalgroup.uk/en/articles/10097421-alpha-one"),
    "acg-p6": ("Alpha Capital", "Alpha Pro 6%", 3, _EB, 6, _S, (6, 6), SIZES, False,
               "https://help.alphacapitalgroup.uk/en/articles/6934210-what-are-the-daily-risk-limits-and-how-do-they-work"),
    "acg-p8": ("Alpha Capital", "Alpha Pro 8%", 4, _B, 8, _S, (8, 5), SIZES, False,
               "https://help.alphacapitalgroup.uk/en/articles/8420429-alpha-pro-8-10"),
    "acg-p10": ("Alpha Capital", "Alpha Pro 10%", 5, _B, 10, _S, (10, 5), SIZES, False,
                "https://help.alphacapitalgroup.uk/en/articles/8420429-alpha-pro-8-10"),
    "acg-sw": ("Alpha Capital", "Alpha Swing", 5, _B, 10, _S, (10, 5), SIZES, False,
               "https://help.alphacapitalgroup.uk/en/articles/9789907-alpha-swing"),
    "acg-3": ("Alpha Capital", "Alpha Three", 4, _B, 6, _S, (8, 4, 4), SIZES, True,
              "https://help.alphacapitalgroup.uk/en/articles/10192958-alpha-three"),
    "bg-2": ("Blue Guardian", "2 Step Standard", 4, _EB, 8, _S, (8, 4), SIZES, False,
             "https://help.blueguardian.com/en/articles/14062291-2-step-standard-rules"),
    "bg-1": ("Blue Guardian", "1 Step Standard", 4, _EB, 6, _TL, (9,), (5000, 10000, 25000, 50000, 100000, 150000, 200000), False,
             "https://help.blueguardian.com/en/articles/14062186-1-step-standard-rules"),
    "bg-inst": ("Blue Guardian", "Instant Standard", 3, _EB, 6, _T, (), SIZES, True,
                "https://help.blueguardian.com/en/articles/14061082-instant-standard-account-rules"),
    "maven-2": ("Maven Trading", "2-Step", 4, _EB, 8, _S, (8, 5), (2000, 5000, 10000, 20000, 50000, 100000), False,
                "https://maventrading.com/challenges/2-step"),
    "maven-1": ("Maven Trading", "1-Step", 3, _EB, 5, _T, (8,), (2000, 5000, 10000, 20000, 50000, 100000), False,
                "https://maventrading.com/faqs"),
    "maven-3": ("Maven Trading", "3-Step", 2, _EB, 3, _S, (3, 3, 3), (2000, 5000, 10000, 20000, 50000, 100000), True,
                "https://maventrading.com/pricing"),
    "maven-inst": ("Maven Trading", "Instant", 2, _EB, 3, _T, (), (2000, 5000, 10000, 20000, 50000, 100000), True,
                   "https://maventrading.com/challenges/instant"),
    "ftp-1": ("Funded Trading Plus", "1-Step Express", 4, _B, 6, _TL, (10,), (10000, 25000, 50000, 100000, 200000), False,
              "https://www.fundedtradingplus.com/prop-trading-challenges/one-step"),
    "ftp-2": ("Funded Trading Plus", "2-Step Classic", 4, _B, 8, _S, (7, 7), SIZES, True,
              "https://help.fundedtradingplus.com/2-step-classic-program-information/"),
    "ftp-inst": ("Funded Trading Plus", "Instant Funding", 6, _B, 6, _T, (), SIZES, True,
                 "https://help.fundedtradingplus.com/instant-program-information/"),
    "if-1": ("Instant Funding", "One-Phase Challenge", 3, _EB, 8, _S, (10,), (5000, 10000, 25000, 50000, 100000), False,
             "https://instantfunding.com/help/one-phase/"),
    "if-2": ("Instant Funding", "Two-Phase Challenge", 5, _EB, 10, _S, (8, 5), (5000, 10000, 25000, 50000, 100000), False,
             "https://instantfunding.com/help/two-phase/"),
    "goat-2g": ("Goat Funded Trader", "2-Step GOAT", 4, _EB, 10, _S, (8, 6), SIZES, False,
                "https://help.goatfundedtrader.com/en/articles/13575348-2-step-goat-model"),
    "goat-2s": ("Goat Funded Trader", "2-Step Standard", 5, _EB, 10, _S, (10, 5), SIZES, False,
                "https://help.goatfundedtrader.com/en/articles/13575169-2-step-standard"),
    "goat-2p": ("Goat Funded Trader", "2-Step PRO", 4, _EB, 8, _S, (8, 4), SIZES, True,
                "https://help.goatfundedtrader.com/en/articles/13778401-2-step-pro-model"),
    "goat-1": ("Goat Funded Trader", "1-Step", 3, _EB, 6, _S, (10,), (15000, 25000, 50000, 100000, 200000), False,
               "https://help.goatfundedtrader.com/en/articles/10630134-1-step-model"),
    "goat-3": ("Goat Funded Trader", "3-Step", 4, _EB, 8, _S, (6, 6, 6), SIZES, True,
               "https://help.goatfundedtrader.com/en/articles/10630343-3-step-model"),
    "goat-inst": ("Goat Funded Trader", "Instant GOAT", 3, _EB, 6, _T, (), (5000, 10000, 25000, 50000, 100000, 200000, 400000), True,
                  "https://help.goatfundedtrader.com/en/articles/13574117-instant-funding-goat-model"),
    "aqua-1s": ("Aqua Funded", "1 Step Standard", 3, _EB, 6, _T, (9,), SIZES, False,
                "https://help.aquafunded.com/en/articles/15281183-1-step-standard"),
    "aqua-1f": ("Aqua Funded", "1 Step Flex", 3, _EB, 12, _S, (), SIZES, True,
                "https://help.aquafunded.com/en/articles/10476451-1-step-flex"),
    "aqua-2s": ("Aqua Funded", "2 Step Standard", 5, _B, 8, _S, (8, 5), SIZES, True,
                "https://help.aquafunded.com/en/articles/15281226-2-step-standard"),
    "aqua-2p": ("Aqua Funded", "2 Step Pro", 5, _EB, 10, _T, (10,), SIZES, True,
                "https://help.aquafunded.com/en/articles/15281229-2-step-pro"),
    "aqua-2e": ("Aqua Funded", "2 Step Elite", 4, _B, 10, _S, (8, 5), SIZES, True,
                "https://help.aquafunded.com/en/articles/15281231-2-step-elite"),
    "aqua-3": ("Aqua Funded", "3 Step", 4, _B, 8, _S, (6, 6), SIZES, True,
               "https://help.aquafunded.com/en/articles/10476458-3-step-model"),
    "bf-2c": ("BrightFunded", "2-Step Classic", 5, _EB, 10, _S, (10, 5), SIZES, False,
              "https://brightfunded.com/2-step-classic"),
    "bf-2b": ("BrightFunded", "2-Step Bright", 4, _EB, 8, _S, (8, 5), SIZES, False,
              "https://brightfunded.com/2-step-bright"),
    "bf-1": ("BrightFunded", "1-Step", 3, _EB, 6, _TL, (10,), SIZES, True,
             "https://help.brightfunded.com/en/articles/14284743-brightfunded-1-step"),
    "ft-1p": ("FundingTraders", "1-Step Pro", 3, _E, 10, _T, (10,), SIZES, False,
              "https://fundingtraders.com/help/en/articles/13615032-1-step-pro"),
    "ft-2p6": ("FundingTraders", "2-Step Pro6", 3, _B, 6, _S, (6, 6), SIZES, False,
               "https://fundingtraders.com/help/en/articles/13399206-2-step-pro"),
    "ft-2p10": ("FundingTraders", "2-Step Pro10", 5, _B, 10, _S, (10, 5), SIZES, False,
                "https://fundingtraders.com/help/en/articles/13399206-2-step-pro"),
}

_BASIS = {_B: "start-of-day balance", _E: "start-of-day equity", _EB: "start-of-day balance or equity, whichever is higher"}
_MAXT = {_S: "fixed at the start size", _T: "trails your highest equity",
         _TL: "trails your highest equity until it reaches the start size, then stays",
         _EOD: "trails your highest end-of-day balance"}


def get(pid):
    """The preset as a dict, or None."""
    p = PRESETS.get(pid)
    if not p:
        return None
    firm, prog, daily, basis, mx, mtype, targets, sizes, check, src = p
    return {"id": pid, "firm": firm, "program": prog, "daily_pct": daily, "daily_basis": basis,
            "max_pct": mx, "max_type": mtype, "targets": list(targets), "sizes": list(sizes),
            "check": check, "source": src}


def listing():
    """Every preset, grouped by firm in a stable order, for the app's dropdown."""
    out = [get(k) for k in PRESETS]
    for p in out:
        p["summary"] = summary(p)
    return {"checked": CHECKED, "presets": out}


def summary(p, size=None):
    """One plain line: the firm's two limits in % (and $ when the size is known)."""
    def amt(pct):
        return " ($%s)" % format(int(round(size * pct / 100)), ",") if size else ""
    parts = []
    if p["daily_pct"]:
        parts.append("Daily loss %g%%%s from your %s" % (p["daily_pct"], amt(p["daily_pct"]), _BASIS[p["daily_basis"]]))
    else:
        parts.append("No daily loss limit")
    parts.append("max loss %g%%%s, %s" % (p["max_pct"], amt(p["max_pct"]), _MAXT[p["max_type"]]))
    if p["targets"]:
        parts.append("target " + " / ".join("%g%%" % t for t in p["targets"]))
    return ". ".join(s[0].upper() + s[1:] for s in parts) + "."


def floors(p, size, st):
    """The two equity levels the account must stay above, from the preset,
    the start size and the tracked state:
        st = {"day_bal", "day_eq", "peak_eq", "peak_day_bal"}
    Returns (daily_floor or None, max_floor)."""
    size = float(size)
    daily = None
    if p["daily_pct"]:
        db, de = float(st.get("day_bal") or size), float(st.get("day_eq") or st.get("day_bal") or size)
        base = {_B: db, _E: de, _EB: max(db, de)}.get(p["daily_basis"], db)
        daily = base - size * p["daily_pct"] / 100
    cut = size * p["max_pct"] / 100
    static = size - cut
    t = p["max_type"]
    if t == _S:
        mx = static
    elif t == _EOD:
        mx = max(static, float(st.get("peak_day_bal") or size) - cut)
    else:
        mx = max(static, float(st.get("peak_eq") or size) - cut)
        if t == _TL:
            mx = min(mx, size)
    return daily, mx
