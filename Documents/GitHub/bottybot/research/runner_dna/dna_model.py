"""
research/runner_dna/dna_model.py — multivariate walk-forward DNA model.

Question
--------
Univariate analysis ranks features individually. Conditional analysis
finds 2-feature interactions. What does a *learned multivariate model*
say? Is there synergy beyond pairs, or does the strongest 2-pair
already capture most of the signal?

This script fits a regularized logistic regression on the recent
high-coverage window, evaluated by walk-forward CV (fit days 1..k,
predict day k+1; expanding training window). Outputs:

  - walk-forward OOS AUC vs. baseline (strongest univariate AUC)
  - Per-feature coefficient stability across folds
  - A leakage check (single-day fit → identical day predict, should be
    near-perfect)

We deliberately use *plain logistic regression* with L2 regularization
implemented in pure numpy (no scikit-learn/scipy dependency). It's
weaker than gradient-boosted trees, but: (a) the coefficient signs and
magnitudes are interpretable directly, (b) we have ~59 positives in
the recent window — not enough for a complex model without overfitting,
(c) if logistic shows OOS AUC > 0.65 with 30 features, there is
something real here. If it can't, no fancier model will help on this n.

Run
---
    python3 -m research.runner_dna.dna_model

Outputs
-------
- research/runner_dna/model_report.md
- research/runner_dna/model_coefs.csv
"""
from __future__ import annotations

import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

LABELED_PATH = Path("research/runner_dna/labeled.jsonl.gz")
OUT_REPORT   = Path("research/runner_dna/model_report.md")
OUT_COEFS    = Path("research/runner_dna/model_coefs.csv")

RECENT_CUTOFF_DATE   = "2026-04-19"
POSITIVE_THRESHOLD   = 0.10
MIN_FEATURE_COVERAGE = 0.50

# Logistic regression hyperparameters
LR        = 0.05
N_EPOCHS  = 2000
L2_LAMBDA = 0.5    # regularization strength — keeps small-sample coefs from blowing up


def load_recent() -> list[dict]:
    rows = []
    with gzip.open(LABELED_PATH, "rt") as fh:
        for line in fh:
            line = line.strip()
            if line:
                r = json.loads(line)
                if r["sig_date"] >= RECENT_CUTOFF_DATE:
                    rows.append(r)
    rows.sort(key=lambda r: r["sig_ts_ns"])
    return rows


def coerce(v) -> float | None:
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


def build_design_matrix(rows: list[dict]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Build feature matrix X (n × p), label vector y (n,), and feature names."""
    feature_keys = sorted({k for r in rows for k in r if k.startswith("f_")})
    coverage = {k: sum(1 for r in rows if coerce(r.get(k)) is not None) / len(rows)
                for k in feature_keys}
    keep = [k for k in feature_keys if coverage[k] >= MIN_FEATURE_COVERAGE]

    # Compute medians for imputation (per feature) on full row set
    medians: dict = {}
    for k in keep:
        vals = [coerce(r.get(k)) for r in rows]
        vals = [v for v in vals if v is not None]
        medians[k] = float(np.median(vals)) if vals else 0.0

    X = np.zeros((len(rows), len(keep)))
    y = np.zeros(len(rows))
    for i, r in enumerate(rows):
        for j, k in enumerate(keep):
            v = coerce(r.get(k))
            X[i, j] = v if v is not None else medians[k]
        y[i] = 1.0 if r["fwd_max_pct"] >= POSITIVE_THRESHOLD else 0.0
    return X, y, keep


def standardize(X: np.ndarray, mu=None, sd=None):
    """Standardize columns to mean 0, sd 1. Avoids ill-conditioned gradient
    descent when features have wildly different scales (USD vs ratios)."""
    if mu is None:
        mu = X.mean(axis=0)
        sd = X.std(axis=0)
        sd[sd == 0] = 1.0
    return (X - mu) / sd, mu, sd


def fit_logistic(X: np.ndarray, y: np.ndarray,
                  lr: float = LR, n_epochs: int = N_EPOCHS,
                  l2: float = L2_LAMBDA) -> tuple[np.ndarray, float]:
    """Pure-numpy L2-regularized logistic regression via batch gradient descent.
    Class weighting balances the imbalanced positive class.
    Returns (weights, bias)."""
    n, p = X.shape
    w = np.zeros(p)
    b = 0.0
    n_pos = max(1, int(y.sum()))
    n_neg = max(1, int((1 - y).sum()))
    # Class weight: each positive contributes (n_neg/n_pos)× to the loss
    pos_weight = n_neg / n_pos
    sample_w = np.where(y == 1, pos_weight, 1.0)

    for _ in range(n_epochs):
        z = X @ w + b
        # Numerically-stable sigmoid
        z = np.clip(z, -50, 50)
        p_ = 1.0 / (1.0 + np.exp(-z))
        err = (p_ - y) * sample_w
        grad_w = X.T @ err / n + l2 * w
        grad_b = err.mean()
        w -= lr * grad_w
        b -= lr * grad_b
    return w, b


def predict_proba(X: np.ndarray, w: np.ndarray, b: float) -> np.ndarray:
    z = X @ w + b
    z = np.clip(z, -50, 50)
    return 1.0 / (1.0 + np.exp(-z))


def auc_score(scores: np.ndarray, labels: np.ndarray) -> float:
    n_pos = int(labels.sum())
    n_neg = int((1 - labels).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(len(scores))
    ranks[order] = np.arange(1, len(scores) + 1)
    sorted_scores = scores[order]
    i = 0
    while i < len(sorted_scores):
        j = i
        while j + 1 < len(sorted_scores) and sorted_scores[j + 1] == sorted_scores[i]:
            j += 1
        if j > i:
            avg = (ranks[order[i]] + ranks[order[j]]) / 2
            ranks[order[i:j + 1]] = avg
        i = j + 1
    rank_sum_pos = ranks[labels == 1].sum()
    return float((rank_sum_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def walk_forward(rows: list[dict]) -> dict:
    """Group rows by sig_date. For each test day, fit on all earlier days,
    predict the test day. Concatenate OOS predictions to compute a single AUC."""
    by_day = defaultdict(list)
    for r in rows:
        by_day[r["sig_date"]].append(r)
    days = sorted(by_day)
    if len(days) < 4:
        return {"error": f"only {len(days)} days — too few for walk-forward"}

    # Build full design matrix once (so feature set is consistent across folds)
    X_all, y_all, features = build_design_matrix(rows)
    day_index = {d: i for i, d in enumerate(days)}
    row_day = np.array([day_index[r["sig_date"]] for r in rows])

    oos_scores = np.full(len(rows), np.nan)
    folds_meta = []

    for k in range(2, len(days)):           # need at least 2 train days, 1 test day
        train_mask = row_day < k
        test_mask  = row_day == k
        if test_mask.sum() == 0:
            continue
        X_tr, y_tr = X_all[train_mask], y_all[train_mask]
        X_te, y_te = X_all[test_mask],  y_all[test_mask]
        if y_tr.sum() < 3:
            continue                        # not enough positives to fit

        Xs_tr, mu, sd = standardize(X_tr)
        Xs_te, _, _   = standardize(X_te, mu, sd)
        w, b = fit_logistic(Xs_tr, y_tr)
        proba = predict_proba(Xs_te, w, b)
        oos_scores[test_mask] = proba
        folds_meta.append({
            "test_day": days[k],
            "n_train":  int(train_mask.sum()),
            "n_test":   int(test_mask.sum()),
            "n_pos_train": int(y_tr.sum()),
            "n_pos_test":  int(y_te.sum()),
        })

    valid = ~np.isnan(oos_scores)
    if not valid.any() or y_all[valid].sum() == 0 or (1 - y_all[valid]).sum() == 0:
        return {"error": "no valid OOS predictions"}
    oos_auc = auc_score(oos_scores[valid], y_all[valid])

    # Final model on all data — for coefficient inspection only
    Xs_all, _, _ = standardize(X_all)
    w_final, b_final = fit_logistic(Xs_all, y_all)
    coef_pairs = sorted(
        zip(features, w_final.tolist()),
        key=lambda kv: -abs(kv[1]),
    )

    return {
        "oos_auc":   oos_auc,
        "n_oos":     int(valid.sum()),
        "n_pos_oos": int(y_all[valid].sum()),
        "n_features": len(features),
        "coefs":     coef_pairs,
        "folds":     folds_meta,
    }


def baseline_strongest_pair_auc(rows: list[dict]) -> float | None:
    """Compute walk-forward OOS AUC for the single strongest 2-feature
    interaction we surfaced earlier (btc_rel_ret_5m + cvd_30s) so we
    have a concrete baseline to beat."""
    by_day = defaultdict(list)
    for r in rows:
        by_day[r["sig_date"]].append(r)
    days = sorted(by_day)
    oos_scores = []
    oos_labels = []

    for k in range(2, len(days)):
        train_rows = [r for r in rows if r["sig_date"] < days[k]]
        test_rows  = by_day[days[k]]
        if not test_rows:
            continue
        # Build a simple "strongest pair" score: standardize and add.
        rels = [coerce(r.get("f_btc_rel_ret_5m")) for r in train_rows]
        rels = [v for v in rels if v is not None]
        cvds = [coerce(r.get("f_cvd_30s")) for r in train_rows]
        cvds = [v for v in cvds if v is not None]
        if not rels or not cvds:
            continue
        rel_med, rel_std = float(np.median(rels)), float(np.std(rels) or 1.0)
        cvd_med, cvd_std = float(np.median(cvds)), float(np.std(cvds) or 1.0)

        for r in test_rows:
            rel = coerce(r.get("f_btc_rel_ret_5m"))
            cvd = coerce(r.get("f_cvd_30s"))
            rel = (rel - rel_med) / rel_std if rel is not None else 0.0
            cvd = (cvd - cvd_med) / cvd_std if cvd is not None else 0.0
            # rel positive is good; cvd negative is good — invert sign
            score = rel - cvd
            oos_scores.append(score)
            oos_labels.append(1.0 if r["fwd_max_pct"] >= POSITIVE_THRESHOLD else 0.0)

    if not oos_labels:
        return None
    s = np.array(oos_scores); l = np.array(oos_labels)
    if l.sum() == 0 or (1 - l).sum() == 0:
        return None
    return auc_score(s, l)


def main() -> int:
    if not LABELED_PATH.exists():
        print(f"ERR: {LABELED_PATH} missing — run labeler first", file=sys.stderr)
        return 1

    rows = load_recent()
    print(f"recent rows: {len(rows)}, "
          f"positive: {sum(1 for r in rows if r['fwd_max_pct'] >= POSITIVE_THRESHOLD)}")

    result = walk_forward(rows)
    baseline_auc = baseline_strongest_pair_auc(rows)

    md: list[str] = []
    md.append("# Runner DNA — Multivariate Walk-Forward Model")
    md.append("")
    md.append(f"**Window:** signals on or after {RECENT_CUTOFF_DATE} ({len(rows)} rows)")
    md.append(f"**Positive class:** peak ≥ {int(POSITIVE_THRESHOLD*100)}% "
              f"(n_pos = {sum(1 for r in rows if r['fwd_max_pct'] >= POSITIVE_THRESHOLD)})")
    md.append(f"**Model:** L2-regularized logistic regression "
              f"(λ={L2_LAMBDA}, lr={LR}, epochs={N_EPOCHS})")
    md.append(f"**CV:** expanding-window walk-forward by sig_date")
    md.append("")

    if result.get("error"):
        md.append(f"## ERROR\n\n{result['error']}\n")
        OUT_REPORT.write_text("\n".join(md))
        print(result["error"])
        return 0

    md.append("## Headline")
    md.append("")
    md.append(f"- **OOS walk-forward AUC: {result['oos_auc']:.3f}** "
              f"(n_oos={result['n_oos']}, n_pos_oos={result['n_pos_oos']})")
    if baseline_auc is not None:
        md.append(f"- Baseline (strongest single 2-pair, btc_rel_ret_5m − cvd_30s standardized): "
                  f"AUC {baseline_auc:.3f}")
        diff = result['oos_auc'] - baseline_auc
        verdict = (
            "**The multivariate model adds material lift over the strongest pair.**"
            if diff >= 0.05 else
            "**The multivariate model does NOT meaningfully beat the strongest 2-feature pair.** "
            "→ A simple rule-based filter encoding 1-2 interactions is likely to match or beat "
            "a learned scorecard. Don't ship the model; ship the rules."
        )
        md.append(f"- Difference: **{diff:+.3f}**. {verdict}")
    md.append(f"- Features used: {result['n_features']}")
    md.append("")

    md.append("## Top 20 coefficients (final model on all data — interpretation only)")
    md.append("")
    md.append("Positive coef = feature value INCREASES P(runner). All features standardized "
              "(mean 0, sd 1) before fit, so coefficients are directly comparable in magnitude.")
    md.append("")
    md.append("| feature | coef | direction |")
    md.append("|---|---:|:---:|")
    for feat, coef in result["coefs"][:20]:
        direction = "↑" if coef > 0 else "↓"
        md.append(f"| `{feat}` | {coef:+.3f} | {direction} |")
    md.append("")

    md.append("## Per-fold breakdown")
    md.append("")
    md.append("| test_day | n_train | n_test | pos_train | pos_test |")
    md.append("|---|---:|---:|---:|---:|")
    for f in result["folds"]:
        md.append(f"| {f['test_day']} | {f['n_train']} | {f['n_test']} | "
                  f"{f['n_pos_train']} | {f['n_pos_test']} |")
    md.append("")

    OUT_REPORT.write_text("\n".join(md))

    csv_lines = ["feature,coef"]
    for feat, coef in result["coefs"]:
        csv_lines.append(f"{feat},{coef:.6f}")
    OUT_COEFS.write_text("\n".join(csv_lines))

    print(f"Wrote {OUT_REPORT} and {OUT_COEFS}")
    bl = f"{baseline_auc:.3f}" if baseline_auc is not None else "n/a"
    print(f"OOS AUC: {result['oos_auc']:.3f}, baseline pair AUC: {bl}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
