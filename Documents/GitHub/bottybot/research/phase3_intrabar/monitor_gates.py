#!/usr/bin/env python3
"""
monitor_gates.py — Track signal performance before/after gate changes deployed 2026-04-24.

Usage:
    python3 monitor_gates.py [--shadow /path/to/shadow_trades.jsonl]

Outputs:
    - Per-variant EV/WR/N for pre-change vs post-change period
    - Gate filter impact: how many signals each new gate blocks
    - Revert instructions if post-change performance drops significantly
"""
import json
import sys
from argparse import ArgumentParser
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev

TRADES_FILE   = Path("/home/ec2-user/phase3_intrabar/artifacts/shadow_trades.jsonl")
CHANGE_TS     = "2026-04-24T00:00:00Z"   # UTC datetime when new gates went live
FRICTION      = 0.003                     # 0.3% round-trip friction
REVERT_ALERT_EV_DROP = 0.20              # alert if post-change EV drops >20% relative

CHANGE_DT = datetime.fromisoformat(CHANGE_TS.replace("Z", "+00:00"))


# ── Gate definitions matching the 2026-04-24 live_executor changes ──────────
def gate_r12(t: dict) -> bool:
    """R12: R11 + higher_lows_3m + cvd_30s>0."""
    f = t.get("sig_features", {})
    return (
        t.get("variant") == "R7_STAIRCASE"
        and (f.get("step_2m") or 0) >= 0.018
        and (f.get("spread_bps") or 999) <= 8
        and f.get("higher_lows_3m") is True
        and (f.get("cvd_30s") or 0) > 0
    )


def gate_r11(t: dict) -> bool:
    """R11: step_2m>=0.018 + spread<=8 (pre-change R11 standard)."""
    f = t.get("sig_features", {})
    return (
        t.get("variant") == "R7_STAIRCASE"
        and (f.get("step_2m") or 0) >= 0.018
        and (f.get("spread_bps") or 999) <= 8
    )


def gate_btc_macro_r7(t: dict) -> bool:
    """BTC macro filter on R7: btc_rel_ret_5m >= 0.02."""
    f = t.get("sig_features", {})
    btc_rel = f.get("btc_rel_ret_5m")
    return (
        t.get("variant") == "R7_STAIRCASE"
        and btc_rel is not None
        and btc_rel >= 0.02
    )


def gate_r8_whale(t: dict) -> bool:
    """R8 with whale gate: whale_pct_60s >= 0.50."""
    f = t.get("sig_features", {})
    return (
        t.get("variant") == "R8_HIGH_CONVICTION"
        and (f.get("whale_pct_60s") or 0) >= 0.50
    )


def gate_r5_ret5m(t: dict) -> bool:
    """R5 momentum gate: ret_5m >= 0.05."""
    f = t.get("sig_features", {})
    return (
        t.get("variant") == "R5_CONFIRMED_RUN"
        and (f.get("ret_5m") or 0) >= 0.05
    )


# ── Statistics helpers ────────────────────────────────────────────────────────
def ev_stats(nets: list) -> dict:
    if not nets:
        return {"n": 0, "ev": 0.0, "wr": 0.0, "ci": 0.0}
    n  = len(nets)
    ev = mean(nets)
    wr = sum(1 for x in nets if x > 0) / n
    ci = (1.96 * stdev(nets) / n**0.5) if n > 1 else 0.0
    return {"n": n, "ev": round(ev * 100, 3), "wr": round(wr * 100, 1), "ci": round(ci * 100, 3)}


def fmt_row(label: str, s: dict) -> str:
    if s["n"] == 0:
        return f"  {label:<28}  n=0"
    return (
        f"  {label:<28}  n={s['n']:<5}  EV={s['ev']:+.3f}%  "
        f"WR={s['wr']:.1f}%  CI=±{s['ci']:.3f}%"
    )


# ── Main ──────────────────────────────────────────────────────────────────────
def load_trades(path: Path) -> list:
    trades = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                t = json.loads(line)
                if t.get("net_pct") is None:
                    continue
                trades.append(t)
            except Exception:
                pass
    return trades


def parse_ts(t: dict) -> datetime:
    raw = t.get("entry_ts_ns") or t.get("entry_ts") or ""
    try:
        if isinstance(raw, (int, float)) and raw > 1e15:
            return datetime.fromtimestamp(raw / 1e9, tz=timezone.utc)
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return CHANGE_DT  # fallback: treat as post-change


def split_periods(trades: list) -> tuple:
    pre, post = [], []
    for t in trades:
        dt = parse_ts(t)
        if dt >= CHANGE_DT:
            post.append(t)
        else:
            pre.append(t)
    return pre, post


def analyze_variant(trades: list, variant: str) -> dict:
    nets = [t["net_pct"] for t in trades if t.get("variant") == variant]
    return ev_stats(nets)


def analyze_gate_impact(trades: list, gate_fn, gate_label: str) -> None:
    """Show how many trades pass the gate and their EV vs those that don't."""
    passing  = [t for t in trades if gate_fn(t)]
    blocking = [t for t in trades if not gate_fn(t)]
    p = ev_stats([t["net_pct"] for t in passing])
    b = ev_stats([t["net_pct"] for t in blocking])
    total = len(passing) + len(blocking)
    pct_blocked = 100 * len(blocking) / total if total else 0
    print(f"\n── Gate: {gate_label} ─────────────────────────────────")
    print(f"  PASS  {fmt_row('(would trade)', p)}")
    print(f"  BLOCK {fmt_row('(would skip)', b)}")
    print(f"  Signals blocked: {len(blocking)}/{total} ({pct_blocked:.0f}%)")


def check_regression(pre: list, post: list, variant: str, label: str) -> bool:
    s_pre  = analyze_variant(pre,  variant)
    s_post = analyze_variant(post, variant)
    print(f"\n  {label}")
    print(f"    pre-change:  {fmt_row('', s_pre).strip()}")
    print(f"    post-change: {fmt_row('', s_post).strip()}")
    if s_pre["n"] > 0 and s_post["n"] > 0 and s_pre["ev"] != 0:
        drop = (s_pre["ev"] - s_post["ev"]) / abs(s_pre["ev"])
        if drop > REVERT_ALERT_EV_DROP:
            print(f"    *** REGRESSION ALERT: EV dropped {drop:.0%} — consider reverting ***")
            return True
    return False


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--shadow", type=Path, default=TRADES_FILE)
    args = parser.parse_args()

    if not args.shadow.exists():
        print(f"ERROR: shadow_trades not found at {args.shadow}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading trades from {args.shadow} …")
    trades = load_trades(args.shadow)
    pre, post = split_periods(trades)
    print(f"Total: {len(trades)} trades | pre: {len(pre)} | post: {len(post)}")
    print(f"Change date: {CHANGE_TS}")

    # ── Section 1: pre-change gate impact analysis (shows what changed) ──────
    print("\n" + "=" * 70)
    print("GATE IMPACT ON PRE-CHANGE DATA (historical validation)")
    print("=" * 70)

    r7_pre = [t for t in pre if t.get("variant") == "R7_STAIRCASE"]
    r8_pre = [t for t in pre if t.get("variant") == "R8_HIGH_CONVICTION"]
    r5_pre = [t for t in pre if t.get("variant") == "R5_CONFIRMED_RUN"]

    if r7_pre:
        r11_pre  = [t for t in r7_pre if gate_r11(t)]
        r12_pre  = [t for t in r7_pre if gate_r12(t)]
        btc_pre  = [t for t in r7_pre if gate_btc_macro_r7(t)]
        print(f"\nR7_STAIRCASE (n={len(r7_pre)}):")
        print(f"  All R7:        {fmt_row('', ev_stats([t['net_pct'] for t in r7_pre])).strip()}")
        print(f"  R11 (step≥1.8%+spread≤8): {fmt_row('', ev_stats([t['net_pct'] for t in r11_pre])).strip()}")
        print(f"  R12 (+hl3m+cvd>0):         {fmt_row('', ev_stats([t['net_pct'] for t in r12_pre])).strip()}")
        print(f"  BTC macro (btc_rel≥0.02):  {fmt_row('', ev_stats([t['net_pct'] for t in btc_pre])).strip()}")

    if r8_pre:
        r8_whale = [t for t in r8_pre if gate_r8_whale(t)]
        print(f"\nR8_HIGH_CONVICTION (n={len(r8_pre)}):")
        print(f"  All R8:        {fmt_row('', ev_stats([t['net_pct'] for t in r8_pre])).strip()}")
        print(f"  whale≥50%:     {fmt_row('', ev_stats([t['net_pct'] for t in r8_whale])).strip()}")

    if r5_pre:
        r5_gate = [t for t in r5_pre if gate_r5_ret5m(t)]
        print(f"\nR5_CONFIRMED_RUN (n={len(r5_pre)}):")
        print(f"  All R5:        {fmt_row('', ev_stats([t['net_pct'] for t in r5_pre])).strip()}")
        print(f"  ret_5m≥5%:     {fmt_row('', ev_stats([t['net_pct'] for t in r5_gate])).strip()}")

    # ── Section 2: post-change period performance (shows live results) ────────
    if post:
        print("\n" + "=" * 70)
        print("POST-CHANGE PERIOD PERFORMANCE (live gate results)")
        print("=" * 70)
        for v in ("R5_CONFIRMED_RUN", "R7_STAIRCASE", "R8_HIGH_CONVICTION",
                  "R9_VOLUME_STAIRCASE", "R10_EXPLOSION_ONSET", "R11_BIG_STAIRCASE",
                  "R12_PRECISION"):
            s = analyze_variant(post, v)
            if s["n"] > 0:
                print(fmt_row(v, s))

        # Daily breakdown of post-change period
        print("\nPost-change daily EV trend:")
        by_day = defaultdict(list)
        for t in post:
            dt  = parse_ts(t)
            day = dt.date().isoformat()
            by_day[day].append(t["net_pct"])
        for day in sorted(by_day):
            nets = by_day[day]
            s = ev_stats(nets)
            print(f"  {day}  n={s['n']:<4} EV={s['ev']:+.3f}% WR={s['wr']:.1f}%")

    # ── Section 3: regression check ───────────────────────────────────────────
    if pre and post:
        print("\n" + "=" * 70)
        print("REGRESSION CHECK (pre vs post — alert if EV drops >20%)")
        print("=" * 70)
        regressions = []
        regressions.append(check_regression(pre, post, "R7_STAIRCASE",    "R7 all"))
        regressions.append(check_regression(pre, post, "R5_CONFIRMED_RUN","R5 all"))
        regressions.append(check_regression(pre, post, "R8_HIGH_CONVICTION","R8 all"))
        if any(regressions):
            print("\n*** ONE OR MORE REGRESSIONS DETECTED ***")
            print("Revert commands:")
            print("  ssh -i ~/.ssh/domainsnobs-key.pem ec2-user@52.45.183.196")
            print("  cp /home/ec2-user/phase3_intrabar/detector/currently_ripping.py.bak_20260424 \\")
            print("     /home/ec2-user/phase3_intrabar/detector/currently_ripping.py")
            print("  cp /home/ec2-user/phase3_intrabar/live_executor.py.bak_20260424 \\")
            print("     /home/ec2-user/phase3_intrabar/live_executor.py")
            print("  sudo systemctl restart phase3")
        else:
            print("\nNo regressions detected.")

    print("\nDone.")


if __name__ == "__main__":
    main()
