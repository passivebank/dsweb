"""
cb_recorder.py — async Coinbase Exchange WebSocket recorder + live shadow runner.

Connects to the public Exchange feed:
    wss://ws-feed.exchange.coinbase.com
Subscribes to:
    channels = [matches, ticker]
    product_ids = full Coinbase USD universe (fetched at startup)

For every incoming message:
  1. Stamp local recv_ts_ns immediately
  2. Normalize to a flat record:
        {ch:"trade",  prod, price, size, side, server_ts_ns, recv_ts_ns}
        {ch:"quote",  prod, bid,   ask,  bid_size, ask_size, server_ts_ns, recv_ts_ns}
  3. Append to RollingWriter (durable, gzipped, capped)
  4. Feed to DetectorEngine in-memory
  5. DetectorEngine signals are forwarded to ShadowSimulator

The recorder runs forever; SIGTERM / SIGINT triggers graceful close
(rotates active files, flushes shadow_trades.jsonl).

Periodic stats line every 30s:
  [stats] msgs/s=... lat_p50_ms=... lat_p99_ms=... open_pos=... shadow_signals=...

Health endpoint:
  Writes a one-line JSON heartbeat to artifacts/recorder_heartbeat.json
  every 5s. The watchdog reads this to confirm the process is alive.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
import traceback
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import websockets

# Make sibling packages importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from detector.engine import DetectorEngine
from detector.currently_ripping import SignalEvent
from recorder.storage import RollingWriter
from recorder.orderbook import BookTracker
from recorder.l2_watchlist import WatchlistManager
from shadow.simulator import ShadowSimulator

PHASE3_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = PHASE3_ROOT / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

# Storage paths — overridable for the EC2 deploy
ACTIVE_DIR = Path(os.environ.get("PHASE3_ACTIVE_DIR", "/tmp/phase3_active"))
DURABLE_DIR = Path(os.environ.get("PHASE3_DURABLE_DIR", str(PHASE3_ROOT / "data" / "durable")))
MAX_DURABLE_BYTES = int(os.environ.get("PHASE3_MAX_BYTES", str(1_500_000_000)))  # 1.5 GB

WS_URL = "wss://ws-feed.exchange.coinbase.com"
PRODUCTS_URL = "https://api.exchange.coinbase.com/products"
USER_AGENT = "phase3-intrabar-recorder/1.0"

# ── Market context URLs (all free, no API key) ──────────────────────
_FNG_URL       = "https://api.alternative.me/fng/?limit=1"
_COINGECKO_URL = "https://api.coingecko.com/api/v3/global"
_CONTEXT_INTERVAL_S = 60   # poll every 60 seconds

_COINGECKO_TRENDING_URL  = "https://api.coingecko.com/api/v3/search/trending"
# Binance spot — US stream first (works from AWS US), global as fallback
_BINANCE_STREAM_URLS     = [
    "wss://stream.binance.us:9443/ws/!miniTicker@arr",   # US — no geo-block
    "wss://stream.binance.com:9443/ws/!miniTicker@arr",  # Global — blocked on AWS US
]
_BINANCE_REST_TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr"  # REST fallback
_BINANCE_REST_FALLBACK_S = 3   # poll interval when WS unavailable
# OKX futures REST (accessible from AWS US — Binance/Bybit are geo-blocked)
# One call each for all funding rates and OI — no per-coin loops needed.
_OKX_FUNDING_URL = "https://www.okx.com/api/v5/public/funding-rate"   # per-symbol, but batched manually
_OKX_OI_URL      = "https://www.okx.com/api/v5/public/open-interest?instType=SWAP"   # all at once
_FUTURES_POLL_S  = 60
# Top Coinbase coins that have OKX perp markets (coin-USDT-SWAP or coin-USD-SWAP)
_FUTURES_TOP_COINS = [
    "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT",
    "LTC", "ATOM", "TRX", "NEAR", "APT", "SUI", "INJ", "HBAR", "AAVE",
    "PEPE", "OP", "ARB", "ICP", "FIL", "ETC", "BCH", "RUNE",
]


class MarketContextPoller:
    """Polls Fear & Greed + BTC dominance in a background async loop.

    Thread-safe reads via simple dict replacement (GIL sufficient for
    single-reader / single-writer in CPython).
    """

    def __init__(self) -> None:
        self._ctx: dict = {}
        self._stop = False

    @property
    def ctx(self) -> dict:
        return self._ctx

    async def run(self) -> None:
        while not self._stop:
            try:
                await self._refresh()
            except Exception as e:
                print(f"[mktctx] poll error: {e}", flush=True)
            await asyncio.sleep(_CONTEXT_INTERVAL_S)

    def stop(self) -> None:
        self._stop = True

    async def _refresh(self) -> None:
        loop = asyncio.get_event_loop()
        fng = await loop.run_in_executor(None, self._fetch_fng)
        dom = await loop.run_in_executor(None, self._fetch_btc_dom)
        trending = await loop.run_in_executor(None, self._fetch_trending)
        snap: dict = {}
        if fng is not None:
            snap["fear_greed"] = fng
        if dom is not None:
            snap["btc_dom_pct"] = round(dom, 2)
        if trending:
            snap["cg_trending"] = trending  # list of coin symbols
        if snap:
            self._ctx = snap

    @staticmethod
    def _fetch_fng() -> "int | None":
        try:
            req = urllib.request.Request(
                _FNG_URL, headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                d = json.loads(r.read())
            return int(d["data"][0]["value"])
        except Exception:
            return None

    @staticmethod
    def _fetch_btc_dom() -> "float | None":
        try:
            req = urllib.request.Request(
                _COINGECKO_URL, headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                d = json.loads(r.read())
            return float(d["data"]["market_cap_percentage"]["btc"])
        except Exception:
            return None

    @staticmethod
    def _fetch_trending() -> "list | None":
        try:
            req = urllib.request.Request(
                _COINGECKO_TRENDING_URL,
                headers={"User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                d = json.loads(r.read())
            return [c["item"]["symbol"].upper() for c in d.get("coins", [])]
        except Exception:
            return None

class BinanceWSPoller:
    """Real-time Binance spot prices, with REST fallback when WS is geo-blocked.

    On startup: probe each WS URL with a 10s timeout.
    If a URL responds: run it forever with auto-reconnect.
    If all URLs fail or are geo-blocked: fall back to REST every 3s.

    AWS US-East blocks stream.binance.com (HTTP 451).
    stream.binance.us may also be unreachable from some AWS regions.
    REST api.binance.com is always reachable and is used as the fallback.
    """

    def __init__(self) -> None:
        self._prices:  dict[str, float] = {}
        self._ret_24h: dict[str, float] = {}
        self._connected = False
        self._stop = False

    @property
    def prices(self) -> dict[str, float]:
        return self._prices

    @property
    def ret_24h(self) -> dict[str, float]:
        return self._ret_24h

    @property
    def connected(self) -> bool:
        return self._connected

    async def run(self) -> None:
        # Probe each WS URL; use the first that responds within 10s.
        working_url: str | None = None
        for url in _BINANCE_STREAM_URLS:
            if self._stop:
                return
            try:
                ws = await asyncio.wait_for(
                    websockets.connect(url, open_timeout=10, max_size=2 ** 23),
                    timeout=12,
                )
                await ws.close()
                working_url = url
                print(f"[binance-ws] probe OK: {url}", flush=True)
                break
            except Exception as e:
                print(f"[binance-ws] probe failed {url}: {e}", flush=True)

        if working_url is None:
            print("[binance-ws] no WS reachable — REST poll every 3s", flush=True)
            await self._rest_loop()
            return

        # Run WS forever with auto-reconnect
        while not self._stop:
            try:
                async with websockets.connect(
                    working_url, ping_interval=20, ping_timeout=30, max_size=2 ** 23,
                ) as ws:
                    self._connected = True
                    print(f"[binance-ws] streaming: {working_url}", flush=True)
                    async for raw in ws:
                        if self._stop:
                            return
                        self._parse_frame(raw)
                    self._connected = False
            except Exception as e:
                self._connected = False
                print(f"[binance-ws] dropped: {e}; reconnecting in 5s", flush=True)
                await asyncio.sleep(5)

    def _parse_frame(self, raw: str) -> None:
        try:
            data = json.loads(raw)
            if not isinstance(data, list):
                return
            prices: dict[str, float] = {}
            rets:   dict[str, float] = {}
            for item in data:
                sym = item.get("s", "")
                if (not sym.endswith("USDT")
                        or sym.endswith("DOWNUSDT")
                        or sym.endswith("UPUSDT")):
                    continue
                coin = sym[:-4]
                try:
                    c = float(item["c"])
                    o = float(item["o"])
                    prices[coin] = c
                    if o > 0:
                        rets[coin] = (c / o) - 1.0
                except Exception:
                    pass
            if prices:
                self._prices = prices
            if rets:
                self._ret_24h = rets
        except Exception:
            pass

    async def _rest_loop(self) -> None:
        loop = asyncio.get_event_loop()
        while not self._stop:
            try:
                await loop.run_in_executor(None, self._refresh_rest)
            except Exception as e:
                print(f"[binance-rest] error: {e}", flush=True)
            await asyncio.sleep(_BINANCE_REST_FALLBACK_S)

    def _refresh_rest(self) -> None:
        try:
            req = urllib.request.Request(
                _BINANCE_REST_TICKER_URL, headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            prices: dict[str, float] = {}
            rets:   dict[str, float] = {}
            for item in data:
                sym = item.get("symbol", "")
                if (not sym.endswith("USDT")
                        or sym.endswith("DOWNUSDT")
                        or sym.endswith("UPUSDT")):
                    continue
                coin = sym[:-4]
                try:
                    prices[coin] = float(item["lastPrice"])
                    o = float(item["openPrice"])
                    if o > 0:
                        rets[coin] = (prices[coin] / o) - 1.0
                except Exception:
                    pass
            if prices:
                self._prices = prices
            if rets:
                self._ret_24h = rets
        except Exception:
            pass

    def stop(self) -> None:
        self._stop = True


class OKXFuturesPoller:
    """Polls OKX perpetual futures for funding rates and open interest.

    OKX is accessible from AWS US-East (Binance/Bybit are geo-blocked).

    Two REST calls per cycle:
      1. /public/open-interest?instType=SWAP — ALL 309 perp OI in one shot
      2. /public/funding-rate?instId=<coin>-USDT-SWAP — per top-coin list

    Signals stamped on each trade:
      bn_funding_rate  — negative = shorts paying longs = squeeze fuel
      bn_oi_delta_60s  — OI change over 60s: positive = new longs (sustainable),
                         negative = short squeeze only (fades faster)
    """

    def __init__(self) -> None:
        self._funding: dict[str, float] = {}    # coin -> current funding rate
        self._oi: dict[str, deque] = {}         # coin -> deque[(ts_ns, oi_usd)]
        self._stop = False

    @property
    def funding(self) -> dict[str, float]:
        return self._funding

    def oi_delta_60s(self, coin: str, now_ns: int) -> "float | None":
        """Fraction change in OI over last 60s.  Positive = new longs entering."""
        q = self._oi.get(coin)
        if not q or len(q) < 2:
            return None
        cutoff = now_ns - 60 * NS
        oldest = None
        for ts, oi in q:
            if ts >= cutoff:
                oldest = oi
                break
        if oldest is None or oldest <= 0:
            return None
        return (q[-1][1] - oldest) / oldest

    async def run(self) -> None:
        while not self._stop:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._refresh_all)
            except Exception as e:
                print(f"[okx-futures] error: {e}", flush=True)
            await asyncio.sleep(_FUTURES_POLL_S)

    def stop(self) -> None:
        self._stop = True

    def _refresh_all(self) -> None:
        now_ns = time.time_ns()
        # Step 1: ALL OI in one call
        try:
            req = urllib.request.Request(_OKX_OI_URL, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            for item in data.get("data", []):
                inst = item.get("instId", "")
                # Accept both coin-USDT-SWAP and coin-USD-SWAP
                if not inst.endswith("-SWAP"):
                    continue
                parts = inst.split("-")
                if len(parts) < 3:
                    continue
                coin = parts[0]
                try:
                    oi_usd = float(item.get("oiUsd") or item.get("oi") or 0)
                    if oi_usd > 0:
                        if coin not in self._oi:
                            self._oi[coin] = deque(maxlen=30)
                        self._oi[coin].append((now_ns, oi_usd))
                except Exception:
                    pass
        except Exception as e:
            print(f"[okx-futures] OI fetch error: {e}", flush=True)

        # Step 2: funding rates for top coins (individual calls, fast)
        funding: dict[str, float] = {}
        for coin in _FUTURES_TOP_COINS:
            for suffix in (f"{coin}-USDT-SWAP", f"{coin}-USD-SWAP"):
                try:
                    url = f"{_OKX_FUNDING_URL}?instId={suffix}"
                    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                    with urllib.request.urlopen(req, timeout=5) as r:
                        d = json.loads(r.read())
                    items = d.get("data") or []
                    if items:
                        rate = float(items[0].get("fundingRate", 0))
                        funding[coin] = rate
                        break   # found it, skip second suffix
                except Exception:
                    pass
                time.sleep(0.02)
        if funding:
            self._funding = funding
            print(f"[okx-futures] funding updated: {len(funding)} coins", flush=True)


STABLECOINS = {
    "USDT", "USDC", "DAI", "PYUSD", "USDP", "GUSD", "TUSD", "BUSD", "USDS",
    "EURC", "RLUSD", "USDG", "FDUSD", "WBTC", "CBETH",
}


def fetch_usd_universe() -> list[str]:
    req = urllib.request.Request(PRODUCTS_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as r:
        rows = json.loads(r.read())
    out = []
    for row in rows:
        if row.get("quote_currency") != "USD":
            continue
        if row.get("trading_disabled") or row.get("status") != "online":
            continue
        base = row.get("base_currency")
        if not base or base in STABLECOINS:
            continue
        out.append(f"{base}-USD")
    return sorted(out)


def fetch_baseline_universe(top_n: int = 30) -> list[str]:
    """Top-N USD products by 24h dollar volume — always-on L2 baseline.

    Uses /products/{id}/stats for each candidate. Slow but only runs at
    startup; results are cached for the recorder's lifetime.
    """
    universe = fetch_usd_universe()
    stats_url_t = "https://api.exchange.coinbase.com/products/{}/stats"
    rows = []
    for prod in universe:
        try:
            req = urllib.request.Request(stats_url_t.format(prod), headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.loads(r.read())
            vol = float(d.get("volume") or 0)
            last = float(d.get("last") or 0)
            rows.append((prod, vol * last))
        except Exception:
            continue
        time.sleep(0.05)  # ~20 req/s, well under public limit
    rows.sort(key=lambda x: x[1], reverse=True)
    return [r[0] for r in rows[:top_n]]


def parse_iso_to_ns(s: str) -> int:
    """Parse Coinbase ISO timestamp like '2026-04-11T19:30:00.123456Z' to ns."""
    if not s:
        return 0
    s = s.replace("Z", "+00:00")
    try:
        # avoid datetime overhead — use a fast manual parser
        # 2026-04-11T19:30:00.123456+00:00
        date, t = s.split("T")
        y, m, d = date.split("-")
        time_part = t.split("+")[0].split("-")[0]
        if "." in time_part:
            hms, frac = time_part.split(".")
            frac = (frac + "000000000")[:9]
        else:
            hms, frac = time_part, "000000000"
        hh, mm, ss = hms.split(":")
        import calendar
        secs = calendar.timegm((int(y), int(m), int(d), int(hh), int(mm), int(ss), 0, 0, 0))
        return secs * 1_000_000_000 + int(frac)
    except Exception:
        return 0


class Recorder:
    def __init__(self, products: list[str], shadow_log: Path,
                 baseline_l2: list[str] | None = None,
                 active_dir: Path = ACTIVE_DIR,
                 durable_dir: Path = DURABLE_DIR,
                 max_bytes: int = MAX_DURABLE_BYTES) -> None:
        self.products = products
        self.engine = DetectorEngine(on_signal=self._on_signal)
        self.shadow = ShadowSimulator(log_path=shadow_log, engine=self.engine)
        self.writer = RollingWriter(
            active_dir=active_dir,
            durable_dir=durable_dir,
            prefix="events",
            max_bytes=max_bytes,
        )
        self.signal_log = ARTIFACTS / "shadow_signals.jsonl"
        self.heartbeat_path = ARTIFACTS / "recorder_heartbeat.json"
        self.stats = {
            "started_at_ns": time.time_ns(),
            "msgs_total": 0,
            "msgs_window": 0,
            "trades_total": 0,
            "quotes_total": 0,
            "books_emitted": 0,
            "errors": 0,
            "last_msg_ts_ns": 0,
        }
        self._lat_window: deque[int] = deque(maxlen=2000)
        self._stop = False
        self._mkt = MarketContextPoller()
        self._binance = BinanceWSPoller()
        self._bn_futures = OKXFuturesPoller()
        self._ret_24h: dict[str, float] = {}   # coin → (mid/open_24h) - 1

        # L2 plumbing
        self.book_tracker = BookTracker()
        self.watchlist = WatchlistManager(set(baseline_l2 or []))
        self._l2_subscribed: set[str] = set()
        self._ws = None  # set inside _ws_loop so the sub manager can send mid-stream

    def _on_signal(self, sig: SignalEvent) -> None:
        coin = sig.coin
        now_ns = sig.sig_ts_ns

        # ── macro context (60s-refresh poller) ─────────────────────
        ctx = self._mkt.ctx
        if ctx:
            sig.features.update(ctx)

        # ── BTC 1h return (engine state — zero extra I/O) ───────────
        btc_st = self.engine.coins.get("BTC")
        if btc_st is not None:
            try:
                sig.features["btc_ret_1h"] = round(btc_st.return_over(now_ns, 3600), 5)
            except Exception:
                pass

        # ── CVD: cumulative volume delta (buy_usd - sell_usd) ───────
        st = self.engine.coins.get(coin)
        if st is not None:
            sig.features["cvd_30s"] = round(st.cvd_in(now_ns, 30), 2)
            sig.features["cvd_60s"] = round(st.cvd_in(now_ns, 60), 2)

        # ── Order book imbalance: bid_depth_10 / ask_depth_10 ───────
        # Only available if this coin is on the L2 watchlist.
        bim = self.book_tracker.book_imbalance(coin)
        if bim is not None:
            sig.features["book_imbalance_10"] = bim

        # ── 24h return (from ticker open_24h) ───────────────────────
        ret24 = self._ret_24h.get(coin)
        if ret24 is not None:
            sig.features["ret_24h"] = round(ret24, 5)

        # ── Time of day (UTC hour) ───────────────────────────────────
        sig.features["utc_hour"] = datetime.now(timezone.utc).hour

        # ── Prior signal history for this coin ──────────────────────
        # Counts signals already recorded (including this one — engine
        # called _record_signal_history before the callback).
        sig.features["signals_24h"] = self.engine.signal_count_for(coin, now_ns, 86400)
        sig.features["signals_1h"]  = self.engine.signal_count_for(coin, now_ns, 3600)

        # ── Binance cross-exchange premium (now real-time, not 10s lag) ─
        binance_px = self._binance.prices.get(coin)
        if binance_px and binance_px > 0 and sig.sig_mid > 0:
            sig.features["cb_binance_premium"] = round((sig.sig_mid / binance_px) - 1.0, 5)

        # ── Binance 24h return (confirms move is cross-exchange, not CB only) ─
        bn_ret = self._binance.ret_24h.get(coin)
        if bn_ret is not None:
            sig.features["bn_ret_24h"] = round(bn_ret, 5)

        # ── Funding rate: negative = shorts paying longs = squeeze fuel ──
        funding = self._bn_futures.funding.get(coin)
        if funding is not None:
            sig.features["bn_funding_rate"] = round(funding, 6)

        # ── OI delta 60s: positive = new longs (sustainable), negative = shorts covering (fades) ──
        oi_delta = self._bn_futures.oi_delta_60s(coin, now_ns)
        if oi_delta is not None:
            sig.features["bn_oi_delta_60s"] = round(oi_delta, 5)

        # ── CoinGecko trending ───────────────────────────────────────
        cg_trending = self._mkt.ctx.get("cg_trending")
        if cg_trending is not None:
            sig.features["cg_trending"] = coin.upper() in cg_trending

        # ── Ask depth and bid depth at signal time ───────────────────
        ask_d = self.book_tracker.total_ask_depth_usd(coin)
        bid_d = self.book_tracker.total_bid_depth_usd(coin)
        if ask_d > 0:
            sig.features["ask_depth_usd"] = round(ask_d, 2)
        if bid_d > 0:
            sig.features["bid_depth_usd"] = round(bid_d, 2)

        # ── Persist the signal ──────────────────────────────────────
        with self.signal_log.open("a") as f:
            f.write(json.dumps({
                "variant":   sig.variant,
                "coin":      sig.coin,
                "sig_ts_ns": sig.sig_ts_ns,
                "sig_mid":   sig.sig_mid,
                "features":  sig.features,
            }) + "\n")

        # ── Hand off to shadow simulator ────────────────────────────
        self.shadow.on_signal(sig)

    async def _heartbeat_loop(self) -> None:
        while not self._stop:
            try:
                stats = dict(self.stats)
                stats["uptime_s"] = (time.time_ns() - stats["started_at_ns"]) / 1e9
                stats["n_open_positions"] = len(self.shadow.open)
                stats["n_pending_entries"] = len(self.shadow.pending)
                stats["n_signals_seen"] = self.shadow.n_signals_seen
                stats["n_shadow_trades_closed"] = self.shadow.n_trades_closed
                stats["last_event_age_s"] = (time.time_ns() - stats["last_msg_ts_ns"]) / 1e9 if stats["last_msg_ts_ns"] else None
                stats["l2_subscribed_n"] = len(self._l2_subscribed)
                stats["l2_books_tracked"] = len(self.book_tracker.books)
                self.heartbeat_path.write_text(json.dumps(stats, indent=2))
            except Exception:
                pass
            await asyncio.sleep(5)

    async def _stats_loop(self) -> None:
        while not self._stop:
            await asyncio.sleep(30)
            n = self.stats["msgs_window"]
            self.stats["msgs_window"] = 0
            lats = sorted(self._lat_window)
            if lats:
                p50 = lats[len(lats) // 2] / 1e6
                p99 = lats[max(0, int(len(lats) * 0.99) - 1)] / 1e6
            else:
                p50 = p99 = 0.0
            print(f"[stats] msgs/s={n / 30.0:.0f}  lat_p50_ms={p50:.1f}  lat_p99_ms={p99:.1f}  "
                  f"open_pos={len(self.shadow.open)}  pending={len(self.shadow.pending)}  "
                  f"signals={self.shadow.n_signals_seen}  closed={self.shadow.n_trades_closed}",
                  flush=True)

    async def _ws_loop(self) -> None:
        while not self._stop:
            try:
                async with websockets.connect(
                    WS_URL,
                    ping_interval=15,
                    ping_timeout=20,
                    max_size=2**22,
                    user_agent_header=USER_AGENT,
                ) as ws:
                    self._ws = ws
                    sub = {
                        "type": "subscribe",
                        "product_ids": self.products,
                        "channels": ["matches", "ticker"],
                    }
                    await ws.send(json.dumps(sub))
                    print(f"[ws] subscribed: {len(self.products)} products, channels=matches+ticker", flush=True)
                    # If we already have a baseline L2 set, subscribe to it immediately
                    if self.watchlist.baseline:
                        baseline_pids = sorted({f"{c}-USD" for c in self.watchlist.baseline})
                        await self._send_l2_subscribe(baseline_pids)
                    async for raw in ws:
                        if self._stop:
                            break
                        recv_ns = time.time_ns()
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            self.stats["errors"] += 1
                            continue
                        await self._handle_msg(msg, recv_ns)
                    self._ws = None
            except Exception as e:
                self._ws = None
                self.stats["errors"] += 1
                print(f"[ws] connection error: {e}; reconnecting in 3s", flush=True)
                await asyncio.sleep(3)

    async def _send_l2_subscribe(self, product_ids: list[str]) -> None:
        if not product_ids or self._ws is None:
            return
        msg = {
            "type": "subscribe",
            "channels": [{"name": "level2_batch", "product_ids": product_ids}],
        }
        try:
            await self._ws.send(json.dumps(msg))
            self._l2_subscribed.update(product_ids)
            print(f"[l2] +sub {len(product_ids)}: {','.join(product_ids[:5])}{'…' if len(product_ids) > 5 else ''}", flush=True)
        except Exception as e:
            print(f"[l2] subscribe error: {e}", flush=True)

    async def _send_l2_unsubscribe(self, product_ids: list[str]) -> None:
        if not product_ids or self._ws is None:
            return
        msg = {
            "type": "unsubscribe",
            "channels": [{"name": "level2_batch", "product_ids": product_ids}],
        }
        try:
            await self._ws.send(json.dumps(msg))
            for p in product_ids:
                self._l2_subscribed.discard(p)
                self.book_tracker.drop(p.split("-USD")[0])
            print(f"[l2] -unsub {len(product_ids)}: {','.join(product_ids[:5])}{'…' if len(product_ids) > 5 else ''}", flush=True)
        except Exception as e:
            print(f"[l2] unsubscribe error: {e}", flush=True)

    async def _subscription_manager_loop(self) -> None:
        """Every 5s, recompute the L2 watchlist and send sub/unsub diffs."""
        await asyncio.sleep(10)  # let the engine accumulate some state first
        while not self._stop:
            try:
                if self._ws is not None:
                    desired = self.watchlist.update(self.engine, time.time_ns())
                    to_add = sorted(desired - self._l2_subscribed)
                    to_remove = sorted(self._l2_subscribed - desired)
                    if to_add:
                        await self._send_l2_subscribe(to_add)
                    if to_remove:
                        await self._send_l2_unsubscribe(to_remove)
            except Exception as e:
                print(f"[l2] manager error: {e}", flush=True)
            await asyncio.sleep(5)

    async def _handle_msg(self, msg: dict, recv_ns: int) -> None:
        t = msg.get("type")
        if t == "match" or t == "last_match":
            prod = msg.get("product_id") or ""
            price = msg.get("price")
            size = msg.get("size")
            side = msg.get("side")  # 'buy' or 'sell' = taker side
            server_ts_ns = parse_iso_to_ns(msg.get("time") or "")
            if not (price and size and prod):
                return
            try:
                price_f = float(price)
                size_f = float(size)
            except Exception:
                return
            rec = {
                "ch": "trade", "prod": prod, "price": price_f, "size": size_f,
                "side": side, "server_ts_ns": server_ts_ns, "recv_ts_ns": recv_ns,
            }
            self.writer.write(rec)
            self.engine.on_event({"ch": "trade", "coin": prod, "price": price_f, "size": size_f,
                                  "side": side, "recv_ts_ns": recv_ns})
            self.shadow.on_event({"ch": "trade", "coin": prod, "price": price_f,
                                  "recv_ts_ns": recv_ns})
            self.stats["trades_total"] += 1
        elif t == "ticker":
            prod = msg.get("product_id") or ""
            bid = msg.get("best_bid")
            ask = msg.get("best_ask")
            bid_size = msg.get("best_bid_size")
            ask_size = msg.get("best_ask_size")
            server_ts_ns = parse_iso_to_ns(msg.get("time") or "")
            if not (bid and ask and prod):
                return
            try:
                bid_f = float(bid)
                ask_f = float(ask)
            except Exception:
                return
            # Capture 24h open from ticker — feed both local cache and engine
            open_24h = msg.get("open_24h")
            if open_24h:
                try:
                    open_f = float(open_24h)
                    if open_f > 0:
                        coin_key = prod.split("-USD")[0]
                        ret = ((bid_f + ask_f) / 2.0) / open_f - 1.0
                        self._ret_24h[coin_key] = ret
                        self.engine.update_ret_24h(coin_key, ret)
                except Exception:
                    pass
            rec = {
                "ch": "quote", "prod": prod, "bid": bid_f, "ask": ask_f,
                "bid_size": float(bid_size or 0), "ask_size": float(ask_size or 0),
                "server_ts_ns": server_ts_ns, "recv_ts_ns": recv_ns,
            }
            self.writer.write(rec)
            self.engine.on_event({"ch": "quote", "coin": prod, "bid": bid_f, "ask": ask_f,
                                  "recv_ts_ns": recv_ns})
            self.stats["quotes_total"] += 1
        elif t == "snapshot":
            prod = msg.get("product_id") or ""
            if not prod:
                return
            base = prod.split("-USD")[0]
            top = self.book_tracker.on_snapshot(base, msg.get("bids") or [], msg.get("asks") or [], recv_ns)
            if top is not None:
                self.writer.write(top)
                self.stats["books_emitted"] += 1
            rec = None  # snapshot itself isn't a single record we'd track in latency
        elif t == "l2update":
            prod = msg.get("product_id") or ""
            if not prod:
                return
            base = prod.split("-USD")[0]
            server_ts_ns = parse_iso_to_ns(msg.get("time") or "")
            top = self.book_tracker.on_update(base, msg.get("changes") or [], recv_ns)
            if top is not None:
                top["server_ts_ns"] = server_ts_ns
                self.writer.write(top)
                self.stats["books_emitted"] += 1
            # Feed ask depth to engine for trend tracking
            ask_depth = self.book_tracker.total_ask_depth_usd(base)
            if ask_depth > 0:
                self.engine.update_ask_depth(base, ask_depth, recv_ns)
            rec = {"ch": "book10", "server_ts_ns": server_ts_ns} if server_ts_ns else None
        elif t in ("subscriptions", "heartbeat"):
            return
        else:
            return

        self.stats["msgs_total"] += 1
        self.stats["msgs_window"] += 1
        self.stats["last_msg_ts_ns"] = recv_ns
        if rec and rec.get("server_ts_ns"):
            lat = recv_ns - rec["server_ts_ns"]
            if 0 < lat < 60_000_000_000:  # filter clock skew outliers
                self._lat_window.append(lat)

    def stop(self) -> None:
        self._stop = True
        self._mkt.stop()
        self._binance.stop()
        self._bn_futures.stop()

    async def run(self) -> None:
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.stop)
        try:
            await asyncio.gather(
                self._ws_loop(),
                self._stats_loop(),
                self._heartbeat_loop(),
                self._subscription_manager_loop(),
                self._mkt.run(),
                self._binance.run(),
                self._bn_futures.run(),
            )
        finally:
            print("[recorder] shutting down", flush=True)
            self.writer.close()


async def main() -> None:
    universe = fetch_usd_universe()
    print(f"[recorder] USD universe: {len(universe)} products", flush=True)
    print("[recorder] fetching baseline L2 universe (top 30 by 24h $ volume)…", flush=True)
    try:
        baseline = fetch_baseline_universe(top_n=30)
    except Exception as e:
        print(f"[recorder] baseline fetch failed: {e} — proceeding with no baseline L2", flush=True)
        baseline = []
    print(f"[recorder] baseline L2: {baseline}", flush=True)
    shadow_log = ARTIFACTS / "shadow_trades.jsonl"
    rec = Recorder(products=universe, baseline_l2=baseline, shadow_log=shadow_log)
    await rec.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        traceback.print_exc()
        sys.exit(1)
