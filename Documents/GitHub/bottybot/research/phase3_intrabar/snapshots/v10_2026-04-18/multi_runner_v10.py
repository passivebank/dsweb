#!/usr/bin/env python3
"""
multi_runner_v10.py — dvt bimodal FIXED from v9 lesson + v8 base.

v9 lesson: removing dvt >= 1.0 minimum opened up declining-volume entries (dvt < 1.0)
           and flooded in bad trades. EV dropped from +4.70% to +2.53%.

Correct dvt filter: (1.0 <= dvt < 1.5) OR (dvt >= 2.5)
  - 1.0 to 1.5: steady stable volume accumulation (NOT declining)
  - 1.5 to 2.5: moderate surge zone — bad tier (removed)
  - >= 2.5: institutional volume tsunami — keep

v8 losses targeted by this fix:
  CHECK -8.8% (dvt=1.69), INX -6.8% (dvt=2.48), INX -5.0% (dvt=2.02), RAVE -4.8% (dvt=1.56)
  All fall in 1.5-2.5 "bad middle zone" — will be filtered.

Changes from v8:
  1. R5 dvt filter: (1.0 <= dvt < 1.5) OR (dvt >= 2.5) — removes the moderate surge zone
     Previously v8 had dvt >= 1.0 with no upper constraint (let bad 1.5-2.5 through)
"""

import sys, gzip, json, csv, bisect
from datetime import datetime, timezone
from pathlib import Path
from collections import deque, defaultdict

DURABLE = Path("/home/ec2-user/phase3_intrabar/data/durable")
OUT_DIR  = Path("/home/ec2-user/phase3_intrabar/artifacts")
OUT_DIR.mkdir(exist_ok=True)
NS = 1_000_000_000

def fmt(ns):
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ── Phase 1: 1m candles ──────────────────────────────────────────────

def build_all_candles(all_files):
    candles = defaultdict(dict)
    print(f"Phase 1: candles from {len(all_files)} files...", flush=True)
    for i, path in enumerate(all_files):
        if i % 20 == 0:
            print(f"  {i}/{len(all_files)}", flush=True)
        with gzip.open(path, "rt") as f:
            for line in f:
                if '"trade"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if ev.get("ch") != "trade":
                    continue
                prod  = ev.get("prod", "")
                if not prod.endswith("-USD"):
                    continue
                ts    = ev.get("server_ts_ns") or ev.get("recv_ts_ns", 0)
                price = ev.get("price", 0.0)
                size  = ev.get("size", 0.0)
                side  = ev.get("side", "")
                if price <= 0 or size <= 0 or ts <= 0:
                    continue
                coin = prod[:-4];  usd = price * size
                mt   = (ts // (60 * NS)) * 60
                cd   = candles[coin]
                if mt not in cd:
                    cd[mt] = {"o": price, "h": price, "l": price,
                               "c": price, "v": usd, "bv": 0.0, "n": 1}
                else:
                    c = cd[mt]
                    if price > c["h"]: c["h"] = price
                    if price < c["l"]: c["l"] = price
                    c["c"] = price;  c["v"] += usd;  c["n"] += 1
                    if side == "buy": c["bv"] += usd
    print(f"  Done: {len(candles)} coins.", flush=True)
    return dict(candles)


# ── Phase 2: find runners ────────────────────────────────────────────

def find_runners(candles_all, min_gain=0.25):
    runners = {}
    for coin, cd in candles_all.items():
        if len(cd) < 20:
            continue
        mins   = sorted(cd.keys())
        prices = [cd[m]["c"] for m in mins]
        n      = len(prices)
        max_g  = 0.0
        for i in range(n):
            if prices[i] <= 0: continue
            fm = max(prices[i:min(i + 241, n)])
            g  = fm / prices[i] - 1.0
            if g > max_g: max_g = g
        if max_g >= min_gain:
            all_p = [p for p in prices if p > 0]
            runners[coin] = {
                "max_4h_gain":  max_g,
                "overall_gain": max(all_p) / min(all_p) - 1.0 if all_p else 0,
                "n_candles":    n,
            }
    return dict(sorted(runners.items(), key=lambda x: -x[1]["max_4h_gain"]))


# ── Streaming state ──────────────────────────────────────────────────

class CoinStream:
    MID_WIN  = 1800 * NS   # 30 min mid window (enough for ret_over 900s)

    def __init__(self, coin, candles_1m):
        self.coin  = coin
        self.c1m   = candles_1m
        self._cms  = sorted(candles_1m.keys())

        self.trades  = deque()
        self.mts     = []    # mid ts (sorted, append-only for bisect)
        self.mpx     = []    # mid prices
        self.spreads = deque(maxlen=600)

        self.last_mid = 0.0
        self.last_bid = 0.0
        self.last_ask = 0.0

        self.consec   = 0
        self._bnd_ns  = 0
        self._bnd_mid = 0.0
        self._nev     = 0    # next evict timestamp

    def on_trade(self, ts, price, usd, side):
        self.trades.append((ts, price, usd, side))
        if self.last_mid == 0.0: self.last_mid = price

    def on_quote(self, ts, bid, ask):
        mid = (bid + ask) * 0.5
        self.last_bid = bid;  self.last_ask = ask;  self.last_mid = mid
        self.mts.append(ts);  self.mpx.append(mid)
        s = (ask - bid) / mid * 1e4
        if s > 0: self.spreads.append(s)
        bnd = (ts // (30 * NS)) * 30
        if bnd > self._bnd_ns and self._bnd_mid > 0:
            self.consec = self.consec + 1 if mid / self._bnd_mid - 1.0 > 0.002 else 0
            self._bnd_mid = mid;  self._bnd_ns = bnd
        elif self._bnd_ns == 0:
            self._bnd_ns = bnd;  self._bnd_mid = mid

    def evict(self, ts):
        ct = ts - 600 * NS
        while self.trades and self.trades[0][0] < ct:
            self.trades.popleft()
        if ts >= self._nev:
            self._nev = ts + 60 * NS
            cm = ts - self.MID_WIN
            idx = bisect.bisect_left(self.mts, cm)
            if idx > 0:
                del self.mts[:idx]
                del self.mpx[:idx]

    def dv(self, ts, s):
        c = ts - s * NS
        return sum(t[2] for t in self.trades if t[0] >= c)

    def tr(self, ts, s=30):
        c = ts - s * NS
        return sum(1 for t in self.trades if t[0] >= c)

    def avgsz(self, ts, s=60):
        c = ts - s * NS
        sz = [t[2] for t in self.trades if t[0] >= c]
        return sum(sz) / len(sz) if sz else 0.0

    def sprd(self):
        if self.last_bid <= 0 or self.last_ask <= 0: return 999.0
        return (self.last_ask - self.last_bid) / self.last_mid * 1e4

    def typ_sprd(self):
        n = len(self.spreads)
        return sorted(self.spreads)[n // 2] if n >= 40 else 0.0

    def mid_at(self, ts):
        if not self.mts: return 0.0
        i = bisect.bisect_right(self.mts, ts) - 1
        return self.mpx[i] if i >= 0 else 0.0

    def ret(self, ts, s):
        if self.last_mid <= 0: return 0.0
        old = self.mid_at(ts - s * NS)
        return self.last_mid / old - 1.0 if old > 0 else 0.0

    def r24(self, ts):
        if self.last_mid <= 0 or not self._cms: return 0.0
        tgt = ((ts - 86400 * NS) // (60 * NS)) * 60
        i   = bisect.bisect_right(self._cms, tgt) - 1
        if i < 0: return 0.0
        old = self.c1m[self._cms[i]]["c"]
        return self.last_mid / old - 1.0 if old > 0 else 0.0

    def stairs(self, ts, n=3, step=60):
        steps = []
        for i in range(n):
            me = self.mid_at(ts - i * step * NS)
            ms = self.mid_at(ts - (i+1) * step * NS)
            if ms <= 0 or me <= 0: return None
            steps.append(me / ms - 1.0)
        steps.reverse()
        return steps


# ── Signals ──────────────────────────────────────────────────────────

CD_NS = {"WAVE_RIDER": 300*NS, "MEGA_RUNNER": 600*NS,
         "R9_STAIRCASE": 300*NS, "R5_CONFIRMED_RUN": 300*NS, "CONSOLIDATION": 300*NS}

def detect(st, ts, cd, dv30, dv60, dv300):
    """dv30/60/300 passed in to avoid recomputation."""
    if st.last_mid <= 0: return []
    mid   = st.last_mid
    sprd  = st.sprd()
    tsp   = st.typ_sprd()
    tr30  = st.tr(ts, 30)
    avgsz = st.avgsz(ts, 60)
    r15m  = st.ret(ts, 900);  r5m = st.ret(ts, 300);  r1m = st.ret(ts, 60)
    csec  = st.consec
    r24   = st.r24(ts)
    stps  = st.stairs(ts)
    mstp  = sum(stps) / 3 if stps else 0.0
    mxsp  = max(10.0, min(tsp * 0.20, 20.0)) if tsp > 0 else 10.0
    dvt   = (dv60 / (dv300 / 5)) if dv300 > 0 else 1.0

    # Spread ratio: current / typical. < 1.0 = book compressing (bullish liquidity)
    sprd_ratio = sprd / tsp if tsp > 0 else 999.0

    out = []
    def can(n): return ts - cd.get(n, 0) >= CD_NS[n]
    def em(n, f): cd[n] = ts; out.append((n, mid, f))

    # WAVE_RIDER: strict original thresholds restored after v6 showed relaxation
    # added 3 trades, all losses. csec>=8 = 4 continuous minutes of momentum.
    if can("WAVE_RIDER") and csec >= 8 and tr30 >= 80 and dv30 >= 50_000 \
            and stps and mstp >= 0.010 and r15m >= 0.06 and sprd <= mxsp:
        em("WAVE_RIDER", {"csec": csec, "tr30": tr30, "dv30": round(dv30),
                           "mstp": round(mstp,4), "r15m": round(r15m,4),
                           "sprd": round(sprd,1), "r24": round(r24,3)})

    if can("MEGA_RUNNER") and tr30 >= 150 and r24 >= 0.30 \
            and csec >= 20 and dv30 >= 100_000:
        em("MEGA_RUNNER", {"tr30": tr30, "r24": round(r24,3),
                            "csec": csec, "dv30": round(dv30), "sprd": round(sprd,1)})

    # R9_STAIRCASE: DISABLED — net negative in v6 (5 trades, 40% WR, -9.8% total)
    # even with spread compression gate. Signal over-fitted to RAVE Apr-12 behavior.
    # Re-enable only after collecting more multi-coin data to generalize.
    # if can("R9_STAIRCASE") and dv30 >= 100_000 and stps \
    #         and mstp >= 0.010 and all(s >= 0.003 for s in stps) and avgsz >= 500 \
    #         and sprd_ratio <= 0.5:
    #     em("R9_STAIRCASE", ...)

    # R5_CONFIRMED_RUN: bimodal r5m + bimodal dvt (FIXED) + 10bps spread cap
    # r5m bimodal: 0.5-1% (consolidation, 73% WR) OR >=3% (surge, 67% WR) — skip 1-3%
    # dvt bimodal: [1.0,1.5) steady stable volume OR >=2.5 tsunami — skip 1.5-2.5 moderate zone
    #   v8 losses: CHECK -8.8%(dvt=1.69), INX -6.8%(dvt=2.48), INX -5.0%(dvt=2.02) all in bad zone
    #   v9 lesson: must keep dvt >= 1.0 floor (dvt < 1.0 = declining volume = bad entries)
    r5m_bimodal = (0.005 <= r5m < 0.010) or (r5m >= 0.030)
    dvt_bimodal = (1.0 <= dvt < 1.5) or (dvt >= 2.5)
    if can("R5_CONFIRMED_RUN") and r24 >= 0.12 and r15m >= 0.01 \
            and r5m_bimodal and dvt_bimodal and sprd <= 10.0 \
            and not (1.0 <= r24 < 2.0):
        em("R5_CONFIRMED_RUN", {"r24": round(r24,3), "r15m": round(r15m,4),
                                 "r5m": round(r5m,4), "dvt": round(dvt,2), "sprd": round(sprd,1)})

    if can("CONSOLIDATION") and csec >= 25 and abs(r1m) < 0.005 \
            and dv30 >= 20_000 and r24 >= 0.20:
        em("CONSOLIDATION", {"csec": csec, "r1m": round(r1m,5),
                              "dv30": round(dv30), "r24": round(r24,3), "sprd": round(sprd,1)})
    return out


# ── Trade / P&L ──────────────────────────────────────────────────────

SLIP  = 10.0 / 10_000

# v7: R5 trail reverted to 7% PRE-partial (v6's 12% let losses reach -12%)
# Once 50% is locked in at +20%, trail widens to 15% on the remainder
TRAIL = {"WAVE_RIDER": 0.07, "MEGA_RUNNER": 0.10, "R9_STAIRCASE": 0.07,
         "R5_CONFIRMED_RUN": 0.07, "CONSOLIDATION": 0.08}
TRAIL_AFTER_PARTIAL = 0.15   # wider trail once 50% is locked in
PARTIAL_TRIGGER = 0.20       # sell 50% when gain first reaches +20%

TMAX  = 4 * 3600 * NS
VCMIN = 300 * NS

class Trade:
    __slots__ = ("sig","coin","emid","epx","ets","peak","mdv5",
                 "xpx","xts","xrsn","feats","half_px")
    def __init__(self, sig, coin, mid, ts, feats):
        self.sig = sig; self.coin = coin; self.emid = mid
        self.epx = mid*(1+SLIP); self.ets = ts
        self.peak = mid; self.mdv5 = 0.0
        self.xpx = None; self.xts = None; self.xrsn = None
        self.feats = feats
        self.half_px = None  # price at which 50% was sold (None = not triggered)

    def close(self, mid, ts, rsn):
        self.xpx = mid*(1-SLIP); self.xts = ts; self.xrsn = rsn

    @property
    def gain(self):
        if self.xpx is None: return None
        final_gain = self.xpx / self.epx - 1.0
        if self.half_px is not None:
            # 50% sold at half_px, 50% closed at xpx
            half_gain = self.half_px / self.epx - 1.0
            return 0.5 * half_gain + 0.5 * final_gain
        return final_gain

    @property
    def max_gain(self): return self.peak / self.epx - 1.0

    @property
    def hold_min(self): return (self.xts - self.ets) / NS / 60 if self.xts else None


# ── Main replay ──────────────────────────────────────────────────────

def run_backtest(runners, candles_all, all_files):
    runner_list = list(runners.keys())
    states   = {c: CoinStream(c, candles_all[c]) for c in runner_list}
    cds      = {c: {} for c in runner_list}
    open_tr  = {c: [] for c in runner_list}
    closed   = {c: [] for c in runner_list}
    last_chk = {c: 0 for c in runner_list}
    p2c      = {c + "-USD": c for c in runner_list}  # fast prod→coin lookup
    CHECK_NS = 10 * NS
    total    = 0
    n        = len(all_files)

    for fi, path in enumerate(all_files):
        print(f"\r  [{fi+1}/{n}] closed={total}  ", end="", flush=True)
        with gzip.open(path, "rt") as f:
            for line in f:
                # ── Fast prod extraction ─────────────────────────
                i = line.find('"prod":"')
                if i < 0: continue
                j = line.find('"', i + 8)
                if j < 0: continue
                prod = line[i+8:j]
                coin = p2c.get(prod)
                if coin is None: continue
                if '"book' in line: continue   # skip book10

                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                ch = ev.get("ch")
                if ch not in ("trade", "quote"): continue
                ts = ev.get("server_ts_ns") or ev.get("recv_ts_ns", 0)
                if ts <= 0: continue

                st = states[coin]
                if ch == "trade":
                    p, sz = ev.get("price", 0.0), ev.get("size", 0.0)
                    if p > 0 and sz > 0:
                        st.on_trade(ts, p, p*sz, ev.get("side", ""))
                else:
                    b, a = ev.get("bid", 0.0), ev.get("ask", 0.0)
                    if b > 0 and a > 0:
                        st.on_quote(ts, b, a)

                st.evict(ts)

                # ── Per-event: cheap O(1) exit checks only ───────
                mid = st.last_mid
                if mid > 0 and open_tr[coin]:
                    for tr in list(open_tr[coin]):
                        if mid > tr.peak: tr.peak = mid

                        # Partial exit: lock in 50% at +20% gain
                        if tr.half_px is None and mid / tr.epx - 1.0 >= PARTIAL_TRIGGER:
                            tr.half_px = mid * (1 - SLIP)

                        # Trailing stop: wider after partial exit
                        if tr.half_px is not None:
                            trail = TRAIL_AFTER_PARTIAL
                        else:
                            trail = TRAIL.get(tr.sig, 0.07)

                        if tr.peak > 0 and mid < tr.peak * (1 - trail):
                            tr.close(mid, ts, "TRAILING_STOP")
                            open_tr[coin].remove(tr)
                            closed[coin].append(tr);  total += 1
                            continue

                        # Time stop (O(1))
                        if ts - tr.ets >= TMAX:
                            tr.close(mid, ts, "TIME_STOP")
                            open_tr[coin].remove(tr)
                            closed[coin].append(tr);  total += 1

                # ── Every 10s: dv computations + vol collapse + signals
                if ts - last_chk[coin] >= CHECK_NS:
                    last_chk[coin] = ts
                    dv30  = st.dv(ts, 30)
                    dv60  = st.dv(ts, 60)
                    dv300 = st.dv(ts, 300)

                    # Vol collapse check (expensive dv300 only here)
                    if open_tr[coin]:
                        for tr in list(open_tr[coin]):
                            if dv300 > tr.mdv5: tr.mdv5 = dv300
                            if (ts - tr.ets >= VCMIN and
                                    tr.mdv5 > 0 and dv300 < tr.mdv5 * 0.05):
                                tr.close(st.last_mid, ts, "VOL_COLLAPSE")
                                open_tr[coin].remove(tr)
                                closed[coin].append(tr);  total += 1

                    # Signals
                    for sig, emid, feats in detect(st, ts, cds[coin], dv30, dv60, dv300):
                        if not any(t.sig == sig for t in open_tr[coin]):
                            open_tr[coin].append(Trade(sig, coin, emid, ts, feats))

    print(f"\r  Done. {total} closed trades.              ", flush=True)

    # Force-close remaining open trades
    for coin, tl in open_tr.items():
        st = states[coin]
        for tr in tl:
            if st.last_mid > 0:
                tr.close(st.last_mid, last_chk[coin], "END_OF_DATA")
            closed[coin].append(tr)
    return closed


# ── Analysis ─────────────────────────────────────────────────────────

def classify(t):
    g, mg = t.gain or 0, t.max_gain
    if g >= 0: return "WIN"
    if mg > 0.15 and g < -0.03: return f"MISSED_EXIT:max={mg*100:.0f}%"
    if t.hold_min is not None and t.hold_min < 10: return f"EARLY_STOP:{t.hold_min:.0f}m"
    if t.xrsn == "TIME_STOP" and g < -0.02: return "WRONG_DIRECTION"
    if t.xrsn == "VOL_COLLAPSE": return "VOL_SPIKE_NO_WAVE"
    return f"MISC:{g*100:.1f}%"


# ── Main ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    all_files = sorted(DURABLE.glob("events_*.jsonl.gz"))
    print(f"Multi-Runner Backtest v10")
    print(f"Changes: R5 dvt bimodal FIXED: (1.0<=dvt<1.5) OR (dvt>=2.5)")
    print(f"         Targets: CHECK -8.8%(dvt=1.69), INX -6.8%(dvt=2.48), INX -5.0%(dvt=2.02)")
    print(f"Files: {len(all_files)} | {all_files[0].stem} → {all_files[-1].stem}")
    print("=" * 72)

    candles_all = build_all_candles(all_files)

    print("\nPhase 2: runners >= 25%...")
    runners = find_runners(candles_all, min_gain=0.25)
    print(f"{len(runners)} runners:")
    for c, info in list(runners.items())[:30]:
        print(f"  {c:<14} 4h={info['max_4h_gain']*100:5.0f}%  "
              f"tot={info['overall_gain']*100:5.0f}%  n={info['n_candles']}")

    print(f"\nPhase 3: replay ({len(runners)} coins, single pass)...")
    closed = run_backtest(runners, candles_all, all_files)

    all_tr = [t for tl in closed.values() for t in tl if t.gain is not None]

    # ── Coin results ───────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("COIN RESULTS")
    print("=" * 72)
    print(f"{'Coin':<12} {'4h%':>6} {'N':>5} {'WR%':>5} {'AvgW%':>7} {'AvgL%':>7} {'Tot%':>7} {'Best%':>7}")
    print("-" * 72)
    for coin, info in runners.items():
        tl = [t for t in closed.get(coin, []) if t.gain is not None]
        if not tl:
            print(f"{coin:<12} {info['max_4h_gain']*100:>5.0f}%    —"); continue
        wi = [t for t in tl if t.gain >= 0]
        lo = [t for t in tl if t.gain < 0]
        print(f"{coin:<12} {info['max_4h_gain']*100:>5.0f}% {len(tl):>5} "
              f"{len(wi)/len(tl)*100:>4.0f}% "
              f"{(sum(t.gain for t in wi)/len(wi)*100 if wi else 0):>6.1f}% "
              f"{(sum(t.gain for t in lo)/len(lo)*100 if lo else 0):>6.1f}% "
              f"{sum(t.gain for t in tl)*100:>6.1f}% "
              f"{max(t.gain for t in tl)*100:>6.1f}%")

    # ── Signal results ─────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("SIGNAL RESULTS")
    print("=" * 72)
    print(f"{'Signal':<22} {'N':>5} {'WR%':>5} {'AvgW%':>7} {'AvgL%':>7} {'PF':>6} {'Tot%':>7}")
    print("-" * 72)
    bysig = defaultdict(list)
    for t in all_tr: bysig[t.sig].append(t)
    for sig in ["WAVE_RIDER","MEGA_RUNNER","R9_STAIRCASE","R5_CONFIRMED_RUN","CONSOLIDATION"]:
        tl = bysig.get(sig, [])
        if not tl: print(f"{sig:<22}      0"); continue
        wi = [t for t in tl if t.gain >= 0]
        lo = [t for t in tl if t.gain < 0]
        gw = sum(t.gain for t in wi)
        gl = abs(sum(t.gain for t in lo)) or 1e-9
        print(f"{sig:<22} {len(tl):>5} {len(wi)/len(tl)*100:>4.0f}% "
              f"{(gw/len(wi)*100 if wi else 0):>6.1f}% "
              f"{(sum(t.gain for t in lo)/len(lo)*100 if lo else 0):>6.1f}% "
              f"{gw/gl:>5.1f}x {sum(t.gain for t in tl)*100:>6.1f}%")

    # ── Partial exit stats ─────────────────────────────────────────
    partial = [t for t in all_tr if t.half_px is not None]
    print(f"\n  Partial exits triggered: {len(partial)} trades "
          f"({len(partial)/len(all_tr)*100:.0f}% of all trades)")
    if partial:
        p_gain = sum(t.gain for t in partial)
        print(f"  Partial exit avg gain: {p_gain/len(partial)*100:+.2f}%  "
              f"total contribution: {p_gain*100:+.1f}%")

    # ── Exit reasons ───────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("EXIT REASONS")
    print("=" * 72)
    ec = defaultdict(lambda: {"n":0, "g":0.0})
    for t in all_tr: ec[t.xrsn]["n"]+=1; ec[t.xrsn]["g"]+=t.gain
    for rsn, d in sorted(ec.items(), key=lambda x:-x[1]["n"]):
        print(f"  {rsn:<22} n={d['n']:>4}  avg={d['g']/d['n']*100:+.1f}%")

    # ── Failures ───────────────────────────────────────────────────
    losses = [t for t in all_tr if t.gain < -0.02]
    print(f"\n" + "=" * 72)
    print(f"FAILURE BREAKDOWN ({len(losses)} losses > 2%)")
    print("=" * 72)
    cats = defaultdict(int)
    for t in losses: cats[classify(t)] += 1
    for cls, n in sorted(cats.items(), key=lambda x:-x[1]):
        print(f"  {n:>3}x  {cls}")

    big = sorted([t for t in all_tr if (t.gain or 0) < -0.05], key=lambda x:x.gain)
    if big:
        print("\nLargest losses (>5%):")
        for t in big[:12]:
            print(f"  [{t.coin}/{t.sig}] entry=${t.emid:.5f} gain={t.gain*100:.1f}% "
                  f"max={t.max_gain*100:.1f}% hold={t.hold_min:.0f}m → {classify(t)}")

    # ── Top trades ─────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("TOP 15 TRADES")
    print("=" * 72)
    for t in sorted(all_tr, key=lambda x:-(x.gain or 0))[:15]:
        half_tag = f" [partial@{t.half_px/t.epx*100-100:+.0f}%]" if t.half_px else ""
        print(f"  {t.coin:<10} {t.sig:<22} "
              f"+{t.gain*100:.1f}%  max={t.max_gain*100:.1f}%  "
              f"hold={t.hold_min:.0f}m  exit={t.xrsn}{half_tag}")

    # ── v5 vs v6 comparison ────────────────────────────────────────
    print("\n" + "=" * 72)
    print("v5 → v8 → v10 COMPARISON")
    print("=" * 72)
    print("  v5 baseline:  127 trades, 58% WR, +3.22% EV/trade, +408.8% total")
    print("  v6 result:     97 trades, 60% WR, +3.23% EV/trade, +313.7% total")
    print("  v7 result:     99 trades, 63% WR, +3.23% EV/trade, +319.3% total")
    print("  v8 result:     65 trades, 69% WR, +4.70% EV/trade, +305.5% total")
    print("  v9 result:    107 trades, 59% WR, +2.53% EV/trade, +271.0% total  [bad-dvt<1.0 opened]")
    nt = len(all_tr)
    nw = sum(1 for t in all_tr if t.gain >= 0)
    tot = sum(t.gain for t in all_tr)
    print(f"  v6 result:   {nt:3d} trades, {nw/nt:.0%} WR, {tot/nt*100:+.2f}% EV/trade, {tot*100:+.1f}% total")
    ev_delta_v5 = tot/nt*100 - 3.22
    ev_delta_v8 = tot/nt*100 - 4.70
    print(f"  EV delta vs v5: {ev_delta_v5:+.2f}%/trade  vs v8: {ev_delta_v8:+.2f}%/trade")

    # ── Summary ────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    if nt:
        print(f"TOTAL: {nt} trades  WR={nw/nt:.0%}  "
              f"EV={tot/nt*100:+.2f}%/trade  "
              f"sum={tot*100:+.1f}%")

    # ── Write CSV ──────────────────────────────────────────────────
    trades_csv = OUT_DIR / "backtest_v10_trades.csv"
    with open(trades_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["coin","sig","entry_mid","peak","gain_pct","max_gain_pct",
                    "hold_min","exit_reason","half_exit_pct","entry_time","features"])
        for t in sorted(all_tr, key=lambda x:-(x.gain or 0)):
            w.writerow([
                t.coin, t.sig,
                round(t.emid, 8), round(t.peak, 8),
                round((t.gain or 0)*100, 3),
                round(t.max_gain*100, 3),
                round(t.hold_min or 0, 1),
                t.xrsn,
                round(t.half_px/t.epx*100-100, 2) if t.half_px else "",
                fmt(t.ets),
                json.dumps(t.feats),
            ])
    print(f"\nTrades CSV: {trades_csv}")

    coins_csv = OUT_DIR / "backtest_v10_coins.csv"
    with open(coins_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["coin","max_4h_gain","overall_gain","n_trades","win_rate",
                    "avg_win","avg_loss","total","best"])
        for coin, info in runners.items():
            tl = [t for t in closed.get(coin, []) if t.gain is not None]
            if not tl:
                w.writerow([coin, round(info["max_4h_gain"]*100,1),
                             round(info["overall_gain"]*100,1), 0,"","","","",""])
                continue
            wi = [t for t in tl if t.gain >= 0]
            lo = [t for t in tl if t.gain < 0]
            w.writerow([
                coin,
                round(info["max_4h_gain"]*100,1),
                round(info["overall_gain"]*100,1),
                len(tl),
                round(len(wi)/len(tl)*100,1),
                round(sum(t.gain for t in wi)/len(wi)*100 if wi else 0, 2),
                round(sum(t.gain for t in lo)/len(lo)*100 if lo else 0, 2),
                round(sum(t.gain for t in tl)*100, 2),
                round(max(t.gain for t in tl)*100, 2),
            ])
    print(f"Coins CSV:  {coins_csv}")
