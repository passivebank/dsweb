"""
research/config.py — single source of truth for the champion/challenger loop.

Every constant that drives strategy definition, cost assumptions, data paths,
and promotion gates lives here. Nothing else should hard-code these values.
"""
from __future__ import annotations

from pathlib import Path

# ── Deployment timestamps ─────────────────────────────────────────────────────
# Precision filter go-live: 2026-04-22T17:13:46Z
PRECISION_FILTER_DEPLOY_TS_NS = 1776878026_000_000_000

# ── Data paths (EC2) ──────────────────────────────────────────────────────────
EC2_ROOT      = Path("/home/ec2-user/phase3_intrabar")
SHADOW_FILE   = EC2_ROOT / "artifacts" / "shadow_trades.jsonl"
LIVE_FILE     = EC2_ROOT / "artifacts" / "live_trades.jsonl"
RESEARCH_DIR  = EC2_ROOT / "research"
EXPERIMENTS   = RESEARCH_DIR / "experiments"
CHAMPIONS_DIR = RESEARCH_DIR / "champions"

# ── Cost model ────────────────────────────────────────────────────────────────
# Applies on top of the `cost_pct` already embedded in shadow records.
# shadow records already deduct TAKER_FEE×2 + half-spread. We add slippage.
ADDITIONAL_SLIPPAGE = 0.0005   # extra 5 bps for real-world market impact
# Total round-trip cost already in shadow records: ~0.004 (4 bps taker×2 + spread).
# Use net_pct from shadow records directly — it already reflects cost_pct.
# Additional slippage is applied when computing "stressed EV" for promotion gates.

# ── Live variant → exit policy mapping ───────────────────────────────────────
# This must stay in sync with live_executor.py and shadow/simulator.py.
LIVE_VARIANTS: dict[str, str] = {
    "R7_STAIRCASE":     "time_300s",
    "R5_CONFIRMED_RUN": "r5_v10",
}

# ── Champion definition ───────────────────────────────────────────────────────
CHAMPION_ID           = "precision_filter_v1"
CHAMPION_DEPLOY_TS_NS = PRECISION_FILTER_DEPLOY_TS_NS

# ── Feature spec for meta-model ───────────────────────────────────────────────
# Shared features available for both live variants.
FEATURES_SHARED = [
    "rank_60s",
    "cg_trending",
    "market_breadth_5m",
    "signals_24h",
    "signals_1h",
    "spread_bps",
    "spread_bps_at_entry",
    "fear_greed",
    "btc_ret_1h",
    "cvd_30s",
    "cvd_60s",
    "secs_since_onset",
    "ret_24h",
    "utc_hour",
    "candle_close_str_1m",
    "ask_depth_usd",
    "ask_depth_trend",
    "btc_dom_pct",
    "book_imbalance_10",
    "large_trade_pct_60s",
    "avg_trade_size_60s",
    "higher_lows_3m",
    "first_signal_today",
]

FEATURES_R7 = FEATURES_SHARED + ["step_1m", "step_2m", "step_3m", "total_3m"]

FEATURES_R5 = FEATURES_SHARED + [
    "dv_trend", "ret_5m", "ret_15m", "ret_1m",
    "bn_ret_24h", "bid_depth_usd",
]

FEATURES_BY_VARIANT: dict[str, list[str]] = {
    "R7_STAIRCASE":     FEATURES_R7,
    "R5_CONFIRMED_RUN": FEATURES_R5,
}

# ── Promotion gates ───────────────────────────────────────────────────────────
# ALL must pass for a challenger to be recommended for promotion.
PROMOTION_GATES: dict[str, float | int] = {
    # OOS data requirements
    "min_oos_trades":            15,    # minimum OOS trades across test window
    "min_oos_days_with_trade":    5,    # test days that had at least 1 trade
    # Performance vs. pure cost
    "min_oos_ev_adj":           0.005,  # OOS adj_EV > 0.5% per trade (net of costs)
    "oos_ev_ci_90_lower":       0.000,  # 90% bootstrap CI lower bound > 0
    # Performance vs. champion
    "min_champion_ev_uplift":   0.002,  # challenger must beat champion by 0.2% per trade
    "max_wr_drop_vs_champion":  0.15,   # challenger WR cannot drop 15pp below champion
    # Robustness
    "min_regime_positive_ev":     2,    # positive EV in at least 2 distinct F&G regimes
    "stress_cost_multiplier":     2.0,  # OOS EV must be positive after doubling costs
    "max_single_trade_alpha":     0.50, # removing best trade cannot halve the return
}

# ── Fear & Greed regime labels ────────────────────────────────────────────────
REGIMES = [
    ("extreme_fear",  0,  25),
    ("fear",         25,  45),
    ("neutral",      45,  55),
    ("greed",        55,  75),
    ("extreme_greed",75, 101),
]

# ── Champion filter (precision filter v1) ─────────────────────────────────────
def champion_passes(features: dict, variant: str) -> bool:
    """Return True if a signal passes all precision-filter-v1 gates.

    This is a frozen copy of the live filter in live_executor.py._handle_entry().
    It must NOT be changed without a formal promotion. Track changes in git.

    Args:
        features: the sig_features dict from a shadow trade record.
        variant:  the signal variant string.

    Returns:
        True if the signal passes all gates and would be traded live.
    """
    if variant not in LIVE_VARIANTS:
        return False

    def g(key: str, default: float = 0.0) -> float:
        val = features.get(key, default)
        if val is None or isinstance(val, bool):
            return float(val) if isinstance(val, bool) else default
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    # Filter 2: rank must be 1
    if g("rank_60s", 99.0) != 1.0:
        return False

    # Filter 3: not CoinGecko trending
    if features.get("cg_trending") is True:
        return False

    # Filter 4: market breadth 3-10
    breadth = g("market_breadth_5m")
    if not (3.0 <= breadth <= 10.0):
        return False

    # Filter 5: signals_24h <= 15
    if g("signals_24h") > 15.0:
        return False

    if variant == "R7_STAIRCASE":
        # Filter 6: step_2m > 0.008
        if g("step_2m") <= 0.008:
            return False
        # Filter 7: candle_close_str_1m > 0.70
        if g("candle_close_str_1m") <= 0.70:
            return False

    elif variant == "R5_CONFIRMED_RUN":
        # Filter 8: dv_trend > 2.0
        if g("dv_trend") <= 2.0:
            return False
        # Filter 9: ask_depth_usd > 500
        if g("ask_depth_usd") <= 500.0:
            return False
        # Filter 10: spread_bps 5-10
        spread = g("spread_bps", g("spread_bps_at_entry", 0.0))
        if not (5.0 <= spread < 10.0):
            return False

    return True


def regime_label(fear_greed: float) -> str:
    for label, lo, hi in REGIMES:
        if lo <= fear_greed < hi:
            return label
    return "unknown"
