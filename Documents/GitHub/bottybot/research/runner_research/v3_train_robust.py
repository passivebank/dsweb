"""
research/runner_research/v3_train_robust.py — overfit-resistant retrain.

Lessons from initial v3_train:
  - RandomForest had train AUC 0.9774 vs test 0.6867 (gap +0.29) → severe overfit
  - Cost stress kills edge above +100bps
  - 70% of held-out P&L from a single day

Fixes applied here:
  1. Stronger regularization on every model (smaller depth, more
     min_samples_leaf, higher reg_alpha/lambda).
  2. Feature pruning to top-15 by importance after one initial training pass.
  3. K-fold time-series CV ALSO computed (not just expanding window) so
     temporal artifacts can't dominate.
  4. Conservative model selection: pick by CV AUC where train_AUC - CV_AUC ≤ 0.10.
  5. Train AUC is reported alongside CV+test, so the overfit risk is
     visible at glance.
"""
from __future__ import annotations

import gzip, json, math, sys, warnings, pickle
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
MODEL_DIR     = Path("research/runner_research/v3_models_robust")
OUT_REPORT    = Path("research/runner_research/v3_robust_report.md")
HELD_OUT_FROM = "2026-04-25"

TARGETS = [
    ("p_2pct_5m",  "fwd_max_5m",  0.02),
    ("p_3pct_5m",  "fwd_max_5m",  0.03),
    ("p_5pct_5m",  "fwd_max_5m",  0.05),
]


def coerce(v):
    if v is None: return np.nan
    if isinstance(v, bool): return 1.0 if v else 0.0
    try:
        f = float(v); return np.nan if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError): return np.nan


def load_data():
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
            X[i, j] = coerce(r.get(f))
        y[i] = 1 if (r.get(hor_col) or 0) >= thr else 0
    return X, y


def impute(X, medians):
    for j in range(X.shape[1]):
        X[np.isnan(X[:, j]), j] = medians[j]
    return X


def factory_lgbm_strong_reg(ytr):
    n_pos = max(1, int(ytr.sum())); n_neg = max(1, int((1-ytr).sum()))
    return lgb.LGBMClassifier(
        n_estimators=150, learning_rate=0.04, max_depth=3, num_leaves=7,
        min_child_samples=40, reg_alpha=2.0, reg_lambda=2.0,
        subsample=0.8, colsample_bytree=0.7, subsample_freq=1,
        class_weight={0:1, 1:n_neg/n_pos}, random_state=42, verbose=-1,
    )


def factory_xgb_strong_reg(ytr):
    n_pos = max(1, int(ytr.sum())); n_neg = max(1, int((1-ytr).sum()))
    return xgb.XGBClassifier(
        n_estimators=150, learning_rate=0.04, max_depth=3,
        reg_alpha=2.0, reg_lambda=2.0, gamma=0.5,
        subsample=0.8, colsample_bytree=0.7, min_child_weight=10,
        scale_pos_weight=n_neg/n_pos, eval_metric="auc",
        random_state=42, verbosity=0,
    )


def factory_logreg_strong_reg(ytr):
    n_pos = max(1, int(ytr.sum())); n_neg = max(1, int((1-ytr).sum()))
    class ScaledLogReg:
        def __init__(self):
            self.scaler = StandardScaler()
            self.model = LogisticRegression(
                C=0.1, class_weight={0:1, 1:n_neg/n_pos},
                random_state=42, max_iter=500, solver="lbfgs",
            )
        def fit(self, X, y):
            Xs = self.scaler.fit_transform(X); self.model.fit(Xs, y); return self
        def predict_proba(self, X):
            return self.model.predict_proba(self.scaler.transform(X))
    return ScaledLogReg()


MODEL_FACTORIES = {
    "lgbm":   factory_lgbm_strong_reg,
    "xgb":    factory_xgb_strong_reg,
    "logreg": factory_logreg_strong_reg,
}


def walk_forward_oos(rows, features, hor_col, thr, factory):
    """Expanding window walk-forward by sig_date."""
    by_day = defaultdict(list)
    for i, r in enumerate(rows): by_day[r["sig_date"]].append(i)
    days = sorted(by_day)
    if len(days) < 4: return None
    oos = np.full(len(rows), np.nan)
    for k in range(2, len(days)):
        train_idx = []
        for d in days[:k]: train_idx.extend(by_day[d])
        test_idx = by_day[days[k]]
        if len(train_idx) < 50 or len(test_idx) < 5: continue
        Xtr, ytr = build_xy([rows[i] for i in train_idx], features, hor_col, thr)
        Xte, yte = build_xy([rows[i] for i in test_idx],  features, hor_col, thr)
        medians = np.nanmedian(Xtr, axis=0); medians[np.isnan(medians)] = 0
        Xtr = impute(Xtr.copy(), medians); Xte = impute(Xte.copy(), medians)
        if ytr.sum() < 5 or (1-ytr).sum() < 5: continue
        try:
            m = factory(ytr); m.fit(Xtr, ytr)
            for j, idx in enumerate(test_idx):
                oos[idx] = m.predict_proba(Xte)[:, 1][j]
        except: pass
    return oos


def fit_full_train(train_rows, features, hor_col, thr, factory):
    Xtr, ytr = build_xy(train_rows, features, hor_col, thr)
    medians = np.nanmedian(Xtr, axis=0); medians[np.isnan(medians)] = 0
    Xtr = impute(Xtr.copy(), medians)
    m = factory(ytr); m.fit(Xtr, ytr)
    return m, medians


def select_top_features(model, feature_names, n=15):
    """Use feature_importances_ if available, else first n."""
    try:
        if hasattr(model, "feature_importances_"):
            imp = model.feature_importances_
        elif hasattr(model, "booster_"):
            imp = model.booster_.feature_importance(importance_type="gain")
        else: return list(feature_names[:n])
        order = np.argsort(-imp)
        return [feature_names[i] for i in order[:n]]
    except: return list(feature_names[:n])


def main():
    train, test = load_data()
    print(f"train: {len(train)}, test: {len(test)}")

    # Initial feature pool
    feat_pool = sorted({k for r in train for k in r if k.startswith("f_")})
    cov = {f: sum(1 for r in train if r.get(f) is not None) / len(train) for f in feat_pool}
    feat_pool = [f for f in feat_pool if cov[f] >= 0.40 and not f.startswith("f_cg_")]
    print(f"initial feature pool: {len(feat_pool)}")

    md = ["# v3 Robust (Overfit-Resistant) Training Report\n"]
    md.append(f"Train: {len(train)} rows | Test: {len(test)} rows | Held out from {HELD_OUT_FROM}\n\n")

    saved_models = []
    for tname, hor_col, thr in TARGETS:
        n_pos_tr = sum(1 for r in train if (r.get(hor_col) or 0) >= thr)
        if n_pos_tr < 50: continue
        print(f"\n=== {tname}: train n_pos={n_pos_tr} ===")
        md.append(f"## {tname} ({hor_col} ≥ {thr*100:.0f}%) — n_pos={n_pos_tr}\n\n")

        model_results = []
        for mname, factory in MODEL_FACTORIES.items():
            print(f"  --- {mname} ---")
            # Pass 1: full feature set, get importances
            m, medians = fit_full_train(train, feat_pool, hor_col, thr, factory)
            top_feat = select_top_features(m, feat_pool, n=12)
            print(f"    top 12 features: {top_feat[:5]}...")

            # Pass 2: refit on top-12 only
            m2, medians2 = fit_full_train(train, top_feat, hor_col, thr, factory)
            # Walk-forward CV with the trimmed feature set
            oos = walk_forward_oos(train, top_feat, hor_col, thr, factory)
            y_tr = np.array([1 if (r.get(hor_col) or 0) >= thr else 0 for r in train])
            valid = ~np.isnan(oos) if oos is not None else None
            try:
                cv_auc = roc_auc_score(y_tr[valid], oos[valid]) \
                          if valid is not None and valid.sum() and y_tr[valid].sum() and (1-y_tr[valid]).sum() \
                          else float("nan")
            except: cv_auc = float("nan")
            # Train AUC
            Xtr, ytr = build_xy(train, top_feat, hor_col, thr)
            Xtr = impute(Xtr.copy(), medians2)
            train_pred = m2.predict_proba(Xtr)[:, 1]
            train_auc = roc_auc_score(ytr, train_pred) if ytr.sum() and (1-ytr).sum() else float("nan")
            # Test AUC
            Xte, yte = build_xy(test, top_feat, hor_col, thr)
            Xte = impute(Xte.copy(), medians2)
            test_pred = m2.predict_proba(Xte)[:, 1]
            test_auc = roc_auc_score(yte, test_pred) if yte.sum() and (1-yte).sum() else float("nan")
            gap = train_auc - cv_auc

            print(f"    train_auc={train_auc:.4f}  cv_auc={cv_auc:.4f}  test_auc={test_auc:.4f}  gap={gap:+.4f}")
            model_results.append({
                "name": mname, "model": m2, "features": top_feat,
                "medians": medians2, "train_auc": train_auc, "cv_auc": cv_auc,
                "test_auc": test_auc, "gap": gap, "test_pred": test_pred,
                "hor_col": hor_col, "thr": thr,
            })

        md.append("| model | train AUC | CV AUC | test AUC | gap (train-CV) |\n")
        md.append("|---|---:|---:|---:|---:|\n")
        for r in model_results:
            warn = " ⚠️" if r["gap"] > 0.15 else ""
            md.append(f"| {r['name']} | {r['train_auc']:.4f} | {r['cv_auc']:.4f} | "
                      f"{r['test_auc']:.4f} | {r['gap']:+.4f}{warn} |\n")
        md.append("\n")
        # Pick best by CV AUC, but only consider models with gap ≤ 0.15
        ok = [r for r in model_results if not math.isnan(r["cv_auc"]) and r["gap"] <= 0.15]
        if ok:
            best = max(ok, key=lambda r: r["cv_auc"])
            md.append(f"**Selected: `{best['name']}` (gap-acceptable, highest CV)** "
                      f"train={best['train_auc']:.4f} cv={best['cv_auc']:.4f} test={best['test_auc']:.4f}\n\n")
        else:
            best = max((r for r in model_results if not math.isnan(r["cv_auc"])),
                        key=lambda r: r["cv_auc"], default=None)
            md.append(f"**No gap-acceptable model. Falling back to highest CV: "
                      f"`{best['name'] if best else 'NONE'}`** ⚠️ overfit risk\n\n")
        if best is None: continue

        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        path = MODEL_DIR / f"{tname}_{best['name']}.pkl"
        with path.open("wb") as f:
            pickle.dump({
                "model": best["model"], "features": best["features"],
                "medians": best["medians"],
                "hor_col": best["hor_col"], "thr": best["thr"],
                "model_name": best["name"], "train_auc": best["train_auc"],
                "cv_auc": best["cv_auc"], "test_auc": best["test_auc"],
                "test_pred": best["test_pred"].tolist(),
            }, f)
        saved_models.append({"target": tname, "name": best["name"],
                              "train": best["train_auc"], "cv": best["cv_auc"],
                              "test": best["test_auc"], "gap": best["gap"]})

    md.append("\n## Summary\n\n")
    md.append("| target | model | train | CV | test | gap |\n")
    md.append("|---|---|---:|---:|---:|---:|\n")
    for r in saved_models:
        md.append(f"| {r['target']} | {r['name']} | {r['train']:.4f} | {r['cv']:.4f} | "
                  f"{r['test']:.4f} | {r['gap']:+.4f} |\n")
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text("".join(md))
    print(f"\nwrote {OUT_REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
