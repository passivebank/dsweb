# v3 Robust (Overfit-Resistant) Training Report
Train: 3942 rows | Test: 317 rows | Held out from 2026-04-25

## p_2pct_5m (fwd_max_5m ≥ 2%) — n_pos=1025

| model | train AUC | CV AUC | test AUC | gap (train-CV) |
|---|---:|---:|---:|---:|
| lgbm | 0.8367 | 0.6216 | 0.5867 | +0.2151 ⚠️ |
| xgb | 0.8313 | 0.6215 | 0.6178 | +0.2098 ⚠️ |
| logreg | 0.6681 | 0.4824 | 0.5922 | +0.1857 ⚠️ |

**No gap-acceptable model. Falling back to highest CV: `lgbm`** ⚠️ overfit risk

## p_3pct_5m (fwd_max_5m ≥ 3%) — n_pos=720

| model | train AUC | CV AUC | test AUC | gap (train-CV) |
|---|---:|---:|---:|---:|
| lgbm | 0.8698 | 0.6137 | 0.6285 | +0.2560 ⚠️ |
| xgb | 0.8700 | 0.6087 | 0.6379 | +0.2613 ⚠️ |
| logreg | 0.6641 | 0.4796 | 0.5740 | +0.1844 ⚠️ |

**No gap-acceptable model. Falling back to highest CV: `lgbm`** ⚠️ overfit risk

## p_5pct_5m (fwd_max_5m ≥ 5%) — n_pos=434

| model | train AUC | CV AUC | test AUC | gap (train-CV) |
|---|---:|---:|---:|---:|
| lgbm | 0.9073 | 0.6043 | 0.6935 | +0.3030 ⚠️ |
| xgb | 0.9062 | 0.5852 | 0.7308 | +0.3210 ⚠️ |
| logreg | 0.6896 | 0.4624 | 0.6041 | +0.2272 ⚠️ |

**No gap-acceptable model. Falling back to highest CV: `lgbm`** ⚠️ overfit risk


## Summary

| target | model | train | CV | test | gap |
|---|---|---:|---:|---:|---:|
| p_2pct_5m | lgbm | 0.8367 | 0.6216 | 0.5867 | +0.2151 |
| p_3pct_5m | lgbm | 0.8698 | 0.6137 | 0.6285 | +0.2560 |
| p_5pct_5m | lgbm | 0.9073 | 0.6043 | 0.6935 | +0.3030 |
