# Runner DNA — Conditional 2-Feature Patterns

Source: `research/runner_dna/labeled.jsonl.gz` (535 signal moments, recent only)

**Reading guide.** `rate` = P(runner) within a cell. `lift` = `rate / base_rate` — how much better than picking randomly. `wilson_lo` is the 95% lower bound on the true runner rate; `wilson_lo_lift` is that bound divided by base rate. **A pattern is real only if `wilson_lo_lift > 1.0` — meaning even the conservative end of the CI is above baseline.** Patterns where lift > 1.5 but wilson_lo_lift < 1 are small-sample lucky.

## Threshold: peak ≥ 10% (base rate 11.03%, n_pos=59)

### Top 25 BOOST cells (cells where running is more likely)

| feat_a | bucket | feat_b | bucket | n | n_pos | rate | lift | Wilson 95% CI | lo_lift |
|---|---|---|---|---:|---:|---:|---:|---|---:|
| `f_btc_rel_ret_5m` | >=0.03209 | `f_cvd_30s` | <-4990 | 48 | 16 | 33.33% | 3.02× | [21.68%, 47.46%] | 1.97× |
| `f_cvd_30s` | <-4990 | `f_vwap_300s` | >=0.1209 | 31 | 11 | 35.48% | 3.22× | [21.12%, 53.05%] | 1.91× |
| `f_cvd_60s` | <-8832 | `f_vwap_300s` | >=0.1209 | 32 | 11 | 34.38% | 3.12× | [20.41%, 51.69%] | 1.85× |
| `f_btc_rel_ret_5m` | >=0.03209 | `f_signals_24h` | <9 | 40 | 13 | 32.50% | 2.95× | [20.08%, 47.98%] | 1.82× |
| `f_btc_rel_ret_5m` | <0.007655 | `f_higher_lows_3m` | f_higher_lows_3m=F | 42 | 13 | 30.95% | 2.81× | [19.07%, 46.03%] | 1.73× |
| `f_bid_depth_usd` | >=1.655e+04 | `f_higher_lows_3m` | f_higher_lows_3m=F | 35 | 11 | 31.43% | 2.85× | [18.55%, 47.98%] | 1.68× |
| `f_ask_depth_usd` | >=1.243e+04 | `f_higher_lows_3m` | f_higher_lows_3m=F | 36 | 11 | 30.56% | 2.77× | [18.00%, 46.86%] | 1.63× |
| `f_avg_trade_size_60s` | >=209.4 | `f_utc_hour` | >=14 | 32 | 10 | 31.25% | 2.83× | [17.95%, 48.57%] | 1.63× |
| `f_btc_rel_ret_5m` | >=0.03209 | `f_ret_24h` | <0.2853 | 36 | 11 | 30.56% | 2.77× | [18.00%, 46.86%] | 1.63× |
| `f_bn_oi_delta_60s` | f_bn_oi_delta_60s=F | `f_higher_lows_3m` | f_higher_lows_3m=F | 82 | 21 | 25.61% | 2.32× | [17.40%, 36.00%] | 1.58× |
| `f_btc_rel_ret_5m` | >=0.03209 | `f_cvd_60s` | <-8832 | 42 | 12 | 28.57% | 2.59× | [17.17%, 43.57%] | 1.56× |
| `f_cvd_30s` | <-4990 | `f_higher_lows_3m` | f_higher_lows_3m=F | 42 | 12 | 28.57% | 2.59× | [17.17%, 43.57%] | 1.56× |
| `f_book_imbalance_10` | >=2.356 | `f_btc_rel_ret_5m` | >=0.03209 | 34 | 10 | 29.41% | 2.67× | [16.83%, 46.17%] | 1.53× |
| `f_avg_trade_size_60s` | >=209.4 | `f_secs_since_onset` | <4.65 | 35 | 10 | 28.57% | 2.59× | [16.33%, 45.06%] | 1.48× |
| `f_candle_close_str_1m` | [0.916,1) | `f_cvd_30s` | <-4990 | 35 | 10 | 28.57% | 2.59× | [16.33%, 45.06%] | 1.48× |
| `f_cvd_30s` | <-4990 | `f_rank_60s` | [1,2) | 93 | 22 | 23.66% | 2.15× | [16.17%, 33.23%] | 1.47× |
| `f_ask_depth_trend` | [1,1.106) | `f_signals_24h` | <9 | 31 | 9 | 29.03% | 2.63× | [16.10%, 46.59%] | 1.46× |
| `f_cg_trending` | f_cg_trending=T | `f_higher_lows_3m` | f_higher_lows_3m=F | 80 | 19 | 23.75% | 2.15× | [15.76%, 34.14%] | 1.43× |
| `f_btc_rel_ret_5m` | >=0.03209 | `f_signals_1h` | <5 | 37 | 10 | 27.03% | 2.45× | [15.40%, 42.98%] | 1.40× |
| `f_candle_close_str_1m` | [0.7415,0.916) | `f_higher_lows_3m` | f_higher_lows_3m=F | 33 | 9 | 27.27% | 2.47× | [15.07%, 44.22%] | 1.37× |
| `f_avg_trade_size_60s` | >=209.4 | `f_btc_rel_ret_5m` | >=0.03209 | 49 | 12 | 24.49% | 2.22× | [14.60%, 38.09%] | 1.32× |
| `f_avg_trade_size_60s` | >=209.4 | `f_ret_24h` | <0.2853 | 44 | 11 | 25.00% | 2.27× | [14.57%, 39.44%] | 1.32× |
| `f_btc_dom_pct` | <58.08 | `f_utc_hour` | >=14 | 34 | 9 | 26.47% | 2.40× | [14.60%, 43.12%] | 1.32× |
| `f_btc_rel_ret_5m` | >=0.03209 | `f_spread_bps_at_entry` | >=16.49 | 39 | 10 | 25.64% | 2.33× | [14.57%, 41.08%] | 1.32× |
| `f_cvd_30s` | [-4990,-1218) | `f_cvd_60s` | [-2799,74.5) | 44 | 11 | 25.00% | 2.27× | [14.57%, 39.44%] | 1.32× |

### Top 15 SUPPRESS cells (cells where running is materially less likely)

| feat_a | bucket | feat_b | bucket | n | n_pos | rate | lift | Wilson 95% CI |
|---|---|---|---|---:|---:|---:|---:|---|
| `f_ask_depth_trend` | >=1.106 | `f_bid_depth_usd` | <3340 | 38 | 0 | 0.00% | 0.00× | [0.00%, 9.18%] |
| `f_ask_depth_trend` | <0.8085 | `f_btc_rel_ret_5m` | [0.01581,0.03209) | 35 | 0 | 0.00% | 0.00× | [0.00%, 9.89%] |
| `f_ask_depth_trend` | <0.8085 | `f_cvd_30s` | >=296.4 | 31 | 0 | 0.00% | 0.00× | [-0.00%, 11.03%] |
| `f_ask_depth_trend` | <0.8085 | `f_cvd_60s` | >=74.5 | 34 | 0 | 0.00% | 0.00× | [0.00%, 10.15%] |
| `f_ask_depth_trend` | <0.8085 | `f_utc_hour` | [5,9) | 39 | 0 | 0.00% | 0.00× | [0.00%, 8.97%] |
| `f_ask_depth_trend` | <0.8085 | `f_vwap_300s` | [0.0509,0.1209) | 37 | 0 | 0.00% | 0.00× | [0.00%, 9.41%] |
| `f_ask_depth_usd` | [2330,5221) | `f_avg_trade_size_60s` | <81.58 | 31 | 0 | 0.00% | 0.00× | [-0.00%, 11.03%] |
| `f_ask_depth_usd` | <2330 | `f_utc_hour` | [9,14) | 32 | 0 | 0.00% | 0.00× | [0.00%, 10.72%] |
| `f_avg_trade_size_60s` | <81.58 | `f_bid_depth_usd` | [3340,7044) | 35 | 0 | 0.00% | 0.00× | [0.00%, 9.89%] |
| `f_avg_trade_size_60s` | <81.58 | `f_cvd_60s` | >=74.5 | 40 | 0 | 0.00% | 0.00× | [-0.00%, 8.76%] |
| `f_avg_trade_size_60s` | <81.58 | `f_market_breadth_5m` | [3,4) | 31 | 0 | 0.00% | 0.00× | [-0.00%, 11.03%] |
| `f_avg_trade_size_60s` | <81.58 | `f_secs_since_onset` | >=57.4 | 31 | 0 | 0.00% | 0.00× | [-0.00%, 11.03%] |
| `f_avg_trade_size_60s` | <81.58 | `f_signals_1h` | [8,12) | 34 | 0 | 0.00% | 0.00× | [0.00%, 10.15%] |
| `f_avg_trade_size_60s` | <81.58 | `f_signals_24h` | [23,49.5) | 41 | 0 | 0.00% | 0.00× | [0.00%, 8.57%] |
| `f_avg_trade_size_60s` | [81.58,129.6) | `f_step_1m` | <0.00425 | 30 | 0 | 0.00% | 0.00× | [-0.00%, 11.35%] |

## Threshold: peak ≥ 30% (base rate 1.31%, n_pos=7)

### Top 25 BOOST cells (cells where running is more likely)

| feat_a | bucket | feat_b | bucket | n | n_pos | rate | lift | Wilson 95% CI | lo_lift |
|---|---|---|---|---:|---:|---:|---:|---|---:|
| `f_btc_rel_ret_5m` | >=0.03209 | `f_cvd_30s` | <-4990 | 48 | 5 | 10.42% | 7.96× | [4.53%, 22.17%] | 3.46× |
| `f_btc_rel_ret_5m` | >=0.03209 | `f_signals_24h` | <9 | 40 | 4 | 10.00% | 7.64× | [3.96%, 23.05%] | 3.02× |
| `f_book_imbalance_10` | >=2.356 | `f_cvd_30s` | <-4990 | 30 | 3 | 10.00% | 7.64× | [3.46%, 25.62%] | 2.64× |
| `f_cvd_30s` | <-4990 | `f_vwap_300s` | >=0.1209 | 31 | 3 | 9.68% | 7.40× | [3.35%, 24.90%] | 2.56× |
| `f_cvd_60s` | <-8832 | `f_vwap_300s` | >=0.1209 | 32 | 3 | 9.38% | 7.17× | [3.24%, 24.22%] | 2.48× |
| `f_avg_trade_size_60s` | >=209.4 | `f_btc_rel_ret_5m` | >=0.03209 | 49 | 4 | 8.16% | 6.24× | [3.22%, 19.19%] | 2.46× |
| `f_book_imbalance_10` | >=2.356 | `f_btc_rel_ret_5m` | >=0.03209 | 34 | 3 | 8.82% | 6.74× | [3.05%, 22.96%] | 2.33× |
| `f_avg_trade_size_60s` | >=209.4 | `f_btc_dom_pct` | <58.08 | 35 | 3 | 8.57% | 6.55× | [2.96%, 22.38%] | 2.26× |
| `f_btc_rel_ret_5m` | >=0.03209 | `f_secs_since_onset` | [4.65,18.3) | 35 | 3 | 8.57% | 6.55× | [2.96%, 22.38%] | 2.26× |
| `f_candle_close_str_1m` | [0.916,1) | `f_cvd_30s` | <-4990 | 35 | 3 | 8.57% | 6.55× | [2.96%, 22.38%] | 2.26× |
| `f_btc_rel_ret_5m` | >=0.03209 | `f_ret_24h` | <0.2853 | 36 | 3 | 8.33% | 6.37× | [2.87%, 21.83%] | 2.20× |
| `f_btc_rel_ret_5m` | >=0.03209 | `f_signals_1h` | <5 | 37 | 3 | 8.11% | 6.20× | [2.80%, 21.30%] | 2.14× |
| `f_cvd_30s` | <-4990 | `f_signals_24h` | <9 | 37 | 3 | 8.11% | 6.20× | [2.80%, 21.30%] | 2.14× |
| `f_ask_depth_usd` | [5221,1.243e+04) | `f_btc_rel_ret_5m` | >=0.03209 | 38 | 3 | 7.89% | 6.03× | [2.72%, 20.80%] | 2.08× |
| `f_cvd_30s` | <-4990 | `f_secs_since_onset` | [4.65,18.3) | 38 | 3 | 7.89% | 6.03× | [2.72%, 20.80%] | 2.08× |
| `f_candle_close_str_1m` | [0.916,1) | `f_rank_60s` | [1,2) | 59 | 4 | 6.78% | 5.18× | [2.67%, 16.18%] | 2.04× |
| `f_btc_dom_pct` | <58.08 | `f_btc_rel_ret_5m` | >=0.03209 | 39 | 3 | 7.69% | 5.88× | [2.65%, 20.32%] | 2.03× |
| `f_ret_24h` | <0.2853 | `f_utc_hour` | >=14 | 39 | 3 | 7.69% | 5.88× | [2.65%, 20.32%] | 2.03× |
| `f_bid_depth_usd` | [7044,1.655e+04) | `f_btc_rel_ret_5m` | >=0.03209 | 40 | 3 | 7.50% | 5.73× | [2.58%, 19.86%] | 1.97× |
| `f_bid_depth_usd` | [7044,1.655e+04) | `f_cvd_30s` | <-4990 | 40 | 3 | 7.50% | 5.73× | [2.58%, 19.86%] | 1.97× |
| `f_btc_rel_ret_5m` | >=0.03209 | `f_utc_hour` | >=14 | 40 | 3 | 7.50% | 5.73× | [2.58%, 19.86%] | 1.97× |
| `f_avg_trade_size_60s` | >=209.4 | `f_signals_24h` | <9 | 41 | 3 | 7.32% | 5.59× | [2.52%, 19.43%] | 1.93× |
| `f_btc_rel_ret_5m` | >=0.03209 | `f_rank_60s` | [1,2) | 110 | 6 | 5.45% | 4.17× | [2.52%, 11.39%] | 1.93× |
| `f_btc_rel_ret_5m` | >=0.03209 | `f_cvd_60s` | <-8832 | 42 | 3 | 7.14% | 5.46× | [2.46%, 19.01%] | 1.88× |
| `f_btc_dom_pct` | <58.08 | `f_rank_60s` | [1,2) | 66 | 4 | 6.06% | 4.63× | [2.38%, 14.57%] | 1.82× |

### Top 15 SUPPRESS cells (cells where running is materially less likely)

| feat_a | bucket | feat_b | bucket | n | n_pos | rate | lift | Wilson 95% CI |
|---|---|---|---|---:|---:|---:|---:|---|
| `f_ask_depth_trend` | <0.8085 | `f_ask_depth_usd` | <2330 | 59 | 0 | 0.00% | 0.00× | [0.00%, 6.11%] |
| `f_ask_depth_trend` | <0.8085 | `f_ask_depth_usd` | [2330,5221) | 30 | 0 | 0.00% | 0.00× | [-0.00%, 11.35%] |
| `f_ask_depth_trend` | [0.8085,1) | `f_ask_depth_usd` | >=1.243e+04 | 44 | 0 | 0.00% | 0.00× | [0.00%, 8.03%] |
| `f_ask_depth_trend` | [1,1.106) | `f_ask_depth_usd` | [5221,1.243e+04) | 37 | 0 | 0.00% | 0.00× | [0.00%, 9.41%] |
| `f_ask_depth_trend` | >=1.106 | `f_ask_depth_usd` | [2330,5221) | 38 | 0 | 0.00% | 0.00× | [0.00%, 9.18%] |
| `f_ask_depth_trend` | >=1.106 | `f_ask_depth_usd` | [5221,1.243e+04) | 33 | 0 | 0.00% | 0.00× | [0.00%, 10.43%] |
| `f_ask_depth_trend` | <0.8085 | `f_avg_trade_size_60s` | <81.58 | 33 | 0 | 0.00% | 0.00× | [0.00%, 10.43%] |
| `f_ask_depth_trend` | <0.8085 | `f_avg_trade_size_60s` | [81.58,129.6) | 34 | 0 | 0.00% | 0.00× | [0.00%, 10.15%] |
| `f_ask_depth_trend` | <0.8085 | `f_avg_trade_size_60s` | [129.6,209.4) | 31 | 0 | 0.00% | 0.00× | [-0.00%, 11.03%] |
| `f_ask_depth_trend` | [1,1.106) | `f_avg_trade_size_60s` | <81.58 | 34 | 0 | 0.00% | 0.00× | [0.00%, 10.15%] |
| `f_ask_depth_trend` | [1,1.106) | `f_avg_trade_size_60s` | [81.58,129.6) | 36 | 0 | 0.00% | 0.00× | [0.00%, 9.64%] |
| `f_ask_depth_trend` | [1,1.106) | `f_avg_trade_size_60s` | [129.6,209.4) | 33 | 0 | 0.00% | 0.00× | [0.00%, 10.43%] |
| `f_ask_depth_trend` | >=1.106 | `f_avg_trade_size_60s` | <81.58 | 44 | 0 | 0.00% | 0.00× | [0.00%, 8.03%] |
| `f_ask_depth_trend` | >=1.106 | `f_avg_trade_size_60s` | [129.6,209.4) | 32 | 0 | 0.00% | 0.00× | [0.00%, 10.72%] |
| `f_ask_depth_trend` | <0.8085 | `f_bid_depth_usd` | <3340 | 32 | 0 | 0.00% | 0.00× | [0.00%, 10.72%] |
