"""Per-variant × per-exit-policy heatmap and deep features analysis.

For every (variant, exit_policy) combination, measure win rate, avg net,
total PnL, sharpe-like ratio, and trade count. This tells us which
algorithms have the raw edge before we add filtering.
"""
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev

SHADOW = Path("/home/ec2-user/phase3_intrabar/artifacts/shadow_trades.jsonl")


def load(delay_filter=250):
    """Load shadow trades, keeping one record per (coin, ts, variant, policy).

    Prefer delay_ms closest to delay_filter. Default 250ms matches live latency.
    """
    best = {}
    with SHADOW.open() as f:
        for line in f:
            r = json.loads(line)
            k = (r.get("coin"), r.get("entry_ts_ns"), r.get("variant"), r.get("exit_policy"))
            dist = abs((r.get("delay_ms") or 0) - delay_filter)
            prev = best.get(k)
            if prev is None or dist < prev[0]:
                best[k] = (dist, r)
    return [v[1] for v in best.values()]


def stats(rows, label=""):
    if not rows:
        return None
    n = len(rows)
    net = [r["net_pct"] for r in rows]
    wins = [x for x in net if x > 0]
    avg = mean(net)
    s = stdev(net) if n > 1 else 0.0
    sharpe = avg / s if s > 0 else 0.0
    return {
        "label": label,
        "n": n,
        "wr": len(wins) / n,
        "avg": avg,
        "total": sum(net),
        "sharpe": sharpe,
        "max": max(net),
        "min": min(net),
    }


def fmt(s):
    if not s:
        return "(empty)"
    return (f"  n={s['n']:>6}  wr={s['wr']*100:5.1f}%  avg={s['avg']*100:+6.2f}%"
            f"  sum={s['total']*100:+8.1f}%  sharpe={s['sharpe']:+5.2f}"
            f"  max={s['max']*100:+.1f}%  min={s['min']*100:+.1f}%")


def main():
    rows = load(delay_filter=250)
    print(f"Loaded {len(rows):,} records (one per (coin,ts,variant,policy) at ~250ms)")

    # By exit policy (across all variants)
    print("\n=== By exit policy (all variants pooled) ===")
    by_policy = defaultdict(list)
    for r in rows:
        by_policy[r["exit_policy"]].append(r)
    for pol in sorted(by_policy, key=lambda p: -sum(x["net_pct"] for x in by_policy[p])):
        print(f"{pol:>22}")
        print(fmt(stats(by_policy[pol])))

    # By variant (across all policies)
    print("\n=== By variant (all policies pooled) ===")
    by_var = defaultdict(list)
    for r in rows:
        by_var[r["variant"]].append(r)
    for v in sorted(by_var, key=lambda x: -sum(r["net_pct"] for r in by_var[x])):
        print(f"{v:>22}")
        print(fmt(stats(by_var[v])))

    # Variant × policy heatmap — top 25 by total PnL
    print("\n=== Top 25 (variant × exit_policy) by total PnL ===")
    combos = defaultdict(list)
    for r in rows:
        combos[(r["variant"], r["exit_policy"])].append(r)

    scored = []
    for (v, p), lst in combos.items():
        if len(lst) < 20:
            continue
        s = stats(lst)
        scored.append((v, p, s))

    scored.sort(key=lambda x: -x[2]["total"])
    for v, p, s in scored[:25]:
        print(f"{v:>22} × {p:>18}")
        print(fmt(s))

    print("\n=== Worst 10 (variant × exit_policy) by total PnL ===")
    for v, p, s in scored[-10:]:
        print(f"{v:>22} × {p:>18}")
        print(fmt(s))


if __name__ == "__main__":
    main()
