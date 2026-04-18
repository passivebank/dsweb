"""
state.py — per-coin streaming O(1)-ish state for the CURRENTLY_RIPPING detector.

The detector consumes one event at a time (a Trade or a Quote), updates
this state, and asks "is this coin ripping right now?". Everything is
strictly point-in-time: no event in the future can influence the answer.

Two streaming windows are maintained per coin:
  - a TRADE window: deque of (recv_ts_ns, price, size_usd, side) with
    capacity bounded by the longest lookback we need (default 600s).
  - a MID window: deque of (recv_ts_ns, mid) used for short-horizon
    return / pullback computation. Mid updates come from quote (ticker)
    events; if quotes are unavailable for a coin, the trade price acts
    as a fallback mid.

Time is recv_ts_ns (local receipt). server_ts is recorded separately
for latency measurement but the detector uses recv_ts so that the
shadow runner sees events in the order the box actually saw them.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque

NS = 1_000_000_000


@dataclass
class TradePoint:
    ts_ns: int
    price: float
    size_usd: float
    side: str  # 'buy' or 'sell' (taker side)


@dataclass
class MidPoint:
    ts_ns: int
    mid: float


@dataclass
class CoinState:
    coin: str
    # Trade window — capacity in seconds.
    # mid_window_s extended to 1800 so R5/R7 can compute 15-min returns.
    trade_window_s: int = 600
    mid_window_s: int = 1800

    trades: Deque[TradePoint] = field(default_factory=deque)
    mids: Deque[MidPoint] = field(default_factory=deque)

    # Rolling spread history (last 600 observations) for dynamic spread gate.
    # Stored as raw bps values; no timestamp needed since we cap by count.
    spreads: Deque = field(default_factory=lambda: deque(maxlen=600))

    last_trade_ts_ns: int = 0
    last_mid: float = 0.0
    last_event_ts_ns: int = 0
    n_total_trades: int = 0

    def _evict(self, now_ns: int) -> None:
        cutoff_trade = now_ns - self.trade_window_s * NS
        while self.trades and self.trades[0].ts_ns < cutoff_trade:
            self.trades.popleft()
        cutoff_mid = now_ns - self.mid_window_s * NS
        while self.mids and self.mids[0].ts_ns < cutoff_mid:
            self.mids.popleft()

    def on_trade(self, ts_ns: int, price: float, size: float, side: str) -> None:
        if price <= 0 or size <= 0:
            return
        self.trades.append(TradePoint(ts_ns, price, size * price, side))
        self.last_trade_ts_ns = ts_ns
        self.last_event_ts_ns = max(self.last_event_ts_ns, ts_ns)
        self.n_total_trades += 1
        # Use trade as mid fallback if no recent quote
        if self.last_mid == 0.0 or ts_ns - self.mids[-1].ts_ns > 5 * NS if self.mids else True:
            self.mids.append(MidPoint(ts_ns, price))
            self.last_mid = price
        self._evict(ts_ns)

    def on_quote(self, ts_ns: int, bid: float, ask: float) -> None:
        if bid <= 0 or ask <= 0 or ask < bid:
            return
        mid = (bid + ask) / 2.0
        self.mids.append(MidPoint(ts_ns, mid))
        self.last_mid = mid
        self.last_event_ts_ns = max(self.last_event_ts_ns, ts_ns)
        spread_bps = (ask - bid) / mid * 1e4
        if spread_bps > 0:
            self.spreads.append(spread_bps)
        self._evict(ts_ns)

    # ---- queries used by detectors ------------------------------

    def trade_count_in(self, now_ns: int, lookback_s: int) -> int:
        cutoff = now_ns - lookback_s * NS
        # trades is ordered ascending by ts_ns; count from the right
        c = 0
        for tp in reversed(self.trades):
            if tp.ts_ns < cutoff:
                break
            c += 1
        return c

    def dollar_volume_in(self, now_ns: int, lookback_s: int) -> float:
        cutoff = now_ns - lookback_s * NS
        s = 0.0
        for tp in reversed(self.trades):
            if tp.ts_ns < cutoff:
                break
            s += tp.size_usd
        return s

    def buy_share_in(self, now_ns: int, lookback_s: int) -> float:
        cutoff = now_ns - lookback_s * NS
        b = 0.0
        t = 0.0
        for tp in reversed(self.trades):
            if tp.ts_ns < cutoff:
                break
            t += tp.size_usd
            if tp.side == "buy":
                b += tp.size_usd
        if t == 0:
            return 0.5
        return b / t

    def mid_at_or_before(self, target_ns: int) -> float:
        """The most recent mid with ts_ns <= target_ns. 0.0 if none."""
        # mids is ascending; iterate from the right
        for mp in reversed(self.mids):
            if mp.ts_ns <= target_ns:
                return mp.mid
        return 0.0

    def return_over(self, now_ns: int, lookback_s: int) -> float:
        """Return = (last_mid / mid_at[now - lookback_s]) - 1."""
        if not self.mids:
            return 0.0
        target = now_ns - lookback_s * NS
        old = self.mid_at_or_before(target)
        if old <= 0:
            return 0.0
        return (self.last_mid / old) - 1.0

    def max_pullback_over(self, now_ns: int, lookback_s: int) -> float:
        """
        Largest peak-to-trough drawdown of the mid in the last `lookback_s`
        seconds, expressed as a positive fraction. Used to test "no
        meaningful pullback yet".
        """
        if not self.mids:
            return 0.0
        cutoff = now_ns - lookback_s * NS
        # Walk forward through the relevant slice; could be optimized
        # with monotonic deque but the deque sizes here are small.
        max_seen = 0.0
        max_dd = 0.0
        started = False
        for mp in self.mids:
            if mp.ts_ns < cutoff:
                continue
            started = True
            if mp.mid > max_seen:
                max_seen = mp.mid
            if max_seen > 0:
                dd = (max_seen - mp.mid) / max_seen
                if dd > max_dd:
                    max_dd = dd
        if not started:
            return 0.0
        return max_dd

    def is_monotone_up(self, now_ns: int, lookback_s: int, max_drawdown_pct: float) -> bool:
        """True if max_pullback_over(lookback_s) <= max_drawdown_pct."""
        return self.max_pullback_over(now_ns, lookback_s) <= max_drawdown_pct

    def dv_trend(self, now_ns: int, window_s: int = 60) -> float:
        """Dollar-volume in last window_s / dollar-volume in prior window_s.

        > 1.0 = volume accelerating (good).
        < 1.0 = volume fading (run may be ending).
        Returns 1.0 if prior window has no data (neutral, not a blocker).
        """
        dv_now  = self.dollar_volume_in(now_ns, window_s)
        dv_prev = self.dollar_volume_in(now_ns, window_s * 2) - dv_now
        if dv_prev <= 0:
            return 1.0
        return dv_now / dv_prev

    def cvd_in(self, now_ns: int, lookback_s: int) -> float:
        """Cumulative volume delta: (buy_usd - sell_usd) in the lookback window.

        Positive = net buying pressure. Raw dollar-denominated so Phase 4
        can normalize however it wants. Returns 0.0 if no trades in window.
        """
        cutoff = now_ns - lookback_s * NS
        buy_usd = 0.0
        sell_usd = 0.0
        for tp in reversed(self.trades):
            if tp.ts_ns < cutoff:
                break
            if tp.side == "buy":
                buy_usd += tp.size_usd
            else:
                sell_usd += tp.size_usd
        return buy_usd - sell_usd

    def avg_trade_size_in(self, now_ns: int, lookback_s: int) -> float:
        """Average USD size per trade in window. Larger = institutional interest."""
        cutoff = now_ns - lookback_s * NS
        sizes = [tp.size_usd for tp in reversed(self.trades) if tp.ts_ns >= cutoff]
        if not sizes:
            return 0.0
        return sum(sizes) / len(sizes)

    def large_trade_pct_in(self, now_ns: int, lookback_s: int, threshold_usd: float = 5000.0) -> float:
        """Fraction of dollar volume from trades >= threshold_usd. Whale proxy."""
        cutoff = now_ns - lookback_s * NS
        total = 0.0
        large = 0.0
        for tp in reversed(self.trades):
            if tp.ts_ns < cutoff:
                break
            total += tp.size_usd
            if tp.size_usd >= threshold_usd:
                large += tp.size_usd
        if total <= 0:
            return 0.0
        return large / total

    def typical_spread_bps(self, min_samples: int = 40) -> float:
        """Rolling median spread_bps from recent quote history.

        Returns 0.0 if fewer than min_samples observations have been seen
        (caller should fall back to a fixed floor in that case).
        """
        if len(self.spreads) < min_samples:
            return 0.0
        return sorted(self.spreads)[len(self.spreads) // 2]

    def dynamic_spread_gate(self,
                             floor_bps: float = 10.0,
                             cap_bps: float = 20.0,
                             compression: float = 0.20,
                             min_samples: int = 40) -> float:
        """Max allowable spread_bps for signal qualification.

        For liquid coins whose typical spread is near floor_bps, returns
        floor_bps — identical to the old static gate (no behaviour change).

        For illiquid/micro-cap coins whose typical spread is far above
        floor_bps, the gate extends up to min(typical * compression, cap_bps).
        This captures spread-compression events — a micro-cap coin that
        normally trades at 80bps printing 5bps is experiencing a genuine
        liquidity surge, not a routine tick.

        Examples at default params (floor=10, cap=20, compression=0.20):
          BTC  typical  2bps  → max(10, min(0.4, 20))  = 10bps  (unchanged)
          SOL  typical  5bps  → max(10, min(1.0, 20))  = 10bps  (unchanged)
          RAVE typical 80bps  → max(10, min(16,  20))  = 16bps  (extended)
          thin typical 200bps → max(10, min(40,  20))  = 20bps  (capped)
        """
        typical = self.typical_spread_bps(min_samples=min_samples)
        if typical <= 0:
            return floor_bps  # insufficient history — conservative fallback
        return max(floor_bps, min(typical * compression, cap_bps))

    def vwap_in(self, now_ns: int, lookback_s: int) -> float:
        """Volume-weighted average price over window. 0 if no trades."""
        cutoff = now_ns - lookback_s * NS
        vol_px = 0.0
        vol = 0.0
        for tp in reversed(self.trades):
            if tp.ts_ns < cutoff:
                break
            vol_px += tp.price * tp.size_usd
            vol += tp.size_usd
        if vol <= 0:
            return 0.0
        return vol_px / vol

    def candle_close_strength(self, now_ns: int, lookback_s: int = 60) -> float:
        """Where in the candle's high-low range did we close?
        1.0 = closed at high (strong). 0.0 = closed at low (weak). 0.5 if flat."""
        cutoff = now_ns - lookback_s * NS
        mids_in = [mp.mid for mp in self.mids if mp.ts_ns >= cutoff]
        if len(mids_in) < 2:
            return 0.5
        high = max(mids_in)
        low = min(mids_in)
        if high == low:
            return 0.5
        return (mids_in[-1] - low) / (high - low)

    def higher_lows(self, now_ns: int, window_s: int = 60, n_windows: int = 3) -> bool:
        """True if the low of each consecutive window_s bucket is higher than the prior.
        n_windows=3 checks 3 consecutive minutes. Confirms sustained buying pressure."""
        lows = []
        for i in range(n_windows):
            start = now_ns - (i + 1) * window_s * NS
            end   = now_ns - i       * window_s * NS
            bucket = [mp.mid for mp in self.mids if start <= mp.ts_ns < end]
            if not bucket:
                return False
            lows.append(min(bucket))
        # lows[0] = most recent, lows[n-1] = oldest — must be ascending from old to new
        return all(lows[i] > lows[i + 1] for i in range(len(lows) - 1))
