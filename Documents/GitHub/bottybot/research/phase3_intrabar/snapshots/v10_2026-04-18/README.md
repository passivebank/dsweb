# v10 Algorithm Snapshot — 2026-04-18

## Snapshot contents
- `live_executor.py` — live trade executor with v10 params
- `detector/` — R1–R9 signal detectors
- `multi_runner_v10.py` — offline backtester
- `live_trades_snapshot.jsonl` — all live trades up to snapshot time

## Configuration (frozen)

### Entry gates
- Variant: R5_CONFIRMED_RUN only (other variants dropped through filtering)
- r5m bimodal: 0.5–1% OR 3%+
- dvt bimodal: 1.0–1.5× OR 2.5×+
- r24 not in [1.0, 2.0]
- spread_bps ≤ 10
- cvd_30s ≥ -2000 (skip if net selling > $2000)
- secs_since_onset < 15s (skip late entries)
- fear_greed < 15 AND btc_ret_1h ≤ 0.02 → skip A/B (true panic)

### Position sizing (half-Kelly by tier)
- Tier A (consol+stable): 40%
- Tier B (consol+instit): 35%
- Tier C (surge+stable):  25%
- Tier D (surge+instit):  20%
- EV-scored: positions scale 0.5× to 1.0× of tier based on per-signal EV vs tier baseline

### Exit policy
- 7% trail stop before partial
- 50% partial at +20%
- 15% trail after partial
- 4h hard time cap

### Cooldowns after exit
- TRAIL_STOP_FULL:    90 min
- TRAIL_STOP_PARTIAL: 20 min
- TIME_CAP_LOSS:      60 min
- TIME_CAP_GAIN:      20 min

## Performance

### Backtest baseline (claimed, 74 days pre-v10 period)
- 73% WR, +4.65% adj_EV per trade
- 51 trades total, ~0.69 trades/day

### Actual live performance (Apr 15 – Apr 18, 4 days)
- **157 live trades, 36% WR, -1.18% adj_EV**

### Shadow data performance (Apr 11 – Apr 18, 6.7 days)
- **443 unique signals, 34.3% WR, -1.237% avg net per trade, -548% total**
- Matches live — meaning the backtest baseline was a different regime

## Files
- `/home/ec2-user/phase3_intrabar/snapshots/v10_2026-04-18/`

## Why snapshotted
Baseline for a search for a more profitable algorithm against the full
shadow dataset. Goal: 5% average daily PnL if achievable by the data.
