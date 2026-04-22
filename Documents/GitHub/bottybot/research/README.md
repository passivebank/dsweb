# research/ — Champion/Challenger Research Loop

Production-safe continuous improvement system for the live crypto trading bot.

## Principle

The champion filter is **frozen in code** (`config.champion_passes`). Improvement is earned through rigorous OOS evaluation, not ad hoc threshold tweaking. Default verdict is always REJECT.

---

## Files

| File | Purpose |
|------|---------|
| `config.py` | Single source of truth: timestamps, paths, features, champion filter, promotion gates |
| `evaluate.py` | OOS walk-forward engine: `load_events`, `compute_stats`, `walk_forward_oos` |
| `meta_model.py` | L2-regularized logistic meta-filter: `MetaModel`, `meta_model_factory` |
| `promote.py` | 9-gate promotion framework: `run_gates`, `compare_champion_challenger` |
| `daily.py` | Daily QA: shadow coverage, feature coverage, performance snapshot |
| `weekly.py` | Weekly research loop: champion vs. challenger, promotion decision |

---

## Daily (8am UTC)

```bash
python3 -m research.daily           # full report
python3 -m research.daily --brief   # one-line per variant
```

Checks:
1. Shadow coverage — are both R7+time_300s and R5+r5_v10 accumulating?
2. Feature coverage — are critical precision-filter features present in shadow records?
3. Champion-filtered performance — post-deploy EV and WR via champion filter
4. Live trade summary — post-deploy live entries and exits

Alerts if: shadow missing, features >10% absent, champion-filtered EV < -1% (n≥15).

Log: `research/daily_snapshots.jsonl`

---

## Weekly (Sunday 8:30 UTC)

```bash
python3 -m research.weekly              # all variants
python3 -m research.weekly --dry-run    # no artifacts saved
python3 -m research.weekly --variant=R7_STAIRCASE
```

Runs:
1. Champion (precision_filter_v1) — expanding-window OOS baseline
2. Meta-model challenger — L2 logistic regression, threshold=0.55, refitted each day
3. Combined (champion AND meta-model) — strictest filter

Promotion gates (all 9 must pass):

| Gate | Threshold |
|------|-----------|
| min_oos_trades | ≥15 |
| min_oos_days_with_trade | ≥5 distinct days |
| min_oos_ev_adj | >0.5% per trade |
| oos_ev_ci_90_lower | >0% (CI lower bound) |
| min_champion_ev_uplift | +0.2% above champion |
| max_wr_drop_vs_champion | ≤15pp below champion WR |
| min_regime_positive_ev | ≥2 distinct F&G regimes |
| stress_cost_multiplier | Positive EV at 2× extra costs |
| max_single_trade_alpha | Top trade <50% of total return |

Verdicts: PROMOTE / MONITOR / REJECT

Artifacts: `research/experiments/<decision_id>.json`, `research/experiments/decisions.jsonl`

**PROMOTE never automatically changes production.** Human review required. See decision artifact for ACTION REQUIRED steps.

---

## True OOS Validation

`walk_forward_oos` uses an expanding training window:

```
Day 1-4 (train) → Day 5 (test)
Day 1-5 (train) → Day 6 (test)
...
```

The strategy factory is **refitted on each training slice**, never on test data. This eliminates pseudo-OOS leakage.

---

## Adding a New Challenger

1. Write a factory function: `factory(train_events) → callable(features, variant) → bool`
2. Test it via `walk_forward_oos(events, factory, variant)`
3. Run `compare_champion_challenger(champion_result, challenger_result, challenger_id)`
4. Review the verdict and failing gates

---

## Promotion Process (if PROMOTE)

1. Review `research/experiments/<decision_id>.json`
2. Check OOS trade list — look for data quality issues or lucky streaks
3. If approved: update `champion_passes()` in `config.py`
4. Update `live_executor.py` filter logic to match
5. Restart `cb_recorder.service`
6. Document in `research/champions/<decision_id>.md`
7. Update `CHAMPION_ID` in `config.py`

---

## Data Notes

- `shadow_trades.jsonl`: 99,592 records total; post-deploy records accumulate from 2026-04-22T17:13:46Z
- `PRECISION_FILTER_DEPLOY_TS_NS = 1776878026_000_000_000` (2026-04-22T17:13:46Z)
- R7_STAIRCASE + time_300s: live policy (simulator fixed 2026-04-22)
- R5_CONFIRMED_RUN + r5_v10: live policy (simulator tracks correctly)
- Filter derivation bug: original precision_filter_search.py used exit_policy='time_300s' for R5 (wrong). Re-derive R5 filters using r5_v10 outcomes when sufficient post-deploy data accumulates.
