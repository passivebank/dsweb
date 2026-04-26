# Runner DNA — Stop Optimization Analysis

**Trades analyzed:** 72 runner_dna_v1 entries with full forward trajectory (deepest fwd_min across all simulator exit policies)

**Method.** For each candidate hard-stop level, replay every trade: if the deepest observed drawdown crosses the stop, the trade exits at the stop level (locking in -X%). Otherwise the trade plays out to its natural exit (using the longest-window simulator policy as the reference). Stress costs +24bps applied to every trade.

## Flat hard-stop sweep

| stop | n | WR | mean | median | CI lo (95%) | total compound | Sharpe |
|---:|---:|---:|---:|---:|---:|---:|---:|
| **1.0%** | 60 | 40.0% | +0.25% | -1.24% | -0.30% | +1.47% | 7.45 |
| **1.5%** | 61 | 41.0% | +0.05% | -1.28% | -0.54% | +0.28% | 1.33 |
| **2.0%** | 64 | 45.3% | +0.02% | -0.41% | -0.58% | +0.11% | 0.60 |
| **2.5%** | 64 | 45.3% | -0.07% | -0.41% | -0.69% | -0.45% | -1.91 |
| **3.0%** | 69 | 49.3% | -0.06% | -0.28% | -0.69% | -0.42% | -1.93 |
| **3.5%** | 69 | 50.7% | -0.01% | +0.05% | -0.67% | -0.11% | -0.45 |
| **4.0%** | 69 | 50.7% | -0.08% | +0.05% | -0.78% | -0.61% | -2.63 |
| **4.5%** | 69 | 50.7% | -0.16% | +0.05% | -0.90% | -1.11% | -4.54 |
| **5.0%** | 69 | 50.7% | -0.23% | +0.05% | -1.00% | -1.61% | -6.18 |
| **5.5%** | 69 | 50.7% | -0.30% | +0.05% | -1.11% | -2.10% | -7.57 |
| **6.0%** | 69 | 50.7% | -0.30% | +0.05% | -1.14% | -2.10% | -7.55 |
| **7.0%** | 69 | 50.7% | -0.01% | +0.05% | -0.75% | -0.13% | -0.70 |
| **8.0%** | 69 | 50.7% | +0.04% | +0.05% | -0.68% | +0.25% | 1.41 |
| **10.0%** | 69 | 50.7% | +0.14% | +0.05% | -0.52% | +0.97% | 4.24 |

**Best flat stop by mean_net: 1.0%** — mean +0.25%/trade, total +1.47%, CI lo -0.30%, Sharpe 7.45

## Per-feature stratification — best stop per quartile

Slicing the trades by single features and finding the optimal flat stop within each bucket. If different feature buckets prefer different stop widths, that's evidence for per-coin calibration.

### `spread_bps_at_entry`

| bucket | n | best stop | WR | mean | total |
|---|---:|---:|---:|---:|---:|
| q1 [2.341,8.003] | 18 | **1.0%** | 33.3% | -0.32% | -0.58% |
| q2 [8.496,14.54] | 18 | **1.0%** | 22.2% | -0.32% | -0.57% |
| q3 [14.74,19.21] | 18 | **10.0%** | 77.8% | +0.64% | +1.16% |
| q4 [19.38,27.85] | 18 | **6.0%** | 61.1% | +1.84% | +3.34% |

### `ask_depth_usd`

| bucket | n | best stop | WR | mean | total |
|---|---:|---:|---:|---:|---:|
| q1 [226.8,2580] | 14 | **3.5%** | 64.3% | +1.03% | +1.45% |
| q2 [2877,5251] | 14 | **2.0%** | 57.1% | +1.75% | +2.46% |
| q3 [5429,8548] | 13 | **2.5%** | 61.5% | +0.85% | +1.10% |
| q4 [9445,3.712e+04] | 16 | **1.0%** | 18.8% | -0.78% | -1.25% |

### `bid_depth_usd`

| bucket | n | best stop | WR | mean | total |
|---|---:|---:|---:|---:|---:|
| q1 [55.42,1023] | 14 | **3.5%** | 64.3% | +1.52% | +2.14% |
| q2 [1243,4173] | 14 | **7.0%** | 57.1% | +0.35% | +0.49% |
| q3 [4173,1.975e+04] | 14 | **1.0%** | 42.9% | +0.65% | +0.91% |
| q4 [1.975e+04,6.212e+04] | 16 | **3.0%** | 37.5% | -0.13% | -0.21% |

### `ret_24h`

| bucket | n | best stop | WR | mean | total |
|---|---:|---:|---:|---:|---:|
| q1 [0.139,0.2736] | 18 | **8.0%** | 55.6% | +1.54% | +2.80% |
| q2 [0.2736,0.4771] | 18 | **1.0%** | 27.8% | +0.18% | +0.31% |
| q3 [0.4988,0.9716] | 17 | **1.0%** | 47.1% | -0.05% | -0.09% |
| q4 [0.9901,2.894] | 17 | **10.0%** | 70.6% | +0.51% | +0.86% |

### `avg_trade_size_60s`

| bucket | n | best stop | WR | mean | total |
|---|---:|---:|---:|---:|---:|
| q1 [4.91,69.56] | 17 | **7.0%** | 64.7% | +1.06% | +1.81% |
| q2 [69.56,125.9] | 17 | **8.0%** | 29.4% | +0.26% | +0.44% |
| q3 [125.9,248.3] | 18 | **1.0%** | 38.9% | +0.26% | +0.46% |
| q4 [260.1,1251] | 18 | **2.0%** | 72.2% | +0.67% | +1.21% |

### `step_2m`

| bucket | n | best stop | WR | mean | total |
|---|---:|---:|---:|---:|---:|
| q1 [0.00557,0.01503] | 18 | **1.0%** | 27.8% | -0.08% | -0.15% |
| q2 [0.01513,0.01805] | 16 | **1.0%** | 43.8% | +0.17% | +0.28% |
| q3 [0.01861,0.028] | 18 | **2.0%** | 77.8% | +1.61% | +2.92% |
| q4 [0.03017,0.1703] | 18 | **10.0%** | 50.0% | +0.23% | +0.42% |

### `candle_close_str_1m`

| bucket | n | best stop | WR | mean | total |
|---|---:|---:|---:|---:|---:|
| q1 [0.704,0.853] | 18 | **10.0%** | 38.9% | -0.41% | -0.74% |
| q2 [0.853,0.953] | 17 | **8.0%** | 41.2% | +0.60% | +1.02% |
| q3 [0.953,1] | 18 | **3.5%** | 66.7% | +0.58% | +1.04% |
| q4 [1,1] | 18 | **1.5%** | 50.0% | +0.85% | +1.53% |

## Heuristic per-trade stop

Calibrated from the per-feature analysis above. Stop = `0.040 + (spread_bps - 6) / 1000 + 0.05·ret_24h + (10k - depth) / 1M`, clipped to [1.5%, 8.0%].

- Trades:    69
- Win rate:  50.7%
- Mean net:  -0.17% per trade
- Total compound: -1.18%
- Stop range: [5.0%, 8.0%], avg 7.09%

**Heuristic vs best flat stop (1.0%):** 
heuristic mean -0.17% vs flat +0.25% — flat wins
