"""
l2_watchlist.py — pure function from DetectorEngine state to "which coins
should currently be subscribed to L2".

Inputs:
  - the engine's per-coin CoinState (which already has return_over,
    trade_count_in, dollar_volume_in)
  - a `baseline_universe` set fetched at startup (top-30 by 24h volume)
  - the previous watchlist (so we can apply the 30-min hangover)

Outputs:
  - a set of product IDs (e.g., "BTC-USD") that should be subscribed
"""
from __future__ import annotations

from dataclasses import dataclass

NS = 1_000_000_000
HANGOVER_S = 5 * 60    # 5-min hangover: faster expiry prevents L2 overload
MAX_DYNAMIC_L2 = 8     # max 8 dynamic subs on top of ~30 baseline = ~38 total
                       # 38 L2 coins vs 381 ticker: keeps total event rate in budget


# --- trigger thresholds (single source of truth) ----------------
TRIG_RET_1MIN = 0.008
TRIG_RET_5MIN = 0.020
TRIG_RET_30MIN = 0.050
TRIG_RET_24H = 0.10
TRIG_RATE_30S_MULT = 5.0
TRIG_RATE_MIN_BASELINE_PER_S = 0.5  # require at least 0.5 trades/s baseline before rate trigger
TRIG_RATE_MIN_RECENT = 5            # AND at least 5 trades in the recent 30s window


@dataclass
class WatchlistEntry:
    coin: str
    last_trigger_ns: int


class WatchlistManager:
    def __init__(self, baseline_universe: set[str]) -> None:
        # baseline coins: always subscribed (top 30 by 24h volume, fetched at startup)
        # Stored as base symbols (e.g., "BTC"), not product ids.
        self.baseline = {c.split("-USD")[0] for c in baseline_universe}
        self.entries: dict[str, WatchlistEntry] = {}

    def _coin_triggered(self, coin: str, st, now_ns: int) -> bool:
        """Apply each trigger condition; if any fires, return True."""
        # 1m / 5m / 30m return
        if st.return_over(now_ns, 60) >= TRIG_RET_1MIN:
            return True
        if st.return_over(now_ns, 300) >= TRIG_RET_5MIN:
            return True
        if st.return_over(now_ns, 1800) >= TRIG_RET_30MIN:
            return True
        # 24h: state's window may not extend that far back; treated as best-effort.
        # The trade_window_s default is 600s so a 24h return is unavailable from
        # streaming state alone — that's fine, the matches+ticker stream rolls
        # the state forward continuously and a coin that's been +10% on 24h will
        # almost always also satisfy one of the shorter-horizon triggers above.
        # Tape velocity — require minimum baseline so we don't fire on
        # freshly listed coins or low-volume coins where the baseline is
        # diluted by mostly-empty time.
        n_recent = st.trade_count_in(now_ns, 30)
        rate_recent = n_recent / 30.0
        rate_base = st.trade_count_in(now_ns, 300) / 300.0
        if (
            n_recent >= TRIG_RATE_MIN_RECENT
            and rate_base >= TRIG_RATE_MIN_BASELINE_PER_S
            and rate_recent / rate_base >= TRIG_RATE_30S_MULT
        ):
            return True
        return False

    def update(self, engine, now_ns: int) -> set[str]:
        """
        Recompute the watchlist. Returns the set of product IDs that
        should be currently subscribed (e.g. {"BTC-USD","ETH-USD",...}).
        Side effect: updates self.entries with the latest trigger times.
        """
        # 1. Check baseline coins for trigger to refresh their hangover (always-on
        #    means they don't need a trigger to stay subscribed).
        for coin in self.baseline:
            self.entries.setdefault(coin, WatchlistEntry(coin, now_ns))

        # 2. Check every active coin in the engine
        for coin, st in engine.coins.items():
            if not st.trades:
                continue
            try:
                fired = self._coin_triggered(coin, st, now_ns)
            except Exception:
                fired = False
            if fired:
                e = self.entries.get(coin)
                if e is None:
                    self.entries[coin] = WatchlistEntry(coin, now_ns)
                else:
                    e.last_trigger_ns = now_ns

        # 3. Build the active set: baseline always, plus any coin within hangover
        cutoff = now_ns - HANGOVER_S * NS
        active: set[str] = set()
        # baseline always-on
        for coin in self.baseline:
            active.add(f"{coin}-USD")
        # triggered + hangover — cap at MAX_DYNAMIC_L2 (most recently triggered first)
        candidates = [
            (e.last_trigger_ns, coin, e)
            for coin, e in self.entries.items()
            if coin not in self.baseline
        ]
        # sort descending by last_trigger_ns so we keep the most recently active
        candidates.sort(key=lambda x: x[0], reverse=True)

        expired = []
        dynamic_count = 0
        for trigger_ns, coin, e in candidates:
            if trigger_ns < cutoff:
                expired.append(coin)
            elif dynamic_count < MAX_DYNAMIC_L2:
                active.add(f"{coin}-USD")
                dynamic_count += 1
            # else: triggered but over cap — silently skip (will re-qualify next update)

        for coin in expired:
            del self.entries[coin]
        return active
