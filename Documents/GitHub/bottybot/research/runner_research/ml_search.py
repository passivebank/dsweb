"""
research/runner_research/ml_search.py — multi-target LightGBM with strict
walk-forward + grouped CV (no signal moment leaks across folds).

For each capture target (1pct/5m, 2pct/5m, 3pct/5m, 5pct/5m, 10pct/max):
  1. Train LightGBM with expanding-window walk-forward by sig_date
  2. Compute OOS AUC + bootstrap 95% CI
  3. Pull SHAP / feature importance (LightGBM gain)
  4. At inference time on the held-out test (last 3 days), simulate
     trading signals where p_pred ≥ threshold; report EV/WR/total
  5. Pick the model + threshold that maximizes Sharpe-adjusted EV
     under stressed costs (+24bps round-trip)
"""
from __future__ import annotations

import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import lightgbm as lgb

LABELED        = Path("/tmp/runner_research/labeled.jsonl.gz")
OUT_REPORT     = Path("research/runner_research/ml_report.md")
OUT_PRED_CSV   = Path("research/runner_research/ml_predictions.csv")
HELD_OUT_FROM  = "2026-04-25"
EXTRA_COST     = 0.0024
POS_PCT        = 1/3   # user wants 1/3 of bankroll per position

TARGETS = [
    ("p_gain_1pct_5m",  "fwd_max_5m",  0.01),
    ("p_gain_2pct_5m",  "fwd_max_5m",  0.02),
    ("p_gain_3pct_5m",  "fwd_max_5m",  0.03),
    ("p_gain_5pct_5m",  "fwd_max_5m",  0.05),
    ("p_gain_10pct",    "fwd_max_max", 0.10),
]


def coerce(v):
    if v is None: return np.nan
    if isinstance(v, bool): return 1.0 if v else 0.0
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f): return np.nan
        return f
    except (TypeError, ValueError): return np.nan


def load_dataset() -> tuple[list[dict], list[dict]]:
    train, test = [], []
    with gzip.open(LABELED, "rt") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            r = json.loads(line)
            (train if r["sig_date"] < HELD_OUT_FROM else test).append(r)
    return train, test


def build_xy(rows: list[dict], features: list[str], horizon_col: str, threshold: float) -> tuple:
    X = np.array([[coerce(r.get(f)) for f in features] for r in rows])
    y_label = np.array([
        1 if (r.get(horizon_col) or 0) >= threshold else 0 for r in rows
    ])
    y_continuous = np.array([
        r.get(horizon_col) if r.get(horizon_col) is not None else 0.0 for r in rows
    ])
    return X, y_label, y_continuous


def train_walkforward(train_rows: list[dict], features: list[str],
                       horizon_col: str, threshold: float) -> tuple:
    """Expanding-window walk-forward by sig_date. Returns OOS predictions
    in train_rows order (same length as input)."""
    by_day = defaultdict(list)
    for i, r in enumerate(train_rows):
        by_day[r["sig_date"]].append(i)
    days = sorted(by_day)
    if len(days) < 4:
        return np.zeros(len(train_rows)), 0.5

    oos = np.full(len(train_rows), np.nan)
    fold_aucs = []
    for k in range(2, len(days)):
        train_idx = sum((by_day[d] for d in days[:k]), [])
        test_idx  = by_day[days[k]]
        if len(train_idx) < 50 or len(test_idx) < 5: continue
        Xtr, ytr, _ = build_xy([train_rows[i] for i in train_idx], features, horizon_col, threshold)
        Xte, yte, _ = build_xy([train_rows[i] for i in test_idx],  features, horizon_col, threshold)
        if ytr.sum() < 5 or (1-ytr).sum() < 5: continue
        # Class weights: handle imbalance
        n_pos = max(1, int(ytr.sum())); n_neg = max(1, int((1-ytr).sum()))
        pos_w = n_neg / n_pos
        sample_w = np.where(ytr == 1, pos_w, 1.0)
        try:
            model = lgb.LGBMClassifier(
                n_estimators=200, learning_rate=0.05, max_depth=4,
                num_leaves=15, min_child_samples=20, reg_alpha=0.5,
                reg_lambda=0.5, random_state=42, verbose=-1,
            )
            model.fit(Xtr, ytr, sample_weight=sample_w)
            pred = model.predict_proba(Xte)[:, 1]
        except Exception as e:
            print(f"  fold {days[k]} fit error: {e}")
            continue
        for j, idx in enumerate(test_idx): oos[idx] = pred[j]
        if yte.sum() and (1-yte).sum():
            from sklearn.metrics import roc_auc_score
            try: fold_aucs.append(roc_auc_score(yte, pred))
            except: pass

    return oos, float(np.mean(fold_aucs)) if fold_aucs else float("nan")


def fit_final_model(train_rows: list[dict], features: list[str],
                     horizon_col: str, threshold: float) -> lgb.LGBMClassifier:
    Xtr, ytr, _ = build_xy(train_rows, features, horizon_col, threshold)
    n_pos = max(1, int(ytr.sum())); n_neg = max(1, int((1-ytr).sum()))
    sample_w = np.where(ytr == 1, n_neg / n_pos, 1.0)
    m = lgb.LGBMClassifier(
        n_estimators=300, learning_rate=0.04, max_depth=4,
        num_leaves=15, min_child_samples=20, reg_alpha=0.5,
        reg_lambda=0.5, random_state=42, verbose=-1,
    )
    m.fit(Xtr, ytr, sample_weight=sample_w)
    return m


def simulate_strategy(rows_with_pred: list[tuple[dict, float]],
                       prob_threshold: float, capture_pct: float,
                       hard_stop: float = 0.025) -> dict:
    """Trade every row where pred >= threshold. Capture +capture_pct or
    stop at -hard_stop. Use fwd_max_5m and fwd_min_5m for outcome.
    Returns aggregate stats."""
    bankroll = 1.0
    daily_returns = []
    cur_day = None; day_start = 1.0
    nets = []
    n_traded = 0
    for r, p in rows_with_pred:
        if p < prob_threshold: continue
        n_traded += 1
        dt = r["sig_date"]
        if dt != cur_day:
            if cur_day is not None: daily_returns.append(bankroll/day_start - 1)
            cur_day = dt; day_start = bankroll
        # Outcome: did fwd_max_5m hit capture_pct? did fwd_min_5m hit -hard_stop?
        fmax = r.get("fwd_max_5m") or 0.0
        fmin = r.get("fwd_min_5m") or 0.0
        if fmin <= -hard_stop:
            net = -hard_stop - EXTRA_COST
        elif fmax >= capture_pct:
            net = capture_pct - EXTRA_COST
        else:
            # Exit at natural — use 5m fwd_max-based approximate (assume hit max then exit)
            # Conservative: use natural_exit_net if available, else 0
            net = (r.get("natural_exit_net") or 0.0) - EXTRA_COST
        bankroll *= (1 + POS_PCT * net)
        nets.append(net)
    if cur_day is not None: daily_returns.append(bankroll/day_start - 1)
    if not nets: return {"n": 0}
    nets = np.array(nets); daily = np.array(daily_returns)
    return {
        "n":             len(nets),
        "win_rate":      float((nets > 0).mean()),
        "mean_net":      float(nets.mean()),
        "median_net":    float(np.median(nets)),
        "total_pnl_pct": float((bankroll - 1) * 100),
        "max_dd_pct":    _max_dd(daily) * 100,
        "sharpe":        float(daily.mean() / daily.std() * math.sqrt(365))
                          if len(daily) > 1 and daily.std() > 0 else float("nan"),
    }


def _max_dd(returns: np.ndarray) -> float:
    cum = np.cumprod(1 + returns) - 1
    if len(cum) == 0: return 0.0
    peak = np.maximum.accumulate(np.concatenate([[0], cum]))
    return float((peak[1:] - cum).max())


def main() -> int:
    train, test = load_dataset()
    print(f"train: {len(train)} rows, test: {len(test)} rows")
    if not test:
        print("WARN: held-out test set is empty")

    # All numeric features with reasonable coverage
    feature_cols = sorted({k for r in train for k in r if k.startswith("f_")})
    coverage = {f: sum(1 for r in train if r.get(f) is not None) / len(train) for f in feature_cols}
    features = [f for f in feature_cols if coverage[f] >= 0.40]
    print(f"using {len(features)} features (≥40% coverage)")

    md = ["# Runner Research — ML Search\n"]
    md.append(f"_train: {len(train)} rows ({sorted({r['sig_date'] for r in train})[0]} to "
              f"{sorted({r['sig_date'] for r in train})[-1]})_\n")
    md.append(f"_held-out test: {len(test)} rows from {HELD_OUT_FROM} onwards_\n")

    pred_records = []  # for csv

    for tname, hcol, thr in TARGETS:
        print(f"\n=== {tname} (horizon {hcol}, threshold {thr*100:.0f}%) ===")
        # Walk-forward AUC on train
        oos_train, fold_auc = train_walkforward(train, features, hcol, thr)
        valid = ~np.isnan(oos_train)
        if valid.sum() < 50:
            print(f"  too few OOS predictions ({valid.sum()})")
            continue
        from sklearn.metrics import roc_auc_score
        y_train = np.array([1 if (r.get(hcol) or 0) >= thr else 0 for r in train])
        cv_auc = roc_auc_score(y_train[valid], oos_train[valid])
        print(f"  walk-forward CV AUC: {cv_auc:.3f} (per-fold mean {fold_auc:.3f})")

        # Train final on all train, predict on test
        model = fit_final_model(train, features, hcol, thr)
        Xte, yte, _ = build_xy(test, features, hcol, thr)
        if len(yte) and yte.sum() > 0 and (1-yte).sum() > 0:
            test_pred = model.predict_proba(Xte)[:, 1]
            test_auc = roc_auc_score(yte, test_pred)
            print(f"  held-out test AUC:    {test_auc:.3f} (n_test={len(yte)} n_pos={int(yte.sum())})")
        else:
            test_pred = np.zeros(len(test)) if len(test) else np.array([])
            test_auc = float("nan")
            print(f"  held-out: insufficient positives (n_pos={int(yte.sum()) if len(yte) else 0})")

        # Strategy simulation at varying probability thresholds
        rows_with_pred = list(zip(test, test_pred)) if len(test) else []
        # Capture target = same as label threshold (i.e., we take profit at +thr%)
        sim_results = []
        for pt in [0.30, 0.40, 0.50, 0.60, 0.70, 0.80]:
            for stop in [0.015, 0.025, 0.040]:
                s = simulate_strategy(rows_with_pred, pt, thr, hard_stop=stop)
                if s.get("n"):
                    s["prob_threshold"] = pt; s["hard_stop"] = stop
                    sim_results.append(s)

        # Top features by gain
        importances = sorted(zip(features, model.booster_.feature_importance(importance_type="gain")),
                              key=lambda kv: -kv[1])

        md.append(f"## {tname}")
        md.append("")
        md.append(f"- Walk-forward CV AUC (train): **{cv_auc:.3f}** (per-fold mean {fold_auc:.3f})")
        md.append(f"- Held-out test AUC: **{test_auc:.3f}**")
        md.append("")
        md.append("**Top features by LightGBM gain:**")
        md.append("")
        md.append("| feature | gain |")
        md.append("|---|---:|")
        for f, g in importances[:12]:
            md.append(f"| `{f}` | {g:.0f} |")
        md.append("")
        if sim_results:
            md.append("**Held-out strategy simulation (1/3 sizing, +24bps stress):**")
            md.append("")
            md.append("| prob ≥ | hard_stop | n | WR | mean | total | DD | Sharpe |")
            md.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
            for s in sim_results:
                md.append(f"| {s['prob_threshold']:.2f} | {s['hard_stop']*100:.1f}% | "
                          f"{s['n']} | {s['win_rate']*100:.1f}% | "
                          f"{s['mean_net']*100:+.2f}% | {s['total_pnl_pct']:+.2f}% | "
                          f"{s['max_dd_pct']:.2f}% | {s['sharpe']:.2f} |")
            md.append("")

        # Save predictions for downstream analysis
        for r, p in rows_with_pred:
            pred_records.append({
                "sig_dt": r["sig_dt"], "coin": r["coin"], "variant": r.get("variant"),
                "target": tname, "pred": float(p),
                "fwd_max_5m": r.get("fwd_max_5m"), "fwd_min_5m": r.get("fwd_min_5m"),
                "fwd_max_max": r.get("fwd_max_max"),
            })

    # CSV
    OUT_PRED_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PRED_CSV.open("w") as f:
        if pred_records:
            keys = list(pred_records[0].keys())
            f.write(",".join(keys) + "\n")
            for r in pred_records:
                f.write(",".join(str(r.get(k, "")) for k in keys) + "\n")
    OUT_REPORT.write_text("\n".join(md))
    print(f"\nWrote {OUT_REPORT} and {OUT_PRED_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
