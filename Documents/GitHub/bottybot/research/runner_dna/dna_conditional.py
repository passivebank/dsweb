"""
research/runner_dna/dna_conditional.py — 2-feature interaction mining.

The question
------------
Univariate analysis tells us which features carry signal *on average*.
Real edges almost always live in interactions: "when X is in some regime
AND Y has some property, the runner probability jumps."

This script automates discovery of those cells. For every pair of
high-coverage numeric/boolean features, it:

  1. Buckets each feature (deciles for continuous, natural levels for
     boolean/small-cardinality).
  2. Computes runner rate (peak ≥ threshold) within each (feature_a_bucket,
     feature_b_bucket) cell.
  3. Computes Wilson confidence interval lower bound on the rate.
  4. Surfaces cells where the lower-bound rate is materially above the
     overall base rate — i.e. real concentrations, not lucky cells.

Output is a ranked CSV plus a markdown summary of the top conditional
patterns.

This runs on the same labeled.jsonl.gz produced by labeler.py and
analyzed univariately by dna_univariate.py.

Run
---
    python3 -m research.runner_dna.dna_conditional [--threshold 0.10]
                                                   [--recent-only]

Default analyzes both 0.10 and 0.30 thresholds. `--recent-only` filters
to signal moments after 2026-04-19 where the high-discrimination
features (step_2m, dv_trend, cg_trending, etc.) actually exist.
"""
from __future__ import annotations

import argparse
import gzip
import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np

LABELED_PATH = Path("research/runner_dna/labeled.jsonl.gz")
OUT_CSV      = Path("research/runner_dna/conditional_ranking.csv")
OUT_REPORT   = Path("research/runner_dna/conditional_report.md")

POSITIVE_THRESHOLDS  = [0.10, 0.30]
MIN_CELL_N           = 30      # ignore cells smaller than this — too noisy
MIN_FEATURE_COVERAGE = 0.50    # feature must be present on this much of dataset
LIFT_FLOOR           = 1.5     # only surface cells whose runner rate is at least
                               # 1.5× the base rate
RECENT_CUTOFF_DATE   = "2026-04-19"  # post-recorder-feature-extension window


# ── Bucketing helpers ────────────────────────────────────────────────────────

def bucket_continuous(values: list[float], n_buckets: int = 4) -> list[tuple]:
    """Quantile-bucket a continuous feature. Returns a list of (lo, hi, label)
    tuples. n_buckets=4 → quartiles. We use quartiles (not deciles) because
    cells must clear MIN_CELL_N — at 4054 rows / 16 quartile-quartile cells,
    we have ~250 per cell on average, which is the right floor."""
    arr = np.array([v for v in values if v is not None and not math.isnan(v)])
    if len(arr) < n_buckets * MIN_CELL_N:
        return []
    qs = np.percentile(arr, [25, 50, 75])
    edges = [float("-inf")] + [float(q) for q in qs] + [float("inf")]
    out = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i+1]
        label = (
            f"<{qs[0]:.4g}" if i == 0 else
            f">={qs[2]:.4g}" if i == len(edges) - 2 else
            f"[{lo:.4g},{hi:.4g})"
        )
        out.append((lo, hi, label))
    return out


def is_boolean_like(values: list) -> bool:
    """A feature is boolean-like if its non-null values are all 0/1 or
    True/False, or there are exactly two distinct values total."""
    distinct = set()
    for v in values:
        if v is None:
            continue
        if isinstance(v, bool):
            distinct.add(int(v))
        else:
            distinct.add(v)
        if len(distinct) > 4:
            return False
    return len(distinct) <= 2


def bucket_for(feat: str, rows: list[dict]) -> list[tuple]:
    """Return bucket definitions for a feature: [(predicate, label), ...]"""
    raw_values = [r.get(feat) for r in rows]
    coverage = sum(1 for v in raw_values if v is not None) / len(rows)
    if coverage < MIN_FEATURE_COVERAGE:
        return []

    if is_boolean_like(raw_values):
        # Booleans get 2 buckets: True/False
        def make_pred(target):
            return lambda v: (v is not None and (
                (v if isinstance(v, bool) else bool(v)) == target
            ))
        return [
            (make_pred(False), f"{feat}=F"),
            (make_pred(True),  f"{feat}=T"),
        ]

    # Continuous: quartile buckets
    nums = []
    for v in raw_values:
        if v is None:
            continue
        if isinstance(v, bool):
            continue
        try:
            nums.append(float(v))
        except (TypeError, ValueError):
            continue
    quartiles = bucket_continuous(nums, n_buckets=4)
    if not quartiles:
        return []

    def make_pred(lo, hi):
        return lambda v: (
            v is not None and not isinstance(v, bool)
            and isinstance(v, (int, float))
            and lo <= float(v) < hi
        )
    return [(make_pred(lo, hi), label) for lo, hi, label in quartiles]


# ── Wilson CI for proportions ────────────────────────────────────────────────

def wilson_lower(positives: int, n: int, z: float = 1.96) -> float:
    """Wilson 95% lower bound on a binomial proportion. More accurate than
    normal approximation for small/extreme rates — important for our 23
    runners spread across 16+ cells."""
    if n == 0:
        return 0.0
    p = positives / n
    denom = 1 + z*z / n
    centre = p + z*z / (2*n)
    margin = z * math.sqrt(p * (1 - p) / n + z*z / (4*n*n))
    return (centre - margin) / denom


def wilson_upper(positives: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 1.0
    p = positives / n
    denom = 1 + z*z / n
    centre = p + z*z / (2*n)
    margin = z * math.sqrt(p * (1 - p) / n + z*z / (4*n*n))
    return (centre + margin) / denom


# ── Main analysis ────────────────────────────────────────────────────────────

def load_labeled(recent_only: bool = False) -> list[dict]:
    rows = []
    with gzip.open(LABELED_PATH, "rt") as fh:
        for line in fh:
            line = line.strip()
            if line:
                r = json.loads(line)
                if recent_only and r["sig_date"] < RECENT_CUTOFF_DATE:
                    continue
                rows.append(r)
    return rows


def find_high_coverage_features(rows: list[dict]) -> list[str]:
    counts: dict = {}
    for r in rows:
        for k in r:
            if k.startswith("f_"):
                if r[k] is not None:
                    counts[k] = counts.get(k, 0) + 1
    return sorted([k for k, c in counts.items() if c / len(rows) >= MIN_FEATURE_COVERAGE])


def analyze_pair(feat_a: str, feat_b: str, rows: list[dict],
                 threshold: float, base_rate: float) -> list[dict]:
    buckets_a = bucket_for(feat_a, rows)
    buckets_b = bucket_for(feat_b, rows)
    if not buckets_a or not buckets_b:
        return []

    cells: list[dict] = []
    for (pred_a, label_a), (pred_b, label_b) in itertools.product(buckets_a, buckets_b):
        n = 0
        pos = 0
        for r in rows:
            if not pred_a(r.get(feat_a)):
                continue
            if not pred_b(r.get(feat_b)):
                continue
            n += 1
            if r["fwd_max_pct"] >= threshold:
                pos += 1
        if n < MIN_CELL_N:
            continue
        rate = pos / n if n else 0.0
        wl = wilson_lower(pos, n)
        wu = wilson_upper(pos, n)
        lift = rate / base_rate if base_rate > 0 else 0.0
        cells.append({
            "feat_a":      feat_a,
            "label_a":     label_a,
            "feat_b":      feat_b,
            "label_b":     label_b,
            "n":           n,
            "n_pos":       pos,
            "rate":        round(rate, 4),
            "lift":        round(lift, 2),
            "wilson_lo":   round(wl, 4),
            "wilson_hi":   round(wu, 4),
            "wilson_lo_lift": round(wl / base_rate, 2) if base_rate > 0 else 0.0,
        })
    return cells


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--threshold", type=float, default=None,
                   help="single positive-class threshold (default: run both 0.10 and 0.30)")
    p.add_argument("--recent-only", action="store_true",
                   help=f"filter to signals on or after {RECENT_CUTOFF_DATE}")
    args = p.parse_args(argv[1:])

    rows = load_labeled(recent_only=args.recent_only)
    if not rows:
        print("ERR: no labeled rows", file=sys.stderr)
        return 1
    suffix = "_recent" if args.recent_only else ""
    print(f"loaded {len(rows)} rows (recent_only={args.recent_only})")

    features = find_high_coverage_features(rows)
    print(f"high-coverage features: {len(features)}")

    thresholds = [args.threshold] if args.threshold else POSITIVE_THRESHOLDS

    md: list[str] = []
    md.append(f"# Runner DNA — Conditional 2-Feature Patterns")
    md.append("")
    md.append(f"Source: `{LABELED_PATH}` ({len(rows)} signal moments"
              f"{', recent only' if args.recent_only else ''})")
    md.append("")
    md.append(
        "**Reading guide.** `rate` = P(runner) within a cell. `lift` = `rate / base_rate` — "
        "how much better than picking randomly. `wilson_lo` is the 95% lower bound on the "
        "true runner rate; `wilson_lo_lift` is that bound divided by base rate. **A pattern "
        "is real only if `wilson_lo_lift > 1.0` — meaning even the conservative end of the "
        "CI is above baseline.** Patterns where lift > 1.5 but wilson_lo_lift < 1 are "
        "small-sample lucky."
    )
    md.append("")

    csv_lines: list[str] = []
    csv_fields = [
        "threshold", "feat_a", "label_a", "feat_b", "label_b",
        "n", "n_pos", "rate", "lift", "wilson_lo", "wilson_hi", "wilson_lo_lift",
    ]
    csv_lines.append(",".join(csv_fields))

    for threshold in thresholds:
        n_pos_total = sum(1 for r in rows if r["fwd_max_pct"] >= threshold)
        base_rate = n_pos_total / len(rows)
        print(f"\nthreshold={threshold:.0%} | base rate {base_rate*100:.2f}% "
              f"(n_pos={n_pos_total})")

        all_cells: list[dict] = []
        for feat_a, feat_b in itertools.combinations(features, 2):
            cells = analyze_pair(feat_a, feat_b, rows, threshold, base_rate)
            all_cells.extend(cells)

        # Filter: keep cells with lift >= LIFT_FLOOR (or matching depressive — lift <= 1/LIFT_FLOOR)
        positives  = [c for c in all_cells if c["lift"] >= LIFT_FLOOR]
        depressive = [c for c in all_cells if c["lift"] <= 1.0 / LIFT_FLOOR]

        # Rank by Wilson lower bound (most credible boost first)
        positives.sort(key=lambda c: -c["wilson_lo_lift"])
        depressive.sort(key=lambda c: c["wilson_lo_lift"])  # most credible suppressors

        md.append(f"## Threshold: peak ≥ {int(threshold*100)}% "
                  f"(base rate {base_rate*100:.2f}%, n_pos={n_pos_total})")
        md.append("")

        md.append("### Top 25 BOOST cells (cells where running is more likely)")
        md.append("")
        md.append("| feat_a | bucket | feat_b | bucket | n | n_pos | rate | lift | "
                  "Wilson 95% CI | lo_lift |")
        md.append("|---|---|---|---|---:|---:|---:|---:|---|---:|")
        for c in positives[:25]:
            md.append(
                f"| `{c['feat_a']}` | {c['label_a']} | `{c['feat_b']}` | {c['label_b']} "
                f"| {c['n']} | {c['n_pos']} | {c['rate']*100:.2f}% | {c['lift']:.2f}× "
                f"| [{c['wilson_lo']*100:.2f}%, {c['wilson_hi']*100:.2f}%] "
                f"| {c['wilson_lo_lift']:.2f}× |"
            )
        md.append("")

        md.append("### Top 15 SUPPRESS cells (cells where running is materially less likely)")
        md.append("")
        md.append("| feat_a | bucket | feat_b | bucket | n | n_pos | rate | lift | Wilson 95% CI |")
        md.append("|---|---|---|---|---:|---:|---:|---:|---|")
        for c in depressive[:15]:
            md.append(
                f"| `{c['feat_a']}` | {c['label_a']} | `{c['feat_b']}` | {c['label_b']} "
                f"| {c['n']} | {c['n_pos']} | {c['rate']*100:.2f}% | {c['lift']:.2f}× "
                f"| [{c['wilson_lo']*100:.2f}%, {c['wilson_hi']*100:.2f}%] |"
            )
        md.append("")

        for c in all_cells:
            csv_lines.append(",".join([
                str(threshold), c["feat_a"], c["label_a"], c["feat_b"], c["label_b"],
                str(c["n"]), str(c["n_pos"]), str(c["rate"]), str(c["lift"]),
                str(c["wilson_lo"]), str(c["wilson_hi"]), str(c["wilson_lo_lift"]),
            ]))

    csv_path    = OUT_CSV.with_suffix(f".{suffix}.csv") if suffix else OUT_CSV
    report_path = OUT_REPORT.with_suffix(f".{suffix}.md") if suffix else OUT_REPORT
    csv_path.write_text("\n".join(csv_lines))
    report_path.write_text("\n".join(md))
    print(f"\nWrote {csv_path} and {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
