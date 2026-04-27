"""
research/runner_research/build_perp_features.py — join perp data → per-signal features.

Reads:
  - /tmp/runner_research/labeled.jsonl.gz  (signal moments)
  - perp_funding_history.jsonl              (8h funding events from OKX backfill)
  - perp_oi_history.jsonl                   (1h OI/volume rows from OKX backfill)

Computes new per-signal features:
  - perp_last_funding_rate              (most recent funding ≤ signal time)
  - perp_funding_rate_24h_avg           (avg of last 3 funding events)
  - perp_funding_rate_change_24h        (current minus 24h ago)
  - perp_oi_now                         (1h OI at signal time)
  - perp_oi_change_1h                   (% change from 1h ago)
  - perp_oi_change_4h                   (% change from 4h ago)
  - perp_vol_now                        (1h taker volume at signal time)
  - perp_vol_change_1h                  (% change vs 1h ago)
  - perp_vol_vs_24h_avg                 (current vs trailing 24h)

Output:
  - /tmp/runner_research/labeled_with_perp.jsonl.gz  (replaces labeled.jsonl.gz
    for retrain consumption; original kept for backwards compatibility)

Run after perp_enrichment backfill completes:
  python3 -m research.runner_research.build_perp_features
"""
from __future__ import annotations

import gzip
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

LABELED       = Path("/tmp/runner_research/labeled.jsonl.gz")
OUT           = Path("/tmp/runner_research/labeled_with_perp.jsonl.gz")
FUND_HIST     = Path(os.environ.get(
    "PERP_FUND_HIST_PATH",
    "/home/ec2-user/phase3_intrabar/artifacts/perp_funding_history.jsonl",
))
OI_HIST       = Path(os.environ.get(
    "PERP_OI_HIST_PATH",
    "/home/ec2-user/phase3_intrabar/artifacts/perp_oi_history.jsonl",
))


def main() -> int:
    if not FUND_HIST.exists():
        print(f"ERR: {FUND_HIST} missing — run perp_enrichment backfill first", file=sys.stderr)
        return 1
    if not OI_HIST.exists():
        print(f"ERR: {OI_HIST} missing", file=sys.stderr)
        return 1
    if not LABELED.exists():
        print(f"ERR: {LABELED} missing — run build_dataset first", file=sys.stderr)
        return 1

    # Index funding events by coin, sorted by time
    fund_by_coin: dict[str, list[tuple[int, float]]] = defaultdict(list)
    with FUND_HIST.open() as f:
        for line in f:
            try: r = json.loads(line)
            except: continue
            ts = r.get("funding_time_ms")
            rate = r.get("funding_rate")
            if ts is None or rate is None: continue
            fund_by_coin[r["coin"]].append((int(ts), float(rate)))
    for coin in fund_by_coin: fund_by_coin[coin].sort()
    print(f"funding history: {len(fund_by_coin)} coins, "
          f"{sum(len(v) for v in fund_by_coin.values())} events")

    # Index OI events by coin, sorted by time
    oi_by_coin: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
    with OI_HIST.open() as f:
        for line in f:
            try: r = json.loads(line)
            except: continue
            ts = r.get("ts_ms"); oi_usd = r.get("oi_usd"); vol_usd = r.get("vol_usd")
            if ts is None: continue
            oi_by_coin[r["coin"]].append((int(ts), float(oi_usd or 0), float(vol_usd or 0)))
    for coin in oi_by_coin: oi_by_coin[coin].sort()
    print(f"oi history: {len(oi_by_coin)} coins, "
          f"{sum(len(v) for v in oi_by_coin.values())} rows")

    def _last_at_or_before(rows: list[tuple], ts_ms: int):
        """Binary search the last row whose timestamp is <= ts_ms."""
        if not rows: return None
        lo, hi = 0, len(rows) - 1
        if rows[0][0] > ts_ms: return None
        if rows[-1][0] <= ts_ms: return rows[-1]
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if rows[mid][0] <= ts_ms: lo = mid
            else: hi = mid - 1
        return rows[lo]

    enriched = 0; total = 0; matched = 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(LABELED, "rt") as fin, gzip.open(OUT, "wt") as fout:
        for line in fin:
            line = line.strip()
            if not line: continue
            r = json.loads(line)
            total += 1
            coin = r.get("coin", "")
            sig_ts_ns = r.get("sig_ts_ns")
            if not coin or sig_ts_ns is None:
                fout.write(line + "\n"); continue
            sig_ts_ms = sig_ts_ns // 1_000_000

            # Funding features
            f_rows = fund_by_coin.get(coin, [])
            cur = _last_at_or_before(f_rows, sig_ts_ms)
            if cur:
                r["f_perp_last_funding_rate"] = cur[1]
                # Find rates 8h, 16h, 24h before
                rates_24h = [
                    rate for ts, rate in f_rows
                    if sig_ts_ms - 3 * 8 * 3600_000 <= ts <= sig_ts_ms
                ]
                if rates_24h:
                    r["f_perp_funding_rate_24h_avg"] = sum(rates_24h) / len(rates_24h)
                rate_24h_ago = _last_at_or_before(f_rows, sig_ts_ms - 24 * 3600_000)
                if rate_24h_ago:
                    r["f_perp_funding_rate_change_24h"] = cur[1] - rate_24h_ago[1]

            # OI / volume features
            oi_rows = oi_by_coin.get(coin, [])
            now = _last_at_or_before(oi_rows, sig_ts_ms)
            if now:
                r["f_perp_oi_now"] = now[1]
                r["f_perp_vol_now"] = now[2]
                # 1h, 4h, 24h ago
                hr1 = _last_at_or_before(oi_rows, sig_ts_ms - 3600_000)
                hr4 = _last_at_or_before(oi_rows, sig_ts_ms - 4 * 3600_000)
                hr24 = [oi for ts, oi, _v in oi_rows
                        if sig_ts_ms - 24 * 3600_000 <= ts <= sig_ts_ms]
                if hr1 and hr1[1] > 0:
                    r["f_perp_oi_change_1h"] = (now[1] - hr1[1]) / hr1[1]
                if hr4 and hr4[1] > 0:
                    r["f_perp_oi_change_4h"] = (now[1] - hr4[1]) / hr4[1]
                if hr24:
                    avg_oi_24h = sum(hr24) / len(hr24)
                    if avg_oi_24h > 0:
                        r["f_perp_oi_vs_24h_avg"] = now[1] / avg_oi_24h
                # Volume features
                v1h = _last_at_or_before(oi_rows, sig_ts_ms - 3600_000)
                if v1h and v1h[2] > 0:
                    r["f_perp_vol_change_1h"] = (now[2] - v1h[2]) / v1h[2]
                vol_24h = [v for ts, _o, v in oi_rows
                           if sig_ts_ms - 24 * 3600_000 <= ts <= sig_ts_ms]
                if vol_24h:
                    avg_v = sum(vol_24h) / len(vol_24h)
                    if avg_v > 0:
                        r["f_perp_vol_vs_24h_avg"] = now[2] / avg_v
                matched += 1

            if any(k.startswith("f_perp_") for k in r):
                enriched += 1

            fout.write(json.dumps(r, default=str) + "\n")

    print(f"\nrows: {total}, matched OI: {matched}, enriched with any perp feature: {enriched}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
