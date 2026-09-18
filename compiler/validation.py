"""Statistical validation label for a signal — is the move real, or noise?

Ports the Deflated Sharpe Ratio (Bailey & Lopez de Prado), the same method EA
Forge uses to separate real edges from curve-fit luck. DSR = P(the true Sharpe
is above a benchmark Sharpe), where the benchmark grows with the number of
(effective, correlation-discounted) trials — so scanning ~44 markets and reading
the best one no longer masquerades as a proven edge.

Honest scope: this labels the instrument's OWN risk-adjusted drift, in the
signal's direction, over the sampled bars. It is a real-vs-noise tint on the
current move, NOT a backtest of a trading strategy, and intraday bars are
autocorrelated — so read it as a confidence tint, not proof. It is a LABEL only:
it never enters the 0-100 score or flips a verdict (same rule as news tilt).
"""
import math

_G = 0.5772156649015329   # Euler-Mascheroni


def _erf(x):
    t = 1.0 / (1.0 + 0.3275911 * abs(x))
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t
               - 0.284496736) * t + 0.254829592) * t * math.exp(-x * x)
    return y if x >= 0 else -y


def _ncdf(x):
    return 0.5 * (1.0 + _erf(x / math.sqrt(2.0)))


def _ninv(p):
    """Inverse standard-normal CDF (Acklam's approximation)."""
    p = min(1 - 1e-9, max(1e-9, p))
    a = [-39.6968302866538, 220.946098424521, -275.928510446969,
         138.357751867269, -30.6647980661472, 2.50662827745924]
    b = [-54.4760987982241, 161.585836858041, -155.698979859887,
         66.8013118877197, -13.2806815528857]
    c = [-7.78489400243029e-3, -0.322396458041136, -2.40075827716184,
         -2.54973253934373, 4.37466414146497, 2.93816398269878]
    d = [7.78469570904146e-3, 0.32246712907004, 2.445134137143, 3.75440866190742]
    pl = 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p <= 1 - pl:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)


def effective_trials(tested):
    """Independent trials from raw count. Correlated markets aren't independent
    bets, so discount with a sqrt law (clamped to [20, tested])."""
    t = max(1, int(tested or 0))
    return max(20, min(t, round(8 * math.sqrt(t))))


def deflated_sharpe(returns, n_trials, var_sr=None):
    n = len(returns)
    if n < 20:
        return {"dsr": 0.0, "sr": 0.0, "sr0": 0.0, "n": n}
    mean = sum(returns) / n
    sd = math.sqrt(sum((r - mean) ** 2 for r in returns) / n) or 1e-9
    sr = mean / sd
    s3 = s4 = 0.0
    for r in returns:
        z = (r - mean) / sd
        s3 += z ** 3
        s4 += z ** 4
    skew, kurt = s3 / n, s4 / n
    den = math.sqrt(max(1e-6, 1 - skew * sr + ((kurt - 1) / 4) * sr * sr))
    vsr = var_sr if (var_sr and var_sr > 0) else (den * den) / max(1, n - 1)
    N = max(2, n_trials)
    sr0 = math.sqrt(max(1e-8, vsr)) * ((1 - _G) * _ninv(1 - 1.0 / N)
                                       + _G * _ninv(1 - 1.0 / (N * math.e)))
    dsr = _ncdf(((sr - sr0) * math.sqrt(n - 1)) / den)
    return {"dsr": round(dsr, 3), "sr": round(sr, 4), "sr0": round(sr0, 4), "n": n}


def label(dsr):
    if dsr is None:
        return "n/a"
    if dsr >= 0.95:
        return "very likely real"
    if dsr >= 0.90:
        return "likely real"
    if dsr >= 0.75:
        return "unproven"
    return "indistinguishable from noise"


def validate(returns, side, n_trials):
    """returns: per-bar returns (oldest->newest). side: +1 long, -1 short, 0
    neutral. Returns {dsr, label, sr, n, trials}."""
    returns = returns or []
    if side == 0:
        return {"dsr": None, "label": "no directional edge", "sr": None,
                "n": len(returns), "trials": None}
    if len(returns) < 20:
        return {"dsr": None, "label": "too little data", "sr": None,
                "n": len(returns), "trials": None}
    trials = effective_trials(n_trials)
    ds = deflated_sharpe([side * r for r in returns], trials)
    return {"dsr": ds["dsr"], "label": label(ds["dsr"]), "sr": ds["sr"],
            "n": ds["n"], "trials": trials}
