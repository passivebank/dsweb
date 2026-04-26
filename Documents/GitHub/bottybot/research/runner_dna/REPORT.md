# Runner DNA — Findings After Univariate + Conditional Analysis

**Source data:** 4,054 unique signal moments across 14 days (2026-04-11 → 2026-04-25).
Forward-peak labels from the simulator's `fwd_max_pct` (supremum across exit policies per signal moment).

**Positive class definitions:**
- `MINOR_RUN+` = peak ≥ 10% (n=242 over 14 days, 59 in recent 7-day high-coverage window)
- `TRUE_RUNNER+` = peak ≥ 30% (n=23 over 14 days, 7 in recent window)

---

## Headline findings

### 1. "Absorption pattern" is the strongest conditional pattern in the data

When BTC has lifted relative to the alt market in the last 5 minutes
(`btc_rel_ret_5m ≥ +3.2%`) AND there is heavy net selling in the
last 30s (`cvd_30s < -$5,000`), the runner rate is:

- **33% (peak ≥ 10%)** — CI [22%, 47%], n=48, lift 3×
- **10% (peak ≥ 30%)** — CI [5%, 22%], n=48, lift **8×**

**This is the absorption signature you described.** Macro turns risk-on
*and* big sellers are dumping — buyers absorb the dump, the coin
breaks out. The current precision filter does not catch this — it
explicitly *blocks* trades when CVD is heavily negative
(`cvd_30s > -2000`). The data here says that gate is the wrong sign
on the wrong feature: blocking the strongest predictor of the kind
of move the user wants to capture.

### 2. There are two distinct runner profiles — current code only finds one

When `higher_lows_3m == False` is paired with depth/macro features:

| condition | n | rate | lift |
|---|---:|---:|---:|
| `higher_lows_3m=F` × `btc_rel_ret_5m < 0.008` | 42 | 31% | 2.81× |
| `higher_lows_3m=F` × `bid_depth_usd ≥ $16k` | 35 | 31% | 2.85× |
| `higher_lows_3m=F` × `ask_depth_usd ≥ $12k` | 36 | 31% | 2.77× |
| `higher_lows_3m=F` × `cvd_30s < -$5k` | 42 | 29% | 2.59× |

The R12 entry gate (R7+R11+R12) explicitly *requires*
`higher_lows_3m == True`. **That filter excludes a runner population
that fires at ~30% hit rate.** Two profiles exist:

- **Continuation profile** — higher highs/lows, momentum: caught by current detectors
- **Absorption / bounce profile** — pullback (no higher lows), heavy
  selling that gets absorbed, depth supports: not caught by current
  detectors. This is what produced 30% of the recent-window runners.

### 3. Macro regime dominates

`fear_greed` AUC 0.677 @10% / 0.767 @30% (CIs both well clear of 0.55).
This is a daily-level variable — it tells you which DAYS to trade
aggressively, not which signals to take within a day. The current
filter ignores it. **A simple `fear_greed >= 22` gate at the day
level should be added.**

`btc_dom_pct >= 57.33` × `cvd_30s < -4385` → 15% runner rate (lift 2.6×, CI lower bound 11%).
Macro setup matters even when within-coin signal is otherwise strong.

### 4. The current precision filter is directionally wrong on at least one critical feature

The data here suggests three changes to the current `champion_passes()`:

| Current filter | What data says |
|---|---|
| `cvd_30s > -2000` | Should be REMOVED or INVERTED. Strong negative CVD predicts runners. |
| `higher_lows_3m == True` (R12) | Should be a TWO-PATH detector: this OR `higher_lows_3m == False` + absorption pattern. |
| (missing) | `btc_rel_ret_5m >= 0.03` should be a hard gate — single most powerful conditional pattern depends on this. |
| (missing) | `fear_greed >= 22` daily regime gate. |

### 5. The R7-style step features (`step_2m`, `candle_close_str_1m`) are valid but not as strong as the conditional patterns

`step_2m`, `step_1m`, `candle_close_str_1m` only have 27% coverage so they
were excluded from the 14-day univariate. In the recent 535-row window
they show up:

- `candle_close_str_1m ≥ 0.916` × `cvd_30s < -4990` → 28% runner rate, lift 2.6×

So R7 step/close features ARE real predictors, but they're individually
weaker than the macro+CVD interactions. They probably belong in the
filter as supporting evidence, not as primary gates.

---

## Strong patterns surfaced (recent 7-day window, n_pos=59 at 10%)

Top boost cells by Wilson lower bound on lift:

```
btc_rel_ret_5m ≥ +3.2%  ∧  cvd_30s < -$5k        → 33% rate, n=48, lo_lift 1.97×
cvd_30s < -$5k          ∧  vwap_300s ≥ 0.12      → 35% rate, n=31, lo_lift 1.91×
cvd_60s < -$8.8k        ∧  vwap_300s ≥ 0.12      → 34% rate, n=32, lo_lift 1.85×
btc_rel_ret_5m ≥ +3.2%  ∧  signals_24h < 9       → 33% rate, n=40, lo_lift 1.82×
btc_rel_ret_5m < +0.8%  ∧  higher_lows_3m=F      → 31% rate, n=42, lo_lift 1.73×
bid_depth_usd ≥ $16k    ∧  higher_lows_3m=F      → 31% rate, n=35, lo_lift 1.68×
avg_trade_size_60s ≥ 209 ∧ utc_hour ≥ 14         → 31% rate, n=32, lo_lift 1.63×
candle_close_str ≥ 0.92 ∧ cvd_30s < -$5k         → 29% rate, n=35, lo_lift 1.48×
```

---

## What I propose next

**Stop changing the live filter.** The data has a coherent, testable
hypothesis — implementing it now without walk-forward verification
would be a repeat of the n=17 trap.

Build `dna_model.py` to fit a regularized logistic regression on the
recent window (n=535, 31 features, n_pos=59 at 10% threshold) with
walk-forward CV. Compare its OOS AUC to the strongest single-pair
conditional. If multivariate doesn't beat the strongest pair, the
edge is in 1-2 specific interactions and we should encode those as
hard rules. If multivariate beats by ≥0.05 AUC OOS, there are
synergies worth a learned scorecard.

Then translate into a candidate `runner_dna_v1` rule set, walk-forward
test it, and run it through the existing 9-gate promotion framework.
Only deploy if it passes.

The hypothesis I'd put forward as the leading runner_dna_v1
candidate (NOT YET DEPLOYED, NOT YET WALK-FORWARD VALIDATED):

```python
def runner_dna_v1_passes(features) -> bool:
    # Macro regime gate (daily)
    if features.get("fear_greed", 0) < 22:
        return False

    # Macro setup gate (per-signal)
    btc_rel = features.get("btc_rel_ret_5m")
    if btc_rel is None or btc_rel < 0.02:
        return False

    # Activity confirmation: not a quiet day (signals_24h proxy for noise)
    if features.get("signals_24h", 0) > 15:
        return False

    # Two-path entry — pick whichever matches:
    cvd_30s     = features.get("cvd_30s", 0)
    higher_lows = features.get("higher_lows_3m")

    # Path A: continuation profile
    if higher_lows is True:
        if features.get("step_2m", 0) >= 0.012 and \
           features.get("candle_close_str_1m", 0) >= 0.70:
            return True

    # Path B: absorption profile
    if higher_lows is False:
        if cvd_30s < -3000 and \
           features.get("ask_depth_usd", 0) >= 5000 and \
           features.get("bid_depth_usd", 0) >= 8000:
            return True

    return False
```

This is a candidate for *evaluation*, not deployment. We don't deploy
until walk-forward says it's positive on data the model hasn't seen.

---

## Update — multivariate walk-forward + stratification (final findings)

After running the multivariate model and stratifying the absorption pattern
by coin and day, the picture has tightened.

### The model says: ship rules, not a learned scorecard

| | OOS AUC |
|---|---:|
| L2 logistic regression (31 features) | **0.548** |
| Single 2-pair `btc_rel_ret_5m − cvd_30s` | **0.586** |

The full multivariate model performs **worse** than the single 2-feature
interaction on walk-forward CV. This is unusual and informative:

1. There is no extra synergy hiding in the rest of the feature set —
   the rest is noise relative to the absorption pair.
2. **Encode the pattern as a hard rule, not a learned scorecard.** A
   learned model on n=535 / n_pos=59 cannot beat a 2-condition rule
   here, and is more brittle.
3. Several existing filter inputs (`step_2m`, `fear_greed` after
   controlling for the pair) are coefficient-zero or even *negative* —
   the current detectors gate on features that don't help once
   you have the absorption pair.

### The absorption pattern is real but partially coin-concentrated

| slice | n hits | ran ≥10% | rate |
|---|---:|---:|---:|
| All recent moments (baseline) | 535 | 59 | 11% |
| Absorption pattern only | 59 | 17 | **29%** |
| Absorption + ret_24h ≥ 20% | 49 | 15 | 31% |
| Absorption + ret_24h ≥ 50% | 28 | 8 | 29% |
| Absorption, excluding KAT and RAVE | 30 | 6 | **20%** |
| Absorption + ret_24h ≥ 20% + ex-KAT/RAVE | 21 | 5 | **24%** |

KAT and RAVE alone produce 11/17 (65%) of the runners hit by the pattern
in this 7-day window. That's because they were the dominant runners in
the period — in any 7-day window, a small number of coins typically
dominate. **The pattern is not coin-specific** (it fires on AXS, TROLL,
RSC, HYPER, ORCA, GODS, SAPIEN, SPK in this window too) but the runner
concentration is real.

After excluding the dominant coins, the absorption pattern still
produces a **20-24% hit rate** vs an 11% baseline — a 1.8× to 2.2×
lift. Smaller than the headline 3× lift but **structurally durable**:
it doesn't depend on a specific coin, it depends on a regime + signal
combination that recurs.

### The pattern matches the user's stated mission

The user's mission, in their own words: *"after a runner starts,
detect the highest confidence moment to trade and safely extract a
small amount of the run."*

The absorption pattern fires on coins with median `ret_24h = 45%` —
i.e., coins that are **already in active runner mode**. It detects
moments where:

1. Macro is risk-on (BTC lifting in last 5m)
2. The coin is being heavily sold in the last 30s (a flush)
3. The flush is being absorbed (price doesn't crater — this is implicit
   in the 5m VWAP staying elevated)

This is exactly the "exhaustion bounce" / "absorption" pattern the user
described. The data confirms it exists at meaningful frequency
(~10/day during high-activity periods) and meaningful hit rate
(20-30% of triggers run ≥10%, vs 11% baseline).

### What should happen next

**Required before any deploy:**

1. Walk-forward simulate the candidate filter with a realistic exit
   policy. AUC is not EV. We need to know: does +29% hit rate × small
   2-3% wins beat -71% miss rate × small -1% losses, AFTER realistic
   slippage and exit-policy execution?

2. Run the filter through the existing 9-gate `research.promote`
   framework. Either it passes or it doesn't.

3. Implement per-coin EV tracking (the suggestion you made earlier and
   I underweighted). The KAT/RAVE concentration shows that PER-COIN
   recent performance is itself a feature. Coins running well now
   continue to do so for a while; that's the law-of-momentum effect.
   Capture this with a simple SQLite per-coin scorecard, not by
   excluding coins.

4. **Don't change the live filter for 30 more days regardless of what
   walk-forward shows on this data.** The recent window is 7 days. Add
   3 more weeks of full-coverage data, re-run all of this analysis,
   and only THEN consider promoting a new champion. The discipline is
   the durable edge, not the rule.

**Files written:**
- `research/runner_dna/labeled.jsonl.gz` — single source of truth
- `research/runner_dna/labeler_report.md`
- `research/runner_dna/univariate_report.md`
- `research/runner_dna/conditional_report.md` (full 14-day)
- `research/runner_dna/conditional_report._recent.md` (recent 7-day, full feature coverage)
- `research/runner_dna/model_report.md`
- `research/runner_dna/REPORT.md` (this file)
