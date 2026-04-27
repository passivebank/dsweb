"""
research/runner_research/coingecko_snapshot.py — daily CoinGecko enrichment.

Pulls per-coin metadata from the CoinGecko free API for every coin in our
trading universe and appends a dated snapshot to a rolling JSONL.

Free-tier rate limit is ~10-30 req/min. We batch via the /coins/markets
endpoint (250 coins per request, paginated) — completes in 2-3 requests
total. Plus optional /coins/{id} per coin for ATH date / age (slower,
optional via --enrich-detail).

Output: artifacts/coingecko_snapshot.jsonl (append-only, one JSON line
per coin per snapshot day).

Usage:
    python3 -m research.runner_research.coingecko_snapshot
    python3 -m research.runner_research.coingecko_snapshot --enrich-detail
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# stdlib HTTP — no external deps
import urllib.request
import urllib.parse
import urllib.error

CG_BASE = "https://api.coingecko.com/api/v3"
OUT_PATH = Path(os.environ.get(
    "COINGECKO_SNAPSHOT_PATH",
    "/home/ec2-user/phase3_intrabar/artifacts/coingecko_snapshot.jsonl",
))
COIN_MAP_CACHE = Path(os.environ.get(
    "COINGECKO_COIN_MAP_PATH",
    "/home/ec2-user/phase3_intrabar/artifacts/coingecko_coin_map.json",
))
UNIVERSE_PATH = Path(os.environ.get(
    "PHASE3_UNIVERSE_PATH",
    "/home/ec2-user/phase3_intrabar/artifacts/recorder_heartbeat.json",
))

PER_PAGE = 250
SLEEP_BETWEEN_REQ_S = 6   # ~10 req/min budget — safe for free tier


def _http_get(url: str, params: dict | None = None, retries: int = 3) -> dict | list:
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
            print(f"  HTTP {e.code}: {e.reason}")
            time.sleep(2 ** attempt)
        except Exception as e:
            last_err = e
            print(f"  err {e}")
            time.sleep(2 ** attempt)
    raise RuntimeError(f"failed after {retries} retries: {last_err}")


def load_universe() -> list[str]:
    """Get list of coin symbols we trade. Tries the recorder heartbeat first
    (lists current products), falls back to a hard-coded universe."""
    if UNIVERSE_PATH.exists():
        try:
            d = json.loads(UNIVERSE_PATH.read_text())
            for k in ("products", "universe", "coins"):
                if k in d and isinstance(d[k], list):
                    return [str(x).replace("-USD", "").upper() for x in d[k]]
        except Exception:
            pass

    # Fallback: pull current Coinbase USD universe via the recorder's API
    print("recorder heartbeat doesn't have universe; using fallback Coinbase fetch")
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
        print(f"fallback fetch failed: {e}")
        return []


def fetch_full_coin_map() -> dict[str, str]:
    """CoinGecko symbol → coin_id mapping. Some symbols collide; CoinGecko
    has multiple coins for "DAI", "USDT", etc. We pick the highest market
    cap (first hit on /coins/markets)."""
    if COIN_MAP_CACHE.exists():
        try:
            return json.loads(COIN_MAP_CACHE.read_text())
        except Exception:
            pass

    print("building coin map from /coins/list and /coins/markets...")
    coin_list = _http_get(f"{CG_BASE}/coins/list")
    if not isinstance(coin_list, list):
        return {}

    # Pull top-1000 by mcap from /coins/markets to resolve symbol collisions
    top_by_mcap: list[dict] = []
    for page in (1, 2, 3, 4):
        d = _http_get(f"{CG_BASE}/coins/markets", {
            "vs_currency": "usd", "order": "market_cap_desc",
            "per_page": PER_PAGE, "page": page, "sparkline": "false",
        })
        if not isinstance(d, list) or not d: break
        top_by_mcap.extend(d)
        time.sleep(SLEEP_BETWEEN_REQ_S)
    print(f"  top {len(top_by_mcap)} coins by mcap loaded")

    # Best id per symbol = highest mcap. Build symbol→id from top_by_mcap.
    sym_to_id: dict[str, str] = {}
    for c in top_by_mcap:
        sym = (c.get("symbol") or "").upper()
        if sym and sym not in sym_to_id:
            sym_to_id[sym] = c["id"]

    # Fill in any remaining symbols from /coins/list (may pick wrong id but
    # better than nothing for low-cap stuff)
    for c in coin_list:
        sym = (c.get("symbol") or "").upper()
        if sym and sym not in sym_to_id:
            sym_to_id[sym] = c["id"]

    COIN_MAP_CACHE.parent.mkdir(parents=True, exist_ok=True)
    COIN_MAP_CACHE.write_text(json.dumps(sym_to_id))
    print(f"  cached {len(sym_to_id)} symbol→id mappings to {COIN_MAP_CACHE}")
    return sym_to_id


def fetch_market_data(coin_ids: list[str]) -> dict[str, dict]:
    """Batch /coins/markets call. Up to 250 coins per request via `ids` param."""
    out: dict[str, dict] = {}
    for i in range(0, len(coin_ids), 250):
        batch = coin_ids[i:i + 250]
        try:
            data = _http_get(f"{CG_BASE}/coins/markets", {
                "vs_currency": "usd",
                "ids": ",".join(batch),
                "per_page": 250,
                "page": 1,
                "sparkline": "false",
                "price_change_percentage": "1h,24h,7d",
            })
        except Exception as e:
            print(f"  batch {i//250+1} failed: {e}")
            continue
        if isinstance(data, list):
            for r in data:
                out[r["id"]] = r
        time.sleep(SLEEP_BETWEEN_REQ_S)
    return out


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--enrich-detail", action="store_true",
                   help="ALSO call /coins/{id} for ATH date / categories (slow, ~5min/100coins)")
    p.add_argument("--max-detail", type=int, default=50,
                   help="when --enrich-detail, fetch detail for top N by trading volume only")
    args = p.parse_args(argv[1:])

    universe = load_universe()
    print(f"universe: {len(universe)} coins")
    if not universe: return 1

    sym_to_id = fetch_full_coin_map()
    matched = {}
    unmatched = []
    for sym in universe:
        cid = sym_to_id.get(sym)
        if cid:
            matched[sym] = cid
        else:
            unmatched.append(sym)
    print(f"  matched: {len(matched)}, unmatched: {len(unmatched)}")
    if unmatched[:10]:
        print(f"  examples unmatched: {unmatched[:10]}")

    market = fetch_market_data(list(matched.values()))
    print(f"  market data: {len(market)} coins")

    snapshot_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snapshot_date = snapshot_ts.split("T")[0]
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for sym, cid in matched.items():
        m = market.get(cid)
        if not m: continue
        rows.append({
            "snapshot_ts":           snapshot_ts,
            "snapshot_date":         snapshot_date,
            "coin":                  sym,
            "cg_id":                 cid,
            "market_cap_usd":        m.get("market_cap"),
            "market_cap_rank":       m.get("market_cap_rank"),
            "fully_diluted_val_usd": m.get("fully_diluted_valuation"),
            "circulating_supply":    m.get("circulating_supply"),
            "total_supply":          m.get("total_supply"),
            "max_supply":            m.get("max_supply"),
            "volume_24h_usd":        m.get("total_volume"),
            "price_usd":             m.get("current_price"),
            "price_change_1h_pct":   m.get("price_change_percentage_1h_in_currency"),
            "price_change_24h_pct":  m.get("price_change_percentage_24h_in_currency"),
            "price_change_7d_pct":   m.get("price_change_percentage_7d_in_currency"),
            "high_24h":              m.get("high_24h"),
            "low_24h":               m.get("low_24h"),
            "ath":                   m.get("ath"),
            "ath_change_pct":        m.get("ath_change_percentage"),
            "ath_date":              m.get("ath_date"),
            "atl":                   m.get("atl"),
            "atl_date":              m.get("atl_date"),
        })

    if args.enrich_detail:
        # Sort by 24h vol, take top N
        rows_with_vol = sorted(rows, key=lambda r: -(r.get("volume_24h_usd") or 0))[:args.max_detail]
        print(f"  enriching detail for top {len(rows_with_vol)} by volume...")
        for i, r in enumerate(rows_with_vol):
            cid = r["cg_id"]
            try:
                d = _http_get(f"{CG_BASE}/coins/{cid}",
                              {"localization": "false", "tickers": "false",
                               "market_data": "false", "community_data": "true",
                               "developer_data": "false"})
                if isinstance(d, dict):
                    r["categories"] = d.get("categories", [])[:6]
                    r["genesis_date"] = d.get("genesis_date")
                    r["sentiment_votes_up_pct"] = d.get("sentiment_votes_up_percentage")
                    r["twitter_followers"] = (d.get("community_data") or {}).get("twitter_followers")
                    r["reddit_subscribers"] = (d.get("community_data") or {}).get("reddit_subscribers")
            except Exception as e:
                print(f"  detail fetch failed for {cid}: {e}")
            time.sleep(SLEEP_BETWEEN_REQ_S)
            if (i + 1) % 10 == 0:
                print(f"  {i+1}/{len(rows_with_vol)}")

    # Append to rolling JSONL
    with OUT_PATH.open("a") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")
    print(f"\nappended {len(rows)} rows to {OUT_PATH}")

    # Summary
    nonnull_mcap = sum(1 for r in rows if r.get("market_cap_usd"))
    nonnull_vol  = sum(1 for r in rows if r.get("volume_24h_usd"))
    nonnull_ath  = sum(1 for r in rows if r.get("ath_date"))
    print(f"  market_cap populated:  {nonnull_mcap}/{len(rows)}")
    print(f"  volume_24h populated:  {nonnull_vol}/{len(rows)}")
    print(f"  ath_date populated:    {nonnull_ath}/{len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
