"""
research/runner_research/per_coin_scorecard.py — per-coin EV tracker.

For each coin in our trading universe, computes daily and rolling
metrics from shadow_trades:
  - n_signals (over 7d, 14d, 30d)
  - accepted-by-live count (current champion)
  - mean fwd_max_5m
  - mean fwd_min_5m
  - hit-rate at +5%/5min target
  - simulated smart-trail net P&L per trade
  - days_since_last_runner (≥10% peak)

Output: artifacts/per_coin_scorecard.jsonl (append-only daily) +
artifacts/per_coin_scorecard_latest.json (snapshot for inference).

Used by:
  - Future ML retrain (as f_coin_recent_wr, f_coin_days_since_runner, etc.)
  - Future per-coin gate (skip coins with 7-day smart-trail mean ≤ -1%)
  - Dashboard inspection
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np

ARTIFACTS = Path(os.environ.get(
    "PHASE3_ARTIFACTS",
    "/home/ec2-user/phase3_intrabar/artifacts",
))
SHADOW_TRADES = ARTIFACTS / "shadow_trades.jsonl"
OUT_HISTORY   = ARTIFACTS / "per_coin_scorecard.jsonl"
OUT_LATEST    = ARTIFACTS / "per_coin_scorecard_latest.json"

HARD_STOP = 0.015


def smart_trail(fmax, fmin, natural):
    fmax = max(fmax or 0.0, 0.0); fmin = min(fmin or 0.0, 0.0)
    def fav():
        if fmax >= 0.07:  return fmax - 0.010
        if fmax >= 0.04:  return fmax - 0.015
        if fmax >= 0.025: return 0.010 if fmin < 0.010 else fmax - 0.010
        if fmax >= 0.015: return 0.0   if fmin < 0     else fmax * 0.7
        if fmin <= -HARD_STOP: return -HARD_STOP
        return natural if natural is not None else 0.0
    def adv():
        if fmin <= -HARD_STOP: return -HARD_STOP
        return fav()
    if fmin <= -HARD_STOP and fmax >= 0.015:
        return 0.5 * fav() + 0.5 * adv()
    return fav()


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--max-window-days", type=int, default=30)
    args = p.parse_args(argv[1:])

    cutoff = int((datetime.now(timezone.utc) - timedelta(days=args.max_window_days))
                  .timestamp() * 1e9)

    # Group shadow_trades by (coin, signal_moment) — pick longest window per signal
    sigs: dict[tuple, dict] = {}
    with SHADOW_TRADES.open() as f:
        for line in f:
            try: r = json.loads(line)
            except: continue
            ts = r.get("entry_ts_ns") or r.get("sig_ts_ns")
            if not ts or int(ts) < cutoff: continue
            coin = r.get("coin")
            if not coin: continue
            key = (coin, int(ts))
            cur = sigs.get(key)
            hs = r.get("holding_s") or 0
            if cur is None or (cur.get("holding_s") or 0) < hs:
                sigs[key] = r

    print(f"Loaded {len(sigs)} unique signal moments over {args.max_window_days}d")

    # Bucket per coin
    by_coin: dict[str, list[dict]] = defaultdict(list)
    for (coin, ts), r in sigs.items():
        fmax = r.get("fwd_max_pct"); fmin = r.get("fwd_min_pct")
        nat  = r.get("net_pct")
        net = smart_trail(fmax, fmin, nat)
        by_coin[coin].append({
            "ts_ns":     int(ts),
            "ts_date":   datetime.fromtimestamp(int(ts)/1e9, tz=timezone.utc).date().isoformat(),
            "variant":   r.get("variant"),
            "fwd_max":   fmax,
            "fwd_min":   fmin,
            "smart_trail_net": net,
            "is_runner": (fmax or 0) >= 0.10,
            "hit_5pct":  (fmax or 0) >= 0.05,
        })

    now_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)
    def in_window(ts_ns, days):
        return ts_ns >= now_ns - days * 86400 * 1_000_000_000

    out_per_coin = {}
    for coin, sigs_for_coin in by_coin.items():
        s7  = [s for s in sigs_for_coin if in_window(s["ts_ns"], 7)]
        s14 = [s for s in sigs_for_coin if in_window(s["ts_ns"], 14)]
        s30 = sigs_for_coin
        last_runner = None
        for s in sorted(sigs_for_coin, key=lambda x: -x["ts_ns"]):
            if s["is_runner"]:
                last_runner = s["ts_ns"]; break
        days_since_runner = ((now_ns - last_runner) / (86400 * 1e9)
                              if last_runner else None)

        def stats(rows):
            if not rows: return {"n": 0}
            nets = [r["smart_trail_net"] for r in rows]
            arr = np.array(nets)
            n_runner = sum(1 for r in rows if r["is_runner"])
            n_hit5   = sum(1 for r in rows if r["hit_5pct"])
            return {
                "n":              len(rows),
                "win_rate":       float((arr > 0).mean()),
                "mean_net":       float(arr.mean()),
                "median_net":     float(np.median(arr)),
                "total_net":      float(arr.sum()),
                "n_runners":      n_runner,
                "n_hit_5pct":     n_hit5,
                "hit_5pct_rate":  n_hit5 / len(rows),
            }

        out_per_coin[coin] = {
            "coin":              coin,
            "stats_7d":          stats(s7),
            "stats_14d":         stats(s14),
            "stats_30d":         stats(s30),
            "days_since_runner": days_since_runner,
            "last_runner_ts":    last_runner,
        }

    # Save snapshot
    snapshot = {
        "ts_utc":        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_coins":       len(out_per_coin),
        "max_window_days": args.max_window_days,
        "per_coin":      out_per_coin,
    }
    OUT_LATEST.parent.mkdir(parents=True, exist_ok=True)
    OUT_LATEST.write_text(json.dumps(snapshot, indent=2, default=str))
    with OUT_HISTORY.open("a") as f:
        f.write(json.dumps({k: v for k, v in snapshot.items() if k != "per_coin"},
                            default=str) + "\n")

    # Print top winners + losers
    coins_sorted = sorted(out_per_coin.values(),
                           key=lambda x: -(x["stats_7d"].get("total_net", 0)))

    print(f"\n=== PER-COIN SCORECARD (7d window) ===\n")
    print(f"  {'coin':10s}  {'n7d':>5s}  {'WR':>5s}  {'mean':>7s}  {'total':>7s}  {'5%hit':>6s}  {'days_since_runner'}")
    print("  TOP WINNERS:")
    for c in coins_sorted[:10]:
        s = c["stats_7d"]
        if s["n"] == 0: continue
        dsr = f"{c['days_since_runner']:.1f}" if c['days_since_runner'] is not None else "—"
        print(f"  {c['coin']:10s}  {s['n']:>5d}  {s['win_rate']*100:>4.1f}%  "
              f"{s['mean_net']*100:>+6.2f}%  {s['total_net']*100:>+6.2f}%  "
              f"{s['hit_5pct_rate']*100:>5.1f}%  {dsr}")
    print("\n  TOP LOSERS:")
    for c in list(reversed(coins_sorted))[:10]:
        s = c["stats_7d"]
        if s["n"] == 0: continue
        dsr = f"{c['days_since_runner']:.1f}" if c['days_since_runner'] is not None else "—"
        print(f"  {c['coin']:10s}  {s['n']:>5d}  {s['win_rate']*100:>4.1f}%  "
              f"{s['mean_net']*100:>+6.2f}%  {s['total_net']*100:>+6.2f}%  "
              f"{s['hit_5pct_rate']*100:>5.1f}%  {dsr}")

    # High-frequency signal coins (most signals, regardless of P&L)
    high_freq = sorted([c for c in out_per_coin.values()
                         if c["stats_7d"]["n"] > 0],
                        key=lambda x: -x["stats_7d"]["n"])[:5]
    print("\n  HIGH-FREQUENCY (most 7d signals):")
    for c in high_freq:
        s = c["stats_7d"]
        dsr = f"{c['days_since_runner']:.1f}" if c['days_since_runner'] is not None else "—"
        print(f"  {c['coin']:10s}  {s['n']:>5d}  {s['win_rate']*100:>4.1f}%  "
              f"{s['mean_net']*100:>+6.2f}%  {s['total_net']*100:>+6.2f}%  "
              f"{s['hit_5pct_rate']*100:>5.1f}%  {dsr}")

    print(f"\n  → snapshot saved to {OUT_LATEST}")
    print(f"  → history line appended to {OUT_HISTORY}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
