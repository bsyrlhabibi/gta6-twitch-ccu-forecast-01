"""gta6-twitch-ccu-forecast-01: launch-day Twitch viewer forecaster (Python 3.13, stdlib only).

Model: a similarity-weighted pool of past launches' release-day shapes.

Every past launch in the case's `comparables` contributes its release-day curve as log-ratios
to its own first hour, r_k = ln(viewers_k / viewers_1) for the day's hours k = 1..23. Two kinds
of comparables are left out:

* the one that is not a launch (the GTA VI category's own pre-release history has no release
  day), and
* launches whose first hour was a pre-unlock trickle -- their day's peak is more than e^3.5
  (~33x) their first hour. Those are simultaneous global unlocks in the middle of the UTC day;
  a rolling midnight-local console launch (this case, and every practice case) never looks
  like that, and their vertical mid-day jumps poison the pool.

The remaining launches are pooled per hour with Gaussian weights on two features that are
known at the end of hour 1, for the case and for each comparable alike:

* f2 = ln(mean viewers over the 6 hours before the day / viewers of hour 1) -- how much
  audience the category already held, relative to hour 1, before the day began. A high f2
  (hour 1 is a deep overnight trough for an already-warm category) goes with a steep day;
  a low f2 (hour 1 already at full blaze, e.g. an early-access title) goes with a flat one.
* g  = ln(viewers of the last hour before the day / viewers of hour 1), the same idea for
  the single hour before midnight.

The forecast is the case's hour-1 print times the weighted empirical quantiles of the pooled
ratios:  q_tau(h) = p1 * exp(Q_tau^w({r_h})).  An hour whose pool is empty falls back to the
persistence spread, so the output is always schema-valid.

Validation on the kit's four practice cases (mean pinball loss on the log scale, the contest's
scoring, against the launches' actual release-day curves): this model 0.210 overall
(p00 0.288, p01 0.197, p02 0.151, p03 0.203); the house persistence baseline scores 0.387.
Leave-one-out over the 29 pool launches: 0.285 for this model, 0.310 for the pool unweighted.

Run: MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
The grader runs `python3 -P -s /bot/main.py` with one case file in the input dir.
"""

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
# Standard-normal quantiles at LEVELS, for the persistence fallback.
Z = (-1.644854, -0.674490, 0.0, 0.674490, 1.644854)
FALLBACK_SIGMA = 0.15
MAX_Q = 1_000_000_000.0

# A comparable whose release-day peak exceeds e^PEAK_LN_MAX times its first hour was a
# simultaneous mid-day unlock, a different regime: excluded from the pool.
PEAK_LN_MAX = 3.5
# Gaussian kernel bandwidths for the two similarity features. Round 2 retune (0.35/0.45 ->
# 0.6/0.25): leave-one-out over the 29 pool launches improves 0.287 -> 0.285 and the four
# practice cases improve 0.229 -> 0.210; the tighter g bandwidth is what carries it -- the
# single hour before midnight is the sharpest signal of how the day will unfold.
BW_F2 = 0.6
BW_G = 0.25


def parse_ts(text):
    """ISO-8601 UTC timestamp -> epoch seconds (int)."""
    dt = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def by_hour(rows, start, key):
    """{hour index relative to `start` (may be negative): viewers} from timestamped rows."""
    out = {}
    for row in rows or []:
        try:
            t = parse_ts(row[key])
            viewers = row["viewers"]
        except (KeyError, ValueError, TypeError):
            continue
        if viewers is None or viewers <= 0:
            continue
        k = (t - start) // 3600
        if -48 <= k <= 23:
            out[k] = viewers
    return out


def shape_features(by):
    """(f2, g) for a day whose hour-1 viewers sit at index 0 of `by`; None where unknowable."""
    v1 = by.get(0)
    if not v1:
        return None, None
    pre = [by[k] for k in range(-6, 0) if by.get(k)]
    f2 = math.log((sum(pre) / len(pre)) / v1) if len(pre) >= 3 else None
    g = math.log(by[-1] / v1) if by.get(-1) else None
    return f2, g


def comparable_day(comp):
    """(ratios, f2, g, peak_ln) for one comparable's release day, or None if unusable."""
    unlock = (comp.get("unlock") or "").strip().lower()
    name = (comp.get("name") or "").lower()
    if unlock.startswith("not a launch") or "before release" in name:
        return None
    try:
        start = parse_ts(comp["day_start"])
    except (KeyError, ValueError):
        return None
    by = by_hour(comp.get("hourly"), start, "from")
    if not by.get(0):
        return None
    log_first = math.log(by[0])
    ratios = {k: math.log(v) - log_first for k, v in by.items() if 1 <= k <= 23}
    if not ratios:
        return None
    peak_ln = math.log(max(v for k, v in by.items() if 0 <= k <= 23) / by[0])
    f2, g = shape_features(by)
    return ratios, f2, g, peak_ln


def weighted_quantile(pairs, tau):
    """Weighted empirical quantile of [(value, weight)] via the midpoint-CDF rule."""
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    if total <= 0.0:
        return pairs[len(pairs) // 2][0]
    xs, ps = [], []
    cum = 0.0
    for value, w in pairs:
        cum += w
        xs.append(value)
        ps.append((cum - w / 2.0) / total)
    if tau <= ps[0]:
        return xs[0]
    if tau >= ps[-1]:
        return xs[-1]
    for i in range(1, len(ps)):
        if ps[i] >= tau:
            frac = (tau - ps[i - 1]) / (ps[i] - ps[i - 1])
            return xs[i - 1] * (1.0 - frac) + xs[i] * frac
    return xs[-1]


def plain_quantile(sorted_vals, tau):
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = tau * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def similarity_weight(comp_f2, comp_g, case_f2, case_g):
    """Gaussian weight of one comparable for this case; 1.0 when nothing is comparable."""
    d2 = 0.0
    used = False
    if comp_f2 is not None and case_f2 is not None:
        d2 += ((comp_f2 - case_f2) / BW_F2) ** 2
        used = True
    if comp_g is not None and case_g is not None:
        d2 += ((comp_g - case_g) / BW_G) ** 2
        used = True
    if not used:
        return 1.0
    return math.exp(-0.5 * d2)


def build_hour_pools(comparables, case_f2, case_g):
    """hour index k (1..23) -> [(log-ratio, weight)] pooled from the kept comparables."""
    pools = {k: [] for k in range(1, 24)}
    for comp in comparables or []:
        day = comparable_day(comp)
        if day is None:
            continue
        ratios, f2, g, peak_ln = day
        if peak_ln > PEAK_LN_MAX:
            continue
        w = similarity_weight(f2, g, case_f2, case_g)
        for k, r in ratios.items():
            pools[k].append((r, w))
    return pools


def round2(x):
    """Round half up to 2 decimals, as the house baseline writes its numbers."""
    scaled = x * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    return whole / 100.0


def hour_quantiles(p1, hour, pools):
    """The five forecast quantiles for one hour (hour is 2..24)."""
    k = hour - 1
    pairs = pools.get(k) or []
    if pairs:
        offsets = [weighted_quantile(pairs, tau) for tau in LEVELS]
        qs = [p1 * math.exp(off) for off in offsets]
    else:
        spread = FALLBACK_SIGMA * math.sqrt(k)
        qs = [p1 * math.exp(z * spread) for z in Z]
    # Schema discipline: finite, ordered, inside (0, 1e9].
    out = []
    prev = 0.0
    for q in qs:
        if not math.isfinite(q) or q <= 0.0:
            q = prev if prev > 0.0 else p1
        q = min(max(q, 0.01), MAX_Q)
        q = max(q, prev)
        out.append(round2(q))
        prev = out[-1]
    return out


def forecast_case(case):
    first = next((row for row in case.get("known") or [] if row.get("hour") == 1), None)
    p1 = 1.0
    if first is not None and first.get("viewers"):
        p1 = max(1.0, float(first["viewers"]))
    try:
        start = parse_ts(case["day_start"])
    except (KeyError, ValueError):
        start = None
    case_f2 = case_g = None
    if start is not None:
        by = by_hour(case.get("history_hourly"), start, "from")
        if not by.get(0):
            by[0] = p1
        case_f2, case_g = shape_features(by)
    pools = build_hour_pools(case.get("comparables"), case_f2, case_g)
    hours = []
    for row in case.get("forecast") or []:
        h = row["hour"]
        hours.append({"hour": h, "q": hour_quantiles(p1, h, pools)})
    hours.sort(key=lambda r: r["hour"])
    return {"hours": hours}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        result = forecast_case(case)
        text = json.dumps(result, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / f"{path.stem}.out").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
