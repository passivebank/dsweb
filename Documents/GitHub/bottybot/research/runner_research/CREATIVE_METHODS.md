# 40 Creative/Unusual Methods to Improve EV

Each idea below is a concrete testable hypothesis with the input data,
the predicted effect, and the lift threshold for inclusion.

---

## Tier 1 — Microstructure features (likely real edge)

**1. Top-of-book churn rate** — count of L2 quote updates in the 30s
before signal. High churn = HFT activity = avoid. Low churn = real flow.
Feature derivable from durable archive's `quote` channel events.

**2. Trade-tape clustering** — count of trades within ±50ms windows
during the 60s pre-signal. Clustered trades = single buyer split across
microstructure = institutional accumulation signal.

**3. Microprice deviation** — `microprice = (bid_size*ask + ask_size*bid)
/ (bid_size + ask_size)`. Deviation from mid > N bps signals imbalance.
Test: enter only when microprice ≥ mid (suggests next tick UP).

**4. Effective spread vs quoted spread** — measure realized spread on
recent fills (trade prices vs midprice at trade time). Tighter effective
spread than quoted = aggressive market makers = trend continuation more
likely.

**5. Order book replenishment speed** — after a 30%+ ask depletion,
how fast does the ask refill? Fast replenishment = market makers see
no further upside = avoid. Slow = nobody wants to sell into the move.

---

## Tier 2 — Cross-venue / cross-asset

**6. Coinbase-Binance spread divergence at signal** — if Coinbase price is
≥30bps below Binance at signal, Coinbase is lagging the move and we have
a lead-time advantage. Use `bn_ret_24h` already collected.

**7. Perp basis** — funding rate × OI delta. Positive funding + rising OI
= longs paying = froth = avoid for new entries. Negative funding + rising
OI = shorts squeezed = bullish acceleration. Already collect
`bn_funding_rate` and `bn_oi_delta_60s`.

**8. Cross-asset momentum index** — rolling 5m return of TOP-5 by 24h
volume. If top movers are accelerating, riskier alt entries get a
multiplier. If decelerating, scale back.

**9. ETH-BTC ratio velocity** — ETH outperforming BTC = altcoin season
likely; underperforming = BTC dominance regime. Add as macro feature.

**10. Stablecoin printer signal** — USDT+USDC market cap delta over
last 24h. Rising stablecoin supply = liquidity inflow = bullish for
alts. (Free CoinGecko API.)

---

## Tier 3 — Time-of-day / calendar

**11. UTC hour interaction** — ALL features re-tested within 4-hour
buckets. Maybe `signals_24h > 15` only kills EV during US trading
hours, not Asia. Stratify findings by hour bucket.

**12. Day-of-week effect** — Monday/Friday market profiles differ from
mid-week. Test all rules conditional on day of week.

**13. Distance from US open** — minutes since 13:30 UTC. Pre-open
moves often reverse; post-open moves often continue.

**14. Distance from FOMC / CPI** — calendar of high-impact events.
24h before/after, micro-cap correlation with BTC drops. Tighter filter
in the window.

---

## Tier 4 — Sentiment & social

**15. CoinGecko trending velocity** — change in trending rank over 1h.
If a coin moved from #not-listed to #5 in an hour, that's accelerating
attention. Top quartile of velocity should produce higher hit rate.

**16. Twitter/X mention spike via Lunarcrush** — free tier sufficient
for ~50 coins. Mention rate change × sentiment polarity. Spike with
positive polarity = retail FOMO incoming.

**17. Reddit r/cryptocurrency posts** — coin name appearance rate over
last hour. Latency-leading indicator.

**18. CoinGecko search velocity** — Google Trends API gives search
interest per coin name. Sudden +50% spike vs 7d baseline = retail
entering.

**19. Discord/Telegram chat activity** — for project-specific channels.
Hard to scrape but valuable. Skip unless someone has a working pipe.

---

## Tier 5 — Coin-state stratification

**20. Market cap tier × signal type** — find which signals work on
small caps (<$10M) vs mid ($10M-$100M) vs large ($100M-$1B). Likely
different DNA per tier.

**21. Days since Coinbase listing** — first 24h listing pumps have
different DNA than year-old coin pumps. Add `coinbase_age_days`.

**22. ATH proximity** — coin within 10% of 24h-ATH = momentum
acceleration zone. Coin at -50% from ATH = recovery rally =
different DNA.

**23. 7-day price stability** — variance of 1-hr returns over last 7
days. Steady trend coins behave differently than choppy ones. Reduce
sizing on noisy coins.

**24. Sector rotation** — group coins by category (DeFi, AI, gaming,
memes). When a sector is hot (avg 24h return high), entries on coins
in that sector get a multiplier.

---

## Tier 6 — Order-flow microstructure (advanced)

**25. Aggressive trade volume share** — ratio of taker-aggressed vs
maker-resting volume in last 30s. >70% taker volume = momentum buying.
Very strong predictor in equities; should test crypto.

**26. Iceberg detection** — same-size repeated trades at same price =
hidden order being chunked. Strong continuation signal.

**27. Run length (price up-ticks vs down-ticks)** — trailing 60s,
streak of ↑ ticks ≥ 7 with no ↓ tick = momentum building.

**28. Trade flow toxicity (VPIN)** — Easley/Lopez de Prado measure of
informed trading. Extreme VPIN = informed flow = bullish or bearish
asymmetry.

**29. Hidden liquidity pings** — small probe orders at iceberg-level
prices. Identify and follow institutional buying patterns.

---

## Tier 7 — Position management innovations

**30. Volatility-scaled position size** — larger position when implied
volatility is LOWER (less expected adverse move = better Kelly sizing).
Use vwap_300s deviation as proxy.

**31. Conditional take-profit ladder** — instead of fixed +1%/+2%/+3%
locks, scale them by recent realized volatility. High vol = wider locks.

**32. Adaptive trail width** — trail = 1.5 × ATR(5min). Tight in calm,
wide in volatile.

**33. Win-streak Kelly** — increase position size after wins, decrease
after losses (within bounds). Captures regime by recency.

**34. Concurrent position correlation cap** — refuse to open a 3rd
position if first two are correlated >0.7 with the new candidate.
Avoids regime-concentration risk.

**35. Time-of-trade pyramiding** — if trade gains +2% in first 30s,
add 50% more size. Aggressive runner detection — only the explosive
ones move that fast.

---

## Tier 8 — Statistical / ML enhancements

**36. Stacked model ensemble** — LightGBM + LogReg + Random Forest +
small NN, voted via meta-learner. Reduces model-specific failure modes.

**37. Online learning** — update model weights daily on the previous
day's outcomes. Catches regime shifts in days, not weeks.

**38. Bayesian beta-binomial per-coin posterior** — track each coin's
WR with informative prior (across-coin baseline). Use posterior
probability to scale position size, not block.

**39. Causal forest / Heterogeneous Treatment Effects** — for each
candidate signal, estimate "what's the average return I'd get if I
took this signal vs not-took". Goes beyond AUC to actual EV per signal.

**40. Reinforcement learning for exit timing** — train an RL agent to
make exit decisions tick-by-tick within the held position. Reward = net
P&L. Could find non-linear exit patterns no human rule encodes.

---

## How to evaluate these

For each idea:
1. Build the feature/mechanism in the recorder
2. Let it accumulate ≥30 days of shadow data
3. Re-run `research/runner_dna/evaluate_candidate.py` with the new
   feature in the candidate filter
4. If walk-forward CI lower bound on mean_net rises by ≥+0.10% and
   maintains across regimes, promote to live filter

Highest priority by expected lift:
- **Tier 1** (microstructure features): highest priority, most likely
  to find real edge given our 14-day data already shows AUC 0.735
- **Tier 2** (cross-venue): we already collect Binance data; quick wins
- **Tier 5** (coin-state stratification): the user's original mission
  was "trade based on coin specifics" — directly addresses this
- **Tier 7** (position management): cheapest to implement, modest lift
- **Tier 8** (ML enhancements): only useful once microstructure is
  exhausted

## Lowest priority (but still worth listing)

These are the wild ideas that probably don't pay off but might surprise:

- News sentiment via OpenAI/Anthropic embedding similarity to past pumps
- Astrology / planetary alignment (joking — but tested, no edge)
- Economic calendar event proximity (tested in equities; mixed in crypto)
- Twitter follower count of project founders (proxy for retail awareness)
- Listing on new exchanges within last 30 days
- Audit report dates (CertiK / Halborn) — release dates correlate with pumps
- Github commit activity (developer engagement proxy)
