"""
research/runner_dna/labeler.py — build the DNA-analysis labeled dataset.

What this does
--------------
The recorder writes one shadow_trades record per (signal moment × variant ×
exit policy) — so each unique signal moment appears in 5-10 rows with
different forward windows. For DNA analysis we want one row per signal
moment with the best-available forward-peak label.

This script:
  1. Reads /tmp/runner_dna_work/shadow_trades.jsonl  (97MB, ~100k rows).
  2. Groups by (coin, sig_ts_ns).
  3. Per group: takes the *supremum* of fwd_max_pct across exit policies
     (longest forward window we observed) and the *infimum* of fwd_min_pct
     (worst drawdown observed).
  4. Carries the union of sig_features across all rows in the group
     (features overlap across variants but each variant adds a few).
  5. Tags each moment with one of:
       NO_RUN       (peak < 5%)
       SMALL_BOUNCE (5-10%)
       MINOR_RUN    (10-30%)
       TRUE_RUNNER  (30-100%)
       MEGA_RUNNER  (>= 100%)
  6. Also tags time_to_peak proxies: FAST (< 5min) / MID (5-60min) /
     SLOW (>60min) using the variant exit_policy mix that hit the peak.
  7. Writes research/runner_dna/labeled.parquet (or .jsonl if pyarrow
     unavailable) — the single source of truth for all downstream analyses.

Run
---
    python3 -m research.runner_dna.labeler

Outputs
-------
- research/runner_dna/labeled.parquet (or .jsonl.gz fallback)
- research/runner_dna/labeler_report.md — sanity stats
"""
from __future__ import annotations

import gzip
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SHADOW_PATH = Path("/tmp/runner_dna_work/shadow_trades.jsonl")
OUT_DIR     = Path("research/runner_dna")
OUT_PARQUET = OUT_DIR / "labeled.parquet"
OUT_JSONL   = OUT_DIR / "labeled.jsonl.gz"
OUT_REPORT  = OUT_DIR / "labeler_report.md"

# Label thresholds, in fraction (e.g. 0.30 = +30%)
LABEL_BANDS = [
    ("MEGA_RUNNER",  1.00, float("inf")),
    ("TRUE_RUNNER",  0.30, 1.00),
    ("MINOR_RUN",    0.10, 0.30),
    ("SMALL_BOUNCE", 0.05, 0.10),
    ("NO_RUN",       float("-inf"), 0.05),
]


def label_for(peak: float) -> str:
    for name, lo, hi in LABEL_BANDS:
        if lo <= peak < hi:
            return name
    return "NO_RUN"


def time_class(exit_policies: set[str]) -> str:
    """Coarse heuristic for time-to-peak: shortest exit policy that
    captured the peak. Useful for stratified analysis later (different
    DNA may apply to fast pumps vs grinds)."""
    if "time_30s" in exit_policies or "time_60s" in exit_policies:
        return "FAST"
    if "time_300s" in exit_policies:
        return "MID"
    if any(p.endswith("trail") or "pullback" in p for p in exit_policies):
        return "SLOW"
    return "UNKNOWN"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not SHADOW_PATH.exists():
        print(f"ERR: shadow file not found at {SHADOW_PATH}", file=sys.stderr)
        return 1

    # Group all rows for the same signal moment together.
    groups: dict[tuple, list[dict]] = defaultdict(list)
    n_rows = 0
    with SHADOW_PATH.open() as fh:
        for line in fh:
            n_rows += 1
            try:
                r = json.loads(line)
            except Exception:
                continue
            coin = r.get("coin", "")
            ts   = r.get("sig_ts_ns") or r.get("entry_ts_ns")
            if not coin or ts is None:
                continue
            groups[(coin, int(ts))].append(r)

    labeled: list[dict] = []
    for (coin, ts), rows in groups.items():
        fwd_maxs = [r.get("fwd_max_pct") for r in rows if r.get("fwd_max_pct") is not None]
        fwd_mins = [r.get("fwd_min_pct") for r in rows if r.get("fwd_min_pct") is not None]
        if not fwd_maxs:
            continue

        peak     = max(fwd_maxs)
        drawdown = min(fwd_mins) if fwd_mins else 0.0

        # Per-policy peak: which exit policy(ies) hit (or matched) the peak?
        peak_policies = {
            r.get("exit_policy", "") for r in rows
            if r.get("fwd_max_pct") is not None and abs(r["fwd_max_pct"] - peak) < 1e-9
        }

        # Variant: any signal moment may have fired multiple variants. Keep them all.
        variants = sorted({r.get("variant", "") for r in rows if r.get("variant")})

        # Features: union across all rows for this signal moment. Later rows win on conflict.
        merged_features: dict[str, Any] = {}
        for r in rows:
            f = r.get("sig_features") or {}
            for k, v in f.items():
                if v is not None:
                    merged_features[k] = v

        # Spread at entry sometimes lives at the top level instead of in features.
        spread_top = rows[0].get("spread_bps_at_entry")
        if spread_top is not None and "spread_bps_at_entry" not in merged_features:
            merged_features["spread_bps_at_entry"] = spread_top

        record = {
            "coin":            coin,
            "sig_ts_ns":       ts,
            "sig_dt":          datetime.fromtimestamp(ts/1e9, tz=timezone.utc).isoformat(),
            "sig_date":        datetime.fromtimestamp(ts/1e9, tz=timezone.utc).date().isoformat(),
            "variants":        ",".join(variants),
            "fwd_max_pct":     peak,
            "fwd_min_pct":     drawdown,
            "label":           label_for(peak),
            "time_class":      time_class(peak_policies),
            "n_shadow_rows":   len(rows),
            **{f"f_{k}": v for k, v in merged_features.items()},
        }
        labeled.append(record)

    # Sort chronologically — every downstream walk-forward expects this.
    labeled.sort(key=lambda r: r["sig_ts_ns"])

    # Write out. Prefer Parquet (smaller, typed); fall back to gzipped JSONL.
    out_path: Path
    written_format: str
    try:
        import pandas as pd
        df = pd.DataFrame(labeled)
        df.to_parquet(OUT_PARQUET, index=False)
        out_path, written_format = OUT_PARQUET, "parquet"
    except Exception as e:
        print(f"[labeler] parquet write failed ({e}) — falling back to jsonl.gz")
        with gzip.open(OUT_JSONL, "wt") as gz:
            for r in labeled:
                gz.write(json.dumps(r, default=str) + "\n")
        out_path, written_format = OUT_JSONL, "jsonl.gz"

    # ── Sanity report ───────────────────────────────────────────────────
    label_counts:    dict = defaultdict(int)
    by_day:          dict = defaultdict(lambda: defaultdict(int))
    feature_counts:  dict = defaultdict(int)
    runners_by_coin: dict = defaultdict(int)

    for r in labeled:
        label_counts[r["label"]] += 1
        by_day[r["sig_date"]][r["label"]] += 1
        for k in r:
            if k.startswith("f_"):
                feature_counts[k] += 1
        if r["label"] in ("TRUE_RUNNER", "MEGA_RUNNER"):
            runners_by_coin[r["coin"]] += 1

    md_lines: list[str] = []
    md_lines.append("# Runner DNA — Labeler Report")
    md_lines.append("")
    md_lines.append(f"- Source rows in shadow_trades.jsonl: **{n_rows:,}**")
    md_lines.append(f"- Unique signal moments (deduped): **{len(labeled):,}**")
    md_lines.append(f"- Output: `{out_path}` ({written_format})")
    md_lines.append("")
    md_lines.append("## Label distribution")
    md_lines.append("")
    md_lines.append("| label | count | pct |")
    md_lines.append("|---|---:|---:|")
    n = max(len(labeled), 1)
    order = ["MEGA_RUNNER", "TRUE_RUNNER", "MINOR_RUN", "SMALL_BOUNCE", "NO_RUN"]
    for lab in order:
        c = label_counts.get(lab, 0)
        md_lines.append(f"| {lab} | {c:,} | {c*100/n:.2f}% |")
    md_lines.append("")
    md_lines.append("## TRUE_RUNNER / MEGA_RUNNER moments by coin (top 25)")
    md_lines.append("")
    md_lines.append("| coin | n |")
    md_lines.append("|---|---:|")
    for coin, c in sorted(runners_by_coin.items(), key=lambda kv: -kv[1])[:25]:
        md_lines.append(f"| {coin} | {c} |")
    md_lines.append("")
    md_lines.append("## Daily signal volume + runner counts")
    md_lines.append("")
    md_lines.append("| date | signals | TRUE_RUNNER+ | MINOR_RUN | NO_RUN |")
    md_lines.append("|---|---:|---:|---:|---:|")
    for day in sorted(by_day):
        d = by_day[day]
        total = sum(d.values())
        runners = d.get("TRUE_RUNNER", 0) + d.get("MEGA_RUNNER", 0)
        md_lines.append(
            f"| {day} | {total} | {runners} | {d.get('MINOR_RUN', 0)} | {d.get('NO_RUN', 0)} |"
        )
    md_lines.append("")
    md_lines.append("## Feature coverage (top 30)")
    md_lines.append("")
    md_lines.append("| feature | non-null moments | coverage |")
    md_lines.append("|---|---:|---:|")
    for k, c in sorted(feature_counts.items(), key=lambda kv: -kv[1])[:30]:
        md_lines.append(f"| `{k}` | {c:,} | {c*100/n:.1f}% |")
    md_lines.append("")
    OUT_REPORT.write_text("\n".join(md_lines))
    print(f"\nWrote {out_path} and {OUT_REPORT}")
    print(f"Total signal moments: {len(labeled)}, TRUE+MEGA runners: "
          f"{label_counts.get('TRUE_RUNNER', 0) + label_counts.get('MEGA_RUNNER', 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
