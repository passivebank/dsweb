"""
research/runner_research/perp_enrichment.py — perpetual-futures funding + OI history.

Uses OKX (the recorder already integrates OKX for `bn_funding_rate` since
Binance Futures geo-blocks US IPs). Endpoints used:

  /api/v5/public/instruments?instType=SWAP            — list perpetual contracts
  /api/v5/public/funding-rate-history?instId=         — historical funding (8h granularity, last 100 events ≈ 33 days)
  /api/v5/market/open-interest?instId=                — current open interest
  /api/v5/rubik/stat/contracts/open-interest-volume?ccy=&period=1H
                                                       — historical OI + taker volume by base ccy (1h granularity, last 30 days)

TWO MODES
=========
1. **--backfill**: pull 30 days of funding history + 30 days of 1h OI/volume
   for every coin in our trading universe with an OKX perp. Writes once.
2. **--snapshot**: pull current funding + current OI for every coin and
   append to a rolling JSONL. Runs daily.

OUTPUT
------
- /artifacts/perp_funding_history.jsonl
- /artifacts/perp_oi_history.jsonl
- /artifacts/perp_snapshot.jsonl
- /artifacts/perp_inst_map.json
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

OKX_BASE = "https://www.okx.com"
ARTIFACTS = Path(os.environ.get(
    "PHASE3_ARTIFACTS",
    "/home/ec2-user/phase3_intrabar/artifacts",
))
INST_MAP_PATH   = ARTIFACTS / "perp_inst_map.json"
FUND_HIST_PATH  = ARTIFACTS / "perp_funding_history.jsonl"
OI_HIST_PATH    = ARTIFACTS / "perp_oi_history.jsonl"
SNAPSHOT_PATH   = ARTIFACTS / "perp_snapshot.jsonl"

REQ_SLEEP_S = 0.06   # OKX limit is 20 req/2s on most endpoints — 0.06s is safe


def _http_get(path: str, params: dict | None = None, retries: int = 3):
    url = OKX_BASE + path
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "botty-research/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                d = json.loads(resp.read().decode())
                if isinstance(d, dict) and d.get("code") == "0":
                    return d.get("data", [])
                if isinstance(d, dict) and d.get("code") in ("51001", "51000"):
                    return None  # invalid instrument — caller should skip
                if isinstance(d, dict):
                    print(f"  okx err code={d.get('code')} msg={d.get('msg')[:80] if d.get('msg') else ''}")
                    return None
                return d
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                wait = 30 * (attempt + 1)
                print(f"  rate-limited, sleeping {wait}s")
                time.sleep(wait)
                continue
            print(f"  HTTP {e.code} {e.reason}")
            time.sleep(2 ** attempt)
        except Exception as e:
            last_err = e
            time.sleep(2 ** attempt)
    return None


def load_universe() -> list[str]:
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


def build_inst_map() -> dict[str, str]:
    """Map our coin symbol → OKX instId (e.g. BTC → BTC-USDT-SWAP).
    Cached to disk."""
    if INST_MAP_PATH.exists():
        try:
            return json.loads(INST_MAP_PATH.read_text())
        except Exception:
            pass
    print("fetching OKX perp universe...")
    insts = _http_get("/api/v5/public/instruments", {"instType": "SWAP"})
    if not insts:
        return {}
    base_to_inst: dict[str, str] = {}
    for r in insts:
        # Prefer USDT-margined (most liquid), then USDC, then USD
        if r.get("state") != "live": continue
        if r.get("ctType") != "linear": continue
        inst_id = r.get("instId", "")
        if not inst_id.endswith("-SWAP"): continue
        base = (r.get("ctValCcy") or r.get("settleCcy") or inst_id.split("-")[0]).upper()
        # Use BASE from the inst_id directly for clarity
        parts = inst_id.split("-")
        if len(parts) < 3: continue
        base = parts[0].upper()
        quote = parts[1].upper()
        # Score: USDT > USDC > USD
        score = {"USDT": 3, "USDC": 2, "USD": 1}.get(quote, 0)
        existing = base_to_inst.get(base)
        if existing:
            ex_quote = existing.split("-")[1]
            ex_score = {"USDT": 3, "USDC": 2, "USD": 1}.get(ex_quote, 0)
            if score <= ex_score: continue
        base_to_inst[base] = inst_id

    universe = load_universe()
    matched: dict[str, str] = {}
    for coin in universe:
        if coin in base_to_inst:
            matched[coin] = base_to_inst[coin]
    print(f"  universe: {len(universe)}, OKX perps: {len(base_to_inst)}, matched: {len(matched)}")
    INST_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    INST_MAP_PATH.write_text(json.dumps(matched, indent=2))
    return matched


def backfill_funding(inst_map: dict[str, str], days: int) -> int:
    """OKX funding history: 8h granularity, last 100 events per call ≈ 33d."""
    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    written = 0
    if FUND_HIST_PATH.exists(): FUND_HIST_PATH.unlink()
    FUND_HIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    for i, (coin, inst) in enumerate(sorted(inst_map.items())):
        time.sleep(REQ_SLEEP_S)
        d = _http_get("/api/v5/public/funding-rate-history",
                      {"instId": inst, "limit": 100})
        if not d or not isinstance(d, list): continue
        with FUND_HIST_PATH.open("a") as f:
            for r in d:
                ts = r.get("fundingTime")
                if not ts: continue
                try: ts_int = int(ts)
                except: continue
                if ts_int < cutoff_ms: continue
                f.write(json.dumps({
                    "coin":            coin,
                    "inst":            inst,
                    "funding_time_ms": ts_int,
                    "funding_rate":    float(r.get("fundingRate", 0) or 0),
                    "realized_rate":   float(r.get("realizedRate", 0) or 0),
                }) + "\n")
                written += 1
        if (i + 1) % 50 == 0:
            print(f"  funding: {i+1}/{len(inst_map)} coins, {written} events")
    print(f"  funding total: {written} events written")
    return written


def backfill_oi(inst_map: dict[str, str], days: int) -> int:
    """OKX historical OI by base ccy, 1h granularity, last 30 days."""
    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    written = 0
    if OI_HIST_PATH.exists(): OI_HIST_PATH.unlink()
    OI_HIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    for i, (coin, inst) in enumerate(sorted(inst_map.items())):
        time.sleep(REQ_SLEEP_S)
        d = _http_get("/api/v5/rubik/stat/contracts/open-interest-volume",
                      {"ccy": coin, "period": "1H"})
        if not d or not isinstance(d, list): continue
        with OI_HIST_PATH.open("a") as f:
            for r in d:
                # OKX returns lists [ts, oi, vol]
                if not isinstance(r, list) or len(r) < 3: continue
                try:
                    ts_int = int(r[0]); oi = float(r[1]); vol = float(r[2])
                except Exception:
                    continue
                if ts_int < cutoff_ms: continue
                f.write(json.dumps({
                    "coin":  coin,
                    "ts_ms": ts_int,
                    "oi_usd":  oi,
                    "vol_usd": vol,
                }) + "\n")
                written += 1
        if (i + 1) % 50 == 0:
            print(f"  oi: {i+1}/{len(inst_map)} coins, {written} rows")
    print(f"  OI total: {written} rows written")
    return written


def cmd_backfill(days: int) -> int:
    inst_map = build_inst_map()
    if not inst_map: return 1
    print(f"\n=== Backfilling funding ({days} days) ===")
    backfill_funding(inst_map, days)
    print(f"\n=== Backfilling OI ({days} days) ===")
    backfill_oi(inst_map, days)
    print("\nbackfill complete")
    return 0


def cmd_snapshot() -> int:
    inst_map = build_inst_map()
    if not inst_map: return 1
    snapshot_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snapshot_date = snapshot_ts.split("T")[0]
    rows = []
    for i, (coin, inst) in enumerate(sorted(inst_map.items())):
        time.sleep(REQ_SLEEP_S)
        # Current funding
        fr = _http_get("/api/v5/public/funding-rate", {"instId": inst})
        time.sleep(REQ_SLEEP_S)
        # Current OI
        oi = _http_get("/api/v5/public/open-interest", {"instType": "SWAP", "instId": inst})
        if not fr and not oi: continue
        cur_fund = (fr[0] if isinstance(fr, list) and fr else {}) or {}
        cur_oi   = (oi[0] if isinstance(oi, list) and oi else {}) or {}
        rows.append({
            "snapshot_ts":     snapshot_ts,
            "snapshot_date":   snapshot_date,
            "coin":            coin,
            "inst":            inst,
            "funding_rate":    float(cur_fund.get("fundingRate") or 0),
            "next_funding_ms": int(cur_fund.get("nextFundingTime") or 0),
            "oi_coin":         float(cur_oi.get("oi") or 0),
            "oi_usd":          float(cur_oi.get("oiUsd") or 0),
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
    bf = sub.add_parser("backfill")
    bf.add_argument("--days", type=int, default=30)
    sub.add_parser("snapshot")
    args = p.parse_args(argv[1:])
    return cmd_backfill(args.days) if args.cmd == "backfill" else cmd_snapshot()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
