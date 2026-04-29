# METRIC ATLAS — every feature, every horizon

_Source: 4259 unique signal moments, 14 days (2026-04-11 → 2026-04-27)._

_Outcome buckets are based on `fwd_max_max` (max forward gain across all simulator policies):_
- **FLAT**: <1% peak
- **TINY**: 1-5%
- **SMALL**: 5-10%
- **MINOR**: 10-30%
- **TRUE_RUN**: ≥30%

**Population per bucket:**

| bucket | n | pct |
|---|---:|---:|
| FLAT | 1,765 | 41.44% |
| TINY | 1,788 | 41.98% |
| SMALL | 454 | 10.66% |
| MINOR | 229 | 5.38% |
| TRUE_RUN | 23 | 0.54% |

---

## `f_ask_depth_trend`

_Ask depth now / ask depth 60s ago. >1 = sellers stacking, <1 = book thinning._

**Coverage**: 51.5% of signals · **range**: [0.2732, 2.86] · **median**: 1 · **IQR**: [0.823, 1.113] · **mean ± std**: 2.77 ± 30.8

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 854 | 1 | [0.881, 1.106] |
| TINY | 864 | 1 | [0.789, 1.171] |
| SMALL | 277 | 0.977 | [0.719, 1.152] |
| MINOR | 177 | 0.961 | [0.761, 1.004] |
| TRUE_RUN | 22 | 1 | [0.9105, 1.189] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 2194 | 0.477 | [0.452, 0.504] | - |
| p_2pct_5m | 2194 | 0.460 | [0.432, 0.485] | - |
| p_3pct_5m | 2194 | 0.452 | [0.423, 0.479] | - |
| p_5pct_5m | 2194 | 0.446 | [0.415, 0.477] | - |
| p_5pct_max | 2194 | 0.449 | [0.417, 0.480] | - |
| p_10pct_max | 2194 | 0.442 | [0.404, 0.478] | - |
| p_30pct_max | 2194 | 0.543 | [0.439, 0.634] | + |

**Top quartile (high values) WR @ +5%/5min**: 13.5%   ·   **Bottom quartile (low values) WR**: 20.3%

**Best single-threshold rule for +5%/5min**: `f_ask_depth_trend < 0.5192` → 220 signals, 21.4% hit rate (lift 1.29× vs base 16.5%)

**Takeaway**: at the 1-10 min horizon, **low values predict winners** (discrimination = 0.040; CI [0.439, 0.634]).

---

## `f_ask_depth_usd`

_Total USD value resting on top-10 ask levels. Higher = thicker book sell side._

**Coverage**: 46.1% of signals · **range**: [157.6, 3.205e+04] · **median**: 4826 · **IQR**: [1689, 1.205e+04] · **mean ± std**: 1.021e+04 ± 2.573e+04

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 734 | 5236 | [1974, 1.408e+04] |
| TINY | 789 | 4552 | [1663, 1.088e+04] |
| SMALL | 260 | 4646 | [1627, 9081] |
| MINOR | 162 | 4172 | [1188, 1.164e+04] |
| TRUE_RUN | 18 | 5504 | [3255, 1.594e+04] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 1963 | 0.500 | [0.472, 0.527] | + |
| p_2pct_5m | 1963 | 0.479 | [0.453, 0.505] | - |
| p_3pct_5m | 1963 | 0.483 | [0.456, 0.512] | - |
| p_5pct_5m | 1963 | 0.486 | [0.454, 0.523] | - |
| p_5pct_max | 1963 | 0.476 | [0.447, 0.509] | - |
| p_10pct_max | 1963 | 0.487 | [0.445, 0.532] | - |
| p_30pct_max | 1963 | 0.590 | [0.445, 0.710] | + |

**Top quartile (high values) WR @ +5%/5min**: 14.9%   ·   **Bottom quartile (low values) WR**: 17.5%

**Best single-threshold rule for +5%/5min**: `f_ask_depth_usd < 1362` → 393 signals, 19.6% hit rate (lift 1.14× vs base 17.1%)

**Takeaway**: at the 1-10 min horizon, **low values predict winners** (discrimination = 0.021; CI [0.445, 0.710]).

---

## `f_avg_trade_size_60s`

_Average $ size of trades in last 60s. Higher = bigger players in._

**Coverage**: 51.5% of signals · **range**: [18.01, 583.9] · **median**: 142 · **IQR**: [71.7, 253.4] · **mean ± std**: 200.2 ± 204.1

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 854 | 135.2 | [64.98, 242.7] |
| TINY | 864 | 141.7 | [74.42, 236.2] |
| SMALL | 277 | 149.8 | [76.23, 343.8] |
| MINOR | 177 | 147.5 | [82.66, 254] |
| TRUE_RUN | 22 | 97.02 | [28.52, 205.9] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 2194 | 0.554 | [0.529, 0.580] | + |
| p_2pct_5m | 2194 | 0.535 | [0.512, 0.562] | + |
| p_3pct_5m | 2194 | 0.546 | [0.520, 0.574] | + |
| p_5pct_5m | 2194 | 0.549 | [0.518, 0.579] | + |
| p_5pct_max | 2194 | 0.539 | [0.507, 0.567] | + |
| p_10pct_max | 2194 | 0.511 | [0.469, 0.554] | + |
| p_30pct_max | 2194 | 0.377 | [0.255, 0.505] | - |

**Top quartile (high values) WR @ +5%/5min**: 20.4%   ·   **Bottom quartile (low values) WR**: 14.8%

**Best single-threshold rule for +5%/5min**: `f_avg_trade_size_60s ≥ 433.9` → 223 signals, 21.5% hit rate (lift 1.30× vs base 16.5%)

**Takeaway**: at the 1-10 min horizon, **high values predict winners** (discrimination = 0.035; CI [0.255, 0.505]).

---

## `f_bid_depth_usd`

_Total USD value resting on top-10 bid levels._

**Coverage**: 46.1% of signals · **range**: [115.3, 3.958e+04] · **median**: 5689 · **IQR**: [1996, 1.599e+04] · **mean ± std**: 1.326e+04 ± 2.86e+04

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 734 | 5716 | [1693, 1.557e+04] |
| TINY | 789 | 5589 | [2065, 1.613e+04] |
| SMALL | 260 | 6244 | [2509, 1.567e+04] |
| MINOR | 162 | 5353 | [2007, 1.599e+04] |
| TRUE_RUN | 18 | 9863 | [957.7, 2.019e+04] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 1963 | 0.533 | [0.508, 0.558] | + |
| p_2pct_5m | 1963 | 0.501 | [0.477, 0.528] | + |
| p_3pct_5m | 1963 | 0.517 | [0.490, 0.545] | + |
| p_5pct_5m | 1963 | 0.519 | [0.484, 0.554] | + |
| p_5pct_max | 1963 | 0.511 | [0.484, 0.541] | + |
| p_10pct_max | 1963 | 0.506 | [0.465, 0.552] | + |
| p_30pct_max | 1963 | 0.524 | [0.363, 0.672] | + |

**Top quartile (high values) WR @ +5%/5min**: 17.1%   ·   **Bottom quartile (low values) WR**: 15.3%

**Best single-threshold rule for +5%/5min**: `f_bid_depth_usd ≥ 3915` → 1178 signals, 18.3% hit rate (lift 1.07× vs base 17.1%)

**Takeaway**: at the 1-10 min horizon, **high values predict winners** (discrimination = 0.001; CI [0.363, 0.672]).

---

## `f_book_imbalance_10`

_bid_depth_10 / ask_depth_10 ratio. >1 = more buyers below than sellers above._

**Coverage**: 86.4% of signals · **range**: [0.095, 12.81] · **median**: 0.901 · **IQR**: [0.6045, 2.05] · **mean ± std**: 16.93 ± 263.3

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 1458 | 0.951 | [0.553, 2.049] |
| TINY | 1557 | 0.871 | [0.622, 1.988] |
| SMALL | 434 | 0.844 | [0.592, 2.218] |
| MINOR | 211 | 1.203 | [0.757, 2.389] |
| TRUE_RUN | 19 | 0.785 | [0.21, 1.142] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 3679 | 0.511 | [0.495, 0.529] | + |
| p_2pct_5m | 3679 | 0.509 | [0.487, 0.529] | + |
| p_3pct_5m | 3679 | 0.524 | [0.501, 0.547] | + |
| p_5pct_5m | 3679 | 0.514 | [0.491, 0.541] | + |
| p_5pct_max | 3679 | 0.505 | [0.484, 0.529] | + |
| p_10pct_max | 3679 | 0.540 | [0.505, 0.581] | + |
| p_30pct_max | 3679 | 0.409 | [0.283, 0.549] | - |

**Top quartile (high values) WR @ +5%/5min**: 13.7%   ·   **Bottom quartile (low values) WR**: 12.9%

**Best single-threshold rule for +5%/5min**: `f_book_imbalance_10 ≥ 5.423` → 368 signals, 15.5% hit rate (lift 1.22× vs base 12.7%)

**Takeaway**: at the 1-10 min horizon, **high values predict winners** (discrimination = 0.009; CI [0.283, 0.549]).

---

## `f_btc_dom_pct`

_BTC's share of total crypto mcap (%). Higher = BTC outperforming alts._

**Coverage**: 95.9% of signals · **range**: [56.85, 58.17] · **median**: 57.24 · **IQR**: [56.96, 57.37] · **mean ± std**: 57.33 ± 0.5891

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 1662 | 57.23 | [56.98, 57.35] |
| TINY | 1724 | 57.22 | [56.93, 57.36] |
| SMALL | 451 | 57.27 | [57.05, 57.39] |
| MINOR | 225 | 57.29 | [57.13, 58.06] |
| TRUE_RUN | 23 | 57.35 | [57.22, 57.85] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 4085 | 0.563 | [0.545, 0.579] | + |
| p_2pct_5m | 4085 | 0.583 | [0.562, 0.603] | + ★ |
| p_3pct_5m | 4085 | 0.594 | [0.571, 0.616] | + ★ |
| p_5pct_5m | 4085 | 0.624 | [0.599, 0.651] | + ★ |
| p_5pct_max | 4085 | 0.569 | [0.546, 0.594] | + |
| p_10pct_max | 4085 | 0.609 | [0.573, 0.647] | + ★ |
| p_30pct_max | 4085 | 0.659 | [0.541, 0.762] | + |

**Top quartile (high values) WR @ +5%/5min**: 19.8%   ·   **Bottom quartile (low values) WR**: 6.8%

**Best single-threshold rule for +5%/5min**: `f_btc_dom_pct ≥ 57.42` → 858 signals, 21.2% hit rate (lift 1.76× vs base 12.1%)

**Takeaway**: at the 1-10 min horizon, **high values predict winners** (discrimination = 0.083; CI [0.541, 0.762]).

---

## `f_btc_rel_ret_5m`

_Coin's 5min return MINUS BTC's 5min return. Positive = outperforming._

**Coverage**: 51.5% of signals · **range**: [-0.01168, 0.07155] · **median**: 0.01399 · **IQR**: [0.00533, 0.03049] · **mean ± std**: 0.02044 ± 0.03527

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 854 | 0.0109 | [0.00348, 0.0219] |
| TINY | 864 | 0.01435 | [0.005865, 0.02994] |
| SMALL | 277 | 0.01781 | [0.0076, 0.03962] |
| MINOR | 177 | 0.02107 | [0.00707, 0.04069] |
| TRUE_RUN | 22 | 0.04387 | [0.01874, 0.05812] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 2194 | 0.634 | [0.611, 0.657] | + ★ |
| p_2pct_5m | 2194 | 0.634 | [0.609, 0.658] | + ★ |
| p_3pct_5m | 2194 | 0.648 | [0.622, 0.676] | + ★ |
| p_5pct_5m | 2194 | 0.661 | [0.629, 0.695] | + ★ |
| p_5pct_max | 2194 | 0.615 | [0.584, 0.646] | + ★ |
| p_10pct_max | 2194 | 0.617 | [0.578, 0.663] | + ★ |
| p_30pct_max | 2194 | 0.723 | [0.616, 0.842] | + ★ |

**Top quartile (high values) WR @ +5%/5min**: 34.7%   ·   **Bottom quartile (low values) WR**: 7.3%

**Best single-threshold rule for +5%/5min**: `f_btc_rel_ret_5m ≥ 0.04844` → 221 signals, 37.1% hit rate (lift 2.24× vs base 16.5%)

**Takeaway**: at the 1-10 min horizon, **high values predict winners** (discrimination = 0.134; CI [0.616, 0.842]).

---

## `f_candle_close_str_1m`

_(close - low) / (high - low) for the 1m candle. 1.0 = closed at high._

**Coverage**: 51.5% of signals · **range**: [0, 1] · **median**: 0.889 · **IQR**: [0.5832, 1] · **mean ± std**: 0.7412 ± 0.3205

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 854 | 0.893 | [0.56, 1] |
| TINY | 864 | 0.871 | [0.583, 1] |
| SMALL | 277 | 0.905 | [0.669, 1] |
| MINOR | 177 | 0.923 | [0.6, 1] |
| TRUE_RUN | 22 | 0.998 | [0.9168, 1] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 2194 | 0.553 | [0.527, 0.573] | + |
| p_2pct_5m | 2194 | 0.527 | [0.504, 0.548] | + |
| p_3pct_5m | 2194 | 0.544 | [0.519, 0.569] | + |
| p_5pct_5m | 2194 | 0.551 | [0.524, 0.579] | + |
| p_5pct_max | 2194 | 0.523 | [0.492, 0.551] | + |
| p_10pct_max | 2194 | 0.526 | [0.486, 0.566] | + |
| p_30pct_max | 2194 | 0.643 | [0.526, 0.742] | + |

**Top quartile (high values) WR @ +5%/5min**: 17.5%   ·   **Bottom quartile (low values) WR**: 11.3%

**Best single-threshold rule for +5%/5min**: `f_candle_close_str_1m ≥ 0.7982` → 1316 signals, 19.0% hit rate (lift 1.15× vs base 16.5%)

**Takeaway**: at the 1-10 min horizon, **high values predict winners** (discrimination = 0.027; CI [0.526, 0.742]).

---

## `f_cg_trending`

_Boolean: was this coin on the CoinGecko trending list at signal time?_

**Coverage**: 51.5% of signals · **range**: [0, 1] · **median**: 0 · **IQR**: [0, 1] · **mean ± std**: 0.4535 ± 0.4978

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 854 | 0 | [0, 1] |
| TINY | 864 | 0 | [0, 1] |
| SMALL | 277 | 0 | [0, 1] |
| MINOR | 177 | 0 | [0, 1] |
| TRUE_RUN | 22 | 0 | [0, 0] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 2194 | 0.487 | [0.466, 0.510] | - |
| p_2pct_5m | 2194 | 0.483 | [0.462, 0.507] | - |
| p_3pct_5m | 2194 | 0.482 | [0.458, 0.508] | - |
| p_5pct_5m | 2194 | 0.471 | [0.446, 0.500] | - |
| p_5pct_max | 2194 | 0.476 | [0.452, 0.500] | - |
| p_10pct_max | 2194 | 0.447 | [0.414, 0.483] | - |
| p_30pct_max | 2194 | 0.317 | [0.267, 0.386] | - ★ |

**Top quartile (high values) WR @ +5%/5min**: 14.8%   ·   **Bottom quartile (low values) WR**: 18.0%

**Best single-threshold rule for +5%/5min**: `f_cg_trending < 1` → 1199 signals, 18.0% hit rate (lift 1.09× vs base 16.5%)

**Takeaway**: at the 1-10 min horizon, **low values predict winners** (discrimination = 0.017; CI [0.267, 0.386]).

---

## `f_coin_signal_share`

_This coin's signal share = signals_24h / universe_signals_24h._

**Coverage**: 100.0% of signals · **range**: [0.01471, 2.325] · **median**: 0.2903 · **IQR**: [0.07353, 0.913] · **mean ± std**: 0.6271 ± 0.7907

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 1765 | 0.2292 | [0.05882, 0.75] |
| TINY | 1788 | 0.3704 | [0.1071, 1.029] |
| SMALL | 454 | 0.3504 | [0.1157, 1] |
| MINOR | 229 | 0.2143 | [0.07407, 0.6912] |
| TRUE_RUN | 23 | 0.1765 | [0.08583, 0.3929] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 4259 | 0.588 | [0.571, 0.606] | + ★ |
| p_2pct_5m | 4259 | 0.571 | [0.554, 0.587] | + ★ |
| p_3pct_5m | 4259 | 0.541 | [0.521, 0.560] | + |
| p_5pct_5m | 4259 | 0.521 | [0.496, 0.549] | + |
| p_5pct_max | 4259 | 0.514 | [0.493, 0.534] | + |
| p_10pct_max | 4259 | 0.466 | [0.433, 0.501] | - |
| p_30pct_max | 4259 | 0.430 | [0.328, 0.546] | - |

**Top quartile (high values) WR @ +5%/5min**: 12.9%   ·   **Bottom quartile (low values) WR**: 9.8%

**Best single-threshold rule for +5%/5min**: `f_coin_signal_share ≥ 0.7128` → 1278 signals, 12.8% hit rate (lift 1.09× vs base 11.7%)

**Takeaway**: at the 1-10 min horizon, **high values predict winners** (discrimination = 0.071; CI [0.328, 0.546]).

---

## `f_coin_signals_4h`

_Rolling 4h count of signals for THIS coin. Activity proxy._

**Coverage**: 100.0% of signals · **range**: [1, 43] · **median**: 13 · **IQR**: [5, 28] · **mean ± std**: 17.1 ± 14.06

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 1765 | 11 | [3, 25] |
| TINY | 1788 | 15 | [6, 30] |
| SMALL | 454 | 16 | [7, 31] |
| MINOR | 229 | 9 | [4, 23] |
| TRUE_RUN | 23 | 5 | [3, 14.5] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 4259 | 0.606 | [0.588, 0.623] | + ★ |
| p_2pct_5m | 4259 | 0.589 | [0.571, 0.608] | + ★ |
| p_3pct_5m | 4259 | 0.555 | [0.533, 0.578] | + |
| p_5pct_5m | 4259 | 0.531 | [0.505, 0.559] | + |
| p_5pct_max | 4259 | 0.516 | [0.492, 0.538] | + |
| p_10pct_max | 4259 | 0.442 | [0.408, 0.477] | - |
| p_30pct_max | 4259 | 0.355 | [0.260, 0.471] | - |

**Top quartile (high values) WR @ +5%/5min**: 13.2%   ·   **Bottom quartile (low values) WR**: 11.1%

**Best single-threshold rule for +5%/5min**: `f_coin_signals_4h ≥ 32` → 886 signals, 14.2% hit rate (lift 1.21× vs base 11.7%)

**Takeaway**: at the 1-10 min horizon, **high values predict winners** (discrimination = 0.089; CI [0.260, 0.471]).

---

## `f_cvd_30s`

_Cumulative volume delta over 30s (buy_usd - sell_usd). Negative = net selling._

**Coverage**: 96.1% of signals · **range**: [-3.156e+04, 8982] · **median**: -91.41 · **IQR**: [-4408, 791.8] · **mean ± std**: -4409 ± 2.428e+04

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 1665 | -13.86 | [-3669, 900.5] |
| TINY | 1728 | -91.41 | [-4237, 689.9] |
| SMALL | 451 | -882.1 | [-1.118e+04, 595.3] |
| MINOR | 226 | -545 | [-5466, 1165] |
| TRUE_RUN | 23 | -1877 | [-7116, -27.29] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 4093 | 0.449 | [0.432, 0.463] | - |
| p_2pct_5m | 4093 | 0.453 | [0.433, 0.472] | - |
| p_3pct_5m | 4093 | 0.457 | [0.432, 0.479] | - |
| p_5pct_5m | 4093 | 0.430 | [0.400, 0.455] | - |
| p_5pct_max | 4093 | 0.447 | [0.423, 0.471] | - |
| p_10pct_max | 4093 | 0.466 | [0.426, 0.499] | - |
| p_30pct_max | 4093 | 0.364 | [0.276, 0.449] | - ★ |

**Top quartile (high values) WR @ +5%/5min**: 11.3%   ·   **Bottom quartile (low values) WR**: 15.9%

**Best single-threshold rule for +5%/5min**: `f_cvd_30s < -1.797e+04` → 406 signals, 18.5% hit rate (lift 1.53× vs base 12.1%)

**Takeaway**: at the 1-10 min horizon, **low values predict winners** (discrimination = 0.047; CI [0.276, 0.449]).

---

## `f_cvd_60s`

_Same as cvd_30s but over 60s window — slightly longer-term flow._

**Coverage**: 96.1% of signals · **range**: [-4.225e+04, 1.054e+04] · **median**: -468.2 · **IQR**: [-6738, 1154] · **mean ± std**: -5934 ± 2.895e+04

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 1665 | 13.43 | [-5494, 1383] |
| TINY | 1728 | -586 | [-6510, 1177] |
| SMALL | 451 | -2691 | [-1.564e+04, 576.8] |
| MINOR | 226 | -1246 | [-8930, 1148] |
| TRUE_RUN | 23 | -2551 | [-1.241e+04, -127.6] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 4093 | 0.424 | [0.405, 0.440] | - ★ |
| p_2pct_5m | 4093 | 0.425 | [0.405, 0.445] | - ★ |
| p_3pct_5m | 4093 | 0.427 | [0.403, 0.450] | - |
| p_5pct_5m | 4093 | 0.391 | [0.366, 0.418] | - ★ |
| p_5pct_max | 4093 | 0.428 | [0.405, 0.452] | - |
| p_10pct_max | 4093 | 0.454 | [0.418, 0.488] | - |
| p_30pct_max | 4093 | 0.352 | [0.264, 0.428] | - ★ |

**Top quartile (high values) WR @ +5%/5min**: 8.0%   ·   **Bottom quartile (low values) WR**: 17.3%

**Best single-threshold rule for +5%/5min**: `f_cvd_60s < -2.342e+04` → 410 signals, 20.0% hit rate (lift 1.66× vs base 12.1%)

**Takeaway**: at the 1-10 min horizon, **low values predict winners** (discrimination = 0.075; CI [0.264, 0.428]).

---

## `f_fear_greed`

_Daily F&G index (0-100). Higher = greedier sentiment._

**Coverage**: 96.2% of signals · **range**: [12, 46] · **median**: 21 · **IQR**: [12, 23] · **mean ± std**: 20.72 ± 9.982

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 1667 | 21 | [12, 23] |
| TINY | 1729 | 21 | [12, 23] |
| SMALL | 451 | 21 | [12, 23] |
| MINOR | 226 | 23 | [21, 29] |
| TRUE_RUN | 23 | 23 | [23, 28] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 4096 | 0.592 | [0.577, 0.610] | + ★ |
| p_2pct_5m | 4096 | 0.621 | [0.602, 0.641] | + ★ |
| p_3pct_5m | 4096 | 0.631 | [0.610, 0.652] | + ★ |
| p_5pct_5m | 4096 | 0.644 | [0.621, 0.669] | + ★ |
| p_5pct_max | 4096 | 0.600 | [0.580, 0.624] | + ★ |
| p_10pct_max | 4096 | 0.658 | [0.628, 0.687] | + ★ |
| p_30pct_max | 4096 | 0.733 | [0.672, 0.795] | + ★ |

**Top quartile (high values) WR @ +5%/5min**: 18.6%   ·   **Bottom quartile (low values) WR**: 6.7%

**Best single-threshold rule for +5%/5min**: `f_fear_greed ≥ 39` → 438 signals, 19.6% hit rate (lift 1.63× vs base 12.1%)

**Takeaway**: at the 1-10 min horizon, **high values predict winners** (discrimination = 0.121; CI [0.672, 0.795]).

---

## `f_first_signal_today`

_Boolean: is this the FIRST signal for this coin today?_

**Coverage**: 51.5% of signals · **range**: [0, 1] · **median**: 0 · **IQR**: [0, 0] · **mean ± std**: 0.118 ± 0.3227

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 854 | 0 | [0, 0] |
| TINY | 864 | 0 | [0, 0] |
| SMALL | 277 | 0 | [0, 0] |
| MINOR | 177 | 0 | [0, 0] |
| TRUE_RUN | 22 | 0 | [0, 0] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 2194 | 0.495 | [0.481, 0.508] | - |
| p_2pct_5m | 2194 | 0.497 | [0.483, 0.510] | - |
| p_3pct_5m | 2194 | 0.502 | [0.486, 0.517] | + |
| p_5pct_5m | 2194 | 0.513 | [0.495, 0.533] | + |
| p_5pct_max | 2194 | 0.512 | [0.494, 0.528] | + |
| p_10pct_max | 2194 | 0.515 | [0.493, 0.541] | + |
| p_30pct_max | 2194 | 0.532 | [0.464, 0.620] | + |

**Top quartile (high values) WR @ +5%/5min**: 16.5%   ·   **Bottom quartile (low values) WR**: 16.1%

**Best single-threshold rule for +5%/5min**: `f_first_signal_today ≥ 1` → 259 signals, 19.7% hit rate (lift 1.19× vs base 16.5%)

**Takeaway**: at the 1-10 min horizon, **low values predict winners** (discrimination = 0.003; CI [0.464, 0.620]).

---

## `f_higher_lows_3m`

_Boolean: did the coin make higher lows over the last 3 minutes?_

**Coverage**: 51.5% of signals · **range**: [0, 1] · **median**: 1 · **IQR**: [0, 1] · **mean ± std**: 0.5912 ± 0.4916

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 854 | 1 | [0, 1] |
| TINY | 864 | 1 | [0, 1] |
| SMALL | 277 | 1 | [0, 1] |
| MINOR | 177 | 1 | [0, 1] |
| TRUE_RUN | 22 | 1 | [0, 1] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 2194 | 0.542 | [0.521, 0.561] | + |
| p_2pct_5m | 2194 | 0.532 | [0.511, 0.552] | + |
| p_3pct_5m | 2194 | 0.531 | [0.507, 0.555] | + |
| p_5pct_5m | 2194 | 0.524 | [0.495, 0.552] | + |
| p_5pct_max | 2194 | 0.495 | [0.471, 0.521] | - |
| p_10pct_max | 2194 | 0.498 | [0.466, 0.532] | - |
| p_30pct_max | 2194 | 0.546 | [0.457, 0.639] | + |

**Top quartile (high values) WR @ +5%/5min**: 17.7%   ·   **Bottom quartile (low values) WR**: 14.9%

**Best single-threshold rule for +5%/5min**: `f_higher_lows_3m ≥ 1` → 1297 signals, 17.7% hit rate (lift 1.07× vs base 16.5%)

**Takeaway**: at the 1-10 min horizon, **high values predict winners** (discrimination = 0.032; CI [0.457, 0.639]).

---

## `f_large_trade_pct_60s`

_Fraction of last 60s volume from trades ≥ $500. Whale presence._

**Coverage**: 51.5% of signals · **range**: [0, 0.5297] · **median**: 0 · **IQR**: [0, 0] · **mean ± std**: 0.07595 ± 0.18

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 854 | 0 | [0, 0] |
| TINY | 864 | 0 | [0, 0] |
| SMALL | 277 | 0 | [0, 0.154] |
| MINOR | 177 | 0 | [0, 0] |
| TRUE_RUN | 22 | 0 | [0, 0] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 2194 | 0.518 | [0.504, 0.536] | + |
| p_2pct_5m | 2194 | 0.518 | [0.499, 0.538] | + |
| p_3pct_5m | 2194 | 0.524 | [0.504, 0.544] | + |
| p_5pct_5m | 2194 | 0.523 | [0.501, 0.545] | + |
| p_5pct_max | 2194 | 0.533 | [0.513, 0.555] | + |
| p_10pct_max | 2194 | 0.503 | [0.474, 0.531] | + |
| p_30pct_max | 2194 | 0.487 | [0.423, 0.570] | - |

**Top quartile (high values) WR @ +5%/5min**: 16.5%   ·   **Bottom quartile (low values) WR**: 15.6%

**Best single-threshold rule for +5%/5min**: `f_large_trade_pct_60s < 0.335` → 1970 signals, 16.7% hit rate (lift 1.01× vs base 16.5%)

**Takeaway**: at the 1-10 min horizon, **high values predict winners** (discrimination = 0.018; CI [0.423, 0.570]).

---

## `f_market_breadth_5m`

_Count of coins with positive 5m return across universe._

**Coverage**: 51.5% of signals · **range**: [1, 11] · **median**: 4 · **IQR**: [2, 6] · **mean ± std**: 4.68 ± 3.883

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 854 | 4 | [2, 6] |
| TINY | 864 | 4 | [2, 6] |
| SMALL | 277 | 4 | [2, 6] |
| MINOR | 177 | 4 | [2, 7] |
| TRUE_RUN | 22 | 4 | [3.25, 5] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 2194 | 0.470 | [0.444, 0.491] | - |
| p_2pct_5m | 2194 | 0.470 | [0.444, 0.494] | - |
| p_3pct_5m | 2194 | 0.471 | [0.445, 0.499] | - |
| p_5pct_5m | 2194 | 0.501 | [0.469, 0.535] | + |
| p_5pct_max | 2194 | 0.516 | [0.492, 0.544] | + |
| p_10pct_max | 2194 | 0.525 | [0.486, 0.570] | + |
| p_30pct_max | 2194 | 0.540 | [0.455, 0.627] | + |

**Top quartile (high values) WR @ +5%/5min**: 17.2%   ·   **Bottom quartile (low values) WR**: 16.3%

**Best single-threshold rule for +5%/5min**: `f_market_breadth_5m < 1` → 72 signals, 19.4% hit rate (lift 1.18× vs base 16.5%)

**Takeaway**: at the 1-10 min horizon, **low values predict winners** (discrimination = 0.030; CI [0.455, 0.627]).

---

## `f_perp_oi_change_1h`

**Coverage**: 39.2% of signals · **range**: [-0.2215, 0.2165] · **median**: 0 · **IQR**: [-0.01292, 0.0212] · **mean ± std**: 0.01458 ± 0.2628

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 692 | 0 | [-0.01982, 0.01761] |
| TINY | 697 | 0 | [-0.01157, 0.01955] |
| SMALL | 177 | 0.00543 | [-0.005154, 0.04992] |
| MINOR | 98 | 0 | [0, 0.02544] |
| TRUE_RUN | 7 | 0 | [-0.007071, 0.05141] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 1671 | 0.549 | [0.520, 0.576] | + |
| p_2pct_5m | 1671 | 0.535 | [0.507, 0.568] | + |
| p_3pct_5m | 1671 | 0.523 | [0.491, 0.557] | + |
| p_5pct_5m | 1671 | 0.535 | [0.491, 0.581] | + |
| p_5pct_max | 1671 | 0.569 | [0.531, 0.604] | + |
| p_10pct_max | 1671 | 0.572 | [0.518, 0.625] | + |
| p_30pct_max | 1671 | 0.545 | [0.328, 0.799] | + |

**Top quartile (high values) WR @ +5%/5min**: 12.7%   ·   **Bottom quartile (low values) WR**: 10.0%

**Best single-threshold rule for +5%/5min**: `f_perp_oi_change_1h ≥ 0.116` → 169 signals, 17.8% hit rate (lift 1.48× vs base 12.0%)

**Takeaway**: at the 1-10 min horizon, **high values predict winners** (discrimination = 0.035; CI [0.328, 0.799]).

---

## `f_perp_oi_now`

**Coverage**: 41.4% of signals · **range**: [5.103e+05, 4.027e+07] · **median**: 4.829e+06 · **IQR**: [2.626e+06, 1.891e+07] · **mean ± std**: 3.095e+07 ± 2.383e+08

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 733 | 5.125e+06 | [2.658e+06, 1.496e+07] |
| TINY | 728 | 4.119e+06 | [2.56e+06, 1.109e+07] |
| SMALL | 191 | 7.163e+06 | [2.72e+06, 3.135e+07] |
| MINOR | 104 | 4.345e+06 | [2.128e+06, 2.41e+07] |
| TRUE_RUN | 7 | 5.196e+05 | [3.925e+05, 5.177e+06] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 1763 | 0.504 | [0.473, 0.530] | + |
| p_2pct_5m | 1763 | 0.505 | [0.474, 0.533] | + |
| p_3pct_5m | 1763 | 0.508 | [0.471, 0.540] | + |
| p_5pct_5m | 1763 | 0.502 | [0.460, 0.544] | + |
| p_5pct_max | 1763 | 0.538 | [0.505, 0.577] | + |
| p_10pct_max | 1763 | 0.487 | [0.426, 0.546] | - |
| p_30pct_max | 1763 | 0.247 | [0.043, 0.492] | - |

**Top quartile (high values) WR @ +5%/5min**: 12.2%   ·   **Bottom quartile (low values) WR**: 10.4%

**Best single-threshold rule for +5%/5min**: `f_perp_oi_now ≥ 2.72e+06` → 1291 signals, 12.5% hit rate (lift 1.06× vs base 11.9%)

**Takeaway**: at the 1-10 min horizon, **high values predict winners** (discrimination = 0.005; CI [0.043, 0.492]).

---

## `f_perp_vol_now`

**Coverage**: 41.4% of signals · **range**: [1.784e+05, 2.172e+08] · **median**: 1.847e+07 · **IQR**: [2.656e+06, 7.86e+07] · **mean ± std**: 5.894e+07 ± 1.583e+08

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 733 | 1.798e+07 | [1.395e+06, 8.06e+07] |
| TINY | 728 | 1.568e+07 | [3.253e+06, 6.717e+07] |
| SMALL | 191 | 4.22e+07 | [6.137e+06, 8.959e+07] |
| MINOR | 104 | 1.978e+07 | [5.249e+06, 6.663e+07] |
| TRUE_RUN | 7 | 1.401e+06 | [1.614e+05, 1.841e+07] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 1763 | 0.558 | [0.533, 0.585] | + |
| p_2pct_5m | 1763 | 0.558 | [0.532, 0.585] | + |
| p_3pct_5m | 1763 | 0.551 | [0.521, 0.581] | + |
| p_5pct_5m | 1763 | 0.532 | [0.494, 0.573] | + |
| p_5pct_max | 1763 | 0.559 | [0.527, 0.594] | + |
| p_10pct_max | 1763 | 0.495 | [0.453, 0.543] | - |
| p_30pct_max | 1763 | 0.293 | [0.074, 0.556] | - |

**Top quartile (high values) WR @ +5%/5min**: 11.3%   ·   **Bottom quartile (low values) WR**: 7.9%

**Best single-threshold rule for +5%/5min**: `f_perp_vol_now ≥ 1.457e+08` → 179 signals, 16.8% hit rate (lift 1.41× vs base 11.9%)

**Takeaway**: at the 1-10 min horizon, **high values predict winners** (discrimination = 0.058; CI [0.074, 0.556]).

---

## `f_rank_60s`

_This coin's rank by 60s return, across all monitored coins. 1 = top mover._

**Coverage**: 76.5% of signals · **range**: [1, 6] · **median**: 1 · **IQR**: [1, 2] · **mean ± std**: 2.335 ± 4.127

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 1282 | 1 | [1, 2] |
| TINY | 1386 | 1 | [1, 2] |
| SMALL | 375 | 1 | [1, 2] |
| MINOR | 194 | 1 | [1, 2] |
| TRUE_RUN | 21 | 1 | [1, 1] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 3258 | 0.469 | [0.451, 0.486] | - |
| p_2pct_5m | 3258 | 0.454 | [0.436, 0.472] | - |
| p_3pct_5m | 3258 | 0.462 | [0.443, 0.483] | - |
| p_5pct_5m | 3258 | 0.442 | [0.421, 0.467] | - |
| p_5pct_max | 3258 | 0.451 | [0.431, 0.474] | - |
| p_10pct_max | 3258 | 0.443 | [0.412, 0.472] | - |
| p_30pct_max | 3258 | 0.308 | [0.300, 0.317] | - ★ |

**Top quartile (high values) WR @ +5%/5min**: 10.4%   ·   **Bottom quartile (low values) WR**: 16.4%

**Best single-threshold rule for +5%/5min**: `f_rank_60s < 2` → 2013 signals, 16.4% hit rate (lift 1.16× vs base 14.1%)

**Takeaway**: at the 1-10 min horizon, **low values predict winners** (discrimination = 0.046; CI [0.300, 0.317]).

---

## `f_ret_24h`

_24-hour price change (fraction). 0.5 = +50% vs 24h ago._

**Coverage**: 96.1% of signals · **range**: [-0.001388, 2.051] · **median**: 0.3259 · **IQR**: [0.1262, 0.6962] · **mean ± std**: 0.5388 ± 0.6322

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 1665 | 0.2774 | [0.09367, 0.6455] |
| TINY | 1728 | 0.3407 | [0.1388, 0.6839] |
| SMALL | 451 | 0.4388 | [0.2168, 0.8985] |
| MINOR | 226 | 0.3865 | [0.1661, 0.7823] |
| TRUE_RUN | 23 | 0.2668 | [0.1847, 1.531] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 4093 | 0.646 | [0.632, 0.664] | + ★ |
| p_2pct_5m | 4093 | 0.642 | [0.626, 0.659] | + ★ |
| p_3pct_5m | 4093 | 0.631 | [0.612, 0.651] | + ★ |
| p_5pct_5m | 4093 | 0.623 | [0.599, 0.648] | + ★ |
| p_5pct_max | 4093 | 0.584 | [0.560, 0.609] | + ★ |
| p_10pct_max | 4093 | 0.543 | [0.508, 0.583] | + |
| p_30pct_max | 4093 | 0.577 | [0.471, 0.699] | + |

**Top quartile (high values) WR @ +5%/5min**: 17.7%   ·   **Bottom quartile (low values) WR**: 2.7%

**Best single-threshold rule for +5%/5min**: `f_ret_24h ≥ 0.5933` → 1228 signals, 17.1% hit rate (lift 1.42× vs base 12.1%)

**Takeaway**: at the 1-10 min horizon, **high values predict winners** (discrimination = 0.142; CI [0.471, 0.699]).

---

## `f_secs_since_onset`

_Seconds elapsed between move onset and signal. Low = fresh, high = late._

**Coverage**: 51.5% of signals · **range**: [-1, 109.8] · **median**: 6.9 · **IQR**: [0.2, 30.8] · **mean ± std**: 23.5 ± 36.95

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 854 | 7.6 | [0, 33.27] |
| TINY | 864 | 7.55 | [0.6, 34.15] |
| SMALL | 277 | 4.5 | [0, 24.7] |
| MINOR | 177 | 5.6 | [0.5, 27.3] |
| TRUE_RUN | 22 | 7.05 | [1.2, 15.8] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 2194 | 0.536 | [0.512, 0.559] | + |
| p_2pct_5m | 2194 | 0.509 | [0.484, 0.530] | + |
| p_3pct_5m | 2194 | 0.516 | [0.490, 0.541] | + |
| p_5pct_5m | 2194 | 0.502 | [0.474, 0.532] | + |
| p_5pct_max | 2194 | 0.469 | [0.442, 0.497] | - |
| p_10pct_max | 2194 | 0.489 | [0.450, 0.529] | - |
| p_30pct_max | 2194 | 0.484 | [0.391, 0.585] | - |

**Top quartile (high values) WR @ +5%/5min**: 14.2%   ·   **Bottom quartile (low values) WR**: 12.7%

**Best single-threshold rule for +5%/5min**: `f_secs_since_onset ≥ 0` → 1796 signals, 18.4% hit rate (lift 1.11× vs base 16.5%)

**Takeaway**: at the 1-10 min horizon, **high values predict winners** (discrimination = 0.009; CI [0.391, 0.585]).

---

## `f_signals_1h`

_Per-coin signals in last 1h. Same idea, shorter window._

**Coverage**: 96.1% of signals · **range**: [1, 15] · **median**: 5 · **IQR**: [3, 9] · **mean ± std**: 6.269 ± 4.477

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 1665 | 5 | [2, 9] |
| TINY | 1728 | 6 | [3, 9] |
| SMALL | 451 | 6 | [3, 10] |
| MINOR | 226 | 4 | [2, 9] |
| TRUE_RUN | 23 | 4 | [2, 6] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 4093 | 0.601 | [0.587, 0.619] | + ★ |
| p_2pct_5m | 4093 | 0.588 | [0.570, 0.608] | + ★ |
| p_3pct_5m | 4093 | 0.560 | [0.541, 0.580] | + |
| p_5pct_5m | 4093 | 0.525 | [0.499, 0.552] | + |
| p_5pct_max | 4093 | 0.508 | [0.488, 0.532] | + |
| p_10pct_max | 4093 | 0.450 | [0.417, 0.494] | - |
| p_30pct_max | 4093 | 0.391 | [0.288, 0.498] | - |

**Top quartile (high values) WR @ +5%/5min**: 14.0%   ·   **Bottom quartile (low values) WR**: 11.2%

**Best single-threshold rule for +5%/5min**: `f_signals_1h ≥ 10` → 948 signals, 14.8% hit rate (lift 1.22× vs base 12.1%)

**Takeaway**: at the 1-10 min horizon, **high values predict winners** (discrimination = 0.088; CI [0.288, 0.498]).

---

## `f_signals_24h`

_How many signals THIS coin has fired today. High = noise day OR coin is running hard._

**Coverage**: 96.1% of signals · **range**: [1, 143] · **median**: 15 · **IQR**: [4, 47] · **mean ± std**: 35.99 ± 46.83

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 1665 | 12 | [3, 40] |
| TINY | 1728 | 19 | [6, 56] |
| SMALL | 451 | 16 | [6, 54.5] |
| MINOR | 226 | 9 | [4, 32] |
| TRUE_RUN | 23 | 8 | [3, 11.5] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 4093 | 0.573 | [0.558, 0.592] | + ★ |
| p_2pct_5m | 4093 | 0.548 | [0.530, 0.570] | + |
| p_3pct_5m | 4093 | 0.518 | [0.496, 0.541] | + |
| p_5pct_5m | 4093 | 0.488 | [0.464, 0.517] | - |
| p_5pct_max | 4093 | 0.481 | [0.456, 0.504] | - |
| p_10pct_max | 4093 | 0.423 | [0.390, 0.463] | - |
| p_30pct_max | 4093 | 0.361 | [0.267, 0.470] | - |

**Top quartile (high values) WR @ +5%/5min**: 12.0%   ·   **Bottom quartile (low values) WR**: 12.7%

**Best single-threshold rule for +5%/5min**: `f_signals_24h < 2` → 353 signals, 13.6% hit rate (lift 1.13× vs base 12.1%)

**Takeaway**: at the 1-10 min horizon, **high values predict winners** (discrimination = 0.048; CI [0.267, 0.470]).

---

## `f_spread_bps`

_Bid-ask spread at signal, in basis points (1bp = 0.01%)._

**Coverage**: 96.9% of signals · **range**: [1.7, 26.6] · **median**: 10.8 · **IQR**: [6, 19.4] · **mean ± std**: 12.72 ± 8.008

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 1671 | 12.2 | [6.2, 19.8] |
| TINY | 1753 | 11.6 | [6.2, 19.7] |
| SMALL | 453 | 8.5 | [5.3, 17.6] |
| MINOR | 226 | 8.55 | [5.025, 16.18] |
| TRUE_RUN | 23 | 7.9 | [5.65, 10.35] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 4126 | 0.463 | [0.447, 0.481] | - |
| p_2pct_5m | 4126 | 0.424 | [0.406, 0.443] | - ★ |
| p_3pct_5m | 4126 | 0.402 | [0.382, 0.421] | - ★ |
| p_5pct_5m | 4126 | 0.380 | [0.356, 0.405] | - ★ |
| p_5pct_max | 4126 | 0.424 | [0.403, 0.447] | - ★ |
| p_10pct_max | 4126 | 0.408 | [0.372, 0.443] | - ★ |
| p_30pct_max | 4126 | 0.372 | [0.279, 0.466] | - |

**Top quartile (high values) WR @ +5%/5min**: 7.2%   ·   **Bottom quartile (low values) WR**: 17.7%

**Best single-threshold rule for +5%/5min**: `f_spread_bps < 3` → 389 signals, 18.3% hit rate (lift 1.52× vs base 12.0%)

**Takeaway**: at the 1-10 min horizon, **low values predict winners** (discrimination = 0.076; CI [0.279, 0.466]).

---

## `f_spread_bps_at_entry`

_Spread at the actual entry moment (slightly later than sig)._

**Coverage**: 100.0% of signals · **range**: [2.045, 28.45] · **median**: 15.06 · **IQR**: [7.886, 22.01] · **mean ± std**: 15.48 ± 11.2

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 1765 | 14.89 | [7.579, 22.07] |
| TINY | 1788 | 15.61 | [8.598, 22.39] |
| SMALL | 454 | 13.68 | [6.533, 21.43] |
| MINOR | 229 | 13.79 | [7.902, 20.49] |
| TRUE_RUN | 23 | 10.89 | [8.442, 16.6] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 4259 | 0.501 | [0.483, 0.517] | + |
| p_2pct_5m | 4259 | 0.476 | [0.456, 0.495] | - |
| p_3pct_5m | 4259 | 0.456 | [0.436, 0.480] | - |
| p_5pct_5m | 4259 | 0.436 | [0.409, 0.463] | - |
| p_5pct_max | 4259 | 0.458 | [0.434, 0.483] | - |
| p_10pct_max | 4259 | 0.461 | [0.427, 0.496] | - |
| p_30pct_max | 4259 | 0.418 | [0.305, 0.540] | - |

**Top quartile (high values) WR @ +5%/5min**: 8.5%   ·   **Bottom quartile (low values) WR**: 14.0%

**Best single-threshold rule for +5%/5min**: `f_spread_bps_at_entry < 6.387` → 852 signals, 15.1% hit rate (lift 1.29× vs base 11.7%)

**Takeaway**: at the 1-10 min horizon, **low values predict winners** (discrimination = 0.024; CI [0.305, 0.540]).

---

## `f_universe_signals_24h`

_How many DISTINCT coins fired any signal today. Universe-level activity._

**Coverage**: 100.0% of signals · **range**: [28, 68] · **median**: 54 · **IQR**: [39, 68] · **mean ± std**: 51.87 ± 15.66

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 1765 | 48 | [45, 68] |
| TINY | 1788 | 54 | [43.5, 68] |
| SMALL | 454 | 54 | [38, 68] |
| MINOR | 229 | 46 | [31, 54] |
| TRUE_RUN | 23 | 36 | [28, 54] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 4259 | 0.455 | [0.440, 0.472] | - |
| p_2pct_5m | 4259 | 0.437 | [0.419, 0.458] | - |
| p_3pct_5m | 4259 | 0.436 | [0.418, 0.459] | - |
| p_5pct_5m | 4259 | 0.425 | [0.400, 0.450] | - ★ |
| p_5pct_max | 4259 | 0.445 | [0.423, 0.466] | - |
| p_10pct_max | 4259 | 0.389 | [0.357, 0.424] | - ★ |
| p_30pct_max | 4259 | 0.315 | [0.232, 0.401] | - ★ |

**Top quartile (high values) WR @ +5%/5min**: 6.7%   ·   **Bottom quartile (low values) WR**: 15.0%

**Best single-threshold rule for +5%/5min**: `f_universe_signals_24h < 46` → 1145 signals, 15.6% hit rate (lift 1.33× vs base 11.7%)

**Takeaway**: at the 1-10 min horizon, **low values predict winners** (discrimination = 0.063; CI [0.232, 0.401]).

---

## `f_utc_hour`

_UTC hour of day (0-23). Time-of-day pattern._

**Coverage**: 96.1% of signals · **range**: [0, 22] · **median**: 10 · **IQR**: [4, 16] · **mean ± std**: 10.38 ± 7.058

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 1665 | 10 | [4, 17] |
| TINY | 1728 | 10 | [4, 16] |
| SMALL | 451 | 8 | [3, 16] |
| MINOR | 226 | 11 | [4.25, 17] |
| TRUE_RUN | 23 | 8 | [5.5, 14.5] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 4093 | 0.468 | [0.448, 0.485] | - |
| p_2pct_5m | 4093 | 0.475 | [0.456, 0.498] | - |
| p_3pct_5m | 4093 | 0.498 | [0.476, 0.523] | - |
| p_5pct_5m | 4093 | 0.504 | [0.474, 0.531] | + |
| p_5pct_max | 4093 | 0.481 | [0.457, 0.505] | - |
| p_10pct_max | 4093 | 0.510 | [0.477, 0.545] | + |
| p_30pct_max | 4093 | 0.489 | [0.394, 0.595] | - |

**Top quartile (high values) WR @ +5%/5min**: 13.4%   ·   **Bottom quartile (low values) WR**: 12.2%

**Best single-threshold rule for +5%/5min**: `f_utc_hour < 1` → 274 signals, 14.6% hit rate (lift 1.21× vs base 12.1%)

**Takeaway**: at the 1-10 min horizon, **low values predict winners** (discrimination = 0.025; CI [0.394, 0.595]).

---

## `f_vwap_300s`

_5-minute VWAP for this coin._

**Coverage**: 51.5% of signals · **range**: [0.01064, 16.38] · **median**: 0.1101 · **IQR**: [0.03238, 1.458] · **mean ± std**: 2.983 ± 5.785

**How does this metric change across outcomes?**

| outcome | n | median | IQR |
|---|---:|---:|---|
| FLAT | 854 | 0.1118 | [0.03127, 1.531] |
| TINY | 864 | 0.1049 | [0.03247, 1.397] |
| SMALL | 277 | 0.1246 | [0.03905, 1.589] |
| MINOR | 177 | 0.1071 | [0.02305, 1.047] |
| TRUE_RUN | 22 | 0.1698 | [0.08794, 0.2158] |

**Predictive AUC per target** (>0.55 = high values predict winners; <0.45 = low values predict)

| target | n | AUC | 95% CI | direction |
|---|---:|---:|---|:---:|
| p_1pct_5m | 2194 | 0.478 | [0.451, 0.504] | - |
| p_2pct_5m | 2194 | 0.470 | [0.445, 0.495] | - |
| p_3pct_5m | 2194 | 0.480 | [0.453, 0.507] | - |
| p_5pct_5m | 2194 | 0.474 | [0.442, 0.504] | - |
| p_5pct_max | 2194 | 0.512 | [0.484, 0.539] | + |
| p_10pct_max | 2194 | 0.480 | [0.439, 0.520] | - |
| p_30pct_max | 2194 | 0.527 | [0.425, 0.620] | + |

**Top quartile (high values) WR @ +5%/5min**: 13.3%   ·   **Bottom quartile (low values) WR**: 18.8%

**Best single-threshold rule for +5%/5min**: `f_vwap_300s < 0.02469` → 439 signals, 21.0% hit rate (lift 1.27× vs base 16.5%)

**Takeaway**: at the 1-10 min horizon, **low values predict winners** (discrimination = 0.030; CI [0.425, 0.620]).

---

