# Stop Optimization — Findings

User asked: simulate exact 4% and other stops, find positive-EV number,
check whether per-coin calibration is feasible.

Source: 72 runner_dna_v1 entries with full forward trajectory across 14
days of shadow data, +24bps stress costs, 10% sizing, kill switch +
per-coin loss limit applied.

## Headline answer

**No flat hard stop produces statistically positive EV on
runner_dna_v1.** Best flat is 1.0% with mean +0.25%/trade but CI lower
bound -0.30% — within noise. The current 2.5% stop is the worst
practical choice (mean -0.07%, CI lo -0.69%).

But: a **sharpened filter that gates on spread + depth + step_2m**
produces the **first positive CI lower bound** we've seen in any
analysis on this dataset.

## The flat-stop curve

| stop | n | WR | mean | CI lo (95%) | total | Sharpe |
|---:|---:|---:|---:|---:|---:|---:|
| 1.0% | 60 | 40.0% | +0.25% | **-0.30%** | +1.47% | 7.45 |
| 1.5% | 61 | 41.0% | +0.05% | -0.54% | +0.28% | 1.33 |
| 2.0% | 64 | 45.3% | +0.02% | -0.58% | +0.11% | 0.60 |
| **2.5% (LIVE)** | 64 | 45.3% | **-0.07%** | -0.69% | -0.45% | -1.91 |
| 3.0% | 69 | 49.3% | -0.06% | -0.69% | -0.42% | -1.93 |
| 3.5% | 69 | 50.7% | -0.01% | -0.67% | -0.11% | -0.45 |
| 4.0% | 69 | 50.7% | -0.08% | -0.78% | -0.61% | -2.63 |
| 5.0% | 69 | 50.7% | -0.23% | -1.00% | -1.61% | -6.18 |
| 6.0% | 69 | 50.7% | -0.30% | -1.14% | -2.10% | -7.55 |
| 8.0% | 69 | 50.7% | +0.04% | -0.68% | +0.25% | 1.41 |
| 10.0% | 69 | 50.7% | +0.14% | -0.52% | +0.97% | 4.24 |

Every CI lower bound spans below zero. **No flat stop has a
statistically detectable edge on the broad runner_dna_v1 universe.**

The shape is informative: tight stops protect from blow-ups but cut
the few real winners, and stops between 4-6% are strictly worse than
either extreme. Going wider than 6% only recovers because the 14-day
window happens to contain large absolute movers (TIME, MEZO, RARI,
BIO) that require room to develop.

## Per-feature stratification — which buckets are real?

Stratifying the 72 trades by feature quartiles and finding the optimal
flat stop within each bucket:

### `spread_bps_at_entry` — clearest signal

| bucket | n | best stop | WR | mean | total |
|---|---:|---:|---:|---:|---:|
| q1 [2.3, 8.0] tight | 18 | 1.0% | 33.3% | -0.32% | -0.58% |
| q2 [8.5, 14.5] | 18 | 1.0% | 22.2% | -0.32% | -0.57% |
| q3 [14.7, 19.2] | 18 | 10.0% | **77.8%** | +0.64% | +1.16% |
| q4 [19.4, 27.8] wide | 18 | 6.0% | 61.1% | **+1.84%** | +3.34% |

**Wider spreads need wider stops AND produce the positive EV.** This
inverts the precision-filter dogma — the prior `spread_bps in [5,10]`
gate was excluding the buckets that actually pay.

### `ask_depth_usd` — clear inversion

| bucket | n | best stop | WR | mean | total |
|---|---:|---:|---:|---:|---:|
| q1 [227, 2580] thin | 14 | 3.5% | **64.3%** | +1.03% | +1.45% |
| q2 [2877, 5251] | 14 | 2.0% | 57.1% | +1.75% | +2.46% |
| q3 [5429, 8548] | 13 | 2.5% | 61.5% | +0.85% | +1.10% |
| q4 [9445, 37k] deep | 16 | 1.0% | **18.8%** | -0.78% | -1.25% |

**Thick-book trades are losing.** This is counterintuitive but
consistent with the spread finding: deep books mean lots of competing
liquidity providers, fewer paying customers; thin books with real
demand are where runs continue.

### `step_2m`

| bucket | n | best stop | WR | mean | total |
|---|---:|---:|---:|---:|---:|
| q1 [0.0056, 0.015] | 18 | 1.0% | 27.8% | -0.08% | -0.15% |
| q2 [0.0151, 0.018] | 16 | 1.0% | 43.8% | +0.17% | +0.28% |
| q3 [0.0186, 0.028] | 18 | 2.0% | **77.8%** | **+1.61%** | +2.92% |
| q4 [0.0302, 0.170] | 18 | 10.0% | 50.0% | +0.23% | +0.42% |

**Mid-high step_2m is the sweet spot.** Below 0.015 = noise; above
0.030 = late entry on a coin that's already exploded.

### Also tested but no clear pattern: `bid_depth_usd`, `ret_24h`,
`avg_trade_size_60s`, `candle_close_str_1m`

These showed mixed direction across quartiles.

## The sharpened filter — what to actually deploy

Combine the three real signals as additional gates on top of
runner_dna_v1:

```
runner_dna_v2_sharpened(features, variant) =
  runner_dna_v1(features, variant)
  AND spread_bps_at_entry ≥ 14
  AND ask_depth_usd ≤ 9000
  AND step_2m ≥ 0.015
```

### Sharpened filter — flat stop sweep (n=26)

| stop | n | WR | mean | CI lo (95%) | total | Sharpe |
|---:|---:|---:|---:|---:|---:|---:|
| 1.0% | 19 | 52.6% | +1.12% | -0.28% | +2.13% | 10.99 |
| 1.5% | 20 | 60.0% | +1.65% | -0.00% | +3.34% | 14.86 |
| 2.0% | 21 | 66.7% | +1.70% | +0.04% | +3.62% | 19.48 |
| 2.5% | 21 | 66.7% | +1.61% | -0.11% | +3.41% | 18.77 |
| 3.0% | 26 | 73.1% | +1.44% | +0.18% | +3.78% | 18.16 |
| **3.5%** | **26** | **76.9%** | **+1.65%** | **+0.37%** | **+4.37%** | 18.87 |
| 4.0% | 26 | 76.9% | +1.62% | +0.31% | +4.27% | 19.11 |
| 5.0% | 26 | 76.9% | +1.54% | +0.20% | +4.06% | 19.56 |
| 6.0% | 26 | 76.9% | +1.68% | +0.33% | +4.43% | 18.73 |
| 10.0% | 26 | 76.9% | +1.85% | **+0.64%** | +4.91% | 17.56 |

**At 3.5% stop, the sharpened filter has a CI lower bound of +0.37% —
the first time we've seen a positive lower bound on this dataset.**

10% stop has the highest CI lo (+0.64%) but the gap from 3.5% is small
and a 10% stop is operationally risky (single bad day kills the kill
switch budget).

### Per-coin calibration — feasible but data-thin

Direction we'd want a heuristic to follow, from the per-feature
analysis:

```
stop_pct = 0.035                                # base
        + max(0, (spread_bps - 14) * 0.0005)   # +5bps stop per bps over 14
        + step_2m_bucket_adjustment             # tighter for q4, looser for q3
        + max(0, (8000 - ask_depth) * 1e-6)    # very thin books need room
```

A naive heuristic version (pre-calibration) underperforms flat 3.5% on
the n=26 sample. To make per-coin calibration win we'd need ~5x more
data per bucket — call it 6-8 weeks of accumulating sharpened-filter
shadow data before the heuristic can be properly fit.

## Caveats

1. **n=26 over 14 days.** Small sample. Coin-concentrated: TIME (7),
   MEZO (4), RARI (4) account for 15/26 trades.
2. **In-sample bias.** The features chosen for sharpening were
   identified BY examining this same data. Real OOS performance is
   typically 30-40% lower than in-sample.
3. **Regime dependent.** The 14-day window contained Apr 15's
   altseason day. Different regime → different result.

## Recommended action

1. **Keep halt on the live bot.** The current 2.5% stop on
   runner_dna_v1 is statistically negative.
2. **Add `runner_dna_v2_sharpened` to the registry.** Done — already
   in the registry.
3. **Let it accumulate shadow data for 7-14 days.** The auto-promotion
   engine will score it on rolling windows. When it clears the gate
   (≥15 OOS trades, CI lo > 0, ≥+0.2% uplift over champion), it
   auto-promotes.
4. **Do NOT change the live filter or stop today** based on these
   findings. They're in-sample. Hold the halt; let shadow data
   validate. Promotion happens automatically when it earns it.
