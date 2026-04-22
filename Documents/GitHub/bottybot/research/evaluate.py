"""
research/evaluate.py — OOS walk-forward evaluation framework.

This is the measurement core. All strategy comparison runs through here.
Nothing here trains a model — it takes a strategy callable and applies it
to data, returning metrics that can be compared across strategies.

Design rules:
  - Training data must never contaminate test data.
  - The champion filter is applied without refitting (it has no training step).
  - ML challengers must be refitted on the training slice before scoring test.
  - All metrics are net of costs already embedded in net_pct.
  - CI is computed via bootstrap, not parametric assumptions.
  - Every function documents its contamination risk explicitly.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .config import LIVE_VARIANTS, REGIMES, ADDITIONAL_SLIPPAGE, regime_label

# ── Types ─────────────────────────────────────────────────────────────────────
# A strategy is a callable that takes (features_dict, variant_str) and returns bool.
# For the champion, this is config.champion_passes.
# For ML challengers, this is a fitted model's predict method.
Strategy = Callable[[dict, str], bool]

# ── Data loading ──────────────────────────────────────────────────────────────

def load_events(
    shadow_file: Path,
    variants: Optional[list[str]] = None,
    delay_target_ms: int = 250,
    since_ts_ns: int = 0,
) -> list[dict]:
    """Load canonical events from shadow_trades.jsonl.

    One event per unique signal (coin × entry_ts_ns × variant), using the
    exit policy that matches each variant's live policy. Deduplicates across
    delay_ms variants by selecting the record closest to delay_target_ms.

    Contamination risk: NONE. This function loads raw outcomes — no model
    is fitted here and no test data sees any training data.

    Args:
        shadow_file: path to shadow_trades.jsonl
        variants:    list of variant names to include; defaults to LIVE_VARIANTS
        delay_target_ms: prefer records with this entry delay

    Returns:
        List of event dicts, sorted by entry_ts_ns ascending.
    """
    if variants is None:
        variants = list(LIVE_VARIANTS.keys())

    from .config import LIVE_VARIANTS as LV
    policy_for = {v: LV.get(v, "time_300s") for v in variants}

    # best[(coin, ts, variant)] = (dist_to_target, record)
    best: dict[tuple, tuple] = {}

    with shadow_file.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue

            v = r.get("variant", "")
            if v not in policy_for:
                continue
            expected_policy = policy_for[v]
            if r.get("exit_policy") != expected_policy:
                continue

            coin = r.get("coin")
            ts = r.get("entry_ts_ns")
            net = r.get("net_pct")
            if None in (coin, ts, net):
                continue
            if int(ts) <= since_ts_ns:
                continue

            delay = r.get("delay_ms") or 0
            dist = abs(delay - delay_target_ms)
            key = (coin, ts, v)
            prev = best.get(key)
            if prev is None or dist < prev[0]:
                best[key] = (dist, r)

    events = []
    for (coin, ts, v), (_, r) in best.items():
        feat = r.get("sig_features") or {}
        fg = feat.get("fear_greed", 50.0) or 50.0

        # Compute adjusted entry day from timestamp
        entry_dt = datetime.fromtimestamp(ts / 1e9, tz=timezone.utc)
        day_str = entry_dt.date().isoformat()

        net_pct = float(r.get("net_pct", 0.0))
        gross_pct = float(r.get("gross_pct", net_pct))

        events.append({
            "coin":          coin,
            "variant":       v,
            "entry_ts_ns":   int(ts),
            "delay_ms":      int(r.get("delay_ms") or 0),
            "day":           day_str,
            "utc_hour":      entry_dt.hour,
            "exit_policy":   r.get("exit_policy", ""),
            "exit_reason":   r.get("exit_reason", ""),
            "holding_s":     float(r.get("holding_s", 0.0)),
            "gross_pct":     gross_pct,
            "net_pct":       net_pct,
            "fwd_max_pct":   float(r.get("fwd_max_pct", 0.0)),
            "fwd_min_pct":   float(r.get("fwd_min_pct", 0.0)),
            "features":      feat,
            "regime":        regime_label(float(fg) if fg else 50.0),
            "fear_greed":    float(fg) if fg else 50.0,
            "win":           net_pct > 0.0,
        })

    events.sort(key=lambda e: e["entry_ts_ns"])
    return events


# ── Statistics helpers ────────────────────────────────────────────────────────

def wilson_ci(k: int, n: int, z: float = 1.645) -> tuple[float, float]:
    """Wilson score CI for a binomial proportion (default z=1.645 → 90% CI)."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    center = (p + z**2 / (2 * n)) / (1 + z**2 / n)
    margin  = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / (1 + z**2 / n)
    return (max(0.0, center - margin), min(1.0, center + margin))


def bootstrap_ci(
    values: list[float],
    n_boot: int = 2000,
    ci: float = 0.90,
    seed: int = 42,
) -> tuple[float, float, float]:
    """Bootstrap CI on the mean of values. Returns (mean, lo, hi)."""
    if not values:
        return (0.0, 0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(n_boot):
        sample = [rng.choice(values) for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    alpha = (1 - ci) / 2
    lo = means[int(alpha * n_boot)]
    hi = means[int((1 - alpha) * n_boot)]
    return (sum(values) / n, lo, hi)


def compute_stats(
    outcomes: list[float],
    extra_cost_pct: float = 0.0,
) -> dict:
    """Compute full stats for a list of net_pct outcomes.

    Args:
        outcomes:       list of net_pct values (already cost-adjusted)
        extra_cost_pct: additional cost to stress-test (deducted per trade)
    """
    if not outcomes:
        return {"n": 0}

    n = len(outcomes)
    adj = [x - extra_cost_pct for x in outcomes]
    wins  = [x for x in adj if x > 0]
    loss  = [x for x in adj if x <= 0]

    wr     = len(wins) / n
    ev_adj = sum(adj) / n
    wr_lo, wr_hi = wilson_ci(len(wins), n)
    ev_mean, ev_lo, ev_hi = bootstrap_ci(adj)

    avg_win  = sum(wins) / len(wins)  if wins else 0.0
    avg_loss = sum(loss) / len(loss) if loss else 0.0
    pf       = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")
    kf       = (wr * pf - (1 - wr)) / pf if 0.0 < pf < float("inf") else 0.0

    # Drawdown: treat each outcome as a sequential trade with equal unit sizing
    bankroll = 1.0
    peak     = 1.0
    max_dd   = 0.0
    for x in adj:
        bankroll *= (1 + x)
        if bankroll > peak:
            peak = bankroll
        dd = (peak - bankroll) / peak
        if dd > max_dd:
            max_dd = dd

    # Alpha: how much of total return comes from the single best trade?
    top_trade     = max(adj) if adj else 0.0
    total_return  = sum(adj)
    top_trade_alpha = (top_trade / total_return) if total_return > 0 else 1.0

    return {
        "n":              n,
        "wr":             round(wr, 4),
        "wr_ci_90_lo":    round(wr_lo, 4),
        "wr_ci_90_hi":    round(wr_hi, 4),
        "ev_adj":         round(ev_adj, 5),
        "ev_ci_90_lo":    round(ev_lo, 5),
        "ev_ci_90_hi":    round(ev_hi, 5),
        "avg_win":        round(avg_win, 4),
        "avg_loss":       round(avg_loss, 4),
        "profit_factor":  round(pf, 3) if pf != float("inf") else 999.0,
        "kelly_fraction": round(kf, 4),
        "max_drawdown":   round(max_dd, 4),
        "total_net":      round(sum(adj), 4),
        "top_trade_alpha":round(top_trade_alpha, 4),
    }


# ── Walk-forward OOS ──────────────────────────────────────────────────────────

def walk_forward_oos(
    events: list[dict],
    strategy_factory: Callable,
    variant: str,
    min_train_days: int = 5,
    min_train_events: int = 30,
    fit_each_day: bool = True,
) -> dict:
    """Expanding-window walk-forward OOS evaluation.

    For each test day d (starting from min_train_days + 1):
      1. Gather all events with day < d as the training set.
      2. Call strategy_factory(train_events) to get a fitted strategy.
         (For the champion, factory returns champion_passes unchanged.)
      3. Apply strategy to all events on day d.
      4. Collect outcomes for events where strategy returns True.

    Contamination guarantee: test events are NEVER seen by the factory
    during training. The factory receives only events with day < test_day.

    Args:
        events:          list of event dicts from load_events(), sorted by ts.
        strategy_factory: callable(train_events) -> strategy_fn(features, variant) -> bool
                          For no-training strategies, return the strategy unchanged.
        variant:         which variant to evaluate (e.g. 'R7_STAIRCASE').
        min_train_days:  skip test days until we have at least this many training days.
        min_train_events: skip test days until training set has this many events.
        fit_each_day:    if True, refit strategy on each expanding window.
                         If False, fit once on all events before the last day.

    Returns:
        dict with:
            oos_trades: list of trade dicts (includes outcome + whether strategy passed)
            stats:      OOS stats across all test trades
            by_day:     per-day stats
            by_regime:  per-regime stats
            all_days:   list of all test days considered
            n_train_at_end: size of training set at the end
    """
    # Filter to the relevant variant
    var_events = [e for e in events if e["variant"] == variant]
    if not var_events:
        return {"oos_trades": [], "stats": {"n": 0},
                "by_day": {}, "by_regime": {}, "all_days": []}

    all_days = sorted({e["day"] for e in var_events})
    oos_trades: list[dict] = []
    strategy_cache: dict[str, object] = {}

    for i, test_day in enumerate(all_days):
        train_events = [e for e in var_events if e["day"] < test_day]
        test_events  = [e for e in var_events if e["day"] == test_day]

        # Enforce minimum training requirements
        train_days = len({e["day"] for e in train_events})
        if train_days < min_train_days:
            continue
        if len(train_events) < min_train_events:
            continue

        # Fit or retrieve the strategy for this training window
        if fit_each_day:
            strategy = strategy_factory(train_events)
        else:
            # Fit once and reuse (weaker but faster)
            cache_key = str(len(train_events))
            if cache_key not in strategy_cache:
                strategy_cache[cache_key] = strategy_factory(train_events)
            strategy = strategy_cache[cache_key]

        # Apply strategy to test events
        for e in test_events:
            passed = strategy(e["features"], e["variant"])
            oos_trades.append({
                **e,
                "strategy_passed": bool(passed),
            })

    # Compute OOS metrics only for trades where strategy passed
    taken = [t for t in oos_trades if t["strategy_passed"]]
    outcomes = [t["net_pct"] for t in taken]

    stats = compute_stats(outcomes)
    stats["n_signals_seen"] = len(oos_trades)
    stats["pass_rate"] = len(taken) / len(oos_trades) if oos_trades else 0.0

    # Per-day breakdown
    by_day: dict[str, dict] = {}
    for day in {t["day"] for t in oos_trades}:
        day_taken = [t for t in taken if t["day"] == day]
        by_day[day] = compute_stats([t["net_pct"] for t in day_taken])
        by_day[day]["n_signals"] = sum(1 for t in oos_trades if t["day"] == day)

    # Per-regime breakdown
    by_regime: dict[str, dict] = {}
    for label, _, _ in REGIMES:
        regime_taken = [t for t in taken if t["regime"] == label]
        if regime_taken:
            by_regime[label] = compute_stats([t["net_pct"] for t in regime_taken])

    # Stressed EV (double extra costs)
    stressed_stats = compute_stats(outcomes, extra_cost_pct=ADDITIONAL_SLIPPAGE * 2)

    return {
        "variant":          variant,
        "oos_trades":       oos_trades,
        "taken":            taken,
        "stats":            stats,
        "stressed_stats":   stressed_stats,
        "by_day":           by_day,
        "by_regime":        by_regime,
        "all_days":         all_days,
        "n_train_at_end":   sum(1 for e in var_events if e["day"] < all_days[-1])
                            if all_days else 0,
    }


def evaluate_no_filter(events: list[dict], variant: str) -> dict:
    """Baseline: what is the EV if we trade every signal with no filter?"""
    var_events = [e for e in events if e["variant"] == variant]
    outcomes = [e["net_pct"] for e in var_events]
    return {
        "variant": variant,
        "label":   "no_filter_baseline",
        "stats":   compute_stats(outcomes),
    }


def evaluate_champion(events: list[dict], variant: str) -> dict:
    """Apply champion filter (no training needed) to all data.

    WARNING: The champion filter was DERIVED using this same dataset.
    The result is therefore in-sample for the champion and will be optimistic.
    Use this for reference and calibration, not for promotion decisions.
    The true OOS for the champion starts from PRECISION_FILTER_DEPLOY_TS_NS.
    """
    from .config import champion_passes

    def factory(train_events):
        return champion_passes

    return walk_forward_oos(
        events, factory, variant,
        min_train_days=0,     # champion needs no training
        min_train_events=0,
        fit_each_day=False,
    )


def sensitivity_analysis(
    events: list[dict],
    strategy_factory: Callable,
    variant: str,
    param_name: str,
    param_values: list,
    get_factory_with_param: Callable,
) -> list[dict]:
    """Run walk-forward for multiple values of a key parameter.

    Used to verify that a strategy doesn't depend critically on a single
    parameter choice. A robust strategy should show consistent EV across
    a range of nearby parameter values.

    Args:
        get_factory_with_param: callable(param_value) -> strategy_factory
    """
    results = []
    for val in param_values:
        factory = get_factory_with_param(val)
        result = walk_forward_oos(events, factory, variant)
        results.append({
            "param_name":  param_name,
            "param_value": val,
            "stats":       result["stats"],
        })
    return results


def format_report(results: dict, label: str = "") -> str:
    """Format walk-forward results as a human-readable report."""
    lines = []
    s = results.get("stats", {})
    n = s.get("n", 0)
    variant = results.get("variant", "?")

    lines.append(f"\n{'='*65}")
    lines.append(f"  {label or variant}  —  OOS Walk-Forward Results")
    lines.append(f"{'='*65}")

    if n == 0:
        lines.append("  No OOS trades taken.")
        return "\n".join(lines)

    wr    = s.get("wr", 0)
    ev    = s.get("ev_adj", 0)
    ci_lo = s.get("ev_ci_90_lo", 0)
    ci_hi = s.get("ev_ci_90_hi", 0)
    dd    = s.get("max_drawdown", 0)
    pf    = s.get("profit_factor", 0)
    alpha = s.get("top_trade_alpha", 0)
    pr    = s.get("pass_rate", 0)
    seen  = s.get("n_signals_seen", 0)

    lines.append(f"  Signals seen: {seen}   Taken: {n}   Pass rate: {pr:.0%}")
    lines.append(f"  Win rate:     {wr:.0%}   (90% CI: {s.get('wr_ci_90_lo',0):.0%}–{s.get('wr_ci_90_hi',0):.0%})")
    lines.append(f"  adj_EV/trade: {ev:+.3%}   (90% CI: {ci_lo:+.3%}–{ci_hi:+.3%})")
    lines.append(f"  Total net:    {s.get('total_net',0):+.3%}")
    lines.append(f"  Max drawdown: {dd:.1%}   Profit factor: {pf:.2f}")
    lines.append(f"  Top trade alpha: {alpha:.0%}  (share of total return from best trade)")

    # Stressed EV
    ss = results.get("stressed_stats", {})
    if ss:
        lines.append(f"  Stressed EV:  {ss.get('ev_adj',0):+.3%}  (2× extra slippage)")

    # Per-day
    bd = results.get("by_day", {})
    if bd:
        lines.append(f"\n  Per-day breakdown:")
        for day in sorted(bd):
            ds = bd[day]
            lines.append(f"    {day}:  n={ds.get('n',0):3d}  "
                         f"WR={ds.get('wr',0):.0%}  EV={ds.get('ev_adj',0):+.2%}")

    # Per-regime
    br = results.get("by_regime", {})
    if br:
        lines.append(f"\n  Per-regime breakdown:")
        for regime, rs in sorted(br.items()):
            lines.append(f"    {regime:16s}:  n={rs.get('n',0):3d}  "
                         f"WR={rs.get('wr',0):.0%}  EV={rs.get('ev_adj',0):+.2%}")

    return "\n".join(lines)
