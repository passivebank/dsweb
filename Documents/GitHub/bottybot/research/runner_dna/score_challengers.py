"""
research/runner_dna/score_challengers.py — score every registered filter
against the most recent shadow data.

Run on a schedule (every 4 hours via systemd timer). Outputs:
  - artifacts/challenger_scores.json — current scores for each filter,
    consumed by auto_promote.py
  - artifacts/challenger_scores_history.jsonl — append-only history

Scoring window: trailing N days of shadow_trades.jsonl (default 7).
For each filter, simulates trade-by-trade compounding with stressed
costs (+24bps over modeled), enforces daily kill switch and per-coin
loss limit. Reports walk-forward stats per filter:
  - n_trades, n_days, win_rate
  - mean_net_pct, median_net_pct
  - total_return_pct (compounded), max_drawdown_pct
  - daily_sharpe
  - bootstrap 95% CI on mean_net_pct
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from research.runner_dna.registry import REGISTRY

SHADOW_PATH    = Path(os.environ.get(
    "SHADOW_TRADES_PATH",
    "/home/ec2-user/phase3_intrabar/artifacts/shadow_trades.jsonl",
))
SCORES_PATH    = Path(os.environ.get(
    "CHALLENGER_SCORES_PATH",
    "/home/ec2-user/phase3_intrabar/artifacts/challenger_scores.json",
))
HISTORY_PATH   = SCORES_PATH.with_name("challenger_scores_history.jsonl")

EXTRA_COST     = 0.0024            # +24bps stress on top of modeled cost
POS_PCT        = 0.10
KILL_SWITCH    = -0.05
MAX_LOSSES     = 2

VARIANT_EXIT = {
    "R7_STAIRCASE": "time_300s", "R8_HIGH_CONVICTION": "time_300s",
    "R5_CONFIRMED_RUN": "std_trail", "R10_EXPLOSION_ONSET": "std_trail",
    "R11_BIG_STAIRCASE": "time_300s", "R3_DV_EXPLOSION": "time_300s",
    "R4_POST_RUN_HOLD": "std_trail", "R6_LOCAL_BREAKOUT": "time_300s",
}
APPROVED_VARIANTS = {"R7_STAIRCASE", "R8_HIGH_CONVICTION", "R10_EXPLOSION_ONSET"}


def load_shadow_recent(window_days: int) -> list[dict]:
    """Load shadow trades from the last `window_days`."""
    cutoff_ns = int((datetime.now(timezone.utc) - timedelta(days=window_days)).timestamp() * 1e9)
    rows = []
    with SHADOW_PATH.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            ts = r.get("entry_ts_ns") or r.get("sig_ts_ns")
            if ts and int(ts) >= cutoff_ns:
                rows.append(r)
    return rows


def select_for_filter(rows: list[dict], filter_fn) -> list[dict]:
    """Apply variant whitelist + named filter; pick preferred exit policy
    per signal moment. Mirrors evaluate_candidate.simulate."""
    groups = defaultdict(list)
    for r in rows:
        coin = r.get("coin")
        ts   = r.get("entry_ts_ns") or r.get("sig_ts_ns")
        if coin and ts:
            groups[(coin, int(ts))].append(r)

    selected = []
    for key, group_rows in groups.items():
        merged = {}
        for r in group_rows:
            for k, v in (r.get("sig_features") or {}).items():
                if v is not None:
                    merged[k] = v
        spread = group_rows[0].get("spread_bps_at_entry")
        if spread is not None and "spread_bps_at_entry" not in merged:
            merged["spread_bps_at_entry"] = spread
        for r in group_rows:
            v = r.get("variant", "")
            if v not in APPROVED_VARIANTS:
                continue
            if not filter_fn(merged, v):
                continue
            preferred = VARIANT_EXIT.get(v, "std_trail")
            same = [x for x in group_rows if x.get("variant") == v]
            match = next((x for x in same if x.get("exit_policy") == preferred), None)
            if match is None and same:
                match = sorted(same, key=lambda x: -(x.get("net_pct") or -1e9))[0]
            if match and match.get("net_pct") is not None:
                selected.append(match)
                break
    selected.sort(key=lambda r: r["entry_ts_ns"])
    return selected


def simulate_compound(trades: list[dict]) -> dict:
    """Compound bankroll trade-by-trade, enforce daily kill+per-coin loss."""
    bankroll = 1.0
    daily_returns = []
    cur_day = None
    day_start = 1.0
    losses_today: dict = defaultdict(int)
    killed = False
    nets = []
    n_executed = 0

    for t in trades:
        dt = datetime.fromtimestamp(t["entry_ts_ns"]/1e9, tz=timezone.utc).date().isoformat()
        if dt != cur_day:
            if cur_day is not None:
                daily_returns.append((cur_day, bankroll / day_start - 1))
            cur_day = dt
            day_start = bankroll
            losses_today.clear()
            killed = False
        if killed:
            continue
        if losses_today[t["coin"]] >= MAX_LOSSES:
            continue
        net = (t.get("net_pct") or 0.0) - EXTRA_COST
        bankroll *= (1 + POS_PCT * net)
        nets.append(net)
        n_executed += 1
        if net < 0:
            losses_today[t["coin"]] += 1
        if (bankroll / day_start - 1) <= KILL_SWITCH:
            killed = True
    if cur_day is not None:
        daily_returns.append((cur_day, bankroll / day_start - 1))

    if not nets:
        return {"n_trades": 0}

    daily_pnl = np.array([d[1] for d in daily_returns])
    nets_arr  = np.array(nets)

    # Bootstrap 95% CI on mean net
    rng = np.random.default_rng(42)
    boot_means = []
    for _ in range(500):
        idx = rng.integers(0, len(nets_arr), len(nets_arr))
        boot_means.append(float(nets_arr[idx].mean()))
    ci_lo, ci_hi = float(np.percentile(boot_means, 2.5)), float(np.percentile(boot_means, 97.5))

    # Drawdown
    cum = np.cumsum(daily_pnl)
    peaks = np.maximum.accumulate(np.concatenate([[0], cum]))
    dd = float((peaks[1:] - cum).max()) if len(cum) > 0 else 0.0

    sharpe = (
        float(np.mean(daily_pnl) / np.std(daily_pnl) * math.sqrt(365))
        if len(daily_pnl) > 1 and np.std(daily_pnl) > 0 else float("nan")
    )

    return {
        "n_trades":         n_executed,
        "n_days":           len(daily_returns),
        "win_rate":         float((nets_arr > 0).mean()),
        "mean_net_pct":     float(nets_arr.mean()),
        "median_net_pct":   float(np.median(nets_arr)),
        "mean_net_ci_lo":   ci_lo,
        "mean_net_ci_hi":   ci_hi,
        "total_return_pct": float((bankroll - 1) * 100),
        "max_drawdown_pct": float(dd * 100),
        "daily_sharpe":     sharpe,
    }


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--window-days", type=int, default=7)
    args = p.parse_args(argv[1:])

    if not SHADOW_PATH.exists():
        print(f"ERR: {SHADOW_PATH} missing", file=sys.stderr)
        return 1

    rows = load_shadow_recent(args.window_days)
    print(f"loaded {len(rows)} shadow trades from last {args.window_days} days")
    if not rows:
        print("no shadow data in window")
        return 0

    scored: dict = {}
    for name, (fn, desc) in REGISTRY.items():
        sel = select_for_filter(rows, fn)
        stats = simulate_compound(sel)
        stats["description"] = desc
        scored[name] = stats
        n = stats.get("n_trades", 0)
        if n:
            print(f"  {name:25s}  n={n:>3d}  WR={stats['win_rate']*100:>5.1f}%  "
                  f"mean={stats['mean_net_pct']*100:+5.2f}%  "
                  f"total={stats['total_return_pct']:+5.2f}%  "
                  f"DD={stats['max_drawdown_pct']:>4.1f}%")
        else:
            print(f"  {name:25s}  n=0")

    payload = {
        "scored_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window_days":   args.window_days,
        "shadow_rows":   len(rows),
        "scores":        scored,
    }
    SCORES_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCORES_PATH.write_text(json.dumps(payload, indent=2))
    with HISTORY_PATH.open("a") as f:
        f.write(json.dumps(payload, default=str) + "\n")
    print(f"\nwrote {SCORES_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
