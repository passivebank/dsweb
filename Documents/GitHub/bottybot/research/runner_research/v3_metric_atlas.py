"""
research/runner_research/v3_metric_atlas.py — atlas of every recorded metric.

For each numeric feature in our dataset, computes (across the labeled
population of 4,259 unique signal moments):

  COVERAGE / DISTRIBUTION
    - non-null count, coverage %
    - p5, p25, p50 (median), p75, p95, mean, std
    - simple histogram of value bands

  BEHAVIOR DURING RUNS vs NOT
    - median + IQR for each forward-outcome bucket:
        FLAT       : fwd_max_max < 1%
        TINY       : 1-5%
        SMALL      : 5-10%
        MINOR      : 10-30%
        TRUE_RUN   : ≥30%
    - shows how the metric changes between losers and winners

  PREDICTIVE POWER PER HORIZON
    - AUC at fwd_max_5m ≥ 1%, 2%, 3%, 5%
    - AUC at fwd_max_max ≥ 5%, 10%, 30%
    - Top quartile WR vs bottom quartile WR for each target
    - Direction (does HIGH or LOW value predict winners?)
    - Bootstrap 95% CI on AUC

  RECOMMENDED THRESHOLD
    - Best single threshold + the WR/lift it produces (5m horizon, 2%)

Output:
  - research/runner_research/METRIC_ATLAS.md (human-readable)
  - research/runner_research/metric_atlas.csv (machine-readable rows)
"""
from __future__ import annotations

import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

LABELED   = Path("/tmp/runner_research/v3_labeled.jsonl.gz")
OUT_MD    = Path("research/runner_research/METRIC_ATLAS.md")
OUT_CSV   = Path("research/runner_research/metric_atlas.csv")

OUTCOME_BUCKETS = [
    ("FLAT",     -1e9, 0.01),
    ("TINY",      0.01, 0.05),
    ("SMALL",     0.05, 0.10),
    ("MINOR",     0.10, 0.30),
    ("TRUE_RUN",  0.30, 1e9),
]

PRED_TARGETS = [
    ("p_1pct_5m",   "fwd_max_5m",  0.01),
    ("p_2pct_5m",   "fwd_max_5m",  0.02),
    ("p_3pct_5m",   "fwd_max_5m",  0.03),
    ("p_5pct_5m",   "fwd_max_5m",  0.05),
    ("p_5pct_max",  "fwd_max_max", 0.05),
    ("p_10pct_max", "fwd_max_max", 0.10),
    ("p_30pct_max", "fwd_max_max", 0.30),
]


def coerce(v):
    if v is None: return None
    if isinstance(v, bool): return 1.0 if v else 0.0
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f): return None
        return f
    except (TypeError, ValueError): return None


def auc(values, labels):
    n_pos = int(labels.sum()); n_neg = int((1 - labels).sum())
    if n_pos == 0 or n_neg == 0: return float("nan")
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values))
    ranks[order] = np.arange(1, len(values) + 1)
    sorted_vals = values[order]
    i = 0
    while i < len(sorted_vals):
        j = i
        while j + 1 < len(sorted_vals) and sorted_vals[j + 1] == sorted_vals[i]: j += 1
        if j > i:
            avg = (ranks[order[i]] + ranks[order[j]]) / 2
            ranks[order[i:j+1]] = avg
        i = j + 1
    return float((ranks[labels == 1].sum() - n_pos*(n_pos+1)/2) / (n_pos*n_neg))


def bootstrap_auc_ci(vals, labs, iters=300):
    n = len(vals)
    rng = np.random.default_rng(42)
    aucs = []
    for _ in range(iters):
        idx = rng.integers(0, n, n)
        try: aucs.append(auc(vals[idx], labs[idx]))
        except: pass
    aucs = [a for a in aucs if not math.isnan(a)]
    if len(aucs) < 30: return (float("nan"), float("nan"))
    return float(np.percentile(aucs, 2.5)), float(np.percentile(aucs, 97.5))


def categorize(fwd_max):
    for name, lo, hi in OUTCOME_BUCKETS:
        if lo <= (fwd_max or 0) < hi: return name
    return "FLAT"


def load_data():
    rows = []
    with gzip.open(LABELED, "rt") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            rows.append(json.loads(line))
    return rows


def feature_explanations() -> dict[str, str]:
    """Plain-language explanation of what each feature MEANS."""
    return {
        "f_ret_24h": "24-hour price change (fraction). 0.5 = +50% vs 24h ago.",
        "f_btc_dom_pct": "BTC's share of total crypto mcap (%). Higher = BTC outperforming alts.",
        "f_btc_ret_1h": "BTC 1-hour return — short-term BTC momentum.",
        "f_btc_rel_ret_5m": "Coin's 5min return MINUS BTC's 5min return. Positive = outperforming.",
        "f_fear_greed": "Daily F&G index (0-100). Higher = greedier sentiment.",
        "f_cvd_30s": "Cumulative volume delta over 30s (buy_usd - sell_usd). Negative = net selling.",
        "f_cvd_60s": "Same as cvd_30s but over 60s window — slightly longer-term flow.",
        "f_spread_bps": "Bid-ask spread at signal, in basis points (1bp = 0.01%).",
        "f_spread_bps_at_entry": "Spread at the actual entry moment (slightly later than sig).",
        "f_signals_24h": "How many signals THIS coin has fired today. High = noise day OR coin is running hard.",
        "f_signals_1h": "Per-coin signals in last 1h. Same idea, shorter window.",
        "f_universe_signals_24h": "How many DISTINCT coins fired any signal today. Universe-level activity.",
        "f_coin_signal_share": "This coin's signal share = signals_24h / universe_signals_24h.",
        "f_coin_signals_4h": "Rolling 4h count of signals for THIS coin. Activity proxy.",
        "f_step_1m": "1-minute bar return. The last completed minute candle's % change.",
        "f_step_2m": "2-minute bar return — the 2nd minute back.",
        "f_step_3m": "3-minute bar return — the 3rd minute back.",
        "f_total_3m": "Cumulative 3-min return (sum of last 3 1m bars).",
        "f_rank_60s": "This coin's rank by 60s return, across all monitored coins. 1 = top mover.",
        "f_secs_since_onset": "Seconds elapsed between move onset and signal. Low = fresh, high = late.",
        "f_market_breadth_5m": "Count of coins with positive 5m return across universe.",
        "f_ask_depth_usd": "Total USD value resting on top-10 ask levels. Higher = thicker book sell side.",
        "f_bid_depth_usd": "Total USD value resting on top-10 bid levels.",
        "f_ask_depth_trend": "Ask depth now / ask depth 60s ago. >1 = sellers stacking, <1 = book thinning.",
        "f_book_imbalance_10": "bid_depth_10 / ask_depth_10 ratio. >1 = more buyers below than sellers above.",
        "f_avg_trade_size_60s": "Average $ size of trades in last 60s. Higher = bigger players in.",
        "f_large_trade_pct_60s": "Fraction of last 60s volume from trades ≥ $500. Whale presence.",
        "f_buy_share_60s": "Fraction of trades that were taker-buys in last 60s.",
        "f_higher_lows_3m": "Boolean: did the coin make higher lows over the last 3 minutes?",
        "f_first_signal_today": "Boolean: is this the FIRST signal for this coin today?",
        "f_candle_close_str_1m": "(close - low) / (high - low) for the 1m candle. 1.0 = closed at high.",
        "f_vwap_300s": "5-minute VWAP for this coin.",
        "f_cg_trending": "Boolean: was this coin on the CoinGecko trending list at signal time?",
        "f_utc_hour": "UTC hour of day (0-23). Time-of-day pattern.",
        "f_pullback_from_peak": "How far below recent peak the price is at signal time (fraction).",
        "f_peak_gain_pct": "Coin's gain from session low to recent peak.",
        "f_run_peak_mid": "Recent peak mid-price during the active run.",
        "f_run_signal_mid": "Mid-price at the signal moment.",
        "f_secs_since_run": "Seconds since the run was first detected.",
        "f_hold_ratio": "Some position-holding ratio (recorder-internal).",
        "f_rate_30s": "Rate of price change in last 30s.",
        "f_dv_30s_usd": "Dollar volume in last 30s.",
        "f_dv_30s_mult": "Ratio of dv_30s to a baseline — volume spike strength.",
        "f_move_from_5m_low": "How much the price has moved from the 5-min low (fraction).",
    }


def main():
    rows = load_data()
    print(f"loaded {len(rows)} signal moments")

    # Categorize each row by outcome
    for r in rows:
        r["_outcome"] = categorize(r.get("fwd_max_max"))

    # All numeric feature columns
    feat_cols = sorted({k for r in rows for k in r if k.startswith("f_")})
    print(f"feature columns: {len(feat_cols)}")

    explanations = feature_explanations()

    md = ["# METRIC ATLAS — every feature, every horizon\n\n"]
    md.append(f"_Source: {len(rows)} unique signal moments, 14 days (2026-04-11 → 2026-04-27)._\n\n")
    md.append(f"_Outcome buckets are based on `fwd_max_max` (max forward gain across all simulator policies):_\n")
    md.append("- **FLAT**: <1% peak\n")
    md.append("- **TINY**: 1-5%\n")
    md.append("- **SMALL**: 5-10%\n")
    md.append("- **MINOR**: 10-30%\n")
    md.append("- **TRUE_RUN**: ≥30%\n\n")
    bucket_counts = defaultdict(int)
    for r in rows: bucket_counts[r["_outcome"]] += 1
    md.append("**Population per bucket:**\n\n")
    md.append("| bucket | n | pct |\n|---|---:|---:|\n")
    for name, _, _ in OUTCOME_BUCKETS:
        n = bucket_counts.get(name, 0)
        md.append(f"| {name} | {n:,} | {n*100/len(rows):.2f}% |\n")
    md.append("\n---\n\n")

    csv_lines = ["feature,coverage_pct,median,p25,p75,direction_5pct_5m,auc_1pct_5m,auc_2pct_5m,auc_3pct_5m,auc_5pct_5m,auc_5pct_max,auc_10pct_max,auc_30pct_max,top_q_wr_5pct_5m,bot_q_wr_5pct_5m,best_threshold,best_threshold_lift"]

    # Iterate every feature
    for feat in feat_cols:
        # Collect values (None where missing)
        vals_with_outcome = []
        for r in rows:
            v = coerce(r.get(feat))
            if v is None: continue
            vals_with_outcome.append({
                "v":         v,
                "outcome":   r["_outcome"],
                "fwd_5m":    r.get("fwd_max_5m") or 0,
                "fwd_max":   r.get("fwd_max_max") or 0,
            })
        if len(vals_with_outcome) < 100: continue
        coverage = len(vals_with_outcome) / len(rows)
        if coverage < 0.30: continue

        v_arr = np.array([x["v"] for x in vals_with_outcome])
        if v_arr.std() == 0: continue   # constant feature, no use

        # Distribution
        p5, p25, p50, p75, p95 = np.percentile(v_arr, [5, 25, 50, 75, 95])
        mean, std = float(v_arr.mean()), float(v_arr.std())

        # Per-outcome breakdown
        per_bucket = {}
        for name, _, _ in OUTCOME_BUCKETS:
            sub = [x["v"] for x in vals_with_outcome if x["outcome"] == name]
            if sub:
                per_bucket[name] = {
                    "n":     len(sub),
                    "median": float(np.median(sub)),
                    "p25":   float(np.percentile(sub, 25)),
                    "p75":   float(np.percentile(sub, 75)),
                    "mean":  float(np.mean(sub)),
                }

        # Predictive power per target
        per_target = {}
        for tname, tcol, thr in PRED_TARGETS:
            labels = np.array([
                1 if (x["fwd_5m" if tcol == "fwd_max_5m" else "fwd_max"]) >= thr else 0
                for x in vals_with_outcome
            ])
            if labels.sum() < 5 or (1 - labels).sum() < 5:
                per_target[tname] = None; continue
            a = auc(v_arr, labels)
            ci_lo, ci_hi = bootstrap_auc_ci(v_arr, labels)
            per_target[tname] = {
                "auc":   a,
                "ci_lo": ci_lo,
                "ci_hi": ci_hi,
                "discrim": abs(a - 0.5),
                "direction": "+" if a >= 0.5 else "-",
            }

        # Top/bottom quartile WR for the 5pct/5m target (the user's main mission)
        labels_5pct = np.array([1 if x["fwd_5m"] >= 0.05 else 0 for x in vals_with_outcome])
        try:
            q25, q75 = np.percentile(v_arr, [25, 75])
            top = labels_5pct[v_arr >= q75]
            bot = labels_5pct[v_arr <= q25]
            top_q_wr = float(top.mean()) if len(top) else float("nan")
            bot_q_wr = float(bot.mean()) if len(bot) else float("nan")
        except Exception:
            top_q_wr = bot_q_wr = float("nan")

        # Best single threshold scan for 5pct/5m
        best_lift = 0.0; best_threshold = None; base_rate = labels_5pct.mean()
        # Try cuts at percentiles
        for pct in [10, 20, 30, 40, 50, 60, 70, 80, 90]:
            cut = float(np.percentile(v_arr, pct))
            for direction in ("≥", "<"):
                if direction == "≥":
                    mask = v_arr >= cut
                else:
                    mask = v_arr < cut
                if mask.sum() < 50: continue
                lift = labels_5pct[mask].mean() / max(base_rate, 1e-9)
                if lift > best_lift:
                    best_lift = lift
                    best_threshold = (cut, direction, int(mask.sum()))

        # ── Render this feature ────────────────────────────────────────
        md.append(f"## `{feat}`\n\n")
        if explanations.get(feat):
            md.append(f"_{explanations[feat]}_\n\n")
        md.append(f"**Coverage**: {coverage*100:.1f}% of signals · "
                  f"**range**: [{p5:.4g}, {p95:.4g}] · "
                  f"**median**: {p50:.4g} · "
                  f"**IQR**: [{p25:.4g}, {p75:.4g}] · "
                  f"**mean ± std**: {mean:.4g} ± {std:.4g}\n\n")

        # Bucket comparison table
        md.append("**How does this metric change across outcomes?**\n\n")
        md.append("| outcome | n | median | IQR |\n|---|---:|---:|---|\n")
        for name, _, _ in OUTCOME_BUCKETS:
            b = per_bucket.get(name)
            if b is None:
                md.append(f"| {name} | 0 | — | — |\n")
                continue
            md.append(f"| {name} | {b['n']} | {b['median']:.4g} | "
                      f"[{b['p25']:.4g}, {b['p75']:.4g}] |\n")
        md.append("\n")

        # AUC table
        md.append("**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)\n\n")
        md.append("| target | n | AUC | 95% CI | direction |\n")
        md.append("|---|---:|---:|---|:---:|\n")
        for tname, _, _ in PRED_TARGETS:
            t = per_target.get(tname)
            if t is None:
                md.append(f"| {tname} | — | — | — | — |\n"); continue
            n_total = len(vals_with_outcome)
            ci = f"[{t['ci_lo']:.3f}, {t['ci_hi']:.3f}]" if not math.isnan(t['ci_lo']) else "—"
            warn = ""
            if not math.isnan(t['ci_lo']) and not math.isnan(t['ci_hi']):
                if (t['ci_lo'] > 0.55 and t['ci_hi'] > 0.55) or (t['ci_lo'] < 0.45 and t['ci_hi'] < 0.45):
                    warn = " ★"
            md.append(f"| {tname} | {n_total} | {t['auc']:.3f} | {ci} | {t['direction']}{warn} |\n")
        md.append("\n")

        # Quartile spread for 5pct target
        if not math.isnan(top_q_wr):
            md.append(f"**Top quartile (high values) WR @ +5%/5min**: {top_q_wr*100:.1f}%   ·   "
                      f"**Bottom quartile (low values) WR**: {bot_q_wr*100:.1f}%\n\n")
            best = ""
            if best_threshold:
                cut, dir_str, n_passing = best_threshold
                hit_pct = labels_5pct[(v_arr >= cut) if dir_str == "≥" else (v_arr < cut)].mean()
                md.append(f"**Best single-threshold rule for +5%/5min**: "
                          f"`{feat} {dir_str} {cut:.4g}` → {n_passing} signals, "
                          f"{hit_pct*100:.1f}% hit rate (lift {best_lift:.2f}× vs base {base_rate*100:.1f}%)\n\n")

        # Practical takeaway lines
        # 1. Direction: do high values or low values mean a winner?
        target_5m_2pct = per_target.get("p_2pct_5m") or {}
        if target_5m_2pct:
            d = target_5m_2pct["direction"]
            disc = target_5m_2pct["discrim"]
            sense = "high values predict winners" if d == "+" else "low values predict winners"
            md.append(f"**Takeaway**: at the 1-10 min horizon, **{sense}** "
                      f"(discrimination = {disc:.3f}; CI {ci}).\n\n")

        md.append("---\n\n")

        # CSV row
        thresh_str = ""
        if best_threshold:
            cut, dir_str, _ = best_threshold
            thresh_str = f"{dir_str}{cut:.4g}"
        a_5pct_5m = (per_target.get("p_5pct_5m") or {}).get("auc") or float("nan")
        d_5pct_5m = (per_target.get("p_5pct_5m") or {}).get("direction") or "?"
        csv_lines.append(",".join([
            feat, f"{coverage*100:.1f}",
            f"{p50:.6g}", f"{p25:.6g}", f"{p75:.6g}",
            d_5pct_5m,
            f"{(per_target.get('p_1pct_5m') or {}).get('auc') or 0:.4f}",
            f"{(per_target.get('p_2pct_5m') or {}).get('auc') or 0:.4f}",
            f"{(per_target.get('p_3pct_5m') or {}).get('auc') or 0:.4f}",
            f"{a_5pct_5m:.4f}",
            f"{(per_target.get('p_5pct_max') or {}).get('auc') or 0:.4f}",
            f"{(per_target.get('p_10pct_max') or {}).get('auc') or 0:.4f}",
            f"{(per_target.get('p_30pct_max') or {}).get('auc') or 0:.4f}",
            f"{top_q_wr if not math.isnan(top_q_wr) else 0:.4f}",
            f"{bot_q_wr if not math.isnan(bot_q_wr) else 0:.4f}",
            thresh_str,
            f"{best_lift:.2f}",
        ]))

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("".join(md))
    OUT_CSV.write_text("\n".join(csv_lines))
    print(f"\nwrote {OUT_MD}")
    print(f"wrote {OUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
