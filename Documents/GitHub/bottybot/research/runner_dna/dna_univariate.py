"""
research/runner_dna/dna_univariate.py — feature-by-feature DNA analysis.

The question
------------
Across the labeled signal-moments dataset, which single features
discriminate the eventual *runners* (peak ≥ 10%) from the *non-runners*?

This is intentionally univariate. We learn nothing about feature
interactions here — that's the next step. But we get a ranked picture
of which raw signals carry information at all, which features the
existing filter stack is over-relying on, and which features we've
never gated on but should.

Method
------
For each feature with ≥ 50% coverage:

1. **AUC** — sort signal moments by the feature value, compute area under
   the ROC curve where the positive class is "peak ≥ 10%". A feature
   with no information lands at ~0.50; a perfectly discriminative
   feature is 1.00 or 0.00 (the latter means *high* values are bad).

2. **KS-statistic** — supremum difference between the two classes' empirical
   CDFs. Insensitive to mean differences, sensitive to *any* distribution
   difference. Useful for catching multi-modal feature behavior.

3. **Median / IQR by class** — practical readout for human inspection.

4. **Bootstrap 95% CI on AUC** — guards against single-event leverage
   when the positive class is small.

We also report the same numbers at the stricter positive class
(peak ≥ 30%) for cross-validation. A feature that ranks high on both
thresholds is more likely to encode real signal vs. small-sample noise.

Run
---
    python3 -m research.runner_dna.dna_univariate

Inputs
------
- research/runner_dna/labeled.jsonl.gz (or .parquet)

Outputs
-------
- research/runner_dna/univariate_ranking.csv
- research/runner_dna/univariate_report.md
"""
from __future__ import annotations

import gzip
import json
import math
import sys
from pathlib import Path

import numpy as np

LABELED_PATH = Path("research/runner_dna/labeled.jsonl.gz")
OUT_CSV      = Path("research/runner_dna/univariate_ranking.csv")
OUT_REPORT   = Path("research/runner_dna/univariate_report.md")

POSITIVE_THRESHOLDS = [0.10, 0.30]   # peak ≥ X%
MIN_COVERAGE         = 0.50          # skip features present on <50% of moments
MIN_POS_COUNT        = 5             # need at least this many positive samples to even try
BOOTSTRAP_ITERS      = 500


def load_labeled() -> list[dict]:
    rows: list[dict] = []
    with gzip.open(LABELED_PATH, "rt") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def coerce_numeric(v) -> float | None:
    """Boolean→0/1, numeric→float, anything else→None."""
    if v is None:
        return None
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def auc_score(values: np.ndarray, labels: np.ndarray) -> float:
    """Area under the ROC curve. Higher value of `values` is treated as
    "more positive." If a feature is in fact inversely related to the
    positive class, AUC will be < 0.5 — that's informative.

    Implementation: rank-based form of AUC = (sum of ranks of positives
    minus n_pos*(n_pos+1)/2) / (n_pos * n_neg).
    """
    n_pos = int(labels.sum())
    n_neg = int((1 - labels).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    ranks[order] = np.arange(1, len(values) + 1)
    # average ranks for ties
    sorted_vals = values[order]
    i = 0
    while i < len(sorted_vals):
        j = i
        while j + 1 < len(sorted_vals) and sorted_vals[j + 1] == sorted_vals[i]:
            j += 1
        if j > i:
            avg = (ranks[order[i]] + ranks[order[j]]) / 2.0
            ranks[order[i:j + 1]] = avg
        i = j + 1
    rank_sum_pos = float(ranks[labels == 1].sum())
    auc = (rank_sum_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    return float(auc)


def ks_statistic(pos: np.ndarray, neg: np.ndarray) -> float:
    """Kolmogorov-Smirnov 2-sample statistic. Returns max distance between
    empirical CDFs of the two samples — in [0, 1]. 0 = identical
    distributions; 1 = no overlap."""
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    all_vals = np.concatenate([pos, neg])
    all_vals.sort()
    cdf_pos = np.searchsorted(np.sort(pos), all_vals, side="right") / len(pos)
    cdf_neg = np.searchsorted(np.sort(neg), all_vals, side="right") / len(neg)
    return float(np.max(np.abs(cdf_pos - cdf_neg)))


def bootstrap_auc_ci(values: np.ndarray, labels: np.ndarray,
                     iters: int = BOOTSTRAP_ITERS) -> tuple[float, float]:
    n = len(values)
    rng = np.random.default_rng(42)
    aucs = np.empty(iters)
    aucs.fill(np.nan)
    for i in range(iters):
        idx = rng.integers(0, n, n)
        try:
            aucs[i] = auc_score(values[idx], labels[idx])
        except Exception:
            pass
    valid = aucs[~np.isnan(aucs)]
    if len(valid) < 50:
        return float("nan"), float("nan")
    lo, hi = np.percentile(valid, [2.5, 97.5])
    return float(lo), float(hi)


def analyze_feature(feat: str, rows: list[dict], threshold: float) -> dict | None:
    pairs: list[tuple[float, int]] = []
    for r in rows:
        v = coerce_numeric(r.get(feat))
        if v is None:
            continue
        is_pos = 1 if r["fwd_max_pct"] >= threshold else 0
        pairs.append((v, is_pos))
    if not pairs:
        return None
    coverage = len(pairs) / len(rows)
    if coverage < MIN_COVERAGE:
        return None
    values = np.array([p[0] for p in pairs])
    labels = np.array([p[1] for p in pairs])
    n_pos = int(labels.sum())
    if n_pos < MIN_POS_COUNT:
        return None
    auc      = auc_score(values, labels)
    ks       = ks_statistic(values[labels == 1], values[labels == 0])
    pos_vals = values[labels == 1]
    neg_vals = values[labels == 0]
    auc_lo, auc_hi = bootstrap_auc_ci(values, labels)

    # Direction: which way does the feature relate to the positive class?
    direction = "+" if auc >= 0.5 else "-"
    # |AUC - 0.5| is the discriminative magnitude regardless of direction
    discrim = abs(auc - 0.5)

    return {
        "feature":        feat,
        "threshold":      threshold,
        "n":              len(values),
        "coverage":       round(coverage, 3),
        "n_pos":          n_pos,
        "auc":            round(auc, 4),
        "auc_ci_lo":      round(auc_lo, 4) if not np.isnan(auc_lo) else None,
        "auc_ci_hi":      round(auc_hi, 4) if not np.isnan(auc_hi) else None,
        "discrim":        round(discrim, 4),
        "direction":      direction,
        "ks":             round(ks, 4),
        "pos_median":     float(round(np.median(pos_vals), 6)),
        "pos_p25":        float(round(np.percentile(pos_vals, 25), 6)),
        "pos_p75":        float(round(np.percentile(pos_vals, 75), 6)),
        "neg_median":     float(round(np.median(neg_vals), 6)),
        "neg_p25":        float(round(np.percentile(neg_vals, 25), 6)),
        "neg_p75":        float(round(np.percentile(neg_vals, 75), 6)),
    }


def main() -> int:
    if not LABELED_PATH.exists():
        print(f"ERR: {LABELED_PATH} not found — run labeler first", file=sys.stderr)
        return 1

    rows = load_labeled()
    print(f"loaded {len(rows)} signal moments")

    feature_cols = sorted({k for r in rows for k in r if k.startswith("f_")})
    print(f"candidate features: {len(feature_cols)}")

    results_by_threshold: dict[float, list[dict]] = {}
    for threshold in POSITIVE_THRESHOLDS:
        results: list[dict] = []
        for feat in feature_cols:
            r = analyze_feature(feat, rows, threshold)
            if r is not None:
                results.append(r)
        results.sort(key=lambda x: -x["discrim"])
        results_by_threshold[threshold] = results
        print(f"  threshold={threshold:.0%}: kept {len(results)} features")

    # Combined CSV: all rows from all thresholds
    csv_lines: list[str] = []
    fields = [
        "threshold", "feature", "auc", "auc_ci_lo", "auc_ci_hi", "discrim",
        "direction", "ks", "n", "coverage", "n_pos",
        "pos_median", "pos_p25", "pos_p75",
        "neg_median", "neg_p25", "neg_p75",
    ]
    csv_lines.append(",".join(fields))
    for thr, results in results_by_threshold.items():
        for r in results:
            csv_lines.append(",".join(str(r.get(f, "")) for f in fields))
    OUT_CSV.write_text("\n".join(csv_lines))

    # Markdown report — top features at each threshold
    md: list[str] = []
    md.append("# Runner DNA — Univariate Feature Ranking")
    md.append("")
    md.append(f"Source: `{LABELED_PATH}` ({len(rows)} signal moments)")
    md.append("")
    md.append(
        "**How to read AUC:** 0.50 = no signal. >0.55 means *higher* feature values are "
        "associated with eventual runners; <0.45 means lower values are. The strength of "
        "discrimination is `|AUC - 0.50|`."
    )
    md.append("")
    md.append(
        "**`auc_ci_lo` is the bootstrap 2.5%ile.** A feature whose CI lower bound is "
        "still > 0.55 (or upper bound < 0.45) is robust at the 95% level. CIs that span "
        "0.50 should be treated as 'pretty plausibly noise.'"
    )
    md.append("")

    for thr in POSITIVE_THRESHOLDS:
        results = results_by_threshold[thr]
        n_pos = results[0]["n_pos"] if results else 0
        md.append(f"## Positive class: peak ≥ {int(thr*100)}% (n_pos ≈ {n_pos})")
        md.append("")
        md.append("| rank | feature | AUC | 95% CI | dir | KS | n | n_pos | pos median | neg median |")
        md.append("|---:|---|---:|---|:---:|---:|---:|---:|---:|---:|")
        for i, r in enumerate(results[:25], 1):
            ci = (
                f"[{r['auc_ci_lo']:.3f}, {r['auc_ci_hi']:.3f}]"
                if r["auc_ci_lo"] is not None else "—"
            )
            md.append(
                f"| {i} | `{r['feature']}` | {r['auc']:.3f} | {ci} | "
                f"{r['direction']} | {r['ks']:.3f} | {r['n']} | {r['n_pos']} | "
                f"{r['pos_median']:.4g} | {r['neg_median']:.4g} |"
            )
        md.append("")

    # Cross-threshold consistency: features that score high on both
    md.append("## Cross-threshold consistency")
    md.append("")
    md.append(
        "A feature ranking high at both ≥10% and ≥30% positive thresholds is more "
        "credible than one only present at one level. Below: features ranked by the "
        "minimum discriminative power across thresholds (we want both to be high)."
    )
    md.append("")
    by_feat = {}
    for thr, results in results_by_threshold.items():
        for r in results:
            by_feat.setdefault(r["feature"], {})[thr] = r
    rows_consist = []
    for feat, by_thr in by_feat.items():
        if len(by_thr) < 2:
            continue
        d10 = by_thr[POSITIVE_THRESHOLDS[0]]
        d30 = by_thr[POSITIVE_THRESHOLDS[1]]
        rows_consist.append({
            "feature": feat,
            "auc_10": d10["auc"], "auc_30": d30["auc"],
            "discrim_10": d10["discrim"], "discrim_30": d30["discrim"],
            "min_discrim": min(d10["discrim"], d30["discrim"]),
            "dir_10": d10["direction"], "dir_30": d30["direction"],
        })
    rows_consist.sort(key=lambda r: -r["min_discrim"])
    md.append("| feature | AUC@10% | AUC@30% | min |dir 10|dir 30|")
    md.append("|---|---:|---:|---:|:---:|:---:|")
    for r in rows_consist[:20]:
        md.append(
            f"| `{r['feature']}` | {r['auc_10']:.3f} | {r['auc_30']:.3f} | "
            f"{r['min_discrim']:.3f} | {r['dir_10']} | {r['dir_30']} |"
        )

    OUT_REPORT.write_text("\n".join(md))
    print(f"\nWrote {OUT_CSV} and {OUT_REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
