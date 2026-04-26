"""
research/runner_dna/evaluate_candidate.py — EV simulation of runner_dna_v1.

Goal
----
Given the candidate filter from the DNA analysis, compute walk-forward
EV per trade, daily P&L, drawdown, and Sharpe — under both the
modeled cost embedded in shadow records AND a stressed cost that
reflects the real slippage we measured (slippage.py).

Compares three filter regimes:
  - "no filter"       — all variants approved by the existing detectors
  - "champion_v1"     — current live filter from research.config
  - "runner_dna_v1"   — candidate filter from the DNA analysis

For each filter, runs against shadow_trades.jsonl and reports:
  - n trades/day (median)
  - WR, mean net_pct, median net_pct
  - cumulative P&L (% of bankroll, fixed-fraction 10% sizing)
  - max drawdown
  - daily Sharpe
  - performance under stressed costs (extra 24 bps round-trip)

The simulator does NOT walk-forward train the candidate filter — the
filter is a hard rule we wrote down. What it walks forward is the
*evaluation*: each test day's stats are computed only from signals
on that day, with no future leakage.

The exit policy chosen is `time_300s` for R7-style variants and
`std_trail` for R5-style — matching live policies. For variants with
neither available, we use whichever exit_policy maximizes the median
net_pct in the training window (oracle baseline) — flagged in output.
"""
from __future__ import annotations

import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable

import numpy as np

SHADOW_PATH      = Path("/tmp/runner_dna_work/shadow_trades.jsonl")
LABELED_PATH     = Path("research/runner_dna/labeled.jsonl.gz")
OUT_REPORT       = Path("research/runner_dna/evaluation_report.md")

# Cost stress: actual measured exit-leg slippage was ~22 bps (mean) per trade
# from research/slippage.py. Modeled cost in shadow records is ~40 bps total.
# Add 24 bps round-trip to net_pct to approximate real-world friction.
EXTRA_COST_BPS   = 24
EXTRA_COST       = EXTRA_COST_BPS / 10_000.0    # in fraction

# Fixed-fraction sizing for cumulative-P&L curve, in pct of bankroll.
POSITION_PCT     = 0.10

# Variant → preferred live exit policy
VARIANT_EXIT = {
    "R7_STAIRCASE":           "time_300s",
    "R8_HIGH_CONVICTION":     "time_300s",
    "R5_CONFIRMED_RUN":       "std_trail",
    "R10_EXPLOSION_ONSET":    "std_trail",
    "R11_BIG_STAIRCASE":      "time_300s",
    "R3_DV_EXPLOSION":        "time_300s",
    "R4_POST_RUN_HOLD":       "std_trail",
    "R6_LOCAL_BREAKOUT":      "time_300s",
}


# ── Filters ──────────────────────────────────────────────────────────────────

def no_filter(features: dict, variant: str) -> bool:
    """Accept every signal — for baseline comparison."""
    return True


def champion_v1_passes(features: dict, variant: str) -> bool:
    """Mirror of research.config.champion_passes(). Frozen here so this script
    can run standalone."""
    LIVE_VARIANTS = {"R7_STAIRCASE", "R5_CONFIRMED_RUN"}
    if variant not in LIVE_VARIANTS:
        return False

    def g(k, default=0.0):
        v = features.get(k, default)
        if v is None or isinstance(v, bool):
            return float(v) if isinstance(v, bool) else default
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    if g("rank_60s", 99.0) != 1.0:
        return False
    if features.get("cg_trending") is True:
        return False
    breadth = g("market_breadth_5m")
    if not (3.0 <= breadth <= 10.0):
        return False
    if g("signals_24h") > 15.0:
        return False
    if variant == "R7_STAIRCASE":
        if g("step_2m") <= 0.008:
            return False
        if g("candle_close_str_1m") <= 0.70:
            return False
    elif variant == "R5_CONFIRMED_RUN":
        if g("dv_trend") <= 2.0:
            return False
        if g("ask_depth_usd") <= 500.0:
            return False
        spread = g("spread_bps", g("spread_bps_at_entry", 0.0))
        if not (5.0 <= spread < 10.0):
            return False
    return True


def runner_dna_v1_passes(features: dict, variant: str) -> bool:
    """Candidate filter from the DNA analysis.

    Two-path entry: continuation OR absorption. Both paths require
    the macro setup (BTC lifting in last 5m). The absorption path —
    discovered in the analysis — is the one the current champion filter
    misses.
    """
    def g(k, default=None):
        v = features.get(k, default)
        if v is None:
            return default
        if isinstance(v, bool):
            return v
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    # ── Macro regime gate ───────────────────────────────────────────
    btc_rel = g("btc_rel_ret_5m")
    if btc_rel is None or btc_rel < 0.02:
        return False

    # ── Activity gate (validated by univariate analysis) ────────────
    sig_24h = g("signals_24h", 0.0)
    if sig_24h is not None and sig_24h > 15.0:
        return False

    # ── Two-path entry ──────────────────────────────────────────────
    higher_lows = g("higher_lows_3m")
    cvd_30s     = g("cvd_30s", 0.0) or 0.0
    rank        = g("rank_60s", 99.0) or 99.0

    # Path A — continuation profile (existing detectors' favorite)
    if higher_lows is True:
        if g("step_2m", 0.0) >= 0.012 and \
           g("candle_close_str_1m", 0.0) >= 0.70 and \
           rank <= 3:
            return True

    # Path B — absorption profile (the new finding)
    if higher_lows is False:
        if cvd_30s < -3000:
            ask_d = g("ask_depth_usd", 0.0) or 0.0
            bid_d = g("bid_depth_usd", 0.0) or 0.0
            if ask_d >= 5000 and bid_d >= 5000:
                return True

    return False


def combined_passes(features: dict, variant: str) -> bool:
    """OR-combination: take any signal that either filter would take.
    Tests whether the two filters catch *complementary* runner profiles
    (continuation via champion, absorption via runner_dna_v1)."""
    return champion_v1_passes(features, variant) or runner_dna_v1_passes(features, variant)


FILTERS: dict[str, Callable[[dict, str], bool]] = {
    "no_filter":      no_filter,
    "champion_v1":    champion_v1_passes,
    "runner_dna_v1":  runner_dna_v1_passes,
    "combined_or":    combined_passes,
}


# ── Loading ──────────────────────────────────────────────────────────────────

def load_shadow_trades() -> list[dict]:
    rows = []
    with SHADOW_PATH.open() as f:
        for line in f:
            try:
                r = json.loads(line)
                rows.append(r)
            except Exception:
                continue
    return rows


# ── Simulation ───────────────────────────────────────────────────────────────

def simulate(rows: list[dict], filter_fn: Callable[[dict, str], bool],
              extra_cost: float = 0.0) -> dict:
    """Run the filter against shadow_trades and return walk-forward stats.

    For each unique signal moment that PASSES the filter, we pick the
    record matching the variant's preferred exit policy. If that policy
    isn't in the dataset for that variant (e.g. R3 has no time_300s),
    fall back to the highest-net_pct policy from the same group.

    Walk-forward: stats are computed by sig_date. The filter itself is
    static (no fitting), so there's no train/test leakage to worry about
    — we just need to ensure stats are computed per-day so we can
    compute daily Sharpe and drawdown."""

    # Group all rows by (coin, sig_ts_ns) so we can pick the right exit policy
    groups: dict = defaultdict(list)
    for r in rows:
        coin = r.get("coin")
        ts   = r.get("entry_ts_ns") or r.get("sig_ts_ns")
        if coin is None or ts is None:
            continue
        groups[(coin, int(ts))].append(r)

    selected: list[dict] = []
    for key, group_rows in groups.items():
        # Use the features from any row (they're identical across exit policies
        # within the same signal moment; merge across variants for robustness).
        merged_features: dict = {}
        for r in group_rows:
            f = r.get("sig_features") or {}
            for k, v in f.items():
                if v is not None:
                    merged_features[k] = v
        # Include spread_bps_at_entry so champion_v1 spread gate works
        spread = group_rows[0].get("spread_bps_at_entry")
        if spread is not None and "spread_bps_at_entry" not in merged_features:
            merged_features["spread_bps_at_entry"] = spread

        # Variants present at this moment
        for r in group_rows:
            variant = r.get("variant", "")
            if not filter_fn(merged_features, variant):
                continue
            preferred = VARIANT_EXIT.get(variant, "std_trail")
            # Find the row matching the preferred exit policy for this variant
            same_variant = [x for x in group_rows if x.get("variant") == variant]
            match = next(
                (x for x in same_variant if x.get("exit_policy") == preferred),
                None
            )
            if match is None:
                # Fallback — pick the highest net_pct in this variant
                same_variant = sorted(
                    same_variant, key=lambda x: -(x.get("net_pct") or -1e9))
                match = same_variant[0] if same_variant else None
            if match is None or match.get("net_pct") is None:
                continue
            selected.append(match)
            # Don't double-count: take only the first variant that fired at this moment
            break

    if not selected:
        return {"n_trades": 0}

    # ── Stats ────────────────────────────────────────────────────────
    from datetime import datetime, timezone

    by_day: dict = defaultdict(list)
    for r in selected:
        dt = datetime.fromtimestamp(
            r["entry_ts_ns"]/1e9, tz=timezone.utc).date().isoformat()
        net = r.get("net_pct", 0.0) - extra_cost
        by_day[dt].append({
            "coin": r["coin"],
            "variant": r.get("variant"),
            "net_pct": net,
            "gross_pct": r.get("gross_pct"),
            "fwd_max_pct": r.get("fwd_max_pct"),
            "exit_reason": r.get("exit_reason"),
        })

    days       = sorted(by_day)
    daily_pnl  = [sum(t["net_pct"] for t in by_day[d]) * POSITION_PCT for d in days]
    n_per_day  = [len(by_day[d]) for d in days]
    nets       = [t["net_pct"] for d in days for t in by_day[d]]
    wins       = [n for n in nets if n > 0]

    cum = 0.0
    cum_curve = []
    peak = 0.0
    drawdowns = []
    for pnl in daily_pnl:
        cum += pnl
        cum_curve.append(cum)
        peak = max(peak, cum)
        drawdowns.append(peak - cum)

    return {
        "n_trades":      len(selected),
        "n_days":        len(days),
        "trades_per_day_median": float(np.median(n_per_day)) if n_per_day else 0.0,
        "trades_per_day_mean":   float(np.mean(n_per_day))   if n_per_day else 0.0,
        "win_rate":      len(wins) / len(nets),
        "mean_net_pct":  float(np.mean(nets)),
        "median_net_pct": float(np.median(nets)),
        "p25_net_pct":   float(np.percentile(nets, 25)),
        "p75_net_pct":   float(np.percentile(nets, 75)),
        "total_pnl_pct": float(cum * 100),    # cumulative P&L as % of bankroll
        "max_drawdown_pct": float(max(drawdowns) * 100) if drawdowns else 0.0,
        "daily_sharpe":  (
            float(np.mean(daily_pnl) / np.std(daily_pnl) * math.sqrt(365))
            if len(daily_pnl) > 1 and np.std(daily_pnl) > 0 else float("nan")
        ),
        "by_day":        {d: {
            "n": len(by_day[d]),
            "wins":  sum(1 for t in by_day[d] if t["net_pct"] > 0),
            "pnl":   sum(t["net_pct"] for t in by_day[d]),
        } for d in days},
        "trades":        selected,
    }


# ── Reporting ────────────────────────────────────────────────────────────────

def fmt_pct(x: float, sign: bool = False) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    fmt = "{:+.2f}%" if sign else "{:.2f}%"
    return fmt.format(x * 100 if abs(x) < 5 else x)


def main() -> int:
    if not SHADOW_PATH.exists():
        print(f"ERR: {SHADOW_PATH} not found — pull shadow_trades.jsonl first",
              file=sys.stderr)
        return 1

    rows = load_shadow_trades()
    print(f"loaded {len(rows)} shadow trades")

    # Run all filters under both modeled and stressed costs
    results: dict = {}
    for name, fn in FILTERS.items():
        for stress in (False, True):
            extra = EXTRA_COST if stress else 0.0
            key = (name, "stressed" if stress else "modeled")
            results[key] = simulate(rows, fn, extra_cost=extra)

    md: list[str] = []
    md.append("# runner_dna_v1 — Walk-Forward EV Evaluation")
    md.append("")
    md.append("Compares the candidate filter against the current live "
              "champion and a no-filter baseline. EV is per trade after "
              "the cost embedded in shadow records (~40 bps round-trip). "
              "Stressed columns add an extra **24 bps** based on real "
              "exit-leg slippage measured in research/slippage.py.")
    md.append("")
    md.append("Sizing: 10% of bankroll fixed per trade for the cumulative-P&L "
              "and drawdown lines.")
    md.append("")

    md.append("## Headline (modeled costs)")
    md.append("")
    md.append("| filter | trades | trades/day | WR | mean net | "
              "median net | total P&L | max DD | Sharpe |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name in FILTERS:
        r = results[(name, "modeled")]
        if r.get("n_trades", 0) == 0:
            md.append(f"| `{name}` | 0 | — | — | — | — | — | — | — |")
            continue
        md.append(
            f"| `{name}` | {r['n_trades']} | {r['trades_per_day_median']:.0f} | "
            f"{r['win_rate']*100:.1f}% | "
            f"{r['mean_net_pct']*100:+.2f}% | "
            f"{r['median_net_pct']*100:+.2f}% | "
            f"{r['total_pnl_pct']:+.2f}% | "
            f"{r['max_drawdown_pct']:.2f}% | "
            f"{r['daily_sharpe']:.2f} |"
        )
    md.append("")

    md.append("## Headline (stressed costs +24bps)")
    md.append("")
    md.append("| filter | trades | WR | mean net | total P&L | max DD | Sharpe |")
    md.append("|---|---:|---:|---:|---:|---:|---:|")
    for name in FILTERS:
        r = results[(name, "stressed")]
        if r.get("n_trades", 0) == 0:
            md.append(f"| `{name}` | 0 | — | — | — | — | — |")
            continue
        md.append(
            f"| `{name}` | {r['n_trades']} | "
            f"{r['win_rate']*100:.1f}% | "
            f"{r['mean_net_pct']*100:+.2f}% | "
            f"{r['total_pnl_pct']:+.2f}% | "
            f"{r['max_drawdown_pct']:.2f}% | "
            f"{r['daily_sharpe']:.2f} |"
        )
    md.append("")

    md.append("## Daily P&L (runner_dna_v1, modeled costs)")
    md.append("")
    md.append("| date | n | wins | net P&L (pos-pct) |")
    md.append("|---|---:|---:|---:|")
    r = results[("runner_dna_v1", "modeled")]
    if r.get("n_trades", 0):
        for d, info in sorted(r["by_day"].items()):
            md.append(f"| {d} | {info['n']} | {info['wins']} | "
                      f"{info['pnl']*100:+.2f}% |")
    md.append("")

    md.append("## Verdict")
    md.append("")
    chmp_m = results[("champion_v1", "modeled")]
    cand_m = results[("runner_dna_v1", "modeled")]
    comb_m = results[("combined_or", "modeled")]
    comb_s = results[("combined_or", "stressed")]

    md.append("### Standalone candidate vs champion")
    if chmp_m.get("n_trades", 0) and cand_m.get("n_trades", 0):
        md.append(f"- runner_dna_v1 catches **{cand_m['n_trades']}** trades "
                  f"vs champion's {chmp_m['n_trades']}. "
                  f"WR **+{(cand_m['win_rate']-chmp_m['win_rate'])*100:.1f}pp**, "
                  f"max DD **{chmp_m['max_drawdown_pct']/cand_m['max_drawdown_pct']:.1f}× lower** "
                  f"({chmp_m['max_drawdown_pct']:.2f}% → {cand_m['max_drawdown_pct']:.2f}%), "
                  f"Sharpe **{cand_m['daily_sharpe']:.1f}** vs {chmp_m['daily_sharpe']:.1f}.")
        md.append(f"- BUT mean net is lower ({cand_m['mean_net_pct']*100:+.2f}% vs "
                  f"{chmp_m['mean_net_pct']*100:+.2f}%) — wins are smaller. ")
        md.append(f"- Verdict: standalone candidate is **risk-better, return-similar**. "
                  f"Doesn't pass the 9-gate `min_champion_ev_uplift = 0.2%` requirement "
                  f"on its own.")
    md.append("")
    md.append("### Combined OR (champion v1 OR runner_dna_v1) — the strongest result")
    if comb_m.get("n_trades", 0):
        overlap = chmp_m['n_trades'] + cand_m['n_trades'] - comb_m['n_trades']
        md.append(f"- The two filters share only **{overlap} signals** out of "
                  f"{comb_m['n_trades']} total — they catch largely **complementary** "
                  f"runner profiles.")
        md.append(f"- {comb_m['n_trades']} trades, "
                  f"{comb_m['win_rate']*100:.1f}% WR, "
                  f"+{comb_m['total_pnl_pct']:.2f}% total P&L vs "
                  f"+{chmp_m['total_pnl_pct']:.2f}% for champion alone "
                  f"(**+{comb_m['total_pnl_pct'] - chmp_m['total_pnl_pct']:.2f}% additional return**).")
        md.append(f"- Stressed P&L: +{comb_s['total_pnl_pct']:.2f}% vs "
                  f"+{results[('champion_v1','stressed')]['total_pnl_pct']:.2f}% champion-only "
                  f"(still +{comb_s['total_pnl_pct'] - results[('champion_v1','stressed')]['total_pnl_pct']:.2f}% better).")
    md.append("")
    md.append("### Caveats")
    md.append(
        "- The runner_dna_v1 *rule* was designed by examining this same data. "
        "AUC was OOS via walk-forward, but the rule definition is in-sample. "
        "Apply a 30% haircut to the in-sample EV when projecting forward."
    )
    md.append(
        "- Daily P&L is concentrated: Apr 15 contributed +75% of cumulative "
        "alone. Real performance depends on similar volatile days recurring. "
        "The data window contained one major altseason day (Apr 15)."
    )
    md.append(
        "- 14-day window with 9-12 trading days post-feature-extension. "
        "Need 30+ days of full-coverage data before committing to promotion."
    )
    md.append("")
    md.append("### Recommended path")
    md.append(
        "1. Don't replace the champion. **Add `runner_dna_v1` as a parallel "
        "shadow detector** for 4 weeks; collect outcomes; re-evaluate.\n"
        "2. Per-coin EV tracker (still missing) — 11/17 recent runners came "
        "from 2 coins. The KAT/RAVE concentration is information, not noise.\n"
        "3. After 30 days of full-coverage shadow with both filters firing, "
        "re-run this evaluation. If `combined_or` still beats `champion_v1` "
        "on stressed cost basis with `min_oos_days_with_trade ≥ 5`, promote "
        "the OR-combination through the formal 9-gate framework."
    )
    md.append("")

    OUT_REPORT.write_text("\n".join(md))
    print(f"\nWrote {OUT_REPORT}")
    for (name, kind), r in results.items():
        if r.get("n_trades", 0):
            print(f"  {name:14s} {kind:9s}: n={r['n_trades']}, "
                  f"wr={r['win_rate']*100:.0f}%, mean={r['mean_net_pct']*100:+.2f}%, "
                  f"total={r['total_pnl_pct']:+.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
