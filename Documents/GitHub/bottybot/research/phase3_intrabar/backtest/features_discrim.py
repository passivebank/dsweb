"""Find features that discriminate winners from losers within each variant.

For each variant, for the best-performing exit policy (or r5_v10), binarize
feature values and compute win rate / PnL lift above vs below threshold.
Surface features with strong discrimination power.
"""
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

SHADOW = Path("/home/ec2-user/phase3_intrabar/artifacts/shadow_trades.jsonl")

# Best exit policy per variant (from heatmap.py, positive or least-negative)
VARIANT_POLICY = {
    "R8_HIGH_CONVICTION": "time_120s",  # +2.77%
    "R5_CONFIRMED_RUN":   "time_300s",  # +0.06%
    "R7_STAIRCASE":       "time_300s",  # -0.05%
    "R3_DV_EXPLOSION":    "r5_v10",     # -0.48%
    "R6_LOCAL_BREAKOUT":  "r5_v10",     # +0.43%
    "R4_POST_RUN_HOLD":   "wide_trail_30m",
    "R1_TAPE_BURST":      "r5_v10",
}


def load_variant(variant, policy, delay_target=250):
    rows = {}
    with SHADOW.open() as f:
        for line in f:
            r = json.loads(line)
            if r.get("variant") != variant or r.get("exit_policy") != policy:
                continue
            k = (r.get("coin"), r.get("entry_ts_ns"))
            dist = abs((r.get("delay_ms") or 0) - delay_target)
            prev = rows.get(k)
            if prev is None or dist < prev[0]:
                rows[k] = (dist, r)
    return [v[1] for v in rows.values()]


def feature_lift(rows, feature, thresholds=None):
    """For a feature, compute PnL and WR above/below various thresholds."""
    vals = []
    for r in rows:
        f = r.get("sig_features") or {}
        v = f.get(feature)
        if v is None or isinstance(v, bool):
            continue
        try:
            vals.append((float(v), r["net_pct"]))
        except Exception:
            pass

    if len(vals) < 30:
        return None

    xs = sorted(v[0] for v in vals)
    if thresholds is None:
        # Use deciles
        thresholds = [xs[int(len(xs) * q)] for q in (0.1, 0.25, 0.5, 0.75, 0.9)]

    results = []
    for t in thresholds:
        above = [v[1] for v in vals if v[0] > t]
        below = [v[1] for v in vals if v[0] <= t]
        if len(above) < 15 or len(below) < 15:
            continue
        above_wr  = sum(1 for x in above if x > 0) / len(above)
        below_wr  = sum(1 for x in below if x > 0) / len(below)
        above_avg = mean(above)
        below_avg = mean(below)
        results.append({
            "threshold": t,
            "n_above": len(above), "wr_above": above_wr, "avg_above": above_avg,
            "n_below": len(below), "wr_below": below_wr, "avg_below": below_avg,
            "lift_avg": above_avg - below_avg,
        })
    return results


def main():
    for variant, policy in VARIANT_POLICY.items():
        rows = load_variant(variant, policy)
        if len(rows) < 30:
            continue
        net = [r["net_pct"] for r in rows]
        base_wr = sum(1 for n in net if n > 0) / len(net)
        base_avg = mean(net)
        print(f"\n{'='*78}")
        print(f"{variant} × {policy}   n={len(rows)}  "
              f"base WR={base_wr*100:.1f}%  base avg={base_avg*100:+.2f}%")
        print("="*78)

        # Collect all features seen
        all_features = set()
        for r in rows:
            all_features.update((r.get("sig_features") or {}).keys())

        # Score each feature by its max lift at any threshold
        ranked = []
        for feat in sorted(all_features):
            res = feature_lift(rows, feat)
            if not res:
                continue
            best = max(res, key=lambda x: x["lift_avg"])
            worst = min(res, key=lambda x: x["lift_avg"])
            lift = max(abs(best["lift_avg"]), abs(worst["lift_avg"]))
            ranked.append((lift, feat, res, best, worst))

        ranked.sort(reverse=True)
        print(f"\n  Top 10 discriminating features:")
        for lift, feat, res, best, worst in ranked[:10]:
            b = best if abs(best["lift_avg"]) >= abs(worst["lift_avg"]) else worst
            print(f"  {feat:22s}  thresh={b['threshold']:>10.4f}")
            print(f"    ABOVE: n={b['n_above']:>4}  wr={b['wr_above']*100:5.1f}%  avg={b['avg_above']*100:+6.2f}%")
            print(f"    BELOW: n={b['n_below']:>4}  wr={b['wr_below']*100:5.1f}%  avg={b['avg_below']*100:+6.2f}%")
            print(f"    LIFT:  {b['lift_avg']*100:+.2f}%")


if __name__ == "__main__":
    main()
