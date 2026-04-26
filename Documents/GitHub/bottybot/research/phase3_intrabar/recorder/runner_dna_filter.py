"""
runner_dna_filter.py — candidate filter v1 for the Runner DNA shadow study.

Discovered via research/runner_dna/ analysis on 14 days of shadow data.
Two complementary entry profiles:

  Path A — Continuation:  higher_lows_3m == True AND step_2m strong
                          AND candle_close_str high AND rank ≤ 3.
  Path B — Absorption:    higher_lows_3m == False AND heavy negative CVD
                          AND book depth supportive (≥$5k each side).

Both paths require the macro setup: BTC has lifted relative to alts in
the last 5 minutes (`btc_rel_ret_5m ≥ +2%`), and the day isn't already
saturated with signals (`signals_24h ≤ 15`).

This module exists ONLY for shadow tagging. Live trading routes are
unchanged. Every signal the recorder emits gets stamped with
`features['runner_dna_v1']: bool` so subsequent analysis can compare
this filter's performance against champion_v1 on accumulating
out-of-sample data.

Re-run `python3 -m research.runner_dna.evaluate_candidate` after enough
days have accumulated to refresh the comparison.
"""
from __future__ import annotations

from typing import Any


def _g(features: dict, key: str, default: Any = None) -> Any:
    """Coerce a feature value to float when possible. Booleans pass through.
    Returns `default` when the feature is missing or unparseable."""
    v = features.get(key, default)
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def runner_dna_v1_passes(features: dict, variant: str) -> bool:
    """Return True if the signal matches one of the two runner_dna_v1
    entry profiles. Fails closed: any missing critical feature returns
    False rather than risk a permissive default.
    """
    # ── Macro regime gate ───────────────────────────────────────────
    btc_rel = _g(features, "btc_rel_ret_5m")
    if btc_rel is None or btc_rel < 0.02:
        return False

    # ── Activity gate ────────────────────────────────────────────────
    sig_24h = _g(features, "signals_24h", 0.0)
    if sig_24h is not None and sig_24h > 15.0:
        return False

    higher_lows = _g(features, "higher_lows_3m")
    rank        = _g(features, "rank_60s", 99.0) or 99.0

    # ── Path A: continuation ────────────────────────────────────────
    if higher_lows is True:
        step_2m = _g(features, "step_2m", 0.0) or 0.0
        ccs     = _g(features, "candle_close_str_1m", 0.0) or 0.0
        if step_2m >= 0.012 and ccs >= 0.70 and rank <= 3:
            return True

    # ── Path B: absorption ──────────────────────────────────────────
    if higher_lows is False:
        cvd_30s = _g(features, "cvd_30s", 0.0) or 0.0
        if cvd_30s < -3000:
            ask_d = _g(features, "ask_depth_usd", 0.0) or 0.0
            bid_d = _g(features, "bid_depth_usd", 0.0) or 0.0
            if ask_d >= 5000 and bid_d >= 5000:
                return True

    return False
