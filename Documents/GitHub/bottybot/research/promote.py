"""
research/promote.py — Champion/challenger promotion framework.

This module implements the hard gates that determine whether a challenger
is ready to replace the champion in production.

Design rules:
  - Default action is REJECT. The burden of proof is on the challenger.
  - Every gate must pass — one failure = REJECT (not weighted average).
  - All decisions are fully logged with the specific gate that failed.
  - The promotion decision is advisory: a human must confirm.
  - Never automatically update live_executor.py.

Promotion verdicts:
  PROMOTE  — challenger passes all gates; recommend production promotion.
  MONITOR  — challenger shows promise but lacks statistical evidence; continue accumulating.
  REJECT   — challenger fails one or more hard gates; do not promote.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .config import PROMOTION_GATES, ADDITIONAL_SLIPPAGE

Verdict = Literal["PROMOTE", "MONITOR", "REJECT"]


# ── Gate checks ───────────────────────────────────────────────────────────────

def _gate(
    passed: bool,
    gate_name: str,
    actual: float | int,
    threshold: float | int,
    description: str,
    failures: list,
) -> None:
    """Evaluate one gate; append to failures list if it fails."""
    if not passed:
        failures.append({
            "gate":        gate_name,
            "actual":      actual,
            "threshold":   threshold,
            "description": description,
        })


def run_gates(
    challenger_stats: dict,
    champion_stats:   dict,
    challenger_by_day: dict,
    challenger_by_regime: dict,
    stressed_stats:   dict,
    challenger_taken: list[dict],
    gates: dict | None = None,
) -> dict:
    """Run all promotion gates and return a structured decision.

    Args:
        challenger_stats:     OOS stats dict from evaluate.compute_stats for challenger
        champion_stats:       OOS stats dict for champion (same period)
        challenger_by_day:    per-day stats for challenger
        challenger_by_regime: per-regime stats for challenger
        stressed_stats:       challenger stats under 2× extra slippage
        challenger_taken:     list of trades taken by challenger (for alpha check)
        gates:                override default gates (uses PROMOTION_GATES if None)

    Returns:
        dict with:
            verdict:    "PROMOTE" | "MONITOR" | "REJECT"
            failures:   list of failed gates with details
            summary:    human-readable summary string
            gates_run:  count of gates evaluated
    """
    g = gates or PROMOTION_GATES
    failures: list[dict] = []
    cn = challenger_stats.get("n", 0)
    cc = champion_stats.get("n", 0)

    # Gate 1: minimum OOS trade count
    _gate(
        cn >= g["min_oos_trades"],
        "min_oos_trades",
        cn, g["min_oos_trades"],
        f"Challenger must have at least {g['min_oos_trades']} OOS trades.",
        failures,
    )

    # Gate 2: minimum distinct test days with trades
    days_with_trade = sum(
        1 for d, ds in challenger_by_day.items() if ds.get("n", 0) > 0
    )
    _gate(
        days_with_trade >= g["min_oos_days_with_trade"],
        "min_oos_days_with_trade",
        days_with_trade, g["min_oos_days_with_trade"],
        "Challenger must take trades on at least N distinct OOS test days.",
        failures,
    )

    # Gate 3: challenger OOS EV > floor
    cev = challenger_stats.get("ev_adj", -999.0)
    _gate(
        cev >= g["min_oos_ev_adj"],
        "min_oos_ev_adj",
        cev, g["min_oos_ev_adj"],
        "Challenger OOS adj_EV must exceed the minimum absolute floor.",
        failures,
    )

    # Gate 4: EV CI lower bound > 0
    ev_ci_lo = challenger_stats.get("ev_ci_90_lo", -999.0)
    _gate(
        ev_ci_lo >= g["oos_ev_ci_90_lower"],
        "oos_ev_ci_90_lower",
        ev_ci_lo, g["oos_ev_ci_90_lower"],
        "90% bootstrap CI lower bound on challenger EV must be > 0.",
        failures,
    )

    # Gate 5: challenger beats champion by minimum uplift
    champ_ev = champion_stats.get("ev_adj", 0.0)
    uplift    = cev - champ_ev
    _gate(
        uplift >= g["min_champion_ev_uplift"],
        "min_champion_ev_uplift",
        uplift, g["min_champion_ev_uplift"],
        "Challenger must beat champion OOS EV by the minimum uplift margin.",
        failures,
    )

    # Gate 6: challenger WR does not drop too far below champion
    cwr  = challenger_stats.get("wr", 0.0)
    chwr = champion_stats.get("wr", 0.0)
    wr_drop = chwr - cwr
    _gate(
        wr_drop <= g["max_wr_drop_vs_champion"],
        "max_wr_drop_vs_champion",
        wr_drop, g["max_wr_drop_vs_champion"],
        "Challenger WR cannot drop too far below champion WR.",
        failures,
    )

    # Gate 7: positive EV in at least N distinct regimes
    regimes_positive = sum(
        1 for rs in challenger_by_regime.values() if rs.get("ev_adj", -999) > 0
    )
    _gate(
        regimes_positive >= g["min_regime_positive_ev"],
        "min_regime_positive_ev",
        regimes_positive, g["min_regime_positive_ev"],
        "Challenger must show positive EV in at least N distinct F&G regimes.",
        failures,
    )

    # Gate 8: stressed EV still positive (cost robustness)
    stressed_ev = stressed_stats.get("ev_adj", -999.0)
    _gate(
        stressed_ev > 0,
        "stress_cost_multiplier",
        stressed_ev, 0.0,
        f"Challenger EV must remain positive after {g['stress_cost_multiplier']}× extra costs.",
        failures,
    )

    # Gate 9: top trade does not dominate returns (alpha concentration)
    alpha = challenger_stats.get("top_trade_alpha", 1.0)
    _gate(
        alpha <= g["max_single_trade_alpha"],
        "max_single_trade_alpha",
        alpha, g["max_single_trade_alpha"],
        "Strategy cannot rely on a single outlier trade for most of its return.",
        failures,
    )

    # ── Determine verdict ──────────────────────────────────────────────────────
    n_gates = 9
    n_failed = len(failures)

    if n_failed == 0:
        verdict: Verdict = "PROMOTE"
    elif n_failed <= 2 and cn >= g["min_oos_trades"]:
        # Minor failures + sufficient data → MONITOR (continue accumulating)
        verdict = "MONITOR"
    else:
        verdict = "REJECT"

    # Build summary string
    gate_summary = []
    if failures:
        gate_summary.append(f"  FAILED gates ({n_failed}/{n_gates}):")
        for f in failures:
            gate_summary.append(
                f"    ✗ {f['gate']}: actual={f['actual']:.4g}  "
                f"required={f['threshold']:.4g} — {f['description']}"
            )
    else:
        gate_summary.append(f"  All {n_gates} gates PASSED.")

    summary_parts = [
        f"  Challenger:  n={cn}  WR={cwr:.0%}  EV={cev:+.3%}",
        f"  Champion:    n={cc}  WR={chwr:.0%}  EV={champ_ev:+.3%}",
        f"  EV uplift:   {uplift:+.3%}  Stressed EV: {stressed_ev:+.3%}",
        f"  Regime wins: {regimes_positive}  Days with trades: {days_with_trade}",
        f"  Top-trade alpha: {alpha:.0%}",
        "",
        *gate_summary,
    ]

    return {
        "verdict":    verdict,
        "failures":   failures,
        "n_gates":    n_gates,
        "n_failed":   n_failed,
        "summary":    "\n".join(summary_parts),
        "challenger": {"stats": challenger_stats},
        "champion":   {"stats": champion_stats},
        "uplift":     round(uplift, 6),
    }


# ── Full promotion run ────────────────────────────────────────────────────────

def compare_champion_challenger(
    champion_result: dict,
    challenger_result: dict,
    challenger_id: str,
    champion_id: str = "precision_filter_v1",
    gates: dict | None = None,
) -> dict:
    """Compare champion and challenger on the same OOS window.

    Both results must come from evaluate.walk_forward_oos() with the same
    events list, same variant, and same date range. They must share the same
    OOS test window — otherwise the comparison is not apples-to-apples.

    Returns a decision dict that can be saved to disk as a research artifact.
    """
    cs = challenger_result.get("stats", {})
    ch = champion_result.get("stats", {})
    cbd = challenger_result.get("by_day", {})
    cbr = challenger_result.get("by_regime", {})
    ss  = challenger_result.get("stressed_stats", {})
    taken = challenger_result.get("taken", [])

    gates_result = run_gates(
        challenger_stats=cs,
        champion_stats=ch,
        challenger_by_day=cbd,
        challenger_by_regime=cbr,
        stressed_stats=ss,
        challenger_taken=taken,
        gates=gates,
    )

    now = datetime.now(timezone.utc).isoformat()
    decision_id = hashlib.sha256(
        f"{challenger_id}_{now}".encode()
    ).hexdigest()[:12]

    return {
        "decision_id":    decision_id,
        "timestamp":      now,
        "champion_id":    champion_id,
        "challenger_id":  challenger_id,
        "variant":        challenger_result.get("variant", "?"),
        "verdict":        gates_result["verdict"],
        "gates":          gates_result,
        "oos_days":       sorted(cbd.keys()),
        "n_oos_days":     len(cbd),
    }


def format_promotion_report(decision: dict) -> str:
    """Format a promotion decision as a human-readable report."""
    lines = []
    verdict = decision.get("verdict", "UNKNOWN")
    color_map = {"PROMOTE": "✅", "MONITOR": "⚠️", "REJECT": "❌"}
    icon = color_map.get(verdict, "?")

    lines.append(f"\n{'='*65}")
    lines.append(f"  PROMOTION DECISION  —  {icon}  {verdict}")
    lines.append(f"  ID: {decision.get('decision_id')}  |  {decision.get('timestamp')[:16]}")
    lines.append(f"  Challenger: {decision.get('challenger_id')}")
    lines.append(f"  Champion:   {decision.get('champion_id')}")
    lines.append(f"  Variant:    {decision.get('variant')}")
    lines.append(f"  OOS days:   {decision.get('n_oos_days')} ({', '.join(decision.get('oos_days', [])[:5])}...)")
    lines.append(f"{'='*65}")
    lines.append(decision["gates"]["summary"])

    if verdict == "PROMOTE":
        lines.append("\n  ACTION REQUIRED:")
        lines.append("  1. Human review of decision_id and OOS trade list.")
        lines.append("  2. If approved, update champion_id in research/config.py.")
        lines.append("  3. Update live_executor.py filter logic.")
        lines.append("  4. Restart cb_recorder.service.")
        lines.append("  5. Document the change in research/champions/.")
    elif verdict == "MONITOR":
        lines.append("\n  ACTION: Continue accumulating OOS data.")
        lines.append("  Re-evaluate when more OOS trades are available.")
    else:
        lines.append("\n  ACTION: No production change.")
        lines.append("  Investigate failed gates before next challenger.")

    return "\n".join(lines)


def save_decision(decision: dict, path: Path) -> None:
    """Save a promotion decision to a JSONL file for audit trail."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(decision) + "\n")
