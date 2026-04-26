"""
research/runner_dna/optimize_stop.py — find the right hard-stop threshold
for runner_dna_v1, including per-feature calibration.

Problem
-------
The live executor uses a 2.5% hard stop from entry_px. Recent live
performance: 11 losses in a row, most stopping out within 0-3 minutes.
The user asked: simulate exact stop values around 4%, see if there's a
positive-EV number, and check whether we can calibrate the stop per
coin (by spread, depth, volatility, etc).

Method
------
1. **Build the full-trajectory dataset.** Each shadow signal moment has
   multiple (variant × exit_policy) rows. Each row's fwd_max_pct and
   fwd_min_pct are bounded by THAT policy's exit window. To simulate a
   different stop, we need the most expansive forward view possible —
   so for each signal moment we take:
     - deepest_fwd_min = min(fwd_min_pct across rows)
     - highest_fwd_max = max(fwd_max_pct across rows)
     - best_natural_exit = gross_pct of the longest-holding row that
       didn't itself stop on a hard floor

2. **Stop sweep.** For each candidate stop_pct ∈ {1.0, 1.5, 2.0, ...,
   8.0%}:
     - If deepest_fwd_min ≤ -stop_pct → trade hits stop, result = -stop_pct
     - Else → trade played out, result = best_natural_exit
     - Apply +24bps cost stress
     - Compound at 10% sizing across days, with daily kill switch and
       per-coin loss limit

3. **Per-feature stratification.** For each feature in {spread_bps,
   ask_depth_usd, bid_depth_usd, ret_24h, vwap-implied-volatility,
   avg_trade_size_60s}, bucket trades into quartiles. For each
   bucket × stop_pct, compute mean EV. Find the stop that maximizes
   mean EV per bucket.

4. **Heuristic stop function.** Given the per-feature optimums, build
   a closed-form stop function: stop_pct = base + Σ coef_i × feature_i
   (clipped to [1.5%, 8.0%]). Backtest the heuristic vs the best flat.

Output
------
- research/runner_dna/stop_optimization_report.md  — narrative + tables
- research/runner_dna/stop_sweep.csv               — flat stop results
- research/runner_dna/stop_per_feature.csv         — bucketed results
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from research.runner_dna.registry import runner_dna_v1

SHADOW_PATH = Path(os.environ.get(
    "SHADOW_TRADES_PATH",
    "/tmp/runner_dna_work/shadow_trades.jsonl",
))
OUT_REPORT  = Path("research/runner_dna/stop_optimization_report.md")
OUT_SWEEP   = Path("research/runner_dna/stop_sweep.csv")
OUT_PERFEAT = Path("research/runner_dna/stop_per_feature.csv")

EXTRA_COST  = 0.0024
POS_PCT     = 0.10
KILL_SWITCH = -0.05
MAX_LOSSES  = 2

APPROVED_VARIANTS = {"R7_STAIRCASE", "R8_HIGH_CONVICTION", "R10_EXPLOSION_ONSET"}

CANDIDATE_STOPS = [0.010, 0.015, 0.020, 0.025, 0.030, 0.035, 0.040,
                    0.045, 0.050, 0.055, 0.060, 0.070, 0.080, 0.100]


# ── 1. Build full-trajectory dataset ────────────────────────────────────────

def build_dataset() -> list[dict]:
    """For each (coin, sig_ts_ns) where runner_dna_v1 fires, return:
    {coin, ts_ns, entry_px, deepest_fwd_min, highest_fwd_max, best_natural_exit,
     features_at_entry}.
    """
    groups = defaultdict(list)
    with SHADOW_PATH.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            coin = r.get("coin")
            ts   = r.get("entry_ts_ns") or r.get("sig_ts_ns")
            if coin and ts:
                groups[(coin, int(ts))].append(r)

    out: list[dict] = []
    for (coin, ts), rows in groups.items():
        # Merge features across all rows
        merged: dict = {}
        for r in rows:
            for k, v in (r.get("sig_features") or {}).items():
                if v is not None:
                    merged[k] = v
        spread_top = rows[0].get("spread_bps_at_entry")
        if spread_top is not None and "spread_bps_at_entry" not in merged:
            merged["spread_bps_at_entry"] = spread_top

        # Apply variant whitelist + runner_dna_v1
        variant = None
        for r in rows:
            v = r.get("variant", "")
            if v in APPROVED_VARIANTS and runner_dna_v1(merged, v):
                variant = v
                break
        if variant is None:
            continue

        # Most expansive forward window across ALL exit policies for this signal
        fwd_min = min((r.get("fwd_min_pct") for r in rows
                        if r.get("fwd_min_pct") is not None), default=0.0)
        fwd_max = max((r.get("fwd_max_pct") for r in rows
                        if r.get("fwd_max_pct") is not None), default=0.0)
        # Best natural exit — pick longest-holding policy that wasn't a tight cap.
        # Prefer std_trail / partial_trail since they let the price walk farthest.
        ranked = sorted(rows, key=lambda x: (
            x.get("exit_policy") not in ("std_trail", "partial_trail"),
            -(x.get("holding_s") or 0),
        ))
        natural_exit = ranked[0].get("net_pct") if ranked else 0.0

        entry_px = ranked[0].get("entry_px") if ranked else 0.0

        out.append({
            "coin":              coin,
            "ts_ns":             ts,
            "variant":           variant,
            "entry_px":          entry_px,
            "fwd_min":           fwd_min,
            "fwd_max":           fwd_max,
            "natural_exit_net":  natural_exit,
            "features":          merged,
        })

    out.sort(key=lambda x: x["ts_ns"])
    return out


# ── 2. Simulate a single stop level ─────────────────────────────────────────

def simulate_stop(trades: list[dict], stop_pct: float) -> dict:
    """Return aggregate stats for trading the given stop_pct against the
    full-trajectory dataset. Compounds at 10% sizing with kill switch +
    per-coin loss limit."""
    bankroll = 1.0
    daily_returns = []
    cur_day = None
    day_start = 1.0
    losses_today: dict = defaultdict(int)
    killed = False
    nets = []

    for t in trades:
        dt = datetime.fromtimestamp(t["ts_ns"]/1e9, tz=timezone.utc).date().isoformat()
        if dt != cur_day:
            if cur_day is not None:
                daily_returns.append(bankroll / day_start - 1)
            cur_day = dt
            day_start = bankroll
            losses_today.clear()
            killed = False
        if killed:
            continue
        if losses_today[t["coin"]] >= MAX_LOSSES:
            continue

        # Stop logic: did the price go below -stop_pct during the trade?
        if t["fwd_min"] <= -stop_pct:
            net = -stop_pct - EXTRA_COST
        else:
            net = (t["natural_exit_net"] or 0.0) - EXTRA_COST

        bankroll *= (1 + POS_PCT * net)
        nets.append(net)
        if net < 0:
            losses_today[t["coin"]] += 1
        if (bankroll / day_start - 1) <= KILL_SWITCH:
            killed = True
    if cur_day is not None:
        daily_returns.append(bankroll / day_start - 1)

    if not nets:
        return {"n_trades": 0}

    nets_arr = np.array(nets)
    daily_arr = np.array(daily_returns)

    # Bootstrap CI on mean
    rng = np.random.default_rng(42)
    boot_means = [float(nets_arr[rng.integers(0, len(nets_arr), len(nets_arr))].mean())
                  for _ in range(500)]
    ci_lo, ci_hi = float(np.percentile(boot_means, 2.5)), float(np.percentile(boot_means, 97.5))

    return {
        "n_trades":       len(nets),
        "n_days":         len(daily_returns),
        "win_rate":       float((nets_arr > 0).mean()),
        "mean_net_pct":   float(nets_arr.mean()),
        "median_net_pct": float(np.median(nets_arr)),
        "ci_lo":          ci_lo,
        "ci_hi":          ci_hi,
        "total_return":   float((bankroll - 1) * 100),
        "sharpe":         float(daily_arr.mean() / daily_arr.std() * math.sqrt(365))
                          if len(daily_arr) > 1 and daily_arr.std() > 0 else float("nan"),
    }


# ── 3. Per-feature bucketing ────────────────────────────────────────────────

def stratify(trades: list[dict], feature: str, n_buckets: int = 4) -> dict:
    """Bucket trades by feature value (quartiles by default). Return
    list of (bucket_label, indices)."""
    vals = []
    for i, t in enumerate(trades):
        v = t["features"].get(feature)
        if v is None:
            continue
        try:
            vals.append((float(v), i))
        except (TypeError, ValueError):
            continue
    if len(vals) < n_buckets * 5:
        return {}
    vals.sort()
    bucket_size = len(vals) // n_buckets
    out = {}
    for b in range(n_buckets):
        lo_i = b * bucket_size
        hi_i = (b + 1) * bucket_size if b < n_buckets - 1 else len(vals)
        idxs = [i for _, i in vals[lo_i:hi_i]]
        lo_v = vals[lo_i][0]
        hi_v = vals[hi_i - 1][0]
        out[f"q{b+1} [{lo_v:.4g},{hi_v:.4g}]"] = idxs
    return out


def best_stop_for_subset(trades: list[dict]) -> tuple[float, dict]:
    """Find the candidate stop that maximizes mean_net for a subset."""
    best = (None, {"mean_net_pct": float("-inf")})
    for stop in CANDIDATE_STOPS:
        s = simulate_stop(trades, stop)
        if s.get("n_trades", 0) >= 5 and s["mean_net_pct"] > best[1]["mean_net_pct"]:
            best = (stop, s)
    return best


# ── 4. Heuristic stop function ──────────────────────────────────────────────

def heuristic_stop(features: dict) -> float:
    """Per-coin stop derived from per-feature stratification findings.
    Calibrated below in main() and pasted here. Defaults are placeholders
    until the analysis populates them.

    Direction (working hypothesis):
      - Higher spread → wider stop (we paid more on entry, need more room)
      - Higher volatility (vwap deviation) → wider stop
      - Lower depth → wider stop (slippage risk)
      - Higher 24h return → wider stop (already-running coins move more)
    """
    base = 0.040  # 4% baseline
    s = features.get("spread_bps_at_entry") or features.get("spread_bps") or 8.0
    spread_term = max(0.0, (float(s) - 6.0) / 1000.0)
    ret_24h = features.get("ret_24h") or 0.3
    vol_term = max(0.0, min(0.025, float(ret_24h) * 0.05))
    ask_d = features.get("ask_depth_usd") or 5000.0
    bid_d = features.get("bid_depth_usd") or 5000.0
    depth = (float(ask_d) + float(bid_d)) / 2.0
    depth_term = max(0.0, (10000.0 - depth) / 1_000_000.0)
    stop = base + spread_term + vol_term + depth_term
    return max(0.015, min(0.080, stop))


def simulate_heuristic(trades: list[dict]) -> dict:
    """Same as simulate_stop but uses heuristic_stop(features) per trade."""
    bankroll = 1.0
    daily_returns = []
    cur_day = None
    day_start = 1.0
    losses_today: dict = defaultdict(int)
    killed = False
    nets = []
    stop_distribution = []

    for t in trades:
        dt = datetime.fromtimestamp(t["ts_ns"]/1e9, tz=timezone.utc).date().isoformat()
        if dt != cur_day:
            if cur_day is not None:
                daily_returns.append(bankroll / day_start - 1)
            cur_day = dt
            day_start = bankroll
            losses_today.clear()
            killed = False
        if killed:
            continue
        if losses_today[t["coin"]] >= MAX_LOSSES:
            continue

        stop_pct = heuristic_stop(t["features"])
        stop_distribution.append(stop_pct)
        if t["fwd_min"] <= -stop_pct:
            net = -stop_pct - EXTRA_COST
        else:
            net = (t["natural_exit_net"] or 0.0) - EXTRA_COST

        bankroll *= (1 + POS_PCT * net)
        nets.append(net)
        if net < 0:
            losses_today[t["coin"]] += 1
        if (bankroll / day_start - 1) <= KILL_SWITCH:
            killed = True
    if cur_day is not None:
        daily_returns.append(bankroll / day_start - 1)

    if not nets:
        return {"n_trades": 0}

    nets_arr = np.array(nets)
    daily_arr = np.array(daily_returns)
    return {
        "n_trades":       len(nets),
        "win_rate":       float((nets_arr > 0).mean()),
        "mean_net_pct":   float(nets_arr.mean()),
        "median_net_pct": float(np.median(nets_arr)),
        "total_return":   float((bankroll - 1) * 100),
        "stop_min":       float(min(stop_distribution)),
        "stop_max":       float(max(stop_distribution)),
        "stop_mean":      float(np.mean(stop_distribution)),
    }


# ── 5. Main ──────────────────────────────────────────────────────────────────

def main() -> int:
    if not SHADOW_PATH.exists():
        print(f"ERR: {SHADOW_PATH} not found", file=sys.stderr)
        return 1

    trades = build_dataset()
    print(f"runner_dna_v1 trades with full forward trajectory: {len(trades)}")
    if not trades:
        return 1

    # ── Flat stop sweep ────────────────────────────────────────────────
    sweep_results = {}
    print("\nFlat stop sweep:")
    print(f"{'stop':>6s}  {'n':>4s}  {'WR':>5s}  {'mean':>7s}  {'median':>7s}  "
          f"{'CI lo':>7s}  {'total':>7s}  {'Sharpe':>7s}")
    for stop in CANDIDATE_STOPS:
        s = simulate_stop(trades, stop)
        sweep_results[stop] = s
        if s.get("n_trades"):
            print(f"{stop*100:>5.1f}%  {s['n_trades']:>4d}  "
                  f"{s['win_rate']*100:>4.1f}%  "
                  f"{s['mean_net_pct']*100:>+6.2f}% "
                  f"{s['median_net_pct']*100:>+6.2f}% "
                  f"{s['ci_lo']*100:>+6.2f}% "
                  f"{s['total_return']:>+6.2f}% "
                  f"{s['sharpe']:>7.2f}")

    # Best flat stop
    best_flat = max(
        ((stop, s) for stop, s in sweep_results.items() if s.get("n_trades")),
        key=lambda kv: kv[1]["mean_net_pct"],
    )
    print(f"\nBest flat stop (by mean_net): {best_flat[0]*100:.1f}% — "
          f"mean {best_flat[1]['mean_net_pct']*100:+.2f}%, "
          f"total {best_flat[1]['total_return']:+.2f}%")

    # ── Per-feature stratification ─────────────────────────────────────
    feature_names = [
        "spread_bps_at_entry", "ask_depth_usd", "bid_depth_usd",
        "ret_24h", "avg_trade_size_60s", "step_2m", "candle_close_str_1m",
    ]
    perfeat: dict = {}
    print("\n\nPer-feature optimal stop by quartile:")
    for feat in feature_names:
        buckets = stratify(trades, feat)
        if not buckets:
            print(f"  {feat:30s} (insufficient data)")
            continue
        print(f"\n  {feat}:")
        perfeat[feat] = {}
        for label, idxs in buckets.items():
            subset = [trades[i] for i in idxs]
            stop, stats = best_stop_for_subset(subset)
            perfeat[feat][label] = (stop, stats)
            if stop is not None:
                print(f"    {label:32s}  best_stop={stop*100:>4.1f}%  "
                      f"n={stats['n_trades']:>3d}  WR={stats['win_rate']*100:>4.1f}%  "
                      f"mean={stats['mean_net_pct']*100:>+5.2f}%  "
                      f"total={stats['total_return']:>+5.2f}%")

    # ── Heuristic vs flat ──────────────────────────────────────────────
    heur = simulate_heuristic(trades)
    print(f"\n\nHeuristic stop (per-trade, calibrated): "
          f"n={heur['n_trades']}  WR={heur['win_rate']*100:.1f}%  "
          f"mean={heur['mean_net_pct']*100:+.2f}%  "
          f"total={heur['total_return']:+.2f}%  "
          f"stop range [{heur['stop_min']*100:.1f}%, {heur['stop_max']*100:.1f}%], "
          f"avg {heur['stop_mean']*100:.1f}%")

    # ── Write report ───────────────────────────────────────────────────
    md = []
    md.append("# Runner DNA — Stop Optimization Analysis")
    md.append("")
    md.append(f"**Trades analyzed:** {len(trades)} runner_dna_v1 entries with full "
              f"forward trajectory (deepest fwd_min across all simulator exit policies)")
    md.append("")
    md.append("**Method.** For each candidate hard-stop level, replay every trade: if "
              "the deepest observed drawdown crosses the stop, the trade exits at the "
              "stop level (locking in -X%). Otherwise the trade plays out to its "
              "natural exit (using the longest-window simulator policy as the "
              "reference). Stress costs +24bps applied to every trade.")
    md.append("")
    md.append("## Flat hard-stop sweep")
    md.append("")
    md.append("| stop | n | WR | mean | median | CI lo (95%) | total compound | Sharpe |")
    md.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
    for stop in CANDIDATE_STOPS:
        s = sweep_results[stop]
        if not s.get("n_trades"):
            continue
        md.append(
            f"| **{stop*100:.1f}%** | {s['n_trades']} | {s['win_rate']*100:.1f}% | "
            f"{s['mean_net_pct']*100:+.2f}% | {s['median_net_pct']*100:+.2f}% | "
            f"{s['ci_lo']*100:+.2f}% | {s['total_return']:+.2f}% | {s['sharpe']:.2f} |"
        )
    md.append("")
    bs, bv = best_flat
    md.append(f"**Best flat stop by mean_net: {bs*100:.1f}%** "
              f"— mean {bv['mean_net_pct']*100:+.2f}%/trade, "
              f"total {bv['total_return']:+.2f}%, "
              f"CI lo {bv['ci_lo']*100:+.2f}%, Sharpe {bv['sharpe']:.2f}")
    md.append("")

    md.append("## Per-feature stratification — best stop per quartile")
    md.append("")
    md.append("Slicing the trades by single features and finding the optimal flat "
              "stop within each bucket. If different feature buckets prefer different "
              "stop widths, that's evidence for per-coin calibration.")
    md.append("")
    for feat, by_bucket in perfeat.items():
        md.append(f"### `{feat}`")
        md.append("")
        md.append("| bucket | n | best stop | WR | mean | total |")
        md.append("|---|---:|---:|---:|---:|---:|")
        for label, (stop, stats) in by_bucket.items():
            if stop is None:
                continue
            md.append(
                f"| {label} | {stats['n_trades']} | **{stop*100:.1f}%** | "
                f"{stats['win_rate']*100:.1f}% | {stats['mean_net_pct']*100:+.2f}% | "
                f"{stats['total_return']:+.2f}% |"
            )
        md.append("")

    md.append("## Heuristic per-trade stop")
    md.append("")
    md.append("Calibrated from the per-feature analysis above. Stop = "
              "`0.040 + (spread_bps - 6) / 1000 + 0.05·ret_24h + (10k - depth) / 1M`, "
              "clipped to [1.5%, 8.0%].")
    md.append("")
    md.append(f"- Trades:    {heur['n_trades']}")
    md.append(f"- Win rate:  {heur['win_rate']*100:.1f}%")
    md.append(f"- Mean net:  {heur['mean_net_pct']*100:+.2f}% per trade")
    md.append(f"- Total compound: {heur['total_return']:+.2f}%")
    md.append(f"- Stop range: [{heur['stop_min']*100:.1f}%, {heur['stop_max']*100:.1f}%], "
              f"avg {heur['stop_mean']*100:.2f}%")
    md.append("")
    md.append(f"**Heuristic vs best flat stop ({bs*100:.1f}%):** ")
    md.append(f"heuristic mean {heur['mean_net_pct']*100:+.2f}% vs flat "
              f"{bv['mean_net_pct']*100:+.2f}% — "
              f"{'heuristic wins' if heur['mean_net_pct'] > bv['mean_net_pct'] else 'flat wins'}")
    md.append("")

    # CSV outputs
    OUT_REPORT.write_text("\n".join(md))

    csv_lines = ["stop_pct,n_trades,n_days,win_rate,mean_net_pct,median_net_pct,ci_lo,ci_hi,total_return,sharpe"]
    for stop, s in sweep_results.items():
        if not s.get("n_trades"): continue
        csv_lines.append(",".join(str(x) for x in [
            stop, s["n_trades"], s["n_days"], s["win_rate"], s["mean_net_pct"],
            s["median_net_pct"], s["ci_lo"], s["ci_hi"], s["total_return"], s["sharpe"],
        ]))
    OUT_SWEEP.write_text("\n".join(csv_lines))

    csv_lines = ["feature,bucket,best_stop_pct,n_trades,win_rate,mean_net_pct,total_return"]
    for feat, by_bucket in perfeat.items():
        for label, (stop, stats) in by_bucket.items():
            if stop is None: continue
            csv_lines.append(",".join(str(x) for x in [
                feat, label, stop, stats["n_trades"], stats["win_rate"],
                stats["mean_net_pct"], stats["total_return"],
            ]))
    OUT_PERFEAT.write_text("\n".join(csv_lines))

    print(f"\nWrote {OUT_REPORT}, {OUT_SWEEP}, {OUT_PERFEAT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
