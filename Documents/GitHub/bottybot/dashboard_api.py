"""
dashboard_api.py — BOTTY Command Center API (Phase 3 Precision Filter Edition)
Reads live_trades.jsonl from EC2 via SSH. Coinbase API for live portfolio.
Port 8003.
"""

import os, json, time, subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import uvicorn

app = FastAPI(title="BOTTY Command Center — Phase 3")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# File paths (same whether local or on EC2)
LIVE_TRADES  = "/home/ec2-user/phase3_intrabar/artifacts/live_trades.jsonl"
RECORDER_LOG = "/home/ec2-user/phase3_intrabar/artifacts/recorder.log"
HEARTBEAT    = "/home/ec2-user/phase3_intrabar/artifacts/recorder_heartbeat.json"

# Auto-detect: if running ON the EC2, files are local; otherwise SSH
LOCAL = Path(LIVE_TRADES).exists()
ENV_FILE = "/home/ec2-user/nkn_bot/.env" if LOCAL else ".env"
TEMPLATES_DIR = Path(__file__).parent / "templates" if not LOCAL else Path("/home/ec2-user/botty_dashboard/templates")

# SSH config (only used when not LOCAL)
EC2_HOST = "ec2-user@3.214.53.81"
EC2_KEY  = str(Path.home() / "Documents/GitHub/bottybot/Botty.pem")

# Precision filter go-live timestamp
DEPLOY_TS = "2026-04-22T17:13:46Z"

# ── Data fetching (local or SSH) ─────────────────────────────────────────────

_cache: dict[str, Any] = {}

def _fetch(key: str, ttl: int, local_fn, ssh_cmd: str) -> str:
    now = time.monotonic()
    entry = _cache.get(key)
    if entry and now - entry["ts"] < ttl:
        return entry["data"]
    try:
        if LOCAL:
            data = local_fn()
        else:
            r = subprocess.run(
                ["ssh", "-i", EC2_KEY, "-o", "StrictHostKeyChecking=no",
                 "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", EC2_HOST, ssh_cmd],
                capture_output=True, text=True, timeout=12,
            )
            data = r.stdout
    except Exception:
        data = (entry or {}).get("data", "")
    _cache[key] = {"ts": now, "data": data}
    return data

def read_file(path: str, key: str, ttl: int = 25) -> str:
    return _fetch(key, ttl,
        local_fn=lambda: Path(path).read_text(errors="replace"),
        ssh_cmd=f"cat {path}",
    )

def grep_file(path: str, pattern: str, key: str, ttl: int = 12, tail: int = 600) -> str:
    return _fetch(key, ttl,
        local_fn=lambda: subprocess.run(
            ["grep", "-E", pattern, path],
            capture_output=True, text=True, timeout=5,
        ).stdout,
        ssh_cmd=f"grep -E '{pattern}' {path} | tail -{tail}",
    )

def run_remote(cmd: str, key: str, ttl: int = 20) -> str:
    return _fetch(key, ttl,
        local_fn=lambda: subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5).stdout,
        ssh_cmd=cmd,
    )

# ── Trade parsing ────────────────────────────────────────────────────────────

def _get_field(obj: dict, *keys, default=0):
    for k in keys:
        v = obj.get(k)
        if v is not None:
            return v
    return default

def parse_live_trades():
    """Parse live_trades.jsonl → (closed_trades, open_positions)."""
    raw = read_file(LIVE_TRADES, "live_trades", ttl=25)
    events = []
    for line in raw.strip().splitlines():
        try:
            events.append(json.loads(line.strip()))
        except Exception:
            pass

    open_pos: dict[str, dict] = {}
    closed: list[dict] = []

    for e in events:
        ev   = e.get("event", "")
        coin = e.get("coin", "")
        if not coin:
            continue

        if ev == "ENTRY":
            open_pos[coin] = e

        elif ev == "EXIT":
            entry = open_pos.pop(coin, None)

            # Normalise gain across both log formats
            gain = _get_field(e, "gain", "net_pct", "gross_pct", default=None)
            if gain is None:
                usd_out = e.get("usd_out", 0)
                usd_in_e = entry.get("usd_in", entry.get("usd_size", 0)) if entry else 0
                gain = (usd_out - usd_in_e) / usd_in_e if usd_in_e else 0

            usd_in  = _get_field(entry or {}, "usd_size", "usd_in", default=0)
            pnl_usd = round(usd_in * gain, 2) if usd_in else 0

            features = {}
            if entry:
                features = entry.get("features") or entry.get("sig_features") or {}

            variant = (
                entry.get("variant") if entry else None
            ) or features.get("variant", "")

            # Label pre-deploy trades clearly
            exit_ts = _get_field(e, "ts", "exit_ts", default="")
            if not variant:
                variant = "precision" if exit_ts >= DEPLOY_TS else "legacy"

            entry_ts = _get_field(entry or {}, "ts", "entry_ts", default="")
            entry_px = _get_field(entry or {}, "price", "entry_px", default=0)

            closed.append({
                "coin":        coin,
                "variant":     variant,
                "tier":        (entry or {}).get("tier", ""),
                "entry_ts":    entry_ts,
                "exit_ts":     exit_ts,
                "entry_px":    entry_px,
                "exit_px":     _get_field(e, "price", "exit_px", default=0),
                "usd_in":      usd_in,
                "gain":        round(gain, 4),
                "pnl_usd":     pnl_usd,
                "hold_min":    e.get("hold_min", 0),
                "exit_reason": _get_field(e, "reason", "exit_reason", default=""),
                "win":         gain > 0,
                "rank_60s":    features.get("rank_60s", ""),
                "breadth":     features.get("market_breadth_5m", ""),
                "half_sold":   e.get("half_sold", False),
            })

        # FILL/PARTIAL events: ignored for P&L tracking

    # Sort chronologically, compute running cumulative P&L
    closed.sort(key=lambda x: x["exit_ts"])
    cum = 0.0
    for t in closed:
        cum += t["pnl_usd"]
        t["cum_pnl"] = round(cum, 2)

    # Build open positions list
    open_list = []
    for coin, entry in open_pos.items():
        features = entry.get("features") or entry.get("sig_features") or {}
        variant  = entry.get("variant") or features.get("variant", "precision")
        open_list.append({
            "coin":     coin,
            "variant":  variant,
            "tier":     entry.get("tier", ""),
            "entry_ts": _get_field(entry, "ts", "entry_ts", default=""),
            "entry_px": _get_field(entry, "price", "entry_px", default=0),
            "usd_in":   _get_field(entry, "usd_size", "usd_in", default=0),
            "rank_60s": features.get("rank_60s", ""),
        })

    return closed, open_list

# ── Coinbase portfolio ────────────────────────────────────────────────────────

_cb_cache: dict[str, Any] = {"ts": 0, "data": None}

def get_portfolio() -> dict:
    now = time.monotonic()
    if now - _cb_cache["ts"] < 60 and _cb_cache["data"]:
        return _cb_cache["data"]
    try:
        from dotenv import dotenv_values
        from coinbase.rest import RESTClient
        cfg    = dotenv_values(ENV_FILE)
        client = RESTClient(api_key=cfg["CB_API_KEY"], api_secret=cfg["CB_API_SECRET"])

        cash = 0.0
        coin_accts: list[dict] = []
        SKIP_COINS = {"CLV", "NU", "WBTC", "CBETH"}

        for a in client.get_accounts(limit=250).accounts:
            avail = float(a.available_balance["value"])
            held  = float(a.hold["value"]) if isinstance(a.hold, dict) else 0.0
            total = avail + held
            if total < 0.001:
                continue
            if a.currency in ("USD", "USDC", "USDT"):
                cash += total
            elif a.currency not in SKIP_COINS:
                coin_accts.append({"coin": a.currency, "qty": total, "avail": avail})

        prices: dict[str, float] = {}
        if coin_accts:
            try:
                ba = client.get_best_bid_ask(product_ids=[f"{c['coin']}-USD" for c in coin_accts])
                for pb in ba.pricebooks:
                    coin = pb.product_id.replace("-USD", "")
                    prices[coin] = (float(pb.bids[0].price) + float(pb.asks[0].price)) / 2
            except Exception:
                pass

        holdings = []
        for c in coin_accts:
            px = prices.get(c["coin"], 0)
            val = c["qty"] * px
            if val > 0.05:
                holdings.append({
                    "coin":  c["coin"],
                    "qty":   c["qty"],
                    "price": round(px, 6),
                    "value": round(val, 2),
                })
        holdings.sort(key=lambda x: x["value"], reverse=True)

        orders = []
        try:
            for o in client.list_orders(order_status=["OPEN"], limit=50).orders:
                orders.append({
                    "product": o.product_id,
                    "side":    o.side,
                    "id":      o.order_id[:12],
                })
        except Exception:
            pass

        data = {
            "cash":     round(cash, 2),
            "holdings": holdings,
            "total":    round(cash + sum(h["value"] for h in holdings), 2),
            "orders":   orders,
        }
    except Exception as exc:
        data = {"cash": 0, "holdings": [], "total": 0, "orders": [], "error": str(exc)}

    _cb_cache["ts"] = now
    _cb_cache["data"] = data
    return data

# ── Log parsing ───────────────────────────────────────────────────────────────

def parse_log():
    raw = grep_file(RECORDER_LOG,
        r'\[SKIP\]|\[SIG-QUEUED\]|\[ENTRY\]|\[EXIT\]|\[stats\]',
        "filter_log", ttl=12, tail=600,
    )

    skip_counts: dict[str, int] = {}
    recent_events: list[dict]   = []
    stats_line: str = ""

    for line in raw.strip().splitlines():
        if "[SKIP]" in line:
            parts = line.split("[SKIP]", 1)
            rest  = parts[1].strip() if len(parts) > 1 else ""
            tokens = rest.split(None, 1)
            reason = tokens[1].strip() if len(tokens) > 1 else rest
            # Bucket by first keyword
            key = reason.split("=")[0].split()[0] if reason else "unknown"
            skip_counts[key] = skip_counts.get(key, 0) + 1
            recent_events.append({"type": "SKIP", "text": rest[:80]})

        elif "[SIG-QUEUED]" in line:
            text = line.split("[SIG-QUEUED]", 1)[-1].strip()
            recent_events.append({"type": "SIGNAL", "text": text[:80]})

        elif "[ENTRY]" in line:
            text = line.split("[ENTRY]", 1)[-1].strip()
            recent_events.append({"type": "ENTRY", "text": text[:80]})

        elif "[EXIT]" in line:
            text = line.split("[EXIT]", 1)[-1].strip()
            recent_events.append({"type": "EXIT", "text": text[:80]})

        elif "[stats]" in line:
            stats_line = line.split("[stats]", 1)[-1].strip()

    return skip_counts, recent_events[-120:], stats_line

# ── API routes ────────────────────────────────────────────────────────────────

@app.get("/")
def serve_dashboard():
    return FileResponse(str(TEMPLATES_DIR / "command_center_v3.html"))


@app.get("/api/trades")
def api_trades():
    closed, open_pos = parse_live_trades()

    completed = [t for t in closed if t["usd_in"] > 0]
    wins      = [t for t in completed if t["win"]]

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today     = [t for t in completed if t["exit_ts"].startswith(today_str)]

    since_deploy = [t for t in completed if t["exit_ts"] >= DEPLOY_TS]
    sd_wins      = [t for t in since_deploy if t["win"]]

    r7 = [t for t in completed if "R7" in t["variant"]]
    r5 = [t for t in completed if "R5" in t["variant"]]

    def variant_stats(subset):
        w = [t for t in subset if t["win"]]
        return {
            "n":    len(subset),
            "wins": len(w),
            "wr":   round(len(w) / max(len(subset), 1) * 100, 1),
            "pnl":  round(sum(t["pnl_usd"] for t in subset), 2),
            "avg":  round(sum(t["gain"] for t in subset) / max(len(subset), 1) * 100, 2),
        }

    return {
        "closed":  list(reversed(completed))[:60],   # most-recent first for table
        "open":    open_pos,
        "chart":   [
            {"ts": t["exit_ts"], "pnl": t["pnl_usd"], "cum": t["cum_pnl"],
             "coin": t["coin"], "variant": t["variant"], "win": t["win"]}
            for t in completed
        ],
        "stats": {
            "total":           len(completed),
            "wins":            len(wins),
            "losses":          len(completed) - len(wins),
            "win_rate":        round(len(wins) / max(len(completed), 1) * 100, 1),
            "total_pnl":       round(sum(t["pnl_usd"] for t in completed), 2),
            "avg_pnl":         round(sum(t["pnl_usd"] for t in completed) / max(len(completed), 1), 2),
            "avg_pct":         round(sum(t["gain"] for t in completed) / max(len(completed), 1) * 100, 2),
            "today_n":         len(today),
            "today_pnl":       round(sum(t["pnl_usd"] for t in today), 2),
            "deploy_n":        len(since_deploy),
            "deploy_wins":     len(sd_wins),
            "deploy_wr":       round(len(sd_wins) / max(len(since_deploy), 1) * 100, 1),
            "deploy_pnl":      round(sum(t["pnl_usd"] for t in since_deploy), 2),
            "r7":              variant_stats(r7),
            "r5":              variant_stats(r5),
        },
    }


@app.get("/api/portfolio")
def api_portfolio():
    return get_portfolio()


@app.get("/api/log")
def api_log():
    skip_counts, events, stats_line = parse_log()
    return {
        "skip_counts": skip_counts,
        "events":      events,
        "stats_line":  stats_line,
    }


@app.get("/api/heartbeat")
def api_heartbeat():
    raw = read_file(HEARTBEAT, "heartbeat", ttl=12)
    try:
        hb = json.loads(raw)
    except Exception:
        hb = {}

    svc = run_remote("systemctl is-active cb_recorder.service", "svc_status", ttl=20)
    hb["service_active"] = svc.strip() == "active"
    hb["service_status"] = svc.strip()
    return hb


@app.get("/api/restart-service")
def api_restart_service():
    try:
        if LOCAL:
            r = subprocess.run(
                ["sudo", "systemctl", "restart", "cb_recorder.service"],
                capture_output=True, text=True, timeout=25,
            )
            ok = r.returncode == 0
            out = (r.stdout + r.stderr).strip() or "OK"
        else:
            r = subprocess.run(
                ["ssh", "-i", EC2_KEY, "-o", "StrictHostKeyChecking=no",
                 "-o", "ConnectTimeout=5", EC2_HOST,
                 "sudo systemctl restart cb_recorder.service && echo OK"],
                capture_output=True, text=True, timeout=25,
            )
            ok = "OK" in r.stdout
            out = (r.stdout + r.stderr).strip()
        for k in list(_cache):
            del _cache[k]
        return {"status": "restarted" if ok else "error", "output": out}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@app.get("/api/cancel-orders")
def api_cancel_orders():
    try:
        from dotenv import dotenv_values
        from coinbase.rest import RESTClient
        cfg    = dotenv_values(ENV_FILE)
        client = RESTClient(api_key=cfg["CB_API_KEY"], api_secret=cfg["CB_API_SECRET"])
        orders = client.list_orders(order_status=["OPEN"], limit=100)
        ids    = [o.order_id for o in orders.orders]
        if ids:
            client.cancel_orders(order_ids=ids)
            _cb_cache["ts"] = 0  # force portfolio refresh
            return {"cancelled": len(ids)}
        return {"cancelled": 0}
    except Exception as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    print("=" * 55)
    print("  BOTTY Command Center — Phase 3 Precision Filter")
    print("  http://localhost:8003")
    print("=" * 55)
    uvicorn.run(app, host="0.0.0.0", port=8003, log_level="warning")
