"""
research/weekly.py — Weekly champion/challenger research loop.

Runs Sunday 8:30 UTC via cron. Jobs:
  1. Load all post-deploy shadow events.
  2. Evaluate champion (precision_filter_v1) on full window.
  3. Evaluate meta-model challenger via true expanding-window OOS.
  4. Evaluate combined (champion AND meta-model) via expanding-window OOS.
  5. Run promotion gates: challenger vs. champion.
  6. Save decision artifacts + print human-readable report.

This script does NOT modify live_executor.py or any production file.
Promotions require human confirmation.

Usage:
  python3 -m research.weekly              # full run
  python3 -m research.weekly --dry-run    # load + eval but don't save artifacts
  python3 -m research.weekly --variant=R7_STAIRCASE
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import (
    LIVE_VARIANTS,
    SHADOW_FILE,
    EXPERIMENTS,
    CHAMPIONS_DIR,
    PRECISION_FILTER_DEPLOY_TS_NS,
    champion_passes,
)
from .evaluate import load_events, walk_forward_oos, compute_stats, format_report
from .meta_model import meta_model_factory, champion_and_meta_factory
from .promote import compare_champion_challenger, format_promotion_report, save_decision

WEEKLY_LOG = Path(__file__).parent.parent / "research" / "weekly_log.jsonl"
if not WEEKLY_LOG.parent.exists():
    WEEKLY_LOG = EXPERIMENTS.parent / "weekly_log.jsonl"


def _champion_factory(variant: str):
    """Factory that always applies the frozen champion filter — no training."""
    def factory(train_events):
        def passes(features, v):
            return champion_passes(features, v)
        return passes
    return factory


def run_variant(
    variant: str,
    events: list[dict],
    dry_run: bool = False,
) -> dict:
    """Run full champion vs. challenger evaluation for one variant.

    Returns a result dict with champion stats, challenger stats, and promotion decision.
    """
    var_events = [e for e in events if e["variant"] == variant]
    print(f"\n  Variant: {variant}  ({len(var_events)} events total)")

    if len(var_events) < 30:
        print(f"  ⚠ Too few events ({len(var_events)}) for meaningful OOS. Skipping.")
        return {"variant": variant, "skipped": True, "reason": "insufficient_events"}

    # ── Champion baseline ──────────────────────────────────────────────────────
    print("  [1/3] Evaluating champion (precision_filter_v1)...")
    champ_result = walk_forward_oos(
        events=var_events,
        strategy_factory=_champion_factory(variant),
        variant=variant,
        min_train_days=3,
        min_train_events=10,
        fit_each_day=False,
    )
    champ_stats = champ_result.get("stats", {})
    print(f"        n={champ_stats.get('n', 0)}  "
          f"WR={champ_stats.get('wr', 0):.0%}  "
          f"EV={champ_stats.get('ev_adj', 0):+.3%}")

    # ── Meta-model challenger ──────────────────────────────────────────────────
    print("  [2/3] Evaluating meta-model challenger (expanding-window OOS)...")
    try:
        meta_result = walk_forward_oos(
            events=var_events,
            strategy_factory=meta_model_factory(variant, threshold=0.55),
            variant=variant,
            min_train_days=5,
            min_train_events=30,
            fit_each_day=True,
        )
        meta_stats = meta_result.get("stats", {})
        print(f"        n={meta_stats.get('n', 0)}  "
              f"WR={meta_stats.get('wr', 0):.0%}  "
              f"EV={meta_stats.get('ev_adj', 0):+.3%}  "
              f"CI=[{meta_stats.get('ev_ci_90_lo', 0):+.3%},"
              f"{meta_stats.get('ev_ci_90_hi', 0):+.3%}]")
    except Exception as e:
        print(f"        Meta-model failed: {e}")
        meta_result = {"stats": {}, "variant": variant, "error": str(e)}
        meta_stats = {}

    # ── Combined challenger (champion AND meta-model) ──────────────────────────
    print("  [3/3] Evaluating combined filter (champion AND meta-model)...")
    try:
        combined_result = walk_forward_oos(
            events=var_events,
            strategy_factory=champion_and_meta_factory(variant, threshold=0.55),
            variant=variant,
            min_train_days=5,
            min_train_events=30,
            fit_each_day=True,
        )
        combined_stats = combined_result.get("stats", {})
        print(f"        n={combined_stats.get('n', 0)}  "
              f"WR={combined_stats.get('wr', 0):.0%}  "
              f"EV={combined_stats.get('ev_adj', 0):+.3%}  "
              f"CI=[{combined_stats.get('ev_ci_90_lo', 0):+.3%},"
              f"{combined_stats.get('ev_ci_90_hi', 0):+.3%}]")
    except Exception as e:
        print(f"        Combined filter failed: {e}")
        combined_result = {"stats": {}, "variant": variant, "error": str(e)}
        combined_stats = {}

    # ── Promotion decision ─────────────────────────────────────────────────────
    results = {}
    for chal_name, chal_result in [
        ("meta_model_v1", meta_result),
        ("combined_v1", combined_result),
    ]:
        if not chal_result.get("stats"):
            continue
        try:
            decision = compare_champion_challenger(
                champion_result=champ_result,
                challenger_result=chal_result,
                challenger_id=f"{chal_name}_{variant}",
            )
            results[chal_name] = decision
            print(f"\n  {format_promotion_report(decision)}")

            if not dry_run:
                EXPERIMENTS.mkdir(parents=True, exist_ok=True)
                artifact_path = EXPERIMENTS / f"{decision['decision_id']}.json"
                artifact_path.write_text(json.dumps(decision, indent=2))
                print(f"\n  Saved: {artifact_path}")

                decision_log = EXPERIMENTS / "decisions.jsonl"
                save_decision(decision, decision_log)
        except Exception as e:
            print(f"  Promotion gate error for {chal_name}: {e}")

    return {
        "variant":    variant,
        "champion":   {"stats": champ_stats},
        "meta_model": {"stats": meta_stats},
        "combined":   {"stats": combined_stats},
        "decisions":  results,
        "n_events":   len(var_events),
    }


def run_weekly(
    variants: list[str] | None = None,
    dry_run: bool = False,
    write_log: bool = True,
) -> dict:
    """Run the weekly research loop for all (or specified) variants."""
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M UTC")

    print(f"\n{'='*65}")
    print(f"  WEEKLY RESEARCH RUN  —  {now_str}")
    if dry_run:
        print("  [DRY RUN — no artifacts will be saved]")
    print(f"{'='*65}")

    # Load post-deploy events only
    print(f"\n  Loading shadow events (post-deploy)...")
    try:
        events = load_events(
            shadow_file=SHADOW_FILE,
            variants=list(LIVE_VARIANTS.keys()),
            delay_target_ms=250,
            since_ts_ns=PRECISION_FILTER_DEPLOY_TS_NS,
        )
        by_variant = {}
        for v in LIVE_VARIANTS:
            by_variant[v] = sum(1 for e in events if e["variant"] == v)
        print(f"  Loaded {len(events)} events total: "
              + "  ".join(f"{v}={n}" for v, n in by_variant.items()))
    except FileNotFoundError:
        print(f"  ERROR: {SHADOW_FILE} not found. Run on EC2.")
        return {"error": "shadow_file_not_found"}
    except Exception as e:
        print(f"  ERROR loading events: {e}")
        return {"error": str(e)}

    target_variants = variants or list(LIVE_VARIANTS.keys())
    results = {}

    for variant in target_variants:
        result = run_variant(variant, events, dry_run=dry_run)
        results[variant] = result

    # ── Weekly summary ─────────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print("  WEEKLY SUMMARY")
    print(f"{'='*65}")

    any_promote = False
    for variant, r in results.items():
        if r.get("skipped"):
            print(f"  {variant}: SKIPPED — {r.get('reason')}")
            continue
        for chal_name, decision in r.get("decisions", {}).items():
            verdict = decision.get("verdict", "?")
            icon = {"PROMOTE": "✅", "MONITOR": "⚠️", "REJECT": "❌"}.get(verdict, "?")
            print(f"  {variant}/{chal_name}: {icon} {verdict}")
            if verdict == "PROMOTE":
                any_promote = True

    if any_promote:
        print("\n  ACTION REQUIRED: One or more challengers recommend PROMOTE.")
        print("  Review artifacts in research/experiments/ before making any changes.")
    else:
        print("\n  No challengers ready for promotion this week.")

    output = {
        "ts":      now_str,
        "results": results,
    }

    if write_log and not dry_run:
        try:
            log_path = EXPERIMENTS.parent / "weekly_log.jsonl"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a") as f:
                summary = {
                    "ts": now_str,
                    "variants": {
                        v: {
                            "n_events": r.get("n_events", 0),
                            "champion_n": r.get("champion", {}).get("stats", {}).get("n", 0),
                            "meta_model_n": r.get("meta_model", {}).get("stats", {}).get("n", 0),
                            "decisions": {
                                k: d.get("verdict")
                                for k, d in r.get("decisions", {}).items()
                            },
                        }
                        for v, r in results.items()
                        if not r.get("skipped")
                    },
                }
                f.write(json.dumps(summary) + "\n")
        except Exception as e:
            print(f"  Warning: could not write weekly log: {e}")

    return output


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    variant_arg = next((a for a in sys.argv if a.startswith("--variant=")), None)
    variants = [variant_arg.split("=", 1)[1]] if variant_arg else None
    run_weekly(variants=variants, dry_run=dry_run)
