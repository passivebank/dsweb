"""Audit of shadow_trades data and r5_v10 baseline performance."""
import json
from collections import Counter
from pathlib import Path

SHADOW = Path("/home/ec2-user/phase3_intrabar/artifacts/shadow_trades.jsonl")


def main():
    delays = Counter()
    with SHADOW.open() as f:
        for line in f:
            r = json.loads(line)
            delays[r.get("delay_ms")] += 1

    print("Delays distribution:")
    for k, v in sorted(delays.items(), key=lambda x: (x[0] is None, x[0])):
        print(f"  {str(k):>10s}  {v:,}")

    # ===== r5_v10 (current live algorithm) baseline =====
    print("\n=== r5_v10 performance (current live algo) ===")
    rows = []
    with SHADOW.open() as f:
        for line in f:
            r = json.loads(line)
            if r.get("exit_policy") == "r5_v10":
                rows.append(r)

    print(f"r5_v10 records: {len(rows)}")
    delays_r5 = Counter(t["delay_ms"] for t in rows)
    variants_r5 = Counter(t["variant"] for t in rows)
    reasons_r5 = Counter(t["exit_reason"] for t in rows)
    print(f"Delays: {dict(delays_r5)}")
    print(f"Variants: {dict(variants_r5)}")
    print(f"Exit reasons: {dict(reasons_r5)}")

    # Deduplicate to one record per signal (prefer delay_ms==0)
    seen = {}
    for t in rows:
        k = (t["coin"], t["entry_ts_ns"])
        prev = seen.get(k)
        if prev is None or (t["delay_ms"] or 0) < (prev["delay_ms"] or 99999):
            seen[k] = t

    print(f"Unique signals: {len(seen)}")

    net = [t["net_pct"] for t in seen.values()]
    if net:
        wins = [n for n in net if n > 0]
        print(f"Win rate: {len(wins) / len(net) * 100:.1f}%")
        print(f"Avg net:  {sum(net) / len(net) * 100:+.3f}%")
        print(f"Sum net:  {sum(net) * 100:+.2f}%")
        print(f"Max:      {max(net) * 100:+.2f}%")
        print(f"Min:      {min(net) * 100:+.2f}%")

    # ===== Daily signal counts across full dataset =====
    print("\n=== Unique signals per day (any variant) ===")
    from datetime import datetime, timezone
    by_day = Counter()
    seen_all = set()
    with SHADOW.open() as f:
        for line in f:
            r = json.loads(line)
            key = (r.get("entry_ts_ns"), r.get("coin"), r.get("variant"))
            if key in seen_all:
                continue
            seen_all.add(key)
            ts_ns = r.get("entry_ts_ns", 0)
            if ts_ns:
                d = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc).date().isoformat()
                by_day[d] += 1
    print(f"Days with signals: {len(by_day)}")
    for d in sorted(by_day):
        print(f"  {d}: {by_day[d]:,}")


if __name__ == "__main__":
    main()
