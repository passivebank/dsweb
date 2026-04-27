"""Train the final ML model with NAMED features, save model + feature list +
training-time medians for live inference. Outputs to a single deployable
artifact directory: research/runner_research/deploy/."""
import gzip, json, math, sys
from pathlib import Path

import numpy as np
import lightgbm as lgb

LABELED       = Path("/tmp/runner_research/labeled.jsonl.gz")
DEPLOY_DIR    = Path("research/runner_research/deploy")
HELD_OUT_FROM = "2026-04-25"

TARGET_HORIZON   = "fwd_max_5m"
TARGET_THRESHOLD = 0.05


def coerce(v):
    if v is None: return np.nan
    if isinstance(v, bool): return 1.0 if v else 0.0
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f): return np.nan
        return f
    except (TypeError, ValueError): return np.nan


def main():
    train = []
    with gzip.open(LABELED, "rt") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            r = json.loads(line)
            if r["sig_date"] < HELD_OUT_FROM:
                train.append(r)

    feature_cols = sorted({k for r in train for k in r if k.startswith("f_")})
    coverage = {f: sum(1 for r in train if r.get(f) is not None) / len(train) for f in feature_cols}
    features = [f for f in feature_cols if coverage[f] >= 0.40]
    print(f"features: {features}")

    # Compute medians for imputation at inference time
    medians = {}
    for f in features:
        vals = [coerce(r.get(f)) for r in train]
        vals = [v for v in vals if not (isinstance(v, float) and math.isnan(v))]
        medians[f] = float(np.median(vals)) if vals else 0.0

    # Build training matrix using ordered feature list
    X = np.zeros((len(train), len(features)))
    for i, r in enumerate(train):
        for j, f in enumerate(features):
            v = coerce(r.get(f))
            X[i, j] = v if not (isinstance(v, float) and math.isnan(v)) else medians[f]
    y = np.array([1 if (r.get(TARGET_HORIZON) or 0) >= TARGET_THRESHOLD else 0 for r in train])

    n_pos = max(1, int(y.sum())); n_neg = max(1, int((1-y).sum()))
    sample_w = np.where(y == 1, n_neg/n_pos, 1.0)

    # Train with explicit feature names
    train_dataset = lgb.Dataset(X, label=y, weight=sample_w, feature_name=features)
    params = dict(objective="binary", learning_rate=0.04, max_depth=4, num_leaves=15,
                   min_child_samples=20, reg_alpha=0.5, reg_lambda=0.5, verbose=-1)
    booster = lgb.train(params, train_dataset, num_boost_round=300)

    DEPLOY_DIR.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(DEPLOY_DIR / "model.txt"))
    (DEPLOY_DIR / "features.json").write_text(json.dumps({
        "features":          features,
        "medians":           medians,
        "target_horizon":    TARGET_HORIZON,
        "target_threshold":  TARGET_THRESHOLD,
        "trained_at":        "2026-04-27",
        "trained_on":        f"{len(train)} signal moments before {HELD_OUT_FROM}",
        "default_prob_threshold": 0.40,
        "default_hard_stop_pct":  0.015,
    }, indent=2))
    print(f"saved {DEPLOY_DIR}/model.txt and {DEPLOY_DIR}/features.json")
    print(f"feature count: {len(features)}")

if __name__ == "__main__":
    sys.exit(main() or 0)
