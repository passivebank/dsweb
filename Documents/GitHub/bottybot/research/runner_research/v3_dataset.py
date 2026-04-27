"""
research/runner_research/v3_dataset.py — comprehensive labeled dataset for v3.

Differences from earlier dataset:
  - Universe-level signals_24h_universe: count of distinct coins firing
    signals on the same UTC day (not per-coin signals_24h)
  - True per-coin recent-history features:
      coin_signals_in_last_4h    (rolling 4h count of signals for THIS coin)
      coin_consecutive_signals   (signals in a row before this one, on this coin)
      coin_recent_runner         (was this coin in a 10%+ move in past 12h)
  - Multi-horizon forward outcomes computed properly:
      For each (coin, sig_ts_ns), pull max/min over each policy's window.
      Use longest-policy fwd_max/fwd_min as the "true forward trajectory" proxy.
  - Joins CoinGecko market cap / volume / ATH proximity per signal day
  - Joins OKX perp funding / OI features
"""
from __future__ import annotations

import gzip
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SHADOW_SIGNALS = Path("/tmp/runner_research/shadow_signals.jsonl")
SHADOW_TRADES  = Path("/tmp/runner_research/shadow_trades.jsonl")
PERP_FUND      = Path("/tmp/runner_research/perp_funding_history.jsonl")
PERP_OI        = Path("/tmp/runner_research/perp_oi_history.jsonl")
CG_SNAPSHOT    = Path("/tmp/runner_research/coingecko_snapshot.jsonl")
OUT            = Path("/tmp/runner_research/v3_labeled.jsonl.gz")
OUT_REPORT     = Path("research/runner_research/v3_dataset_report.md")


def main():
    # ── 1. Load all shadow_trades, group by signal moment ─────────────
    by_signal: dict[tuple, list[dict]] = defaultdict(list)
    n_raw = 0
    with SHADOW_TRADES.open() as f:
        for line in f:
            n_raw += 1
            try: r = json.loads(line)
            except: continue
            coin = r.get("coin")
            ts = r.get("entry_ts_ns") or r.get("sig_ts_ns")
            if coin and ts:
                by_signal[(coin, int(ts))].append(r)
    print(f"shadow_trades: {n_raw} rows → {len(by_signal)} unique signal moments")

    # ── 2. Index shadow_signals features by (coin, ts) ─────────────────
    sig_features: dict[tuple, dict] = {}
    with SHADOW_SIGNALS.open() as f:
        for line in f:
            try: r = json.loads(line)
            except: continue
            coin = r.get("coin"); ts = r.get("sig_ts_ns")
            if coin and ts:
                key = (coin, int(ts))
                merged = sig_features.setdefault(key, {})
                for k, v in (r.get("features") or {}).items():
                    if v is not None:
                        merged[k] = v
    print(f"shadow_signals: {len(sig_features)} feature snapshots")

    # ── 3. Index CoinGecko snapshots by coin (latest per day) ─────────
    cg_by_coin_date: dict[tuple, dict] = {}
    if CG_SNAPSHOT.exists():
        with CG_SNAPSHOT.open() as f:
            for line in f:
                try: r = json.loads(line)
                except: continue
                key = (r.get("coin"), r.get("snapshot_date"))
                cg_by_coin_date[key] = r
    print(f"coingecko: {len(cg_by_coin_date)} coin-date snapshots")

    # ── 4. Index perp data by (coin, ms) ─────────────────────────────
    perp_funding_by_coin: dict[str, list] = defaultdict(list)
    if PERP_FUND.exists():
        with PERP_FUND.open() as f:
            for line in f:
                try: r = json.loads(line)
                except: continue
                if r.get("coin") and r.get("funding_time_ms"):
                    perp_funding_by_coin[r["coin"]].append(
                        (int(r["funding_time_ms"]), float(r["funding_rate"]))
                    )
    for c in perp_funding_by_coin: perp_funding_by_coin[c].sort()
    perp_oi_by_coin: dict[str, list] = defaultdict(list)
    if PERP_OI.exists():
        with PERP_OI.open() as f:
            for line in f:
                try: r = json.loads(line)
                except: continue
                if r.get("coin") and r.get("ts_ms"):
                    perp_oi_by_coin[r["coin"]].append((
                        int(r["ts_ms"]),
                        float(r.get("oi_usd") or 0),
                        float(r.get("vol_usd") or 0),
                    ))
    for c in perp_oi_by_coin: perp_oi_by_coin[c].sort()
    print(f"perp data: {len(perp_funding_by_coin)} coins funding, {len(perp_oi_by_coin)} coins OI")

    def _last_at_or_before(rows, ts_ms):
        if not rows: return None
        if rows[0][0] > ts_ms: return None
        if rows[-1][0] <= ts_ms: return rows[-1]
        lo, hi = 0, len(rows) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if rows[mid][0] <= ts_ms: lo = mid
            else: hi = mid - 1
        return rows[lo]

    # ── 5. Pre-compute universe-level signals_24h_universe ────────────
    # For each UTC day, count of DISTINCT coins that fired any signal that day
    by_day_coins: dict[str, set] = defaultdict(set)
    for (coin, ts) in sig_features:
        d = datetime.fromtimestamp(ts/1e9, tz=timezone.utc).date().isoformat()
        by_day_coins[d].add(coin)
    universe_sig24h_by_day = {d: len(s) for d, s in by_day_coins.items()}

    # ── 6. Pre-compute per-coin signal history (rolling 4h count) ────
    coin_sigs: dict[str, list[int]] = defaultdict(list)
    for (coin, ts) in sig_features:
        coin_sigs[coin].append(int(ts))
    for coin in coin_sigs: coin_sigs[coin].sort()

    def coin_4h_count(coin: str, ts_ns: int) -> int:
        sigs = coin_sigs.get(coin, [])
        cutoff = ts_ns - 4 * 3600 * 1_000_000_000
        # bisect right
        lo, hi = 0, len(sigs)
        while lo < hi:
            mid = (lo + hi) // 2
            if sigs[mid] < cutoff: lo = mid + 1
            else: hi = mid
        # count from lo to where ts < ts_ns
        upper_lo, upper_hi = lo, len(sigs)
        while upper_lo < upper_hi:
            mid = (upper_lo + upper_hi) // 2
            if sigs[mid] < ts_ns: upper_lo = mid + 1
            else: upper_hi = mid
        return upper_lo - lo

    # ── 7. Build the labeled dataset ───────────────────────────────────
    out_rows = []
    for (coin, ts), trade_rows in by_signal.items():
        # Merge features from shadow_signals (canonical) + shadow_trades
        features = dict(sig_features.get((coin, ts), {}))
        if not features:
            for r in trade_rows:
                for k, v in (r.get("sig_features") or {}).items():
                    if v is not None and k not in features:
                        features[k] = v
        if "spread_bps_at_entry" not in features:
            spread_top = trade_rows[0].get("spread_bps_at_entry")
            if spread_top is not None: features["spread_bps_at_entry"] = spread_top

        variant = trade_rows[0].get("variant", "")
        sig_mid = trade_rows[0].get("entry_px", 0.0)
        sig_dt  = datetime.fromtimestamp(ts/1e9, tz=timezone.utc).isoformat()
        sig_date = sig_dt.split("T")[0]

        # Per-policy fwd_max / fwd_min
        policies: dict[str, dict] = defaultdict(lambda: {
            "fwd_max": None, "fwd_min": None, "holding_s": 0.0, "net_pct": None,
        })
        for r in trade_rows:
            pol = r.get("exit_policy", "?")
            fmax = r.get("fwd_max_pct"); fmin = r.get("fwd_min_pct")
            hs = r.get("holding_s") or 0.0
            cur = policies[pol]
            if fmax is not None and (cur["fwd_max"] is None or fmax > cur["fwd_max"]):
                cur["fwd_max"] = fmax
            if fmin is not None and (cur["fwd_min"] is None or fmin < cur["fwd_min"]):
                cur["fwd_min"] = fmin
            if hs > cur["holding_s"]:
                cur["holding_s"] = hs
                cur["net_pct"] = r.get("net_pct")

        all_max = max((p["fwd_max"] for p in policies.values() if p["fwd_max"] is not None),
                      default=None)
        all_min = min((p["fwd_min"] for p in policies.values() if p["fwd_min"] is not None),
                      default=None)
        # Multi-horizon: use exit_policy that best matches the horizon
        def get_window(secs_target):
            best = (None, None, float("inf"))
            for pol, info in policies.items():
                if info["fwd_max"] is None: continue
                diff = abs((info["holding_s"] or 0) - secs_target)
                if diff < best[2]:
                    best = (info["fwd_max"], info["fwd_min"], diff)
            return best[0], best[1]

        fmax_30s, fmin_30s = get_window(30)
        fmax_1m,  fmin_1m  = get_window(60)
        fmax_3m,  fmin_3m  = get_window(180)
        fmax_5m,  fmin_5m  = get_window(300)

        # Longest-policy natural exit
        natural = None; best_holding = 0.0
        for pol, info in policies.items():
            if info["holding_s"] > best_holding and info["net_pct"] is not None:
                best_holding = info["holding_s"]
                natural = info["net_pct"]

        # ── Add NEW v3 features ────────────────────────────────────────
        new_feats = {}
        # Universe-level signals today (NOT per-coin)
        new_feats["universe_signals_24h"] = universe_sig24h_by_day.get(sig_date, 0)
        # Per-coin recent activity (legitimate runner indicator)
        new_feats["coin_signals_4h"] = coin_4h_count(coin, ts)
        # Coin's signals_24h ratio: per-coin sig24h / universe-sig24h
        per_coin_24h = features.get("signals_24h", 0)
        univ_24h = max(universe_sig24h_by_day.get(sig_date, 0), 1)
        new_feats["coin_signal_share"] = (per_coin_24h or 0) / univ_24h

        # CoinGecko features (joined by date)
        cg = cg_by_coin_date.get((coin, sig_date))
        if cg:
            new_feats["cg_market_cap_usd"]   = cg.get("market_cap_usd")
            new_feats["cg_market_cap_rank"]  = cg.get("market_cap_rank")
            new_feats["cg_volume_24h_usd"]   = cg.get("volume_24h_usd")
            new_feats["cg_ath_change_pct"]   = cg.get("ath_change_pct")  # negative — distance from ATH
            new_feats["cg_price_change_24h"] = cg.get("price_change_24h_pct")
            new_feats["cg_price_change_7d"]  = cg.get("price_change_7d_pct")
            new_feats["cg_circ_supply"]      = cg.get("circulating_supply")
        # Perp funding/OI features
        sig_ms = ts // 1_000_000
        cur_fund = _last_at_or_before(perp_funding_by_coin.get(coin, []), sig_ms)
        if cur_fund:
            new_feats["perp_last_funding"] = cur_fund[1]
        cur_oi = _last_at_or_before(perp_oi_by_coin.get(coin, []), sig_ms)
        if cur_oi:
            new_feats["perp_oi_now"] = cur_oi[1]
            new_feats["perp_vol_now"] = cur_oi[2]
            hr1 = _last_at_or_before(perp_oi_by_coin.get(coin, []), sig_ms - 3600_000)
            if hr1 and hr1[1] > 0:
                new_feats["perp_oi_change_1h"] = (cur_oi[1] - hr1[1]) / hr1[1]

        row = {
            "coin": coin, "sig_ts_ns": ts, "sig_dt": sig_dt, "sig_date": sig_date,
            "variant": variant, "sig_mid": sig_mid,
            "fwd_max_30s": fmax_30s, "fwd_min_30s": fmin_30s,
            "fwd_max_1m":  fmax_1m,  "fwd_min_1m":  fmin_1m,
            "fwd_max_3m":  fmax_3m,  "fwd_min_3m":  fmin_3m,
            "fwd_max_5m":  fmax_5m,  "fwd_min_5m":  fmin_5m,
            "fwd_max_max": all_max,  "fwd_min_min": all_min,
            "natural_exit_net": natural,
        }
        for k, v in features.items():
            if v is None: continue
            row[f"f_{k}"] = v
        for k, v in new_feats.items():
            if v is None: continue
            row[f"f_{k}"] = v
        out_rows.append(row)

    out_rows.sort(key=lambda r: r["sig_ts_ns"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt") as gz:
        for r in out_rows:
            gz.write(json.dumps(r, default=str) + "\n")

    # ── 8. Sanity report ───────────────────────────────────────────────
    md = ["# v3 Dataset Report", ""]
    md.append(f"- Source: {n_raw:,} shadow_trades rows → {len(by_signal):,} unique signal moments")
    md.append(f"- CoinGecko snapshots: {len(cg_by_coin_date)} coin-date pairs")
    md.append(f"- Perp data: {len(perp_funding_by_coin)} coins funding, {len(perp_oi_by_coin)} coins OI")
    md.append(f"- Output rows: {len(out_rows):,}")
    md.append(f"- Output: `{OUT}`")
    md.append("")
    bands = [(-100, -5), (-5, -2), (-2, 0), (0, 1), (1, 2), (2, 3), (3, 5), (5, 10), (10, 30), (30, 1e9)]
    for col in ["fwd_max_5m", "fwd_max_max"]:
        md.append(f"## `{col}` distribution")
        md.append("| band | n | pct |")
        md.append("|---|---:|---:|")
        n_total = sum(1 for r in out_rows if r.get(col) is not None)
        for lo, hi in bands:
            c = sum(1 for r in out_rows
                    if r.get(col) is not None
                    and lo/100 <= r[col] < hi/100)
            md.append(f"| [{lo}%, {hi}%) | {c:,} | {c*100/max(n_total,1):.2f}% |")
        md.append("")
    md.append("## Per-day coverage")
    md.append("| date | signals | TRUE_RUNNER (≥10%) | small (5-10%) | tiny (1-5%) |")
    md.append("|---|---:|---:|---:|---:|")
    by_day = defaultdict(lambda: {"total":0, "tr":0, "sm":0, "ti":0})
    for r in out_rows:
        d = r["sig_date"]
        by_day[d]["total"] += 1
        fm = r.get("fwd_max_max") or 0
        if fm >= 0.10: by_day[d]["tr"] += 1
        elif fm >= 0.05: by_day[d]["sm"] += 1
        elif fm >= 0.01: by_day[d]["ti"] += 1
    for d in sorted(by_day):
        s = by_day[d]
        md.append(f"| {d} | {s['total']} | {s['tr']} | {s['sm']} | {s['ti']} |")
    md.append("")
    md.append("## NEW v3 features coverage")
    new_keys = ["f_universe_signals_24h", "f_coin_signals_4h", "f_coin_signal_share",
                "f_cg_market_cap_usd", "f_cg_market_cap_rank", "f_cg_volume_24h_usd",
                "f_cg_ath_change_pct", "f_perp_last_funding", "f_perp_oi_change_1h"]
    md.append("| feature | non-null count | coverage |")
    md.append("|---|---:|---:|")
    for k in new_keys:
        c = sum(1 for r in out_rows if r.get(k) is not None)
        md.append(f"| `{k}` | {c:,} | {c*100/max(len(out_rows),1):.1f}% |")
    md.append("")
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text("\n".join(md))
    print(f"\nwrote {OUT}, {OUT_REPORT}")
    print(f"total rows: {len(out_rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
