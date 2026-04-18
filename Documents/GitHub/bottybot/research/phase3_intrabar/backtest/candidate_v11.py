"""Candidate algorithm v11 — filtered multi-variant backtest simulator.

Design principles from feature discrimination analysis:
  - SKIP R4_POST_RUN_HOLD entirely (consistently negative across all policies)
  - R6_LOCAL_BREAKOUT: filter breakout_pct ≥ 0.013 AND cvd_30s ≥ -4000
  - R3_DV_EXPLOSION: filter buy_share_10s ≥ 0.97 AND dv_30s_usd ≤ 40000
  - R5_CONFIRMED_RUN: filter ret_15m ≥ 0.10 OR (utc_hour ≥ 16 AND cvd_30s ≥ 0)
  - R7_STAIRCASE: filter step_2m ≥ 0.013 AND fear_greed > 21
  - R8_HIGH_CONVICTION: take all (already rare, high edge)

Exit policies (from heatmap):
  R3: r5_v10,  R5: time_300s,  R6: r5_v10,  R7: time_300s,  R8: time_120s

Simulation:
  - Chronological processing of all signals
  - Fixed position size fraction per trade (configurable)
  - Max N concurrent positions (overlap cap)
  - Daily bankroll compounding
  - Report daily PnL, cumulative return, sharpe
"""
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SHADOW = Path("/home/ec2-user/phase3_intrabar/artifacts/shadow_trades.jsonl")


def load_filtered(delay_target=250):
    """Load one (coin, ts, variant, policy) record per signal, keeping only
    trades we'd take under the candidate filter rules."""

    # The exit policy we want for each variant
    POLICY = {
        "R3_DV_EXPLOSION":    "r5_v10",
        "R5_CONFIRMED_RUN":   "time_300s",
        "R6_LOCAL_BREAKOUT":  "r5_v10",
        "R7_STAIRCASE":       "time_300s",
        "R8_HIGH_CONVICTION": "time_120s",
    }

    # Best (dist to target delay, record) per unique signal+policy
    best = {}
    with SHADOW.open() as f:
        for line in f:
            r = json.loads(line)
            v = r.get("variant")
            p = r.get("exit_policy")
            if v not in POLICY or POLICY[v] != p:
                continue
            k = (r.get("coin"), r.get("entry_ts_ns"), v)
            dist = abs((r.get("delay_ms") or 0) - delay_target)
            prev = best.get(k)
            if prev is None or dist < prev[0]:
                best[k] = (dist, r)

    return [v[1] for v in best.values()]


def passes_filter(r):
    """Apply variant-specific filter rules."""
    f = r.get("sig_features") or {}
    v = r["variant"]

    def g(key, default=0.0):
        val = f.get(key, default)
        return float(val) if val is not None and not isinstance(val, bool) else default

    if v == "R6_LOCAL_BREAKOUT":
        return g("breakout_pct") >= 0.013 and g("cvd_30s", -1e9) >= -4000

    if v == "R3_DV_EXPLOSION":
        return (g("buy_share_10s") >= 0.97
                and g("dv_30s_usd", 1e9) <= 40000
                and g("spread_bps", 100) <= 20)

    if v == "R5_CONFIRMED_RUN":
        return (g("ret_15m") >= 0.10
                or (int(g("utc_hour")) >= 16 and g("cvd_30s", -1e9) >= 0))

    if v == "R7_STAIRCASE":
        return g("step_2m") >= 0.013 and g("fear_greed") > 21

    if v == "R8_HIGH_CONVICTION":
        return True

    return False


def simulate(
    trades,
    starting_usd=200.0,
    position_pct=0.35,
    max_concurrent=3,
    max_per_day=20,
    cooldown_per_coin_s=1800,
):
    """Run chronological simulation.

    - position_pct of bankroll per trade
    - max_concurrent simultaneous open positions
    - max_per_day new entries
    - cooldown per coin after exit
    """
    trades_sorted = sorted(trades, key=lambda r: r["entry_ts_ns"])
    bankroll = starting_usd
    open_positions = []   # list of (exit_ts_ns, net_pct, usd_committed, coin)
    last_exit_per_coin = {}  # coin -> exit_ts_ns
    per_day_count = defaultdict(int)
    daily_pnl = defaultdict(float)
    daily_start = defaultdict(lambda: None)
    taken = []
    skipped_concurrent = 0
    skipped_cooldown = 0
    skipped_day_cap = 0

    def close_open_up_to(now_ns):
        nonlocal bankroll
        remaining = []
        for exit_ts, net_pct, usd_in, coin in open_positions:
            if exit_ts <= now_ns:
                pnl = usd_in * net_pct
                bankroll += pnl
                d = datetime.fromtimestamp(exit_ts / 1e9, tz=timezone.utc).date().isoformat()
                daily_pnl[d] += pnl
                last_exit_per_coin[coin] = exit_ts
            else:
                remaining.append((exit_ts, net_pct, usd_in, coin))
        open_positions[:] = remaining

    for t in trades_sorted:
        entry_ns = t["entry_ts_ns"]
        exit_ns = t["exit_ts_ns"]
        coin = t["coin"]
        net = t["net_pct"]
        d = datetime.fromtimestamp(entry_ns / 1e9, tz=timezone.utc).date().isoformat()

        # Close any positions that exit before this signal
        close_open_up_to(entry_ns)

        if daily_start[d] is None:
            daily_start[d] = bankroll

        # Filter gate
        if not passes_filter(t):
            continue

        # Concurrency cap
        if len(open_positions) >= max_concurrent:
            skipped_concurrent += 1
            continue

        # Per-coin cooldown
        last = last_exit_per_coin.get(coin)
        if last is not None and (entry_ns - last) / 1e9 < cooldown_per_coin_s:
            skipped_cooldown += 1
            continue

        # Daily entry cap
        if per_day_count[d] >= max_per_day:
            skipped_day_cap += 1
            continue

        usd_in = bankroll * position_pct
        if usd_in < 10:
            continue

        open_positions.append((exit_ns, net, usd_in, coin))
        per_day_count[d] += 1
        taken.append({
            "ts": entry_ns, "coin": coin, "variant": t["variant"],
            "net_pct": net, "usd_in": usd_in, "day": d,
        })

    # Close remaining positions at infinity (assumes exit already logged in net_pct)
    close_open_up_to(10**20)

    # Compute per-day return %
    daily_report = []
    for d in sorted(daily_pnl):
        start = daily_start.get(d, starting_usd) or starting_usd
        pct = daily_pnl[d] / start if start > 0 else 0.0
        daily_report.append((d, start, daily_pnl[d], pct))

    return {
        "taken": taken,
        "final_bankroll": bankroll,
        "total_return_pct": (bankroll / starting_usd) - 1.0,
        "daily": daily_report,
        "skipped_concurrent": skipped_concurrent,
        "skipped_cooldown": skipped_cooldown,
        "skipped_day_cap": skipped_day_cap,
    }


def main():
    trades = load_filtered()
    print(f"Loaded {len(trades)} signals across candidate variants")

    by_var_all = defaultdict(int)
    by_var_filt = defaultdict(int)
    for t in trades:
        by_var_all[t["variant"]] += 1
        if passes_filter(t):
            by_var_filt[t["variant"]] += 1
    print("\nFilter pass rates by variant:")
    for v in sorted(by_var_all):
        print(f"  {v:22s}  {by_var_filt[v]:>4} / {by_var_all[v]:>4}  "
              f"({by_var_filt[v] / by_var_all[v] * 100:.1f}%)")

    # Baseline: all filtered trades, no concurrency / sizing model
    all_filt = [t for t in trades if passes_filter(t)]
    net = [t["net_pct"] for t in all_filt]
    wins = [x for x in net if x > 0]
    if net:
        print(f"\nFiltered pool: n={len(net)}  "
              f"WR={len(wins) / len(net) * 100:.1f}%  "
              f"avg_net={statistics.mean(net) * 100:+.2f}%  "
              f"sum_net={sum(net) * 100:+.1f}%")

    # Grid over position size + concurrency
    print("\n=== Parameter grid ===")
    print(f"{'pos_pct':>8s}  {'max_conc':>8s}  {'total%':>8s}  "
          f"{'trades':>7s}  {'days':>4s}  {'avg_day%':>8s}  {'final$':>8s}")
    for pos_pct in (0.20, 0.30, 0.40, 0.50):
        for max_conc in (2, 3, 5):
            res = simulate(trades, position_pct=pos_pct, max_concurrent=max_conc)
            daily_pcts = [d[3] for d in res["daily"]]
            avg_day = statistics.mean(daily_pcts) if daily_pcts else 0.0
            print(f"  {pos_pct:.2f}  {max_conc:>8}  "
                  f"{res['total_return_pct'] * 100:+7.1f}%  "
                  f"{len(res['taken']):>7}  {len(res['daily']):>4}  "
                  f"{avg_day * 100:+7.2f}%  "
                  f"${res['final_bankroll']:>7.2f}")

    # Best config — detail
    best_res = simulate(trades, position_pct=0.40, max_concurrent=3)
    print("\n=== Best config (pos=40%, max_conc=3) daily breakdown ===")
    print(f"{'date':>12s}  {'start$':>8s}  {'pnl$':>8s}  {'pct':>7s}  {'trades':>6s}")
    trade_count_by_day = defaultdict(int)
    for t in best_res["taken"]:
        trade_count_by_day[t["day"]] += 1
    for d, start, pnl, pct in best_res["daily"]:
        print(f"  {d}  ${start:>7.2f}  ${pnl:>+7.2f}  {pct * 100:+6.2f}%  {trade_count_by_day[d]:>6}")

    print(f"\nTotal: ${best_res['final_bankroll']:.2f} "
          f"({best_res['total_return_pct'] * 100:+.1f}% total, "
          f"{len(best_res['taken'])} trades, "
          f"skipped {best_res['skipped_concurrent']} for concurrency, "
          f"{best_res['skipped_cooldown']} for cooldown, "
          f"{best_res['skipped_day_cap']} for day cap)")


if __name__ == "__main__":
    main()
