"""Quick test: does adding perp features lift the ML AUC?

Compares two LightGBM models trained on the same signal moments:
  baseline: original 25 features
  enriched: original 25 + 9 new perp features

Walk-forward held-out test on the last 3 days. Reports AUC delta.
"""
import gzip, json, math, sys
from pathlib import Path
import numpy as np
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

LABELED_BASE = Path("/tmp/runner_research/labeled.jsonl.gz")
LABELED_PERP = Path("/tmp/runner_research/labeled_with_perp.jsonl.gz")
HELD_OUT_FROM = "2026-04-25"
TARGET_HORIZON = "fwd_max_5m"
TARGET_THRESHOLD = 0.05


def coerce(v):
    if v is None: return np.nan
    if isinstance(v, bool): return 1.0 if v else 0.0
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f): return np.nan
        return f
    except (TypeError, ValueError): return np.nan


def load(path):
    rows = []
    with gzip.open(path, "rt") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            rows.append(json.loads(line))
    return rows


def split(rows):
    train = [r for r in rows if r["sig_date"] < HELD_OUT_FROM]
    test  = [r for r in rows if r["sig_date"] >= HELD_OUT_FROM]
    return train, test


def fit_and_test(train, test, features):
    coverage = {f: sum(1 for r in train if r.get(f) is not None) / len(train) for f in features}
    used = [f for f in features if coverage[f] >= 0.20]   # lower coverage threshold for perp
    print(f"  features ≥20% coverage: {len(used)}")

    medians = {}
    for f in used:
        vals = [coerce(r.get(f)) for r in train]
        vals = [v for v in vals if not (isinstance(v, float) and math.isnan(v))]
        medians[f] = float(np.median(vals)) if vals else 0.0

    def build_xy(rs):
        X = np.zeros((len(rs), len(used)))
        y = np.zeros(len(rs))
        for i, r in enumerate(rs):
            for j, f in enumerate(used):
                v = coerce(r.get(f))
                X[i, j] = v if not math.isnan(v) else medians[f]
            y[i] = 1 if (r.get(TARGET_HORIZON) or 0) >= TARGET_THRESHOLD else 0
        return X, y

    Xtr, ytr = build_xy(train); Xte, yte = build_xy(test)
    n_pos = max(1, int(ytr.sum())); n_neg = max(1, int((1-ytr).sum()))
    sample_w = np.where(ytr == 1, n_neg/n_pos, 1.0)
    m = lgb.LGBMClassifier(
        n_estimators=300, learning_rate=0.04, max_depth=4, num_leaves=15,
        min_child_samples=20, reg_alpha=0.5, reg_lambda=0.5,
        random_state=42, verbose=-1,
    )
    m.fit(Xtr, ytr, sample_weight=sample_w)
    auc_test = roc_auc_score(yte, m.predict_proba(Xte)[:, 1]) if yte.sum() and (1-yte).sum() else float("nan")
    return auc_test, used, m


def main():
    print("=== BASELINE (25 features) ===")
    rows_base = load(LABELED_BASE)
    train, test = split(rows_base)
    feat_base = sorted({k for r in train for k in r if k.startswith("f_")})
    auc_base, used_base, _ = fit_and_test(train, test, feat_base)
    print(f"  test AUC: {auc_base:.4f}\n")

    print("=== ENRICHED (25 + perp features) ===")
    rows_perp = load(LABELED_PERP)
    train_p, test_p = split(rows_perp)
    feat_perp = sorted({k for r in train_p for k in r if k.startswith("f_")})
    print(f"  total feature pool: {len(feat_perp)}")
    perp_only = [f for f in feat_perp if f.startswith("f_perp_")]
    print(f"  perp-only features: {perp_only}")
    auc_perp, used_perp, m_perp = fit_and_test(train_p, test_p, feat_perp)
    print(f"  test AUC: {auc_perp:.4f}\n")

    print(f"=== DELTA: {auc_perp - auc_base:+.4f} ===")
    print()
    print("Top 15 features by gain in enriched model:")
    for f, g in sorted(zip(used_perp, m_perp.booster_.feature_importance(importance_type='gain')),
                       key=lambda kv: -kv[1])[:15]:
        marker = " ★" if f.startswith("f_perp_") else ""
        print(f"  {f:35s} {g:>8.0f}{marker}")


if __name__ == "__main__":
    sys.exit(main() or 0)
