"""
research/slippage.py — measure realized slippage on live fills.

What it answers
---------------
On the trades the bot has actually placed, how much did the *real* fill price
differ from the price the executor intended to hit, and how does that compare
to the cost model embedded in shadow records?

The cost model used in shadow records is roughly:
    cost_pct ≈ TAKER_FEE × 2 + half_spread   (~40 bps total round-trip)

If realized slippage on the TRAIL_STOP leg alone is materially larger than 40
bps, the in-sample EV claim of +5.25% is overstated by an amount that may
flip the strategy from positive to negative EV out of sample.

What's directly measurable today
--------------------------------
The live trade log records `trigger_px` (the trail-stop level the executor
decided to sell at) and `exit_px` (the price the order actually filled at).
The difference is *exit slippage in the TRAIL_STOP leg*, expressed in bps:

    exit_slip_bps = (trigger_px - exit_px) / trigger_px × 10_000   (positive = lost ground)

For TIME_CAP exits there is no trigger, only a market-on-time-out fill, so
slippage in that leg is unmeasurable from this log alone. Same for ENTRY:
the log records `entry_px` (fill) but not the price the executor intended to
chase. Entry slippage requires either the executor's pre-submit log line or
a join against L2 book snapshots from the recorder. That's noted below.

Outputs
-------
- prints a markdown summary table to stdout
- writes research/slippage_report.json with the per-trade and aggregate
  numbers so downstream tooling can consume them

Usage
-----
    python3 -m research.slippage [path/to/live_trades.jsonl]

Default path: research/phase3_intrabar/artifacts/from_ec2/live_trades.jsonl
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

DEFAULT_LIVE = Path("research/phase3_intrabar/artifacts/from_ec2/live_trades.jsonl")
REPORT_PATH  = Path("research/slippage_report.json")

# Cost model embedded in shadow records — round-trip, in pct (not bps).
# Used as the comparison baseline against which realized slippage is judged.
MODELED_ROUND_TRIP_COST_BPS = 40.0


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open() if line.strip()]


def _entry_price(e: dict) -> float | None:
    return e.get("entry_px") or e.get("price")


def _exit_price(e: dict) -> float | None:
    return e.get("exit_px") or e.get("price")


def _exit_reason(e: dict) -> str | None:
    return e.get("exit_reason") or e.get("reason")


def _net_pnl_pct(x: dict) -> float | None:
    """Extract realized net P&L as a fraction.

    Older events use `net_pct` (fraction); newer events use `gain` (fraction).
    """
    if x.get("net_pct") is not None:
        return x["net_pct"]
    if x.get("gain") is not None:
        return x["gain"]
    return None


def pair_trades(events: list[dict]) -> list[dict]:
    """Pair ENTRY → EXIT events per coin in order of occurrence.

    The log doesn't carry a one-to-one trade_id, but events for a coin are
    ordered ENTRY then EXIT. We FIFO-match within coin.
    """
    by_coin: dict[str, list[dict]] = defaultdict(list)
    for ev in events:
        by_coin[ev.get("coin", "")].append(ev)

    trades: list[dict] = []
    for coin, evs in by_coin.items():
        open_entry: dict | None = None
        for ev in evs:
            kind = ev.get("event")
            if kind == "ENTRY":
                # if a previous entry never exited, drop it (data gap)
                open_entry = ev
            elif kind == "EXIT" and open_entry is not None:
                trades.append({"entry": open_entry, "exit": ev, "coin": coin})
                open_entry = None
    return trades


def trade_slippage(trade: dict) -> dict[str, Any]:
    """Compute per-trade slippage metrics from one ENTRY/EXIT pair."""
    e, x = trade["entry"], trade["exit"]
    entry_px = _entry_price(e)
    exit_px  = _exit_price(x)
    trig_px  = x.get("trigger_px")
    reason   = _exit_reason(x)
    variant  = e.get("variant")

    out: dict[str, Any] = {
        "coin":         trade["coin"],
        "variant":      variant,
        "entry_ts":     e.get("entry_ts") or e.get("ts"),
        "exit_ts":      x.get("exit_ts")  or x.get("ts"),
        "exit_reason":  reason,
        "hold_min":     x.get("hold_min"),
        "entry_px":     entry_px,
        "exit_px":      exit_px,
        "trigger_px":   trig_px,
        "gross_pct":    x.get("gross_pct"),
        "net_pct":      _net_pnl_pct(x),
    }

    # Exit slippage: only meaningful when there's a trigger price (TRAIL_STOP).
    if trig_px and exit_px:
        out["exit_slip_bps"] = (trig_px - exit_px) / trig_px * 10_000.0
    else:
        out["exit_slip_bps"] = None

    # Round-trip realized cost — modeled minus realized P&L tells us the
    # difference between what shadow assumed and what live booked.
    # gross_pct already excludes the cost_pct, net_pct includes it.
    if out["gross_pct"] is not None and out["net_pct"] is not None:
        # cost_pct embedded in shadow/live record (positive number, in pct)
        out["modeled_cost_pct"] = out["gross_pct"] - out["net_pct"]
    else:
        out["modeled_cost_pct"] = None

    return out


def _percentiles(values: list[float], pcts: list[int]) -> dict[str, float]:
    if not values:
        return {f"p{p}": float("nan") for p in pcts}
    s = sorted(values)
    out = {}
    for p in pcts:
        if len(s) == 1:
            out[f"p{p}"] = s[0]
            continue
        k = (len(s) - 1) * (p / 100.0)
        f = math.floor(k); c = math.ceil(k)
        if f == c:
            out[f"p{p}"] = s[int(k)]
        else:
            out[f"p{p}"] = s[f] + (s[c] - s[f]) * (k - f)
    return out


def aggregate(per_trade: list[dict]) -> dict[str, Any]:
    """Aggregate metrics across trades, sliced by exit_reason and variant."""
    agg: dict[str, Any] = {}

    # --- Exit slippage by reason (any exit with a trigger_px is measurable) ---
    by_reason: dict[str, list[float]] = defaultdict(list)
    for t in per_trade:
        if t["exit_slip_bps"] is None:
            continue
        by_reason[t["exit_reason"] or "unknown"].append(t["exit_slip_bps"])

    def _summary(vals: list[float]) -> dict[str, float]:
        return {
            "n":       len(vals),
            "mean":    statistics.mean(vals),
            "median":  statistics.median(vals),
            "stdev":   statistics.pstdev(vals) if len(vals) > 1 else 0.0,
            "min":     min(vals),
            "max":     max(vals),
            **_percentiles(vals, [10, 25, 75, 90]),
        }

    agg["exit_slippage_by_reason_bps"] = {r: _summary(v) for r, v in by_reason.items()}

    # Aggregate across all measurable exits regardless of reason
    all_slip = [s for vs in by_reason.values() for s in vs]
    if all_slip:
        agg["exit_slippage_all_bps"] = _summary(all_slip)

    # --- Realized round-trip cost from gross_pct - net_pct ---
    costs_pct = [t["modeled_cost_pct"] for t in per_trade if t["modeled_cost_pct"] is not None]
    if costs_pct:
        agg["modeled_round_trip_cost_bps"] = {
            "n":      len(costs_pct),
            "mean":   statistics.mean(costs_pct) * 100.0,   # pct → bps
            "median": statistics.median(costs_pct) * 100.0,
        }

    # --- Slice by variant (where present, any measurable exit) ---
    by_variant: dict[str, list[float]] = defaultdict(list)
    for t in per_trade:
        v = t["variant"]
        if v and t["exit_slip_bps"] is not None:
            by_variant[v].append(t["exit_slip_bps"])
    agg["exit_slippage_by_variant"] = {
        v: {"n": len(vals), "mean": statistics.mean(vals), "median": statistics.median(vals)}
        for v, vals in by_variant.items()
    }

    # --- Headline: how much of the +5.25% in-sample EV is eaten if realized
    #     slippage replaces the modeled cost? ---
    #
    # Modeled round-trip in shadow ≈ 40 bps. Realized exit-leg slippage is
    # measurable; entry-leg is not (no intent price logged), so we use the
    # measured exit-leg as a 2× placeholder for the round trip. EV is in bps.
    if all_slip:
        mean_exit = statistics.mean(all_slip)
        # Taker fees: 10 bps × 2 = 20 bps. Plus 2× exit slip as a placeholder
        # for symmetric entry+exit slippage.
        implied_round_trip_bps = 20.0 + 2.0 * max(0.0, mean_exit)
        in_sample_ev_bps = 525.0
        agg["headline"] = {
            "modeled_round_trip_cost_bps":  MODELED_ROUND_TRIP_COST_BPS,
            "mean_exit_slip_bps":           mean_exit,
            "median_exit_slip_bps":         statistics.median(all_slip),
            "implied_true_round_trip_bps":  implied_round_trip_bps,
            "in_sample_ev_bps":             in_sample_ev_bps,
            "ev_overhang_bps":              implied_round_trip_bps - MODELED_ROUND_TRIP_COST_BPS,
            "true_ev_estimate_bps":         in_sample_ev_bps - (implied_round_trip_bps - MODELED_ROUND_TRIP_COST_BPS),
            "note": (
                "implied_true_round_trip = 20 (fees) + 2×mean_exit_slip. "
                "ENTRY-leg slippage is not directly measurable — entry intent "
                "price is not logged. The 2× factor is a placeholder; true "
                "entry slip may be larger or smaller."
            ),
        }

    return agg


def render_markdown(per_trade: list[dict], agg: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Slippage Report")
    lines.append("")
    lines.append(f"Pairs analyzed: {len(per_trade)}")
    lines.append("")

    h = agg.get("headline")
    if h:
        lines.append("## Headline")
        lines.append("")
        lines.append(f"- Modeled round-trip cost: **{h['modeled_round_trip_cost_bps']:.0f} bps**")
        lines.append(f"- Realized exit slippage (mean / median): **{h['mean_exit_slip_bps']:+.1f} / {h['median_exit_slip_bps']:+.1f} bps**")
        lines.append(f"- Implied true round-trip cost (fees + 2×mean exit slip): **{h['implied_true_round_trip_bps']:.0f} bps**")
        lines.append(f"- In-sample EV claim:        **{h['in_sample_ev_bps']:.0f} bps** (+5.25%)")
        lines.append(f"- EV overhang from cost model: **{h['ev_overhang_bps']:+.0f} bps**")
        lines.append(f"- Implied true EV after cost correction: **{h['true_ev_estimate_bps']:+.0f} bps**")
        lines.append("")
        lines.append(f"_{h['note']}_")
        lines.append("")

    by_reason = agg.get("exit_slippage_by_reason_bps", {})
    if by_reason:
        lines.append("## Exit slippage by reason (bps)")
        lines.append("")
        lines.append("| reason | n | mean | median | p10 | p25 | p75 | p90 | min | max |")
        lines.append("|--------|---|------|--------|-----|-----|-----|-----|-----|-----|")
        for r, s in sorted(by_reason.items(), key=lambda kv: -kv[1]["n"]):
            lines.append(
                f"| {r} | {s['n']} | {s['mean']:+.1f} | {s['median']:+.1f} | "
                f"{s['p10']:+.1f} | {s['p25']:+.1f} | {s['p75']:+.1f} | "
                f"{s['p90']:+.1f} | {s['min']:+.1f} | {s['max']:+.1f} |"
            )
        lines.append("")
        lines.append("Positive = price moved against us between trigger and fill.")
        lines.append("")

    bv = agg.get("exit_slippage_by_variant", {})
    if bv:
        lines.append("## By variant")
        lines.append("")
        lines.append("| variant | n | mean bps | median bps |")
        lines.append("|---------|---|----------|------------|")
        for v, s in sorted(bv.items()):
            lines.append(f"| {v} | {s['n']} | {s['mean']:+.1f} | {s['median']:+.1f} |")
        lines.append("")

    # Worst 10 individual slippage events
    worst = sorted(
        (t for t in per_trade if t.get("exit_slip_bps") is not None),
        key=lambda t: -t["exit_slip_bps"],
    )[:10]
    if worst:
        lines.append("## Worst 10 exit slippage events")
        lines.append("")
        lines.append("| coin | exit_reason | trigger_px | exit_px | slip_bps | hold_min | net_pct |")
        lines.append("|------|-------------|-----------:|--------:|---------:|---------:|--------:|")
        for t in worst:
            net = t["net_pct"]
            net_s = f"{net*100:+.2f}%" if net is not None else "—"
            lines.append(
                f"| {t['coin']} | {t['exit_reason']} | "
                f"{t['trigger_px']:.6g} | {t['exit_px']:.6g} | "
                f"{t['exit_slip_bps']:+.1f} | "
                f"{t['hold_min'] if t['hold_min'] is not None else '—'} | {net_s} |"
            )
        lines.append("")

    # P&L impact of slippage (sum of pct lost at exit)
    lost_pct = 0.0
    for t in per_trade:
        s = t.get("exit_slip_bps")
        if s is not None and s > 0:
            lost_pct += s / 10_000.0
    if lost_pct:
        lines.append("## P&L impact")
        lines.append("")
        lines.append(f"Sum of adverse exit slippage across {len(per_trade)} trades: "
                     f"**{lost_pct*100:.2f}%** of position-equivalent.")
        lines.append("")
        lines.append("(This is the cumulative percent lost to fills moving against us, "
                     "summed across exits where slippage was positive. Multiply by avg "
                     "position size to get USD impact.)")
        lines.append("")

    lines.append("## What's still unmeasured")
    lines.append("")
    lines.append("- **Entry slippage**: executor doesn't log the intended entry price; only fill price (`entry_px`).")
    lines.append("- **TIME_CAP exits without trigger_px**: most TIME_CAP exits do have a trigger_px and ARE measured here. The remainder don't and aren't.")
    lines.append("")
    lines.append("To close these gaps:")
    lines.append("")
    lines.append("1. Add `intended_px` to ENTRY events in `live_executor.py` — log the best ask at submit time.")
    lines.append("2. Always populate `trigger_px` on TIME_CAP exits (best bid at the cap moment).")
    lines.append("3. Or: join against L2 snapshots in `cb_recorder` artifacts using `entry_ts` as the key.")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_LIVE
    if not path.exists():
        print(f"ERROR: live trades file not found: {path}", file=sys.stderr)
        return 1

    events    = _load(path)
    trades    = pair_trades(events)
    per_trade = [trade_slippage(t) for t in trades]
    agg       = aggregate(per_trade)

    md = render_markdown(per_trade, agg)
    print(md)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps({
        "source_path":  str(path),
        "n_pairs":      len(per_trade),
        "aggregate":    agg,
        "per_trade":    per_trade,
    }, indent=2, default=str))
    print(f"\nWrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
