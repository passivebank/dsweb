"""
shadow/simulator.py — event-driven shadow trade simulator.

For every CURRENTLY_RIPPING signal we open multiple shadow trades in
parallel — one per (entry_delay × exit_policy) combination.

Entry:
  Scheduled at sig_ts_ns + delay_ms.  On the first trade for that coin
  at or after that time we fill at trade price + half-spread haircut.
  Hard gate: if spread_bps > ENTRY_MAX_SPREAD_BPS at fill time, the
  entry is skipped (prevents paper-trading into a wide book).

Exit policies (14 total — 10 short-term + 4 wide/long for run capture):
  Short-term (original):
    tight_trail, std_trail, tp_only, partial_trail, pullback_exit,
    flow_decay, time_30s, time_60s, time_120s, time_300s
  Wide / long-hold (new — for RAVE-style sustained runs):
    wide_trail_10m  — 2% hard stop, 1.5% trail, 10-min cap
    wide_trail_30m  — 3% hard stop, 2.0% trail, 30-min cap
    breakeven_trail — trail activates only after +1% (moves stop to B/E),
                      then 1.5% trail, 20-min cap
    scale_out_30m   — partial TP at +2%, trail remainder 2%, 30-min cap

Entry delays:
  R1/R2/R3: [250ms, 500ms, 1s, 2s, 3s]   (same as before)
  R4:       [2s, 5s, 15s, 30s]            (post-run; less urgency)

Cost model:
  Round-trip = 2 × taker fee + spread.
  TAKER_FEE = 0.0015 (Coinbase Advanced 3).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from detector.currently_ripping import SignalEvent
from detector.state import NS

# --- entry -----------------------------------------------------------
ENTRY_DELAYS_MS_DEFAULT = [250]          # r5_v10 only: 250ms live timing
ENTRY_DELAYS_MS_R4      = [2000]         # r4 only: single delay
ENTRY_MAX_SPREAD_BPS    = 30.0   # skip entry if book is too wide

# Pullback entry parameters — alternative to fixed-delay entry
PULLBACK_TRIGGER_PCT  = 0.003   # wait for 0.3% dip from post-signal high
PULLBACK_RECOVER_PCT  = 0.002   # enter when price recovers 0.2% from pullback low
PULLBACK_MAX_WAIT_S   = 120     # give up after 2 minutes

# --- exit policies ---------------------------------------------------
# (name, hard_stop, trail, tp_full, tp_partial, pullback, flow_decay, time_s,
#  be_activate, trail_after_partial)
# be_activate: if set, trailing stop is dormant until price reaches
#              entry * (1 + be_activate), then stop moves to breakeven and trails.
# trail_after_partial: if set, trail switches to this value once half_closed is True.
#   Enables the v10 two-phase trail: tighter pre-partial, wider post-partial.
EXIT_POLICIES = [
    # Reduced to r5_v10 only: 1 policy × 1 delay = 1 shadow entry per signal.
    # 7% hard stop + 7% trail → 50% partial at +20% → 15% trail post-partial, 4h cap
    ("r5_v10",          0.070, 0.070, None,  0.200, None,  None, 14400, None, 0.150),
]

PULLBACK_POLICIES = []          # no wide-exit variants active


# --- cost model ------------------------------------------------------
TAKER_FEE       = 0.0015
SPREAD_FLOOR_BPS = 5.0


def _round_trip_cost(spread_bps: float) -> float:
    return 2 * (TAKER_FEE + max(SPREAD_FLOOR_BPS, spread_bps) / 1e4)


# --- data classes ----------------------------------------------------

@dataclass
class _PendingEntry:
    sig: SignalEvent
    fire_at_ns: int
    delay_ms: int
    exit_policy: tuple


@dataclass
class _PullbackPending:
    sig: SignalEvent
    exit_policy: tuple
    created_at_ns: int
    post_signal_high: float   # tracks highest price seen since signal
    seen_dip: bool = False
    dip_low: float = 0.0      # lowest price seen during the dip


@dataclass
class _OpenPos:
    sig: SignalEvent
    delay_ms: int
    exit_policy: tuple
    entry_ts_ns: int
    entry_px: float
    spread_bps: float
    max_px: float = 0.0
    half_closed_px: float = 0.0
    half_closed: bool = False
    entry_trade_rate_per_s: float = 0.0
    be_activated: bool = False      # for breakeven_trail


@dataclass
class _ClosedTrade:
    variant: str
    coin: str
    delay_ms: int
    exit_policy: str
    entry_ts_ns: int
    entry_px: float
    exit_ts_ns: int
    exit_px: float
    holding_s: float
    exit_reason: str
    gross_pct: float
    cost_pct: float
    net_pct: float
    fwd_max_pct: float
    fwd_min_pct: float
    spread_bps_at_entry: float
    sig_features: dict


# --- simulator -------------------------------------------------------

class ShadowSimulator:
    def __init__(self, log_path: Path, engine, verbose: bool = False) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = engine
        self.verbose = verbose

        self.pending: list[_PendingEntry] = []
        self.open: list[_OpenPos] = []
        self.pullback_pending: list[_PullbackPending] = []
        self.n_signals_seen = 0
        self.n_trades_closed = 0

    # ---- intake ---------------------------------------------------

    def on_signal(self, sig: SignalEvent) -> None:
        self.n_signals_seen += 1
        # Only shadow-track R5_CONFIRMED_RUN with r5_v10 exit policy.
        # Tracking all 8 variants with the 4h-cap policy causes open positions
        # to accumulate ~8x faster → latency creep. Non-R5 variants are not
        # traded live so their shadow data has no research value here.
        if sig.variant != "R5_CONFIRMED_RUN":
            return
        delays = ENTRY_DELAYS_MS_DEFAULT
        for delay_ms in delays:
            for policy in EXIT_POLICIES:
                self.pending.append(_PendingEntry(
                    sig=sig,
                    fire_at_ns=sig.sig_ts_ns + delay_ms * 1_000_000,
                    delay_ms=delay_ms,
                    exit_policy=policy,
                ))
        # Also create pullback-entry trackers for wide-exit policies
        for policy in PULLBACK_POLICIES:
            self.pullback_pending.append(_PullbackPending(
                sig=sig,
                exit_policy=policy,
                created_at_ns=sig.sig_ts_ns,
                post_signal_high=sig.sig_mid,
            ))

    def on_event(self, ev: dict) -> None:
        ch  = ev.get("ch")
        coin = ev.get("coin") or ev.get("prod") or ""
        if "-USD" in coin:
            coin = coin.split("-USD")[0]
        ts_ns = int(ev.get("recv_ts_ns") or 0)
        if not coin or ts_ns <= 0 or ch != "trade":
            return
        price = float(ev["price"])
        self._realize_pending(coin, ts_ns, price)
        self._tick_open(coin, ts_ns, price)
        self._tick_pullback(coin, ts_ns, price)

    def _realize_pending(self, coin: str, now_ns: int, trade_px: float) -> None:
        if not self.pending:
            return
        kept = []
        for pe in self.pending:
            if pe.sig.coin != coin or now_ns < pe.fire_at_ns:
                kept.append(pe)
                continue
            spread_bps = self.engine._spread_bps.get(coin, 0.0)
            # Hard entry gate: don't paper-trade into a wide book
            if spread_bps > ENTRY_MAX_SPREAD_BPS:
                continue   # drop this pending entry silently
            entry_px = trade_px * (1 + max(SPREAD_FLOOR_BPS, spread_bps) / 1e4 / 2)
            st = self.engine.coins.get(coin)
            entry_rate = st.trade_count_in(now_ns, 10) / 10.0 if st else 0.0
            self.open.append(_OpenPos(
                sig=pe.sig,
                delay_ms=pe.delay_ms,
                exit_policy=pe.exit_policy,
                entry_ts_ns=now_ns,
                entry_px=entry_px,
                spread_bps=spread_bps,
                max_px=entry_px,
                entry_trade_rate_per_s=entry_rate,
            ))
        self.pending = kept

    def _tick_open(self, coin: str, now_ns: int, px: float) -> None:
        if not self.open:
            return
        still: list[_OpenPos] = []
        for op in self.open:
            if op.sig.coin != coin:
                still.append(op)
                continue

            (name, hard_stop, trail, tp_full, tp_partial,
             pullback_pct, flow_decay, time_s, be_activate,
             trail_after_partial) = op.exit_policy
            # Use wider trail once partial exit has fired (v10 two-phase trail)
            eff_trail = (trail_after_partial
                         if (op.half_closed and trail_after_partial is not None)
                         else trail)

            if px > op.max_px:
                op.max_px = px

            # breakeven_trail: once price hits be_activate gain, move stop to B/E
            if be_activate is not None and not op.be_activated:
                if px >= op.entry_px * (1 + be_activate):
                    op.be_activated = True

            exit_reason = None
            exit_px     = None

            # Compute effective stop
            if be_activate is not None and op.be_activated:
                # Stop is max(breakeven, trailing_stop_from_peak)
                be_stop = op.entry_px
                trail_stop = op.max_px * (1 - eff_trail) if eff_trail else 0.0
                effective_stop = max(be_stop, trail_stop)
                if px <= effective_stop:
                    exit_reason = "trail_be_stop"
                    exit_px     = effective_stop
            else:
                stop_px = op.entry_px * (1 - hard_stop)
                if px <= stop_px:
                    exit_reason = "hard_stop"
                    exit_px     = stop_px

            if exit_reason is None:
                if tp_full is not None and px >= op.entry_px * (1 + tp_full):
                    exit_reason = "take_profit"
                    exit_px     = op.entry_px * (1 + tp_full)
                elif (tp_partial is not None and not op.half_closed
                      and px >= op.entry_px * (1 + tp_partial)):
                    op.half_closed    = True
                    op.half_closed_px = op.entry_px * (1 + tp_partial)
                elif (eff_trail is not None and be_activate is None
                      and op.max_px > op.entry_px
                      and px <= op.max_px * (1 - eff_trail)):
                    exit_reason = "trailing_stop"
                    exit_px     = op.max_px * (1 - eff_trail)
                elif (pullback_pct is not None and op.max_px > 0
                      and (op.max_px - px) / op.max_px >= pullback_pct):
                    exit_reason = "pullback"
                    exit_px     = px
                elif flow_decay is not None:
                    st = self.engine.coins.get(coin)
                    if st is not None:
                        cur_rate = st.trade_count_in(now_ns, 10) / 10.0
                        if (op.entry_trade_rate_per_s > 0
                                and cur_rate < flow_decay * op.entry_trade_rate_per_s
                                and now_ns - op.entry_ts_ns > 10 * NS):
                            exit_reason = "flow_decay"
                            exit_px     = px

            if exit_reason is None and (now_ns - op.entry_ts_ns) >= time_s * NS:
                exit_reason = "time_stop"
                exit_px     = px

            if exit_reason is not None:
                final_px = (op.half_closed_px + exit_px) / 2.0 if op.half_closed else exit_px
                gross    = (final_px / op.entry_px) - 1.0
                cost     = _round_trip_cost(op.spread_bps)
                net      = gross - cost
                fwd_max  = (op.max_px / op.entry_px) - 1.0
                fwd_min  = (px / op.entry_px) - 1.0
                ct = _ClosedTrade(
                    variant=op.sig.variant,
                    coin=op.sig.coin,
                    delay_ms=op.delay_ms,
                    exit_policy=name,
                    entry_ts_ns=op.entry_ts_ns,
                    entry_px=op.entry_px,
                    exit_ts_ns=now_ns,
                    exit_px=final_px,
                    holding_s=(now_ns - op.entry_ts_ns) / NS,
                    exit_reason=exit_reason,
                    gross_pct=gross,
                    cost_pct=cost,
                    net_pct=net,
                    fwd_max_pct=fwd_max,
                    fwd_min_pct=fwd_min,
                    spread_bps_at_entry=op.spread_bps,
                    sig_features=op.sig.features,
                )
                self._append(ct)
                self.n_trades_closed += 1
            else:
                still.append(op)
        self.open = still

    def _tick_pullback(self, coin: str, now_ns: int, px: float) -> None:
        if not self.pullback_pending:
            return
        kept: list[_PullbackPending] = []
        for pb in self.pullback_pending:
            if pb.sig.coin != coin:
                kept.append(pb)
                continue
            # Expire after max wait
            if (now_ns - pb.created_at_ns) > PULLBACK_MAX_WAIT_S * NS:
                continue
            # Track post-signal high
            if px > pb.post_signal_high:
                pb.post_signal_high = px
            # Check if we've seen a sufficient dip
            if not pb.seen_dip:
                dip_pct = (pb.post_signal_high - px) / pb.post_signal_high
                if dip_pct >= PULLBACK_TRIGGER_PCT:
                    pb.seen_dip = True
                    pb.dip_low = px
            else:
                # Track dip low
                if px < pb.dip_low:
                    pb.dip_low = px
                # Check for recovery — enter here
                if pb.dip_low > 0:
                    recovery = (px - pb.dip_low) / pb.dip_low
                    if recovery >= PULLBACK_RECOVER_PCT:
                        spread_bps = self.engine._spread_bps.get(coin, 0.0)
                        if spread_bps <= ENTRY_MAX_SPREAD_BPS:
                            entry_px = px * (1 + max(SPREAD_FLOOR_BPS, spread_bps) / 1e4 / 2)
                            st = self.engine.coins.get(coin)
                            entry_rate = st.trade_count_in(now_ns, 10) / 10.0 if st else 0.0
                            self.open.append(_OpenPos(
                                sig=pb.sig,
                                delay_ms=-1,       # -1 signals pullback entry
                                exit_policy=pb.exit_policy,
                                entry_ts_ns=now_ns,
                                entry_px=entry_px,
                                spread_bps=spread_bps,
                                max_px=entry_px,
                                entry_trade_rate_per_s=entry_rate,
                            ))
                        continue  # don't keep — we entered (or skipped due to spread)
            kept.append(pb)
        self.pullback_pending = kept

    # ---- persistence ---------------------------------------------

    def _append(self, ct: _ClosedTrade) -> None:
        with self.log_path.open("a") as f:
            f.write(json.dumps(asdict(ct)) + "\n")
