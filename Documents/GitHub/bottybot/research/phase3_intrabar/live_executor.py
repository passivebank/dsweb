"""
live_executor.py — R5_CONFIRMED_RUN live trade executor.

Non-blocking: all REST calls run in a background daemon thread via a queue.
on_signal() and on_price() return instantly — never block the asyncio loop.
"""
import json
import math
import os
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
SLIP            = 0.0003
MIN_ORDER_USD   = 10.0   # raised from 5 — sub-$10 positions have negligible dollar P&L
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


def _get_coin_balance(client, coin: str) -> float:
    """Return available balance for a coin from Coinbase. Returns 0.0 on error."""
    try:
        resp = client.get_accounts(limit=250)
        for acc in resp.accounts:
            try:
                cur = acc.currency if hasattr(acc, "currency") else ""
                if cur != coin:
                    continue
                ab = acc.available_balance
                return float(ab["value"] if isinstance(ab, dict) else ab.value)
            except Exception:
                continue
    except Exception as e:
        log.error(f"[BAL ERR] {coin}: {e}")
    return 0.0


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
        # Bot's qty estimate is higher than actual balance — fetch real balance and retry
        real_qty = _get_coin_balance(client, coin)
        log.warning(f"[SELL] {coin} INSUFFICIENT_FUND — fetched real balance: {real_qty} (bot had {base_qty:.6f})")
        if real_qty > 0:
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

        # cached balance — refreshed in worker, used at entry
        self._usd_cache     = 0.0
        self._usd_cache_ts  = 0.0

        # per-coin exit state for cooldown gate
        self._last_exit: dict = {}  # coin → (exit_ts_s: float, cooldown_key: str)

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
                        log.info(f"[PARTIAL] {coin} gain={gain:+.1%}  sold 50% @ ~{price:.6f}")
                        self._log("PARTIAL", coin, price, gain=gain)
                    else:
                        # Sell failed — revert position state so it can retry
                        log.error(f"[PARTIAL FAIL] {coin} — reverting half_sold, full qty restored")
                        with self._lock:
                            if coin in self._positions:
                                self._positions[coin]["half_sold"] = False
                                self._positions[coin]["qty"] *= 2.0

                elif cmd == "sell":
                    _, coin, pos, price, reason = item
                    oid = _market_sell(self._client, coin, pos["qty"], reason)
                    if oid is None:
                        # Sell failed — restore position so on_price keeps managing it
                        # and will enqueue another sell attempt on the next price tick.
                        with self._lock:
                            if coin not in self._positions:
                                self._positions[coin] = pos
                        log.error(f"[SELL FAIL] {coin} — position RESTORED, will retry on next tick")
                        continue
                    gain = price / pos["entry_px"] - 1.0
                    hold_min = (time.time() - pos["entry_ts"]) / 60.0
                    log.info(f"[EXIT] {coin} {reason} gain={gain:+.1%} held={hold_min:.1f}m Tier={pos['tier']}")
                    self._log("EXIT", coin, price, gain=gain, reason=reason,
                              hold_min=round(hold_min, 1), tier=pos["tier"])
                    # Classify exit and arm the per-coin cooldown gate
                    if reason == "TRAIL_STOP":
                        ck = "TRAIL_STOP_PARTIAL" if pos.get("half_sold") else "TRAIL_STOP_FULL"
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
        # In extreme fear they reverse immediately — 0/7 live, -7% adj_EV.
        # Skip until F&G recovers above 25.
        if tier in ("A", "B") and fear_greed < 25:
            log.info(f"[SKIP] {coin} Tier={tier} F&G={fear_greed} — extreme fear, consolidation skip")
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
        # loss, require a minimum rest period before re-entering. If the coin makes a
        # fresh genuine breakout after the cooldown expires, it trades freely.
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

        with self._lock:
            if coin in self._positions:
                log.info(f"[SKIP] {coin} already in position")
                return

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

        # refresh balance
        self._refresh_balance()
        bal = self._usd_cache

        if bal < MIN_ORDER_USD * 2:
            log.warning(f"[SKIP] {coin} — USD balance too low: {bal:.2f}")
            return

        usd_size = round(bal * pos_pct, 2)
        if usd_size < MIN_ORDER_USD:
            log.warning(f"[SKIP] {coin} — position size {usd_size:.2f} < min {MIN_ORDER_USD}")
            return

        order_id = _market_buy(self._client, coin, usd_size)
        if not order_id:
            return

        approx_qty = (usd_size / mid) * (1 - SLIP)
        with self._lock:
            self._positions[coin] = {
                "entry_px": mid, "qty": approx_qty,
                "peak_px": mid, "half_sold": False,
                "entry_ts": time.time(), "tier": tier,
                "usd_in": usd_size, "buy_order": order_id,
            }
        log.info(
            f"[ENTRY] {coin} Tier={tier} ev={ev_score:.1f}% pos={pos_pct:.0%} "
            f"usd={usd_size:.2f} @ ~{mid:.6f}  bal={bal:.2f}"
        )
        self._log("ENTRY", coin, mid, tier=tier, usd_size=usd_size,
                  pos_pct=pos_pct, ev_score=ev_score, ev_scale=ev_scale,
                  features=sig.features)

    def _reconcile_from_log(self) -> None:
        """Rebuild open positions from live_trades.jsonl on startup.

        Handles both ENTRY record formats:
          executor:  {"event":"ENTRY","coin":"X","price":…,"ts":…,"tier":…,"usd_size":…}
          manual:    {"event":"ENTRY","coin":"X","entry_px":…,"entry_ts":…,"qty":…,"usd_in":…}

        Uses a per-coin stack (LIFO) so that a manually appended ENTRY+EXIT pair
        correctly cancels out against its own ENTRY even when a newer ENTRY for the
        same coin was logged earlier in the file (restart-amnesia edge case).
        """
        if not self._trade_log.exists():
            log.info("[RECONCILE] no trade log — starting fresh")
            return

        stacks: dict = defaultdict(list)   # coin → [pos_dict, ...]  top = most recently appended

        try:
            with self._trade_log.open() as f:
                lines = f.readlines()
        except Exception as e:
            log.error(f"[RECONCILE] read error: {e}")
            return

        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except Exception:
                continue

            event = rec.get("event", "")
            coin  = rec.get("coin", "")
            if not coin or not event:
                continue

            if event == "ENTRY":
                price    = float(rec.get("price") or rec.get("entry_px") or 0)
                usd_size = float(rec.get("usd_size") or rec.get("usd_in") or 0)
                tier     = rec.get("tier", "D")
                qty_raw  = rec.get("qty")
                qty      = float(qty_raw) if qty_raw is not None else (
                    (usd_size / price) * (1.0 - SLIP) if price > 0 else 0.0
                )
                ts_raw = rec.get("ts") or rec.get("entry_ts", "")
                try:
                    entry_ts = datetime.fromisoformat(
                        ts_raw.rstrip("Z")
                    ).replace(tzinfo=_tz.utc).timestamp()
                except Exception:
                    entry_ts = time.time()

                stacks[coin].append({
                    "entry_px":  price,
                    "qty":       qty,
                    "peak_px":   price,
                    "half_sold": False,
                    "entry_ts":  entry_ts,
                    "tier":      tier,
                    "usd_in":    usd_size,
                    "buy_order": rec.get("buy_order", "reconciled"),
                })

            elif event == "PARTIAL":
                if stacks[coin]:
                    stacks[coin][-1]["half_sold"] = True
                    stacks[coin][-1]["qty"]      *= 0.5

            elif event in ("EXIT", "SELL"):
                if stacks[coin]:
                    stacks[coin].pop()      # LIFO: EXIT cancels its own ENTRY

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
            reason = rec.get("reason", "")
            gain   = float(rec.get("gain", 0.0))
            ts_raw = rec.get("ts", "")
            try:
                exit_ts = datetime.fromisoformat(
                    ts_raw.rstrip("Z")
                ).replace(tzinfo=_tz.utc).timestamp()
            except Exception:
                exit_ts = time.time()
            if reason == "TRAIL_STOP":
                ck = "TRAIL_STOP_PARTIAL" if gain > 0 else "TRAIL_STOP_FULL"
            elif reason == "TIME_CAP":
                ck = "TIME_CAP_GAIN" if gain >= 0 else "TIME_CAP_LOSS"
            else:
                ck = "TIME_CAP_GAIN"
            self._last_exit[coin] = (exit_ts, ck)
            remaining = max(0.0, (COOLDOWN_S.get(ck, 0) - (time.time() - exit_ts)) / 60)
            if remaining > 0:
                log.info(f"[RECONCILE] {coin} cooldown={ck} remaining={remaining:.0f}m")

        if not open_pos:
            log.info("[RECONCILE] no open positions found")
            return

        recovered = 0
        for coin, pos in open_pos.items():
            try:
                resp  = self._client.get_best_bid_ask(product_ids=[f"{coin}-USD"])
                price = float(resp.pricebooks[0].bids[0].price)
                pos["peak_px"] = max(pos["entry_px"], price)
                gain     = price / pos["entry_px"] - 1.0
                hold_min = (time.time() - pos["entry_ts"]) / 60.0
                log.info(
                    f"[RECONCILE] restored {coin}  tier={pos['tier']}  "
                    f"entry={pos['entry_px']:.6f}  now={price:.6f}  "
                    f"gain={gain:+.1%}  held={hold_min:.0f}m  "
                    f"half_sold={pos['half_sold']}"
                )
            except Exception as e:
                log.warning(f"[RECONCILE] price fetch failed for {coin}: {e}")

            with self._lock:
                self._positions[coin] = pos
            recovered += 1

        log.info(f"[RECONCILE] {recovered} position(s) restored")

    def _refresh_balance(self) -> None:
        if time.time() - self._usd_cache_ts < 30:
            return
        try:
            bal = _get_usd_balance(self._client)
            self._usd_cache    = bal
            self._usd_cache_ts = time.time()
            log.info(f"[BALANCE] USD available: {bal:.2f}")
        except Exception as e:
            log.error(f"[BALANCE ERR] {e}")

    def _log(self, event: str, coin: str, price: float, **kw) -> None:
        rec = {"event": event, "coin": coin, "price": price,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **kw}
        try:
            with self._trade_log.open("a") as f:
                f.write(json.dumps(rec, default=str) + "\n")
        except Exception as e:
            log.error(f"[LOG ERR] {e}")
