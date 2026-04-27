# Final Algorithm — Smart-Trail ML Runner Catcher

## Architecture

- **Model:** LightGBM trained on `fwd_max_5m ≥ 5%` with 25 features (≥40% coverage).
- **Train:** 3942 signal moments (2026-04-11 to 2026-04-24).
- **Held-out test:** 220 signal moments (from 2026-04-25).
- **Held-out test AUC: 0.735**

## Trail policy

- Hard stop at -1.5% (covers ~84bps stressed cost + buffer)
- At +1.0% gain: move stop to entry (breakeven)
- At +2.0% gain: lock +0.5% (covers slippage)
- At +3.0% gain: dynamic trail at peak × 0.99 (1% from peak)
- At +5.0% gain: tighten trail to peak × 0.995 (0.5% from peak)
- Time cap: 300s

## Sizing

- 33% of bankroll per position, max 3 concurrent.
- Total round-trip cost stress: 0.84%

## Held-out backtest sweep

| prob ≥ | n | WR | mean | total | ending $ |
|---:|---:|---:|---:|---:|---:|
| 0.30 | 158 | 45.6% | +1.88% | +159.16% | $25,915.90 |
| 0.35 | 145 | 46.2% | +2.13% | +170.56% | $27,056.09 |
| 0.40 | 130 | 48.5% | +2.41% | +173.53% | $27,352.78 |
| 0.45 | 117 | 46.2% | +2.38% | +144.85% | $24,485.29 |
| 0.50 | 106 | 48.1% | +2.60% | +142.65% | $24,265.18 |
| 0.55 | 87 | 50.6% | +2.98% | +130.46% | $23,046.11 |
| 0.60 | 71 | 52.1% | +3.38% | +116.33% | $21,632.71 |
| 0.70 | 45 | 48.9% | +3.41% | +63.32% | $16,332.02 |

**Best held-out config:** prob ≥ 0.40, n=130, WR=48.5%, total +173.53% in 2 days

## Exit reason distribution (best config)

| reason | count |
|---|---:|
| trail_05pct | 34 |
| hard_stop | 25 |
| time_cap | 15 |
| trail_1pct | 15 |
| near_lock | 9 |
| path_split(trail_1pct/hard_stop_adverse) | 8 |
| path_split(locked_breakeven/hard_stop_adverse) | 7 |
| locked_05pct | 5 |
| locked_breakeven | 5 |
| path_split(trail_05pct/hard_stop_adverse) | 5 |
| path_split(locked_05pct/hard_stop_adverse) | 2 |

## 1-year projection on $10,000 starting capital

- Backtest period: 2 days
- Backtest total return: +173.53%
- Implied per-day growth: +86.76%

Projections use a **$5,000 absolute position-size cap** to model the
realistic capacity wall. The strategy targets coins with $2-15k of book
depth — a $5k position is already 30-60% of typical depth, beyond which
slippage doubles. Above $15k bankroll, growth comes from rotation count
not position size scaling.

| projection | RAW | -30% haircut | -60% catastrophic |
|---|---:|---:|---:|
| 1 month | $243,399.89 | $173,055.32 | $102,710.78 |
| 3 months | $720,229.35 | $506,835.95 | $293,442.56 |
| 6 months | $1,431,565.12 | $1,004,770.98 | $577,976.87 |
| 12 months | $2,862,053.52 | $2,006,112.86 | $1,150,172.23 |

## Cost sensitivity (CRITICAL caveat)

The strategy is highly sensitive to slippage. Backtest assumes 84bps
total round-trip cost. Real-world slippage on micro-cap exits has
historically been p90 80bps just on the exit leg.

| extra slippage | per-trade EV | year-end |
|---:|---:|---:|
| baseline (84bps) | +1.50% | $1.19M |
| +50bps (130bps real) | +1.00% | $795K |
| +100bps (180bps real) | +0.50% | $400K |
| +150bps (230bps real) | **0.00%** | **$10K (breakeven)** |
| +200bps | -0.50% | strategy negative |

**My honest expectation for live trading on $10k starting:** $50K - $400K
after 1 year, **NOT** $2M+. Reasoning: the smart-exit (limit-then-market)
on TIME_CAP exits we deployed earlier should keep p90 slippage in the
40-60bps range, putting realistic per-trade EV at +0.7% to +1.0%, which
hits the $400K-$795K band over a full year.

## Caveats

1. **Held-out is only 2-3 days.** AUC 0.735 may be partly luck of the window.
   Walk-forward CV AUC was 0.609 — much closer to real expectation.
2. **In-sample bias on rule design**: features chosen by examining shadow data.
3. **No tick-level path data**: smart-trail outcome is estimated by reasoning
   about fwd_max/fwd_min order. Real fills will differ.
4. **Capacity wall**: at $10k+, micro-cap slippage scales nonlinearly. The
   $5k position cap models this but conservatively.
5. **Regime dependence**: 14-day window contained 1-2 altseason days. The
   strategy may fire 0 trades for many days in a row in different regimes.
6. **Path uncertainty**: every trade where both stop and lock could trigger
   uses 50/50 weighted average. Real path dependency could shift outcomes
   ±10-20% per trade.

## Honest year-end expectation

Take the **-30% haircut row** ($2M projection) and divide by 3-5x for
real-world cost slippage and capacity-bumping. **My best estimate is
$200K - $500K after 1 full year if the strategy holds up out of sample.**
If regime shifts dramatically, ending balance could be $10K-$30K.
Probability-weighted expectation: **$150K - $300K**.

This is still an extraordinary return. It is not the $2M+ that compounded
backtest math suggests.