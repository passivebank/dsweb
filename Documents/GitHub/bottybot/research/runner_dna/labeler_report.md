# Runner DNA — Labeler Report

- Source rows in shadow_trades.jsonl: **100,050**
- Unique signal moments (deduped): **4,054**
- Output: `research/runner_dna/labeled.jsonl.gz` (jsonl.gz)

## Label distribution

| label | count | pct |
|---|---:|---:|
| MEGA_RUNNER | 0 | 0.00% |
| TRUE_RUNNER | 23 | 0.57% |
| MINOR_RUN | 219 | 5.40% |
| SMALL_BOUNCE | 422 | 10.41% |
| NO_RUN | 3,390 | 83.62% |

## TRUE_RUNNER / MEGA_RUNNER moments by coin (top 25)

| coin | n |
|---|---:|
| RARI | 5 |
| TIME | 3 |
| BASED1 | 3 |
| WAL | 2 |
| SAPIEN | 2 |
| RAVE | 2 |
| MEZO | 1 |
| NCT | 1 |
| TROLL | 1 |
| RSC | 1 |
| KAT | 1 |
| HYPER | 1 |

## Daily signal volume + runner counts

| date | signals | TRUE_RUNNER+ | MINOR_RUN | NO_RUN |
|---|---:|---:|---:|---:|
| 2026-04-11 | 1 | 0 | 0 | 1 |
| 2026-04-12 | 165 | 0 | 3 | 159 |
| 2026-04-13 | 1757 | 1 | 45 | 1546 |
| 2026-04-14 | 756 | 0 | 28 | 669 |
| 2026-04-15 | 426 | 8 | 43 | 311 |
| 2026-04-16 | 355 | 4 | 37 | 264 |
| 2026-04-17 | 32 | 2 | 6 | 15 |
| 2026-04-18 | 27 | 1 | 5 | 13 |
| 2026-04-19 | 25 | 1 | 2 | 17 |
| 2026-04-20 | 34 | 1 | 6 | 22 |
| 2026-04-21 | 23 | 2 | 3 | 13 |
| 2026-04-23 | 179 | 1 | 13 | 147 |
| 2026-04-24 | 162 | 1 | 14 | 127 |
| 2026-04-25 | 112 | 1 | 14 | 86 |

## Feature coverage (top 30)

| feature | non-null moments | coverage |
|---|---:|---:|
| `f_spread_bps_at_entry` | 4,054 | 100.0% |
| `f_spread_bps` | 3,921 | 96.7% |
| `f_fear_greed` | 3,891 | 96.0% |
| `f_btc_ret_1h` | 3,891 | 96.0% |
| `f_cvd_30s` | 3,888 | 95.9% |
| `f_cvd_60s` | 3,888 | 95.9% |
| `f_ret_24h` | 3,888 | 95.9% |
| `f_utc_hour` | 3,888 | 95.9% |
| `f_signals_24h` | 3,888 | 95.9% |
| `f_signals_1h` | 3,888 | 95.9% |
| `f_btc_dom_pct` | 3,882 | 95.8% |
| `f_book_imbalance_10` | 3,479 | 85.8% |
| `f_rank_60s` | 3,048 | 75.2% |
| `f_secs_since_onset` | 1,989 | 49.1% |
| `f_market_breadth_5m` | 1,989 | 49.1% |
| `f_ask_depth_trend` | 1,989 | 49.1% |
| `f_first_signal_today` | 1,989 | 49.1% |
| `f_btc_rel_ret_5m` | 1,989 | 49.1% |
| `f_avg_trade_size_60s` | 1,989 | 49.1% |
| `f_large_trade_pct_60s` | 1,989 | 49.1% |
| `f_vwap_300s` | 1,989 | 49.1% |
| `f_candle_close_str_1m` | 1,989 | 49.1% |
| `f_higher_lows_3m` | 1,989 | 49.1% |
| `f_cg_trending` | 1,989 | 49.1% |
| `f_ask_depth_usd` | 1,763 | 43.5% |
| `f_bid_depth_usd` | 1,763 | 43.5% |
| `f_step_1m` | 1,092 | 26.9% |
| `f_step_2m` | 1,092 | 26.9% |
| `f_step_3m` | 1,092 | 26.9% |
| `f_total_3m` | 1,091 | 26.9% |
