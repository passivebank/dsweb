"""
research/runner_research/build_dataset.py — build the master labeled dataset.

Joins shadow_signals.jsonl (with ALL features at signal time) with the
forward-window outcomes from shadow_trades.jsonl. Outputs one row per
unique (coin, sig_ts_ns) signal moment with forward peak/trough at
multiple horizons:

  fwd_max_1m,  fwd_min_1m   (from time_60s shadow records)
  fwd_max_5m,  fwd_min_5m   (from time_300s)
  fwd_max_30s, fwd_min_30s  (from time_30s)
  fwd_max_max, fwd_min_max  (deepest observed across all policies — best
                              proxy for "true" forward trajectory)
  natural_exit_net          (longest-policy realized P&L)

Plus all sig_features inlined as f_* columns. Plus a label_class for
each forward horizon.
"""
from __future__ import annotations

import gzip
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SHADOW_SIGNALS = Path("/tmp/runner_research/shadow_signals.jsonl")
SHADOW_TRADES  = Path("/tmp/runner_research/shadow_trades.jsonl")
OUT            = Path("/tmp/runner_research/labeled.jsonl.gz")
OUT_REPORT     = Path("research/runner_research/dataset_report.md")


def main() -> int:
    # ── Index shadow_signals features by (coin, ts) for enrichment ─────
    sig_features: dict[tuple, dict] = {}
    sig_variants: dict[tuple, str] = {}
    with SHADOW_SIGNALS.open() as f:
        for line in f:
            try: r = json.loads(line)
            except Exception: continue
            coin = r.get("coin"); ts = r.get("sig_ts_ns")
            if coin and ts:
                # Multiple signal events at same (coin, ts) — merge features
                key = (coin, int(ts))
                merged = sig_features.setdefault(key, {})
                for k, v in (r.get("features") or {}).items():
                    if v is not None:
                        merged[k] = v
                if r.get("variant"):
                    sig_variants[key] = r["variant"]

    # ── Index shadow_trades by signal moment ────────────────────────────
    by_signal: dict[tuple, list[dict]] = defaultdict(list)
    with SHADOW_TRADES.open() as f:
        for line in f:
            try: r = json.loads(line)
            except Exception: continue
            coin = r.get("coin"); ts = r.get("entry_ts_ns") or r.get("sig_ts_ns")
            if coin and ts:
                by_signal[(coin, int(ts))].append(r)

    # ── Walk every unique signal moment seen in shadow_trades ──────────
    out_rows = []
    n_signals = len(by_signal)
    by_day: dict = defaultdict(int)
    for key, trade_rows in by_signal.items():
        coin, ts = key
        # Pick canonical feature snapshot from shadow_signals (preferred)
        # or from the first shadow_trade record's sig_features
        features = dict(sig_features.get(key, {}))
        if not features:
            for r in trade_rows:
                for k, v in (r.get("sig_features") or {}).items():
                    if v is not None:
                        features.setdefault(k, v)
        variant = sig_variants.get(key) or trade_rows[0].get("variant", "")
        sig_mid = trade_rows[0].get("entry_px", 0.0)

        if True:  # keep the indented block from the original logic

            # For each exit policy seen, take the (max, min) of (fwd_max, fwd_min)
            policies: dict[str, dict] = defaultdict(lambda: {
                "fwd_max": float("-inf"), "fwd_min": float("inf"),
                "holding_s": 0.0, "net_pct": None,
            })
            for r in trade_rows:
                pol = r.get("exit_policy", "?")
                fmax = r.get("fwd_max_pct"); fmin = r.get("fwd_min_pct")
                hs   = r.get("holding_s") or 0.0
                if fmax is not None and fmax > policies[pol]["fwd_max"]:
                    policies[pol]["fwd_max"] = fmax
                if fmin is not None and fmin < policies[pol]["fwd_min"]:
                    policies[pol]["fwd_min"] = fmin
                if hs > policies[pol]["holding_s"]:
                    policies[pol]["holding_s"] = hs
                    policies[pol]["net_pct"]   = r.get("net_pct")

            # Most expansive view across all policies
            all_max = max((p["fwd_max"] for p in policies.values()
                            if p["fwd_max"] != float("-inf")), default=0.0)
            all_min = min((p["fwd_min"] for p in policies.values()
                            if p["fwd_min"] != float("inf")), default=0.0)

            # Pick the longest-window record's net_pct as the "natural exit" reference.
            natural = None
            best_holding = 0.0
            for pol, info in policies.items():
                if info["holding_s"] > best_holding and info["net_pct"] is not None:
                    best_holding = info["holding_s"]
                    natural = info["net_pct"]

            # Per-horizon proxies — pick the policy whose holding window
            # most closely matches the target horizon.
            def get_window(secs_target: float) -> tuple:
                """Closest policy by holding_s ≈ target."""
                best = (None, float("inf"))
                for pol, info in policies.items():
                    diff = abs((info["holding_s"] or 0) - secs_target)
                    if diff < best[1]:
                        best = ((info["fwd_max"], info["fwd_min"]), diff)
                return best[0] or (0.0, 0.0)

            fmax_1m, fmin_1m   = get_window(60)
            fmax_5m, fmin_5m   = get_window(300)
            fmax_30s, fmin_30s = get_window(30)

            row = {
                "coin":            coin,
                "sig_ts_ns":       ts,
                "sig_dt":          datetime.fromtimestamp(ts/1e9, tz=timezone.utc).isoformat(),
                "sig_date":        datetime.fromtimestamp(ts/1e9, tz=timezone.utc).date().isoformat(),
                "variant":         variant,
                "sig_mid":         sig_mid,
                "fwd_max_30s":     fmax_30s,
                "fwd_min_30s":     fmin_30s,
                "fwd_max_1m":      fmax_1m,
                "fwd_min_1m":      fmin_1m,
                "fwd_max_5m":      fmax_5m,
                "fwd_min_5m":      fmin_5m,
                "fwd_max_max":     all_max,
                "fwd_min_min":     all_min,
                "natural_exit_net": natural,
                "n_shadow_rows":   len(trade_rows),
            }
            for k, v in features.items():
                if v is None: continue
                row[f"f_{k}"] = v
            out_rows.append(row)
            by_day[row["sig_date"]] += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt") as gz:
        for r in sorted(out_rows, key=lambda x: x["sig_ts_ns"]):
            gz.write(json.dumps(r, default=str) + "\n")

    # ── Sanity report ───────────────────────────────────────────────────
    md = []
    md.append("# Runner Research — Dataset Report")
    md.append("")
    md.append(f"- Source signals: **{n_signals:,}** rows across "
              f"{len(by_day)} distinct days")
    md.append(f"- Output rows: **{len(out_rows):,}**")
    md.append(f"- Output: `{OUT}`")
    md.append("")
    md.append("## Per-day coverage")
    md.append("")
    md.append("| date | signals |")
    md.append("|---|---:|")
    for d in sorted(by_day):
        md.append(f"| {d} | {by_day[d]:,} |")
    md.append("")
    md.append("## Forward-horizon label distributions")
    md.append("")
    bands = [(-10, -5), (-5, -2), (-2, 0), (0, 2), (2, 5), (5, 10), (10, 30), (30, 100), (100, 1e9)]
    for col in ["fwd_max_1m", "fwd_max_5m", "fwd_max_max"]:
        md.append(f"### `{col}`")
        md.append("| band | n | pct |")
        md.append("|---|---:|---:|")
        n_total = sum(1 for r in out_rows if r.get(col) is not None)
        for lo, hi in bands:
            c = sum(1 for r in out_rows
                    if r.get(col) is not None
                    and lo/100 <= r[col] < hi/100)
            md.append(f"| [{lo}%, {hi}%) | {c:,} | {c*100/max(n_total,1):.2f}% |")
        md.append("")
    OUT_REPORT.write_text("\n".join(md))
    print(f"Wrote {OUT} and {OUT_REPORT}")
    print(f"Total signal moments: {len(out_rows):,}, "
          f"days: {len(by_day)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
