"""
research/runner_dna/registry.py — registry of candidate entry filters.

Every named filter here is BOTH eligible to be the live champion and
automatically scored against incoming shadow data on a schedule. The
auto-promotion engine reads this registry, computes each filter's
recent walk-forward EV, and may swap the live champion when a
challenger beats the current incumbent on the gate criteria.

Adding a challenger is just adding a function here. No other code
changes required.

Each filter takes (features: dict, variant: str) and returns bool.
"""
from __future__ import annotations

from typing import Any, Callable


def _g(features: dict, key: str, default: Any = None) -> Any:
    v = features.get(key, default)
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ── runner_dna_v1 (current champion as of 2026-04-26) ──────────────────────
def runner_dna_v1(features: dict, variant: str) -> bool:
    """Discovered DNA: 2-path entry with macro setup gate.
    Path A continuation: hl3m=True ∧ step_2m≥0.012 ∧ ccs≥0.70 ∧ rank≤3.
    Path B absorption:   hl3m=False ∧ cvd_30s<-3000 ∧ depth≥$5k each side.
    Both: btc_rel_ret_5m≥0.02 ∧ signals_24h≤15.
    """
    btc_rel = _g(features, "btc_rel_ret_5m")
    if btc_rel is None or btc_rel < 0.02:
        return False
    if (_g(features, "signals_24h", 0.0) or 0.0) > 15.0:
        return False
    hl   = _g(features, "higher_lows_3m")
    rank = _g(features, "rank_60s", 99.0) or 99.0
    if hl is True:
        if (_g(features, "step_2m", 0.0) or 0.0) >= 0.012 and \
           (_g(features, "candle_close_str_1m", 0.0) or 0.0) >= 0.70 and \
           rank <= 3:
            return True
    if hl is False:
        if (_g(features, "cvd_30s", 0.0) or 0.0) < -3000:
            if (_g(features, "ask_depth_usd", 0.0) or 0.0) >= 5000 and \
               (_g(features, "bid_depth_usd", 0.0) or 0.0) >= 5000:
                return True
    return False


# ── Challenger: stricter version (higher bar, fewer fires) ──────────────────
def runner_dna_strict(features: dict, variant: str) -> bool:
    """Tighter thresholds. Hypothesis: less noise, higher per-trade EV at
    the cost of fewer fires. Tighter on every gate that v1 has."""
    btc_rel = _g(features, "btc_rel_ret_5m")
    if btc_rel is None or btc_rel < 0.03:
        return False
    if (_g(features, "signals_24h", 0.0) or 0.0) > 10.0:
        return False
    hl   = _g(features, "higher_lows_3m")
    rank = _g(features, "rank_60s", 99.0) or 99.0
    if hl is True:
        # R11-level continuation
        if (_g(features, "step_2m", 0.0) or 0.0) >= 0.018 and \
           (_g(features, "candle_close_str_1m", 0.0) or 0.0) >= 0.85 and \
           rank <= 1:
            return True
    if hl is False:
        # Stronger absorption signature
        if (_g(features, "cvd_30s", 0.0) or 0.0) < -5000:
            if (_g(features, "ask_depth_usd", 0.0) or 0.0) >= 8000 and \
               (_g(features, "bid_depth_usd", 0.0) or 0.0) >= 8000 and \
               rank <= 3:
                return True
    return False


# ── Challenger: looser version (more fires, lower per-trade EV) ─────────────
def runner_dna_loose(features: dict, variant: str) -> bool:
    """Looser thresholds. Hypothesis: more fires capture more total
    P&L even at lower per-trade EV. Tests whether v1 was over-tightened."""
    btc_rel = _g(features, "btc_rel_ret_5m")
    if btc_rel is None or btc_rel < 0.01:
        return False
    if (_g(features, "signals_24h", 0.0) or 0.0) > 25.0:
        return False
    hl   = _g(features, "higher_lows_3m")
    rank = _g(features, "rank_60s", 99.0) or 99.0
    if hl is True:
        if (_g(features, "step_2m", 0.0) or 0.0) >= 0.008 and \
           (_g(features, "candle_close_str_1m", 0.0) or 0.0) >= 0.60 and \
           rank <= 5:
            return True
    if hl is False:
        if (_g(features, "cvd_30s", 0.0) or 0.0) < -1500:
            if (_g(features, "ask_depth_usd", 0.0) or 0.0) >= 3000 and \
               (_g(features, "bid_depth_usd", 0.0) or 0.0) >= 3000:
                return True
    return False


# ── Challenger: continuation-only ───────────────────────────────────────────
def runner_dna_cont_only(features: dict, variant: str) -> bool:
    """Path A only. Tests whether the absorption finding actually adds value
    or whether continuation alone matches it."""
    btc_rel = _g(features, "btc_rel_ret_5m")
    if btc_rel is None or btc_rel < 0.02:
        return False
    if (_g(features, "signals_24h", 0.0) or 0.0) > 15.0:
        return False
    if _g(features, "higher_lows_3m") is not True:
        return False
    rank = _g(features, "rank_60s", 99.0) or 99.0
    if (_g(features, "step_2m", 0.0) or 0.0) >= 0.012 and \
       (_g(features, "candle_close_str_1m", 0.0) or 0.0) >= 0.70 and \
       rank <= 3:
        return True
    return False


# ── Challenger: absorption-only ─────────────────────────────────────────────
def runner_dna_abs_only(features: dict, variant: str) -> bool:
    """Path B only. The "new" finding from the DNA analysis on its own."""
    btc_rel = _g(features, "btc_rel_ret_5m")
    if btc_rel is None or btc_rel < 0.02:
        return False
    if (_g(features, "signals_24h", 0.0) or 0.0) > 15.0:
        return False
    if _g(features, "higher_lows_3m") is not False:
        return False
    if (_g(features, "cvd_30s", 0.0) or 0.0) < -3000:
        if (_g(features, "ask_depth_usd", 0.0) or 0.0) >= 5000 and \
           (_g(features, "bid_depth_usd", 0.0) or 0.0) >= 5000:
            return True
    return False


# ── Baseline: legacy champion (precision filter v1) ─────────────────────────
def champion_v1_legacy(features: dict, variant: str) -> bool:
    """Frozen copy of the precision filter that ran live before runner_dna_v1.
    Kept as a baseline so the auto-promotion engine can detect if the
    research conclusion was wrong and the legacy filter actually beats
    the new champion on accumulating data."""
    if variant not in {"R7_STAIRCASE", "R5_CONFIRMED_RUN"}:
        return False
    g = lambda k, d=0.0: _g(features, k, d) or d
    if g("rank_60s", 99.0) != 1.0:
        return False
    if features.get("cg_trending") is True:
        return False
    breadth = g("market_breadth_5m")
    if not (3.0 <= breadth <= 10.0):
        return False
    if g("signals_24h") > 15.0:
        return False
    if variant == "R7_STAIRCASE":
        if g("step_2m") <= 0.008:
            return False
        if g("candle_close_str_1m") <= 0.70:
            return False
    elif variant == "R5_CONFIRMED_RUN":
        if g("dv_trend") <= 2.0:
            return False
        if g("ask_depth_usd") <= 500.0:
            return False
        spread = g("spread_bps", g("spread_bps_at_entry", 0.0))
        if not (5.0 <= spread < 10.0):
            return False
    return True


# ── Combined OR: champion logic OR runner_dna_v1 ────────────────────────────
def combined_or(features: dict, variant: str) -> bool:
    """Strongest historical performer in the 14-day backtest. Catches both
    continuation+absorption AND legacy precision profile."""
    return runner_dna_v1(features, variant) or champion_v1_legacy(features, variant)


# ── REGISTRY ────────────────────────────────────────────────────────────────
# name → (callable, description)
REGISTRY: dict[str, tuple[Callable, str]] = {
    "runner_dna_v1":      (runner_dna_v1,      "current champion — 2-path with macro gate"),
    "runner_dna_strict":  (runner_dna_strict,  "tighter on every gate"),
    "runner_dna_loose":   (runner_dna_loose,   "more permissive"),
    "runner_dna_cont":    (runner_dna_cont_only, "Path A continuation only"),
    "runner_dna_abs":     (runner_dna_abs_only,  "Path B absorption only"),
    "combined_or":        (combined_or,        "runner_dna_v1 OR legacy champion"),
    "champion_v1_legacy": (champion_v1_legacy, "old precision filter — baseline"),
}


def get_filter(name: str) -> Callable:
    """Return the callable for a registered filter name. Raises KeyError if
    name is not registered — fail loudly so we never silently fall back to
    a default that might trade real money."""
    return REGISTRY[name][0]
