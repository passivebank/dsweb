"""
research/runner_research/sweep_edges.py — exhaustive edge search.

For every (feature × forward_horizon × capture_target) combination, compute:
  - AUC with bootstrap 95% CI
  - Mean conditional return for the top tercile of the feature
  - Win rate when the feature exceeds threshold
  - Sample size

Outputs:
  research/runner_research/edges_ranking.csv
  research/runner_research/edges_top.md   (top features per target)

Targets to test:
  small_target  : P(fwd_max ≥ 1%)   in 1m / 5m / 10m windows
  medium_target : P(fwd_max ≥ 2%)   in 5m / 10m windows
  large_target  : P(fwd_max ≥ 5%)   in 10m+ windows
  ev_target     : net P&L of holding to natural exit (continuous)

Each feature is tested:
  - Raw: AUC of feature value → label
  - Quartile-bucketed: WR/EV per quartile
  - Inverted (low values predict): also reported for CIs that go below 0.5
"""
from __future__ import annotations

import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

LABELED  = Path("/tmp/runner_research/labeled.jsonl.gz")
OUT_CSV  = Path("research/runner_research/edges_ranking.csv")
OUT_MD   = Path("research/runner_research/edges_top.md")

# Held-out test window — last 3 days
HELD_OUT_FROM = "2026-04-25"

TARGETS = [
    # (name, label_fn, horizon_col, threshold)
    ("p_gain_1pct_5m",  "fwd_max_5m",  0.01),
    ("p_gain_2pct_5m",  "fwd_max_5m",  0.02),
    ("p_gain_3pct_5m",  "fwd_max_5m",  0.03),
    ("p_gain_5pct_5m",  "fwd_max_5m",  0.05),
    ("p_gain_2pct_max", "fwd_max_max", 0.02),
    ("p_gain_5pct_max", "fwd_max_max", 0.05),
    ("p_gain_10pct",    "fwd_max_max", 0.10),
    ("p_gain_30pct",    "fwd_max_max", 0.30),
]


def coerce(v):
    if v is None: return None
    if isinstance(v, bool): return 1.0 if v else 0.0
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f): return None
        return f
    except (TypeError, ValueError): return None


def load_train_only() -> list[dict]:
    rows = []
    with gzip.open(LABELED, "rt") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            r = json.loads(line)
            if r["sig_date"] >= HELD_OUT_FROM:
                continue   # reserve for final test
            rows.append(r)
    return rows


def auc(values: np.ndarray, labels: np.ndarray) -> float:
    n_pos = int(labels.sum()); n_neg = int((1 - labels).sum())
    if n_pos == 0 or n_neg == 0: return float("nan")
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values))
    ranks[order] = np.arange(1, len(values) + 1)
    sorted_vals = values[order]
    i = 0
    while i < len(sorted_vals):
        j = i
        while j + 1 < len(sorted_vals) and sorted_vals[j + 1] == sorted_vals[i]: j += 1
        if j > i:
            avg = (ranks[order[i]] + ranks[order[j]]) / 2
            ranks[order[i:j+1]] = avg
        i = j + 1
    return float((ranks[labels == 1].sum() - n_pos*(n_pos+1)/2) / (n_pos*n_neg))


def bootstrap_auc_ci(values: np.ndarray, labels: np.ndarray, iters: int = 300) -> tuple[float, float]:
    n = len(values)
    rng = np.random.default_rng(42)
    aucs = np.empty(iters); aucs.fill(np.nan)
    for i in range(iters):
        idx = rng.integers(0, n, n)
        try: aucs[i] = auc(values[idx], labels[idx])
        except: pass
    valid = aucs[~np.isnan(aucs)]
    if len(valid) < 30: return float("nan"), float("nan")
    return float(np.percentile(valid, 2.5)), float(np.percentile(valid, 97.5))


def analyze_feature(feat: str, rows: list[dict], horizon: str, threshold: float) -> dict | None:
    pairs = []
    for r in rows:
        v = coerce(r.get(feat))
        if v is None: continue
        h = r.get(horizon)
        if h is None: continue
        is_pos = 1 if h >= threshold else 0
        pairs.append((v, is_pos))
    if len(pairs) < 100: return None
    coverage = len(pairs) / len(rows)
    if coverage < 0.30: return None
    values = np.array([p[0] for p in pairs])
    labels = np.array([p[1] for p in pairs])
    n_pos = int(labels.sum())
    if n_pos < 5: return None

    a   = auc(values, labels)
    ci  = bootstrap_auc_ci(values, labels)
    pos_med = float(np.median(values[labels==1]))
    neg_med = float(np.median(values[labels==0]))

    # Top quartile mean conditional return at the relevant horizon
    p75 = float(np.percentile(values, 75))
    p25 = float(np.percentile(values, 25))
    mask_top = values >= p75
    mask_bot = values <= p25
    top_wr  = float(labels[mask_top].mean()) if mask_top.sum() else float("nan")
    bot_wr  = float(labels[mask_bot].mean()) if mask_bot.sum() else float("nan")

    return {
        "feature":    feat,
        "horizon":    horizon,
        "threshold":  threshold,
        "n":          len(values),
        "n_pos":      n_pos,
        "base_rate":  float(labels.mean()),
        "coverage":   round(coverage, 3),
        "auc":        round(a, 4),
        "auc_ci_lo":  round(ci[0], 4) if not np.isnan(ci[0]) else None,
        "auc_ci_hi":  round(ci[1], 4) if not np.isnan(ci[1]) else None,
        "discrim":    round(abs(a - 0.5), 4),
        "direction":  "+" if a >= 0.5 else "-",
        "pos_median": pos_med,
        "neg_median": neg_med,
        "top_q_wr":   round(top_wr * 100, 2) if not np.isnan(top_wr) else None,
        "bot_q_wr":   round(bot_wr * 100, 2) if not np.isnan(bot_wr) else None,
    }


def main() -> int:
    rows = load_train_only()
    print(f"loaded {len(rows)} signal moments (train window, before {HELD_OUT_FROM})")

    feature_cols = sorted({k for r in rows for k in r if k.startswith("f_")})
    print(f"features to test: {len(feature_cols)}")

    all_results = []
    for tname, hor, thr in TARGETS:
        # Find which target rows have this horizon column
        valid = [r for r in rows if r.get(hor) is not None]
        n_pos = sum(1 for r in valid if r[hor] >= thr)
        print(f"\nTARGET {tname}: horizon={hor} thr={thr*100:.0f}% "
              f"n={len(valid)} n_pos={n_pos} ({n_pos*100/max(len(valid),1):.2f}%)")
        if n_pos < 10:
            print("  too few positives, skipping")
            continue
        for feat in feature_cols:
            res = analyze_feature(feat, valid, hor, thr)
            if res is None: continue
            res["target"] = tname
            all_results.append(res)

    # Rank by discrim within target
    all_results.sort(key=lambda r: -r["discrim"])

    # CSV
    fields = ["target", "feature", "horizon", "threshold", "n", "n_pos", "base_rate",
              "auc", "auc_ci_lo", "auc_ci_hi", "discrim", "direction",
              "pos_median", "neg_median", "top_q_wr", "bot_q_wr", "coverage"]
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w") as f:
        f.write(",".join(fields) + "\n")
        for r in all_results:
            f.write(",".join(str(r.get(k, "")) for k in fields) + "\n")

    # MD report — top 10 per target with auc_ci_lo > 0.55 or upper < 0.45 (robust)
    md = ["# Edge Search — Top Features per Target\n"]
    md.append(f"_Train rows: {len(rows)}, days < {HELD_OUT_FROM} (held-out test reserved)._\n")
    by_target = defaultdict(list)
    for r in all_results:
        by_target[r["target"]].append(r)
    for t in [t[0] for t in TARGETS]:
        md.append(f"## {t}\n")
        md.append("| feature | AUC | 95% CI | dir | n | n_pos | top_q WR | bot_q WR |")
        md.append("|---|---:|---|:---:|---:|---:|---:|---:|")
        sub = sorted(by_target[t], key=lambda r: -r["discrim"])[:15]
        for r in sub:
            ci = (f"[{r['auc_ci_lo']:.3f}, {r['auc_ci_hi']:.3f}]"
                  if r["auc_ci_lo"] is not None else "—")
            tq = f"{r['top_q_wr']:.1f}%" if r["top_q_wr"] is not None else "—"
            bq = f"{r['bot_q_wr']:.1f}%" if r["bot_q_wr"] is not None else "—"
            md.append(f"| `{r['feature']}` | {r['auc']:.3f} | {ci} | {r['direction']} | "
                      f"{r['n']} | {r['n_pos']} | {tq} | {bq} |")
        md.append("")
    OUT_MD.write_text("\n".join(md))

    print(f"\nWrote {OUT_CSV} ({len(all_results)} rows) and {OUT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
