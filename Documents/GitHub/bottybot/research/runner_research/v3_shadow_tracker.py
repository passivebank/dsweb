"""
research/runner_research/v3_shadow_tracker.py — daily v3 performance audit.

Reads shadow_signals.jsonl (each signal now has ml_runner_v3 + score
fields tagged at recording time) and shadow_trades.jsonl (forward
outcomes), joins them, and reports v3's actual performance on the
trailing N days.

Outputs:
  - artifacts/v3_shadow_track.jsonl — append-only daily summary
  - prints a summary table per run
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

ARTIFACTS = Path(os.environ.get(
    "PHASE3_ARTIFACTS",
    "/home/ec2-user/phase3_intrabar/artifacts",
))
SIGNALS_PATH = ARTIFACTS / "shadow_signals.jsonl"
TRADES_PATH  = ARTIFACTS / "shadow_trades.jsonl"
OUT_PATH     = ARTIFACTS / "v3_shadow_track.jsonl"

PROB_THRESHOLD = 0.50
HARD_STOP_PCT  = 0.015


def _smart_trail_outcome(fmax, fmin, natural):
    """Same outcome model as v3_simulate, 50/50 path mix."""
    fmax = max(fmax or 0.0, 0.0); fmin = min(fmin or 0.0, 0.0)
    def fav():
        if fmax >= 0.07:  return fmax - 0.010
        if fmax >= 0.04:  return fmax - 0.015
        if fmax >= 0.025: return 0.010 if fmin < 0.010 else fmax - 0.010
        if fmax >= 0.015: return 0.0   if fmin < 0     else fmax * 0.7
        if fmin <= -HARD_STOP_PCT: return -HARD_STOP_PCT
        return natural if natural is not None else 0.0
    def adv():
        if fmin <= -HARD_STOP_PCT: return -HARD_STOP_PCT
        return fav()
    if fmin <= -HARD_STOP_PCT and fmax >= 0.015:
        return 0.5 * fav() + 0.5 * adv()
    return fav()


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=14, help="trailing window")
    args = p.parse_args(argv[1:])

    cutoff_ns = int((datetime.now(timezone.utc) - timedelta(days=args.days)).timestamp() * 1e9)

    # Index shadow_trades by signal moment for forward outcomes
    by_sig: dict[tuple, list[dict]] = defaultdict(list)
    with TRADES_PATH.open() as f:
        for line in f:
            try: r = json.loads(line)
            except: continue
            coin = r.get("coin"); ts = r.get("entry_ts_ns") or r.get("sig_ts_ns")
            if coin and ts and int(ts) >= cutoff_ns:
                by_sig[(coin, int(ts))].append(r)

    # Walk shadow_signals — find ones tagged with ml_runner_v3
    n_total = 0; n_v3_tagged = 0; n_v3_accept = 0
    accepted_outcomes = []  # list of (sig_ts_ns, coin, score, fwd_max_5m, fwd_min_5m, simulated_net)
    with SIGNALS_PATH.open() as f:
        for line in f:
            try: r = json.loads(line)
            except: continue
            ts = r.get("sig_ts_ns")
            if not ts or int(ts) < cutoff_ns: continue
            n_total += 1
            feats = r.get("features") or {}
            if "ml_runner_v3_score" not in feats: continue
            n_v3_tagged += 1
            score = feats.get("ml_runner_v3_score")
            accept = bool(feats.get("ml_runner_v3", False))
            if not accept: continue
            n_v3_accept += 1

            # Find forward outcome from shadow_trades
            tr = by_sig.get((r["coin"], int(ts)), [])
            if not tr: continue
            # Use the longest-window record's fwd_max/fwd_min
            longest = max(tr, key=lambda x: x.get("holding_s") or 0)
            fmax = longest.get("fwd_max_pct"); fmin = longest.get("fwd_min_pct")
            natural = longest.get("net_pct")
            net = _smart_trail_outcome(fmax, fmin, natural)
            accepted_outcomes.append({
                "sig_ts_ns": int(ts), "coin": r["coin"], "variant": r.get("variant"),
                "score": score, "fwd_max": fmax, "fwd_min": fmin, "natural": natural,
                "smart_trail_net": net,
            })

    if not accepted_outcomes:
        print(f"v3 shadow tracker: {n_total} signals examined in last {args.days}d, "
              f"{n_v3_tagged} tagged, {n_v3_accept} accepted, 0 with outcomes")
        return 0

    nets = np.array([a["smart_trail_net"] for a in accepted_outcomes])
    n = len(nets)
    wr = float((nets > 0).mean())
    mean_net = float(nets.mean())
    median_net = float(np.median(nets))

    # Bootstrap 95% CI on mean
    rng = np.random.default_rng(42)
    boots = [float(nets[rng.integers(0, n, n)].mean()) for _ in range(500)]
    ci_lo = float(np.percentile(boots, 2.5))
    ci_hi = float(np.percentile(boots, 97.5))

    # Hit rate of the original target (+5%/5min)
    n_target_hit = sum(1 for a in accepted_outcomes if (a["fwd_max"] or 0) >= 0.05)
    target_hit_rate = n_target_hit / n

    summary = {
        "ts_utc":        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window_days":   args.days,
        "n_signals":     n_total,
        "n_v3_tagged":   n_v3_tagged,
        "n_v3_accept":   n_v3_accept,
        "n_with_outcome": n,
        "win_rate":      wr,
        "mean_net":      mean_net,
        "median_net":    median_net,
        "ci_lo":         ci_lo,
        "ci_hi":         ci_hi,
        "target_5pct_hit_rate": target_hit_rate,
        "n_target_5pct_hit":    n_target_hit,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("a") as f:
        f.write(json.dumps(summary) + "\n")

    print(f"\n=== v3 shadow tracker ({args.days}d window) ===")
    print(f"  total signals:       {n_total}")
    print(f"  tagged with v3:      {n_v3_tagged} ({n_v3_tagged*100/max(n_total,1):.1f}%)")
    print(f"  v3 accept count:     {n_v3_accept}")
    print(f"  with forward data:   {n} ({n*100/max(n_v3_accept,1):.1f}% of accepts)")
    print(f"  WR (smart trail):    {wr*100:.1f}%")
    print(f"  mean net:            {mean_net*100:+.2f}% per trade")
    print(f"  median net:          {median_net*100:+.2f}%")
    print(f"  95% bootstrap CI:    [{ci_lo*100:+.2f}%, {ci_hi*100:+.2f}%]")
    print(f"  P(fwd_max_5m ≥ 5%):  {target_hit_rate*100:.1f}% ({n_target_hit}/{n})")
    print(f"  appended summary to {OUT_PATH}")

    # If accepted outcomes are interesting, show a few
    if n > 0:
        print(f"\n  recent accepted signals:")
        for a in accepted_outcomes[-min(10, n):]:
            ts = datetime.fromtimestamp(a["sig_ts_ns"]/1e9, tz=timezone.utc).isoformat(timespec="seconds")
            print(f"    {ts}  {a['coin']:8s}  score={a['score']:.3f}  "
                  f"fwd_max={(a['fwd_max'] or 0)*100:+.1f}%  "
                  f"fwd_min={(a['fwd_min'] or 0)*100:+.1f}%  "
                  f"smart_trail={a['smart_trail_net']*100:+.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
