"""
research/daily.py — Daily data ingestion, QA, and monitoring.

Runs at 8am UTC via cron. Jobs:
  1. Validate new shadow records (schema, feature coverage, shadow coverage).
  2. Count post-deploy trades per variant.
  3. Update monitoring snapshot.
  4. Alert on: broken shadow coverage, missing features, EV drift.

This script does NOT train models or make promotion decisions.
It is a measurement and health-check tool only.

Usage:
  python3 -m research.daily              # full QA run
  python3 -m research.daily --brief      # one-line summary per variant
  python3 -m research.daily --since=DATE # only process records after DATE (YYYY-MM-DD)
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .config import (
    LIVE_VARIANTS,
    SHADOW_FILE,
    LIVE_FILE,
    RESEARCH_DIR,
    PRECISION_FILTER_DEPLOY_TS_NS,
    regime_label,
)
from .evaluate import load_events, compute_stats

QA_LOG  = RESEARCH_DIR / "daily_qa.jsonl"
SNAP_LOG = RESEARCH_DIR / "daily_snapshots.jsonl"

# Critical features that MUST be present in every live-traded signal record.
CRITICAL_FEATURES: dict[str, list[str]] = {
    "R7_STAIRCASE": [
        "rank_60s", "cg_trending", "market_breadth_5m", "signals_24h",
        "step_2m", "candle_close_str_1m", "spread_bps",
    ],
    "R5_CONFIRMED_RUN": [
        "rank_60s", "cg_trending", "market_breadth_5m", "signals_24h",
        "dv_trend", "ask_depth_usd", "spread_bps",
    ],
}


# ── Shadow coverage check ─────────────────────────────────────────────────────

def check_shadow_coverage(
    shadow_file: Path,
    since_ts_ns: int = PRECISION_FILTER_DEPLOY_TS_NS,
) -> dict:
    """Verify that shadow_trades.jsonl covers every live variant post-deploy.

    Returns coverage dict per variant with: count, exit_policies seen, date range.
    """
    by_variant: dict[str, dict] = {}

    with shadow_file.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("entry_ts_ns", 0) <= since_ts_ns:
                continue
            v = r.get("variant", "")
            p = r.get("exit_policy", "")
            if v not in LIVE_VARIANTS:
                continue
            entry = by_variant.setdefault(v, {
                "count": 0, "policies": set(), "min_ts": float("inf"), "max_ts": 0
            })
            entry["count"] += 1
            entry["policies"].add(p)
            ts = int(r.get("entry_ts_ns", 0))
            entry["min_ts"] = min(entry["min_ts"], ts)
            entry["max_ts"] = max(entry["max_ts"], ts)

    # Serialize sets
    result = {}
    alerts = []
    for v, lv_policy in LIVE_VARIANTS.items():
        info = by_variant.get(v)
        if info is None:
            result[v] = {"count": 0, "has_live_policy": False, "alert": True}
            alerts.append(f"NO shadow coverage for {v} after deploy")
            continue
        has_live_policy = lv_policy in info["policies"]
        if not has_live_policy:
            alerts.append(
                f"{v}: shadow exists (n={info['count']}) "
                f"but missing live exit policy '{lv_policy}' — check simulator.py"
            )
        result[v] = {
            "count":           info["count"],
            "policies":        sorted(info["policies"]),
            "has_live_policy": has_live_policy,
            "alert":           not has_live_policy,
        }

    return {"by_variant": result, "alerts": alerts}


# ── Feature coverage check ────────────────────────────────────────────────────

def check_feature_coverage(
    shadow_file: Path,
    since_ts_ns: int = PRECISION_FILTER_DEPLOY_TS_NS,
    sample_n: int = 200,
) -> dict:
    """Check that critical features are present in recent shadow records.

    Samples up to sample_n records per variant and checks that the critical
    precision-filter features are populated (not None/missing).
    """
    samples: dict[str, list[dict]] = {v: [] for v in LIVE_VARIANTS}

    with shadow_file.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("entry_ts_ns", 0) <= since_ts_ns:
                continue
            v = r.get("variant", "")
            if v not in LIVE_VARIANTS:
                continue
            expected_policy = LIVE_VARIANTS[v]
            if r.get("exit_policy") != expected_policy:
                continue
            if len(samples[v]) < sample_n:
                samples[v].append(r)

    result = {}
    alerts = []
    for v, records in samples.items():
        if not records:
            result[v] = {"n_sampled": 0, "alert": True}
            alerts.append(f"{v}: no sample records to check feature coverage")
            continue

        critical = CRITICAL_FEATURES.get(v, [])
        missing_counts: dict[str, int] = defaultdict(int)
        for r in records:
            feat = r.get("sig_features") or {}
            for k in critical:
                if feat.get(k) is None:
                    missing_counts[k] += 1

        n = len(records)
        feature_ok = {k: n - missing_counts.get(k, 0) for k in critical}
        missing_pct = {k: missing_counts[k] / n for k in critical if missing_counts.get(k, 0) > 0}

        variant_alerts = []
        for k, pct in missing_pct.items():
            if pct > 0.10:  # more than 10% missing is a problem
                msg = f"{v}: feature '{k}' missing in {pct:.0%} of records"
                alerts.append(msg)
                variant_alerts.append(msg)

        result[v] = {
            "n_sampled":   n,
            "feature_ok":  feature_ok,
            "missing_pct": missing_pct,
            "alerts":      variant_alerts,
        }

    return {"by_variant": result, "alerts": alerts}


# ── Performance snapshot ──────────────────────────────────────────────────────

def compute_post_deploy_snapshot(
    shadow_file: Path,
    since_ts_ns: int = PRECISION_FILTER_DEPLOY_TS_NS,
) -> dict:
    """Compute OOS performance snapshot for post-deploy shadow trades.

    Uses the champion filter to count only trades that would have been taken.
    Returns raw (unfiltered) stats and champion-filtered stats separately.
    """
    from .config import champion_passes

    raw_by_v: dict[str, list[float]] = {v: [] for v in LIVE_VARIANTS}
    filtered_by_v: dict[str, list[float]] = {v: [] for v in LIVE_VARIANTS}
    dedup: dict[tuple, tuple] = {}

    with shadow_file.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = r.get("entry_ts_ns", 0)
            if ts <= since_ts_ns:
                continue
            v = r.get("variant", "")
            if v not in LIVE_VARIANTS:
                continue
            expected_policy = LIVE_VARIANTS[v]
            if r.get("exit_policy") != expected_policy:
                continue
            net = r.get("net_pct")
            if net is None:
                continue

            coin = r.get("coin", "")
            delay = r.get("delay_ms") or 0
            key = (coin, ts, v)
            prev = dedup.get(key)
            if prev is not None and abs(prev[0] - 250) < abs(delay - 250):
                continue
            dedup[key] = (delay, r)

    for (coin, ts, v), (delay, r) in dedup.items():
        net = float(r.get("net_pct", 0.0))
        feat = r.get("sig_features") or {}
        raw_by_v[v].append(net)
        if champion_passes(feat, v):
            filtered_by_v[v].append(net)

    snapshot = {}
    for v in LIVE_VARIANTS:
        raw_n = len(raw_by_v[v])
        filt_n = len(filtered_by_v[v])
        raw_stats = compute_stats(raw_by_v[v]) if raw_by_v[v] else {"n": 0}
        filt_stats = compute_stats(filtered_by_v[v]) if filtered_by_v[v] else {"n": 0}
        snapshot[v] = {
            "raw":      {"n": raw_n, **raw_stats},
            "filtered": {"n": filt_n, **filt_stats},
        }

    return snapshot


# ── Live trade check ──────────────────────────────────────────────────────────

def check_live_trades(
    live_file: Path,
    since_ts_str: str = "2026-04-22T17:13:46",
) -> dict:
    """Parse live_trades.jsonl and report post-deploy live performance."""
    if not live_file.exists():
        return {"exists": False, "entries": 0, "exits": 0}

    entries: list[dict] = []
    exits:   list[dict] = []

    with live_file.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = r.get("ts") or r.get("event_ts") or ""
            if ts < since_ts_str:
                continue
            ev = r.get("event", "")
            if ev == "ENTRY":
                entries.append(r)
            elif ev == "EXIT":
                exits.append(r)

    gains = []
    for ex in exits:
        g = ex.get("gain") or ex.get("net_pct") or ex.get("gross_pct")
        if g is not None:
            gains.append(float(g))

    return {
        "exists":   True,
        "entries":  len(entries),
        "exits":    len(exits),
        "stats":    compute_stats(gains) if gains else {"n": 0},
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def run_daily(
    brief: bool = False,
    since_ts_ns: int = PRECISION_FILTER_DEPLOY_TS_NS,
    write_log: bool = True,
) -> dict:
    """Run all daily QA checks and return results."""
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M UTC")

    print(f"{'='*65}")
    print(f"  DAILY QA  —  {now_str}")
    print(f"{'='*65}")

    # 1. Shadow coverage
    shadow_cov = check_shadow_coverage(SHADOW_FILE, since_ts_ns)
    # 2. Feature coverage
    feat_cov = check_feature_coverage(SHADOW_FILE, since_ts_ns)
    # 3. Performance snapshot (champion-filtered)
    perf = compute_post_deploy_snapshot(SHADOW_FILE, since_ts_ns)
    # 4. Live trades
    live = check_live_trades(LIVE_FILE)

    all_alerts: list[str] = (
        shadow_cov.get("alerts", []) +
        feat_cov.get("alerts", []) +
        _perf_alerts(perf)
    )

    if brief:
        for v in LIVE_VARIANTS:
            filt = perf.get(v, {}).get("filtered", {})
            n = filt.get("n", 0)
            wr = filt.get("wr", 0)
            ev = filt.get("ev_adj", 0)
            shadow_n = shadow_cov["by_variant"].get(v, {}).get("count", 0)
            print(f"  {v}: shadow_n={shadow_n}  champion_filtered n={n}  "
                  f"WR={wr:.0%}  EV={ev:+.2%}")
        if all_alerts:
            print(f"\n  ⚠ {len(all_alerts)} alert(s) — run without --brief to see them")
    else:
        _print_full_report(shadow_cov, feat_cov, perf, live, all_alerts)

    result = {
        "ts":             now_str,
        "shadow_coverage": shadow_cov,
        "feature_coverage": feat_cov,
        "performance":    perf,
        "live":           live,
        "alerts":         all_alerts,
    }

    if write_log and RESEARCH_DIR.exists():
        with SNAP_LOG.open("a") as f:
            f.write(json.dumps({
                "ts":      now_str,
                "alerts":  all_alerts,
                "perf":    {v: perf[v]["filtered"] for v in LIVE_VARIANTS},
                "shadow":  {v: shadow_cov["by_variant"].get(v, {}).get("count", 0)
                            for v in LIVE_VARIANTS},
                "live_exits": live.get("exits", 0),
            }) + "\n")

    return result


def _perf_alerts(perf: dict) -> list[str]:
    alerts = []
    for v, stats in perf.items():
        filt = stats.get("filtered", {})
        n = filt.get("n", 0)
        ev = filt.get("ev_adj", 0.0)
        wr = filt.get("wr", 0.0)
        # Only alert once we have enough data
        if n >= 15 and ev < -0.01:
            alerts.append(f"{v}: champion-filtered EV is {ev:+.2%} (strongly negative, n={n})")
        if n >= 15 and wr < 0.30:
            alerts.append(f"{v}: champion-filtered WR is {wr:.0%} (n={n}) — far below baseline")
    return alerts


def _print_full_report(shadow_cov, feat_cov, perf, live, alerts):
    print("\n  === SHADOW COVERAGE ===")
    for v, info in shadow_cov["by_variant"].items():
        expected = LIVE_VARIANTS[v]
        has = "✓" if info.get("has_live_policy") else "✗"
        print(f"  {v}: n={info.get('count',0)}  live_policy='{expected}' {has}")
        if info.get("alert"):
            print(f"    ⚠ Missing live exit policy in shadow records!")

    print("\n  === FEATURE COVERAGE (sample of recent records) ===")
    for v, info in feat_cov["by_variant"].items():
        n = info.get("n_sampled", 0)
        if n == 0:
            print(f"  {v}: no records to sample")
            continue
        mp = info.get("missing_pct", {})
        if mp:
            print(f"  {v} (n={n}): ⚠ missing features: "
                  + ", ".join(f"{k}={pct:.0%}" for k, pct in mp.items()))
        else:
            print(f"  {v} (n={n}): all critical features present ✓")

    print("\n  === CHAMPION-FILTERED PERFORMANCE (post-deploy shadow) ===")
    for v, stats in perf.items():
        raw_n  = stats["raw"].get("n", 0)
        filt_n = stats["filtered"].get("n", 0)
        filt   = stats["filtered"]
        if filt_n == 0:
            print(f"  {v}: raw_signals={raw_n}  champion_filtered=0  (accumulating...)")
            continue
        wr = filt.get("wr", 0)
        ev = filt.get("ev_adj", 0)
        ci_lo = filt.get("ev_ci_90_lo", 0)
        ci_hi = filt.get("ev_ci_90_hi", 0)
        print(f"  {v}: raw={raw_n}  filtered={filt_n}  "
              f"WR={wr:.0%}  EV={ev:+.2%}  CI=[{ci_lo:+.2%},{ci_hi:+.2%}]")

    print("\n  === LIVE TRADES (post-deploy) ===")
    if not live.get("exists"):
        print("  live_trades.jsonl not found")
    else:
        ls = live.get("stats", {})
        n  = ls.get("n", 0)
        wr = ls.get("wr", 0)
        ev = ls.get("ev_adj", 0)
        print(f"  entries={live.get('entries',0)}  exits={live.get('exits',0)}"
              + (f"  WR={wr:.0%}  EV={ev:+.2%}" if n > 0 else ""))

    print()
    if alerts:
        print(f"  {'!'*55}")
        print(f"  ⚠ {len(alerts)} ALERT(S) — investigate before next session:")
        for a in alerts:
            print(f"    ► {a}")
        print(f"  {'!'*55}")
    else:
        print("  ✓  No QA alerts.")


if __name__ == "__main__":
    brief  = "--brief" in sys.argv
    run_daily(brief=brief)
