"""
orderbook.py — in-memory L2 book tracker for the recorder.

Maintains a per-coin order book from Coinbase `level2_batch` snapshots
and incremental updates, then emits TOP-10 snapshots to the durable
event stream at most once per second per coin (plus an immediate emit
when the top-of-book *price* changes, gated to ≥100ms spacing).

We do not log every l2update — that would be 5-15 GB/day on the
watchlist alone. We log a top-10 image at ~1 Hz which is sufficient
resolution to model "the book moved N levels in 250-1000 ms while my
order was in flight."

Book-level cap (MAX_BOOK_LEVELS):
  Each side is capped at MAX_BOOK_LEVELS active price levels.
  Without a cap, bids/asks grow unboundedly as new price levels are seen
  over hours of trading.  max()/min()/sorted() calls are O(n) or O(n log n),
  so a 1800-level book after 1.5h is ~36× slower than a fresh book —
  causing monotonically increasing event-loop latency and eventual crash.
  Capping at 50 keeps all operations O(1) while retaining enough depth
  for accurate top-10 calculations.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

NS = 1_000_000_000

# Emission gating
MIN_SPACING_NS = 100_000_000          # 100 ms minimum between emissions per coin
PERIODIC_INTERVAL_NS = 1_000_000_000  # 1 s baseline emission cadence

# Book depth cap — keeps sorted()/max()/min() calls O(1) over long runs.
# We only ever read top-10, so 50 per side is more than sufficient.
MAX_BOOK_LEVELS = 50
TRIM_THRESHOLD  = 100  # prune when either side exceeds this; amortises sort cost


@dataclass
class BookState:
    bids: dict = field(default_factory=dict)   # price -> size
    asks: dict = field(default_factory=dict)
    last_emit_ns: int = 0
    last_top_bid: float = 0.0
    last_top_ask: float = 0.0


class BookTracker:
    def __init__(self) -> None:
        self.books: dict[str, BookState] = {}

    def has(self, coin: str) -> bool:
        return coin in self.books

    def reset(self, coin: str) -> None:
        self.books[coin] = BookState()

    def on_snapshot(self, coin: str, bids, asks, recv_ts_ns: int) -> dict | None:
        """Initialize a coin's book from a `snapshot` message."""
        st = BookState()
        for price_s, size_s in bids:
            try:
                p = float(price_s)
                s = float(size_s)
            except Exception:
                continue
            if s > 0:
                st.bids[p] = s
        for price_s, size_s in asks:
            try:
                p = float(price_s)
                s = float(size_s)
            except Exception:
                continue
            if s > 0:
                st.asks[p] = s
        # Trim immediately — snapshots can arrive with hundreds of levels.
        if len(st.bids) > MAX_BOOK_LEVELS:
            keep = sorted(st.bids.keys(), reverse=True)[:MAX_BOOK_LEVELS]
            st.bids = {p: st.bids[p] for p in keep}
        if len(st.asks) > MAX_BOOK_LEVELS:
            keep = sorted(st.asks.keys())[:MAX_BOOK_LEVELS]
            st.asks = {p: st.asks[p] for p in keep}
        self.books[coin] = st
        return self._maybe_emit(coin, recv_ts_ns, force=True)

    def on_update(self, coin: str, changes, recv_ts_ns: int) -> dict | None:
        """Apply an `l2update` to an existing book; return a top-10 emit if due."""
        st = self.books.get(coin)
        if st is None:
            # received update before snapshot — wait for snapshot
            return None
        for change in changes:
            try:
                side, price_s, size_s = change[0], change[1], change[2]
                price = float(price_s)
                size = float(size_s)
            except Exception:
                continue
            d = st.bids if side == "buy" else st.asks
            if size == 0:
                d.pop(price, None)
            else:
                d[price] = size
        # Batch-prune when either side exceeds TRIM_THRESHOLD.
        # Amortised cost: O(log n) per update; keeps max()/min()/sorted()
        # calls bounded to O(MAX_BOOK_LEVELS) for the lifetime of the run.
        if len(st.bids) > TRIM_THRESHOLD:
            keep = sorted(st.bids.keys(), reverse=True)[:MAX_BOOK_LEVELS]
            st.bids = {p: st.bids[p] for p in keep}
        if len(st.asks) > TRIM_THRESHOLD:
            keep = sorted(st.asks.keys())[:MAX_BOOK_LEVELS]
            st.asks = {p: st.asks[p] for p in keep}
        return self._maybe_emit(coin, recv_ts_ns)

    def _maybe_emit(self, coin: str, ts_ns: int, force: bool = False) -> dict | None:
        st = self.books.get(coin)
        if st is None or not st.bids or not st.asks:
            return None
        # Cheap top-of-book check before doing the full sort
        top_bid = max(st.bids)
        top_ask = min(st.asks)
        if top_ask <= top_bid:
            return None
        elapsed = ts_ns - st.last_emit_ns
        top_changed = (top_bid != st.last_top_bid) or (top_ask != st.last_top_ask)
        if not force:
            if elapsed < MIN_SPACING_NS:
                return None
            if elapsed < PERIODIC_INTERVAL_NS and not top_changed:
                return None
        # OK, emit top-10
        bids_sorted = sorted(st.bids.items(), key=lambda x: -x[0])[:10]
        asks_sorted = sorted(st.asks.items(), key=lambda x: x[0])[:10]
        st.last_emit_ns = ts_ns
        st.last_top_bid = top_bid
        st.last_top_ask = top_ask
        return {
            "ch": "book10",
            "prod": f"{coin}-USD" if "-USD" not in coin else coin,
            "bids": [[round(p, 12), round(s, 12)] for p, s in bids_sorted],
            "asks": [[round(p, 12), round(s, 12)] for p, s in asks_sorted],
            "recv_ts_ns": ts_ns,
        }

    def book_imbalance(self, coin: str, top_n: int = 10) -> "float | None":
        """Bid depth / ask depth for top_n price levels (dollar-weighted).

        > 1.0 = buy-side pressure (more $ defending bids than asks).
        < 1.0 = sell-side pressure.
        Returns None if the coin has no L2 book yet.

        Dollar-weighting (price × size) makes the ratio comparable across
        coins at very different price levels.
        """
        st = self.books.get(coin)
        if st is None or not st.bids or not st.asks:
            return None
        bids_top = sorted(st.bids.items(), key=lambda x: -x[0])[:top_n]
        asks_top = sorted(st.asks.items(), key=lambda x: x[0])[:top_n]
        bid_depth = sum(p * s for p, s in bids_top)
        ask_depth = sum(p * s for p, s in asks_top)
        if ask_depth <= 0:
            return None
        return round(bid_depth / ask_depth, 3)

    def total_ask_depth_usd(self, coin: str, top_n: int = 10) -> float:
        """Total dollar value of ask-side top_n price levels."""
        st = self.books.get(coin)
        if st is None or not st.asks:
            return 0.0
        asks_top = sorted(st.asks.items(), key=lambda x: x[0])[:top_n]
        return sum(p * s for p, s in asks_top)

    def total_bid_depth_usd(self, coin: str, top_n: int = 10) -> float:
        """Total dollar value of bid-side top_n price levels."""
        st = self.books.get(coin)
        if st is None or not st.bids:
            return 0.0
        bids_top = sorted(st.bids.items(), key=lambda x: -x[0])[:top_n]
        return sum(p * s for p, s in bids_top)

    def drop(self, coin: str) -> None:
        self.books.pop(coin, None)
