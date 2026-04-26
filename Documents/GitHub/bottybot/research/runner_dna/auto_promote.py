"""
research/runner_dna/auto_promote.py — auto-promote a challenger to live champion
when promotion gates pass.

Reads challenger_scores.json (produced by score_challengers.py) and decides
whether to swap the live champion. Designed to be conservative: a
challenger must clear several gates simultaneously to be promoted.

Gates (ALL must pass):
  - challenger has at least MIN_TRADES executed in the scoring window
  - challenger spans at least MIN_DAYS distinct trading days
  - challenger CI lower bound on mean_net is > 0
  - challenger mean_net beats current champion by MIN_UPLIFT_PCT
  - challenger total_return beats current champion (compounded)
  - challenger max_drawdown is not catastrophically worse (≤ 2× champion DD)
  - cooling-off: no promotion if a promotion fired in the last MIN_PROMOTION_INTERVAL_S

Also tracks the bankroll_peak in the live config — written from the
recorder/dashboard balance reading.

Run on schedule (every 4 hours via systemd timer). Alongside the recorder.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Promotion gates ────────────────────────────────────────────────────────
MIN_TRADES                 = 15
MIN_DAYS                   = 3
MIN_UPLIFT_PCT             = 0.002    # +0.2% mean_net uplift over champion
MAX_DD_RATIO               = 2.0      # challenger DD must be ≤ 2× champion DD
MIN_PROMOTION_INTERVAL_S   = 24 * 3600  # at least 24h between promotions

SCORES_PATH = Path(os.environ.get(
    "CHALLENGER_SCORES_PATH",
    "/home/ec2-user/phase3_intrabar/artifacts/challenger_scores.json",
))
LIVE_CONFIG_PATH = Path(os.environ.get(
    "LIVE_FILTER_CONFIG",
    "/home/ec2-user/phase3_intrabar/live_filter_config.json",
))
PROMOTION_LOG = LIVE_CONFIG_PATH.parent / "artifacts" / "promotion_log.jsonl"


def load_scores() -> dict | None:
    if not SCORES_PATH.exists():
        return None
    try:
        return json.loads(SCORES_PATH.read_text())
    except Exception:
        return None


def load_config() -> dict:
    fallback = {
        "champion": "runner_dna_v1",
        "halt": False,
        "max_position_pct": 0.10,
        "bankroll_peak_usd": 0.0,
        "bankroll_drawdown_halt": 0.10,
    }
    if LIVE_CONFIG_PATH.exists():
        try:
            return {**fallback, **json.loads(LIVE_CONFIG_PATH.read_text())}
        except Exception:
            pass
    return fallback


def write_config(cfg: dict) -> None:
    LIVE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = LIVE_CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    os.replace(tmp, LIVE_CONFIG_PATH)


def log_event(event: dict) -> None:
    PROMOTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with PROMOTION_LOG.open("a") as f:
        f.write(json.dumps(event, default=str) + "\n")


def maybe_promote(scores: dict, cfg: dict, dry_run: bool = False) -> dict:
    """Decide whether to promote a challenger. Returns a decision dict."""
    champion = cfg.get("champion")
    score_map = scores.get("scores", {})
    champ_score = score_map.get(champion)
    if not champ_score or champ_score.get("n_trades", 0) == 0:
        return {"action": "no_champion_data", "champion": champion}

    # Cooling-off
    last_ts = cfg.get("last_promotion_ts")
    now = datetime.now(timezone.utc)
    if last_ts:
        try:
            last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            elapsed = (now - last_dt).total_seconds()
            if elapsed < MIN_PROMOTION_INTERVAL_S:
                return {
                    "action": "cooling_off",
                    "elapsed_s": elapsed,
                    "min_interval_s": MIN_PROMOTION_INTERVAL_S,
                }
        except Exception:
            pass

    # Score every challenger and pick the best one that passes ALL gates
    candidates: list[dict] = []
    for name, s in score_map.items():
        if name == champion:
            continue
        n = s.get("n_trades", 0)
        if n < MIN_TRADES:
            continue
        if s.get("n_days", 0) < MIN_DAYS:
            continue
        if (s.get("mean_net_ci_lo") or -1) <= 0:
            continue
        uplift = s["mean_net_pct"] - champ_score["mean_net_pct"]
        if uplift < MIN_UPLIFT_PCT:
            continue
        if s["total_return_pct"] <= champ_score["total_return_pct"]:
            continue
        champ_dd = max(champ_score.get("max_drawdown_pct", 0.01), 0.01)
        if s.get("max_drawdown_pct", 0.0) > MAX_DD_RATIO * champ_dd:
            continue
        candidates.append({"name": name, "score": s, "uplift": uplift})

    if not candidates:
        return {"action": "no_qualifying_challenger", "champion": champion,
                "champ_score": champ_score}

    # Pick the candidate with the largest uplift
    best = max(candidates, key=lambda c: c["uplift"])
    new_champion = best["name"]

    decision = {
        "action":       "promote" if not dry_run else "would_promote",
        "ts_utc":       now.isoformat(timespec="seconds"),
        "old_champion": champion,
        "new_champion": new_champion,
        "uplift_pct":   best["uplift"],
        "old_score":    champ_score,
        "new_score":    best["score"],
    }

    if not dry_run:
        cfg["champion"] = new_champion
        cfg["last_promotion_ts"] = decision["ts_utc"]
        cfg["notes"] = (
            f"Auto-promoted from {champion} → {new_champion} "
            f"by auto_promote.py at {decision['ts_utc']} "
            f"(uplift {best['uplift']*100:+.2f}%)"
        )
        write_config(cfg)
        log_event(decision)

    return decision


def update_bankroll_peak(cfg: dict, current_bankroll_usd: float | None) -> dict:
    """If current bankroll exceeds peak, raise the peak. Caller should pass
    the live USD balance + position value. None means we don't know — leave
    peak as-is."""
    if current_bankroll_usd is None or current_bankroll_usd <= 0:
        return cfg
    peak = float(cfg.get("bankroll_peak_usd") or 0.0)
    if current_bankroll_usd > peak:
        cfg["bankroll_peak_usd"] = round(current_bankroll_usd, 2)
        cfg["peak_set_ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        write_config(cfg)
        log_event({"action": "peak_updated",
                   "ts_utc": cfg["peak_set_ts"],
                   "old_peak": peak,
                   "new_peak": cfg["bankroll_peak_usd"]})
    return cfg


def fetch_current_bankroll() -> float | None:
    """Best-effort bankroll fetch via Coinbase. Returns None on failure."""
    try:
        from dotenv import dotenv_values
        from coinbase.rest import RESTClient
        cfg = dotenv_values("/home/ec2-user/nkn_bot/.env")
        client = RESTClient(api_key=cfg["CB_API_KEY"], api_secret=cfg["CB_API_SECRET"])
        cash = 0.0
        cursor = None
        while True:
            kw = {"limit": 250}
            if cursor:
                kw["cursor"] = cursor
            r = client.get_accounts(**kw)
            for a in r.accounts:
                cur = getattr(a, "currency", "")
                ab  = a.available_balance
                bal = float(ab["value"] if isinstance(ab, dict) else ab.value)
                hold = a.hold
                hbal = float(hold["value"] if isinstance(hold, dict) else hold.value)
                # USD only — we don't price every coin here. Imperfect but
                # safe (under-counts position value, never over-counts).
                if cur in ("USD", "USDC", "USDT"):
                    cash += bal + hbal
            if not getattr(r, "has_next", False):
                break
            cursor = getattr(r, "cursor", None)
            if not cursor:
                break
        return cash
    except Exception as e:
        print(f"WARN: bankroll fetch failed: {e}", file=sys.stderr)
        return None


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="don't write config, just report")
    p.add_argument("--no-bankroll-fetch", action="store_true",
                   help="skip the Coinbase bankroll API call")
    args = p.parse_args(argv[1:])

    cfg = load_config()
    print(f"current champion: {cfg.get('champion')}")
    print(f"halt: {cfg.get('halt')}")
    print(f"bankroll_peak_usd: ${cfg.get('bankroll_peak_usd')}")

    # Update bankroll peak (best-effort)
    if not args.no_bankroll_fetch:
        bal = fetch_current_bankroll()
        if bal is not None:
            print(f"current USD cash: ${bal:.2f}")
            cfg = update_bankroll_peak(cfg, bal)

    scores = load_scores()
    if not scores:
        print(f"ERR: no scores at {SCORES_PATH} — run score_challengers.py first")
        return 1

    print(f"\nscored at: {scores.get('scored_at_utc')} window_days={scores.get('window_days')}")
    decision = maybe_promote(scores, cfg, dry_run=args.dry_run)
    print(f"\nDECISION: {json.dumps(decision, indent=2, default=str)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
