# runner_dna_v1 — Walk-Forward EV Evaluation

Compares the candidate filter against the current live champion and a no-filter baseline. EV is per trade after the cost embedded in shadow records (~40 bps round-trip). Stressed columns add an extra **24 bps** based on real exit-leg slippage measured in research/slippage.py.

Sizing: 10% of bankroll fixed per trade for the cumulative-P&L and drawdown lines.

## Headline (modeled costs)

| filter | trades | trades/day | WR | mean net | median net | total P&L | max DD | Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `no_filter` | 4054 | 137 | 22.7% | -0.45% | -0.86% | -183.99% | 184.83% | -10.51 |
| `champion_v1` | 84 | 6 | 36.9% | +1.60% | -0.81% | +13.42% | 2.48% | 7.36 |
| `runner_dna_v1` | 93 | 7 | 41.9% | +1.32% | -0.62% | +12.27% | 0.43% | 11.46 |
| `combined_or` | 140 | 11 | 37.9% | +1.17% | -0.86% | +16.33% | 1.96% | 9.98 |

## Headline (stressed costs +24bps)

| filter | trades | WR | mean net | total P&L | max DD | Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| `no_filter` | 4054 | 19.3% | -0.69% | -281.29% | 281.29% | -11.14 |
| `champion_v1` | 84 | 35.7% | +1.36% | +11.40% | 2.92% | 6.53 |
| `runner_dna_v1` | 93 | 39.8% | +1.08% | +10.04% | 0.45% | 9.99 |
| `combined_or` | 140 | 35.7% | +0.93% | +12.97% | 2.18% | 8.51 |

## Daily P&L (runner_dna_v1, modeled costs)

| date | n | wins | net P&L (pos-pct) |
|---|---:|---:|---:|
| 2026-04-14 | 17 | 7 | +9.26% |
| 2026-04-15 | 28 | 12 | +75.29% |
| 2026-04-16 | 19 | 8 | +6.48% |
| 2026-04-17 | 2 | 1 | +5.18% |
| 2026-04-19 | 1 | 0 | -4.27% |
| 2026-04-20 | 1 | 1 | +19.36% |
| 2026-04-23 | 7 | 2 | -1.24% |
| 2026-04-24 | 11 | 3 | +2.96% |
| 2026-04-25 | 7 | 5 | +9.67% |

## Verdict

### Standalone candidate vs champion
- runner_dna_v1 catches **93** trades vs champion's 84. WR **+5.0pp**, max DD **5.8× lower** (2.48% → 0.43%), Sharpe **11.5** vs 7.4.
- BUT mean net is lower (+1.32% vs +1.60%) — wins are smaller. 
- Verdict: standalone candidate is **risk-better, return-similar**. Doesn't pass the 9-gate `min_champion_ev_uplift = 0.2%` requirement on its own.

### Combined OR (champion v1 OR runner_dna_v1) — the strongest result
- The two filters share only **37 signals** out of 140 total — they catch largely **complementary** runner profiles.
- 140 trades, 37.9% WR, +16.33% total P&L vs +13.42% for champion alone (**+2.91% additional return**).
- Stressed P&L: +12.97% vs +11.40% champion-only (still +1.57% better).

### Caveats
- The runner_dna_v1 *rule* was designed by examining this same data. AUC was OOS via walk-forward, but the rule definition is in-sample. Apply a 30% haircut to the in-sample EV when projecting forward.
- Daily P&L is concentrated: Apr 15 contributed +75% of cumulative alone. Real performance depends on similar volatile days recurring. The data window contained one major altseason day (Apr 15).
- 14-day window with 9-12 trading days post-feature-extension. Need 30+ days of full-coverage data before committing to promotion.

### Recommended path
1. Don't replace the champion. **Add `runner_dna_v1` as a parallel shadow detector** for 4 weeks; collect outcomes; re-evaluate.
2. Per-coin EV tracker (still missing) — 11/17 recent runners came from 2 coins. The KAT/RAVE concentration is information, not noise.
3. After 30 days of full-coverage shadow with both filters firing, re-run this evaluation. If `combined_or` still beats `champion_v1` on stressed cost basis with `min_oos_days_with_trade ≥ 5`, promote the OR-combination through the formal 9-gate framework.
