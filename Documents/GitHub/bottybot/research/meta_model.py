"""
research/meta_model.py — Penalized logistic regression meta-filter.

Replaces brittle threshold hunting as the core optimization engine.
Uses L2-regularized logistic regression (sklearn) with cross-validated
regularization strength. Separate models per variant.

Design philosophy:
  - Weak features collapse toward zero via regularization.
  - Interpretable: coefficients can be inspected.
  - Stable: robust to small changes in training set.
  - No look-ahead: only uses entry-time features.
  - Trained only on the provided training set.

The meta-model score is a probability of winning (net_pct > 0).
The threshold for "take this trade" defaults to 0.55 but is tunable.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np

from .config import FEATURES_BY_VARIANT, LIVE_VARIANTS


# ── Feature extraction ────────────────────────────────────────────────────────

def _extract(features: dict, feat_list: list[str]) -> np.ndarray:
    """Extract a feature vector from a features dict.

    Missing values are imputed with 0 (after the has_feat mask).
    Returns array of shape (2 * len(feat_list),): [values, has_feat_mask].
    The has_feat mask is 1 if the feature was present, 0 if imputed.
    This lets the model distinguish "zero" from "missing".
    """
    vals = np.zeros(len(feat_list), dtype=np.float64)
    mask = np.zeros(len(feat_list), dtype=np.float64)
    for j, k in enumerate(feat_list):
        v = features.get(k)
        if v is None:
            continue
        if isinstance(v, bool):
            vals[j] = float(v)
            mask[j] = 1.0
        else:
            try:
                vals[j] = float(v)
                mask[j] = 1.0
            except (TypeError, ValueError):
                pass
    return np.concatenate([vals, mask])


def build_X_y(events: list[dict], variant: str) -> tuple[np.ndarray, np.ndarray]:
    """Build feature matrix and label vector for a variant.

    Args:
        events:  list of event dicts (must all be for the given variant)
        variant: variant name (determines which features to use)

    Returns:
        X: float64 array of shape (n, 2*n_features)
        y: int8 array of shape (n,) — 1 if net_pct > 0, else 0
    """
    feat_list = FEATURES_BY_VARIANT.get(variant, [])
    rows = []
    labels = []
    for e in events:
        if e["variant"] != variant:
            continue
        row = _extract(e["features"], feat_list)
        rows.append(row)
        labels.append(1 if e["net_pct"] > 0.0 else 0)

    if not rows:
        return np.empty((0, 2 * len(feat_list))), np.empty(0, dtype=np.int8)

    return np.array(rows, dtype=np.float64), np.array(labels, dtype=np.int8)


# ── Model ─────────────────────────────────────────────────────────────────────

class MetaModel:
    """Per-variant L2-regularized logistic regression meta-filter.

    Usage:
        model = MetaModel(variant="R7_STAIRCASE")
        model.fit(train_events)  # train on training window
        prob = model.predict_proba(features_dict)  # score one signal
        passed = model.passes(features_dict, threshold=0.55)
    """

    def __init__(
        self,
        variant: str,
        threshold: float = 0.55,
        cv_Cs: int = 10,
        max_iter: int = 1000,
    ) -> None:
        if variant not in LIVE_VARIANTS:
            raise ValueError(f"Unknown variant: {variant}")
        self.variant   = variant
        self.threshold = threshold
        self.cv_Cs     = cv_Cs
        self.max_iter  = max_iter
        self._model    = None
        self._feat_list = FEATURES_BY_VARIANT.get(variant, [])
        self.train_n   = 0
        self.train_wr  = 0.0
        self.coef_     = None
        self.C_        = None

    def fit(self, train_events: list[dict]) -> "MetaModel":
        """Fit model on training events. Only events for this variant are used.

        Raises RuntimeError if fewer than 20 training examples or both classes
        not present.
        """
        from sklearn.linear_model import LogisticRegressionCV
        from sklearn.preprocessing import StandardScaler

        var_events = [e for e in train_events if e["variant"] == self.variant]
        if len(var_events) < 20:
            raise RuntimeError(
                f"Too few training examples for {self.variant}: {len(var_events)} < 20"
            )

        X, y = build_X_y(var_events, self.variant)
        if len(np.unique(y)) < 2:
            raise RuntimeError(
                f"Only one class present in training data for {self.variant}"
            )

        self.train_n  = len(y)
        self.train_wr = float(y.mean())

        # Scale features — important for L2 penalty to be meaningful
        self._scaler = StandardScaler()
        X_scaled = self._scaler.fit_transform(X)

        # Cross-validated C selection on training set only
        # Cs range: strong regularization (C=0.001) to weak (C=100)
        Cs = np.logspace(-3, 2, 20)
        clf = LogisticRegressionCV(
            Cs=Cs,
            cv=min(5, max(2, self.train_n // 10)),
            max_iter=self.max_iter,
            class_weight="balanced",  # handle class imbalance
            scoring="neg_log_loss",
            n_jobs=-1,
            random_state=42,
        )
        clf.fit(X_scaled, y)

        self._model = clf
        self.C_ = float(clf.C_[0])
        self.coef_ = clf.coef_[0].tolist()

        return self

    def predict_proba(self, features: dict) -> float:
        """Return P(win | features) for a single signal."""
        if self._model is None:
            raise RuntimeError("Model not fitted. Call fit() first.")
        x = _extract(features, self._feat_list).reshape(1, -1)
        x_scaled = self._scaler.transform(x)
        return float(self._model.predict_proba(x_scaled)[0, 1])

    def passes(self, features: dict, variant: str) -> bool:
        """Return True if this signal should be traded (P(win) > threshold)."""
        if variant != self.variant:
            return False
        try:
            prob = self.predict_proba(features)
            return prob > self.threshold
        except Exception:
            return False

    def top_features(self, n: int = 10) -> list[tuple[str, float]]:
        """Return the top-n features by absolute coefficient weight."""
        if self.coef_ is None:
            return []
        n_feats = len(self._feat_list)
        # Only use value coefficients, not has_feat indicators
        names_vals = list(zip(self._feat_list, self.coef_[:n_feats]))
        names_vals.sort(key=lambda x: abs(x[1]), reverse=True)
        return names_vals[:n]

    def save(self, path: Path) -> None:
        """Save model config and weights to a JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "variant":   self.variant,
            "threshold": self.threshold,
            "train_n":   self.train_n,
            "train_wr":  self.train_wr,
            "C":         self.C_,
            "coef":      self.coef_,
            "feat_list": self._feat_list,
            "scaler_mean":  self._scaler.mean_.tolist() if self._scaler else [],
            "scaler_scale": self._scaler.scale_.tolist() if self._scaler else [],
        }
        path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: Path) -> "MetaModel":
        """Load a previously saved model."""
        from sklearn.preprocessing import StandardScaler
        import numpy as np

        data = json.loads(Path(path).read_text())
        m = cls(variant=data["variant"], threshold=data["threshold"])
        m.train_n  = data["train_n"]
        m.train_wr = data["train_wr"]
        m.C_       = data["C"]
        m.coef_    = data["coef"]
        m._feat_list = data["feat_list"]

        # Rebuild scaler
        scaler = StandardScaler()
        scaler.mean_  = np.array(data["scaler_mean"])
        scaler.scale_ = np.array(data["scaler_scale"])
        m._scaler = scaler

        # Rebuild sklearn model shell for prediction
        from sklearn.linear_model import LogisticRegressionCV
        # We can't fully restore LogisticRegressionCV without the full state,
        # but we can use the intercept + coef directly.
        m._model = _DirectLogisticModel(
            coef=np.array(data["coef"]),
            intercept=0.0,  # will be inferred below
        )
        # The intercept is embedded in the bias term of LogisticRegressionCV.
        # Since we need it for prediction, we store it separately.
        # Check if intercept_ was saved:
        if "intercept" in data:
            m._model.intercept = data["intercept"]
        return m


class _DirectLogisticModel:
    """Minimal logistic model for inference from saved coefficients."""

    def __init__(self, coef: np.ndarray, intercept: float = 0.0) -> None:
        self.coef_      = coef
        self.intercept_ = np.array([intercept])

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        logit = X @ self.coef_ + self.intercept_[0]
        p = 1.0 / (1.0 + np.exp(-logit))
        return np.column_stack([1 - p, p])


# ── Multi-variant meta-model (combines R7 and R5 models) ─────────────────────

class MultiVariantMetaModel:
    """Wrapper that holds one MetaModel per live variant.

    Usage:
        model = MultiVariantMetaModel()
        model.fit(train_events)
        passed = model.passes(features, variant)
    """

    def __init__(
        self,
        threshold: float = 0.55,
        min_train_n: int = 20,
    ) -> None:
        self.threshold    = threshold
        self.min_train_n  = min_train_n
        self._models: dict[str, MetaModel] = {}
        self.fit_errors: dict[str, str] = {}

    def fit(self, train_events: list[dict]) -> "MultiVariantMetaModel":
        """Fit one model per variant on the training events."""
        for v in LIVE_VARIANTS:
            try:
                m = MetaModel(variant=v, threshold=self.threshold)
                m.fit(train_events)
                self._models[v] = m
            except RuntimeError as e:
                self.fit_errors[v] = str(e)
        return self

    def passes(self, features: dict, variant: str) -> bool:
        """Return True if signal passes the meta-filter for its variant."""
        m = self._models.get(variant)
        if m is None:
            return False
        return m.passes(features, variant)

    def predict_proba(self, features: dict, variant: str) -> float:
        """Return win probability for a signal."""
        m = self._models.get(variant)
        if m is None:
            return 0.0
        try:
            return m.predict_proba(features)
        except Exception:
            return 0.0

    def summary(self) -> str:
        """Return a human-readable summary of fitted models."""
        lines = ["  MetaModel summary:"]
        for v in LIVE_VARIANTS:
            m = self._models.get(v)
            if m is None:
                err = self.fit_errors.get(v, "not fitted")
                lines.append(f"    {v}: FAILED — {err}")
                continue
            top = m.top_features(5)
            feat_str = ", ".join(f"{k}={v:.2f}" for k, v in top)
            lines.append(
                f"    {v}: C={m.C_:.4f}  train_n={m.train_n}  "
                f"train_wr={m.train_wr:.0%}  threshold={m.threshold}"
            )
            lines.append(f"      Top features: {feat_str}")
        return "\n".join(lines)


# ── Factory helpers for walk_forward_oos ─────────────────────────────────────

def meta_model_factory(variant: str, threshold: float = 0.55):
    """Return a strategy_factory for use with evaluate.walk_forward_oos.

    The returned factory takes train_events and returns a passes() callable.
    """
    def factory(train_events: list[dict]):
        try:
            m = MetaModel(variant=variant, threshold=threshold)
            m.fit(train_events)
            return m.passes
        except RuntimeError:
            # Not enough training data — abstain (never trade)
            return lambda features, variant: False
    return factory


def champion_and_meta_factory(variant: str, threshold: float = 0.55):
    """Strategy factory: trade only if BOTH champion AND meta-model agree."""
    from .config import champion_passes as cp

    def factory(train_events: list[dict]):
        try:
            m = MetaModel(variant=variant, threshold=threshold)
            m.fit(train_events)

            def combined(features, v):
                return cp(features, v) and m.passes(features, v)

            return combined
        except RuntimeError:
            return lambda features, v: False

    return factory
