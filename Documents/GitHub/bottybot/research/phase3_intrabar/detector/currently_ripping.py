"""
currently_ripping.py — formal definitions of the CURRENTLY_RIPPING event.

Variants:
  R1_TAPE_BURST      — top-rank + tape rate surge + clean return
  R2_RANK_TAKEOVER   — coin jumps from mid-table into top-5 with velocity
  R3_DV_EXPLOSION    — dollar-volume burst regardless of rank
  R4_POST_RUN_HOLD   — 5-60 min after initial run, coin holding well
  R5_CONFIRMED_RUN   — already up 12%+ today AND green on all timeframes
  R6_LOCAL_BREAKOUT  — consolidation breakout with volume burst
  R7_STAIRCASE       — three consecutive 60s green steps, strong mover
  R8_HIGH_CONVICTION — R7 quality gates plus whale presence required;
                        the tightest signal, designed for highest win rate

Spread gates are DECOUPLED per signal tier:
  R1/R2/R3: global SIGNAL_SPREAD_BPS (30bps) — broader for data capture
  R5/R6/R7/R8: dynamic gate via CoinState.dynamic_spread_gate()
    — floor 10bps for liquid coins (phase4 validated)
    — extends to min(typical * 0.20, 20bps) for micro-caps experiencing
      spread compression (e.g. RAVE at 80bps typical → up to 16bps allowed
      when a liquidity surge compresses the book)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .state import CoinState, NS


@dataclass
class SignalEvent:
    variant: str
    coin: str
    sig_ts_ns: int
    sig_mid: float
    features: dict = field(default_factory=dict)


# ----- eligibility (engine enforces these) --------------------------
ELIG_DV_300S_USD = 5_000.0
ELIG_MIN_TRADE_HISTORY_S = 60

# Spread gates — DECOUPLED:
#   RANK_SPREAD_BPS  : max spread to appear in the cross-section rank table.
#                      Wider so thin/active coins are visible for R2 rank jumps.
#   SIGNAL_SPREAD_BPS: max spread to actually fire a signal / open a trade.
#                      Tighter — we won't trade into a wide book.
RANK_SPREAD_BPS    = 50.0
SIGNAL_SPREAD_BPS  = 30.0   # R1/R2/R3 — kept wide for data collection

# R5/R6/R7/R8 use CoinState.dynamic_spread_gate() instead of static thresholds.
# These constants define the gate parameters (passed through to that method).
# Phase4 data: ≤5bps PF 1.88, 5-10bps PF 1.58, 10-15bps PF 0.99 (breakeven).
SPREAD_FLOOR_BPS    = 10.0  # always allow up to 10bps (large-cap baseline)
SPREAD_CAP_BPS      = 20.0  # hard ceiling even at maximum compression
SPREAD_COMPRESSION  = 0.20  # micro-cap must compress to ≤20% of typical

TOP_K_RANK = 5          # widened from 3; Phase 4 can tighten based on data


# ----- R1 TAPE_BURST ------------------------------------------------
# A coin that is top-5 by 60s return AND has tape rate surging AND has
# clean multi-horizon momentum with minimal pullback.
# Thresholds loosened from initial conservative pass (R1 never fired).
R1_TRADE_RATE_LOOKBACK_S  = 30
R1_TRADE_RATE_BASELINE_S  = 300
R1_TRADE_RATE_MULT        = 4.0    # was 5.0
R1_RET_30S_MIN            = 0.008
R1_RET_60S_MIN            = 0.012
R1_RET_180S_MIN           = 0.015  # was 0.020 — near-impossible with pullback gate
R1_BUY_SHARE_MIN          = 0.60   # was 0.65
R1_MAX_PULLBACK_30S       = 0.010  # was 0.005 — any real run has ticks against it
R1_REQUIRES_TOP_K_RANK    = True


def check_r1_tape_burst(state: CoinState, now_ns: int,
                        rank_60s: Optional[int],
                        spread_bps: float = 0.0) -> Optional[SignalEvent]:
    if spread_bps > SIGNAL_SPREAD_BPS:
        return None
    if R1_REQUIRES_TOP_K_RANK and (rank_60s is None or rank_60s > TOP_K_RANK):
        return None
    rate_recent = state.trade_count_in(now_ns, R1_TRADE_RATE_LOOKBACK_S) / R1_TRADE_RATE_LOOKBACK_S
    rate_base   = state.trade_count_in(now_ns, R1_TRADE_RATE_BASELINE_S) / R1_TRADE_RATE_BASELINE_S
    if rate_base <= 0:
        return None
    rate_ratio = rate_recent / rate_base
    if rate_ratio < R1_TRADE_RATE_MULT:
        return None
    r30  = state.return_over(now_ns, 30)
    r60  = state.return_over(now_ns, 60)
    r180 = state.return_over(now_ns, 180)
    if r30 < R1_RET_30S_MIN or r60 < R1_RET_60S_MIN or r180 < R1_RET_180S_MIN:
        return None
    buy_share = state.buy_share_in(now_ns, 30)
    if buy_share < R1_BUY_SHARE_MIN:
        return None
    if state.max_pullback_over(now_ns, 30) > R1_MAX_PULLBACK_30S:
        return None
    return SignalEvent(
        variant="R1_TAPE_BURST",
        coin=state.coin,
        sig_ts_ns=now_ns,
        sig_mid=state.last_mid,
        features={
            "rate_ratio":       round(rate_ratio, 3),
            "ret_30s":          round(r30, 5),
            "ret_60s":          round(r60, 5),
            "ret_180s":         round(r180, 5),
            "buy_share_30s":    round(buy_share, 3),
            "max_pullback_30s": round(state.max_pullback_over(now_ns, 30), 5),
            "rank_60s":         rank_60s,
            "spread_bps":       round(spread_bps, 1),
        },
    )


# ----- R2 RANK_TAKEOVER ---------------------------------------------
# Coin was mid-table (rank >R2_RANK_PREV_OUT) within the last
# R2_RANK_LOOKBACK_S seconds and is now top-K.  Captures the "just
# broke out of the pack" moment rather than a coin already running.
# Thresholds loosened: prev_out 10→7, new_top_k 3→5, pullback relaxed.
R2_RANK_NEW_TOP_K         = 5     # was 3
R2_RANK_PREV_OUT          = 7     # was 10 — "was outside top-7 recently"
R2_RANK_LOOKBACK_S        = 30
R2_RET_60S_MIN            = 0.008 # was 0.010
R2_TRADE_RATE_MULT        = 2.5   # was 3.0
R2_MAX_PULLBACK_60S       = 0.012 # was 0.008


def check_r2_rank_takeover(state: CoinState, now_ns: int,
                           rank_60s: Optional[int],
                           prev_min_rank_in_lookback: Optional[int],
                           spread_bps: float = 0.0) -> Optional[SignalEvent]:
    """`prev_min_rank_in_lookback` = the best (lowest) rank held by this
    coin in the prior R2_RANK_LOOKBACK_S seconds.  Engine must supply."""
    if spread_bps > SIGNAL_SPREAD_BPS:
        return None
    if rank_60s is None or rank_60s > R2_RANK_NEW_TOP_K:
        return None
    # Must have BEEN outside top-K in recent history (not already a leader)
    if prev_min_rank_in_lookback is None or prev_min_rank_in_lookback <= R2_RANK_NEW_TOP_K:
        return None
    if prev_min_rank_in_lookback < R2_RANK_PREV_OUT:
        return None
    r60 = state.return_over(now_ns, 60)
    if r60 < R2_RET_60S_MIN:
        return None
    rate_recent = state.trade_count_in(now_ns, 30) / 30.0
    rate_base   = state.trade_count_in(now_ns, 300) / 300.0
    if rate_base <= 0 or rate_recent / rate_base < R2_TRADE_RATE_MULT:
        return None
    if state.max_pullback_over(now_ns, 60) > R2_MAX_PULLBACK_60S:
        return None
    return SignalEvent(
        variant="R2_RANK_TAKEOVER",
        coin=state.coin,
        sig_ts_ns=now_ns,
        sig_mid=state.last_mid,
        features={
            "rank_60s":          rank_60s,
            "prev_min_rank":     prev_min_rank_in_lookback,
            "ret_60s":           round(r60, 5),
            "rate_ratio":        round(rate_recent / rate_base, 3),
            "max_pullback_60s":  round(state.max_pullback_over(now_ns, 60), 5),
            "spread_bps":        round(spread_bps, 1),
        },
    )


# ----- R3 DV_EXPLOSION ----------------------------------------------
# Dollar-volume burst — the clearest "something is happening RIGHT NOW"
# signal.  No rank requirement; rank is logged as a feature for Phase 4
# to find the discriminating threshold empirically.
R3_DV_30S_MULT           = 8.0
R3_DV_BASELINE_S         = 300
R3_RET_FROM_5MIN_LOW_MIN = 0.015
R3_BUY_SHARE_10S_MIN     = 0.70
R3_REQUIRES_TOP_K_RANK   = False


def check_r3_dv_explosion(state: CoinState, now_ns: int,
                          rank_60s: Optional[int],
                          spread_bps: float = 0.0) -> Optional[SignalEvent]:
    if spread_bps > SIGNAL_SPREAD_BPS:
        return None
    if R3_REQUIRES_TOP_K_RANK and (rank_60s is None or rank_60s > TOP_K_RANK):
        return None
    dv_recent = state.dollar_volume_in(now_ns, 30)
    dv_base   = state.dollar_volume_in(now_ns, R3_DV_BASELINE_S) - dv_recent
    if dv_base <= 0 or dv_recent / (dv_base / (R3_DV_BASELINE_S / 30.0)) < R3_DV_30S_MULT:
        return None
    if not state.mids:
        return None
    cutoff  = now_ns - 300 * NS
    lows    = [mp.mid for mp in state.mids if mp.ts_ns >= cutoff]
    if not lows:
        return None
    low_5m  = min(lows)
    if low_5m <= 0:
        return None
    move_from_low = (state.last_mid / low_5m) - 1.0
    if move_from_low < R3_RET_FROM_5MIN_LOW_MIN:
        return None
    if state.buy_share_in(now_ns, 10) < R3_BUY_SHARE_10S_MIN:
        return None
    return SignalEvent(
        variant="R3_DV_EXPLOSION",
        coin=state.coin,
        sig_ts_ns=now_ns,
        sig_mid=state.last_mid,
        features={
            "dv_30s_usd":       round(dv_recent, 2),
            "dv_30s_mult":      round(dv_recent / (dv_base / (R3_DV_BASELINE_S / 30.0)), 2),
            "move_from_5m_low": round(move_from_low, 5),
            "buy_share_10s":    round(state.buy_share_in(now_ns, 10), 3),
            "rank_60s":         rank_60s,
            "spread_bps":       round(spread_bps, 1),
        },
    )


# ----- R4 POST_RUN_HOLD ---------------------------------------------
# 5-60 minutes after an initial run (any R1/R2/R3 signal), the coin
# has held a large portion of its gains, the book has normalised, and
# buy pressure remains elevated.  This is the "continuation setup"
# discretionary traders look for before the second leg.
#
# The engine supplies:
#   run_peak_mid     : highest mid seen since the original signal
#   run_signal_mid   : mid at the time of the original signal
#   secs_since_signal: seconds elapsed since original signal
R4_MIN_HOLD_RATIO         = 0.50   # must hold ≥50% of peak gain from signal
R4_MAX_PULLBACK_FROM_PEAK = 0.40   # but not a minor dip: must be at ≥40% of peak
R4_MIN_SECS_AFTER_RUN     = 300    # at least 5 min since original signal
R4_MAX_SECS_AFTER_RUN     = 3600   # no more than 60 min — stale
R4_BUY_SHARE_60S_MIN      = 0.52   # buy pressure still slightly dominant
# Rate condition: absolute floor (not a ratio — during consolidation the rate
# is below the explosion baseline, so a ratio would always fail).
# 0.1 trades/s = 6 per minute — coin must still be trading.
# 3.0 trades/s cap — if it's in full frenzy again, R3 handles it.
R4_RATE_ABS_MIN           = 0.10
R4_RATE_ABS_MAX           = 3.0
R4_SIGNAL_SPREAD_BPS      = 25.0   # tighter — we want a clean book for entry


def check_r4_post_run_hold(state: CoinState, now_ns: int,
                           run_peak_mid: float,
                           run_signal_mid: float,
                           secs_since_signal: float,
                           spread_bps: float = 0.0) -> Optional[SignalEvent]:
    """Fires when a post-run consolidation looks likely to continue up."""
    if spread_bps > R4_SIGNAL_SPREAD_BPS:
        return None
    if not (R4_MIN_SECS_AFTER_RUN <= secs_since_signal <= R4_MAX_SECS_AFTER_RUN):
        return None
    if run_signal_mid <= 0 or run_peak_mid <= run_signal_mid:
        return None

    peak_gain      = (run_peak_mid - run_signal_mid) / run_signal_mid
    current_gain   = (state.last_mid - run_signal_mid) / run_signal_mid
    if peak_gain <= 0:
        return None
    hold_ratio     = current_gain / peak_gain
    # Must hold ≥50% of the peak gain from signal price
    if hold_ratio < R4_MIN_HOLD_RATIO:
        return None
    # Must have pulled back at least a little (not still at the peak — R3 handles that)
    pullback_from_peak = (run_peak_mid - state.last_mid) / run_peak_mid
    if pullback_from_peak < 0.005:  # barely off peak, R3 would fire instead
        return None
    if pullback_from_peak > R4_MAX_PULLBACK_FROM_PEAK:
        return None

    buy_share = state.buy_share_in(now_ns, 60)
    if buy_share < R4_BUY_SHARE_60S_MIN:
        return None

    rate_30s = state.trade_count_in(now_ns, 30) / 30.0
    if not (R4_RATE_ABS_MIN <= rate_30s <= R4_RATE_ABS_MAX):
        return None

    return SignalEvent(
        variant="R4_POST_RUN_HOLD",
        coin=state.coin,
        sig_ts_ns=now_ns,
        sig_mid=state.last_mid,
        features={
            "secs_since_run":       round(secs_since_signal, 1),
            "run_peak_mid":         round(run_peak_mid, 8),
            "run_signal_mid":       round(run_signal_mid, 8),
            "peak_gain_pct":        round(peak_gain * 100, 3),
            "hold_ratio":           round(hold_ratio, 3),
            "pullback_from_peak":   round(pullback_from_peak, 4),
            "buy_share_60s":        round(buy_share, 3),
            "rate_30s":             round(rate_30s, 3),
            "spread_bps":           round(spread_bps, 1),
        },
    )


# ----- R5 CONFIRMED_RUN --------------------------------------------
# The human trader's process: coin is ALREADY a top gainer on the day
# AND currently green on all three timeframes AND volume is not fading.
# This is NOT chasing the first spike — it fires during sustained runs.
# Entry is cleaner because the book has normalized post-explosion.
#
# 15-min return requires mid_window_s >= 1800 in CoinState.
R5_RET_24H_MIN      = 0.12   # already up 12%+ today
R5_RET_24H_EXHST_LO = 1.0   # exhaustion zone: 100-200% 24h gain = dangerous late entry
R5_RET_24H_EXHST_HI = 2.0   # above 200% = still running (MEZO-type outlier), allow
# v10 cross-tab (n=51): r24 < 1.0 tiers = 68-79% WR; r24 > 2.0 = 100% WR +12.2% EV (n=5)
# The exhaustion block (1.0-2.0) is correct: that's the dangerous late-entry zone.
# r24 > 2.0 outlier movers are NOT weak — they're the highest-EV subset in the dataset.
R5_RET_15M_MIN   = 0.020   # green 15-min
# r5m bimodal: consolidation entry (0.5-1%) OR surge entry (3%+)
# "uncanny valley" 1-3% = decelerating momentum, ~0.66% EV → blocked
# v10 backtest: 0.5-1% bucket 24 trades 83% WR; 3%+ bucket 27 trades 67% WR
R5_RET_5M_LO_MIN = 0.005   # consolidation entry floor
R5_RET_5M_LO_MAX = 0.010   # consolidation entry ceiling (exclusive)
R5_RET_5M_HI_MIN = 0.030   # surge entry floor (no ceiling)
R5_RET_1M_MIN    = 0.002   # still moving now
# dvt bimodal: steady stable (1.0-1.5) OR institutional tsunami (2.5+)
# moderate surge (1.5-2.5) = net negative EV in backtest → blocked
# floor at 1.0 is critical — dvt < 1.0 = declining volume = do not enter
# v10 backtest: [1.0,1.5) bucket 29 trades 72% WR; [2.5,∞) bucket 21 trades 81% WR
R5_DVT_STBL_MIN  = 1.0     # stable volume floor
R5_DVT_STBL_MAX  = 1.5     # stable volume ceiling (exclusive)
R5_DVT_SURGE_MIN = 2.5     # institutional surge floor (no ceiling)
R5_SPREAD_MAX_BPS = 10.0   # hard cap: >10bps is net losing in backtest (replaces dynamic gate)
R5_TOP_K_RANK    = 10

# ── Position sizing tiers (half-Kelly from v10 cross-tab, n=51) ──
# Ordered by EV/risk (half-Kelly), NOT by win rate.
# r5m_zone × dvt_zone cross-tabulation:
#   A  consol + stable  n=11  82% WR  +7.5% adj_EV  half-K 39%  → 40% bankroll
#   B  consol + instit  n=13  85% WR  +4.3% adj_EV  half-K 35%  → 35% bankroll
#   C  surge  + stable  n=18  67% WR  +4.2% adj_EV  half-K 25%  → 25% bankroll
#   D  surge  + instit  n= 9  67% WR  +3.2% adj_EV  half-K 20%  → 20% bankroll
# Tier A has the best risk-adjusted return: huge b-ratio (6.25x), tiny avg loss (-1.6%).
# Tier B has highest WR but larger losses (-5.8%) pull Kelly below Tier A.
#
# LIVE RECALIBRATION 2026-04-17 (134 live shadow trades, 4.8 days):
#   Backtest WR/EV diverged significantly from live — signal fires 109x/day vs 0.69
#   backtest (reduced selectivity in bull market). Live-derived half-Kelly sizing:
#   A: WR=10% adj_EV=-4.1%  → 5%  (net loser — de minimis until re-validated)
#   B: WR=23% adj_EV=-2.8%  → 5%  (net loser — de minimis until re-validated)
#   C: WR=57% adj_EV=+3.2%  → 21% (only profitable tier — hold sizing)
#   D: WR=41% adj_EV=-1.1%  → 5%  (marginally losing — de minimis)
#   At ~$195 balance, 5% = $9.75 which is below MIN_ORDER_USD ($10) → A/B/D skip.
#   Revisit when: 50+ trades per tier OR market regime returns to backtest conditions.
R5_TIER_POS = {'A': 0.05, 'B': 0.05, 'C': 0.21, 'D': 0.05}


def check_r5_confirmed_run(state: CoinState, now_ns: int,
                           rank_60s: Optional[int],
                           ret_24h: float,
                           spread_bps: float = 0.0) -> Optional[SignalEvent]:
    """Fires when a coin is confirmed running on all timeframes — not a spike.

    Exhaustion filter: block ret_24h in the 100-200% zone (39% WR, -24.7% total).
    Allow r24 > 200% — those are outlier movers (100% WR, +12.2% EV in v10).

    r5m bimodal filter (v10): consolidation entries (0.5-1%) OR surge entries (3%+).
    The 1-3% uncanny valley is decelerating momentum — EV ~0.66%, blocked.

    dvt bimodal filter (v10): steady stable volume (1.0-1.5x) OR institutional
    tsunami (2.5x+). Moderate surge (1.5-2.5x) is net negative. Floor at 1.0
    is critical — dvt < 1.0 means declining volume, never enter.

    Spread hard cap: 10bps. >10bps is net losing.

    Confidence tier (half-Kelly position sizing from v10 cross-tab n=51):
      A (consol+stable):  82% WR, +7.5% adj_EV, b=6.25x → 40% bankroll
      B (consol+instit):  85% WR, +4.3% adj_EV, b=1.14x → 35% bankroll
      C (surge+stable):   67% WR, +4.2% adj_EV, b=2.46x → 25% bankroll
      D (surge+instit):   67% WR, +3.2% adj_EV, b=1.41x → 20% bankroll
    Tier A has the best risk-adjusted return despite lower WR than B: its losses
    average only -1.6% (vs -5.8% for B) giving it a 6.25x win/loss ratio.
    """
    if spread_bps > R5_SPREAD_MAX_BPS:
        return None
    if rank_60s is None or rank_60s > R5_TOP_K_RANK:
        return None
    if ret_24h < R5_RET_24H_MIN:
        return None
    # Exhaustion zone: 100-200% 24h gain → losing tier (39% WR, -24.7% total)
    if R5_RET_24H_EXHST_LO <= ret_24h < R5_RET_24H_EXHST_HI:
        return None

    r15m = state.return_over(now_ns, 900)
    r5m  = state.return_over(now_ns, 300)
    r1m  = state.return_over(now_ns, 60)

    if r15m < R5_RET_15M_MIN:
        return None
    # Bimodal r5m: consolidation entry (0.5-1%) OR surge entry (3%+)
    r5m_consol = R5_RET_5M_LO_MIN <= r5m < R5_RET_5M_LO_MAX
    r5m_surge  = r5m >= R5_RET_5M_HI_MIN
    if not (r5m_consol or r5m_surge):
        return None
    if r1m < R5_RET_1M_MIN:
        return None

    dv_trend = state.dv_trend(now_ns, 60)
    # Bimodal dvt: stable volume (1.0-1.5) OR institutional surge (2.5+)
    dvt_stable = R5_DVT_STBL_MIN <= dv_trend < R5_DVT_STBL_MAX
    dvt_instit = dv_trend >= R5_DVT_SURGE_MIN
    if not (dvt_stable or dvt_instit):
        return None

    # ── Confidence tier → position size (half-Kelly, v10 cross-tab) ──
    if r5m_consol and dvt_stable:
        tier, pos_pct = 'A', R5_TIER_POS['A']   # best EV/risk: 40%
    elif r5m_consol and dvt_instit:
        tier, pos_pct = 'B', R5_TIER_POS['B']   # high WR: 35%
    elif r5m_surge and dvt_stable:
        tier, pos_pct = 'C', R5_TIER_POS['C']   # solid: 25%
    else:                                         # r5m_surge + dvt_instit
        tier, pos_pct = 'D', R5_TIER_POS['D']   # weakest: 20%

    return SignalEvent(
        variant="R5_CONFIRMED_RUN",
        coin=state.coin,
        sig_ts_ns=now_ns,
        sig_mid=state.last_mid,
        features={
            "ret_24h":          round(ret_24h, 5),
            "ret_15m":          round(r15m, 5),
            "ret_5m":           round(r5m, 5),
            "ret_1m":           round(r1m, 5),
            "dv_trend":         round(dv_trend, 3),
            "rank_60s":         rank_60s,
            "spread_bps":       round(spread_bps, 1),
            "typical_spread":   round(state.typical_spread_bps(), 1),
            "confidence_tier":  tier,
            "position_pct":     pos_pct,
        },
    )


# ----- R6 LOCAL_BREAKOUT --------------------------------------------
# Coin consolidates for 2-4 minutes then breaks ABOVE its local high
# with a volume surge. The "second wind" pattern — price paused,
# absorbed selling, then buyers stepped back in.
# Requires coin is already a mover today (don't catch cold breakouts).
R6_RET_24H_MIN        = 0.15   # raised from 0.05→0.15 per phase4 data: ret_24h<15% is net losing
R6_CONSOLIDATION_S    = 180    # measure local high over prior 3 minutes
R6_LOOKBACK_SKIP_S    = 20     # exclude last 20s from "prior high" (the breakout itself)
R6_BREAKOUT_MIN_PCT   = 0.004  # must clear prior high by at least 0.4%
R6_DV_BURST_MULT      = 2.5    # last-30s volume ≥ 2.5× baseline rate


def check_r6_local_breakout(state: CoinState, now_ns: int,
                            rank_60s: Optional[int],
                            ret_24h: float,
                            spread_bps: float = 0.0) -> Optional[SignalEvent]:
    """Fires on a confirmed breakout above a brief consolidation range."""
    if spread_bps > state.dynamic_spread_gate(SPREAD_FLOOR_BPS, SPREAD_CAP_BPS, SPREAD_COMPRESSION):
        return None
    if ret_24h < R6_RET_24H_MIN:
        return None

    # Local high: highest mid in [CONSOLIDATION_S .. LOOKBACK_SKIP_S] ago
    window_start_ns = now_ns - R6_CONSOLIDATION_S * NS
    window_end_ns   = now_ns - R6_LOOKBACK_SKIP_S  * NS
    prior_mids = [mp.mid for mp in state.mids
                  if window_start_ns <= mp.ts_ns <= window_end_ns]
    if len(prior_mids) < 5:
        return None
    prior_high = max(prior_mids)
    if prior_high <= 0:
        return None

    breakout_pct = (state.last_mid / prior_high) - 1.0
    if breakout_pct < R6_BREAKOUT_MIN_PCT:
        return None

    # Volume burst in last 30s vs the consolidation baseline rate
    dv_burst    = state.dollar_volume_in(now_ns, 30)
    dv_baseline = state.dollar_volume_in(now_ns, R6_CONSOLIDATION_S) - dv_burst
    baseline_rate = dv_baseline / max(R6_CONSOLIDATION_S - 30, 1)
    if baseline_rate <= 0 or (dv_burst / 30.0) < R6_DV_BURST_MULT * baseline_rate:
        return None

    return SignalEvent(
        variant="R6_LOCAL_BREAKOUT",
        coin=state.coin,
        sig_ts_ns=now_ns,
        sig_mid=state.last_mid,
        features={
            "ret_24h":       round(ret_24h, 5),
            "breakout_pct":  round(breakout_pct, 5),
            "prior_high":    round(prior_high, 8),
            "dv_burst_30s":  round(dv_burst, 2),
            "dv_burst_mult": round((dv_burst / 30.0) / baseline_rate if baseline_rate > 0 else 0, 2),
            "rank_60s":      rank_60s,
            "spread_bps":    round(spread_bps, 1),
        },
    )


# ----- R7 STAIRCASE -------------------------------------------------
# Three consecutive 1-minute green candles. Not a spike — a climb.
# The most visually obvious "still going" pattern. Each 60s interval
# must show positive return above a minimum threshold to exclude noise.
R7_RET_24H_MIN   = 0.12    # already up 12%+ today (was 5% — far too loose)
R7_STEP_MIN_PCT  = 0.003   # each 60s step must be up ≥ 0.3%
R7_TOP_K_RANK    = 10


def check_r7_staircase(state: CoinState, now_ns: int,
                       rank_60s: Optional[int],
                       ret_24h: float,
                       spread_bps: float = 0.0) -> Optional[SignalEvent]:
    """Fires when the coin has posted 3 consecutive positive 1-min returns."""
    if spread_bps > state.dynamic_spread_gate(SPREAD_FLOOR_BPS, SPREAD_CAP_BPS, SPREAD_COMPRESSION):
        return None
    if rank_60s is None or rank_60s > R7_TOP_K_RANK:
        return None
    if ret_24h < R7_RET_24H_MIN:
        return None

    # Measure 3 sequential 60s windows ending at now
    steps = []
    for i in range(1, 4):  # i=1 (0-60s ago), i=2 (60-120s), i=3 (120-180s)
        end_ns   = now_ns - (i - 1) * 60 * NS
        start_ns = now_ns - i       * 60 * NS
        mid_end   = state.mid_at_or_before(end_ns)
        mid_start = state.mid_at_or_before(start_ns)
        if mid_start <= 0 or mid_end <= 0:
            return None
        step_ret = (mid_end / mid_start) - 1.0
        if step_ret < R7_STEP_MIN_PCT:
            return None
        steps.append(round(step_ret, 5))

    return SignalEvent(
        variant="R7_STAIRCASE",
        coin=state.coin,
        sig_ts_ns=now_ns,
        sig_mid=state.last_mid,
        features={
            "ret_24h":   round(ret_24h, 5),
            "step_1m":   steps[0],
            "step_2m":   steps[1],
            "step_3m":   steps[2],
            "total_3m":  round(sum(steps), 5),
            "rank_60s":  rank_60s,
            "spread_bps": round(spread_bps, 1),
        },
    )


# ----- R8 HIGH_CONVICTION -------------------------------------------
# The tightest signal — all quality gates stacked simultaneously.
# Designed to fire rarely but at the highest-confidence setups the
# data identified: major mover + strong step structure + whale presence
# + liquid book.  Every R8 that fires is worth examining.
#
# Data findings that drove these thresholds:
#   - ret_24h > 12% filters out 70%+ of noise coins (CB-only micro-caps)
#   - spread ≤ 12bps: Q1 spread bucket is the only one near breakeven
#   - step_2m Q4 (> 0.011) is the only step quartile near breakeven
#   - large_trade_pct > 0: whale filter → 65% win rate on existing data
#   - rank ≤ 5: top 5 rather than top 10 — true market leaders
R8_RET_24H_MIN       = 0.15    # major mover — up 15%+ today
R8_STEP_MIN_PCT      = 0.005   # each 60s step ≥ 0.5% (stronger than R7's 0.3%)
R8_STEP_2M_MIN       = 0.008   # middle step ≥ 0.8% — confirms acceleration
R8_DV_TREND_MIN      = 0.90    # volume holding (not fading)
R8_WHALE_PCT_MIN     = 0.05    # at least 5% of 60s volume from large trades
R8_TOP_K_RANK        = 5       # top 5 only
R8_LARGE_TRADE_USD   = 5_000   # threshold for "large trade" (same as state default)


def check_r8_high_conviction(state: CoinState, now_ns: int,
                              rank_60s: Optional[int],
                              ret_24h: float,
                              spread_bps: float = 0.0) -> Optional[SignalEvent]:
    """Fires only when every quality gate passes simultaneously.

    Designed to produce the smallest signal count but highest win rate.
    Every gate was chosen because the data showed it individually improves
    outcomes; all gates together should compound the edge.
    """
    if spread_bps > state.dynamic_spread_gate(SPREAD_FLOOR_BPS, SPREAD_CAP_BPS, SPREAD_COMPRESSION):
        return None
    if rank_60s is None or rank_60s > R8_TOP_K_RANK:
        return None
    if ret_24h < R8_RET_24H_MIN:
        return None

    # Three consecutive steps — each must clear R8_STEP_MIN_PCT
    steps = []
    for i in range(1, 4):
        end_ns   = now_ns - (i - 1) * 60 * NS
        start_ns = now_ns - i       * 60 * NS
        mid_end   = state.mid_at_or_before(end_ns)
        mid_start = state.mid_at_or_before(start_ns)
        if mid_start <= 0 or mid_end <= 0:
            return None
        step_ret = (mid_end / mid_start) - 1.0
        if step_ret < R8_STEP_MIN_PCT:
            return None
        steps.append(round(step_ret, 5))

    # Middle step (2-3 min ago) must show extra strength — confirms the
    # move had legs in the middle, not just a last-second push.
    if steps[1] < R8_STEP_2M_MIN:
        return None

    # Volume not fading
    dv_trend = state.dv_trend(now_ns, 60)
    if dv_trend < R8_DV_TREND_MIN:
        return None

    # Whale presence required — institutional validation of the move
    whale_pct = state.large_trade_pct_in(now_ns, 60, threshold_usd=R8_LARGE_TRADE_USD)
    if whale_pct < R8_WHALE_PCT_MIN:
        return None

    return SignalEvent(
        variant="R8_HIGH_CONVICTION",
        coin=state.coin,
        sig_ts_ns=now_ns,
        sig_mid=state.last_mid,
        features={
            "ret_24h":          round(ret_24h, 5),
            "step_1m":          steps[0],
            "step_2m":          steps[1],
            "step_3m":          steps[2],
            "total_3m":         round(sum(steps), 5),
            "dv_trend":         round(dv_trend, 3),
            "whale_pct_60s":    round(whale_pct, 3),
            "rank_60s":         rank_60s,
            "spread_bps":       round(spread_bps, 1),
        },
    )


# ----- R9 VOLUME_STAIRCASE ------------------------------------------
# Derived entirely from reverse-engineering 7,226 RAVE snapshots.
#
# The three conditions that predicted +3%/5m AND +5%/10m at 57.8% precision
# (n=45, 4.8x base rate of 12%) with no hand-tuning:
#
#   1. dv_30s >= $100k    — explosive volume in last 30 seconds
#   2. mean_step >= 1%    — 3-minute staircase averaging 1%/min (sustained, not spikey)
#   3. avg_trade >= $500  — institutional sizing (filters retail noise)
#
# NO spread gate — analysis showed setup moments had 74bps avg spread vs
# 32bps all-moments average. Absolute spread gates are wrong for micro-caps;
# the volume+staircase+size combo is the self-contained quality filter.
# Spread is logged as a feature for future phase analysis.
#
# Rank gate is loose (top-20) intentionally: micro-cap runners often don't
# appear in cross-sectional top-5 because the broader market isn't moving.
R9_DV_30S_MIN       = 100_000   # $100k in last 30 seconds (single strongest predictor)
R9_STAIR_MEAN_MIN   = 0.010     # mean of 3 × 60s steps >= 1%
R9_STAIR_STEP_MIN   = 0.003     # each step >= 0.3% — all three must be green
R9_AVG_TRADE_MIN    = 500.0     # avg trade size in 60s >= $500
R9_RET_24H_MIN      = 0.05      # minimal gate — just confirm this is a mover
R9_TOP_K_RANK       = 20        # loose — micro-caps often outside top-10


def check_r9_volume_staircase(state: CoinState, now_ns: int,
                               rank_60s: Optional[int],
                               ret_24h: float,
                               spread_bps: float = 0.0) -> Optional[SignalEvent]:
    """Data-derived signal: large volume burst + sustained staircase + institutional size.

    No spread gate — the three-condition combination is self-filtering.
    Derived from RAVE reverse-engineering: 57.8% precision at n=45 (4.8x base rate).
    Generalizes to any coin experiencing a genuine institutional buying surge.
    """
    if ret_24h < R9_RET_24H_MIN:
        return None
    if rank_60s is not None and rank_60s > R9_TOP_K_RANK:
        return None

    # Gate 1: volume burst — most important single predictor
    dv_30s = state.dollar_volume_in(now_ns, 30)
    if dv_30s < R9_DV_30S_MIN:
        return None

    # Gate 2: quality staircase — all 3 steps green AND mean >= 1%
    steps = []
    for i in range(1, 4):
        end_ns   = now_ns - (i - 1) * 60 * NS
        start_ns = now_ns - i       * 60 * NS
        mid_end   = state.mid_at_or_before(end_ns)
        mid_start = state.mid_at_or_before(start_ns)
        if mid_start <= 0 or mid_end <= 0:
            return None
        step_ret = (mid_end / mid_start) - 1.0
        if step_ret < R9_STAIR_STEP_MIN:
            return None
        steps.append(round(step_ret, 5))
    mean_step = sum(steps) / 3.0
    if mean_step < R9_STAIR_MEAN_MIN:
        return None

    # Gate 3: institutional sizing — not retail scatter
    avg_size = state.avg_trade_size_in(now_ns, 60)
    if avg_size < R9_AVG_TRADE_MIN:
        return None

    # Log spread context for phase5 analysis (not a gate)
    typical_sprd = state.typical_spread_bps()
    spread_ratio = spread_bps / typical_sprd if typical_sprd > 0 else 0.0

    return SignalEvent(
        variant="R9_VOLUME_STAIRCASE",
        coin=state.coin,
        sig_ts_ns=now_ns,
        sig_mid=state.last_mid,
        features={
            "ret_24h":          round(ret_24h, 5),
            "dv_30s":           round(dv_30s, 2),
            "step_1m":          steps[0],
            "step_2m":          steps[1],
            "step_3m":          steps[2],
            "mean_step":        round(mean_step, 5),
            "avg_trade_size":   round(avg_size, 2),
            "spread_bps":       round(spread_bps, 1),
            "typical_spread":   round(typical_sprd, 1),
            "spread_ratio":     round(spread_ratio, 3),
            "rank_60s":         rank_60s,
        },
    )


VARIANTS = [
    ("R1_TAPE_BURST",         check_r1_tape_burst,         {"requires_prev_rank": False}),
    ("R2_RANK_TAKEOVER",      check_r2_rank_takeover,      {"requires_prev_rank": True}),
    ("R3_DV_EXPLOSION",       check_r3_dv_explosion,       {"requires_prev_rank": False}),
    ("R4_POST_RUN_HOLD",      check_r4_post_run_hold,      {"requires_prev_rank": False, "engine_supplied": True}),
    ("R5_CONFIRMED_RUN",      check_r5_confirmed_run,      {"requires_prev_rank": False, "requires_ret_24h": True}),
    ("R6_LOCAL_BREAKOUT",     check_r6_local_breakout,     {"requires_prev_rank": False, "requires_ret_24h": True}),
    ("R7_STAIRCASE",          check_r7_staircase,          {"requires_prev_rank": False, "requires_ret_24h": True}),
    ("R8_HIGH_CONVICTION",    check_r8_high_conviction,    {"requires_prev_rank": False, "requires_ret_24h": True}),
    ("R9_VOLUME_STAIRCASE",   check_r9_volume_staircase,   {"requires_prev_rank": False, "requires_ret_24h": True}),
]
