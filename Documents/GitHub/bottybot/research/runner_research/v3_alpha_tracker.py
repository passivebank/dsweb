"""
research/runner_research/v3_alpha_tracker.py — does v3 add alpha?

For every signal in the trailing window, classifies into one of:
  - BOTH_ACCEPT   : both v3 and the live champion accept
  - V3_ONLY       : v3 accepts, live champion rejects (v3-incremental signal)
  - LIVE_ONLY     : live champion accepts, v3 rejects (v3-blocks signal)
  - BOTH_REJECT   : both reject
  - V3_NULL       : v3 wasn't tagged (pre-deployment)

Joins to forward outcomes. Reports:
  - incremental EV from V3_ONLY signals (the "v3 alpha")
  - opportunity cost of LIVE_ONLY signals where v3 said no
  - agreement rate

Output: artifacts/v3_alpha.jsonl (append daily summary), prints latest.
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
SIGNALS_PATH = ARTIFACTS / "shadow_signals.jsonl"
TRADES_PATH  = ARTIFACTS / "shadow_trades.jsonl"
LIVE_CONFIG  = Path(os.environ.get(
    "LIVE_FILTER_CONFIG",
    "/home/ec2-user/phase3_intrabar/live_filter_config.json",
))
OUT_PATH     = ARTIFACTS / "v3_alpha.jsonl"

HARD_STOP_PCT = 0.015


def smart_trail_outcome(fmax, fmin, natural):
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


def load_live_filter_fn():
    """Load the live champion filter from the registry, dynamically."""
    try:
        sys.path.insert(0, "/home/ec2-user/phase3_intrabar")
        from research.runner_dna.registry import REGISTRY, get_filter
        cfg = json.loads(LIVE_CONFIG.read_text())
        name = cfg.get("champion", "runner_dna_v1")
        return name, get_filter(name)
    except Exception as e:
        print(f"WARN: couldn't load live filter: {e}")
        return None, None


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=7)
    args = p.parse_args(argv[1:])

    cutoff_ns = int((datetime.now(timezone.utc) - timedelta(days=args.days)).timestamp() * 1e9)

    # Index forward outcomes
    by_sig: dict[tuple, list[dict]] = defaultdict(list)
    with TRADES_PATH.open() as f:
        for line in f:
            try: r = json.loads(line)
            except: continue
            coin = r.get("coin"); ts = r.get("entry_ts_ns") or r.get("sig_ts_ns")
            if coin and ts and int(ts) >= cutoff_ns:
                by_sig[(coin, int(ts))].append(r)

    live_name, live_fn = load_live_filter_fn()
    print(f"Live champion: {live_name}")

    # Walk signals
    buckets: dict[str, list[dict]] = defaultdict(list)
    n_examined = 0; n_v3_tagged = 0
    with SIGNALS_PATH.open() as f:
        for line in f:
            try: r = json.loads(line)
            except: continue
            ts = r.get("sig_ts_ns")
            if not ts or int(ts) < cutoff_ns: continue
            n_examined += 1
            feats = r.get("features") or {}
            v3_score = feats.get("ml_runner_v3_score")
            if v3_score is None:
                buckets["V3_NULL"].append(r); continue
            n_v3_tagged += 1
            v3_accept = bool(feats.get("ml_runner_v3", False))
            # Compute live champion's call
            if live_fn:
                try:
                    live_accept = bool(live_fn(feats, r.get("variant", "")))
                except Exception:
                    live_accept = False
            else:
                live_accept = False
            # Classify
            if v3_accept and live_accept: bucket = "BOTH_ACCEPT"
            elif v3_accept and not live_accept: bucket = "V3_ONLY"
            elif live_accept and not v3_accept: bucket = "LIVE_ONLY"
            else: bucket = "BOTH_REJECT"

            # Forward outcome
            tr = by_sig.get((r["coin"], int(ts)), [])
            if tr:
                longest = max(tr, key=lambda x: x.get("holding_s") or 0)
                fmax = longest.get("fwd_max_pct"); fmin = longest.get("fwd_min_pct")
                natural = longest.get("net_pct")
                net = smart_trail_outcome(fmax, fmin, natural)
            else:
                fmax = fmin = net = None
            buckets[bucket].append({
                "sig_ts_ns": int(ts), "coin": r["coin"], "variant": r.get("variant"),
                "v3_score": v3_score, "fwd_max": fmax, "fwd_min": fmin,
                "smart_trail_net": net,
            })

    def summarize(rows):
        nets = [r["smart_trail_net"] for r in rows if r.get("smart_trail_net") is not None]
        if not nets: return {"n": len(rows), "n_with_outcome": 0}
        a = np.array(nets)
        return {
            "n":              len(rows),
            "n_with_outcome": len(nets),
            "win_rate":       float((a > 0).mean()),
            "mean_net":       float(a.mean()),
            "median_net":     float(np.median(a)),
            "total_net":      float(a.sum()),
        }

    summary = {
        "ts_utc":      datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window_days": args.days,
        "live_champion": live_name,
        "n_examined":   n_examined,
        "n_v3_tagged":  n_v3_tagged,
        "v3_alpha":     {},
    }
    for bucket in ["BOTH_ACCEPT", "V3_ONLY", "LIVE_ONLY", "BOTH_REJECT"]:
        summary["v3_alpha"][bucket] = summarize(buckets[bucket])

    # Save the latest list of V3_ONLY (the most interesting)
    summary["v3_only_recent"] = [
        {**r, "sig_ts_ns": int(r["sig_ts_ns"])}
        for r in buckets["V3_ONLY"][-20:]
    ]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("a") as f:
        f.write(json.dumps(summary, default=str) + "\n")

    print(f"\n=== v3 alpha tracker (last {args.days}d) ===")
    print(f"  signals examined: {n_examined}")
    print(f"  v3-tagged:        {n_v3_tagged} ({n_v3_tagged*100/max(n_examined,1):.1f}%)")
    print()
    print(f"  {'bucket':14s}  n   outcome  WR     mean    median   total")
    for bucket in ["BOTH_ACCEPT", "V3_ONLY", "LIVE_ONLY", "BOTH_REJECT"]:
        s = summary["v3_alpha"][bucket]
        if s.get("n_with_outcome", 0) == 0:
            print(f"  {bucket:14s}  {s['n']:>3d}  no outcomes")
            continue
        print(f"  {bucket:14s}  {s['n']:>3d}  {s['n_with_outcome']:>3d}      "
              f"{s['win_rate']*100:>4.1f}%  "
              f"{s['mean_net']*100:>+5.2f}%  "
              f"{s['median_net']*100:>+5.2f}%  "
              f"{s['total_net']*100:>+6.2f}%")

    if buckets["V3_ONLY"]:
        print(f"\n  recent V3_ONLY accepts (v3 said yes, live said no):")
        for r in buckets["V3_ONLY"][-min(8, len(buckets['V3_ONLY'])):]:
            ts = datetime.fromtimestamp(r["sig_ts_ns"]/1e9, tz=timezone.utc).isoformat(timespec="seconds")
            net_str = f"{r['smart_trail_net']*100:+.2f}%" if r.get("smart_trail_net") is not None else "—"
            fwd_max_str = f"{r['fwd_max']*100:+.1f}%" if r.get("fwd_max") is not None else "—"
            print(f"    {ts}  {r['coin']:8s}  v3={r['v3_score']:.3f}  "
                  f"fwd_max={fwd_max_str:>7s}  trail_net={net_str}")
    print(f"\n  appended summary to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
