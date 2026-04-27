# v3 Adversarial Simulation Report
**Model:** lgbm on `fwd_max_5m ≥ 5%`
**CV AUC:** 0.6043  |  **Held-out test AUC:** 0.6935
**Test rows:** 317 (4 days)

## Stress 1: Baseline probability-threshold sweep (50/50 path)
| prob ≥ | n | WR | mean | total | ending $ | n_days |
|---:|---:|---:|---:|---:|---:|---:|
| 0.20 | 313 | 40.6% | +0.75% | +108.42% | $20,842.06 | 3 |
| 0.25 | 310 | 41.0% | +0.77% | +112.08% | $21,208.27 | 3 |
| 0.30 | 307 | 41.4% | +0.79% | +115.61% | $21,560.95 | 3 |
| 0.35 | 299 | 41.8% | +0.86% | +124.58% | $22,458.02 | 3 |
| 0.40 | 279 | 43.0% | +0.92% | +125.77% | $22,577.08 | 3 |
| 0.45 | 249 | 44.2% | +1.06% | +131.85% | $23,184.53 | 3 |
| 0.50 | 220 | 46.4% | +1.29% | +147.43% | $24,742.86 | 3 |
| 0.60 | 142 | 46.5% | +1.75% | +120.96% | $22,096.46 | 3 |
| 0.70 | 90 | 52.2% | +2.09% | +82.85% | $18,285.01 | 3 |

**Best baseline: prob≥0.50, total +147.43% on $10,000**

## Stress 2: Per-coin holdout — exclude top dominant coins
Even if KAT, MEZO, RAVE dominate the recent winners, does the
strategy still work on the rest? This isolates coin-specific dependency.

| excluded coins | n | WR | total | ending $ |
|---|---:|---:|---:|---:|
| (none) | 220 | 46.4% | +147.43% | $24,742.86 |
| KAT | 197 | 47.2% | +115.95% | $21,594.56 |
| KAT,MEZO | 194 | 46.9% | +111.58% | $21,158.43 |
| KAT,MEZO,RAVE | 189 | 47.6% | +116.21% | $21,620.61 |
| KAT,MEZO,RAVE,ORCA,TIME,RARI | 142 | 45.8% | +62.49% | $16,248.63 |

## Stress 3: Drop best single day, see if edge survives

Daily P&L (sorted): ['2026-04-25: $10,119', '2026-04-27: $2,948', '2026-04-26: $1,676']

| excluded day | n | total | ending $ |
|---|---:|---:|---:|
| 2026-04-25 | 126 | +22.98% | $12,298.39 |
| 2026-04-27 | 160 | +117.95% | $21,794.99 |
| 2026-04-26 | 154 | +128.40% | $22,839.93 |

## Stress 4: Higher slippage costs
Adds extra round-trip cost on top of the 84bps baseline.

| extra cost | n | WR | mean | total | ending $ |
|---:|---:|---:|---:|---:|---:|
| +0bps | 220 | 46.4% | +1.29% | +147.43% | $24,742.86 |
| +50bps | 220 | 31.8% | +0.79% | +71.67% | $17,167.41 |
| +100bps | 220 | 28.2% | +0.29% | +19.04% | $11,904.07 |
| +150bps | 220 | 28.2% | -0.21% | -17.51% | $8,249.37 |
| +200bps | 220 | 25.9% | -0.71% | -42.87% | $5,713.21 |

## Stress 5: 100% adverse path order
If on EVERY trade the trough comes before the peak (worst case):

| path mix | n | WR | total | ending $ |
|---|---:|---:|---:|---:|
| favorable | 220 | 52.3% | +196.55% | $29,654.91 |
| 50/50 default | 220 | 46.4% | +147.43% | $24,742.86 |
| adverse | 220 | 42.3% | +106.09% | $20,609.36 |

## Stress 6: Capacity / position size caps
Imposes absolute USD cap on each position to model micro-cap depth limits.

| pos cap | n | total | ending $ |
|---:|---:|---:|---:|
| no cap | 220 | +147.43% | $24,742.86 |
| $50,000 | 220 | +147.43% | $24,742.86 |
| $15,000 | 220 | +147.43% | $24,742.86 |
| $5,000 | 220 | +129.23% | $22,923.32 |
| $1,000 | 220 | +28.38% | $12,838.40 |

## Stress 7: Concurrent position cap binding
| max concurrent | n | total | ending $ |
|---:|---:|---:|---:|
| 1 | 174 | +122.04% | $22,203.95 |
| 2 | 217 | +133.53% | $23,353.47 |
| 3 | 220 | +147.43% | $24,742.86 |
| 5 | 220 | +147.43% | $24,742.86 |
| 99 | 220 | +147.43% | $24,742.86 |

## Stress 8: Train/test inversion (sanity check)
Predict on TRAIN data with the same final model. If train AUC is wildly higher than test AUC, the model overfit.

- **Train AUC:** 0.9073  |  **Test AUC:** 0.6935
- **Gap (overfit indicator):** +0.2138
- **HIGH overfit risk**

