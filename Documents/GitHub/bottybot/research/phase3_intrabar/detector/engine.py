"""
engine.py — the streaming detector engine.

Holds:
  - per-coin CoinState
  - cross-sectional rank cache: rank by 60s return, refreshed at most
    every RANK_REFRESH_MS milliseconds
  - per-coin rolling rank history (for R2 rank-jump detection)
  - per-coin post-run tracker (for R4 continuation setup)

Spread handling (DECOUPLED):
  RANK_SPREAD_BPS  (50 bps) — a coin must be within this spread to
      appear in the cross-section rank table at all.  Wider than the
      signal gate so thin-but-moving coins are visible for R2.
  SIGNAL_SPREAD_BPS (30 bps) — enforced inside each check_rX function.
      Signals do NOT fire into wide books.

API:
  engine = DetectorEngine(on_signal_callback)
  engine.on_event(event_dict)   # called for every event in real time

The engine is the SAME class used by the live recorder AND offline
replay, eliminating look-ahead drift between the two paths.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Callable, Optional
from datetime import datetime, timezone

from .currently_ripping import (
    ELIG_DV_300S_USD,
    ELIG_MIN_TRADE_HISTORY_S,
    RANK_SPREAD_BPS,
    R2_RANK_LOOKBACK_S,
    SignalEvent,
    check_r1_tape_burst,
    check_r2_rank_takeover,
    check_r3_dv_explosion,
    check_r4_post_run_hold,
    check_r5_confirmed_run,
    check_r6_local_breakout,
    check_r7_staircase,
    R4_MIN_SECS_AFTER_RUN,
    R4_MAX_SECS_AFTER_RUN,
)
from .state import NS, CoinState

RANK_REFRESH_MS = 200    # recompute cross-sectional ranks at most every 200ms


@dataclass
class _RankSnap:
    ts_ns: int
    rank: int


@dataclass
class _RunTracker:
    """Tracks state for a coin that has fired any signal recently."""
    signal_ts_ns: int    # when the original signal fired
    signal_mid: float    # price at original signal (mid-run for R3)
    run_base_mid: float  # pre-run price: 5-min low at signal time
    peak_mid: float      # highest mid seen since signal


class DetectorEngine:
    def __init__(self, on_signal: Optional[Callable[[SignalEvent], None]] = None,
                 verbose: bool = False) -> None:
        self.coins: dict[str, CoinState] = {}
        self.on_signal = on_signal
        self.verbose = verbose
        self._last_rank_compute_ns = 0
        self._cached_rank: dict[str, int] = {}
        self._spread_bps: dict[str, float] = {}
        # rolling per-coin rank history (last R2_RANK_LOOKBACK_S seconds)
        self._rank_history: dict[str, deque[_RankSnap]] = defaultdict(deque)
        # post-run trackers: coin → _RunTracker (for R4)
        self._run_trackers: dict[str, _RunTracker] = {}
        # signal de-dup: minimum spacing per (variant, coin)
        self._last_signal_ts_ns: dict[tuple[str, str], int] = {}
        self.SIGNAL_COOLDOWN_S = 60
        self.R4_COOLDOWN_S = 1800    # 30-min cooldown on R4 per coin
        self.R5_COOLDOWN_S = 600     # 10-min cooldown — confirmed run can persist
        self.R6_COOLDOWN_S = 300     # 5-min cooldown — breakouts can repeat
        self.R7_COOLDOWN_S = 300     # 5-min cooldown
        # per-coin signal history (any variant) — 24h rolling, for context features
        self._coin_signal_history: dict[str, deque] = defaultdict(deque)
        # 24h return per coin — fed from ticker open_24h via update_ret_24h()
        self._ret_24h: dict[str, float] = {}
        # Run onset: when each coin first entered top-10 by 60s return
        self._run_onset: dict[str, int] = {}
        # Ask depth history per coin: deque of (ts_ns, ask_depth_usd) — last 90s
        self._ask_depth_hist: dict[str, deque] = defaultdict(lambda: deque(maxlen=18))
        # First-signal-today tracking: set of (coin, 'YYYY-MM-DD') strings
        self._first_signal_today: set = set()
        # Market breadth cache: (ts_ns, count)
        self._breadth_cache: tuple = (0, 0)

    # ----- external feed-ins ----------------------------------

    def update_ret_24h(self, coin: str, ret: float) -> None:
        """Called by the recorder whenever a ticker message carries open_24h."""
        self._ret_24h[coin] = ret

    # ----- event ingestion ------------------------------------

    def _coin(self, name: str) -> CoinState:
        st = self.coins.get(name)
        if st is None:
            st = CoinState(coin=name)
            self.coins[name] = st
        return st

    def on_event(self, ev: dict) -> None:
        ch = ev.get("ch")
        coin = ev.get("coin") or ev.get("prod") or ""
        if "-USD" in coin:
            coin = coin.split("-USD")[0]
        if not coin:
            return
        ts_ns = int(ev.get("recv_ts_ns") or 0)
        if ts_ns <= 0:
            return

        if ch == "trade":
            price = float(ev["price"])
            size  = float(ev["size"])
            side  = ev.get("side") or "buy"
            self._coin(coin).on_trade(ts_ns, price, size, side)
            # Update peak for any active run tracker
            rt = self._run_trackers.get(coin)
            if rt is not None and price > rt.peak_mid:
                rt.peak_mid = price
            self._maybe_check(coin, ts_ns)
        elif ch == "quote":
            bid = float(ev.get("bid") or 0)
            ask = float(ev.get("ask") or 0)
            if bid > 0 and ask > 0 and ask >= bid:
                mid = (bid + ask) / 2.0
                if mid > 0:
                    self._spread_bps[coin] = (ask - bid) / mid * 1e4
                self._coin(coin).on_quote(ts_ns, bid, ask)
                self._maybe_check(coin, ts_ns)

    # ----- cross-section --------------------------------------

    def _refresh_ranks_if_due(self, now_ns: int) -> None:
        if now_ns - self._last_rank_compute_ns < RANK_REFRESH_MS * 1_000_000:
            return
        self._last_rank_compute_ns = now_ns

        eligible_returns: list[tuple[str, float]] = []
        for coin, st in self.coins.items():
            if st.last_event_ts_ns + 30 * NS < now_ns:
                continue
            if (now_ns - (st.trades[0].ts_ns if st.trades else now_ns)) < ELIG_MIN_TRADE_HISTORY_S * NS:
                continue
            if st.dollar_volume_in(now_ns, 300) < ELIG_DV_300S_USD:
                continue
            spread = self._spread_bps.get(coin, 0.0)
            # Use RANK_SPREAD_BPS (50bps) for rank eligibility, NOT signal gate
            if spread > RANK_SPREAD_BPS:
                continue
            r60 = st.return_over(now_ns, 60)
            eligible_returns.append((coin, r60))

        eligible_returns.sort(key=lambda x: x[1], reverse=True)
        self._cached_rank = {coin: i + 1 for i, (coin, _) in enumerate(eligible_returns)}

        # update per-coin rank history for R2
        for coin, rank in self._cached_rank.items():
            hist = self._rank_history[coin]
            hist.append(_RankSnap(now_ns, rank))
            cutoff = now_ns - R2_RANK_LOOKBACK_S * NS
            while hist and hist[0].ts_ns < cutoff:
                hist.popleft()

        # Update run onset tracking
        for coin in list(self._run_onset.keys()):
            if self._cached_rank.get(coin, 999) > 10:
                del self._run_onset[coin]
        for coin, rank in self._cached_rank.items():
            if rank <= 10 and coin not in self._run_onset:
                self._run_onset[coin] = now_ns

    def _prev_min_rank(self, coin: str, now_ns: int) -> Optional[int]:
        hist = self._rank_history.get(coin)
        if not hist:
            return None
        cutoff = now_ns - R2_RANK_LOOKBACK_S * NS
        best = None
        for snap in hist:
            if snap.ts_ns >= now_ns - 100_000_000:  # exclude last 100ms (current snap)
                continue
            if snap.ts_ns < cutoff:
                continue
            if best is None or snap.rank < best:
                best = snap.rank
        return best

    # ----- variant evaluation ---------------------------------

    def _maybe_check(self, coin: str, now_ns: int) -> None:
        self._refresh_ranks_if_due(now_ns)
        st = self.coins.get(coin)
        if st is None:
            return

        spread = self._spread_bps.get(coin, 0.0)
        rank   = self._cached_rank.get(coin)

        # R1, R2, R3 require the coin to be in the rank cache
        # (has sufficient history + DV + spread ≤ RANK_SPREAD_BPS)
        if rank is not None:
            for fn, key in (
                (check_r1_tape_burst,   "R1_TAPE_BURST"),
                (check_r2_rank_takeover, "R2_RANK_TAKEOVER"),
                (check_r3_dv_explosion,  "R3_DV_EXPLOSION"),
            ):
                sig_key = (key, coin)
                last = self._last_signal_ts_ns.get(sig_key, 0)
                if now_ns - last < self.SIGNAL_COOLDOWN_S * NS:
                    continue
                if key == "R2_RANK_TAKEOVER":
                    sig = fn(st, now_ns, rank, self._prev_min_rank(coin, now_ns), spread)
                else:
                    sig = fn(st, now_ns, rank, spread)
                if sig is not None:
                    # Stamp engine-level context features onto every signal
                    sig.features["secs_since_onset"]   = round(self.secs_since_run_onset(coin, now_ns), 1)
                    sig.features["market_breadth_5m"]  = self.market_breadth(now_ns)
                    sig.features["ask_depth_trend"]    = self.ask_depth_trend(coin)
                    sig.features["first_signal_today"] = self.pop_first_signal_today(coin, now_ns)
                    btc_st = self.coins.get("BTC")
                    coin_ret5m = st.return_over(now_ns, 300)
                    btc_ret5m  = btc_st.return_over(now_ns, 300) if btc_st else 0.0
                    sig.features["btc_rel_ret_5m"]     = round(coin_ret5m - btc_ret5m, 5)
                    sig.features["avg_trade_size_60s"] = round(st.avg_trade_size_in(now_ns, 60), 2)
                    sig.features["large_trade_pct_60s"]= round(st.large_trade_pct_in(now_ns, 60), 3)
                    sig.features["vwap_300s"]          = round(st.vwap_in(now_ns, 300), 8)
                    sig.features["candle_close_str_1m"]= round(st.candle_close_strength(now_ns, 60), 3)
                    sig.features["higher_lows_3m"]     = st.higher_lows(now_ns, window_s=60, n_windows=3)
                    self._last_signal_ts_ns[sig_key] = now_ns
                    self._register_run(coin, now_ns, st.last_mid)
                    self._record_signal_history(coin, now_ns)
                    if self.on_signal is not None:
                        self.on_signal(sig)
                    if self.verbose:
                        print(f"[SIGNAL] {sig.variant} {coin} feats={sig.features}")

        # R5 / R6 / R7 — confirmation signals; require rank AND ret_24h
        ret_24h = self._ret_24h.get(coin)
        if rank is not None and ret_24h is not None:
            for fn, key, cooldown in (
                (check_r5_confirmed_run, "R5_CONFIRMED_RUN",  self.R5_COOLDOWN_S),
                (check_r6_local_breakout,"R6_LOCAL_BREAKOUT", self.R6_COOLDOWN_S),
                (check_r7_staircase,     "R7_STAIRCASE",      self.R7_COOLDOWN_S),
            ):
                sig_key = (key, coin)
                last = self._last_signal_ts_ns.get(sig_key, 0)
                if now_ns - last < cooldown * NS:
                    continue
                sig = fn(st, now_ns, rank, ret_24h, spread)
                if sig is not None:
                    # Stamp engine-level context features onto every signal
                    sig.features["secs_since_onset"]   = round(self.secs_since_run_onset(coin, now_ns), 1)
                    sig.features["market_breadth_5m"]  = self.market_breadth(now_ns)
                    sig.features["ask_depth_trend"]    = self.ask_depth_trend(coin)
                    sig.features["first_signal_today"] = self.pop_first_signal_today(coin, now_ns)
                    btc_st = self.coins.get("BTC")
                    coin_ret5m = st.return_over(now_ns, 300)
                    btc_ret5m  = btc_st.return_over(now_ns, 300) if btc_st else 0.0
                    sig.features["btc_rel_ret_5m"]     = round(coin_ret5m - btc_ret5m, 5)
                    sig.features["avg_trade_size_60s"] = round(st.avg_trade_size_in(now_ns, 60), 2)
                    sig.features["large_trade_pct_60s"]= round(st.large_trade_pct_in(now_ns, 60), 3)
                    sig.features["vwap_300s"]          = round(st.vwap_in(now_ns, 300), 8)
                    sig.features["candle_close_str_1m"]= round(st.candle_close_strength(now_ns, 60), 3)
                    sig.features["higher_lows_3m"]     = st.higher_lows(now_ns, window_s=60, n_windows=3)
                    self._last_signal_ts_ns[sig_key] = now_ns
                    self._register_run(coin, now_ns, st.last_mid)
                    self._record_signal_history(coin, now_ns)
                    if self.on_signal is not None:
                        self.on_signal(sig)
                    if self.verbose:
                        print(f"[SIGNAL] {sig.variant} {coin} feats={sig.features}")

        # R4 — independent of rank cache; fires on ANY tracked post-run coin
        rt = self._run_trackers.get(coin)
        if rt is not None:
            secs = (now_ns - rt.signal_ts_ns) / NS
            # Expire tracker after max window
            if secs > R4_MAX_SECS_AFTER_RUN:
                del self._run_trackers[coin]
            elif secs >= R4_MIN_SECS_AFTER_RUN:
                sig_key = ("R4_POST_RUN_HOLD", coin)
                last = self._last_signal_ts_ns.get(sig_key, 0)
                if now_ns - last >= self.R4_COOLDOWN_S * NS:
                    sig = check_r4_post_run_hold(
                        st, now_ns,
                        run_peak_mid=rt.peak_mid,
                        run_signal_mid=rt.run_base_mid,
                        secs_since_signal=secs,
                        spread_bps=spread,
                    )
                    if sig is not None:
                        # Stamp engine-level context features onto every signal
                        sig.features["secs_since_onset"]   = round(self.secs_since_run_onset(coin, now_ns), 1)
                        sig.features["market_breadth_5m"]  = self.market_breadth(now_ns)
                        sig.features["ask_depth_trend"]    = self.ask_depth_trend(coin)
                        sig.features["first_signal_today"] = self.pop_first_signal_today(coin, now_ns)
                        btc_st = self.coins.get("BTC")
                        coin_ret5m = st.return_over(now_ns, 300)
                        btc_ret5m  = btc_st.return_over(now_ns, 300) if btc_st else 0.0
                        sig.features["btc_rel_ret_5m"]     = round(coin_ret5m - btc_ret5m, 5)
                        sig.features["avg_trade_size_60s"] = round(st.avg_trade_size_in(now_ns, 60), 2)
                        sig.features["large_trade_pct_60s"]= round(st.large_trade_pct_in(now_ns, 60), 3)
                        sig.features["vwap_300s"]          = round(st.vwap_in(now_ns, 300), 8)
                        sig.features["candle_close_str_1m"]= round(st.candle_close_strength(now_ns, 60), 3)
                        sig.features["higher_lows_3m"]     = st.higher_lows(now_ns, window_s=60, n_windows=3)
                        self._last_signal_ts_ns[sig_key] = now_ns
                        self._record_signal_history(coin, now_ns)
                        if self.on_signal is not None:
                            self.on_signal(sig)
                        if self.verbose:
                            print(f"[SIGNAL] R4_POST_RUN_HOLD {coin} feats={sig.features}")

    def _record_signal_history(self, coin: str, now_ns: int) -> None:
        """Append signal timestamp; prune entries older than 24h."""
        hist = self._coin_signal_history[coin]
        hist.append(now_ns)
        cutoff = now_ns - 86400 * NS
        while hist and hist[0] < cutoff:
            hist.popleft()

    def signal_count_for(self, coin: str, now_ns: int, lookback_s: int) -> int:
        """Number of signals (any variant) fired for this coin in the last lookback_s seconds.

        Does NOT count the current signal — call this before _record_signal_history
        if you want the count prior to the current signal, or after if you want inclusive.
        The recorder stamps this AFTER the signal fires, so it will be the post-fire count.
        """
        hist = self._coin_signal_history.get(coin)
        if not hist:
            return 0
        cutoff = now_ns - lookback_s * NS
        return sum(1 for ts in hist if ts >= cutoff)

    def update_ask_depth(self, coin: str, ask_depth_usd: float, ts_ns: int) -> None:
        """Called by recorder after each L2 update. Tracks ask depth over time."""
        self._ask_depth_hist[coin].append((ts_ns, ask_depth_usd))

    def ask_depth_trend(self, coin: str) -> float:
        """ask_depth_now / ask_depth_60s_ago.
        < 1.0 = ask wall being consumed (bullish).
        > 1.0 = sellers showing up (bearish).
        Returns 1.0 if insufficient history."""
        hist = self._ask_depth_hist.get(coin)
        if not hist or len(hist) < 2:
            return 1.0
        now_ts, now_depth = hist[-1]
        if now_depth <= 0:
            return 1.0
        cutoff = now_ts - 60 * NS
        old_depth = None
        for ts, depth in hist:
            if ts >= cutoff:
                old_depth = depth
                break
        if old_depth is None or old_depth <= 0:
            return 1.0
        return round(now_depth / old_depth, 3)

    def market_breadth(self, now_ns: int) -> int:
        """Number of coins with ret_5m > 1% right now. Cached every 5s."""
        cache_ts, cache_val = self._breadth_cache
        if now_ns - cache_ts < 5 * NS:
            return cache_val
        count = sum(
            1 for st in self.coins.values()
            if st.last_event_ts_ns + 30 * NS >= now_ns
            and st.return_over(now_ns, 300) > 0.01
        )
        self._breadth_cache = (now_ns, count)
        return count

    def secs_since_run_onset(self, coin: str, now_ns: int) -> float:
        """Seconds since this coin first entered top-10. -1 if not currently in top-10."""
        onset = self._run_onset.get(coin)
        if onset is None:
            return -1.0
        return (now_ns - onset) / NS

    def pop_first_signal_today(self, coin: str, now_ns: int) -> bool:
        """Returns True the FIRST time a signal fires for this coin today (UTC).
        Subsequent calls return False. Side-effect: marks the coin as seen."""
        day = datetime.fromtimestamp(now_ns / 1e9, tz=timezone.utc).strftime('%Y-%m-%d')
        key = f"{coin}:{day}"
        if key not in self._first_signal_today:
            self._first_signal_today.add(key)
            return True
        return False

    def _register_run(self, coin: str, now_ns: int, mid: float) -> None:
        """Called when any R1/R2/R3 fires; starts or refreshes the R4 tracker.

        run_base_mid = 5-minute low at signal time (pre-run price).
        This ensures R4 hold_ratio is measured from the base of the move,
        not from wherever mid-run the signal happened to fire.
        """
        st = self.coins.get(coin)
        # Compute 5-min low as the pre-run base price
        run_base = mid  # fallback
        if st and st.mids:
            cutoff = now_ns - 300 * NS
            lows = [mp.mid for mp in st.mids if mp.ts_ns >= cutoff]
            if lows:
                run_base = min(lows)

        existing = self._run_trackers.get(coin)
        if existing is None:
            self._run_trackers[coin] = _RunTracker(
                signal_ts_ns=now_ns,
                signal_mid=mid,
                run_base_mid=run_base,
                peak_mid=mid,
            )
        else:
            # Refresh signal time; preserve the pre-run base from first signal
            existing.signal_ts_ns = now_ns
            if mid > existing.peak_mid:
                existing.peak_mid = mid
