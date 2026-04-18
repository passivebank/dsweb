"""
live_executor.py — R5_CONFIRMED_RUN live trade executor.

Non-blocking: all REST calls run in a background daemon thread via a queue.
on_signal() and on_price() return instantly — never block the asyncio loop.
"""
import json
import math
import os
import sys
import time
import uuid
import queue
import logging
import threading
from collections import defaultdict
from datetime import datetime, timezone as _tz
from pathlib import Path
from typing import Optional

log = logging.getLogger("LiveExecutor")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[live-exec] %(message)s"))
    log.addHandler(_h)
    log.propagate = False

# ── v10 exit parameters ──────────────────────────────────────────────
PARTIAL_TRIGGER = 0.20    # sell 50% when gain hits +20%
TRAIL_PRE       = 0.07    # trail before partial
TRAIL_POST      = 0.15    # trail after partial
SLIP            = 0.0003  # used only for legacy-record qty estimation (reconciler fallback)
MIN_ORDER_USD   = 10.0    # sub-$10 positions have negligible dollar P&L
MAX_HOLD_S      = 14400   # 4h hard cap

# ── v10 entry filter gates ───────────────────────────────────────────
GATE_ONSET_S     = 15.0   # skip if 15+ seconds since the move started (late entry)
GATE_CVD_30S_MIN = -2000  # skip if net selling > $2000 in last 30s (18% WR vs 46%)

# ── EV-based signal quality scoring ──────────────────────────────────
# Adj-EV baselines by tier from 74-day v10 backtest. Used as the anchor
# for per-signal scoring: signals that score above baseline get full tier
# sizing; signals that score below get scaled down (floor 0.5×); signals
# below MIN_EV_PCT are skipped entirely.
#
# Coefficients (cvd/timing/dvt/spread/ltrade) are calibrated from live
# data — recalibrate at day 30 (2026-05-15).
TIER_EV_BASELINE = {"A": 7.5, "B": 4.3, "C": 4.2, "D": 3.2}
MIN_EV_PCT       = 1.5    # skip signal if estimated EV < 1.5%

# Per-coin cooldown after exit: prevents re-entry on a coin that just reversed.
# Keyed on exit classification; elapsed time must exceed cooldown before re-entry.
COOLDOWN_S = {
    "TRAIL_STOP_FULL":    90 * 60,  # stopped out without partial — full reversal
    "TRAIL_STOP_PARTIAL": 20 * 60,  # had partial, overall profitable — short cooldown
    "TIME_CAP_LOSS":      60 * 60,  # timed out underwater — slow bleed coin
    "TIME_CAP_GAIN":      20 * 60,  # timed out profitable — allow fresh re-entry soon
}

CB_ENV_FILE = Path("/home/ec2-user/nkn_bot/.env")


def _make_client():
    from dotenv import load_dotenv
    load_dotenv(CB_ENV_FILE)
    from coinbase.rest import RESTClient
    return RESTClient(
        api_key=os.getenv("CB_API_KEY"),
        api_secret=os.getenv("CB_API_SECRET"),
        rate_limit_headers=True,
    )


def _get_usd_balance(client) -> float:
    """Paginated USD balance fetch."""
    cursor = None
    while True:
        kw = {"limit": 250}
        if cursor:
            kw["cursor"] = cursor
        resp = client.get_accounts(**kw)
        for acc in resp.accounts:
            try:
                ab  = acc.available_balance
                bal = float(ab["value"]) if isinstance(ab, dict) else float(ab.value)
                cur = acc.currency if hasattr(acc, "currency") else ""
                if cur == "USD":
                    return bal
            except Exception:
                pass
        has_next = getattr(resp, "has_next", False)
        cursor   = getattr(resp, "cursor", None)
        if not has_next or not cursor:
            break
    return 0.0


def _get_all_coin_balances(client) -> dict:
    """Return all non-zero, non-USD balances held on Coinbase.

    Returns:
        dict mapping coin symbol → available qty (float)
    """
    balances = {}
    cursor = None
    while True:
        kw = {"limit": 250}
        if cursor:
            kw["cursor"] = cursor
        resp = client.get_accounts(**kw)
        for acc in resp.accounts:
            try:
                cur = acc.currency if hasattr(acc, "currency") else ""
                if not cur or cur == "USD":
                    continue
                ab  = acc.available_balance
                qty = float(ab["value"] if isinstance(ab, dict) else ab.value)
                if qty > 0:
                    balances[cur] = qty
            except Exception:
                pass
        has_next = getattr(resp, "has_next", False)
        cursor   = getattr(resp, "cursor", None)
        if not has_next or not cursor:
            break
    return balances


def _market_buy(client, coin: str, usd_amount: float) -> Optional[str]:
    cid = str(uuid.uuid4())
    try:
        resp = client.create_order(
            client_order_id=cid,
            product_id=f"{coin}-USD",
            side="BUY",
            order_configuration={"market_market_ioc": {"quote_size": f"{usd_amount:.2f}"}},
        )
        if resp.success:
            oid = resp.success_response["order_id"]
            log.info(f"[BUY]  {coin}  usd={usd_amount:.2f}  oid={oid}")
            return oid
        log.error(f"[BUY REJECT] {coin}: {resp.error_response}")
    except Exception as e:
        log.error(f"[BUY ERR] {coin}: {e}")
    return None


def _get_coin_balance(client, coin: str) -> Optional[float]:
    """Return available balance for a coin from Coinbase.

    Returns:
        float  — balance (may be 0.0 if coin not held)
        None   — API call failed; balance is unknown
    """
    try:
        cursor = None
        while True:
            kw = {"limit": 250}
            if cursor:
                kw["cursor"] = cursor
            resp = client.get_accounts(**kw)
            for acc in resp.accounts:
                try:
                    cur = acc.currency if hasattr(acc, "currency") else ""
                    if cur != coin:
                        continue
                    ab = acc.available_balance
                    return float(ab["value"] if isinstance(ab, dict) else ab.value)
                except Exception:
                    continue
            has_next = getattr(resp, "has_next", False)
            cursor   = getattr(resp, "cursor", None)
            if not has_next or not cursor:
                break
        return 0.0  # API succeeded but coin wallet not found — genuinely not held
    except Exception as e:
        log.error(f"[BAL ERR] {coin}: {e}")
        return None  # API failure — balance unknown


def _fetch_order_fill(client, order_id: str, coin: str, retries: int = 4) -> tuple:
    """Fetch actual fill details for a completed Coinbase order.

    Market IOC orders fill immediately but the ledger may need <1s to settle.
    We retry up to `retries` times with 250ms spacing.

    Returns:
        (filled_size, filled_value_usd, avg_fill_price)
        filled_size  — exact base-currency qty purchased (what we hold)
        filled_value — USD actually spent (after fees)
        avg_fill_price — weighted average fill price
        All three are 0.0 on unrecoverable error.
    """
    for attempt in range(retries):
        try:
            resp  = client.get_order(order_id=order_id)
            order = resp.order if hasattr(resp, "order") else resp
            filled_size  = float(getattr(order, "filled_size",  0) or 0)
            filled_value = float(getattr(order, "filled_value", 0) or 0)
            if filled_value == 0:
                # some SDK versions expose this instead
                filled_value = float(getattr(order, "total_value_after_fees", 0) or 0)
            if filled_size > 0:
                avg_px = filled_value / filled_size if filled_value > 0 else 0.0
                log.info(
                    f"[FILL] {coin}  order={order_id}  qty={filled_size}"
                    f"  value=${filled_value:.4f}  avg_px={avg_px:.8f}"
                )
                return filled_size, filled_value, avg_px
            # Order not yet settled — wait and retry
            log.debug(f"[FILL] {coin} fill not ready (attempt {attempt + 1}/{retries}), waiting…")
            time.sleep(0.25)
        except Exception as e:
            log.error(f"[FILL ERR] {coin} order {order_id} attempt {attempt + 1}: {e}")
            time.sleep(0.25)
    log.error(f"[FILL ERR] {coin} could not fetch fill for {order_id} after {retries} retries")
    return 0.0, 0.0, 0.0


def _market_sell(client, coin: str, base_qty: float, reason: str) -> Optional[str]:
    """Attempt sell, retrying with fewer decimal places on INVALID_SIZE_PRECISION.

    Uses floor (not round) at each precision level so we never overshoot.
    On INSUFFICIENT_FUND, fetches the actual Coinbase balance and retries —
    the reconciler's qty estimate can drift from the real fill due to fees/
    slippage, causing the bot to request more than it holds.
    """
    def _attempt(qty: float) -> Optional[str]:
        for decimals in (8, 4, 2, 1, 0):
            factor = 10 ** decimals
            floored = math.floor(qty * factor) / factor
            if floored <= 0:
                continue
            cid = str(uuid.uuid4())
            qty_str = f"{floored:.{decimals}f}"
            try:
                resp = client.create_order(
                    client_order_id=cid,
                    product_id=f"{coin}-USD",
                    side="SELL",
                    order_configuration={"market_market_ioc": {"base_size": qty_str}},
                )
                if resp.success:
                    oid = resp.success_response["order_id"]
                    log.info(f"[SELL] {coin}  qty={qty_str}  reason={reason}  oid={oid}")
                    return oid
                err = resp.error_response or {}
                err_code = err.get("error", "") if isinstance(err, dict) else str(err)
                if "PRECISION" in err_code or "INVALID_SIZE" in err_code:
                    log.warning(f"[SELL] {coin} precision retry: {decimals}dp → {err_code}")
                    continue
                if "INSUFFICIENT_FUND" in err_code:
                    return "INSUFFICIENT_FUND"
                log.error(f"[SELL REJECT] {coin}: {resp.error_response}")
                return None
            except Exception as e:
                log.error(f"[SELL ERR] {coin}: {e}")
                return None
        return None

    result = _attempt(base_qty)
    if result == "INSUFFICIENT_FUND":
        # Bot's qty may be higher than actual balance — fetch real balance and retry
        real_qty = _get_coin_balance(client, coin)
        if real_qty is None:
            log.error(f"[SELL REJECT] {coin}: INSUFFICIENT_FUND and balance fetch failed")
            return None
        if real_qty <= 0:
            log.error(f"[SELL REJECT] {coin}: INSUFFICIENT_FUND and Coinbase balance is zero")
            return None
        log.warning(
            f"[SELL] {coin} INSUFFICIENT_FUND — fetched real balance: {real_qty}"
            f" (bot had {base_qty:.6f})"
        )
        result = _attempt(real_qty)
        if result and result != "INSUFFICIENT_FUND":
            return result
        log.error(f"[SELL REJECT] {coin}: INSUFFICIENT_FUND even with real balance {real_qty}")
        return None
    return result


class LiveExecutor:
    """
    Non-blocking live executor. on_signal / on_price return immediately.
    All Coinbase REST calls happen in _worker thread.
    """

    def __init__(self, trade_log_path: Path):
        self._client        = _make_client()
        self._positions: dict = {}          # coin → position dict
        self._lock          = threading.Lock()
        self._q: queue.Queue = queue.Queue()
        self._trade_log     = trade_log_path
        self._trade_log.parent.mkdir(parents=True, exist_ok=True)

        # cached balance — guarded by _balance_lock; refreshed periodically
        self._usd_cache     = 0.0
        self._usd_cache_ts  = 0.0
        self._balance_lock  = threading.Lock()

        # per-coin exit state for cooldown gate
        self._last_exit: dict = {}  # coin → (exit_ts_s: float, cooldown_key: str)

        # coins currently being entered (check-then-buy atomicity guard)
        self._pending_entry: set = set()

        self._thread = threading.Thread(target=self._worker, daemon=True, name="live-exec")
        self._thread.start()
        # restore any positions that were open when the service last stopped
        self._reconcile_from_log()
        # immediate balance fetch so we know the account is accessible
        threading.Thread(target=self._refresh_balance, daemon=True).start()
        log.info("[LiveExecutor] STARTED — live trading active on Coinbase account")

    # ── called from asyncio event loop — must be instant ────────────

    def on_signal(self, sig) -> None:
        """Non-blocking: enqueue signal for background processing."""
        log.info("[SIG-IN] variant=%s coin=%s", getattr(sig, "variant", "?"), getattr(sig, "coin", "?"))
        if sig.variant == "R5_CONFIRMED_RUN":
            log.info("[SIG-QUEUED] %s", sig.coin)
            self._q.put(("signal", sig))

    def on_price(self, coin: str, price: float) -> None:
        """Non-blocking: update price cache and check exit conditions inline.
        Exit orders are enqueued to the worker; price update is pure Python."""
        if coin.endswith("-USD"):
            coin = coin[:-4]
        with self._lock:
            pos = self._positions.get(coin)
            if pos is None:
                return
            if price > pos["peak_px"]:
                pos["peak_px"] = price

            gain     = price / pos["entry_px"] - 1.0
            hold_s   = time.time() - pos["entry_ts"]
            trail    = TRAIL_POST if pos["half_sold"] else TRAIL_PRE
            stop_px  = pos["peak_px"] * (1 - trail)

            if hold_s >= MAX_HOLD_S:
                self._q.put(("sell", coin, pos.copy(), price, "TIME_CAP"))
                del self._positions[coin]   # worker restores if sell fails
            elif not pos["half_sold"] and gain >= PARTIAL_TRIGGER:
                pos["half_sold"] = True
                pos["qty"] *= 0.5
                self._q.put(("partial", coin, pos.copy(), price))
            elif price <= stop_px:
                self._q.put(("sell", coin, pos.copy(), price, "TRAIL_STOP"))
                del self._positions[coin]   # worker restores if sell fails

    # ── background worker — all REST calls happen here ───────────────

    def _worker(self) -> None:
        log.info("[LiveExecutor] worker thread started")
        while True:
            try:
                item = self._q.get(timeout=60)
            except queue.Empty:
                # refresh balance cache every ~60s of inactivity
                self._refresh_balance()
                continue

            try:
                cmd = item[0]

                if cmd == "signal":
                    sig = item[1]
                    self._handle_entry(sig)

                elif cmd == "partial":
                    _, coin, pos, price = item
                    half_qty = pos["qty"]   # already halved in on_price
                    oid = _market_sell(self._client, coin, half_qty, "PARTIAL_20PCT")
                    gain = price / pos["entry_px"] - 1.0
                    if oid:
                        # Fetch exact remaining balance — don't assume 50% sold perfectly
                        real_remaining = _get_coin_balance(self._client, coin)
                        if real_remaining is None:
                            # API failure: keep halved estimate rather than zeroing the position
                            log.error(
                                f"[PARTIAL] {coin} — balance fetch failed after sell;"
                                f" keeping estimated remaining qty={half_qty:.6f}"
                            )
                            real_remaining = half_qty
                        with self._lock:
                            if coin in self._positions:
                                self._positions[coin]["qty"] = real_remaining
                                log.info(
                                    f"[PARTIAL] {coin} gain={gain:+.1%}  sold 50%"
                                    f"  remaining_qty={real_remaining}"
                                )
                        self._log("PARTIAL", coin, price, gain=gain, qty_remaining=real_remaining)
                    else:
                        # Sell failed — revert position state so it can retry
                        log.error(f"[PARTIAL FAIL] {coin} — reverting half_sold, full qty restored")
                        with self._lock:
                            if coin in self._positions:
                                self._positions[coin]["half_sold"] = False
                                self._positions[coin]["qty"] *= 2.0

                elif cmd == "sell":
                    _, coin, pos, trigger_px, reason = item
                    oid = _market_sell(self._client, coin, pos["qty"], reason)
                    if oid is None:
                        # Sell failed — restore position so on_price keeps managing it
                        # and will enqueue another sell attempt on the next price tick.
                        with self._lock:
                            if coin not in self._positions:
                                self._positions[coin] = pos
                        log.error(f"[SELL FAIL] {coin} — position RESTORED, will retry on next tick")
                        continue

                    # Verify the order actually filled — IOC orders can be accepted
                    # then cancelled with zero fill (e.g. insufficient liquidity or
                    # exchange-side reject after submission). If fill is zero the
                    # position still exists on the exchange: restore it so on_price
                    # keeps managing it and queues another sell on the next tick.
                    filled_qty, _, fill_px = _fetch_order_fill(self._client, oid, coin)
                    if filled_qty <= 0:
                        with self._lock:
                            if coin not in self._positions:
                                self._positions[coin] = pos
                        log.error(
                            f"[SELL CANCELLED] {coin} order {oid} — accepted but"
                            f" zero fill; position RESTORED, will retry on next tick"
                        )
                        continue
                    actual_exit_px = fill_px if fill_px > 0 else trigger_px
                    gain     = actual_exit_px / pos["entry_px"] - 1.0
                    hold_min = (time.time() - pos["entry_ts"]) / 60.0
                    half_sold = pos.get("half_sold", False)
                    log.info(
                        f"[EXIT] {coin} {reason} gain={gain:+.1%} held={hold_min:.1f}m"
                        f" Tier={pos['tier']} fill_px={actual_exit_px:.6f}"
                    )
                    self._log(
                        "EXIT", coin, actual_exit_px,
                        gain=gain,
                        trigger_px=trigger_px,
                        reason=reason,
                        hold_min=round(hold_min, 1),
                        tier=pos["tier"],
                        half_sold=half_sold,   # needed for correct cooldown key at reconcile
                    )
                    # Classify exit and arm the per-coin cooldown gate
                    if reason == "TRAIL_STOP":
                        ck = "TRAIL_STOP_PARTIAL" if half_sold else "TRAIL_STOP_FULL"
                    elif reason == "TIME_CAP":
                        ck = "TIME_CAP_GAIN" if gain >= 0 else "TIME_CAP_LOSS"
                    else:
                        ck = "TIME_CAP_GAIN"
                    self._last_exit[coin] = (time.time(), ck)
                    log.info(f"[COOLDOWN] {coin} → {ck} ({COOLDOWN_S.get(ck, 0) // 60}m)")

            except Exception as e:
                log.error(f"[WORKER ERR] {e}", exc_info=True)

    def _score_signal(self, sig) -> float:
        """Estimate expected value (%) for this signal from observable features.

        Starts from tier baseline (backtest adj-EV by tier), then adjusts for:
          cvd_30s      — buying vs selling pressure in last 30s
          secs_onset   — timing: fresh = good, chasing = bad
          dv_trend     — volume explosion strength
          spread_bps   — execution drag
          large_trade% — smart-money / institutional flow confirmation

        Returns estimated EV in percent (e.g. 4.2 = +4.2% expected per trade).
        Coefficients calibrated from live data; recalibrate at day 30 (2026-05-15).
        """
        f    = sig.features
        tier = f.get("confidence_tier", "D")
        ev   = float(TIER_EV_BASELINE.get(tier, 3.2))

        # CVD: net-buying pressure adds up to +2%; ranges from 0 at cvd=-2000
        # to +2% at cvd ≥ +2000. Linear interpolation.
        cvd = f.get("cvd_30s", 0.0)
        ev += min(2.0, max(0.0, (cvd + 2000) / 2000.0))

        # Timing: +1% at onset, 0 at 5s, −1.5% at 15s (linear decay).
        secs = f.get("secs_since_onset", 0.0)
        ev  += max(-1.5, 1.0 - (secs / 5.0))

        # Volume explosion: high dvt confirms the move is real.
        dvt = f.get("dv_trend", 0.0)
        ev += 1.5 if dvt >= 10 else (0.5 if dvt >= 5 else (-1.0 if dvt < 3 else 0.0))

        # Spread: execution drag (wide spread eats EV at entry and exit).
        spread = f.get("spread_bps", 5.0)
        ev += 0.5 if spread <= 3 else (0.0 if spread <= 7 else -0.5)

        # Smart-money confirmation: large-trade participation suggests
        # institutional flow rather than retail FOMO.
        ltrade = f.get("large_trade_pct_60s", 0.0)
        ev += 1.5 if ltrade >= 0.3 else (0.5 if ltrade >= 0.1 else 0.0)

        return round(ev, 2)

    def _handle_entry(self, sig) -> None:
        coin       = sig.coin
        mid        = sig.sig_mid
        tier       = sig.features.get("confidence_tier", "D")
        pos_pct    = sig.features.get("position_pct", 0.20)
        fear_greed = sig.features.get("fear_greed", 50)

        # Tier A/B are consolidation patterns (r5m 0.5-1%).
        # Skip only in true panic: F&G < 15 AND BTC not recovering intraday.
        # Threshold lowered from 25→15: F&G=21 is "nervous", not panic.
        # F&G updates once/day at midnight UTC — it cannot capture intraday
        # sentiment reversals (macro catalysts, BTC recovery legs, etc.).
        # Override: if BTC is up >2% in the last hour, market has turned
        # risk-on regardless of the stale daily index.
        btc_ret_1h = sig.features.get("btc_ret_1h", 0.0)
        if tier in ("A", "B") and fear_greed < 15 and btc_ret_1h <= 0.02:
            log.info(
                f"[SKIP] {coin} Tier={tier} F&G={fear_greed} btc_1h={btc_ret_1h:+.1%}"
                f" — true panic, consolidation skip"
            )
            return

        cvd_30s = sig.features.get("cvd_30s", 0.0)
        if cvd_30s < GATE_CVD_30S_MIN:
            log.info(f"[SKIP] {coin} cvd_30s={cvd_30s:.0f} < {GATE_CVD_30S_MIN} — net selling pressure")
            return

        secs_onset = sig.features.get("secs_since_onset", 0.0)
        if secs_onset >= GATE_ONSET_S:
            log.info(f"[SKIP] {coin} secs_since_onset={secs_onset:.1f}s >= {GATE_ONSET_S}s — late entry")
            return

        # Per-coin cooldown gate: if this coin recently stopped us out or timed out at a
        # loss, require a minimum rest period before re-entering.
        last = self._last_exit.get(coin)
        if last is not None:
            exit_ts, cooldown_key = last
            cooldown  = COOLDOWN_S.get(cooldown_key, 0)
            elapsed   = time.time() - exit_ts
            if elapsed < cooldown:
                remaining_m = (cooldown - elapsed) / 60
                log.info(
                    f"[SKIP] {coin} cooldown={cooldown_key} "
                    f"remaining={remaining_m:.0f}m"
                )
                return

        # Atomically check and mark this coin as "being entered" to prevent
        # duplicate buys if two signals for the same coin queue up.
        with self._lock:
            if coin in self._positions or coin in self._pending_entry:
                log.info(f"[SKIP] {coin} already in position or pending entry")
                return
            self._pending_entry.add(coin)

        try:
            self._do_entry(sig, coin, mid, tier, pos_pct)
        finally:
            with self._lock:
                self._pending_entry.discard(coin)

    def _do_entry(self, sig, coin: str, mid: float, tier: str, pos_pct: float) -> None:
        """Execute the buy order and record the position. Called under _pending_entry guard."""
        # Score signal quality. Gate below minimum EV; scale position size
        # proportional to EV vs tier baseline so hot-day high-conviction trades
        # get full capital while marginal signals get reduced (but not blocked).
        ev_score    = self._score_signal(sig)
        baseline_ev = TIER_EV_BASELINE.get(tier, 3.2)
        if ev_score < MIN_EV_PCT:
            log.info(f"[SKIP] {coin} ev={ev_score:.1f}% < {MIN_EV_PCT}% min — low expected value")
            return
        ev_scale = max(0.5, min(1.0, ev_score / baseline_ev))
        pos_pct  = round(pos_pct * ev_scale, 3)
        log.info(
            f"[SCORE] {coin} Tier={tier} ev={ev_score:.1f}% "
            f"baseline={baseline_ev}% scale={ev_scale:.2f} → pos={pos_pct:.1%}"
        )

        # Refresh balance and size the order
        self._refresh_balance()
        with self._balance_lock:
            bal = self._usd_cache

        if bal < MIN_ORDER_USD * 2:
            log.warning(f"[SKIP] {coin} — USD balance too low: {bal:.2f}")
            return

        usd_size = round(bal * pos_pct, 2)
        if usd_size < MIN_ORDER_USD:
            log.warning(f"[SKIP] {coin} — position size {usd_size:.2f} < min {MIN_ORDER_USD}")
            return

        # Capture order submission time BEFORE the API call so entry_ts reflects
        # when the order was placed, not when the fill was confirmed.
        order_ts = time.time()
        order_id = _market_buy(self._client, coin, usd_size)
        if not order_id:
            return

        # Immediately decrement the balance cache so the next signal uses
        # the post-buy balance rather than the stale pre-buy value.
        with self._balance_lock:
            self._usd_cache    = max(0.0, self._usd_cache - usd_size)
            self._usd_cache_ts = 0.0   # force real refresh on next entry

        # Fetch exact fill from Coinbase — never estimate qty
        filled_qty, filled_value, fill_px = _fetch_order_fill(self._client, order_id, coin)
        if filled_qty <= 0:
            # Fill fetch failed after retries. Position may exist on exchange —
            # fall back to estimate and flag the record so it can be audited.
            log.error(
                f"[ENTRY WARN] {coin} fill fetch failed for {order_id} — "
                f"using estimate. Verify on Coinbase manually."
            )
            filled_qty   = (usd_size / mid) * (1 - SLIP)
            filled_value = usd_size
            fill_px      = mid
            fill_warn    = True
        else:
            fill_warn = False

        actual_px = fill_px if fill_px > 0 else mid

        with self._lock:
            self._positions[coin] = {
                "entry_px":  actual_px,
                "qty":       filled_qty,
                "peak_px":   actual_px,
                "half_sold": False,
                "entry_ts":  order_ts,    # order submission time, not fill confirmation time
                "tier":      tier,
                "usd_in":    filled_value,
                "buy_order": order_id,
            }
        log.info(
            f"[ENTRY] {coin} Tier={tier} ev={ev_score:.1f}% pos={pos_pct:.0%} "
            f"qty={filled_qty:.6f} px={actual_px:.6f} usd={filled_value:.2f}  bal={bal:.2f}"
        )

        # Write FILL to trade log first — this is the atomic unit of truth.
        # If the service crashes before ENTRY is written, the orphaned FILL
        # record alerts the reconciler that a position may exist on the exchange.
        self._log(
            "FILL", coin, actual_px,
            order_id=order_id,
            qty=round(filled_qty, 8),
            value_usd=round(filled_value, 4),
        )
        extra = {"fill_warn": True} if fill_warn else {}
        self._log(
            "ENTRY", coin, actual_px,
            tier=tier,
            qty=round(filled_qty, 8),
            usd_size=round(filled_value, 4),
            buy_order=order_id,
            peak_px=round(actual_px, 8),
            pos_pct=pos_pct,
            ev_score=ev_score,
            ev_scale=ev_scale,
            features=sig.features,
            **extra,
        )

    def _reconcile_from_log(self) -> None:
        """Rebuild open positions from live_trades.jsonl on startup.

        Handles both ENTRY record formats:
          executor:  {"event":"ENTRY","coin":"X","price":…,"ts":…,"tier":…,
                       "qty":…,"usd_size":…,"buy_order":…,"peak_px":…}
          manual:    {"event":"ENTRY","coin":"X","entry_px":…,"entry_ts":…,
                       "qty":…,"usd_in":…}

        Uses a per-coin stack (LIFO) so that a manually appended ENTRY+EXIT pair
        correctly cancels out against its own ENTRY even when a newer ENTRY for the
        same coin was logged earlier in the file (restart-amnesia edge case).
        """
        if not self._trade_log.exists():
            log.info("[RECONCILE] no trade log — starting fresh")
            return

        try:
            with self._trade_log.open() as f:
                lines = f.readlines()
        except Exception as e:
            log.error(f"[RECONCILE] read error: {e}")
            return

        stacks: dict  = defaultdict(list)   # coin → [pos_dict, ...]
        fill_ids: set = set()               # order_ids with a FILL record
        entry_ids: set = set()              # order_ids with an ENTRY record

        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except Exception:
                log.warning(f"[RECONCILE] skipped corrupt line: {raw[:80]}")
                continue

            event = rec.get("event", "")
            coin  = rec.get("coin", "")
            if not coin or not event:
                continue

            if event == "FILL":
                oid = rec.get("order_id")
                if oid:
                    fill_ids.add(oid)

            elif event == "ENTRY":
                price    = float(rec.get("price") or rec.get("entry_px") or 0)
                usd_size = float(rec.get("usd_size") or rec.get("usd_in") or 0)
                tier     = rec.get("tier", "D")
                qty_raw  = rec.get("qty")

                if qty_raw is not None:
                    qty = float(qty_raw)   # exact fill qty logged at entry time
                elif price > 0:
                    # Legacy records without qty — estimate.
                    # New records always have qty so this path should not be hit.
                    qty = (usd_size / price) * (1.0 - SLIP)
                    log.warning(f"[RECONCILE] {coin} no qty in ENTRY record — using estimate")
                else:
                    qty = 0.0

                ts_raw = rec.get("ts") or rec.get("entry_ts", "")
                try:
                    entry_ts = datetime.fromisoformat(
                        str(ts_raw).rstrip("Z")
                    ).replace(tzinfo=_tz.utc).timestamp()
                except (ValueError, AttributeError):
                    try:
                        entry_ts = float(ts_raw)  # Unix timestamp (early ENTRY records)
                    except (ValueError, TypeError):
                        log.warning(f"[RECONCILE] {coin} unparseable ts={ts_raw!r} — using current time")
                        entry_ts = time.time()

                # Restore peak_px from log if present; fall back to entry price.
                # peak_px logged at entry equals entry_px, but once a position
                # survives a restart the reconciler sets it to max(entry_px, current_bid).
                peak_px = float(rec.get("peak_px") or price)

                buy_order = rec.get("buy_order", "reconciled")
                if buy_order != "reconciled":
                    entry_ids.add(buy_order)

                stacks[coin].append({
                    "entry_px":  price,
                    "qty":       qty,
                    "peak_px":   peak_px,
                    "half_sold": False,
                    "entry_ts":  entry_ts,
                    "tier":      tier,
                    "usd_in":    usd_size,
                    "buy_order": buy_order,
                })

            elif event == "PARTIAL":
                if stacks[coin]:
                    stacks[coin][-1]["half_sold"] = True
                    qty_remaining = rec.get("qty_remaining")
                    if qty_remaining is not None:
                        # Use exact remaining balance logged at partial sell time
                        stacks[coin][-1]["qty"] = float(qty_remaining)
                    else:
                        # Legacy records without qty_remaining — fall back to 50% estimate
                        stacks[coin][-1]["qty"] *= 0.5

            elif event in ("EXIT", "SELL"):
                if stacks[coin]:
                    stacks[coin].pop()      # LIFO: EXIT cancels its own ENTRY

        # Warn on orphaned FILL records — FILL written but ENTRY never followed
        # (service crashed between the two log writes). Coins may be held on exchange
        # without any tracking record.
        orphaned_fills = fill_ids - entry_ids
        for oid in orphaned_fills:
            log.critical(
                f"[RECONCILE] ORPHANED FILL detected: order_id={oid} has no matching ENTRY. "
                f"A Coinbase position may exist without bot tracking. Verify manually."
            )

        # Any coin with a non-empty stack has an open position
        open_pos = {coin: entries[-1]
                    for coin, entries in stacks.items() if entries}

        # Second pass: restore _last_exit from the most recent EXIT per coin so
        # cooldowns survive service restarts.
        last_exits: dict = {}
        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except Exception:
                continue
            if rec.get("event") in ("EXIT", "SELL") and rec.get("coin"):
                last_exits[rec["coin"]] = rec   # keeps last occurrence (latest in file)

        for coin, rec in last_exits.items():
            reason    = rec.get("reason", "")
            gain      = float(rec.get("gain", 0.0))
            half_sold = rec.get("half_sold")           # present in new records
            ts_raw    = rec.get("ts", "")
            try:
                exit_ts = datetime.fromisoformat(
                    ts_raw.rstrip("Z")
                ).replace(tzinfo=_tz.utc).timestamp()
            except Exception:
                exit_ts = time.time()

            if reason == "TRAIL_STOP":
                if half_sold is not None:
                    # Use the logged half_sold flag — exact classification
                    ck = "TRAIL_STOP_PARTIAL" if half_sold else "TRAIL_STOP_FULL"
                else:
                    # Legacy EXIT record without half_sold field — fall back to
                    # gain-based heuristic (imperfect but better than nothing)
                    ck = "TRAIL_STOP_PARTIAL" if gain > 0 else "TRAIL_STOP_FULL"
                    log.warning(
                        f"[RECONCILE] {coin} EXIT has no half_sold field — "
                        f"classifying by gain sign (legacy fallback)"
                    )
            elif reason == "TIME_CAP":
                ck = "TIME_CAP_GAIN" if gain >= 0 else "TIME_CAP_LOSS"
            else:
                ck = "TIME_CAP_GAIN"

            self._last_exit[coin] = (exit_ts, ck)
            remaining = max(0.0, (COOLDOWN_S.get(ck, 0) - (time.time() - exit_ts)) / 60)
            if remaining > 0:
                log.info(f"[RECONCILE] {coin} cooldown={ck} remaining={remaining:.0f}m")

        if not open_pos:
            log.info("[RECONCILE] no open positions found in log")

        recovered = 0
        for coin, pos in open_pos.items():
            price = None
            try:
                resp  = self._client.get_best_bid_ask(product_ids=[f"{coin}-USD"])
                price = float(resp.pricebooks[0].bids[0].price)
            except Exception as e:
                log.warning(f"[RECONCILE] price fetch failed for {coin}: {e}")

            if price is not None:
                # Update peak_px to at least the current price; the true historical
                # peak since last ENTRY is unknowable after a restart.
                pos["peak_px"] = max(pos["peak_px"], price)
                gain     = price / pos["entry_px"] - 1.0
                hold_s   = time.time() - pos["entry_ts"]
                hold_min = hold_s / 60.0
                trail    = TRAIL_POST if pos["half_sold"] else TRAIL_PRE
                stop_px  = pos["peak_px"] * (1 - trail)
                log.info(
                    f"[RECONCILE] {coin}  tier={pos['tier']}  "
                    f"entry={pos['entry_px']:.6f}  now={price:.6f}  "
                    f"gain={gain:+.1%}  held={hold_min:.0f}m  "
                    f"stop={stop_px:.6f}  half_sold={pos['half_sold']}"
                )
                # Immediate exit check: if position is already past stop threshold
                # or time cap at startup, sell now — don't wait for the next on_price tick.
                if hold_s >= MAX_HOLD_S:
                    log.warning(
                        f"[RECONCILE] {coin} past TIME_CAP (held {hold_min:.0f}m)"
                        f" — queueing immediate exit"
                    )
                    self._q.put(("sell", coin, pos.copy(), price, "TIME_CAP"))
                    continue
                elif price <= stop_px:
                    log.warning(
                        f"[RECONCILE] {coin} past TRAIL_STOP at reconcile"
                        f" (price={price:.6f} <= stop={stop_px:.6f}, gain={gain:+.1%})"
                        f" — queueing immediate exit"
                    )
                    self._q.put(("sell", coin, pos.copy(), price, "TRAIL_STOP"))
                    continue

            with self._lock:
                self._positions[coin] = pos
            recovered += 1

        log.info(f"[RECONCILE] {recovered} position(s) restored")

        # ── Coinbase balance sweep ────────────────────────────────────────
        # Cross-check actual exchange balances against tracked positions.
        # Any coin Coinbase holds that the bot isn't tracking is an orphan —
        # either from a cancelled sell (the bug this was written to catch),
        # a crash between FILL and ENTRY log writes, or manual interference.
        # We restore orphans at best-effort sizing so the exit logic takes over.
        try:
            cb_balances = _get_all_coin_balances(self._client)
        except Exception as e:
            log.error(f"[RECONCILE] balance sweep failed: {e}")
            cb_balances = {}

        with self._lock:
            tracked = set(self._positions.keys())

        for coin, qty in cb_balances.items():
            if coin in tracked:
                # Already tracking — verify qty is in the right ballpark
                with self._lock:
                    pos_qty = self._positions[coin].get("qty", 0)
                if qty > 0 and pos_qty > 0 and abs(qty - pos_qty) / max(qty, pos_qty) > 0.20:
                    log.warning(
                        f"[RECONCILE] {coin} qty mismatch: bot={pos_qty:.6f}"
                        f" coinbase={qty:.6f} — updating to exchange value"
                    )
                    with self._lock:
                        self._positions[coin]["qty"] = qty
                continue

            # Coin held on exchange but not tracked — orphaned position
            price = None
            try:
                resp  = self._client.get_best_bid_ask(product_ids=[f"{coin}-USD"])
                price = float(resp.pricebooks[0].bids[0].price)
            except Exception as e:
                log.warning(f"[RECONCILE] price fetch failed for orphan {coin}: {e}")

            usd_value = (price * qty) if price else 0.0
            if usd_value < MIN_ORDER_USD:
                log.info(
                    f"[RECONCILE] {coin} orphan balance={qty:.6f}"
                    f" (~${usd_value:.2f}) below min — skipping"
                )
                continue

            log.critical(
                f"[RECONCILE] ORPHAN POSITION: {coin} qty={qty:.6f}"
                f" ~${usd_value:.2f} held on Coinbase but NOT tracked by bot."
                f" Restoring with TRAIL_STOP management. Verify entry price manually."
            )
            # Best-effort restore: use current price as entry_px so trail is
            # measured from now. This is conservative — the real entry may have
            # been higher (meaning we're already at a loss we can't recover).
            entry_px = price if price else 1.0
            orphan_pos = {
                "entry_px":  entry_px,
                "qty":       qty,
                "peak_px":   entry_px,
                "half_sold": False,
                "entry_ts":  time.time(),
                "tier":      "D",
                "usd_in":    usd_value,
                "buy_order": "reconciled_orphan",
            }
            if price is not None:
                trail_stop_px = entry_px * (1 - TRAIL_PRE)
                if price <= trail_stop_px:
                    log.warning(
                        f"[RECONCILE] {coin} orphan already past trail stop"
                        f" — queueing immediate sell"
                    )
                    self._q.put(("sell", coin, orphan_pos.copy(), price, "TRAIL_STOP"))
                    continue
            with self._lock:
                self._positions[coin] = orphan_pos

        log.info(f"[RECONCILE] balance sweep complete — exchange has {len(cb_balances)} non-USD coin(s)")

    def _refresh_balance(self) -> None:
        """Refresh USD balance cache. Thread-safe; TTL-gated to avoid hammering the API."""
        with self._balance_lock:
            if time.time() - self._usd_cache_ts < 30:
                return
        # API call outside the lock so we don't hold it while waiting on the network.
        try:
            bal = _get_usd_balance(self._client)
            with self._balance_lock:
                self._usd_cache    = bal
                self._usd_cache_ts = time.time()
            log.info(f"[BALANCE] USD available: {bal:.2f}")
        except Exception as e:
            log.error(f"[BALANCE ERR] {e}")

    def _log(self, event: str, coin: str, price: float, **kw) -> None:
        """Write a trade event to the durable trade log (live_trades.jsonl).

        On write failure: logs CRITICAL (surfaced to systemd journal) and echoes
        the record to stderr as a last-resort audit trail. Never silently drops.
        """
        rec = {
            "event": event,
            "coin":  coin,
            "price": price,
            "ts":    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **kw,
        }
        line = json.dumps(rec, default=str) + "\n"
        try:
            with self._trade_log.open("a") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            log.critical(
                f"[LOG CRITICAL] trade log write FAILED for {event} {coin}: {e}"
            )
            # Echo to stderr so the record lands in the systemd journal even if
            # the log file is unavailable.
            print(f"TRADE_LOG_FAIL: {line.rstrip()}", file=sys.stderr, flush=True)
