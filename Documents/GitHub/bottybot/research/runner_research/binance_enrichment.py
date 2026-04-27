"""
research/runner_research/binance_enrichment.py — Binance perp funding + OI history.

TWO MODES
=========
1. **--backfill**: pull 8h funding-rate history and 5m OI snapshots for the
   last 30 days for every coin in our trading universe (those that have a
   matching Binance perp). Output is a per-coin parquet/jsonl that the ML
   retrain reads. Runs once.

2. **--snapshot**: pull current funding + OI for every matched coin and
   append to a rolling JSONL. Runs daily, like coingecko_snapshot.

Why both
--------
- Backfill: gives us real Binance basis features for the 14-day shadow
  window, which can immediately enrich the ML retrain. No 30-day wait.
- Forward snapshot: keeps the data current alongside CoinGecko.

Endpoints (no auth required)
----------------------------
- /fapi/v1/exchangeInfo                    — list perp symbols (mapping)
- /fapi/v1/fundingRate?symbol=&limit=1000  — last 1000 funding events
- /futures/data/openInterestHist?symbol=&period=5m&limit=500
- /fapi/v1/premiumIndex?symbol=             — current funding + mark price

Free, public. No keys. Rate limit ~1200 req/min on weight-1 endpoints.
We sleep 50ms between requests = 1200 req/min budget = safe.

Output
------
- /artifacts/binance_funding_history.jsonl    (backfill)
- /artifacts/binance_oi_history.jsonl         (backfill)
- /artifacts/binance_snapshot.jsonl           (daily forward-snapshot)
- /artifacts/binance_perp_map.json            (cached symbol→perp mapping)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import urllib.request
import urllib.parse
import urllib.error

BN_BASE = "https://fapi.binance.com"
ARTIFACTS = Path(os.environ.get(
    "PHASE3_ARTIFACTS",
    "/home/ec2-user/phase3_intrabar/artifacts",
))
PERP_MAP_PATH = ARTIFACTS / "binance_perp_map.json"
FUND_HIST_PATH = ARTIFACTS / "binance_funding_history.jsonl"
OI_HIST_PATH   = ARTIFACTS / "binance_oi_history.jsonl"
SNAPSHOT_PATH  = ARTIFACTS / "binance_snapshot.jsonl"
SNAPSHOT_LOG   = ARTIFACTS / "binance_snapshot.log"

REQ_SLEEP_S = 0.06  # 1200 req/min — well under Binance limit


def _http_get(path: str, params: dict | None = None, retries: int = 3) -> dict | list:
    url = BN_BASE + path
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "botty-research/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                wait = 30 * (attempt + 1)
                print(f"  rate-limited, sleeping {wait}s")
                time.sleep(wait)
                continue
            if e.code == 400:
                # symbol not on Binance — caller should handle
                return None
            print(f"  HTTP {e.code} {e.reason} {url}")
            time.sleep(2 ** attempt)
        except Exception as e:
            last_err = e
            time.sleep(2 ** attempt)
    return None


def load_universe() -> list[str]:
    """Pull current Coinbase USD universe from Coinbase REST."""
    try:
        from coinbase.rest import RESTClient
        from dotenv import dotenv_values
        cfg = dotenv_values("/home/ec2-user/nkn_bot/.env")
        c = RESTClient(api_key=cfg["CB_API_KEY"], api_secret=cfg["CB_API_SECRET"])
        products = c.get_products(product_type="SPOT")
        coins = []
        for p in products.products:
            pid = getattr(p, "product_id", "")
            if pid.endswith("-USD") and not getattr(p, "trading_disabled", True):
                coins.append(pid[:-4].upper())
        return sorted(set(coins))
    except Exception as e:
        print(f"universe fetch failed: {e}")
        return []


def build_perp_map() -> dict[str, str]:
    """Map our coin symbol → Binance perp symbol. Tries a few suffix
    conventions; caches result."""
    if PERP_MAP_PATH.exists():
        try:
            return json.loads(PERP_MAP_PATH.read_text())
        except Exception:
            pass
    info = _http_get("/fapi/v1/exchangeInfo")
    if not info or "symbols" not in info:
        return {}
    # Build a set of all perpetual USDT-margined symbols
    perps = {}
    for s in info["symbols"]:
        if (s.get("contractType") == "PERPETUAL"
            and s.get("quoteAsset") in ("USDT", "USDC", "USD")
            and s.get("status") == "TRADING"):
            base = s.get("baseAsset", "").upper()
            perp_sym = s["symbol"]
            # Prefer USDT-margined (most liquid)
            if base not in perps or s.get("quoteAsset") == "USDT":
                perps[base] = perp_sym

    universe = load_universe()
    print(f"universe: {len(universe)} coins; binance perps: {len(perps)}")
    sym_to_perp: dict[str, str] = {}
    for coin in universe:
        if coin in perps:
            sym_to_perp[coin] = perps[coin]
        # Try common renames (e.g. CGLD on Coinbase = CELO on Binance)
        for alias in (coin.replace("1", ""), coin.lstrip("0123456789")):
            if alias != coin and alias in perps:
                sym_to_perp[coin] = perps[alias]
                break
    PERP_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    PERP_MAP_PATH.write_text(json.dumps(sym_to_perp, indent=2))
    print(f"  matched {len(sym_to_perp)} of {len(universe)} coins to a Binance perp")
    return sym_to_perp


def backfill_funding(perp_map: dict[str, str], days: int) -> int:
    """Pull funding rate history for every mapped coin over the last N days.
    Funding events fire every 8h, so days*3 events per coin. limit=1000 is
    enough for ~330 days of history per call."""
    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    written = 0
    FUND_HIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Truncate at start
    if FUND_HIST_PATH.exists(): FUND_HIST_PATH.unlink()
    for i, (coin, perp) in enumerate(sorted(perp_map.items())):
        time.sleep(REQ_SLEEP_S)
        d = _http_get("/fapi/v1/fundingRate",
                      {"symbol": perp, "startTime": cutoff_ms, "limit": 1000})
        if not d or not isinstance(d, list):
            continue
        with FUND_HIST_PATH.open("a") as f:
            for r in d:
                f.write(json.dumps({
                    "coin":            coin,
                    "perp":            perp,
                    "funding_time_ms": r.get("fundingTime"),
                    "funding_rate":    float(r.get("fundingRate", 0)),
                    "mark_price":      float(r.get("markPrice", 0)),
                }) + "\n")
                written += 1
        if (i + 1) % 50 == 0:
            print(f"  funding: {i+1}/{len(perp_map)} coins, {written} events")
    print(f"  funding total: {written} events written to {FUND_HIST_PATH}")
    return written


def backfill_oi(perp_map: dict[str, str], days: int) -> int:
    """Pull 5m OI history for the last N days. Cap at the most-liquid 100
    coins to keep API budget reasonable (5m × 24h × N days = a lot)."""
    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)

    # Pre-rank coins by current 24h volume so we OI-backfill the most-liquid first
    print("  ranking coins by current 24h volume...")
    tickers = _http_get("/fapi/v1/ticker/24hr")
    vol_by_perp = {}
    if isinstance(tickers, list):
        for t in tickers:
            try:
                vol_by_perp[t["symbol"]] = float(t.get("quoteVolume", 0))
            except Exception:
                continue

    ranked = sorted(perp_map.items(), key=lambda kv: -vol_by_perp.get(kv[1], 0))
    top_n = min(100, len(ranked))
    print(f"  backfilling OI for top {top_n} by volume")
    written = 0
    if OI_HIST_PATH.exists(): OI_HIST_PATH.unlink()

    # OI endpoint limits: 30-day max history, period=5m, limit=500 = 41h per call
    # so we need to paginate via end_time
    for i, (coin, perp) in enumerate(ranked[:top_n]):
        end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
        rows_for_coin = 0
        for _ in range(20):  # max 20 pages = ~30 days
            time.sleep(REQ_SLEEP_S)
            d = _http_get("/futures/data/openInterestHist",
                          {"symbol": perp, "period": "5m",
                           "limit": 500, "endTime": end_time})
            if not d or not isinstance(d, list) or len(d) == 0:
                break
            with OI_HIST_PATH.open("a") as f:
                for r in d:
                    ts = r.get("timestamp")
                    if ts and ts < cutoff_ms: continue
                    f.write(json.dumps({
                        "coin":      coin,
                        "perp":      perp,
                        "ts_ms":     ts,
                        "oi_coin":   float(r.get("sumOpenInterest", 0)),
                        "oi_usd":    float(r.get("sumOpenInterestValue", 0)),
                    }) + "\n")
                    rows_for_coin += 1
                    written += 1
            # advance the window
            oldest_ts = min(int(r.get("timestamp", end_time)) for r in d)
            if oldest_ts <= cutoff_ms or oldest_ts >= end_time:
                break
            end_time = oldest_ts - 1
        if (i + 1) % 10 == 0:
            print(f"  OI: {i+1}/{top_n} coins, {written} rows")
    print(f"  OI total: {written} rows written to {OI_HIST_PATH}")
    return written


def cmd_backfill(days: int) -> int:
    perp_map = build_perp_map()
    if not perp_map: return 1
    print(f"\n=== Backfilling funding ({days} days) ===")
    n_fund = backfill_funding(perp_map, days)
    print(f"\n=== Backfilling OI ({days} days, top-100 by vol) ===")
    n_oi = backfill_oi(perp_map, days)
    print(f"\nbackfill complete: {n_fund} funding events, {n_oi} OI rows")
    return 0


def cmd_snapshot() -> int:
    """Daily current-state snapshot: funding rate, mark price, OI, basis."""
    perp_map = build_perp_map()
    if not perp_map: return 1
    snapshot_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snapshot_date = snapshot_ts.split("T")[0]
    rows = []
    for i, (coin, perp) in enumerate(sorted(perp_map.items())):
        time.sleep(REQ_SLEEP_S)
        # Premium index = funding + mark price + index price + estimated next funding
        d = _http_get("/fapi/v1/premiumIndex", {"symbol": perp})
        if not d: continue
        # Open interest snapshot
        time.sleep(REQ_SLEEP_S)
        oi = _http_get("/fapi/v1/openInterest", {"symbol": perp})
        rows.append({
            "snapshot_ts":     snapshot_ts,
            "snapshot_date":   snapshot_date,
            "coin":            coin,
            "perp":            perp,
            "mark_price":      float(d.get("markPrice", 0)),
            "index_price":     float(d.get("indexPrice", 0)),
            "last_funding":    float(d.get("lastFundingRate", 0)),
            "next_funding_ms": int(d.get("nextFundingTime", 0)),
            "oi_coin":         float((oi or {}).get("openInterest", 0)) if oi else 0,
        })
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SNAPSHOT_PATH.open("a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"appended {len(rows)} rows to {SNAPSHOT_PATH}")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    bf = sub.add_parser("backfill", help="one-shot 14-30 day historical pull")
    bf.add_argument("--days", type=int, default=14)
    sub.add_parser("snapshot", help="daily current-state snapshot")
    args = p.parse_args(argv[1:])
    if args.cmd == "backfill":
        return cmd_backfill(args.days)
    if args.cmd == "snapshot":
        return cmd_snapshot()
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
