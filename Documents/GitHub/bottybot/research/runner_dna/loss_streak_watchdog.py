"""
research/runner_dna/loss_streak_watchdog.py — auto-swap on consecutive losses.

Purpose
-------
When the user loses faith in the live champion after N losses in a row,
this watchdog automates the swap to a pre-staged backup champion.

Logic
-----
1. Read live_filter_config.json for the current champion + last_promotion_ts.
2. Read live_trades.jsonl. Find all EXIT events where the matched ENTRY
   was placed AFTER last_promotion_ts.
3. Walk those exits in reverse chronological order. Count consecutive
   losses. Stop at first win or end of post-promotion trades.
4. If consecutive losses ≥ LOSS_STREAK_THRESHOLD, atomically rewrite
   live_filter_config.json:
     - champion = configured backup (default: ml_runner_v1)
     - hard_stop_pct = configured stop for the backup
     - prob_threshold (if applicable) = configured
     - last_promotion_ts = now
     - reason = "auto_promotion_loss_streak"
5. Append a record to promotion_log.jsonl.

Run as systemd timer every 5 minutes. Each run is read-mostly except the
rare case it triggers, so very cheap.

Env / config
------------
- LOSS_STREAK_THRESHOLD (default 3)
- BACKUP_CHAMPION (default ml_runner_v1)
- BACKUP_HARD_STOP_PCT (default 0.015)
- LIVE_FILTER_CONFIG, LIVE_TRADES_PATH

Usage
-----
    python3 -m research.runner_dna.loss_streak_watchdog          # run once
    python3 -m research.runner_dna.loss_streak_watchdog --dry-run

Run with --dry-run to test without rewriting config.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

LIVE_CONFIG_PATH    = Path(os.environ.get(
    "LIVE_FILTER_CONFIG",
    "/home/ec2-user/phase3_intrabar/live_filter_config.json",
))
LIVE_TRADES_PATH    = Path(os.environ.get(
    "LIVE_TRADES_PATH",
    "/home/ec2-user/phase3_intrabar/artifacts/live_trades.jsonl",
))
PROMOTION_LOG       = Path(os.environ.get(
    "PROMOTION_LOG",
    "/home/ec2-user/phase3_intrabar/artifacts/promotion_log.jsonl",
))

LOSS_STREAK_THRESHOLD = int(os.environ.get("LOSS_STREAK_THRESHOLD", "3"))
BACKUP_CHAMPION       = os.environ.get("BACKUP_CHAMPION", "ml_runner_v1")
BACKUP_HARD_STOP_PCT  = float(os.environ.get("BACKUP_HARD_STOP_PCT", "0.015"))


def _parse_iso(s: str | None) -> datetime | None:
    if not s: return None
    s = s.strip().rstrip("Z")
    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc) if "+" not in s and "T" in s \
               else datetime.fromisoformat(s)
    except Exception:
        try:
            return datetime.fromisoformat(s.replace("+00:00", "")).replace(tzinfo=timezone.utc)
        except Exception:
            return None


def load_config() -> dict:
    return json.loads(LIVE_CONFIG_PATH.read_text())


def load_post_promotion_exits(promotion_ts: datetime) -> list[dict]:
    """Return EXIT records whose matching ENTRY was placed after promotion_ts.

    The trade log lists ENTRY then EXIT events. We pair them by walking the
    file: the most recent ENTRY for a coin (without an intervening EXIT) is
    the one matched to the next EXIT for that coin. After we find the EXIT,
    we know its ENTRY's timestamp; if ENTRY ts > promotion_ts, the trade is
    "post-promotion."
    """
    if not LIVE_TRADES_PATH.exists():
        return []

    open_entry: dict[str, dict] = {}     # coin → most recent ENTRY rec
    matched: list[tuple[dict, dict]] = []
    with LIVE_TRADES_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            ev = r.get("event")
            coin = r.get("coin")
            if not coin: continue
            if ev == "ENTRY":
                open_entry[coin] = r
            elif ev == "EXIT":
                ent = open_entry.pop(coin, None)
                if ent is not None:
                    matched.append((ent, r))

    out: list[dict] = []
    for ent, ext in matched:
        ent_ts = _parse_iso(ent.get("entry_ts") or ent.get("ts"))
        if ent_ts is None: continue
        if ent_ts <= promotion_ts: continue
        gain = ext.get("gain") if ext.get("gain") is not None else ext.get("net_pct")
        if gain is None: continue
        out.append({
            "coin": ent.get("coin"),
            "entry_ts": ent.get("entry_ts") or ent.get("ts"),
            "exit_ts":  ext.get("exit_ts")  or ext.get("ts"),
            "gain": float(gain),
            "reason": ext.get("exit_reason") or ext.get("reason"),
        })
    out.sort(key=lambda r: r["exit_ts"])
    return out


def consecutive_losses(exits: list[dict]) -> int:
    """Count consecutive losses from the most recent backwards. Stop at first
    win."""
    n = 0
    for r in reversed(exits):
        if r["gain"] < 0:
            n += 1
        else:
            break
    return n


def write_config_atomic(cfg: dict) -> None:
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=str(LIVE_CONFIG_PATH.parent))
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(cfg, indent=2))
    os.replace(tmp, LIVE_CONFIG_PATH)


def log_event(event: dict) -> None:
    PROMOTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with PROMOTION_LOG.open("a") as f:
        f.write(json.dumps(event, default=str) + "\n")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv[1:])

    if not LIVE_CONFIG_PATH.exists():
        print(f"ERR: {LIVE_CONFIG_PATH} not found", file=sys.stderr)
        return 1
    cfg = load_config()
    cur_champion = cfg.get("champion", "?")
    if cur_champion == BACKUP_CHAMPION:
        print(f"current champion is already {BACKUP_CHAMPION}; nothing to do")
        return 0
    promotion_ts = _parse_iso(cfg.get("last_promotion_ts"))
    if promotion_ts is None:
        print("WARN: last_promotion_ts not parseable — using epoch as floor")
        promotion_ts = datetime(1970, 1, 1, tzinfo=timezone.utc)

    exits = load_post_promotion_exits(promotion_ts)
    streak = consecutive_losses(exits)
    print(f"current champion: {cur_champion}")
    print(f"last promotion:   {promotion_ts.isoformat()}")
    print(f"post-promotion exits: {len(exits)}, consecutive loss streak: {streak}")
    for r in exits[-10:]:
        sign = "L" if r["gain"] < 0 else "W"
        print(f"  {r['exit_ts']:24s} {r['coin']:8s} {sign} gain={r['gain']*100:+6.2f}%  {r.get('reason')}")

    if streak < LOSS_STREAK_THRESHOLD:
        print(f"\nstreak {streak} < threshold {LOSS_STREAK_THRESHOLD}; no action")
        return 0

    print(f"\n*** TRIPWIRE FIRED ***  loss streak {streak} ≥ {LOSS_STREAK_THRESHOLD}")
    print(f"would promote: {cur_champion} → {BACKUP_CHAMPION} (hard_stop {BACKUP_HARD_STOP_PCT*100:.1f}%)")

    decision = {
        "action":        "auto_promote_loss_streak" if not args.dry_run else "would_auto_promote_loss_streak",
        "ts_utc":        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "old_champion":  cur_champion,
        "new_champion":  BACKUP_CHAMPION,
        "loss_streak":   streak,
        "threshold":     LOSS_STREAK_THRESHOLD,
        "old_hard_stop": cfg.get("hard_stop_pct"),
        "new_hard_stop": BACKUP_HARD_STOP_PCT,
        "recent_exits":  exits[-LOSS_STREAK_THRESHOLD:],
    }
    if args.dry_run:
        print(json.dumps(decision, indent=2, default=str))
        return 0

    cfg["champion"] = BACKUP_CHAMPION
    cfg["hard_stop_pct"] = BACKUP_HARD_STOP_PCT
    cfg["halt"] = False
    cfg["halt_reason"] = None
    cfg["last_promotion_ts"] = decision["ts_utc"]
    cfg["notes"] = (
        f"Auto-promoted to {BACKUP_CHAMPION} on loss-streak tripwire "
        f"(streak={streak} ≥ {LOSS_STREAK_THRESHOLD}) at {decision['ts_utc']}. "
        f"Backup champion was pre-staged. Hard stop {BACKUP_HARD_STOP_PCT*100:.1f}%."
    )
    write_config_atomic(cfg)
    log_event(decision)
    print("config rewritten; next signal will use the new champion")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
