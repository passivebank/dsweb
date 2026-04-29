# Teaching Summary — what each metric actually tells us

_Companion to METRIC_ATLAS.md. The atlas has the raw numbers per
feature; this doc translates them into "if X happens, expect Y."_

Source: 4,259 unique signal moments over 14 days. Outcome categories:
- **FLAT** (peak <1%): 41.4% of signals — the bulk
- **TINY** (1-5%): 42.0% — small bounces
- **SMALL** (5-10%): 10.7%
- **MINOR** (10-30%): 5.4%
- **TRUE_RUN** (≥30%): 0.5% — the rare big mover

**Read this carefully**: AUC > 0.60 with CI clear of 0.50 = real signal.
AUC 0.50-0.55 = weak/probably-noise. AUC < 0.45 = low values predict
winners (inverted).

---

## TIER 1 — Strongest predictors (AUC ≥ 0.60, CI clear of 0.5)

These are the metrics with REAL discriminative power. If you only have
3-4 features in your filter, pick from these.

### `f_btc_rel_ret_5m` (BTC-relative 5m return)
- **AUC at +5%/5min: 0.661 [+0.04 to +0.06]** — the strongest single feature
- Top quartile WR: **34.7%** vs bottom quartile: **7.3%**
- **High = winners.** When BTC is outperforming the alt market in the last 5min, alts are MORE likely to make a run within 5 minutes.
- **Best single-rule: `≥ +4.8%`** → 2.24× lift.
- **Why it works**: when BTC is leading, alt liquidity follows. A coin signaling during BTC's outperformance is riding the macro tide.
- **What it looks like during a run**: typically +3-8% above its baseline 0% drift.

### `f_fear_greed` (daily F&G index, 0-100)
- **AUC at +5%/5min: 0.644**
- Top quartile WR 18.6% vs bottom 6.7%
- **High = winners.** Greedy-regime days produce 3× more winners than fearful days.
- **Best rule: `≥ 39`** → 1.63× lift.
- **Why**: bullish sentiment regime makes alt buyers willing to chase. Daily-level — same value all day.
- **TRUE_RUN bucket median: 22**, FLAT bucket median: 21 — the median difference is small, but the **distribution shape** matters: high F&G has FEWER false signals.

### `f_btc_dom_pct` (BTC dominance, %)
- **AUC at +5%/5min: 0.624**
- **Counterintuitive: HIGH BTC dominance predicts alt runners** (+19.9% top vs +6.8% bottom WR).
- Naive theory says LOW BTC dominance = altseason = good. The data says the opposite.
- **My read**: when BTC dom is rising, BTC is leading the market UP. Alts following = real momentum. When BTC dom is falling, BTC is dumping; alts decoupling are usually selling pressure not strength.
- **Best rule: `≥ 57.42`** → 1.76× lift.

### `f_ret_24h` (coin's 24h return)
- **AUC at +5%/5min: 0.623**
- Top quartile WR 17.7% vs bottom **2.7%** — strongest bottom-vs-top spread in the data.
- **High = winners.** A coin already up 60%+ today is FAR more likely to break +5% in the next 5 min than a coin flat or down.
- **TRUE_RUN bucket median: ≥+90% on the day already.**
- **Best rule: `≥ +59%`** → 1.42× lift.
- **Why**: this is the "trade only coins already running" rule. Mean-reversion is rare in crypto; trends extend.

---

## TIER 2 — Real but weaker signals (AUC 0.55-0.60 or 0.40-0.45)

### `f_spread_bps` (bid-ask spread, basis points)
- **AUC: 0.380 (LOW values predict)** — third-strongest in the data.
- Top quartile WR 7.2% vs bottom 17.7% — huge inversion.
- **Tight spread = winners. Wide spread = losers.** This INVERTS the long-horizon `runner_dna_v2_sharpened` finding (which was on max-horizon, not 5min).
- **For your 1-10min mission, you want spread < 6bps.**
- **Best rule: `< 3 bps`** → 1.52× lift.
- **Why**: tight spread means liquid, fairly-priced coin. Real demand can move price clean. Wide spread means thin venue and the move you see is just the spread, not real direction.

### `f_cvd_60s` (60-second cumulative volume delta)
- **AUC: 0.391 (LOW values predict)**
- **Heavy net selling in the last 60s predicts winners.**
- Top quartile (high cvd, lots of buying) WR: 8.0%. Bottom quartile (heavy selling) WR: 17.3%.
- **Best rule: `< -$23,420`** → 1.66× lift.
- **Why (the absorption pattern)**: when sellers are dumping but the price is still going up enough to fire our signal, that's institutional absorption. Buyers are eating the supply. This is one of the most reliable patterns we've found.
- Same direction at `f_cvd_30s` (AUC 0.430) but slightly weaker.

### `f_universe_signals_24h` (count of distinct coins firing today)
- **AUC: 0.425 (LOW values predict)**
- Top quartile (busy day) WR: 6.7%. Bottom quartile (quiet day): 15.0%.
- **Quiet days produce real signals. Busy days are noise.**
- **Best rule: `< 46`** → 1.33× lift.
- **Why**: when the universe is calm, a coin firing a signal is genuinely anomalous. When everything's firing, signals are random.
- This is the right denominator (NOT per-coin signals_24h, which we saw earlier penalizes coins in active runner mode).

### `f_rank_60s` (this coin's 60s rank among universe)
- **AUC: 0.442 (LOW values predict)**
- **Best rule: `< 2`** (i.e., rank=1) → 1.16× lift, weaker than expected.
- **Surprising**: rank=1 alone is weak as a predictor. The earlier filter dogma was "rank=1 only" but the data shows being a top-3 mover only adds ~16% lift.
- Better used as a hard filter with other signals than as a primary one.

### `f_ask_depth_trend` (ask depth now / 60s ago)
- **AUC: 0.446 (LOW values predict)**
- Top quartile WR 13.5% vs bottom 20.3%
- **Book thinning predicts winners.** When sellers are pulling their orders (depth dropping), price has nothing to push against → runs.
- **Best rule: `< 0.52`** → 1.29× lift.
- This is a real microstructure signal — order book flow.

### `f_avg_trade_size_60s` (avg trade $ size, last 60s)
- **AUC: 0.549 (HIGH values predict)** — modest signal
- Top quartile WR 20.4% vs bottom 14.8%
- **Bigger trades = whales = real demand.**
- TRUE_RUN bucket has median trade size $97 — actually LOWER than other buckets. So trade size matters at the SMALL/MEDIUM level but doesn't necessarily predict the very biggest moves.
- **Best rule: `≥ $434`** → 1.30× lift.

### `f_perp_oi_change_1h` (1-hour change in perp OI)
- **AUC: 0.535 (HIGH values predict)**
- Coverage only 39% (only 168 coins have OKX perps).
- New OI = new positions. If positions are growing in the hour before signal, traders are building risk → could go either direction but historically runs more often than dumps.
- **Best rule: `≥ +11.6%`** → 1.48× lift.

### `f_perp_vol_now` (current perp 1h volume)
- **AUC: 0.532 (HIGH values predict)**
- Coverage 41%.
- High perp volume = derivatives engaged = real attention.

---

## TIER 3 — Marginal signals (AUC 0.49-0.55)

These have AUC barely off 0.50. They might be useful in COMBINATION but
have no standalone predictive value.

- `f_higher_lows_3m` (boolean): AUC 0.524, top WR 17.7% vs 14.9%. Mild positive.
- `f_candle_close_str_1m`: AUC 0.551. Strong-close candles slightly more likely to continue.
- `f_book_imbalance_10`: AUC 0.514. Bid stack vs ask stack ratio. Marginal.
- `f_signals_1h`: AUC 0.524. Per-coin signal frequency.
- `f_coin_signals_4h`: AUC 0.531. Coin's recent activity.
- `f_coin_signal_share`: AUC 0.521. Coin's share of universe signals.
- `f_large_trade_pct_60s`: AUC 0.523.
- `f_bid_depth_usd`: AUC 0.519.
- `f_cg_trending`: AUC 0.471 (negative). **CG trending coins UNDERPERFORM** — they've already run.

---

## TIER 4 — No signal / noise (AUC 0.50 ± 0.02)

These are essentially random. Don't bother gating on them:
- `f_btc_ret_1h`: AUC ~0.50 (almost everything we have here had this)
- `f_utc_hour`: AUC 0.50, no time-of-day pattern
- `f_step_1m / f_step_2m / f_step_3m`: surprising — 1-3min step returns don't predict by themselves. Their effect is captured by `ret_24h` and `btc_rel_ret_5m`.
- `f_secs_since_onset`: marginal (rejected via the 8s gate, but the gate may be over-tight)
- `f_buy_share_60s`: weak
- `f_market_breadth_5m`: weak

---

## How metrics CHANGE during a real run vs a fakeout

For each tier-1 feature, the difference between TRUE_RUN bucket and
FLAT bucket medians:

| feature | FLAT median | TRUE_RUN median | shift |
|---|---:|---:|---:|
| `f_btc_rel_ret_5m` | ~0% | +5-7% | **+5pp** |
| `f_ret_24h` | ~+15% | ~+90% | **+75pp** |
| `f_fear_greed` | 21 | 23 | +2 |
| `f_btc_dom_pct` | 57.22 | 57.35 | +0.13 |
| `f_spread_bps` | 12 | 7-8 | -4 (tighter) |
| `f_cvd_60s` | -$240 | -$2,500 | -$2,260 (heavier selling) |

**The two MASSIVE features**: `ret_24h` (winners are coins already up 90%+ today) and `btc_rel_ret_5m` (winners need BTC tailwind RIGHT NOW).

---

## Practical 4-feature filter you could write today

Based on this analysis, the simplest filter that should work in the
current regime (subject to ongoing forward validation) is:

```
ENTRY:
  ret_24h            ≥ 0.30      (coin is already running today)
  btc_rel_ret_5m     ≥ 0.02      (BTC just lifted)
  spread_bps         ≤ 8         (liquid coin)
  universe_signals_24h ≤ 30      (not a noise day)

PLUS one of:
  cvd_60s            ≤ -$5,000   (absorption pattern), OR
  cvd_60s            ≥ +$500     (clean buying, no absorption)

(cvd middle range -5k to +500 is mediocre — skip.)
```

This is the rule version of what the ML models try to learn. With the
right feature combination + 30+ days of accumulation + per-day stress
testing, you'd have a properly grounded filter.

---

## Caveats on this analysis

1. **AUC values are in-sample on the 14-day window.** Forward AUC is
   typically 0.05-0.10 lower. So a 0.66 in-sample becomes ~0.58-0.61
   in true OOS — still useful but not "incredible edge."
2. **Some features have low coverage** (perp_*, ask/bid_depth_*).
   Their AUCs are computed on the subset where they exist, not the
   full population.
3. **A few buckets (TRUE_RUN, n=23) are too small** for reliable median
   estimates. The TRUE_RUN row in the change-during-runs table is
   indicative, not definitive.
4. **The 14-day data window is one regime.** Different macro
   conditions (bear, sideways, post-altseason) will produce different
   feature distributions.

---

## What I'd ask you next

Now that we have the per-metric picture, the right move is for YOU to
look at this and tell me:

1. **Which of these makes intuitive sense to you?** Some metrics may
   match traders' priors and some may surprise. The surprises are the
   ones we should weight HEAVIER (the data has information your prior
   doesn't).
2. **Are there features we're NOT recording that you think SHOULD
   matter?** Sentiment velocity, listing age, twitter mentions,
   whale-wallet activity, dev activity — anything you'd test if you
   could.
3. **What patterns in the data feel like they should INTERACT?**
   (e.g., "high ret_24h means runner — UNLESS spread is wide, in
   which case it's a fakeout"). I can run conditional analysis on
   any pair you flag.

We have the foundational understanding. Let's iterate from here.
