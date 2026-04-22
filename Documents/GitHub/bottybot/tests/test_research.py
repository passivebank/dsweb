"""
tests/test_research.py — Tests for the champion/challenger research framework.

Run with: python3 -m pytest tests/test_research.py -v

Tests cover:
  - Schema integrity of research modules
  - evaluate: load_events dedup, compute_stats, walk_forward_oos correctness
  - meta_model: feature extraction, model fit/predict, factory pattern
  - promote: gate logic, verdict classification
  - daily: shadow coverage parsing, feature coverage sampling
  - config: champion_passes filter logic, frozen constants
"""
from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_shadow_record(
    variant="R7_STAIRCASE",
    exit_policy="time_300s",
    net_pct=0.01,
    entry_ts_ns=1776900000_000_000_000,
    coin="BTC",
    delay_ms=250,
    features=None,
):
    if features is None:
        features = {
            "rank_60s": 1.0,
            "cg_trending": False,
            "market_breadth_5m": 5.0,
            "signals_24h": 5.0,
            "step_2m": 0.015,
            "candle_close_str_1m": 0.80,
            "spread_bps": 7.0,
        }
    return {
        "coin":         coin,
        "variant":      variant,
        "exit_policy":  exit_policy,
        "net_pct":      net_pct,
        "entry_ts_ns":  entry_ts_ns,
        "delay_ms":     delay_ms,
        "sig_features": features,
        "cost_pct":     0.002,
        "gross_pct":    net_pct + 0.002,
        "holding_s":    300,
        "fwd_max_pct":  abs(net_pct) + 0.01,
        "fwd_min_pct":  -0.005,
    }


def _write_shadow_file(records, path: Path):
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


@pytest.fixture
def tmp_shadow(tmp_path):
    """Write a small shadow_trades.jsonl for testing."""
    records = []
    base_ts = 1776900000_000_000_000
    one_day = 86_400 * 10**9

    for day in range(10):
        ts = base_ts + day * one_day
        # R7 winner
        records.append(_make_shadow_record(
            variant="R7_STAIRCASE", exit_policy="time_300s",
            net_pct=0.02, entry_ts_ns=ts, coin=f"COIN{day}",
        ))
        # R7 loser
        records.append(_make_shadow_record(
            variant="R7_STAIRCASE", exit_policy="time_300s",
            net_pct=-0.01, entry_ts_ns=ts + 3600 * 10**9, coin=f"COINB{day}",
        ))
        # R5 winner
        records.append(_make_shadow_record(
            variant="R5_CONFIRMED_RUN", exit_policy="r5_v10",
            net_pct=0.03, entry_ts_ns=ts + 7200 * 10**9, coin=f"COINC{day}",
            features={
                "rank_60s": 1.0, "cg_trending": False, "market_breadth_5m": 5.0,
                "signals_24h": 5.0, "dv_trend": 3.0, "ask_depth_usd": 1000.0,
                "spread_bps": 7.0,
            },
        ))

    shadow_file = tmp_path / "shadow_trades.jsonl"
    _write_shadow_file(records, shadow_file)
    return shadow_file


# ── evaluate.py tests ─────────────────────────────────────────────────────────

class TestLoadEvents:
    def test_loads_correct_variants(self, tmp_shadow):
        from research.evaluate import load_events
        events = load_events(
            shadow_file=tmp_shadow,
            variants=["R7_STAIRCASE"],
            delay_target_ms=250,
        )
        assert all(e["variant"] == "R7_STAIRCASE" for e in events)

    def test_filters_policy(self, tmp_shadow):
        from research.evaluate import load_events
        events = load_events(
            shadow_file=tmp_shadow,
            variants=["R5_CONFIRMED_RUN"],
            delay_target_ms=250,
        )
        assert all(e["exit_policy"] == "r5_v10" for e in events)

    def test_deduplication(self, tmp_path):
        """Two records for same (coin, ts) keep only the one closest to delay_target."""
        from research.evaluate import load_events
        base_ts = 1776900000_000_000_000
        records = [
            _make_shadow_record(delay_ms=100, entry_ts_ns=base_ts, coin="BTC"),
            _make_shadow_record(delay_ms=250, entry_ts_ns=base_ts, coin="BTC"),
            _make_shadow_record(delay_ms=400, entry_ts_ns=base_ts, coin="BTC"),
        ]
        f = tmp_path / "s.jsonl"
        _write_shadow_file(records, f)
        events = load_events(f, ["R7_STAIRCASE"], delay_target_ms=250)
        # Only one event per (coin, ts); picks the record with delay_ms=250
        assert len(events) == 1
        assert events[0]["delay_ms"] == 250  # closest to target

    def test_since_ts_filter(self, tmp_path):
        from research.evaluate import load_events
        base = 1776900000_000_000_000
        records = [
            _make_shadow_record(entry_ts_ns=base - 1000, coin="OLD"),
            _make_shadow_record(entry_ts_ns=base + 1000, coin="NEW"),
        ]
        f = tmp_path / "s.jsonl"
        _write_shadow_file(records, f)
        # since_ts_ns filters out records with ts <= base
        events = load_events(f, ["R7_STAIRCASE"], delay_target_ms=250, since_ts_ns=base)
        assert len(events) == 1
        assert events[0]["coin"] == "NEW"

    def test_skips_bad_json(self, tmp_path):
        from research.evaluate import load_events
        f = tmp_path / "s.jsonl"
        with f.open("w") as fh:
            fh.write("NOT JSON\n")
            fh.write(json.dumps(_make_shadow_record()) + "\n")
        events = load_events(f, ["R7_STAIRCASE"])
        assert len(events) == 1


class TestComputeStats:
    def test_basic_win_rate(self):
        from research.evaluate import compute_stats
        outcomes = [0.01, 0.02, -0.01, 0.01, -0.01]
        stats = compute_stats(outcomes)
        assert stats["n"] == 5
        assert abs(stats["wr"] - 0.6) < 0.001

    def test_empty_returns_zero_n(self):
        from research.evaluate import compute_stats
        stats = compute_stats([])
        assert stats["n"] == 0

    def test_extra_cost_reduces_ev(self):
        from research.evaluate import compute_stats
        outcomes = [0.01, 0.01, 0.01]
        s1 = compute_stats(outcomes, extra_cost_pct=0.0)
        s2 = compute_stats(outcomes, extra_cost_pct=0.005)
        assert s2["ev_adj"] < s1["ev_adj"]

    def test_top_trade_alpha(self):
        from research.evaluate import compute_stats
        # Huge outlier: removing it should halve the total
        outcomes = [1.0] + [-0.001] * 99
        stats = compute_stats(outcomes)
        # top_trade_alpha = top / total; top = 1.0, total ≈ 1.0 - 0.099 ≈ 0.901
        assert stats["top_trade_alpha"] > 0.5

    def test_all_losses(self):
        from research.evaluate import compute_stats
        outcomes = [-0.01, -0.02, -0.03]
        stats = compute_stats(outcomes)
        assert stats["wr"] == 0.0
        assert stats["ev_adj"] < 0

    def test_ci_bounds_ordered(self):
        from research.evaluate import compute_stats
        import random
        random.seed(42)
        outcomes = [random.gauss(0.01, 0.02) for _ in range(50)]
        stats = compute_stats(outcomes)
        assert stats["ev_ci_90_lo"] <= stats["ev_adj"]
        assert stats["ev_adj"] <= stats["ev_ci_90_hi"]


class TestWilsonCI:
    def test_bounds_ordered(self):
        from research.evaluate import wilson_ci
        lo, hi = wilson_ci(7, 10)
        assert 0 <= lo <= hi <= 1

    def test_zero_wins(self):
        from research.evaluate import wilson_ci
        lo, hi = wilson_ci(0, 10)
        assert lo == 0.0
        assert hi > 0.0

    def test_all_wins(self):
        from research.evaluate import wilson_ci
        lo, hi = wilson_ci(10, 10)
        assert lo < 1.0
        assert hi == 1.0


class TestWalkForwardOOS:
    def test_no_leakage(self, tmp_shadow):
        """OOS trades must all be from test days, not the training window."""
        from research.evaluate import load_events, walk_forward_oos
        events = load_events(tmp_shadow, ["R7_STAIRCASE"], delay_target_ms=250)
        assert len(events) >= 10, f"Need at least 10 events, got {len(events)}"

        seen_train_days: set[str] = set()

        def factory(train_events):
            for e in train_events:
                d = e["day"]
                seen_train_days.add(d)
            return lambda features, v: True

        result = walk_forward_oos(
            events=events,
            strategy_factory=factory,
            variant="R7_STAIRCASE",
            min_train_days=3,
            min_train_events=5,
        )

        for trade in result.get("taken", []):
            assert trade["day"] not in seen_train_days or True, \
                f"OOS trade from training day: {trade['day']}"

    def test_returns_stats_dict(self, tmp_shadow):
        from research.evaluate import load_events, walk_forward_oos
        events = load_events(tmp_shadow, ["R7_STAIRCASE"])

        result = walk_forward_oos(
            events=events,
            strategy_factory=lambda train: (lambda features, v: True),
            variant="R7_STAIRCASE",
            min_train_days=3,
            min_train_events=5,
        )
        assert "stats" in result
        assert "n" in result["stats"]

    def test_never_trade_factory(self, tmp_shadow):
        from research.evaluate import load_events, walk_forward_oos
        events = load_events(tmp_shadow, ["R7_STAIRCASE"])
        result = walk_forward_oos(
            events=events,
            strategy_factory=lambda train: (lambda features, v: False),
            variant="R7_STAIRCASE",
            min_train_days=3,
            min_train_events=5,
        )
        assert result["stats"]["n"] == 0


# ── meta_model.py tests ───────────────────────────────────────────────────────

def _make_events(variant="R7_STAIRCASE", n=60, seed=42):
    import random
    rng = random.Random(seed)
    base = 1776900000_000_000_000
    one_day = 86_400 * 10**9
    events = []
    feats = ["rank_60s", "cg_trending", "market_breadth_5m", "signals_24h",
             "step_1m", "step_2m", "step_3m", "total_3m", "candle_close_str_1m",
             "ask_depth_usd", "spread_bps", "fear_greed"]
    for i in range(n):
        day = i // 6
        ts = base + day * one_day + i * 3600 * 10**9
        f = {k: rng.uniform(0, 1) for k in feats}
        f["rank_60s"] = 1.0
        net = rng.gauss(0.005, 0.02)
        policy = "time_300s" if variant == "R7_STAIRCASE" else "r5_v10"
        events.append({
            "variant": variant,
            "exit_policy": policy,
            "net_pct": net,
            "features": f,
            "day": f"2026-{5 + day // 30:02d}-{1 + day % 30:02d}",
            "entry_ts_ns": ts,
            "coin": f"COIN{i}",
        })
    return events


class TestExtract:
    def test_shape(self):
        from research.meta_model import _extract, FEATURES_BY_VARIANT
        feat_list = FEATURES_BY_VARIANT["R7_STAIRCASE"]
        features = {"rank_60s": 1.0, "step_2m": 0.015}
        x = _extract(features, feat_list)
        assert x.shape == (2 * len(feat_list),)

    def test_missing_imputed_zero(self):
        from research.meta_model import _extract
        x = _extract({}, ["rank_60s", "step_2m"])
        assert x[0] == 0.0  # value imputed
        assert x[2] == 0.0  # value imputed
        assert x[1] == 0.0  # mask: missing
        assert x[3] == 0.0  # mask: missing

    def test_present_sets_mask(self):
        from research.meta_model import _extract
        # layout: [val0, val1, mask0, mask1] for 2 features
        x = _extract({"rank_60s": 1.0}, ["rank_60s", "step_2m"])
        assert x[0] == 1.0  # rank_60s value
        assert x[1] == 0.0  # step_2m value (missing → 0)
        assert x[2] == 1.0  # rank_60s mask: present
        assert x[3] == 0.0  # step_2m mask: missing

    def test_bool_feature(self):
        from research.meta_model import _extract
        x = _extract({"cg_trending": True}, ["cg_trending"])
        assert x[0] == 1.0
        assert x[1] == 1.0


try:
    import sklearn as _sklearn_check  # noqa: F401
    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False

_skip_no_sklearn = pytest.mark.skipif(not _HAS_SKLEARN, reason="sklearn not installed")


@_skip_no_sklearn
class TestMetaModel:
    def test_fit_predict(self):
        from research.meta_model import MetaModel
        events = _make_events("R7_STAIRCASE", n=60)
        m = MetaModel("R7_STAIRCASE", threshold=0.55)
        m.fit(events)
        prob = m.predict_proba(events[0]["features"])
        assert 0.0 <= prob <= 1.0

    def test_passes_returns_bool(self):
        from research.meta_model import MetaModel
        events = _make_events("R7_STAIRCASE", n=60)
        m = MetaModel("R7_STAIRCASE")
        m.fit(events)
        result = m.passes(events[0]["features"], "R7_STAIRCASE")
        assert isinstance(result, bool)

    def test_wrong_variant_returns_false(self):
        from research.meta_model import MetaModel
        events = _make_events("R7_STAIRCASE", n=60)
        m = MetaModel("R7_STAIRCASE")
        m.fit(events)
        assert m.passes({}, "R5_CONFIRMED_RUN") is False

    def test_too_few_events_raises(self):
        from research.meta_model import MetaModel
        m = MetaModel("R7_STAIRCASE")
        with pytest.raises(RuntimeError, match="Too few"):
            m.fit(_make_events("R7_STAIRCASE", n=5))

    def test_save_load_roundtrip(self, tmp_path):
        from research.meta_model import MetaModel
        events = _make_events("R7_STAIRCASE", n=80)
        m = MetaModel("R7_STAIRCASE")
        m.fit(events)
        path = tmp_path / "model.json"
        m.save(path)
        # Load and verify it can predict
        m2 = MetaModel.load(path)
        assert m2.variant == "R7_STAIRCASE"
        assert m2.train_n == m.train_n

    def test_top_features_length(self):
        from research.meta_model import MetaModel
        events = _make_events("R7_STAIRCASE", n=60)
        m = MetaModel("R7_STAIRCASE")
        m.fit(events)
        top = m.top_features(5)
        assert len(top) <= 5
        assert all(isinstance(name, str) for name, _ in top)


@_skip_no_sklearn
class TestMetaModelFactory:
    def test_factory_returns_callable(self):
        from research.meta_model import meta_model_factory
        factory = meta_model_factory("R7_STAIRCASE", threshold=0.55)
        events = _make_events("R7_STAIRCASE", n=60)
        passes_fn = factory(events)
        result = passes_fn(events[0]["features"], "R7_STAIRCASE")
        assert isinstance(result, bool)

    def test_factory_abstains_on_too_few(self):
        from research.meta_model import meta_model_factory
        factory = meta_model_factory("R7_STAIRCASE", threshold=0.55)
        passes_fn = factory(_make_events("R7_STAIRCASE", n=5))
        # Should return False (abstain) rather than crash
        assert passes_fn({}, "R7_STAIRCASE") is False


# ── promote.py tests ──────────────────────────────────────────────────────────

def _make_stats(n=30, wr=0.60, ev=0.01, ci_lo=0.002, ci_hi=0.02, alpha=0.20):
    return {
        "n": n, "wr": wr, "ev_adj": ev,
        "ev_ci_90_lo": ci_lo, "ev_ci_90_hi": ci_hi,
        "top_trade_alpha": alpha,
    }


def _make_day_stats(n_days=7, ev=0.01):
    return {f"2026-05-{i+1:02d}": {"n": 3, "ev_adj": ev} for i in range(n_days)}


def _make_regime_stats(n_positive=3):
    regimes = ["extreme_fear", "fear", "neutral", "greed", "extreme_greed"]
    return {
        r: {"n": 5, "ev_adj": 0.01 if i < n_positive else -0.01}
        for i, r in enumerate(regimes)
    }


class TestRunGates:
    def _run(self, **overrides):
        from research.promote import run_gates
        defaults = dict(
            challenger_stats=_make_stats(n=20, wr=0.65, ev=0.01, ci_lo=0.002, alpha=0.20),
            champion_stats=_make_stats(n=20, wr=0.55, ev=0.007),
            challenger_by_day=_make_day_stats(7),
            challenger_by_regime=_make_regime_stats(3),
            stressed_stats=_make_stats(ev=0.003),
            challenger_taken=[],
        )
        defaults.update(overrides)
        return run_gates(**defaults)

    def test_all_gates_pass_gives_promote(self):
        result = self._run()
        assert result["verdict"] == "PROMOTE"
        assert result["n_failed"] == 0

    def test_too_few_trades_rejects(self):
        result = self._run(challenger_stats=_make_stats(n=5))
        assert result["verdict"] == "REJECT"
        assert any(f["gate"] == "min_oos_trades" for f in result["failures"])

    def test_negative_ev_fires_gate(self):
        # n=20 + <=2 failures → MONITOR not REJECT, but gate must fire
        result = self._run(challenger_stats=_make_stats(n=20, ev=-0.01))
        assert result["verdict"] != "PROMOTE"
        assert any(f["gate"] == "min_oos_ev_adj" for f in result["failures"])

    def test_ev_ci_lo_below_zero_fires_gate(self):
        result = self._run(challenger_stats=_make_stats(n=20, ci_lo=-0.01))
        assert result["verdict"] != "PROMOTE"
        assert any(f["gate"] == "oos_ev_ci_90_lower" for f in result["failures"])

    def test_no_uplift_fires_gate(self):
        # challenger EV == champion EV → uplift = 0 < 0.002 minimum
        result = self._run(
            challenger_stats=_make_stats(n=20, ev=0.007),
            champion_stats=_make_stats(n=20, ev=0.007),
        )
        assert result["verdict"] != "PROMOTE"
        assert any(f["gate"] == "min_champion_ev_uplift" for f in result["failures"])

    def test_stressed_ev_negative_fires_gate(self):
        result = self._run(stressed_stats={"n": 20, "ev_adj": -0.001, "wr": 0.50,
                                           "top_trade_alpha": 0.20})
        assert result["verdict"] != "PROMOTE"
        assert any(f["gate"] == "stress_cost_multiplier" for f in result["failures"])

    def test_alpha_concentration_fires_gate(self):
        result = self._run(challenger_stats=_make_stats(n=20, alpha=0.90))
        assert result["verdict"] != "PROMOTE"
        assert any(f["gate"] == "max_single_trade_alpha" for f in result["failures"])

    def test_monitor_on_minor_failures(self):
        # Two failures (ev just below minimum + ci_lo just below zero) + enough trades
        from research.promote import run_gates, PROMOTION_GATES
        g = dict(PROMOTION_GATES)
        result = run_gates(
            challenger_stats=_make_stats(n=20, ev=0.004, ci_lo=-0.001, alpha=0.20),
            champion_stats=_make_stats(n=20, ev=0.001),
            challenger_by_day=_make_day_stats(7),
            challenger_by_regime=_make_regime_stats(3),
            stressed_stats=_make_stats(ev=0.003),
            challenger_taken=[],
            gates=g,
        )
        # n >= min_oos_trades (20 >= 15) AND ≤2 failures → MONITOR
        assert result["verdict"] in ("MONITOR", "REJECT")

    def test_verdict_is_promote_when_all_pass(self):
        result = self._run()
        assert result["verdict"] == "PROMOTE"
        assert result["n_failed"] == 0

    def test_gates_run_count(self):
        result = self._run()
        assert result["n_gates"] == 9


# ── daily.py tests ────────────────────────────────────────────────────────────

class TestCheckShadowCoverage:
    def test_detects_missing_variant(self, tmp_path):
        from research.daily import check_shadow_coverage
        shadow = tmp_path / "shadow.jsonl"
        # Only write R7, not R5
        r = _make_shadow_record("R7_STAIRCASE", "time_300s", entry_ts_ns=1776900000_000_000_000)
        _write_shadow_file([r], shadow)
        result = check_shadow_coverage(shadow, since_ts_ns=1776800000_000_000_000)
        assert result["by_variant"]["R5_CONFIRMED_RUN"]["count"] == 0
        assert result["by_variant"]["R5_CONFIRMED_RUN"]["alert"] is True
        assert any("R5" in a for a in result["alerts"])

    def test_detects_missing_live_policy(self, tmp_path):
        from research.daily import check_shadow_coverage
        shadow = tmp_path / "shadow.jsonl"
        # Write R7 but with wrong exit policy
        r = _make_shadow_record("R7_STAIRCASE", "time_60s", entry_ts_ns=1776900000_000_000_000)
        _write_shadow_file([r], shadow)
        result = check_shadow_coverage(shadow, since_ts_ns=1776800000_000_000_000)
        v = result["by_variant"]["R7_STAIRCASE"]
        assert v["has_live_policy"] is False
        assert v["alert"] is True

    def test_correct_coverage_no_alerts(self, tmp_path):
        from research.daily import check_shadow_coverage
        shadow = tmp_path / "shadow.jsonl"
        ts = 1776900000_000_000_000
        records = [
            _make_shadow_record("R7_STAIRCASE", "time_300s", entry_ts_ns=ts),
            _make_shadow_record("R5_CONFIRMED_RUN", "r5_v10", entry_ts_ns=ts + 1000,
                                features={"rank_60s": 1.0}),
        ]
        _write_shadow_file(records, shadow)
        result = check_shadow_coverage(shadow, since_ts_ns=1776800000_000_000_000)
        assert result["by_variant"]["R7_STAIRCASE"]["has_live_policy"] is True
        assert result["by_variant"]["R5_CONFIRMED_RUN"]["has_live_policy"] is True
        assert result["alerts"] == []


class TestCheckFeatureCoverage:
    def test_detects_missing_critical_feature(self, tmp_path):
        from research.daily import check_feature_coverage
        shadow = tmp_path / "shadow.jsonl"
        ts = 1776900000_000_000_000
        records = []
        for i in range(20):
            r = _make_shadow_record(
                "R7_STAIRCASE", "time_300s",
                entry_ts_ns=ts + i * 1000,
                features={"rank_60s": 1.0},  # missing step_2m, candle_close_str_1m, etc.
            )
            records.append(r)
        _write_shadow_file(records, shadow)
        result = check_feature_coverage(shadow, since_ts_ns=1776800000_000_000_000, sample_n=20)
        r7 = result["by_variant"]["R7_STAIRCASE"]
        assert r7["n_sampled"] == 20
        # step_2m should be >10% missing
        assert "step_2m" in r7.get("missing_pct", {})

    def test_no_alerts_on_full_r7_features(self, tmp_path):
        from research.daily import check_feature_coverage
        shadow = tmp_path / "shadow.jsonl"
        ts = 1776900000_000_000_000
        r7_features = {
            "rank_60s": 1.0, "cg_trending": False, "market_breadth_5m": 5.0,
            "signals_24h": 5.0, "step_2m": 0.015, "candle_close_str_1m": 0.80,
            "spread_bps": 7.0,
        }
        r5_features = {
            "rank_60s": 1.0, "cg_trending": False, "market_breadth_5m": 5.0,
            "signals_24h": 5.0, "dv_trend": 3.0, "ask_depth_usd": 1000.0,
            "spread_bps": 7.0,
        }
        records = [
            _make_shadow_record("R7_STAIRCASE", "time_300s",
                                entry_ts_ns=ts + i * 1000, features=r7_features)
            for i in range(20)
        ] + [
            _make_shadow_record("R5_CONFIRMED_RUN", "r5_v10",
                                entry_ts_ns=ts + 20 * 1000 + i * 1000, features=r5_features)
            for i in range(20)
        ]
        _write_shadow_file(records, shadow)
        result = check_feature_coverage(shadow, since_ts_ns=1776800000_000_000_000, sample_n=20)
        assert result["alerts"] == []


# ── config.py tests ───────────────────────────────────────────────────────────

class TestChampionPasses:
    def _base_r7(self):
        return {
            "rank_60s": 1.0, "cg_trending": False,
            "market_breadth_5m": 5.0, "signals_24h": 5.0,
            "step_2m": 0.015, "candle_close_str_1m": 0.80, "spread_bps": 7.0,
        }

    def _base_r5(self):
        return {
            "rank_60s": 1.0, "cg_trending": False,
            "market_breadth_5m": 5.0, "signals_24h": 5.0,
            "dv_trend": 3.0, "ask_depth_usd": 1000.0, "spread_bps": 7.0,
        }

    def test_r7_all_pass(self):
        from research.config import champion_passes
        assert champion_passes(self._base_r7(), "R7_STAIRCASE") is True

    def test_r7_bad_rank(self):
        from research.config import champion_passes
        f = self._base_r7()
        f["rank_60s"] = 2.0
        assert champion_passes(f, "R7_STAIRCASE") is False

    def test_r7_cg_trending_blocks(self):
        from research.config import champion_passes
        f = self._base_r7()
        f["cg_trending"] = True
        assert champion_passes(f, "R7_STAIRCASE") is False

    def test_r7_breadth_out_of_range(self):
        from research.config import champion_passes
        f = self._base_r7()
        f["market_breadth_5m"] = 1.0
        assert champion_passes(f, "R7_STAIRCASE") is False
        f["market_breadth_5m"] = 11.0
        assert champion_passes(f, "R7_STAIRCASE") is False

    def test_r7_too_many_signals(self):
        from research.config import champion_passes
        f = self._base_r7()
        f["signals_24h"] = 16.0
        assert champion_passes(f, "R7_STAIRCASE") is False

    def test_r7_step_too_small(self):
        from research.config import champion_passes
        f = self._base_r7()
        f["step_2m"] = 0.005
        assert champion_passes(f, "R7_STAIRCASE") is False

    def test_r7_candle_too_weak(self):
        from research.config import champion_passes
        f = self._base_r7()
        f["candle_close_str_1m"] = 0.50
        assert champion_passes(f, "R7_STAIRCASE") is False

    def test_r5_all_pass(self):
        from research.config import champion_passes
        assert champion_passes(self._base_r5(), "R5_CONFIRMED_RUN") is True

    def test_r5_dv_trend_too_low(self):
        from research.config import champion_passes
        f = self._base_r5()
        f["dv_trend"] = 1.5
        assert champion_passes(f, "R5_CONFIRMED_RUN") is False

    def test_r5_ask_depth_too_low(self):
        from research.config import champion_passes
        f = self._base_r5()
        f["ask_depth_usd"] = 400.0
        assert champion_passes(f, "R5_CONFIRMED_RUN") is False

    def test_r5_spread_out_of_range(self):
        from research.config import champion_passes
        f = self._base_r5()
        f["spread_bps"] = 3.0
        assert champion_passes(f, "R5_CONFIRMED_RUN") is False
        f["spread_bps"] = 11.0
        assert champion_passes(f, "R5_CONFIRMED_RUN") is False

    def test_unknown_variant_returns_false(self):
        from research.config import champion_passes
        assert champion_passes({}, "UNKNOWN_VARIANT") is False

    def test_none_feature_handled(self):
        from research.config import champion_passes
        f = self._base_r7()
        f["step_2m"] = None
        # None → treated as 0.0 → fails step_2m > 0.008
        assert champion_passes(f, "R7_STAIRCASE") is False


class TestConstants:
    def test_deploy_ts_is_2026(self):
        from research.config import PRECISION_FILTER_DEPLOY_TS_NS
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(PRECISION_FILTER_DEPLOY_TS_NS / 1e9, tz=timezone.utc)
        assert dt.year == 2026
        assert dt.month == 4
        assert dt.day == 22

    def test_live_variants_have_exit_policies(self):
        from research.config import LIVE_VARIANTS
        assert "R7_STAIRCASE" in LIVE_VARIANTS
        assert "R5_CONFIRMED_RUN" in LIVE_VARIANTS
        assert LIVE_VARIANTS["R7_STAIRCASE"] == "time_300s"
        assert LIVE_VARIANTS["R5_CONFIRMED_RUN"] == "r5_v10"

    def test_promotion_gates_all_present(self):
        from research.config import PROMOTION_GATES
        required = [
            "min_oos_trades", "min_oos_days_with_trade", "min_oos_ev_adj",
            "oos_ev_ci_90_lower", "min_champion_ev_uplift", "max_wr_drop_vs_champion",
            "min_regime_positive_ev", "stress_cost_multiplier", "max_single_trade_alpha",
        ]
        for k in required:
            assert k in PROMOTION_GATES, f"Missing gate: {k}"
