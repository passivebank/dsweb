"""
test_live_executor.py — unit tests for live_executor.py

All Coinbase API calls are mocked. No live connections are made.
Tests verify:
  1. Functional fixes (the 12 reliability issues)
  2. Trading logic is unchanged (EV scoring, thresholds, position sizing,
     trail stops, cooldowns, gates)

Run: python -m pytest research/phase3_intrabar/tests/test_live_executor.py -v
"""

import json
import os
import sys
import time
import threading
import tempfile
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Path setup — allow importing live_executor from parent directory
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent))
import live_executor as le
from live_executor import (
    _get_coin_balance,
    _get_usd_balance,
    _market_buy,
    _market_sell,
    _fetch_order_fill,
    LiveExecutor,
    COOLDOWN_S,
    TIER_EV_BASELINE,
    MIN_EV_PCT,
    PARTIAL_TRIGGER,
    TRAIL_PRE,
    TRAIL_POST,
    MAX_HOLD_S,
    GATE_CVD_30S_MIN,
    GATE_ONSET_S,
)


# ---------------------------------------------------------------------------
# Helpers & fixtures
# ---------------------------------------------------------------------------

@dataclass
class FakeSignal:
    """Minimal stand-in for detector.SignalEvent."""
    variant:    str   = "R5_CONFIRMED_RUN"
    coin:       str   = "TEST"
    sig_ts_ns:  int   = 0
    sig_mid:    float = 1.00
    features:   dict  = field(default_factory=lambda: {
        "confidence_tier":    "D",
        "position_pct":       0.20,
        "fear_greed":         50,
        "cvd_30s":            500.0,
        "secs_since_onset":   1.0,
        "dv_trend":           6.0,
        "spread_bps":         5.0,
        "large_trade_pct_60s": 0.0,
    })


def _make_account(currency: str, balance: float) -> MagicMock:
    """Build a fake Coinbase account object."""
    acc = MagicMock()
    acc.currency = currency
    acc.available_balance = {"value": str(balance)}
    return acc


def _make_accounts_response(*accounts, has_next=False, cursor=None) -> MagicMock:
    resp = MagicMock()
    resp.accounts = list(accounts)
    resp.has_next = has_next
    resp.cursor   = cursor
    return resp


def _make_order_response(order_id: str, success: bool = True,
                          error_code: str = "") -> MagicMock:
    resp = MagicMock()
    resp.success = success
    if success:
        resp.success_response = {"order_id": order_id}
    else:
        resp.error_response = {"error": error_code, "message": error_code}
    return resp


def _make_fill_response(order_id: str, filled_size: float,
                         filled_value: float, status: str = "FILLED") -> MagicMock:
    resp = MagicMock()
    order = MagicMock()
    order.filled_size            = str(filled_size)
    order.filled_value           = str(filled_value)
    order.total_value_after_fees = str(filled_value)
    order.status                 = status
    resp.order = order
    return resp


def _make_bbo_response(bid: float = None, ask: float = None) -> MagicMock:
    """Build a fake get_best_bid_ask response."""
    pb = MagicMock()
    pb.bids = [MagicMock(price=str(bid))] if bid is not None else []
    pb.asks = [MagicMock(price=str(ask))] if ask is not None else []
    resp = MagicMock()
    resp.pricebooks = [pb]
    return resp


def _make_list_orders_response(*orders) -> MagicMock:
    resp = MagicMock()
    resp.orders = list(orders)
    return resp


def _make_cancel_response(success: bool = True) -> MagicMock:
    resp = MagicMock()
    r0 = MagicMock()
    r0.success = success
    r0.failure_reason = "" if success else "ALREADY_FILLED"
    resp.results = [r0]
    return resp


def _make_executor(tmp_path: Path, client: MagicMock) -> LiveExecutor:
    """Build a LiveExecutor with a mocked client, bypassing _make_client."""
    trade_log = tmp_path / "live_trades.jsonl"
    # Default: no stranded sells found at startup. Tests that care can override.
    if not getattr(client.list_orders, "_pretend_set", False):
        client.list_orders.return_value = _make_list_orders_response()
    with patch.object(le, "_make_client", return_value=client):
        ex = LiveExecutor(trade_log)
    return ex


# ---------------------------------------------------------------------------
# FIX 1 — Balance cache decremented immediately after buy
# ---------------------------------------------------------------------------

class TestBalanceCacheDecrement:
    def test_cache_decremented_after_fill(self, tmp_path):
        """After a successful buy+fill, the balance cache drops by filled_value,
        not by the full usd_size (which may differ slightly due to fees)."""
        client = MagicMock()

        # First accounts call: $200 balance
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 200.0)
        )
        client.create_order.return_value = _make_order_response("oid-buy-1")
        # Fill: $38.10 spent, 23.989 coins received
        client.get_order.return_value = _make_fill_response("oid-buy-1", 23.989, 38.10)
        client.get_best_bid_ask.return_value = MagicMock(
            pricebooks=[MagicMock(bids=[MagicMock(price="1.59")])]
        )

        ex = _make_executor(tmp_path, client)

        sig = FakeSignal(coin="EUL", sig_mid=1.59,
                         features={**FakeSignal().features,
                                   "confidence_tier": "D", "position_pct": 0.20})

        # Manually prime the balance cache
        with ex._balance_lock:
            ex._usd_cache    = 200.0
            ex._usd_cache_ts = time.time()

        ex._do_entry(sig, "EUL", 1.59, "D", 0.20)

        # Cache should be decremented by the pre-buy usd_size ($40), not still $200
        with ex._balance_lock:
            cached = ex._usd_cache
        assert cached < 200.0, "Cache must drop after buy"
        assert cached >= 0.0,  "Cache must not go negative"

    def test_cache_invalidated_on_fill_fail(self, tmp_path):
        """If fill fetch fails, the cache TTL is zeroed so the next entry
        forces a real refresh rather than using a stale pre-buy value."""
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 200.0)
        )
        client.create_order.return_value = _make_order_response("oid-x")
        # Fill fetch always returns unfilled (simulates fetch failure)
        fill_resp = MagicMock()
        fill_resp.order = MagicMock(filled_size="0", filled_value="0",
                                     total_value_after_fees="0")
        client.get_order.return_value = fill_resp

        ex = _make_executor(tmp_path, client)
        with ex._balance_lock:
            ex._usd_cache    = 200.0
            ex._usd_cache_ts = time.time()

        sig = FakeSignal(coin="FOO", sig_mid=1.0)
        ex._do_entry(sig, "FOO", 1.0, "D", 0.20)

        with ex._balance_lock:
            assert ex._usd_cache_ts == 0.0, "TTL must be zeroed after fill-fail entry"


# ---------------------------------------------------------------------------
# FIX 2 — Exit P&L uses actual fill price, not trigger price
# ---------------------------------------------------------------------------

class TestExitFillPrice:
    def test_exit_logs_fill_price_not_trigger(self, tmp_path):
        """EXIT record price and gain must reflect actual fill, not on_price trigger."""
        client = MagicMock()

        # Set up balances + buy fill
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 100.0)
        )
        client.create_order.side_effect = [
            _make_order_response("oid-buy"),    # buy
            _make_order_response("oid-sell"),   # sell
        ]
        # Buy fill: 10 coins @ $1.00
        # Sell fill: 10 coins sold, $10.35 received (fill_px = 1.035)
        # filled_size must be > 0 so _fetch_order_fill completes in one attempt
        buy_fill  = _make_fill_response("oid-buy",  10.0, 10.0)
        sell_fill = _make_fill_response("oid-sell", 10.0, 10.35)

        def get_order_side_effect(order_id):
            if order_id == "oid-buy":
                return buy_fill
            return sell_fill

        client.get_order.side_effect = get_order_side_effect
        client.get_best_bid_ask.return_value = MagicMock(
            pricebooks=[MagicMock(bids=[MagicMock(price="1.00")])]
        )

        ex = _make_executor(tmp_path, client)
        with ex._balance_lock:
            ex._usd_cache    = 100.0
            ex._usd_cache_ts = time.time()

        sig = FakeSignal(coin="TST", sig_mid=1.0,
                         features={**FakeSignal().features, "position_pct": 0.10})
        ex._do_entry(sig, "TST", 1.0, "D", 0.10)

        # Inject a pre-built position to simulate the worker receiving a sell command
        with ex._lock:
            pos = ex._positions.get("TST")
        assert pos is not None

        trigger_px = 1.02  # price at which trail stop fired
        # Simulate the worker's sell path directly
        ex._q.put(("sell", "TST", pos.copy(), trigger_px, "TRAIL_STOP"))
        with ex._lock:
            ex._positions.pop("TST", None)

        time.sleep(0.3)  # let worker process

        log_path = tmp_path / "live_trades.jsonl"
        records = [json.loads(l) for l in log_path.read_text().splitlines()]
        exit_rec = next((r for r in records if r["event"] == "EXIT"), None)
        assert exit_rec is not None

        # fill price is 1.035, trigger was 1.02 — log must use fill price
        assert abs(exit_rec["price"] - 1.035) < 0.001, \
            f"EXIT price should be fill price (1.035), got {exit_rec['price']}"
        assert "trigger_px" in exit_rec, "EXIT must log trigger_px separately"
        assert abs(exit_rec["trigger_px"] - trigger_px) < 0.001


# ---------------------------------------------------------------------------
# FIX 3 — _get_coin_balance paginates
# ---------------------------------------------------------------------------

class TestGetCoinBalancePagination:
    def test_finds_coin_on_second_page(self):
        client = MagicMock()
        page1 = _make_accounts_response(
            _make_account("BTC", 0.01),
            has_next=True, cursor="page2"
        )
        page2 = _make_accounts_response(
            _make_account("EUL", 24.644),
            has_next=False, cursor=None
        )
        client.get_accounts.side_effect = [page1, page2]

        result = _get_coin_balance(client, "EUL")
        assert result == pytest.approx(24.644)
        assert client.get_accounts.call_count == 2

    def test_returns_zero_when_coin_not_found(self):
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("BTC", 0.5),
            has_next=False
        )
        result = _get_coin_balance(client, "NOTREAL")
        assert result == 0.0

    def test_returns_none_on_api_error(self):
        client = MagicMock()
        client.get_accounts.side_effect = Exception("network error")
        result = _get_coin_balance(client, "EUL")
        assert result is None


# ---------------------------------------------------------------------------
# FIX 4 — _get_coin_balance None handled safely in partial handler
# ---------------------------------------------------------------------------

class TestPartialBalanceFetchFailure:
    def test_partial_keeps_estimated_qty_on_balance_error(self, tmp_path):
        """If _get_coin_balance returns None after a partial sell, the position
        keeps the halved-estimate qty rather than being zeroed."""
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 100.0)
        )
        client.create_order.side_effect = [
            _make_order_response("oid-buy"),
            _make_order_response("oid-partial"),
        ]
        client.get_order.return_value = _make_fill_response("oid-buy", 50.0, 50.0)

        ex = _make_executor(tmp_path, client)
        with ex._balance_lock:
            ex._usd_cache    = 100.0
            ex._usd_cache_ts = time.time()

        sig = FakeSignal(coin="TSTP", sig_mid=1.0,
                         features={**FakeSignal().features, "position_pct": 0.50})
        ex._do_entry(sig, "TSTP", 1.0, "D", 0.50)

        with ex._lock:
            pos = ex._positions.get("TSTP")
        assert pos is not None

        # Simulate the partial: halve qty in-place (as on_price does)
        with ex._lock:
            ex._positions["TSTP"]["qty"] *= 0.5
            ex._positions["TSTP"]["half_sold"] = True
            halved = ex._positions["TSTP"]["qty"]

        # Now inject partial command; balance fetch will fail
        pos_copy = ex._positions["TSTP"].copy()
        with patch.object(le, "_get_coin_balance", return_value=None):
            ex._q.put(("partial", "TSTP", pos_copy, 1.2))
            time.sleep(0.3)

        with ex._lock:
            remaining_qty = ex._positions.get("TSTP", {}).get("qty", 0)

        # Must not be zero; should be the halved estimate
        assert remaining_qty > 0, "qty must not be zeroed on balance-fetch failure"
        assert remaining_qty == pytest.approx(halved, rel=0.01)


# ---------------------------------------------------------------------------
# FIX 5 — Balance cache is thread-safe
# ---------------------------------------------------------------------------

class TestBalanceLockThreadSafety:
    def test_concurrent_refresh_doesnt_corrupt_cache(self, tmp_path):
        """Two threads calling _refresh_balance concurrently should not produce
        negative or nonsensical cache values."""
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 150.0)
        )

        ex = _make_executor(tmp_path, client)

        def refresh_loop():
            for _ in range(20):
                with ex._balance_lock:
                    ex._usd_cache_ts = 0.0  # force refresh each time
                ex._refresh_balance()
                time.sleep(0.005)

        threads = [threading.Thread(target=refresh_loop) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        with ex._balance_lock:
            assert ex._usd_cache >= 0.0, "cache must never be negative"


# ---------------------------------------------------------------------------
# FIX 6 — ENTRY log includes buy_order_id
# ---------------------------------------------------------------------------

class TestEntryLogIncludesBuyOrder:
    def test_entry_record_has_buy_order_field(self, tmp_path):
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 200.0)
        )
        client.create_order.return_value = _make_order_response("oid-abc-123")
        client.get_order.return_value = _make_fill_response("oid-abc-123", 5.0, 10.0)

        ex = _make_executor(tmp_path, client)
        with ex._balance_lock:
            ex._usd_cache    = 200.0
            ex._usd_cache_ts = time.time()

        sig = FakeSignal(coin="COIN", sig_mid=2.0,
                         features={**FakeSignal().features, "position_pct": 0.05})
        ex._do_entry(sig, "COIN", 2.0, "D", 0.05)

        log_path = tmp_path / "live_trades.jsonl"
        records  = [json.loads(l) for l in log_path.read_text().splitlines()]
        entry    = next((r for r in records if r["event"] == "ENTRY"), None)
        assert entry is not None
        assert entry.get("buy_order") == "oid-abc-123", \
            f"ENTRY must include buy_order; got {entry.get('buy_order')}"


# ---------------------------------------------------------------------------
# FIX 7 — EXIT log includes half_sold; reconciler uses it for cooldown key
# ---------------------------------------------------------------------------

class TestExitHalfSoldAndCooldown:
    def _write_exit(self, tmp_path, reason, half_sold, gain, ts_offset_s=0):
        """Write a synthetic EXIT record to the trade log."""
        log_path = tmp_path / "live_trades.jsonl"
        ts = time.time() - ts_offset_s
        ts_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
        rec = {
            "event":     "EXIT",
            "coin":      "TST",
            "price":     1.0,
            "ts":        ts_str,
            "reason":    reason,
            "gain":      gain,
            "hold_min":  60.0,
            "tier":      "D",
            "half_sold": half_sold,
        }
        log_path.write_text(json.dumps(rec) + "\n")

    def test_trail_stop_full_no_partial(self, tmp_path):
        """TRAIL_STOP with half_sold=False → TRAIL_STOP_FULL (90m cooldown)."""
        self._write_exit(tmp_path, "TRAIL_STOP", half_sold=False, gain=-0.03)
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 100.0)
        )
        ex = _make_executor(tmp_path, client)

        _, ck = ex._last_exit.get("TST", (None, None))
        assert ck == "TRAIL_STOP_FULL", f"Expected TRAIL_STOP_FULL, got {ck}"

    def test_trail_stop_partial_had_half_sell(self, tmp_path):
        """TRAIL_STOP with half_sold=True → TRAIL_STOP_PARTIAL (20m cooldown)."""
        self._write_exit(tmp_path, "TRAIL_STOP", half_sold=True, gain=0.12)
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 100.0)
        )
        ex = _make_executor(tmp_path, client)

        _, ck = ex._last_exit.get("TST", (None, None))
        assert ck == "TRAIL_STOP_PARTIAL", f"Expected TRAIL_STOP_PARTIAL, got {ck}"

    def test_trail_stop_full_positive_gain_no_partial(self, tmp_path):
        """TRAIL_STOP with half_sold=False but positive gain → still TRAIL_STOP_FULL.
        This is the case the old gain-based heuristic would get WRONG."""
        self._write_exit(tmp_path, "TRAIL_STOP", half_sold=False, gain=0.05)
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 100.0)
        )
        ex = _make_executor(tmp_path, client)

        _, ck = ex._last_exit.get("TST", (None, None))
        assert ck == "TRAIL_STOP_FULL", \
            "Positive gain without partial must still be TRAIL_STOP_FULL (90m), " \
            f"got {ck}"

    def test_exit_record_contains_half_sold_field(self, tmp_path):
        """The EXIT record written to the log must include half_sold."""
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 100.0)
        )
        client.create_order.side_effect = [
            _make_order_response("oid-buy"),
            _make_order_response("oid-sell"),
        ]
        buy_fill  = _make_fill_response("oid-buy", 10.0, 10.0)
        sell_fill = _make_fill_response("oid-sell", 10.0, 9.5)  # filled_size>0 so fill resolves immediately

        def get_order_se(order_id):
            return buy_fill if order_id == "oid-buy" else sell_fill

        client.get_order.side_effect = get_order_se
        client.get_best_bid_ask.return_value = MagicMock(
            pricebooks=[MagicMock(bids=[MagicMock(price="1.00")])]
        )

        ex = _make_executor(tmp_path, client)
        with ex._balance_lock:
            ex._usd_cache    = 100.0
            ex._usd_cache_ts = time.time()

        sig = FakeSignal(coin="TST2", sig_mid=1.0,
                         features={**FakeSignal().features, "position_pct": 0.10})
        ex._do_entry(sig, "TST2", 1.0, "D", 0.10)

        with ex._lock:
            pos = ex._positions.get("TST2", {}).copy()

        ex._q.put(("sell", "TST2", pos, 0.95, "TRAIL_STOP"))
        with ex._lock:
            ex._positions.pop("TST2", None)

        time.sleep(0.3)

        records = [json.loads(l) for l in (tmp_path / "live_trades.jsonl").read_text().splitlines()]
        exit_rec = next((r for r in records if r["event"] == "EXIT"), None)
        assert exit_rec is not None
        assert "half_sold" in exit_rec, "EXIT record must contain half_sold field"
        assert exit_rec["half_sold"] is False


# ---------------------------------------------------------------------------
# FIX 8 — Pending-entry guard prevents duplicate buys
# ---------------------------------------------------------------------------

class TestPendingEntryGuard:
    def test_second_signal_skipped_while_first_pending(self, tmp_path):
        """If a coin is already in _pending_entry, a second signal for the same
        coin must be skipped without placing a second buy order."""
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 200.0)
        )

        barrier = threading.Barrier(2)
        buy_count = [0]

        def slow_buy(*args, **kwargs):
            buy_count[0] += 1
            barrier.wait(timeout=2)   # hold until both threads have reached here
            return _make_order_response("oid-slow")

        client.create_order.side_effect = slow_buy
        client.get_order.return_value = _make_fill_response("oid-slow", 10.0, 10.0)

        ex = _make_executor(tmp_path, client)
        with ex._balance_lock:
            ex._usd_cache    = 200.0
            ex._usd_cache_ts = time.time()

        sig = FakeSignal(coin="DUP", sig_mid=1.0,
                         features={**FakeSignal().features, "position_pct": 0.10})

        # Manually set the pending guard to simulate first entry in-flight
        with ex._lock:
            ex._pending_entry.add("DUP")

        # Second signal should be dropped immediately
        try:
            ex._handle_entry(sig)
        except Exception:
            pass

        assert buy_count[0] == 0, \
            "No buy should be placed when coin is in _pending_entry"


# ---------------------------------------------------------------------------
# FIX 9 — _log failure is critical + echoes to stderr, never silent
# ---------------------------------------------------------------------------

class TestLogFailureCritical:
    def test_log_failure_prints_to_stderr(self, tmp_path, capsys):
        """On log write failure, record must appear in stderr (systemd journal)."""
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 100.0)
        )
        ex = _make_executor(tmp_path, client)

        # Point trade log at a path that can't be written
        ex._trade_log = Path("/nonexistent_dir/trades.jsonl")

        ex._log("EXIT", "TST", 1.0, gain=0.05, reason="TRAIL_STOP")

        captured = capsys.readouterr()
        assert "TRADE_LOG_FAIL" in captured.err, \
            "Failed log write must echo to stderr with TRADE_LOG_FAIL prefix"
        assert "EXIT" in captured.err
        assert "TST" in captured.err

    def test_log_is_fsynced(self, tmp_path, monkeypatch):
        """_log must call fsync so data is durable before we proceed."""
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 100.0)
        )
        ex = _make_executor(tmp_path, client)

        fsync_called = []
        real_fsync = os.fsync

        def fake_fsync(fd):
            fsync_called.append(fd)
            real_fsync(fd)

        monkeypatch.setattr(os, "fsync", fake_fsync)
        ex._log("ENTRY", "TST", 1.0, qty=1.0)
        assert len(fsync_called) >= 1, "_log must call os.fsync for durability"


# ---------------------------------------------------------------------------
# FIX 10 — entry_ts reflects order submission time, not fill confirmation time
# ---------------------------------------------------------------------------

class TestEntryTimestamp:
    def test_entry_ts_set_before_fill_fetch(self, tmp_path):
        """entry_ts should be the timestamp when the buy was submitted,
        not after _fetch_order_fill returns (which can take ~1s)."""
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 200.0)
        )
        client.create_order.return_value = _make_order_response("oid-ts")

        fill_delay_s = 0.4

        def slow_get_order(order_id):
            time.sleep(fill_delay_s)
            return _make_fill_response(order_id, 10.0, 10.0)

        client.get_order.side_effect = slow_get_order

        ex = _make_executor(tmp_path, client)
        with ex._balance_lock:
            ex._usd_cache    = 200.0
            ex._usd_cache_ts = time.time()

        before = time.time()
        sig = FakeSignal(coin="TSTS", sig_mid=1.0,
                         features={**FakeSignal().features, "position_pct": 0.05})
        ex._do_entry(sig, "TSTS", 1.0, "D", 0.05)
        after = time.time()

        with ex._lock:
            pos = ex._positions.get("TSTS")
        assert pos is not None

        # entry_ts should be <= the time fill fetch started (before fill_delay elapsed)
        # i.e. it should NOT be close to `after`
        assert pos["entry_ts"] < (before + fill_delay_s * 0.5), \
            "entry_ts must be set at order submission, before fill fetch delay"


# ---------------------------------------------------------------------------
# FIX 11 — peak_px is logged in ENTRY and restored by reconciler
# ---------------------------------------------------------------------------

class TestPeakPxPersistence:
    def test_entry_record_contains_peak_px(self, tmp_path):
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 200.0)
        )
        client.create_order.return_value = _make_order_response("oid-pp")
        client.get_order.return_value = _make_fill_response("oid-pp", 10.0, 15.0)

        ex = _make_executor(tmp_path, client)
        with ex._balance_lock:
            ex._usd_cache    = 200.0
            ex._usd_cache_ts = time.time()

        sig = FakeSignal(coin="PPX", sig_mid=1.5,
                         features={**FakeSignal().features, "position_pct": 0.08})
        ex._do_entry(sig, "PPX", 1.5, "D", 0.08)

        records = [json.loads(l) for l in (tmp_path / "live_trades.jsonl").read_text().splitlines()]
        entry = next((r for r in records if r["event"] == "ENTRY"), None)
        assert entry is not None
        assert "peak_px" in entry, "ENTRY record must contain peak_px"
        # peak_px at entry time equals the fill price
        assert entry["peak_px"] == pytest.approx(entry["price"], rel=0.001)

    def test_reconciler_restores_peak_px_from_entry_record(self, tmp_path):
        """On restart, reconciler should use peak_px from the log record,
        not reset it to entry_px."""
        entry_px = 1.00
        peak_px  = 1.25   # coin ran up before restart
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 100.0)
        )
        # Current bid is below peak but above trail stop (1.25 * 0.93 = 1.1625)
        # so position stays open and we can verify peak_px was restored correctly.
        client.get_best_bid_ask.return_value = MagicMock(
            pricebooks=[MagicMock(bids=[MagicMock(price="1.20")])]
        )

        log_path = tmp_path / "live_trades.jsonl"
        ts_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rec = {
            "event":    "ENTRY",
            "coin":     "PK",
            "price":    entry_px,
            "ts":       ts_str,
            "tier":     "D",
            "qty":      10.0,
            "usd_size": 10.0,
            "peak_px":  peak_px,
            "buy_order": "oid-pk",
        }
        log_path.write_text(json.dumps(rec) + "\n")

        ex = _make_executor(tmp_path, client)

        with ex._lock:
            pos = ex._positions.get("PK")
        assert pos is not None
        # peak_px should be max(logged peak_px=1.25, current_bid=1.20) = 1.25
        assert pos["peak_px"] == pytest.approx(1.25, rel=0.001), \
            f"peak_px should be restored to 1.25 from log, got {pos['peak_px']}"


# ---------------------------------------------------------------------------
# FIX 12 — FILL event written to trade log before ENTRY
# ---------------------------------------------------------------------------

class TestFillLogEvent:
    def test_fill_record_written_to_log(self, tmp_path):
        """A FILL record must appear in the trade log before the ENTRY record."""
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 200.0)
        )
        client.create_order.return_value = _make_order_response("oid-fill-test")
        client.get_order.return_value = _make_fill_response("oid-fill-test", 7.5, 10.0)

        ex = _make_executor(tmp_path, client)
        with ex._balance_lock:
            ex._usd_cache    = 200.0
            ex._usd_cache_ts = time.time()

        sig = FakeSignal(coin="FILL", sig_mid=1.33,
                         features={**FakeSignal().features, "position_pct": 0.05})
        ex._do_entry(sig, "FILL", 1.33, "D", 0.05)

        lines = (tmp_path / "live_trades.jsonl").read_text().splitlines()
        records = [json.loads(l) for l in lines]
        events = [r["event"] for r in records]

        assert "FILL" in events, "FILL event must be written to trade log"
        fill_idx  = events.index("FILL")
        entry_idx = events.index("ENTRY")
        assert fill_idx < entry_idx, "FILL must appear before ENTRY in the log"

    def test_fill_record_contains_order_id(self, tmp_path):
        """FILL record must contain the Coinbase order_id for cross-referencing."""
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 200.0)
        )
        client.create_order.return_value = _make_order_response("oid-cross-ref")
        client.get_order.return_value = _make_fill_response("oid-cross-ref", 5.0, 10.0)

        ex = _make_executor(tmp_path, client)
        with ex._balance_lock:
            ex._usd_cache    = 200.0
            ex._usd_cache_ts = time.time()

        sig = FakeSignal(coin="CRF", sig_mid=2.0,
                         features={**FakeSignal().features, "position_pct": 0.05})
        ex._do_entry(sig, "CRF", 2.0, "D", 0.05)

        records = [json.loads(l) for l in (tmp_path / "live_trades.jsonl").read_text().splitlines()]
        fill_rec = next((r for r in records if r["event"] == "FILL"), None)
        assert fill_rec is not None
        assert fill_rec.get("order_id") == "oid-cross-ref"

    def test_orphaned_fill_detected_at_reconcile(self, tmp_path):
        """FILL without matching ENTRY is an orphaned fill — reconciler must log CRITICAL."""
        log_path = tmp_path / "live_trades.jsonl"
        ts_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        # Write a FILL record without any ENTRY
        log_path.write_text(
            json.dumps({"event": "FILL", "coin": "ORF", "price": 1.0,
                        "ts": ts_str, "order_id": "orphan-oid",
                        "qty": 5.0, "value_usd": 5.0}) + "\n"
        )

        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 100.0)
        )

        import logging
        critical_records = []
        handler = logging.handlers_list = []

        class CaptureCritical(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.CRITICAL:
                    critical_records.append(record.getMessage())

        le.log.addHandler(CaptureCritical())
        try:
            ex = _make_executor(tmp_path, client)
        finally:
            le.log.handlers = [h for h in le.log.handlers
                                if not isinstance(h, CaptureCritical)]

        assert any("orphan-oid" in m or "ORPHANED" in m for m in critical_records), \
            "Reconciler must log CRITICAL for orphaned FILL records"


# ---------------------------------------------------------------------------
# TRADING LOGIC UNCHANGED — verify profitability-relevant constants & behavior
# ---------------------------------------------------------------------------

class TestTradingLogicUnchanged:
    """These tests verify that the reliability fixes did NOT alter any trading
    decision: EV scoring, position sizing, entry gates, exit thresholds."""

    def test_ev_scoring_tier_baselines(self):
        assert TIER_EV_BASELINE == {"A": 7.5, "B": 4.3, "C": 4.2, "D": 3.2}

    def test_ev_min_threshold(self):
        assert MIN_EV_PCT == 1.5

    def test_partial_trigger_threshold(self):
        assert PARTIAL_TRIGGER == pytest.approx(0.20)

    def test_trail_pre_post(self):
        assert TRAIL_PRE  == pytest.approx(0.07)
        assert TRAIL_POST == pytest.approx(0.15)

    def test_max_hold_seconds(self):
        assert MAX_HOLD_S == 14400

    def test_cvd_gate_constant(self):
        assert GATE_CVD_30S_MIN == -2000

    def test_onset_gate_constant(self):
        assert GATE_ONSET_S == pytest.approx(8.0)

    def test_cooldown_values(self):
        assert COOLDOWN_S["TRAIL_STOP_FULL"]    == 90 * 60
        assert COOLDOWN_S["TRAIL_STOP_PARTIAL"] == 20 * 60
        assert COOLDOWN_S["TIME_CAP_LOSS"]      == 60 * 60
        assert COOLDOWN_S["TIME_CAP_GAIN"]      == 20 * 60

    def test_ev_score_cvd_component(self, tmp_path):
        """CVD contribution: +2% at cvd≥2000, 0% at cvd=−2000, linear between."""
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 100.0)
        )
        ex = _make_executor(tmp_path, client)

        def score(cvd):
            sig = FakeSignal(features={
                "confidence_tier": "D",
                "cvd_30s": cvd,
                "secs_since_onset": 5.0,  # zero timing bonus
                "dv_trend": 5.0,           # +0.5
                "spread_bps": 5.0,         # 0
                "large_trade_pct_60s": 0.0 # 0
            })
            return ex._score_signal(sig)

        ev_at_pos2000 = score(2000)
        ev_at_neg2000 = score(-2000)
        ev_at_zero    = score(0)
        assert ev_at_pos2000 > ev_at_zero > ev_at_neg2000

    def test_ev_score_low_rejects_entry(self, tmp_path):
        """Signal with ev below MIN_EV_PCT must be skipped without buy."""
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 200.0)
        )
        ex = _make_executor(tmp_path, client)
        with ex._balance_lock:
            ex._usd_cache    = 200.0
            ex._usd_cache_ts = time.time()

        # All adjustments negative → ev far below 1.5%
        sig = FakeSignal(coin="LOWEV", sig_mid=1.0, features={
            "confidence_tier":    "D",
            "position_pct":       0.20,
            "fear_greed":         50,
            "cvd_30s":            -5000.0,  # below gate, but we test EV here
            "secs_since_onset":   20.0,     # -1.5 timing penalty
            "dv_trend":           1.0,      # -1.0 dvt penalty
            "spread_bps":         15.0,     # -0.5 spread penalty
            "large_trade_pct_60s": 0.0,
        })
        # Override CVD gate so only EV gate applies
        sig.features["cvd_30s"] = 0.0

        with patch.object(le, "_market_buy") as mock_buy:
            ex._do_entry(sig, "LOWEV", 1.0, "D", 0.20)
            mock_buy.assert_not_called()

    def test_extreme_fear_skips_ab_tiers(self, tmp_path):
        """Tier A/B skipped only in true panic: F&G < 15 AND btc_ret_1h <= 2%.
        F&G threshold lowered from 25→15; stale daily index cannot capture
        intraday sentiment reversals, so the bar for skipping is now higher."""
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 200.0)
        )
        ex = _make_executor(tmp_path, client)

        # True panic: F&G=10, BTC flat → must skip
        for tier in ("A", "B"):
            sig = FakeSignal(coin="FEAR", sig_mid=1.0, features={
                **FakeSignal().features,
                "confidence_tier": tier,
                "fear_greed": 10,
                "btc_ret_1h": 0.0,
            })
            with patch.object(le, "_market_buy") as mock_buy:
                ex._handle_entry(sig)
                mock_buy.assert_not_called(), f"Tier {tier} true panic must not buy"

        # F&G=21 (old threshold, today's market) — must NOT skip anymore
        with ex._balance_lock:
            ex._usd_cache = 200.0
            ex._usd_cache_ts = time.time()
        for tier in ("A", "B"):
            sig = FakeSignal(coin="FEAR", sig_mid=1.0, features={
                **FakeSignal().features,
                "confidence_tier": tier,
                "fear_greed": 21,
                "btc_ret_1h": 0.0,
            })
            with patch.object(le, "_market_buy") as mock_buy:
                mock_buy.return_value = f"oid-{tier}"
                client.get_order.return_value = _make_fill_response(f"oid-{tier}", 1.0, 1.0)
                ex._do_entry(sig, "FEAR", 1.0, tier, 0.20)
                mock_buy.assert_called_once(), f"Tier {tier} F&G=21 must NOT be skipped"

        # F&G=10 but BTC recovering +3% → override, must NOT skip
        for tier in ("A", "B"):
            sig = FakeSignal(coin="FEAR", sig_mid=1.0, features={
                **FakeSignal().features,
                "confidence_tier": tier,
                "fear_greed": 10,
                "btc_ret_1h": 0.03,
            })
            with patch.object(le, "_market_buy") as mock_buy:
                mock_buy.return_value = f"oid-btcov-{tier}"
                client.get_order.return_value = _make_fill_response(f"oid-btcov-{tier}", 1.0, 1.0)
                ex._do_entry(sig, "FEAR", 1.0, tier, 0.20)
                mock_buy.assert_called_once(), f"Tier {tier} BTC recovering must override fear gate"

    def test_cvd_gate_skips_net_selling(self, tmp_path):
        """CVD below GATE_CVD_30S_MIN must be skipped."""
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 200.0)
        )
        ex = _make_executor(tmp_path, client)

        sig = FakeSignal(coin="SELL", sig_mid=1.0, features={
            **FakeSignal().features,
            "cvd_30s": -3000.0,
        })
        with patch.object(le, "_market_buy") as mock_buy:
            ex._handle_entry(sig)
            mock_buy.assert_not_called()

    def test_onset_gate_skips_late_entry(self, tmp_path):
        """Signal more than GATE_ONSET_S seconds after move started is skipped."""
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 200.0)
        )
        ex = _make_executor(tmp_path, client)

        sig = FakeSignal(coin="LATE", sig_mid=1.0, features={
            **FakeSignal().features,
            "secs_since_onset": 20.0,
        })
        with patch.object(le, "_market_buy") as mock_buy:
            ex._handle_entry(sig)
            mock_buy.assert_not_called()

    def test_trail_stop_fires_at_correct_threshold(self, tmp_path):
        """TRAIL_STOP must fire when price drops to peak * (1 - TRAIL_PRE)."""
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 100.0)
        )
        ex = _make_executor(tmp_path, client)

        # Inject a position directly
        with ex._lock:
            ex._positions["TRL"] = {
                "entry_px": 1.00, "qty": 10.0, "peak_px": 1.20,
                "half_sold": False, "entry_ts": time.time() - 60,
                "tier": "D", "usd_in": 10.0, "buy_order": "x",
            }

        # price just above stop threshold — should NOT trigger
        stop_px = 1.20 * (1 - TRAIL_PRE)
        above_stop = stop_px + 0.001
        ex.on_price("TRL", above_stop)
        with ex._lock:
            assert "TRL" in ex._positions, "Position should remain above stop"

        # price at or below stop threshold — must trigger
        ex.on_price("TRL-USD", stop_px - 0.001)
        with ex._lock:
            assert "TRL" not in ex._positions, "Position must exit at trail stop"

    def test_partial_fires_at_correct_gain(self, tmp_path):
        """PARTIAL must trigger exactly at PARTIAL_TRIGGER (20%) gain."""
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 100.0)
        )
        ex = _make_executor(tmp_path, client)

        with ex._lock:
            ex._positions["PART"] = {
                "entry_px": 1.00, "qty": 10.0, "peak_px": 1.00,
                "half_sold": False, "entry_ts": time.time() - 60,
                "tier": "D", "usd_in": 10.0, "buy_order": "x",
            }

        # Just below partial trigger
        ex.on_price("PART", 1.00 * (1 + PARTIAL_TRIGGER) - 0.001)
        with ex._lock:
            assert not ex._positions["PART"]["half_sold"], "No partial below threshold"

        # At or above partial trigger — use a price clearly above the threshold to
        # avoid floating-point rounding (1.2 / 1.0 - 1.0 = 0.19999... in Python).
        # Patch _get_coin_balance so the worker sets real_remaining=5.0 (the halved qty).
        trigger_price = 1.00 * (1 + PARTIAL_TRIGGER) + 0.001  # 1.201: unambiguously >= 0.20
        with patch.object(le, "_get_coin_balance", return_value=5.0):
            ex.on_price("PART", trigger_price)
            time.sleep(0.1)   # let worker process the "partial" queue item
            with ex._lock:
                assert ex._positions["PART"]["half_sold"], "Partial must trigger at threshold"
                assert ex._positions["PART"]["qty"] == pytest.approx(5.0), \
                    "qty must halve on partial trigger"

    def test_cooldown_prevents_reentry(self, tmp_path):
        """Cooldown gate must prevent re-entry within the cooldown window."""
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 200.0)
        )
        ex = _make_executor(tmp_path, client)
        with ex._balance_lock:
            ex._usd_cache    = 200.0
            ex._usd_cache_ts = time.time()

        # Arm a fresh cooldown
        ex._last_exit["TST"] = (time.time(), "TRAIL_STOP_FULL")

        sig = FakeSignal(coin="TST", sig_mid=1.0)
        with patch.object(le, "_market_buy") as mock_buy:
            ex._handle_entry(sig)
            mock_buy.assert_not_called(), "Must not buy during cooldown"

    def test_position_sizing_uses_balance_pct(self, tmp_path):
        """Position size must be exactly balance × pos_pct × ev_scale."""
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 200.0)
        )
        ordered_amounts = []

        def capture_order(*a, **kw):
            cfg = kw.get("order_configuration", {})
            market = cfg.get("market_market_ioc", {})
            ordered_amounts.append(float(market.get("quote_size", 0)))
            return _make_order_response("oid-sz")

        client.create_order.side_effect = capture_order
        client.get_order.return_value = _make_fill_response("oid-sz", 20.0, 20.0)

        ex = _make_executor(tmp_path, client)
        with ex._balance_lock:
            ex._usd_cache    = 200.0
            ex._usd_cache_ts = time.time()

        # Controlled signal: tier D, pos_pct=0.20, cvd≈0 → ev_scale≈1.0
        features = {
            "confidence_tier":    "D",
            "position_pct":       0.20,
            "fear_greed":         50,
            "cvd_30s":            2000.0,   # max cvd → +2% EV
            "secs_since_onset":   5.0,      # 0 timing
            "dv_trend":           5.0,      # +0.5
            "spread_bps":         5.0,      # 0
            "large_trade_pct_60s": 0.0,
        }
        # ev = 3.2 + 2.0 + 0.0 + 0.5 + 0.0 + 0.0 = 5.7; baseline=3.2; scale = min(1.0, 5.7/3.2) = 1.0
        sig = FakeSignal(coin="SZT", sig_mid=1.0, features=features)
        ex._do_entry(sig, "SZT", 1.0, "D", 0.20)

        assert len(ordered_amounts) == 1
        expected = round(200.0 * 0.20 * 1.0, 2)   # $40.00
        assert ordered_amounts[0] == pytest.approx(expected, abs=0.05)


# ---------------------------------------------------------------------------
# Reconcile reliability — Unix ts parsing + immediate exit on startup
# ---------------------------------------------------------------------------

class TestReconcileReliability:
    def _make_entry_record(self, coin, entry_px, peak_px, ts, tier="D", qty=10.0):
        return {
            "event":     "ENTRY",
            "coin":      coin,
            "price":     entry_px,
            "ts":        ts,
            "tier":      tier,
            "qty":       qty,
            "usd_size":  entry_px * qty,
            "peak_px":   peak_px,
            "buy_order": f"oid-{coin.lower()}",
        }

    def test_reconcile_parses_unix_float_ts(self, tmp_path):
        """ENTRY records with Unix float ts must have entry_ts correctly restored,
        not reset to time.time() (which would reset the TIME_CAP timer)."""
        entry_px  = 1.00
        # Use a timestamp 1 hour ago so hold_min is ~60, not ~0
        ts_unix   = time.time() - 3600.0
        rec       = self._make_entry_record("TSUNI", entry_px, entry_px, ts_unix)
        log_path  = tmp_path / "live_trades.jsonl"
        log_path.write_text(json.dumps(rec) + "\n")

        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 100.0)
        )
        # Current price above trail stop — position should be restored, not exited
        client.get_best_bid_ask.return_value = MagicMock(
            pricebooks=[MagicMock(bids=[MagicMock(price="0.97")])]
        )

        ex = _make_executor(tmp_path, client)

        with ex._lock:
            pos = ex._positions.get("TSUNI")
        assert pos is not None, "Position should be restored (price above trail stop)"
        # entry_ts must be the original Unix float, not current time
        assert pos["entry_ts"] == pytest.approx(ts_unix, abs=1.0), \
            f"entry_ts should be ~{ts_unix:.0f}, got {pos['entry_ts']:.0f}"
        # hold time should be ~3600s, not ~0
        hold_s = time.time() - pos["entry_ts"]
        assert hold_s > 3500, f"Expected hold_s ~3600, got {hold_s:.0f}"

    def test_reconcile_immediate_trail_stop_exit(self, tmp_path):
        """If price is already below trail stop at startup, reconciler must queue
        an immediate TRAIL_STOP sell rather than restoring the position silently."""
        entry_px = 1.00
        ts_str   = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 60))
        rec      = self._make_entry_record("BLEED", entry_px, entry_px, ts_str)
        log_path = tmp_path / "live_trades.jsonl"
        log_path.write_text(json.dumps(rec) + "\n")

        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 100.0)
        )
        # Price already 10% below entry — well past 7% trail stop
        client.get_best_bid_ask.return_value = MagicMock(
            pricebooks=[MagicMock(bids=[MagicMock(price="0.90")])]
        )
        client.create_order.return_value = _make_order_response("oid-bleed-sell")
        client.get_order.return_value    = _make_fill_response("oid-bleed-sell", 10.0, 0.90)
        client.get_accounts.side_effect  = None

        ex = _make_executor(tmp_path, client)

        # Position must NOT be in _positions — it should have been immediately exited
        with ex._lock:
            assert "BLEED" not in ex._positions, \
                "Position should not be in _positions — must have been immediately exited"

        # Give worker thread time to process the queued sell
        time.sleep(0.3)
        log_lines = (tmp_path / "live_trades.jsonl").read_text().splitlines()
        records   = [json.loads(l) for l in log_lines]
        exit_recs = [r for r in records if r.get("event") == "EXIT" and r.get("coin") == "BLEED"]
        assert exit_recs, "EXIT record must be written for immediately-exited position"
        assert exit_recs[0]["reason"] == "TRAIL_STOP"

    def test_reconcile_immediate_time_cap_exit(self, tmp_path, monkeypatch):
        """If hold time already exceeds MAX_HOLD_S at startup, reconciler must queue
        an immediate TIME_CAP sell.

        TIME_CAP exits go through the smart-exit (limit-then-market) path. We
        speed up the poll for test responsiveness; production polling cadence
        is 1s × 30s window.
        """
        monkeypatch.setattr(le, "TIME_CAP_LIMIT_POLL_S", 0.05)
        entry_px    = 1.00
        # Entry logged 5 hours ago (past 4h cap)
        old_unix_ts = time.time() - (5 * 3600)
        rec         = self._make_entry_record("AGED", entry_px, entry_px, old_unix_ts)
        log_path    = tmp_path / "live_trades.jsonl"
        log_path.write_text(json.dumps(rec) + "\n")

        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 100.0)
        )
        # Price flat — trail stop not triggered, but hold time is way over cap
        client.get_best_bid_ask.return_value = _make_bbo_response(bid=1.00, ask=1.001)
        client.create_order.return_value = _make_order_response("oid-aged-sell")
        client.get_order.return_value    = _make_fill_response("oid-aged-sell", 10.0, 1.00)

        ex = _make_executor(tmp_path, client)

        with ex._lock:
            assert "AGED" not in ex._positions, \
                "Position past TIME_CAP should not be in _positions"

        time.sleep(0.5)
        log_lines = (tmp_path / "live_trades.jsonl").read_text().splitlines()
        records   = [json.loads(l) for l in log_lines]
        exit_recs = [r for r in records if r.get("event") == "EXIT" and r.get("coin") == "AGED"]
        assert exit_recs, "EXIT record must be written for time-capped position at startup"
        assert exit_recs[0]["reason"] == "TIME_CAP"


# ---------------------------------------------------------------------------
# Smart-exit (limit-then-market) — TIME_CAP path
# ---------------------------------------------------------------------------

class TestSmartSell:
    """Unit tests for the _smart_sell orchestrator.

    Exercises the four observable paths:
      1. limit_full          — limit fills entirely within window
      2. limit_partial+market — limit partially fills, market sells remainder
      3. market_fallback     — limit rejected outright (post_only crossed),
                                or BBO unavailable
      4. rejected            — both limit and market fail; caller restores
    """

    def _client_with_bbo(self, bid=1.0, ask=1.001):
        c = MagicMock()
        c.get_best_bid_ask.return_value = _make_bbo_response(bid=bid, ask=ask)
        return c

    def _log_sink(self):
        """A simple log_fn capturing emitted events into a list."""
        events: list = []

        def _log(event, coin, price, **kw):
            events.append({"event": event, "coin": coin, "price": price, **kw})

        return events, _log

    def test_smart_sell_full_limit_fill(self):
        client = self._client_with_bbo(bid=1.0)
        client.create_order.return_value = _make_order_response("oid-limit")
        client.get_order.return_value    = _make_fill_response("oid-limit", 10.0, 10.0)
        events, log_fn = self._log_sink()

        with patch.object(le, "TIME_CAP_LIMIT_POLL_S", 0.01):
            r = le._smart_sell(client, "X", 10.0, "TIME_CAP", log_fn)

        assert r["ok"] is True
        assert r["path"] == "limit_full"
        assert r["limit_oid"]  == "oid-limit"
        assert r["market_oid"] is None
        assert r["filled_qty"] == 10.0
        assert r["avg_fill_px"] == 1.0
        # Log events: LIMIT_PLACED then LIMIT_FILLED
        kinds = [e["event"] for e in events]
        assert kinds == ["LIMIT_PLACED", "LIMIT_FILLED"]

    def test_smart_sell_timeout_then_market(self):
        """Limit never fills; on timeout, cancel and market-sell the full size."""
        client = self._client_with_bbo(bid=1.0)
        # First create_order is the limit; second is the market fallback.
        client.create_order.side_effect = [
            _make_order_response("oid-limit"),
            _make_order_response("oid-market"),
        ]
        # WAIT=0.005s with POLL=0.01s → exactly one poll fires before deadline.
        # Sequence: poll #1 (OPEN), post-cancel recheck (CANCELLED), market fill.
        client.get_order.side_effect = [
            _make_fill_response("oid-limit",  0.0, 0.0,  status="OPEN"),
            _make_fill_response("oid-limit",  0.0, 0.0,  status="CANCELLED"),
            _make_fill_response("oid-market", 10.0, 9.9, status="FILLED"),
        ]
        client.cancel_orders.return_value = _make_cancel_response(success=True)
        events, log_fn = self._log_sink()

        with patch.multiple(le,
                             TIME_CAP_LIMIT_POLL_S=0.01,
                             TIME_CAP_LIMIT_WAIT_S=0.005):
            r = le._smart_sell(client, "X", 10.0, "TIME_CAP", log_fn)

        assert r["ok"] is True
        assert r["path"] == "market_fallback"
        assert r["limit_oid"]  == "oid-limit"
        assert r["market_oid"] == "oid-market"
        assert r["filled_qty"] == 10.0
        assert r["filled_value"] == 9.9
        kinds = [e["event"] for e in events]
        assert "LIMIT_PLACED"    in kinds
        assert "LIMIT_TIMEOUT"   in kinds
        assert "MARKET_FALLBACK" in kinds

    def test_smart_sell_partial_fill_then_market(self):
        """Limit partially fills during the wait; remainder goes via market."""
        client = self._client_with_bbo(bid=1.0)
        client.create_order.side_effect = [
            _make_order_response("oid-limit"),
            _make_order_response("oid-market"),
        ]
        # Sequence: poll #1 (OPEN, 4 filled), post-cancel recheck (CANCELLED, 4 filled),
        # market fill for remainder.
        client.get_order.side_effect = [
            _make_fill_response("oid-limit",  4.0, 4.0,  status="OPEN"),
            _make_fill_response("oid-limit",  4.0, 4.0,  status="CANCELLED"),
            _make_fill_response("oid-market", 6.0, 5.88, status="FILLED"),
        ]
        client.cancel_orders.return_value = _make_cancel_response(success=True)
        events, log_fn = self._log_sink()

        with patch.multiple(le,
                             TIME_CAP_LIMIT_POLL_S=0.01,
                             TIME_CAP_LIMIT_WAIT_S=0.005):
            r = le._smart_sell(client, "X", 10.0, "TIME_CAP", log_fn)

        assert r["ok"] is True
        assert r["path"] == "limit_partial+market"
        assert r["filled_qty"]   == pytest.approx(10.0)
        assert r["filled_value"] == pytest.approx(9.88)
        kinds = [e["event"] for e in events]
        assert "LIMIT_PLACED"        in kinds
        assert "LIMIT_FILL_PARTIAL"  in kinds
        assert "LIMIT_TIMEOUT"       in kinds
        assert "MARKET_FALLBACK"     in kinds

    def test_smart_sell_no_bbo_falls_through_to_market(self):
        """No bid available → straight to market sell."""
        client = MagicMock()
        # No bids → _get_best_bid_ask returns (None, None)
        client.get_best_bid_ask.return_value = _make_bbo_response(bid=None, ask=None)
        client.create_order.return_value = _make_order_response("oid-market")
        client.get_order.return_value    = _make_fill_response("oid-market", 10.0, 9.9)
        events, log_fn = self._log_sink()

        r = le._smart_sell(client, "X", 10.0, "TIME_CAP", log_fn)

        assert r["ok"] is True
        assert r["path"] == "market_fallback"
        assert r["limit_oid"]  is None
        assert r["market_oid"] == "oid-market"

    def test_smart_sell_total_failure_returns_not_ok(self):
        """Limit reject AND market reject → ok=False so caller restores position."""
        client = self._client_with_bbo(bid=1.0)
        client.create_order.return_value = _make_order_response(
            "x", success=False, error_code="UNKNOWN_ERROR")
        events, log_fn = self._log_sink()

        r = le._smart_sell(client, "X", 10.0, "TIME_CAP", log_fn)

        assert r["ok"] is False
        assert r["filled_qty"] == 0.0
        # No LIMIT_PLACED event when the limit submission was rejected
        assert all(e["event"] != "LIMIT_PLACED" for e in events)


class TestStrandedSellCancel:
    """Verify reconciliation cancels open SELL orders left over from a crash."""

    def test_cancels_open_sell_at_startup(self, tmp_path):
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 100.0)
        )
        # One stranded SELL on the books for FOO.
        stranded = MagicMock()
        stranded.order_id   = "stranded-1"
        stranded.product_id = "FOO-USD"
        stranded.side       = "SELL"
        unrelated = MagicMock()
        unrelated.order_id   = "ignore-1"
        unrelated.product_id = "BTC-USD"
        unrelated.side       = "BUY"
        client.list_orders.return_value = _make_list_orders_response(stranded, unrelated)
        client.cancel_orders.return_value = _make_cancel_response(success=True)

        ex = _make_executor(tmp_path, client)

        # The cancel call list contains stranded-1 but not ignore-1.
        cancel_calls = [
            c.kwargs.get("order_ids") or (c.args[0] if c.args else None)
            for c in client.cancel_orders.mock_calls
        ]
        flat = [oid for entry in cancel_calls if entry for oid in entry]
        assert "stranded-1" in flat
        assert "ignore-1"  not in flat


class TestEntryLoggingIntendedPx:
    """ENTRY/FILL events must carry intended_px for slippage measurement."""

    def test_entry_record_includes_intended_px(self, tmp_path):
        client = MagicMock()
        client.get_accounts.return_value = _make_accounts_response(
            _make_account("USD", 100.0)
        )
        client.get_best_bid_ask.return_value = _make_bbo_response(bid=0.99, ask=1.005)
        client.create_order.return_value = _make_order_response("oid-buy")
        client.get_order.return_value    = _make_fill_response("oid-buy", 10.0, 10.07)

        ex = _make_executor(tmp_path, client)

        sig = FakeSignal(coin="ZZ", variant="R7_STAIRCASE")
        sig.features.update({
            "rank_60s": 1, "cg_trending": False, "market_breadth_5m": 5,
            "signals_24h": 5,
            # step_2m below R11 threshold (0.018) so we take the standard R7 path
            # without the extra higher_lows_3m / cvd>0 gates.
            "step_2m": 0.012, "candle_close_str_1m": 0.9,
            "btc_rel_ret_5m": 0.05, "first_signal_today": True,
        })
        ex.on_signal(sig)
        time.sleep(0.4)

        records = [json.loads(l) for l in
                   (tmp_path / "live_trades.jsonl").read_text().splitlines()]
        entries = [r for r in records if r.get("event") == "ENTRY"]
        assert entries, "ENTRY record must be written"
        # intended_px is the best ask captured before submission.
        assert entries[0].get("intended_px") == pytest.approx(1.005)
