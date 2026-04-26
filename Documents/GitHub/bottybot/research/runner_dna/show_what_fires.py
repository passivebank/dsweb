"""
research/runner_dna/show_what_fires.py — preview what runner_dna_v1 accepts.

Two views:
  --recent N            : pull the last N signals from EC2's shadow_signals.jsonl,
                          run them through the live executor's accept logic
                          (variant whitelist + onset gate + runner_dna_v1),
                          and print a per-signal accept/reject reason.
  --audit               : tail the live audit log on EC2 and pretty-print it
                          (live_entry_audit.jsonl — every actual ACCEPT decision).

Use this to:
  - Confirm the filter is doing what you think it is
  - Spot-check close misses ("would have fired if step_2m were just a hair higher")
  - Inspect every entry decision the live bot has actually taken since the
    runner_dna_v1 deploy

Run
---
    python3 -m research.runner_dna.show_what_fires --recent 50
    python3 -m research.runner_dna.show_what_fires --audit
    python3 -m research.runner_dna.show_what_fires --recent 200 --accepted-only
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Reuse the exact filter the live bot now runs
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "phase3_intrabar"))
from recorder.runner_dna_filter import runner_dna_v1_passes

EC2 = "ec2-user@3.214.53.81"
KEY = str(Path.home() / "Documents/GitHub/bottybot/Botty.pem")

SHADOW_SIGNALS = "/home/ec2-user/phase3_intrabar/artifacts/shadow_signals.jsonl"
LIVE_AUDIT     = "/home/ec2-user/phase3_intrabar/artifacts/live_entry_audit.jsonl"

APPROVED_VARIANTS = {"R7_STAIRCASE", "R8_HIGH_CONVICTION", "R10_EXPLOSION_ONSET"}
GATE_ONSET_S      = 8.0


def ssh_tail(path: str, n: int) -> list[str]:
    """Pull last N lines of a remote file via ssh+tail."""
    r = subprocess.run(
        ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=10", EC2, f"tail -n {n} {path} 2>/dev/null"],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        print(f"ssh failed: {r.stderr}", file=sys.stderr)
        return []
    return [line for line in r.stdout.splitlines() if line.strip()]


def explain_reject(features: dict, variant: str) -> str:
    """Return a short string explaining why a signal was rejected by the
    full live accept logic (variant whitelist + onset gate + runner_dna_v1)."""
    if variant not in APPROVED_VARIANTS:
        return f"variant={variant} not in approved exit-policy set"

    secs_onset = features.get("secs_since_onset", 0.0) or 0.0
    if secs_onset >= GATE_ONSET_S:
        return f"secs_since_onset={secs_onset:.1f}>={GATE_ONSET_S}"

    btc_rel = features.get("btc_rel_ret_5m")
    if btc_rel is None or btc_rel < 0.02:
        return f"btc_rel_ret_5m={btc_rel} < 0.02"

    if (features.get("signals_24h") or 0) > 15:
        return f"signals_24h={features.get('signals_24h')} > 15"

    hl = features.get("higher_lows_3m")
    if hl is True:
        if (features.get("step_2m") or 0) < 0.012:
            return f"PathA step_2m={features.get('step_2m')} < 0.012"
        if (features.get("candle_close_str_1m") or 0) < 0.70:
            return f"PathA ccs={features.get('candle_close_str_1m')} < 0.70"
        if (features.get("rank_60s") or 99) > 3:
            return f"PathA rank={features.get('rank_60s')} > 3"
        return "(should have passed Path A — bug?)"
    elif hl is False:
        if (features.get("cvd_30s") or 0) >= -3000:
            return f"PathB cvd_30s={features.get('cvd_30s')} >= -3000"
        if (features.get("ask_depth_usd") or 0) < 5000:
            return f"PathB ask_d={features.get('ask_depth_usd')} < 5000"
        if (features.get("bid_depth_usd") or 0) < 5000:
            return f"PathB bid_d={features.get('bid_depth_usd')} < 5000"
        return "(should have passed Path B — bug?)"
    else:
        return f"hl3m={hl} (need True or False)"


def cmd_recent(n: int, accepted_only: bool) -> int:
    lines = ssh_tail(SHADOW_SIGNALS, n)
    if not lines:
        print("no signals returned")
        return 1
    accepted_count = 0
    rejected_count = 0
    print(f"\n{'time':24s}  {'variant':22s}  {'coin':10s}  {'verdict':8s}  detail")
    print("-" * 110)
    for line in lines:
        try:
            r = json.loads(line)
        except Exception:
            continue
        feats   = r.get("features", {})
        variant = r.get("variant", "")
        coin    = r.get("coin", "")
        ts      = datetime.fromtimestamp(
            r.get("sig_ts_ns", 0) / 1e9, tz=timezone.utc).isoformat(timespec="seconds")

        # Run full live accept logic
        full_accept = (
            variant in APPROVED_VARIANTS
            and (feats.get("secs_since_onset") or 0.0) < GATE_ONSET_S
            and runner_dna_v1_passes(feats, variant)
        )
        if full_accept:
            accepted_count += 1
            hl = feats.get("higher_lows_3m")
            path = "A_continuation" if hl is True else "B_absorption"
            detail = (f"{path}  btc_rel={feats.get('btc_rel_ret_5m')}  "
                      f"cvd_30s={feats.get('cvd_30s')}  rank={feats.get('rank_60s')}")
            print(f"{ts:24s}  {variant:22s}  {coin:10s}  ACCEPT    {detail}")
        else:
            rejected_count += 1
            if accepted_only:
                continue
            print(f"{ts:24s}  {variant:22s}  {coin:10s}  reject    {explain_reject(feats, variant)}")
    print("-" * 110)
    total = accepted_count + rejected_count
    print(f"\nTotal: {total} signals  |  ACCEPTED: {accepted_count} "
          f"({accepted_count/total*100:.1f}%)  |  rejected: {rejected_count}")
    return 0


def cmd_audit(n: int) -> int:
    lines = ssh_tail(LIVE_AUDIT, n)
    if not lines:
        print("live_entry_audit.jsonl is empty or missing — no live accepts yet")
        return 0
    print(f"\nLast {len(lines)} live entry accept decisions:\n")
    print(f"{'time':22s}  {'variant':22s}  {'coin':10s}  {'path':16s}  detail")
    print("-" * 110)
    for line in lines:
        try:
            r = json.loads(line)
        except Exception:
            continue
        f = r.get("features", {})
        detail = (f"btc_rel={f.get('btc_rel_ret_5m')}  cvd_30s={f.get('cvd_30s')}  "
                  f"hl3m={f.get('higher_lows_3m')}  rank={f.get('rank_60s')}  "
                  f"ask_d={f.get('ask_depth_usd')}  bid_d={f.get('bid_depth_usd')}")
        print(f"{r.get('ts',''):22s}  {r.get('variant','?'):22s}  "
              f"{r.get('coin','?'):10s}  {r.get('path',''):16s}  {detail}")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--recent", type=int, help="show last N signals replayed through live filter")
    p.add_argument("--audit",  action="store_true", help="show live entry audit log")
    p.add_argument("--accepted-only", action="store_true",
                   help="hide rejects in --recent view")
    p.add_argument("--n", type=int, default=200,
                   help="number of audit lines to fetch (default: 200)")
    args = p.parse_args(argv[1:])

    if args.recent:
        return cmd_recent(args.recent, args.accepted_only)
    if args.audit:
        return cmd_audit(args.n)
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
