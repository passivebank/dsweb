# Runner DNA — Multivariate Walk-Forward Model

**Window:** signals on or after 2026-04-19 (535 rows)
**Positive class:** peak ≥ 10% (n_pos = 59)
**Model:** L2-regularized logistic regression (λ=0.5, lr=0.05, epochs=2000)
**CV:** expanding-window walk-forward by sig_date

## Headline

- **OOS walk-forward AUC: 0.548** (n_oos=476, n_pos_oos=49)
- Baseline (strongest single 2-pair, btc_rel_ret_5m − cvd_30s standardized): AUC 0.586
- Difference: **-0.038**. **The multivariate model does NOT meaningfully beat the strongest 2-feature pair.** → A simple rule-based filter encoding 1-2 interactions is likely to match or beat a learned scorecard. Don't ship the model; ship the rules.
- Features used: 31

## Top 20 coefficients (final model on all data — interpretation only)

Positive coef = feature value INCREASES P(runner). All features standardized (mean 0, sd 1) before fit, so coefficients are directly comparable in magnitude.

| feature | coef | direction |
|---|---:|:---:|
| `f_higher_lows_3m` | -0.197 | ↓ |
| `f_first_signal_today` | +0.126 | ↑ |
| `f_avg_trade_size_60s` | +0.122 | ↑ |
| `f_btc_rel_ret_5m` | +0.108 | ↑ |
| `f_cvd_30s` | -0.098 | ↓ |
| `f_step_3m` | -0.093 | ↓ |
| `f_spread_bps_at_entry` | +0.090 | ↑ |
| `f_bid_depth_usd` | +0.084 | ↑ |
| `f_btc_dom_pct` | -0.078 | ↓ |
| `f_step_1m` | -0.075 | ↓ |
| `f_large_trade_pct_60s` | -0.070 | ↓ |
| `f_fear_greed` | -0.070 | ↓ |
| `f_signals_24h` | -0.061 | ↓ |
| `f_cvd_60s` | -0.061 | ↓ |
| `f_vwap_300s` | +0.060 | ↑ |
| `f_step_2m` | +0.059 | ↑ |
| `f_secs_since_onset` | -0.056 | ↓ |
| `f_signals_1h` | +0.050 | ↑ |
| `f_cg_trending` | -0.045 | ↓ |
| `f_ask_depth_trend` | -0.044 | ↓ |

## Per-fold breakdown

| test_day | n_train | n_test | pos_train | pos_test |
|---|---:|---:|---:|---:|
| 2026-04-21 | 59 | 23 | 10 | 5 |
| 2026-04-23 | 82 | 179 | 15 | 14 |
| 2026-04-24 | 261 | 162 | 29 | 15 |
| 2026-04-25 | 423 | 112 | 44 | 15 |
