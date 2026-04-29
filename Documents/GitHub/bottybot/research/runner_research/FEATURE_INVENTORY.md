# Complete Feature Inventory — what we record, what we don't, what we could

The earlier METRIC_ATLAS only showed 31 features (≥30% coverage cutoff).
This document is the **complete** inventory: all 77 raw features in
shadow_signals + every external data source + a candid list of what
we DON'T record but easily could.

---

## A. Recorded directly by the detector engine (77 features)

### A1. Universal — recorded on essentially every signal (≥80% coverage)

| feature | coverage | what it is |
|---|---:|---|
| `spread_bps` | 99.3% | Bid-ask spread at signal time, bps |
| `fear_greed` | 99.1% | Daily F&G index, 0-100 |
| `btc_ret_1h` | 99.1% | BTC 1-hour return |
| `cvd_30s` / `cvd_60s` | 99.1% | Cumulative volume delta over 30s/60s window (USD) |
| `ret_24h` | 99.1% | Coin's 24-hour return |
| `utc_hour` | 99.1% | UTC hour of signal (0-23) |
| `signals_24h` / `signals_1h` | 99.1% | This coin's signal count today / last hour |
| `btc_dom_pct` | 98.9% | BTC dominance % at signal |
| `book_imbalance_10` | 86.3% | bid_depth_top10 / ask_depth_top10 ratio |
| `secs_since_onset` | 82.2% | Seconds from move onset to signal — staleness gate |
| `market_breadth_5m` | 82.2% | Count of coins with positive 5m return |
| `ask_depth_trend` | 82.2% | ask_depth_now / ask_depth_60s_ago |
| `first_signal_today` | 82.2% | Boolean: first signal for this coin today |
| `btc_rel_ret_5m` | 82.2% | Coin's 5m return − BTC's 5m return |
| `avg_trade_size_60s` | 82.2% | Avg $ size of trades in last 60s |
| `large_trade_pct_60s` | 82.2% | Fraction of last 60s volume from trades ≥ $500 |
| `vwap_300s` | 82.2% | 5-minute VWAP price |
| `candle_close_str_1m` | 82.2% | (close-low)/(high-low) for 1m candle. 1.0 = closed at high |
| `higher_lows_3m` | 82.2% | Boolean: did coin make higher lows over last 3 min |
| `cg_trending` | 82.2% | Boolean: was coin on CoinGecko trending list |
| `rank_60s` | 73.9% | This coin's rank by 60s return across all monitored coins |
| `ask_depth_usd` / `bid_depth_usd` | 71.0% | Top-10 depth in USD on each side |

### A2. Less common but recorded (20-50% coverage)

| feature | coverage | what it is |
|---|---:|---|
| `bn_oi_delta_60s` | 34.9% | Binance perp OI 60s change (legacy: now via OKX) |
| `secs_since_run` | 26.1% | Seconds since run was first detected (vs onset) |
| `run_peak_mid` | 26.1% | Recent peak mid price during the active run |
| `run_signal_mid` | 26.1% | Mid price at signal moment |
| `peak_gain_pct` | 26.1% | Coin's gain from session low to recent peak |
| `pullback_from_peak` | 26.1% | How far below recent peak price is at signal |
| `hold_ratio` | 26.1% | Position-holding ratio (recorder internal) |
| `buy_share_60s` | 26.1% | Fraction of trades that were taker-buys in last 60s |
| `rate_30s` | 26.1% | Rate of price change in last 30s |
| `step_1m` / `step_2m` / `step_3m` | 23.0% | 1/2/3-minute bar returns |
| `total_3m` | 22.3% | Cumulative 3-min return |
| `dv_30s_usd` | 21.2% | Dollar volume in last 30s |
| `dv_30s_mult` | 21.2% | dv_30s / 60-bar baseline — volume spike strength |
| `move_from_5m_low` | 21.2% | Movement from 5-min low |
| `buy_share_10s` | 21.2% | Taker-buy fraction in last 10s |

### A3. Rare — variant-specific or experimental (<20% coverage)

| feature | coverage | what it is |
|---|---:|---|
| `breakout_pct` | 16.1% | How far past recent high price has broken |
| `prior_high` | 16.1% | The recent high price being broken |
| `dv_burst_30s` | 16.1% | Volume burst over 30s |
| `dv_burst_mult` | 16.1% | dv_burst / baseline ratio |
| `dv_trend` | 13.8% | Dollar volume trend ratio |
| `ret_15m` / `ret_5m` / `ret_1m` | 12.1% | Multi-timeframe returns |
| `runner_dna_v1` | 11.2% | Boolean: did v1 filter accept |
| `typical_spread` | 8.2% | Coin's typical spread baseline |
| `confidence_tier` | 7.3% | A/B/C/D tier from old precision filter |
| `position_pct` | 7.3% | Recommended position % (legacy) |
| `cls_p_fakeout` / `cls_p_go` / `cls_p_weak` | 3.5% | Old runner classifier outputs |
| `cls_verdict` / `cls_pos_scale` / `cls_scored` | 3.5% | Old runner classifier metadata |
| `whale_pct_60s` | 1.8% | Fraction of volume from whale trades |
| `rate_ratio` | 1.6% | Trade rate ratio |
| `ret_60s` | 1.6% | 60-second return |
| `ret_30s` / `ret_180s` | 1.2% | 30s and 3-min returns |
| `buy_share_30s` | 1.2% | Taker-buy share over 30s |
| `max_pullback_30s` | 1.2% | Max pullback in 30s |
| `dv_30s` / `mean_step` / `avg_trade_size` / `spread_ratio` | 0.7% | Variant-internal |
| `cb_binance_premium` | 0.6% | Coinbase price minus Binance price (cross-venue lag) |
| `bn_ret_24h` | 0.6% | Binance 24h return (cross-exchange) |
| `prev_min_rank` | 0.4% | Previous minute's rank |
| `max_pullback_60s` | 0.4% | Max pullback in 60s |
| `bn_funding_rate` | 0.2% | Binance perp funding rate (mostly via OKX now) |
| `spread_gate_used` | 0.2% | Boolean: was spread gate active |

---

## B. Recorded externally, joined per signal

| source | what it adds | coverage on signals |
|---|---|---|
| **CoinGecko** (daily snapshot) | market_cap_usd, mcap_rank, fdv, supply, volume_24h_usd, price_change_1h/24h/7d, ATH price + change_pct + date, ATL, **categories (DeFi/AI/meme)**, **genesis_date**, twitter_followers, reddit_subscribers | only ~3-5% on retroactive data — collection started 2026-04-27. Will grow. |
| **OKX perpetuals** (backfill + daily) | last_funding_rate, funding_rate_24h_avg, funding_rate_change_24h, oi_now, oi_change_1h/4h, oi_vs_24h_avg, vol_now, vol_change_1h, vol_vs_24h_avg | 168 of 389 coins (43%); 28% of signals enriched |

---

## C. What we DON'T record but COULD (and probably should)

This is what you were asking about. None of these exist in shadow_signals
today, but **all are computable from data we already collect** at the
detector or recorder level.

### C1. Classical technical indicators (zero coverage — never recorded)

| indicator | what it'd capture | difficulty |
|---|---|---|
| **RSI(14)** on 1m / 5m | Overbought (>70) / oversold (<30) momentum | Easy. Need rolling close prices. |
| **MACD** (12/26/9) on 1m / 5m | Trend strength + momentum crossover | Easy. Two EMAs + signal line. |
| **Bollinger Bands** position | Where price is in volatility envelope | Easy. SMA + 2σ. |
| **Stochastic Oscillator** | Momentum oscillator | Easy. 14-period high/low. |
| **OBV** (On Balance Volume) | Cumulative volume by direction | Easy. Sign × volume. |
| **ATR**(14) | Average True Range — volatility magnitude | Easy. |
| **ADX**(14) | Trend strength regardless of direction | Medium. |
| **Ichimoku Cloud** position | Multi-timeframe trend + S/R | Medium. |

### C2. Multi-timeframe price action (zero coverage — partial info exists)

| metric | what it'd capture | difficulty |
|---|---|---|
| `ret_15m`, `ret_30m`, `ret_1h`, `ret_4h`, `ret_12h` | Full return ladder | Easy. Recorder tracks tick prices. |
| `peak_gain_4h` / `peak_gain_24h` | Coin's intraday peak | Easy. |
| `consecutive_green_5m` (1m / 5m) | How many consecutive up bars | Easy. |
| `time_above_vwap_300s` | How long price has held above VWAP | Easy. |
| `daily_session_high_distance` | Distance from session high (%) | Easy. |
| `support_distance` / `resistance_distance` | Distance to nearest local levels | Medium. |

### C3. Volume/microstructure (some recorded, much more possible)

| metric | what it'd capture | difficulty |
|---|---|---|
| `dollar_vol_5m` / `_15m` / `_1h` | Multi-window volume | Easy. |
| `vol_vs_5d_avg` / `vol_vs_30d_avg` | Volume anomaly detection | Easy. We have CG daily volume. |
| `quote_count_30s` (book updates) | HFT activity proxy | Medium. Have raw books. |
| `iceberg_score` | Same-size repeated trades = hidden order | Medium. |
| `effective_spread_60s` | Realized vs quoted spread | Medium. |
| `taker_imbalance_5m` | longer-window CVD ratio | Easy. |
| `top_3_trade_pct_60s` | Concentration of last 60s volume in top 3 trades | Easy. |
| `vpin` (volume-clock) | Toxic flow indicator | Hard. Best-in-class. |

### C4. Cross-asset / regime context

| metric | what it'd capture | difficulty |
|---|---|---|
| `eth_btc_ratio_5m` | ETH outperforming BTC = altseason | Easy. |
| `top10_alts_avg_ret_5m` / `_1h` | Are alts as a class moving? | Medium. |
| `corr_to_btc_30d` | This coin's beta to BTC | Easy. |
| `corr_to_top_runner_5m` | Is this coin moving WITH the day's biggest mover? | Medium. |
| `sector_avg_ret_5m` (DeFi, AI, gaming, meme) | Hot sector? | Easy with CG categories. |
| `stablecoin_supply_delta_24h` | Liquidity inflow proxy | Easy via CG. |

### C5. Sentiment & social (mostly need external APIs)

| metric | what it'd capture | difficulty |
|---|---|---|
| `cg_trending_rank_velocity` | Rate of change in CG trending position | Easy. We poll CG already. |
| `cg_search_volume` | Google Trends / CG search popularity | Medium. CG has /search/trending. |
| `twitter_mentions_velocity` | Mentions rate vs baseline | Hard. Twitter API paid; Lunarcrush option. |
| `reddit_mention_rate` | r/cryptocurrency mention velocity | Medium. PRAW/pushshift. |
| `discord_activity` | Project channel chatter | Hard. |
| `news_event_proximity` | Time to nearest scheduled event | Medium. CryptoCompare/CMC calendar. |

### C6. On-chain / wallet (would require third-party data)

| metric | what it'd capture | difficulty |
|---|---|---|
| `whale_inflow_24h` | Large wallets accumulating | Hard. Need Nansen/Glassnode. |
| `top10_wallet_balance_change` | Concentration changes | Hard. |
| `cex_outflow_24h` | Coins leaving exchanges = supply shock | Hard. |
| `exchange_balance` | How much supply on CEX | Medium with CryptoQuant. |

### C7. Time-since features (we have a few; we could have many more)

We have `secs_since_onset`, `secs_since_run`, `signals_24h`, `signals_1h`.
Easy additions:

| metric | difficulty |
|---|---|
| `hours_since_last_runner_for_this_coin` (≥10% peak) | Easy. |
| `hours_since_listing_on_coinbase` | Need CB product creation date. |
| `hours_since_last_ATH` | Easy via CG `ath_date`. |
| `days_since_last_24h_volume_spike` | Easy. |
| `seconds_since_BTC_dump` (>2% in 5m) | Easy. |
| `time_since_last_FOMC` | Easy with calendar. |

### C8. Per-coin learned features (we have the per-coin scorecard but it's not joined yet)

Already collecting:
- `coin_7d_winrate`, `coin_7d_mean_net`, `coin_7d_total_net`
- `coin_5pct_hit_rate`, `coin_days_since_runner`

These are computed daily by `per_coin_scorecard.py` but **not yet
joined into shadow_signals at signal time**. That's a one-line wire-up
in the recorder.

### C9. Listed-on-Coinbase features (zero coverage)

| metric | what it'd capture | difficulty |
|---|---|---|
| `cb_listing_age_days` | New listings have unique pump dynamics | Easy. CB API has product create date. |
| `cb_listing_within_30d` | Boolean for "fresh listing" | Easy. |
| `cb_pair_count` | How many CB pairs this coin has (USD/USDT/USDC/BTC) | Easy. |

---

## D. Why the atlas only showed 31

The atlas filtered to **≥30% coverage** because features below that
have too few observations to compute reliable AUCs. When `step_2m`
(23% coverage) shows AUC 0.50, that's likely because we only see
step_2m on R7-style detector firings — a self-selected subset.

The right way to USE the lower-coverage features is conditional
analysis:
- "Among signals that have step_2m available (R7 firings), what's the
  distribution and predictive power?"

I can re-run the atlas conditional on each detector variant
(R3/R4/R5/R6/R7/R8/R10/R11) — that surfaces variant-specific
predictors.

---

## E. What I think you should ask me to do next

Pick which of these is most important to you:

1. **Add classical TA indicators** (RSI, MACD, Bollinger, ATR) to the
   recorder. These are zero-cost computations on data we already see.
   I can implement and we'd start collecting in <30 min. Re-run the
   atlas in 7 days with them included.

2. **Add multi-timeframe returns** (`ret_15m`, `ret_1h`, `ret_4h`,
   `consecutive_green_5m`, `peak_gain_4h`). Same — recorder change,
   forward collection only.

3. **Wire per-coin scorecard into shadow_signals** so future ML
   retrains have `coin_7d_winrate` etc. as features. 5-line change.

4. **Re-run the atlas conditional on detector variant** so the
   23%-coverage features (step_2m, total_3m, etc.) are evaluated
   against the right population.

5. **Add Coinbase listing-age + sector-from-CG** features. Static per
   coin, easy join.

6. **Build cross-asset regime features** (`eth_btc_ratio_velocity`,
   `top10_alts_avg_ret_5m`, `sector_avg_ret`).

Tell me which (combinations welcome) and I'll execute.
