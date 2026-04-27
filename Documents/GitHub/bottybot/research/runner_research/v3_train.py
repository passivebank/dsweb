"""
research/runner_research/v3_train.py — multi-target multi-model trainer.

Trains LightGBM, XGBoost, LogisticRegression, RandomForest on every
(horizon, target) combo. Strict walk-forward by sig_date (no leakage).
Outputs best model per (horizon, target) pair + comparison table.

Saves all models to research/runner_research/v3_models/
"""
from __future__ import annotations

import gzip
import json
import math
import sys
import warnings
import pickle
from collections import defaultdict
from pathlib import Path

import numpy as np
import lightgbm as lgb
import xgboost as xgb
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")

LABELED       = Path("/tmp/runner_research/v3_labeled.jsonl.gz")
MODEL_DIR     = Path("research/runner_research/v3_models")
OUT_REPORT    = Path("research/runner_research/v3_train_report.md")
HELD_OUT_FROM = "2026-04-25"

# (target_name, horizon_col, threshold)
TARGETS = [
    ("p_1pct_3m",  "fwd_max_3m",  0.01),
    ("p_2pct_3m",  "fwd_max_3m",  0.02),
    ("p_2pct_5m",  "fwd_max_5m",  0.02),
    ("p_3pct_5m",  "fwd_max_5m",  0.03),
    ("p_5pct_5m",  "fwd_max_5m",  0.05),
    ("p_10pct",    "fwd_max_max", 0.10),
]


def coerce(v):
    if v is None: return np.nan
    if isinstance(v, bool): return 1.0 if v else 0.0
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f): return np.nan
        return f
    except (TypeError, ValueError): return np.nan


def load_labeled():
    train, test = [], []
    with gzip.open(LABELED, "rt") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            r = json.loads(line)
            (train if r["sig_date"] < HELD_OUT_FROM else test).append(r)
    return train, test


def build_xy(rows, features, hor_col, thr):
    X = np.zeros((len(rows), len(features)))
    y = np.zeros(len(rows))
    for i, r in enumerate(rows):
        for j, f in enumerate(features):
            v = coerce(r.get(f))
            X[i, j] = v
        y[i] = 1 if (r.get(hor_col) or 0) >= thr else 0
    return X, y


def impute(X, medians):
    """Replace NaN with column medians."""
    for j in range(X.shape[1]):
        X[np.isnan(X[:, j]), j] = medians[j]
    return X


def walk_forward(rows, features, hor_col, thr, model_factory):
    """Expanding window walk-forward by sig_date.
    Returns (oos_predictions array of length len(rows), per-fold AUCs)."""
    by_day = defaultdict(list)
    for i, r in enumerate(rows):
        by_day[r["sig_date"]].append(i)
    days = sorted(by_day)
    if len(days) < 4: return None, []

    oos = np.full(len(rows), np.nan)
    aucs = []
    for k in range(2, len(days)):
        train_idx = []
        for d in days[:k]: train_idx.extend(by_day[d])
        test_idx = by_day[days[k]]
        if len(train_idx) < 50 or len(test_idx) < 5: continue

        Xtr, ytr = build_xy([rows[i] for i in train_idx], features, hor_col, thr)
        Xte, yte = build_xy([rows[i] for i in test_idx],  features, hor_col, thr)

        # Impute with train medians
        medians = np.nanmedian(Xtr, axis=0)
        medians[np.isnan(medians)] = 0.0
        Xtr = impute(Xtr.copy(), medians)
        Xte = impute(Xte.copy(), medians)

        if ytr.sum() < 5 or (1 - ytr).sum() < 5: continue

        try:
            model = model_factory(ytr)
            model.fit(Xtr, ytr)
            pred = model.predict_proba(Xte)[:, 1]
        except Exception as e:
            continue
        for j, idx in enumerate(test_idx): oos[idx] = pred[j]
        if yte.sum() and (1 - yte).sum():
            try: aucs.append(roc_auc_score(yte, pred))
            except: pass
    return oos, aucs


def factory_lgbm(ytr):
    n_pos = max(1, int(ytr.sum())); n_neg = max(1, int((1 - ytr).sum()))
    return lgb.LGBMClassifier(
        n_estimators=200, learning_rate=0.05, max_depth=4, num_leaves=15,
        min_child_samples=20, reg_alpha=0.5, reg_lambda=0.5,
        class_weight={0:1, 1:n_neg/n_pos}, random_state=42, verbose=-1,
    )


def factory_xgb(ytr):
    n_pos = max(1, int(ytr.sum())); n_neg = max(1, int((1 - ytr).sum()))
    return xgb.XGBClassifier(
        n_estimators=200, learning_rate=0.05, max_depth=4,
        reg_alpha=0.5, reg_lambda=0.5,
        scale_pos_weight=n_neg/n_pos,
        eval_metric="auc", random_state=42, verbosity=0,
    )


def factory_logreg(ytr):
    n_pos = max(1, int(ytr.sum())); n_neg = max(1, int((1 - ytr).sum()))
    # Wrap in pipeline-style with scaling
    class ScaledLogReg:
        def __init__(self):
            self.scaler = StandardScaler()
            self.model = LogisticRegression(
                C=0.5, class_weight={0:1, 1:n_neg/n_pos},
                random_state=42, max_iter=500,
            )
        def fit(self, X, y):
            Xs = self.scaler.fit_transform(X)
            self.model.fit(Xs, y); return self
        def predict_proba(self, X):
            return self.model.predict_proba(self.scaler.transform(X))
    return ScaledLogReg()


def factory_rf(ytr):
    n_pos = max(1, int(ytr.sum())); n_neg = max(1, int((1 - ytr).sum()))
    return RandomForestClassifier(
        n_estimators=200, max_depth=8, min_samples_split=20,
        class_weight={0:1, 1:n_neg/n_pos},
        random_state=42, n_jobs=-1,
    )


MODEL_FACTORIES = {
    "lgbm":   factory_lgbm,
    "xgb":    factory_xgb,
    "logreg": factory_logreg,
    "rf":     factory_rf,
}


def fit_final_and_test(train_rows, test_rows, features, hor_col, thr, factory):
    Xtr, ytr = build_xy(train_rows, features, hor_col, thr)
    Xte, yte = build_xy(test_rows,  features, hor_col, thr)
    medians = np.nanmedian(Xtr, axis=0)
    medians[np.isnan(medians)] = 0.0
    Xtr_i = impute(Xtr.copy(), medians)
    Xte_i = impute(Xte.copy(), medians)
    model = factory(ytr)
    model.fit(Xtr_i, ytr)
    pred = model.predict_proba(Xte_i)[:, 1]
    auc = roc_auc_score(yte, pred) if yte.sum() and (1-yte).sum() else float("nan")
    return model, pred, auc, medians


def main():
    train, test = load_labeled()
    print(f"train: {len(train)} rows, test: {len(test)} rows")
    print(f"  train days: {sorted({r['sig_date'] for r in train})[0]} to "
          f"{sorted({r['sig_date'] for r in train})[-1]}")
    if test: print(f"  test days:  {sorted({r['sig_date'] for r in test})}")

    # Feature pool: all f_* columns with ≥40% coverage
    feature_cols = sorted({k for r in train for k in r if k.startswith("f_")})
    coverage = {f: sum(1 for r in train if r.get(f) is not None) / len(train) for f in feature_cols}
    features = [f for f in feature_cols if coverage[f] >= 0.40]
    print(f"  features pool: {len(feature_cols)}, ≥40% coverage: {len(features)}")
    # Drop CG features (only 2% coverage)
    features = [f for f in features if not f.startswith("f_cg_")]
    print(f"  after dropping cg_*: {len(features)}")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    md = ["# v3 Multi-Model Walk-Forward Training\n"]
    md.append(f"Train: {len(train)} rows | Test (held-out): {len(test)} rows\n")
    md.append(f"Held-out from: {HELD_OUT_FROM}\n")
    md.append(f"Features: {len(features)} (≥40% coverage, no cg_*)\n")
    md.append("\n")

    summary_table = []
    for tname, hor_col, thr in TARGETS:
        n_pos_tr = sum(1 for r in train if (r.get(hor_col) or 0) >= thr)
        n_pos_te = sum(1 for r in test  if (r.get(hor_col) or 0) >= thr)
        print(f"\n=== {tname} ({hor_col} ≥ {thr*100:.0f}%): "
              f"train n_pos={n_pos_tr}/{len(train)}, test n_pos={n_pos_te}/{len(test)} ===")
        if n_pos_tr < 30:
            print("  too few positives in train"); continue
        md.append(f"## {tname} ({hor_col} ≥ {thr*100:.0f}%)\n")
        md.append(f"Train n_pos: {n_pos_tr}/{len(train)} ({n_pos_tr*100/len(train):.1f}%)\n")
        md.append(f"Test n_pos:  {n_pos_te}/{len(test)} ({n_pos_te*100/max(len(test),1):.1f}%)\n\n")
        md.append("| model | walk-forward CV AUC | held-out test AUC |\n")
        md.append("|---|---:|---:|\n")
        target_results = []
        for mname, factory in MODEL_FACTORIES.items():
            print(f"  training {mname}...")
            oos, fold_aucs = walk_forward(train, features, hor_col, thr, factory)
            valid = ~np.isnan(oos) if oos is not None else None
            y_train = np.array([1 if (r.get(hor_col) or 0) >= thr else 0 for r in train])
            try:
                cv_auc = roc_auc_score(y_train[valid], oos[valid]) \
                          if valid is not None and valid.sum() and y_train[valid].sum() and (1-y_train[valid]).sum() \
                          else float("nan")
            except: cv_auc = float("nan")
            # Final model on full train, eval on test
            model, test_pred, test_auc, medians = fit_final_and_test(
                train, test, features, hor_col, thr, factory)
            md.append(f"| {mname} | {cv_auc:.4f} | {test_auc:.4f} |\n")
            target_results.append({
                "name": mname, "cv_auc": cv_auc, "test_auc": test_auc,
                "model": model, "test_pred": test_pred, "medians": medians,
            })
            print(f"    cv_auc={cv_auc:.4f}  test_auc={test_auc:.4f}")
        md.append("\n")
        # Pick best by CV (NOT test — avoid overfitting to held-out)
        valid_results = [r for r in target_results if not math.isnan(r["cv_auc"])]
        if not valid_results:
            md.append("**no valid models**\n\n"); continue
        best = max(valid_results, key=lambda r: r["cv_auc"])
        md.append(f"**Best by CV AUC: `{best['name']}` cv={best['cv_auc']:.4f} test={best['test_auc']:.4f}**\n\n")
        # Save best model + metadata
        model_path = MODEL_DIR / f"{tname}_{best['name']}.pkl"
        with model_path.open("wb") as f:
            pickle.dump({
                "model": best["model"], "features": features,
                "medians": best["medians"], "hor_col": hor_col, "thr": thr,
                "model_name": best["name"], "cv_auc": best["cv_auc"],
                "test_auc": best["test_auc"], "test_pred": best["test_pred"].tolist(),
            }, f)
        # Also save a CSV with predictions for later analysis
        pred_csv = MODEL_DIR / f"{tname}_{best['name']}_test_preds.csv"
        with pred_csv.open("w") as f:
            f.write("sig_dt,coin,variant,pred,fwd_max_3m,fwd_min_3m,fwd_max_5m,fwd_min_5m,fwd_max_max,natural_exit\n")
            for r, p in zip(test, best["test_pred"]):
                f.write(f"{r.get('sig_dt')},{r.get('coin')},{r.get('variant')},"
                        f"{float(p):.6f},{r.get('fwd_max_3m')},{r.get('fwd_min_3m')},"
                        f"{r.get('fwd_max_5m')},{r.get('fwd_min_5m')},"
                        f"{r.get('fwd_max_max')},{r.get('natural_exit_net')}\n")
        summary_table.append((tname, best["name"], best["cv_auc"], best["test_auc"]))

    # Final summary
    md.append("\n## Summary\n\n")
    md.append("| target | best model | CV AUC | test AUC |\n")
    md.append("|---|---|---:|---:|\n")
    for tname, mname, cv, te in summary_table:
        md.append(f"| {tname} | {mname} | {cv:.4f} | {te:.4f} |\n")

    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text("".join(md))
    print(f"\nwrote {OUT_REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
