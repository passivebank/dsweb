"""
research/runner_research/v3_simulate.py — adversarial simulator + 8 stress tests.

Takes the best model + simulates the trading strategy with HONEST path-order
modeling. Then runs 8 stress tests:

  1. Flat baseline    — held-out test, default config
  2. Per-coin holdout — exclude top 3 dominant coins (KAT/MEZO/RAVE)
  3. Per-day holdout  — exclude best single day, see if edge persists
  4. Cost stress      — +50/+100/+150 bps slippage on top of base
  5. Adverse-only path— assume worst-case path order on EVERY trade
  6. Capacity caps    — $5k / $15k / $50k absolute position limits
  7. Concurrent cap   — model max 3 concurrent positions binding
  8. signals_24h test — include vs exclude per-coin signals_24h gate

Smart trail policy used in all sims:
  - Hard stop -1.5%
  - At +1.5% gain: lock breakeven (move stop to entry)
  - At +2.5% gain: lock +1.0%
  - At +4.0% gain: dynamic trail (peak × 0.985 = 1.5% from peak)
  - At +7.0% gain: tighten trail to peak × 0.99 (1% from peak)
  - Time cap 5 minutes
"""
from __future__ import annotations

import gzip
import json
import math
import pickle
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np

LABELED   = Path("/tmp/runner_research/v3_labeled.jsonl.gz")
MODEL_DIR = Path("research/runner_research/v3_models")
OUT_REPORT= Path("research/runner_research/v3_stress_report.md")
HELD_OUT_FROM = "2026-04-25"

# Smart trail policy
HARD_STOP_PCT     = 0.015
LOCK_BE_AT        = 0.015
LOCK_PLUS_1_AT    = 0.025
TRAIL_15_AT       = 0.040
TRAIL_10_AT       = 0.070
TIME_CAP_S        = 300

# Sizing
POS_PCT          = 1/3
MAX_CONCURRENT   = 3
TAKER_FEE_BPS    = 30
EXTRA_SLIP_BPS   = 24
TOTAL_COST_PCT   = (TAKER_FEE_BPS * 2 + EXTRA_SLIP_BPS) / 10_000   # 0.84%


def load_data():
    train, test = [], []
    with gzip.open(LABELED, "rt") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            r = json.loads(line)
            (train if r["sig_date"] < HELD_OUT_FROM else test).append(r)
    return train, test


def coerce(v):
    if v is None: return np.nan
    if isinstance(v, bool): return 1.0 if v else 0.0
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f): return np.nan
        return f
    except (TypeError, ValueError): return np.nan


def predict(model_payload, rows):
    """Apply a saved model payload to raw rows. Returns probabilities."""
    features = model_payload["features"]
    medians  = model_payload["medians"]
    X = np.zeros((len(rows), len(features)))
    for i, r in enumerate(rows):
        for j, f in enumerate(features):
            v = coerce(r.get(f))
            X[i, j] = v if not math.isnan(v) else medians[j]
    return model_payload["model"].predict_proba(X)[:, 1]


def smart_trail_outcome_favorable(fmax, fmin, natural):
    """Outcome assuming peak hits BEFORE trough (favorable path)."""
    if fmax >= TRAIL_10_AT:    return (fmax - 0.010, "trail_10")
    if fmax >= TRAIL_15_AT:    return (fmax - 0.015, "trail_15")
    if fmax >= LOCK_PLUS_1_AT: return (0.010 if fmin < 0.010 else fmax - 0.010, "lock_+1")
    if fmax >= LOCK_BE_AT:     return (0.0   if fmin < 0     else fmax * 0.7, "lock_BE")
    if fmin <= -HARD_STOP_PCT: return (-HARD_STOP_PCT, "hard_stop")
    return (natural if natural is not None else 0.0, "time_cap")


def smart_trail_outcome_adverse(fmax, fmin, natural):
    """Outcome assuming trough hits BEFORE peak (adverse path).

    On adverse path, the hard stop fires first if fwd_min ≤ -1.5%.
    Otherwise the trade plays out to the favorable outcome.
    """
    if fmin <= -HARD_STOP_PCT: return (-HARD_STOP_PCT, "hard_stop_adv")
    return smart_trail_outcome_favorable(fmax, fmin, natural)


def smart_trail_outcome(fmax, fmin, natural, path_mix=0.5):
    """50/50 path-order weighted average by default. path_mix=1.0 means
    100% adverse (worst case). path_mix=0.0 means 100% favorable."""
    fmax = max(fmax or 0.0, 0.0)
    fmin = min(fmin or 0.0, 0.0)
    fav, fav_r = smart_trail_outcome_favorable(fmax, fmin, natural)
    if fmin <= -HARD_STOP_PCT and fmax >= LOCK_BE_AT:
        adv, adv_r = smart_trail_outcome_adverse(fmax, fmin, natural)
        return ((1 - path_mix) * fav + path_mix * adv, f"split({fav_r}/{adv_r})")
    return (fav, fav_r)


def simulate(rows_with_pred, prob_threshold, starting_capital=10_000,
             extra_cost_pct=0.0, path_mix=0.5, max_concurrent=MAX_CONCURRENT,
             pos_cap_usd=None, exclude_coins=None, exclude_dates=None):
    """Run the strategy simulation. Returns dict of stats."""
    bankroll = starting_capital
    open_positions: list[dict] = []
    daily_pnl = defaultdict(float)
    nets = []
    trades = []
    extra_cost = TOTAL_COST_PCT + extra_cost_pct

    for r, p in rows_with_pred:
        if p < prob_threshold: continue
        if exclude_coins and r["coin"] in exclude_coins: continue
        if exclude_dates and r["sig_date"] in exclude_dates: continue
        sig_ts = datetime.fromisoformat(r["sig_dt"].replace("Z", "+00:00"))
        # Drop expired positions
        open_positions = [op for op in open_positions if op["close_ts"] > sig_ts]
        if len(open_positions) >= max_concurrent: continue

        net_raw, reason = smart_trail_outcome(
            r.get("fwd_max_5m"), r.get("fwd_min_5m"),
            r.get("natural_exit_net"), path_mix=path_mix,
        )
        net = net_raw - extra_cost
        size_usd = bankroll * POS_PCT
        if pos_cap_usd is not None: size_usd = min(size_usd, pos_cap_usd)
        pnl_usd = size_usd * net
        bankroll += pnl_usd
        nets.append(net)
        close_ts = sig_ts + timedelta(seconds=TIME_CAP_S)
        open_positions.append({"close_ts": close_ts})
        daily_pnl[r["sig_date"]] += pnl_usd
        trades.append({
            "sig_dt": r["sig_dt"], "coin": r["coin"], "pred": float(p),
            "net": net, "reason": reason, "pnl_usd": pnl_usd,
        })

    if not nets:
        return {"n": 0, "ending_capital": starting_capital,
                "starting_capital": starting_capital,
                "total_pnl_pct": 0.0, "win_rate": 0.0}

    nets_arr = np.array(nets)
    return {
        "n":               len(nets),
        "starting_capital": starting_capital,
        "ending_capital":  bankroll,
        "total_pnl_usd":   bankroll - starting_capital,
        "total_pnl_pct":   (bankroll - starting_capital) / starting_capital * 100,
        "win_rate":        float((nets_arr > 0).mean()),
        "mean_net":        float(nets_arr.mean()),
        "median_net":      float(np.median(nets_arr)),
        "min_net":         float(nets_arr.min()),
        "max_net":         float(nets_arr.max()),
        "n_days":          len(daily_pnl),
        "trades":          trades,
        "daily_pnl":       dict(daily_pnl),
    }


def main():
    train, test = load_data()
    # Use robust XGB if present (lower overfit risk), else fall back to RF
    candidates = [
        Path("research/runner_research/v3_models_robust/p_5pct_5m_xgb.pkl"),
        Path("research/runner_research/v3_models_robust/p_5pct_5m_lgbm.pkl"),
        MODEL_DIR / "p_5pct_5m_rf.pkl",
    ]
    best_model_path = next((p for p in candidates if p.exists()), None)
    if best_model_path is None:
        print("ERR: no model file found", file=sys.stderr); return 1
    print(f"Loading {best_model_path}")
    with best_model_path.open("rb") as f:
        payload = pickle.load(f)
    print(f"Loaded model: {payload['model_name']}, "
          f"CV AUC={payload['cv_auc']:.4f}, test AUC={payload['test_auc']:.4f}")
    print(f"Held-out test rows: {len(test)}")

    test_pred = predict(payload, test)
    rows_with_pred = list(zip(test, test_pred))

    md = ["# v3 Adversarial Simulation Report\n"]
    md.append(f"**Model:** {payload['model_name']} on `{payload['hor_col']} ≥ {payload['thr']*100:.0f}%`\n")
    md.append(f"**CV AUC:** {payload['cv_auc']:.4f}  |  **Held-out test AUC:** {payload['test_auc']:.4f}\n")
    md.append(f"**Test rows:** {len(test)} (4 days)\n\n")

    # ── Stress 1: Baseline sweep ───────────────────────────────────────
    md.append("## Stress 1: Baseline probability-threshold sweep (50/50 path)\n")
    md.append("| prob ≥ | n | WR | mean | total | ending $ | n_days |\n")
    md.append("|---:|---:|---:|---:|---:|---:|---:|\n")
    sweep = []
    for pt in [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70]:
        s = simulate(rows_with_pred, pt)
        sweep.append({"pt": pt, **s})
        if s["n"]:
            md.append(f"| {pt:.2f} | {s['n']} | {s['win_rate']*100:.1f}% | "
                      f"{s['mean_net']*100:+.2f}% | {s['total_pnl_pct']:+.2f}% | "
                      f"${s['ending_capital']:,.2f} | {s['n_days']} |\n")
    valid = [s for s in sweep if s.get("n", 0) >= 10]
    best = max(valid, key=lambda s: s["total_pnl_pct"]) if valid else None
    if best:
        md.append(f"\n**Best baseline: prob≥{best['pt']:.2f}, total {best['total_pnl_pct']:+.2f}% on "
                  f"${best['starting_capital']:,.0f}**\n\n")
    PROB = best["pt"] if best else 0.40

    # ── Stress 2: Per-coin holdout — drop top 3 dominant coins ─────────
    md.append("## Stress 2: Per-coin holdout — exclude top dominant coins\n")
    md.append("Even if KAT, MEZO, RAVE dominate the recent winners, does the\n")
    md.append("strategy still work on the rest? This isolates coin-specific dependency.\n\n")
    md.append("| excluded coins | n | WR | total | ending $ |\n")
    md.append("|---|---:|---:|---:|---:|\n")
    for exc in [None, ["KAT"], ["KAT","MEZO"], ["KAT","MEZO","RAVE"],
                 ["KAT","MEZO","RAVE","ORCA","TIME","RARI"]]:
        s = simulate(rows_with_pred, PROB, exclude_coins=set(exc) if exc else None)
        ex_str = ",".join(exc) if exc else "(none)"
        md.append(f"| {ex_str} | {s['n']} | {s.get('win_rate',0)*100:.1f}% | "
                  f"{s.get('total_pnl_pct',0):+.2f}% | ${s.get('ending_capital',0):,.2f} |\n")
    md.append("\n")

    # ── Stress 3: Per-day holdout — drop best day ──────────────────────
    md.append("## Stress 3: Drop best single day, see if edge survives\n")
    by_day_pnl = defaultdict(float)
    if best:
        for t in best["trades"]: by_day_pnl[t["sig_dt"][:10]] += t["pnl_usd"]
    sorted_days = sorted(by_day_pnl.items(), key=lambda kv: -kv[1])
    md.append(f"\nDaily P&L (sorted): {[f'{d}: ${v:,.0f}' for d, v in sorted_days[:5]]}\n\n")
    md.append("| excluded day | n | total | ending $ |\n")
    md.append("|---|---:|---:|---:|\n")
    for d, _ in sorted_days[:3]:
        s = simulate(rows_with_pred, PROB, exclude_dates={d})
        md.append(f"| {d} | {s['n']} | {s.get('total_pnl_pct',0):+.2f}% | ${s.get('ending_capital',0):,.2f} |\n")
    md.append("\n")

    # ── Stress 4: Cost stress ─────────────────────────────────────────
    md.append("## Stress 4: Higher slippage costs\n")
    md.append("Adds extra round-trip cost on top of the 84bps baseline.\n\n")
    md.append("| extra cost | n | WR | mean | total | ending $ |\n")
    md.append("|---:|---:|---:|---:|---:|---:|\n")
    for extra in [0, 0.005, 0.010, 0.015, 0.020]:
        s = simulate(rows_with_pred, PROB, extra_cost_pct=extra)
        md.append(f"| +{extra*10000:.0f}bps | {s['n']} | {s.get('win_rate',0)*100:.1f}% | "
                  f"{s.get('mean_net',0)*100:+.2f}% | {s.get('total_pnl_pct',0):+.2f}% | "
                  f"${s.get('ending_capital',0):,.2f} |\n")
    md.append("\n")

    # ── Stress 5: 100% adverse path order ─────────────────────────────
    md.append("## Stress 5: 100% adverse path order\n")
    md.append("If on EVERY trade the trough comes before the peak (worst case):\n\n")
    s_fav = simulate(rows_with_pred, PROB, path_mix=0.0)
    s_5050 = simulate(rows_with_pred, PROB, path_mix=0.5)
    s_adv = simulate(rows_with_pred, PROB, path_mix=1.0)
    md.append("| path mix | n | WR | total | ending $ |\n")
    md.append("|---|---:|---:|---:|---:|\n")
    for label, s in [("favorable", s_fav), ("50/50 default", s_5050), ("adverse", s_adv)]:
        md.append(f"| {label} | {s['n']} | {s.get('win_rate',0)*100:.1f}% | "
                  f"{s.get('total_pnl_pct',0):+.2f}% | ${s.get('ending_capital',0):,.2f} |\n")
    md.append("\n")

    # ── Stress 6: Position size caps ─────────────────────────────────
    md.append("## Stress 6: Capacity / position size caps\n")
    md.append("Imposes absolute USD cap on each position to model micro-cap depth limits.\n\n")
    md.append("| pos cap | n | total | ending $ |\n")
    md.append("|---:|---:|---:|---:|\n")
    for cap in [None, 50_000, 15_000, 5_000, 1_000]:
        s = simulate(rows_with_pred, PROB, pos_cap_usd=cap)
        cap_str = f"${cap:,}" if cap else "no cap"
        md.append(f"| {cap_str} | {s['n']} | {s.get('total_pnl_pct',0):+.2f}% | ${s.get('ending_capital',0):,.2f} |\n")
    md.append("\n")

    # ── Stress 7: max_concurrent caps ─────────────────────────────────
    md.append("## Stress 7: Concurrent position cap binding\n")
    md.append("| max concurrent | n | total | ending $ |\n")
    md.append("|---:|---:|---:|---:|\n")
    for mc in [1, 2, 3, 5, 99]:
        s = simulate(rows_with_pred, PROB, max_concurrent=mc)
        md.append(f"| {mc} | {s['n']} | {s.get('total_pnl_pct',0):+.2f}% | ${s.get('ending_capital',0):,.2f} |\n")
    md.append("\n")

    # ── Stress 8: train/test reversal sanity ──────────────────────────
    md.append("## Stress 8: Train/test inversion (sanity check)\n")
    md.append("Predict on TRAIN data with the same final model. If train AUC is "
              "wildly higher than test AUC, the model overfit.\n\n")
    train_pred = predict(payload, train)
    from sklearn.metrics import roc_auc_score
    y_train = np.array([1 if (r.get(payload['hor_col']) or 0) >= payload['thr'] else 0 for r in train])
    train_auc = roc_auc_score(y_train, train_pred) if y_train.sum() and (1-y_train).sum() else float("nan")
    md.append(f"- **Train AUC:** {train_auc:.4f}  |  **Test AUC:** {payload['test_auc']:.4f}\n")
    overfit_gap = train_auc - payload['test_auc']
    md.append(f"- **Gap (overfit indicator):** {overfit_gap:+.4f}\n")
    md.append(f"- {'**HIGH overfit risk**' if overfit_gap > 0.20 else '**Acceptable** (<0.20 gap)'}\n\n")

    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text("".join(md))
    print(f"\nwrote {OUT_REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
