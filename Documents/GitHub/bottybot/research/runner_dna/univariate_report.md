# Runner DNA — Univariate Feature Ranking

Source: `research/runner_dna/labeled.jsonl.gz` (4054 signal moments)

**How to read AUC:** 0.50 = no signal. >0.55 means *higher* feature values are associated with eventual runners; <0.45 means lower values are. The strength of discrimination is `|AUC - 0.50|`.

**`auc_ci_lo` is the bootstrap 2.5%ile.** A feature whose CI lower bound is still > 0.55 (or upper bound < 0.45) is robust at the 95% level. CIs that span 0.50 should be treated as 'pretty plausibly noise.'

## Positive class: peak ≥ 10% (n_pos ≈ 239)

| rank | feature | AUC | 95% CI | dir | KS | n | n_pos | pos median | neg median |
|---:|---|---:|---|:---:|---:|---:|---:|---:|---:|
| 1 | `f_fear_greed` | 0.677 | [0.646, 0.708] | + | 0.332 | 3891 | 239 | 23 | 21 |
| 2 | `f_btc_dom_pct` | 0.622 | [0.586, 0.660] | + | 0.179 | 3882 | 238 | 57.29 | 57.22 |
| 3 | `f_spread_bps` | 0.405 | [0.370, 0.443] | - | 0.167 | 3921 | 239 | 8.7 | 12.3 |
| 4 | `f_signals_24h` | 0.423 | [0.387, 0.458] | - | 0.149 | 3888 | 239 | 9 | 16 |
| 5 | `f_rank_60s` | 0.441 | [0.409, 0.472] | - | 0.129 | 3048 | 204 | 1 | 1 |
| 6 | `f_cvd_60s` | 0.448 | [0.409, 0.484] | - | 0.142 | 3888 | 239 | -1419 | -242.8 |
| 7 | `f_signals_1h` | 0.451 | [0.412, 0.491] | - | 0.091 | 3888 | 239 | 4 | 5 |
| 8 | `f_ret_24h` | 0.543 | [0.508, 0.576] | + | 0.107 | 3888 | 239 | 0.3831 | 0.3266 |
| 9 | `f_cvd_30s` | 0.458 | [0.421, 0.496] | - | 0.100 | 3888 | 239 | -581.4 | -75.67 |
| 10 | `f_spread_bps_at_entry` | 0.458 | [0.424, 0.494] | - | 0.097 | 4054 | 242 | 13.49 | 15.44 |
| 11 | `f_book_imbalance_10` | 0.530 | [0.489, 0.569] | + | 0.100 | 3479 | 220 | 1.085 | 0.866 |
| 12 | `f_utc_hour` | 0.509 | [0.478, 0.549] | + | 0.039 | 3888 | 239 | 10 | 10 |
| 13 | `f_btc_ret_1h` | 0.500 | [0.500, 0.500] | + | 0.000 | 3891 | 239 | 0 | 0 |

## Positive class: peak ≥ 30% (n_pos ≈ 23)

| rank | feature | AUC | 95% CI | dir | KS | n | n_pos | pos median | neg median |
|---:|---|---:|---|:---:|---:|---:|---:|---:|---:|
| 1 | `f_fear_greed` | 0.767 | [0.696, 0.824] | + | 0.527 | 3891 | 23 | 23 | 21 |
| 2 | `f_rank_60s` | 0.306 | [0.297, 0.314] | - | 0.388 | 3048 | 21 | 1 | 1 |
| 3 | `f_btc_dom_pct` | 0.685 | [0.571, 0.792] | + | 0.290 | 3882 | 23 | 57.35 | 57.23 |
| 4 | `f_cvd_60s` | 0.346 | [0.269, 0.426] | - | 0.357 | 3888 | 23 | -2551 | -321 |
| 5 | `f_spread_bps` | 0.359 | [0.269, 0.456] | - | 0.304 | 3921 | 23 | 7.9 | 12 |
| 6 | `f_cvd_30s` | 0.363 | [0.273, 0.463] | - | 0.343 | 3888 | 23 | -1877 | -83.98 |
| 7 | `f_signals_24h` | 0.379 | [0.281, 0.482] | - | 0.326 | 3888 | 23 | 8 | 15 |
| 8 | `f_book_imbalance_10` | 0.410 | [0.279, 0.553] | - | 0.254 | 3479 | 19 | 0.785 | 0.882 |
| 9 | `f_spread_bps_at_entry` | 0.411 | [0.291, 0.514] | - | 0.275 | 4054 | 23 | 10.89 | 15.33 |
| 10 | `f_ret_24h` | 0.576 | [0.455, 0.691] | + | 0.277 | 3888 | 23 | 0.2668 | 0.3283 |
| 11 | `f_signals_1h` | 0.424 | [0.324, 0.521] | - | 0.197 | 3888 | 23 | 4 | 5 |
| 12 | `f_utc_hour` | 0.490 | [0.392, 0.599] | - | 0.165 | 3888 | 23 | 8 | 10 |
| 13 | `f_btc_ret_1h` | 0.500 | [0.500, 0.500] | + | 0.000 | 3891 | 23 | 0 | 0 |

## Cross-threshold consistency

A feature ranking high at both ≥10% and ≥30% positive thresholds is more credible than one only present at one level. Below: features ranked by the minimum discriminative power across thresholds (we want both to be high).

| feature | AUC@10% | AUC@30% | min |dir 10|dir 30|
|---|---:|---:|---:|:---:|:---:|
| `f_fear_greed` | 0.677 | 0.767 | 0.177 | + | + |
| `f_btc_dom_pct` | 0.622 | 0.685 | 0.121 | + | + |
| `f_spread_bps` | 0.405 | 0.359 | 0.095 | - | - |
| `f_signals_24h` | 0.423 | 0.379 | 0.077 | - | - |
| `f_rank_60s` | 0.441 | 0.306 | 0.059 | - | - |
| `f_cvd_60s` | 0.448 | 0.346 | 0.052 | - | - |
| `f_signals_1h` | 0.451 | 0.424 | 0.050 | - | - |
| `f_ret_24h` | 0.543 | 0.576 | 0.043 | + | + |
| `f_cvd_30s` | 0.458 | 0.363 | 0.043 | - | - |
| `f_spread_bps_at_entry` | 0.458 | 0.411 | 0.042 | - | - |
| `f_book_imbalance_10` | 0.530 | 0.410 | 0.030 | + | - |
| `f_utc_hour` | 0.509 | 0.490 | 0.009 | + | - |
| `f_btc_ret_1h` | 0.500 | 0.500 | 0.000 | + | + |