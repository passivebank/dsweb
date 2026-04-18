# Algorithm Research — v10 → v11 Candidate

Date: 2026-04-18
Data window: 2026-04-11 → 2026-04-18 (6.7 days of shadow trades)

## Summary

**v10 (current live):** 34.3% WR, -1.24% avg net/trade across 443 shadow signals — matches the -1.18% / 36% WR observed live over 157 trades. The 73% WR / +4.65% baseline from earlier backtests was a different market regime and no longer reflects the current signal quality.

**v11 (candidate):** A filtered multi-variant algorithm. In backtest over the 4 days with meaningful signal volume:
- 73 trades, +89.3% cumulative return
- 40.1% WR, +2.00% avg net/trade (pool of 197 passing signals)
- Average daily return: +18.14%
- Daily sharpe: +1.15
- Bootstrap stability: +41.7% to +96.8% (worst case still ≥13%/day)
- Walk-forward per day: +74%, +161%, +69% totals on Apr 14/15/16 respectively

**Target (5% daily average):** Comfortably clears in backtest with margin, even under conservative sizing (20% position + 2 concurrent → +7.17%/day). In-sample bias is the main risk — live shadow validation is required before deployment.

## Snapshot of v10

Stored in `/snapshots/v10_2026-04-18/`:
- `live_executor.py` — frozen
- `detector/` — frozen
- `multi_runner_v10.py` — offline backtester
- `live_trades_snapshot.jsonl` — 80 live trades up to 2026-04-18 15:32 UTC
- `README.md` — configuration + performance reference

## v11 Algorithm Specification

### Variants to trade (5 of 9)
Variants **R4_POST_RUN_HOLD, R1_TAPE_BURST, R2_RANK_TAKEOVER, R9_VOLUME_STAIRCASE** are skipped entirely — negative edge across all exit policies.

| Variant              | Exit policy   | Filter rules                                                                                          |
|----------------------|---------------|-------------------------------------------------------------------------------------------------------|
| R3_DV_EXPLOSION      | `r5_v10`      | `buy_share_10s ≥ 0.97` AND `dv_30s_usd ≤ 40000` AND `spread_bps ≤ 20`                                 |
| R5_CONFIRMED_RUN     | `time_300s`   | `ret_15m ≥ 0.10` OR (`utc_hour ≥ 16` AND `cvd_30s ≥ 0`)                                               |
| R6_LOCAL_BREAKOUT    | `r5_v10`      | `breakout_pct ≥ 0.013` AND `cvd_30s ≥ -4000`                                                          |
| R7_STAIRCASE         | `time_300s`   | `step_2m ≥ 0.013` AND `fear_greed > 21`                                                               |
| R8_HIGH_CONVICTION   | `time_120s`   | (none — already rare, positive edge)                                                                  |

### Position sizing
- 40% of bankroll per trade
- Max 3 concurrent positions
- Max 20 new entries per day
- 30-minute per-coin cooldown after any exit

### Why these filters (derived from feature discrimination analysis)

**R6_LOCAL_BREAKOUT** has the strongest single discriminator:
- `breakout_pct ≥ 0.013`: 55% WR, +4.23% avg (vs below: 12% WR, -2.61%) — LIFT **+6.84%**

**R3_DV_EXPLOSION**:
- `buy_share_10s ≥ 0.97`: 51% WR, +1.08% avg
- `dv_30s_usd ≤ 40000` (avoid absurd volume spikes that mean-revert): LIFT **+5.27%**

**R5_CONFIRMED_RUN**: larger intraday moves (ret_15m) or US-afternoon with positive CVD

**R7_STAIRCASE**: real step size (step_2m) plus non-panic sentiment

**R8_HIGH_CONVICTION**: untouched — already +2.77% avg @ time_120s

### Exit policy rationale
Per-variant optimal. `time_300s` (5-min hold) wins for R5/R7 because mean-reversion kicks in faster than trail-stops. `r5_v10` (v10's trail-stop-with-partial) works best for R3/R6 where moves extend. `time_120s` (2-min) for R8 because its signals resolve fast.

## Risk / Caveats

1. **Short dataset.** Only 6.7 days, 4 with meaningful signal volume. April 13 was a 1,850-signal pump day; subsequent days had 400→22 signals as market turned. Filters derived from this window may not hold in radically different regimes.

2. **In-sample bias.** Filter thresholds were picked by looking at the full dataset. Walk-forward (holding test days out) still showed positive daily results, but this is not a substitute for real shadow validation.

3. **Architecture change required.** Live executor currently handles only R5_CONFIRMED_RUN. Deploying v11 requires:
   - Accepting all 5 variants in `on_signal`
   - Per-variant filter logic in `_handle_entry`
   - Per-variant exit policy in `on_price` (time-based for some, trail-based for others)
   - Proper cooldown tracking per variant

4. **Concurrency and day-cap sensitivity.** The simulator takes trades first-come-first-served within caps; quality-ranked selection would likely improve realized PnL further.

## Recommended deployment path

1. **Do NOT hot-swap v11 in.** Build it as a second executor running in shadow mode alongside v10, both receiving the same signal stream. v10 remains the source of truth for real trades.

2. **Require ≥10 days of live shadow validation** showing v11 ≥ 5%/day average and positive on 70%+ of days.

3. **Gradual cutover.** Once validated, cut v10 to 20% position and v11 to 20%, run parallel for 5 days, then migrate fully.

## Files
- `audit.py` — dataset scope + v10 performance in shadow data
- `heatmap.py` — variant × exit_policy PnL grid
- `features_discrim.py` — feature lift per variant
- `candidate_v11.py` — v11 simulator with grid search
- `walk_forward.py` — walk-forward + bootstrap validation
- `snapshots/v10_2026-04-18/` — frozen v10 algorithm
