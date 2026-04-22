"""
╔══════════════════════════════════════════════════════════════════╗
║         BOTTY — CLAUDE CODE WORKER  v2.0                     ║
║                                                                  ║
║  The bridge between the neural bot and Claude Code's            ║
║  reasoning engine. Runs as a parallel process alongside         ║
║  nkn_bot.py, communicating via shared SQLite + JSON files.      ║
║                                                                  ║
║  LAYERS:                                                         ║
║    FAST  (every 5 bot cycles ~4min) → Tactical overlay          ║
║    MED   (every 30min)             → Regime narration           ║
║    SLOW  (every 6h)                → Strategy drift check       ║
║    NIGHT (00:00 UTC daily)         → Full post-mortem + rewrite ║
║    EVENT (triggered)               → Catalyst / anomaly resp.   ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import json
import time
import sqlite3
import logging
import subprocess
import threading
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# ─── Paths (shared with nkn_bot.py) ──────────
BRAIN_DB        = "nkn_brain.db"
BOT_DB          = "nkn_trades.db"
OVERLAY_FILE    = "claude_overlay.json"      # bot reads this each cycle
CONFIG_LIVE     = "config_live.json"         # bot reads for live config overrides
POSTMORTEM_FILE = "postmortem_latest.json"

# System Auditor — replaces stripped layers 1-7
AUDIT_INTERVAL_SEC = 30 * 60  # 30 minutes   # nightly analysis result
CATALYST_FILE   = "catalyst_alert.json"      # breaking event alerts
WORKER_LOG      = "worker.log"
WORKER_STATE    = "worker_state.json"        # last run timestamps

# ─── Timing ───────────────────────────────────
TACTICAL_INTERVAL_SEC   = 60 * 60       # 1 hour — bot scanner handles real-time; Claude gives strategic overlay
REGIME_INTERVAL_SEC     = 4 * 60 * 60   # 4 hours — regime shifts don't happen every 30 min
DRIFT_INTERVAL_SEC      = 6 * 60 * 60  # 6 hours
HYPOTHESIS_GEN_SEC      = 2 * 60 * 60   # 2 hours — quality over quantity (was 5min, 61% of all calls)
THEORY_ANALYSIS_SEC     = 30 * 60       # 30 minutes — analyze breakout snapshots
HYPOTHESIS_REVIEW_SEC   = 6 * 60 * 60  # 6 hours — only review after meaningful trade data accumulates
POSTMORTEM_UTC_HOUR     = 0             # midnight UTC
CLAUDE_TIMEOUT_SEC      = 300

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WORKER] %(message)s",
    handlers=[
        logging.FileHandler(WORKER_LOG),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("Worker")


# ══════════════════════════════════════════════
# CLAUDE CODE SUBPROCESS CALLER
# ══════════════════════════════════════════════

class ClaudeCodeBridge:
    """
    Calls Claude Code via subprocess exactly like StudySnob worker.py.
    Uses CLAUDE_CODE_OAUTH_TOKEN env var — no API key needed.
    """

    def __init__(self):
        self.call_count   = 0
        self.success_count = 0
        self.fail_count   = 0
        self.avg_latency  = 0.0
        self._lock        = threading.Lock()

    def call(self, prompt: str, context_label: str = "unnamed") -> Optional[dict]:
        """
        Send prompt to Claude Code, return parsed JSON response.
        Claude Code is always instructed to return pure JSON.
        """
        with self._lock:
            self.call_count += 1

        t0 = time.time()
        try:
            # Run from minimal directory to avoid Claude scanning 900KB of project files
            result = subprocess.run(
                ["claude", "-p", "--dangerously-skip-permissions"],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=CLAUDE_TIMEOUT_SEC,
                cwd="/home/ec2-user/claude_worker",
                env={**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": os.getenv("CLAUDE_CODE_OAUTH_TOKEN", "")}
            )

            latency = time.time() - t0
            self._update_latency(latency)

            if result.returncode != 0:
                log.warning(f"[{context_label}] Claude Code stderr: {result.stderr[:200]}")

            raw = result.stdout.strip()
            if not raw:
                log.warning(f"[{context_label}] Empty response from Claude Code")
                self.fail_count += 1
                return None

            # Extract JSON from Claude's response — it may be wrapped in text/markdown
            parsed = self._extract_json(raw)
            if parsed is not None:
                self.success_count += 1
                log.info(f"[{context_label}] ✓ Claude Code responded in {latency:.1f}s")
                return parsed
            else:
                log.error(f"[{context_label}] No JSON found in response | raw: {raw[:300]}")
                self.fail_count += 1
                return None

        except subprocess.TimeoutExpired:
            log.error(f"[{context_label}] Claude Code timeout after {CLAUDE_TIMEOUT_SEC}s")
            self.fail_count += 1
            return None
        except Exception as e:
            log.error(f"[{context_label}] Bridge error: {e}")
            self.fail_count += 1
            return None

    @staticmethod
    def _extract_json(text: str):
        """Extract JSON object or array from text that may contain markdown/prose."""
        import re

        # Try 1: raw text is valid JSON
        try:
            return json.loads(text)
        except: pass

        # Try 2: JSON inside ```json ... ``` fences
        fence_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', text)
        if fence_match:
            try:
                return json.loads(fence_match.group(1).strip())
            except: pass

        # Try 3: Find first { or [ and extract to matching } or ]
        for start_char, end_char in [('{', '}'), ('[', ']')]:
            start = text.find(start_char)
            if start == -1:
                continue
            # Find matching close by counting braces
            depth = 0
            for i in range(start, len(text)):
                if text[i] == start_char:
                    depth += 1
                elif text[i] == end_char:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i+1])
                        except:
                            break

        return None

    def _update_latency(self, latency: float):
        n = self.call_count
        self.avg_latency = ((self.avg_latency * (n - 1)) + latency) / n

    def health(self) -> dict:
        success_rate = self.success_count / max(self.call_count, 1)
        return {
            "calls": self.call_count,
            "success_rate": round(success_rate, 3),
            "avg_latency_sec": round(self.avg_latency, 1),
            "failures": self.fail_count
        }


# ══════════════════════════════════════════════
# DATABASE READER
# ══════════════════════════════════════════════

class DataReader:
    """Reads live state from both SQLite databases."""

    def __init__(self, purge_poison: bool = False):
        # Destructive cleanup moved behind an explicit flag — never run on construction.
        # Call reader.purge_poisoned_episodes() explicitly if needed.
        if purge_poison:
            self.purge_poisoned_episodes()

    def purge_poisoned_episodes(self) -> int:
        """Delete pre-bot liquidation rows that skew regime PnL. Call explicitly."""
        try:
            conn = sqlite3.connect(BRAIN_DB)
            deleted = conn.execute("DELETE FROM episodes WHERE net_pnl < -50").rowcount
            conn.commit()
            conn.close()
            if deleted:
                log.info(f"[DataReader] Purged {deleted} poisoned episodes (net_pnl < -50)")
            return deleted
        except Exception:
            return 0

    def get_recent_episodes(self, n: int = 20) -> list:
        try:
            conn = sqlite3.connect(BRAIN_DB)
            rows = conn.execute("""
                SELECT episode_id, side, entry_price, exit_price, entry_size,
                       net_pnl, fees_paid, hold_sec, action, confidence,
                       reward, regime_entry, win, entry_time, exit_time
                FROM episodes
                WHERE exit_time != '' AND net_pnl > -50
                ORDER BY exit_time DESC LIMIT ?
            """, (n,)).fetchall()
            conn.close()
            return [dict(zip(
                ["id","side","entry","exit","size","net_pnl","fees",
                 "hold_sec","action","confidence","reward","regime","win",
                 "entry_time","exit_time"], r
            )) for r in rows]
        except Exception as e:
            log.warning(f"DB read error: {e}")
            return []

    def get_pnl_summary(self) -> dict:
        try:
            conn  = sqlite3.connect(BOT_DB)
            rows  = conn.execute("""
                SELECT realized, unrealized, fees_total, inventory, mode
                FROM pnl_events ORDER BY id DESC LIMIT 1
            """).fetchone()
            conn.close()
            if not rows:
                return {}
            return {
                "realized": rows[0], "unrealized": rows[1],
                "fees": rows[2], "inventory_nkn": rows[3], "mode": rows[4]
            }
        except Exception:
            return {}

    def get_training_progress(self) -> dict:
        try:
            conn = sqlite3.connect(BRAIN_DB)
            row  = conn.execute("""
                SELECT epoch, loss, actor_loss, critic_loss, entropy
                FROM training_log ORDER BY id DESC LIMIT 1
            """).fetchone()
            recent = conn.execute("""
                SELECT AVG(loss), MIN(loss), MAX(loss)
                FROM training_log WHERE id > (SELECT MAX(id) - 50 FROM training_log)
            """).fetchone()
            conn.close()
            return {
                "latest_epoch":  row[0] if row else 0,
                "latest_loss":   round(row[1], 6) if row else None,
                "avg_loss_50":   round(recent[0], 6) if recent and recent[0] else None,
                "min_loss_50":   round(recent[1], 6) if recent and recent[1] else None,
            }
        except Exception:
            return {}

    def get_regime_pnl_table(self) -> list:
        """Read regime-level performance from brain DB.
        Excludes pre-bot liquidation trades (net_pnl < -50) to avoid poisoned data."""
        try:
            conn  = sqlite3.connect(BRAIN_DB)
            rows  = conn.execute("""
                SELECT regime_entry, COUNT(*), AVG(net_pnl), SUM(net_pnl),
                       SUM(CASE WHEN win=1 THEN 1 ELSE 0 END) * 1.0 / COUNT(*)
                FROM episodes
                WHERE exit_time != '' AND regime_entry >= 0 AND net_pnl > -50
                GROUP BY regime_entry
            """).fetchall()
            conn.close()
            return [{"regime": r[0], "n": r[1], "avg_pnl": round(r[2],6),
                     "total_pnl": round(r[3],4), "win_rate": round(r[4],3)}
                    for r in rows]
        except Exception:
            return []

    def get_all_episodes_today(self) -> list:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            conn = sqlite3.connect(BRAIN_DB)
            rows = conn.execute("""
                SELECT * FROM episodes
                WHERE exit_time LIKE ? AND exit_time != '' AND net_pnl > -50
                ORDER BY exit_time
            """, (f"{today}%",)).fetchall()
            cols = [d[0] for d in conn.execute("PRAGMA table_info(episodes)").fetchall()]
            conn.close()
            return [dict(zip(cols, r)) for r in rows]
        except Exception:
            return []

    def get_config_live(self) -> dict:
        try:
            with open(CONFIG_LIVE) as f:
                return json.load(f)
        except Exception:
            return {}


# ══════════════════════════════════════════════
# PROMPT LIBRARY
# ══════════════════════════════════════════════

class PromptLibrary:
    """
    All Claude Code prompts. Each returns pure JSON.
    Written to extract maximum signal from Claude's reasoning.
    """

    SYSTEM_IDENTITY = """
You are APEX — the AI trading strategist for BOTTY, an autonomous multi-coin
crypto trading system on Coinbase with ONE OVERRIDING GOAL: reach $100,000 in
profit as quickly as possible while protecting capital.

Current portfolio: ~$7,100 across 14 altcoins + USD cash. Starting capital: $6,700.
The bot scans 385 USD pairs every 5 minutes using Hurst exponent, variance ratio,
momentum detection, Fear & Greed index, order book analysis, and CoinGecko trending.
It uses multiple strategies: mean-reversion entries, momentum captures, breakout
detection, and trailing stop protection.

THE $100K GOAL SHAPES EVERY DECISION:
- Winning trades and capturing momentum is the fastest path to $100K
- Protecting downside prevents setbacks that extend the timeline
- Idle cash earning nothing is the enemy — deploy it on the best opportunities
- Every cycle matters — urgency without recklessness

You think like a prop trader with a clear P&L target:
- You identify asymmetries before they close
- You recognize regime shifts before indicators confirm them
- You favor ACTION over waiting when edge exists
- Capital preservation enables compounding — but sitting in cash doesn't compound
- You evaluate the ENTIRE portfolio, not any single coin

CONSTITUTION (governs all decisions):
- THE #1 PRIORITY: Find and exploit 30-60% runners on sub-$0.05 micro-cap coins.
  This is the PROVEN path to $100K. Evidence:
  - FIDA: +47% ($120 profit on $250 position)
  - RLS: +73% (missed because we sold too early)
  - BTRST: +12% (captured with trailing stop)
  Pattern: sub-$0.05 coin + extreme fear + volume + mean-reverting → buy and HOLD.
  These coins dip 3-5% before running 30-60%. DO NOT sell on small dips.
  Double down on dips to increase position before the run.
- 158 sub-$0.05 coins with volume exist on Coinbase. This is our hunting ground.
- Kelly: 18% per trade. Scale to 30% on DOMINANT-tier proven runners.
- Max 30% portfolio per position. Halt if portfolio < $5,000.
- Hypothesis engine generates and tests strategies. Winners get scaled.
- This system's only goal is to reach $100,000 as quickly as possible
  without taking any action that would prevent it from continuing to try.

CRITICAL: Respond ONLY with valid JSON. No preamble. No explanation outside the JSON.
No markdown. No code fences. Raw JSON only. Your JSON will be parsed by machine.

"""

    SHORT_IDENTITY = (
        "You are APEX, the AI strategist for BOTTY (autonomous crypto bot on Coinbase). "
        "Goal: reach 100K from 6700 starting capital. Strategy: catch 30-60 pct runners on sub-0.05 micro-caps. "
        "CRITICAL: Respond ONLY with valid JSON. No preamble, no markdown, no code fences."
    )

    @staticmethod
    def tactical_overlay(ind: dict, bot_state: dict, recent_episodes: list,
                         regime_table: list, training: dict) -> str:
        return f"""
{PromptLibrary.SHORT_IDENTITY}

TASK: TACTICAL_OVERLAY — assess current market and issue trading guidance.

CURRENT MARKET STATE:
{json.dumps(ind, indent=2)}

BOT STATE:
{json.dumps(bot_state, indent=2)}

LAST 10 COMPLETED TRADES:
{json.dumps(recent_episodes[-10:], indent=2)}

REGIME PERFORMANCE TABLE:
{json.dumps(regime_table, indent=2)}

NEURAL NETWORK STATUS:
{json.dumps(training, indent=2)}

ANALYSIS REQUIRED:
1. Is the current market setup favorable for the grid strategy?
2. Do you see any asymmetry (order book, volume, momentum) the neural net might be missing?
3. Is there any pattern in the last 10 trades suggesting the bot is drifting or repeating a mistake?
4. Should the bot's current mode change?

Respond with this exact JSON schema:
{{
  "action_override": null,
  "action_override_reason": null,
  "confidence": 0.0,
  "size_adjustment": 1.0,
  "risk_flag": null,
  "risk_flag_severity": null,
  "asymmetry_detected": false,
  "asymmetry_direction": null,
  "asymmetry_description": null,
  "market_read": "",
  "neural_net_assessment": "",
  "halt_recommended": false,
  "halt_reason": null,
  "recommended_coins": [],
  "valid_until_cycles": 5,
  "apex_confidence_in_this_call": 0.0
}}

FIELD RULES:
- action_override: null | "STRONG_BUY" | "BUY" | "HOLD" | "SELL" | "STRONG_SELL"
- confidence: 0.0-1.0, your confidence in the action_override (0.5 = uncertain)
- size_adjustment: multiplier on normal order size (0.5 = half size, 1.5 = 50% larger)
- risk_flag: null or short string describing the specific risk
- risk_flag_severity: null | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
- asymmetry_detected: true if you see an exploitable edge
- market_read: 1-2 sentence assessment of current market structure
- recommended_coins: when action_override is BUY/STRONG_BUY, list up to 3 coin symbols to buy (e.g. ["APE", "DOGE"]). These must be coins NOT currently held.
- valid_until_cycles: how many bot cycles this guidance stays valid (1-10)
- apex_confidence_in_this_call: your meta-confidence in your own analysis (honest)
"""

    @staticmethod
    def regime_narration(regime_table: list, recent_episodes: list,
                         current_ind: dict, pnl_summary: dict) -> str:
        return f"""
{PromptLibrary.SHORT_IDENTITY}

TASK: REGIME_NARRATION — interpret what market regime we are in and what it means strategically.

CURRENT INDICATORS:
{json.dumps(current_ind, indent=2)}

REGIME PERFORMANCE (from neural classifier):
{json.dumps(regime_table, indent=2)}

RECENT TRADE SAMPLE (last 20):
{json.dumps(recent_episodes, indent=2)}

P&L SUMMARY:
{json.dumps(pnl_summary, indent=2)}

ANALYSIS REQUIRED:
1. Based on indicators, which named regime does this resemble? (ranging, trending_bull, trending_bear, volatile_breakout, low_liquidity, squeeze_coiling)
2. What is the historical edge in this regime based on the performance table?
3. What specific grid/momentum adjustments does this regime call for?
4. Is the bot currently fighting the regime or aligned with it?
5. What is the single highest-value change to make RIGHT NOW given this regime?

{{
  "regime_human_label": "",
  "regime_confidence": 0.0,
  "regime_historical_edge": "",
  "regime_avg_pnl_per_trade": 0.0,
  "regime_recommended_strategy": "",
  "bot_regime_alignment": "",
  "highest_value_change": "",
  "grid_spacing_suggestion": null,
  "buy_levels_suggestion": null,
  "sell_levels_suggestion": null,
  "hold_time_suggestion_sec": null,
  "avoid_until": null
}}
"""

    @staticmethod
    def strategy_drift_check(all_episodes_week: list, training_history: dict,
                              config_live: dict, pnl_curve: list) -> str:
        return f"""
{PromptLibrary.SYSTEM_IDENTITY}

TASK: STRATEGY_DRIFT_CHECK — detect if the bot has drifted from its optimal behavior.

This is a 6-hour strategic audit. You are looking for:
- Overfitting to recent market conditions that won't persist
- Systematic biases developing in the trade history
- Config parameters that have become misaligned with actual market behavior
- Signs the neural net is converging on a suboptimal local minimum
- Capital efficiency decay (same risk, less reward)

WEEK'S TRADE EPISODES ({len(all_episodes_week)} trades):
{json.dumps(all_episodes_week[-50:], indent=2)}

NEURAL TRAINING HISTORY:
{json.dumps(training_history, indent=2)}

CURRENT LIVE CONFIG:
{json.dumps(config_live, indent=2)}

P&L CURVE (last 50 snapshots):
{json.dumps(pnl_curve, indent=2)}

{{
  "drift_detected": false,
  "drift_type": null,
  "drift_description": null,
  "drift_severity": null,
  "config_mutations": {{}},
  "config_mutation_reasoning": {{}},
  "neural_net_concern": null,
  "capital_efficiency_score": 0.0,
  "capital_efficiency_trend": "",
  "recommended_actions": [],
  "do_not_change": [],
  "overall_strategy_health": "",
  "health_score": 0.0
}}

FIELD RULES:
- config_mutations: dict of config keys → new recommended values ONLY if change is justified
- config_mutation_reasoning: dict of same keys → 1-sentence justification for each change
- capital_efficiency_score: 0.0-1.0 (1.0 = extracting maximum value per risk unit)
- health_score: 0.0-1.0 (1.0 = bot firing on all cylinders)
- do_not_change: list of config keys that are working well and should NOT be touched
"""

    @staticmethod
    def nightly_postmortem(today_episodes: list, pnl_summary: dict,
                           regime_table: list, training: dict,
                           config_live: dict, yesterday_postmortem: dict) -> str:
        wins   = [e for e in today_episodes if e.get("win")]
        losses = [e for e in today_episodes if not e.get("win")]

        return f"""
{PromptLibrary.SYSTEM_IDENTITY}

TASK: NIGHTLY_POSTMORTEM — full day analysis and tomorrow's strategic mandate.

This is the most important call of the day. Be ruthlessly honest.
The bot's ability to compound depends on accurate self-assessment.

TODAY'S SUMMARY:
- Total trades: {len(today_episodes)}
- Wins: {len(wins)} | Losses: {len(losses)}
- Win rate: {len(wins)/max(len(today_episodes),1):.1%}

WINNING TRADES:
{json.dumps(wins[:15], indent=2)}

LOSING TRADES:
{json.dumps(losses[:15], indent=2)}

OVERALL P&L:
{json.dumps(pnl_summary, indent=2)}

REGIME PERFORMANCE:
{json.dumps(regime_table, indent=2)}

NEURAL NETWORK TRAINING:
{json.dumps(training, indent=2)}

CURRENT CONFIG:
{json.dumps(config_live, indent=2)}

YESTERDAY'S POSTMORTEM (for continuity):
{json.dumps(yesterday_postmortem, indent=2)}

DELIVER:
1. Brutal honest assessment of today's performance
2. The 3 most important things the bot did RIGHT today
3. The 3 most important things the bot did WRONG today (be specific — which trades, which patterns)
4. What the neural net is learning correctly vs. what it's learning incorrectly
5. Tomorrow's strategic mandate — exactly what to prioritize
6. Any config changes needed NOW before tomorrow's session

{{
  "date": "",
  "performance_grade": "",
  "performance_narrative": "",
  "things_done_right": [],
  "things_done_wrong": [],
  "worst_trade_analysis": "",
  "best_trade_analysis": "",
  "neural_net_learning_correctly": [],
  "neural_net_learning_incorrectly": [],
  "neural_net_recommendation": "",
  "tomorrows_mandate": "",
  "tomorrows_priority_action": "",
  "tomorrows_avoid": "",
  "immediate_config_changes": {{}},
  "immediate_config_reasoning": {{}},
  "capital_governor_assessment": "",
  "compounding_trajectory": "",
  "days_to_target_at_current_pace": null,
  "biggest_risk_tomorrow": "",
  "apex_message_to_bot": ""
}}

FIELD RULES:
- performance_grade: "A" through "F"
- days_to_target_at_current_pace: integer estimate to reach $100k from current, null if unclear
- apex_message_to_bot: a direct message to the neural network — what should it prioritize learning
  in tomorrow's training batches? This gets injected as a meta-learning signal.
"""

    @staticmethod
    def catalyst_assessment(event_description: str, current_state: dict,
                             open_positions: dict) -> str:
        return f"""
{PromptLibrary.SYSTEM_IDENTITY}

TASK: CATALYST_ASSESSMENT — rapid response to a potential market-moving event.

An external event has been detected that may affect the portfolio.
Assess immediately and issue an action directive.

EVENT DETECTED:
{event_description}

CURRENT BOT STATE:
{json.dumps(current_state, indent=2)}

OPEN POSITIONS:
{json.dumps(open_positions, indent=2)}

ASSESS:
1. Is this event likely to move our held coins? In which direction and magnitude?
2. Is this event genuine signal or noise/manipulation?
3. What should the bot do in the next 3 cycles specifically?
4. Is there an asymmetry to capture or a risk to avoid?

{{
  "event_significance": "",
  "event_genuine": true,
  "expected_price_direction": null,
  "expected_magnitude_pct": null,
  "confidence_in_assessment": 0.0,
  "time_horizon_minutes": null,
  "immediate_action": "",
  "action_directive": null,
  "size_directive": 1.0,
  "cancel_open_orders": false,
  "halt_new_orders": false,
  "halt_duration_cycles": 0,
  "risk_assessment": "",
  "opportunity_assessment": "",
  "apex_urgency": ""
}}
"""

    @staticmethod
    def asymmetry_deep_dive(order_book_history: list, volume_history: list,
                             price_history: list, recent_fills: list) -> str:
        return f"""
{PromptLibrary.SHORT_IDENTITY}

TASK: ASYMMETRY_DEEP_DIVE — find exploitable edges in market microstructure.

You are looking for patterns that repeat, that the neural net may have partially learned
but cannot articulate. Your job is to find the signal and name it precisely so it can
be encoded as a feature or a rule.

ORDER BOOK SNAPSHOTS (last 10, 4min apart):
{json.dumps(order_book_history, indent=2)}

VOLUME BY PERIOD:
{json.dumps(volume_history, indent=2)}

PRICE ACTION (last 40 candles):
{json.dumps(price_history, indent=2)}

RECENT FILLS (what actually executed):
{json.dumps(recent_fills, indent=2)}

FIND:
1. Any recurring order book pattern (walls appearing/disappearing, spoofing, absorption)
2. Volume asymmetry between buy/sell pressure
3. Time-of-day effects visible in the data
4. Price levels that act as consistent support/resistance (not just technical, but order-flow-confirmed)
5. Any pattern in WHICH trades are winning vs losing — is there a microstructure predictor?

{{
  "asymmetries_found": [],
  "strongest_asymmetry": null,
  "strongest_asymmetry_edge_estimate": 0.0,
  "recurring_order_book_pattern": null,
  "volume_bias": null,
  "time_of_day_effect": null,
  "key_price_levels": [],
  "fill_quality_assessment": "",
  "suggested_new_feature": null,
  "suggested_new_rule": null,
  "confidence_in_findings": 0.0
}}

FIELD RULES:
- asymmetries_found: list of strings, each describing one specific edge
- strongest_asymmetry_edge_estimate: estimated win rate improvement (e.g. 0.05 = 5% better)
- suggested_new_feature: a new input feature for the neural net (describe mathematically)
- suggested_new_rule: a hard rule to add to the bot config based on what you found
"""

    @staticmethod
    def confidence_calibration(predictions: list, outcomes: list,
                               training: dict) -> str:
        """
        Feed the brain's historical confidence scores vs actual outcomes.
        Ask Claude to identify where the model is overconfident or underconfident.
        """
        calibration_data = []
        for p, o in zip(predictions[-50:], outcomes[-50:]):
            calibration_data.append({
                "predicted_action": p.get("action"),
                "confidence": p.get("confidence"),
                "actual_pnl": o.get("net_pnl"),
                "win": o.get("win")
            })

        return f"""
{PromptLibrary.SHORT_IDENTITY}

TASK: CONFIDENCE_CALIBRATION — diagnose the neural net's confidence accuracy.

A well-calibrated model should be right ~80% of the time when confidence is 0.8,
~60% when confidence is 0.6, etc. Miscalibration = the model is lying to itself.

CONFIDENCE vs OUTCOME DATA (last 50 trades):
{json.dumps(calibration_data, indent=2)}

TRAINING METRICS:
{json.dumps(training, indent=2)}

FIND:
1. Is the model overconfident (high confidence, wrong often)?
2. Is it underconfident (low confidence, right often)?
3. At what confidence threshold does the model become reliably correct?
4. Should the CONFIDENCE_FLOOR in the bot config be adjusted?
5. Is there a specific ACTION type where confidence is miscalibrated?

{{
  "calibration_quality": "",
  "overconfident": false,
  "underconfident": false,
  "reliable_threshold": 0.0,
  "confidence_floor_recommendation": 0.52,
  "action_miscalibration": {{}},
  "calibration_curve": [],
  "calibration_narrative": "",
  "entropy_assessment": "",
  "recommended_entropy_coeff": 0.01
}}
"""

    @staticmethod
    def meta_learning_injection(postmortem: dict, training: dict,
                                regime_table: list) -> str:
        """
        Creates a synthetic training signal — tells the neural net
        WHAT to learn, not just showing it raw experience.
        """
        return f"""
{PromptLibrary.SYSTEM_IDENTITY}

TASK: META_LEARNING_INJECTION — generate synthetic training examples to accelerate learning.

The neural net learns from real trade experience. But real experience is slow.
You will generate HIGH-QUALITY synthetic state→action→reward examples based on
your understanding of optimal trading behavior. These synthetic examples will be
injected into the experience replay buffer to guide the network faster.

CURRENT POSTMORTEM FINDINGS:
{json.dumps(postmortem, indent=2)}

TRAINING STATUS:
{json.dumps(training, indent=2)}

REGIME ANALYSIS:
{json.dumps(regime_table, indent=2)}

Generate 10 synthetic training examples. Each should represent a market situation
and the CORRECT action + reward the network should learn. Focus on:
- Situations the bot is currently getting wrong (from postmortem)
- High-value situations it's not recognizing (from asymmetry analysis)
- Regime-specific optimal behavior

{{
  "synthetic_examples": [
    {{
      "description": "",
      "key_features": {{
        "rsi": 0.0,
        "adx": 0.0,
        "volume_ratio": 0.0,
        "book_imbalance": 0.0,
        "boll_position": 0.0,
        "price_vs_ema50": 0.0,
        "inventory_ratio": 0.0,
        "macd_cross": 0.0,
        "regime": 0
      }},
      "correct_action": "",
      "correct_reward": 0.0,
      "size_multiplier": 1.0,
      "learning_objective": ""
    }}
  ],
  "injection_priority": "",
  "expected_improvement": ""
}}
"""


# ══════════════════════════════════════════════
# OVERLAY WRITER
# ══════════════════════════════════════════════

def write_overlay(data: dict, filepath: str = OVERLAY_FILE):
    """Write Claude's decision to shared file. Bot reads this each cycle."""
    data["written_at"]    = datetime.now(timezone.utc).isoformat()
    data["expires_cycle"] = data.get("valid_until_cycles", 5)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    log.info(f"Overlay written → {filepath}")


def write_config_mutations(mutations: dict, reasoning: dict):
    """Write config changes. Bot loads these on next cycle."""
    if not mutations:
        return
    existing = {}
    try:
        with open(CONFIG_LIVE) as f:
            existing = json.load(f)
    except Exception:
        pass

    existing.update(mutations)
    existing["_mutations_at"]   = datetime.now(timezone.utc).isoformat()
    existing["_reasoning"]      = reasoning
    with open(CONFIG_LIVE, "w") as f:
        json.dump(existing, f, indent=2)
    log.info(f"Config mutations written: {list(mutations.keys())}")


def write_catalyst_alert(data: dict):
    data["alert_at"] = datetime.now(timezone.utc).isoformat()
    with open(CATALYST_FILE, "w") as f:
        json.dump(data, f, indent=2)
    log.info(f"Catalyst alert written: {data.get('event_significance','?')}")


def inject_synthetic_examples(examples: list):
    """
    Write synthetic training examples to a file.
    ml_brain.py checks for this file and injects into replay buffer.
    """
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "examples":   examples
    }
    with open("synthetic_training.json", "w") as f:
        json.dump(payload, f, indent=2)
    log.info(f"Injected {len(examples)} synthetic training examples")


# ══════════════════════════════════════════════
# HYPOTHESIS PROMPTS
# ══════════════════════════════════════════════

def build_hypothesis_gen_prompt(current_ind: dict, pnl_summary: dict,
                                 lessons: list, active_hyps: list,
                                 promoted: list, strategy_perf: list) -> str:
    # Build these outside f-string to avoid dict-in-f-string issues
    active_summary = json.dumps(
        [{"name": h.get("name","?"), "thesis": h.get("thesis",""), "trades": h.get("trades",0), "pnl": h.get("total_pnl",0)} for h in active_hyps],
        indent=2, default=str)
    promoted_summary = json.dumps(
        [{"name": p.get("name","?"), "conditions": p.get("conditions_json","")} for p in promoted],
        indent=2, default=str)
    return f"""
{PromptLibrary.SYSTEM_IDENTITY}

TASK: HYPOTHESIS_GENERATION — Create 1-3 NEW trading hypotheses to test with real money.

You are a trading scientist. Your job is to generate TESTABLE theories about what makes profitable trades.
Each hypothesis will be tested with $50-200 of real money. Winners get promoted to full strategies.
Winners AUTOMATICALLY spawn 6 mutant variants — your best hypotheses will breed and evolve.

CURRENT MARKET STATE:
{json.dumps(current_ind, indent=2, default=str)}

PORTFOLIO P&L:
{json.dumps(pnl_summary, indent=2, default=str)}

STRATEGY PERFORMANCE (what's working — momentum_capture has MASSIVE edge, mean_revert has NEGATIVE Kelly):
{json.dumps(strategy_perf, indent=2, default=str)}

LESSONS FROM KILLED HYPOTHESES (don't repeat these mistakes):
{json.dumps(lessons[-10:], indent=2, default=str)}

CURRENTLY ACTIVE EXPERIMENTS (don't duplicate):
{active_summary}

PROMOTED STRATEGIES (already working, build on these):
{promoted_summary}

AVAILABLE CONDITION KEYS (use these in conditions):
fear_greed (0-100), btc_price, btc_change_1h (-0.05 to 0.05),
hurst (0-1, <0.5=mean-reverting), scanner_score (0-1), momentum_score (0-1),
momentum_direction (-1/0/1), volatility, spread_pct, book_imbalance (-1 to 1),
hour_of_day (0-23), day_of_week (0-6), cash_pct (0-1), n_holdings,
global_win_rate, coin_price, volume_24h

CRITICAL RULES:
1. ONLY use these condition keys (NOTHING ELSE):
   MARKET: fear_greed, fear_greed_trend, fear_greed_capitulation,
           btc_change_1h, btc_dominance, mcap_change_24h,
           hour_of_day, day_of_week, funding_rate_avg
   COIN-LEVEL: hurst, scanner_score, momentum_score, momentum_direction,
               volatility, spread_pct, book_imbalance, coin_price, volume_24h,
               price_change_24h, volume_change_24h
   TECHNICAL: rsi, ema_cross, macd_histogram, bb_width, bb_position, vwap_distance
   SCANNER SUB-SCORES (each measures a DIFFERENT type of edge):
     hurst_score (0-1, higher=more mean-reverting),
     vr_score (0-1, higher=more predictable variance),
     acf_score (0-1, higher=stronger autocorrelation),
     vol_score (0-1, higher=more consistent volume),
     spread_score (0-1, higher=cheaper to trade),
     entropy_score (0-1, higher=more predictable),
     half_life (1-50 candles, lower=faster mean-reversion snap-back)
   TECHNICAL INDICATORS (calculated from 15-min candles):
     rsi (0-100, <30=oversold bounce opportunity, >70=overbought),
     ema_cross (-1/0/1, 1=bullish 9/21 EMA crossover),
     macd_histogram (-0.01 to 0.01, >0=bullish momentum),
     bb_width (0-0.5, narrow=squeeze/breakout imminent),
     bb_position (0-1, 0=at lower band, 1=at upper band),
     vwap_distance (-0.1 to 0.1, >0=above VWAP=bullish)
   REAL-TIME MOMENTUM:
     price_change_24h (%, >10=already running, >20=in full runner mode),
     volume_change_24h (%, >100=volume explosion, >500=massive interest)
   DO NOT use: coin_winrate, strategy_wr, unrealized_pnl_pct, n_holdings,
   cash_pct, global_win_rate, model_accuracy — these NEVER match.

2. Use 1-3 conditions MAX. Simpler = more matches = more data = faster learning.

3. Generate 3-5 hypotheses. PRIORITY: find 30-60% runners on sub-$0.05 coins.
   The proven pattern: micro-cap + fear + volume + momentum → hold through dips.
   Include: 2 micro-cap runner variants, 1 momentum, 1 fear-based, 1 contrarian.
4. Think about VELOCITY (profit per hour). One 40% runner = $200 on $500.
   Five runners per week = $1,000/week = path to $100K.
5. DO NOT kill any hypothesis with fewer than 5 completed trades.
6. Hypotheses on micro-caps should have HIGHER budgets ($150-250) — this is where the edge is.

Respond with ONLY this JSON array:
[
  {{
    "name": "short_descriptive_name",
    "thesis": "1-2 sentence theory about WHY this should work",
    "signal_type": "ENTRY",
    "conditions": {{
      "key": {{"op": "<", "val": 25}},
      "key2": {{"op": ">", "val": 0.3}}
    }},
    "action": "BUY",
    "target_coins": "*",
    "budget_usd": 100,
    "max_trades": 8,
    "regime": "*"
  }}
]
"""


def build_hypothesis_review_prompt(active_hyps: list, promoted: list,
                                    lessons: list, hyp_trades: list) -> str:
    return f"""
{PromptLibrary.SYSTEM_IDENTITY}

TASK: HYPOTHESIS_REVIEW — Evaluate active experiments and recommend actions.

ACTIVE EXPERIMENTS:
{json.dumps(active_hyps, indent=2, default=str)}

PROMOTED STRATEGIES:
{json.dumps(promoted, indent=2, default=str)}

RECENT LESSONS:
{json.dumps(lessons[-5:], indent=2, default=str)}

For each active experiment, recommend ONE action:
- "continue" — needs more data
- "kill" — clearly not working, explain why
- "promote" — strong enough to graduate
- "breed" — combine this with another hypothesis into a new one

Also suggest:
- Should any promoted strategies be demoted? (performance degraded)
- Can you see a compound hypothesis by merging signals from 2+ experiments?

Respond with ONLY this JSON:
{{
  "reviews": [
    {{"hypothesis_id": "abc123", "action": "continue|kill|promote|breed", "reason": "why"}}
  ],
  "new_breed": null or {{
    "name": "combined_name",
    "thesis": "theory",
    "conditions": {{}},
    "action": "BUY",
    "parent_ids": ["id1", "id2"],
    "generation": 2
  }},
  "demote_strategy": null or "strategy_id",
  "meta_insight": "what am I learning about my own hypothesis quality?"
}}
"""


# ══════════════════════════════════════════════
# WORKER STATE MANAGER
# ══════════════════════════════════════════════

class WorkerState:
    def __init__(self):
        self.last_tactical:    float = 0.0
        self.last_regime:      float = 0.0
        self.last_drift:       float = 0.0
        self.last_postmortem:  str   = ""   # date string YYYY-MM-DD
        self.last_asymmetry:   float = 0.0
        self.last_calibration: float = 0.0
        self.last_hyp_gen:     float = 0.0
        self.last_theory:      float = 0.0
        self.last_audit:       float = 0.0
        self.last_hyp_review:  float = 0.0
        self._load()

    def _load(self):
        try:
            with open(WORKER_STATE) as f:
                d = json.load(f)
            self.last_tactical    = d.get("last_tactical", 0.0)
            self.last_regime      = d.get("last_regime", 0.0)
            self.last_drift       = d.get("last_drift", 0.0)
            self.last_postmortem  = d.get("last_postmortem", "")
            self.last_asymmetry   = d.get("last_asymmetry", 0.0)
            self.last_calibration = d.get("last_calibration", 0.0)
            self.last_hyp_gen     = d.get("last_hyp_gen", 0.0)
            self.last_theory      = d.get("last_theory", 0.0)
            self.last_audit       = d.get("last_audit", 0.0)
            self.last_hyp_review  = d.get("last_hyp_review", 0.0)
        except Exception:
            pass

    def save(self):
        with open(WORKER_STATE, "w") as f:
            json.dump({
                "last_tactical":    self.last_tactical,
                "last_regime":      self.last_regime,
                "last_drift":       self.last_drift,
                "last_postmortem":  self.last_postmortem,
                "last_asymmetry":   self.last_asymmetry,
                "last_calibration": self.last_calibration,
                "last_hyp_gen":     self.last_hyp_gen,
                "last_theory":      self.last_theory,
                "last_audit":       self.last_audit,
                "last_hyp_review":  self.last_hyp_review,
            }, f, indent=2)


# ══════════════════════════════════════════════
# MAIN WORKER LOOP
# ══════════════════════════════════════════════

def main():
    log.info("═" * 60)
    log.info("  BOTTY CLAUDE CODE WORKER — STARTING")
    log.info("  Runs parallel to nkn_bot.py")
    log.info("  Writes overlay decisions to shared files")
    log.info("═" * 60)

    bridge  = ClaudeCodeBridge()
    reader  = DataReader()
    prompts = PromptLibrary()
    ws      = WorkerState()

    # Storage for order book / volume history (in-memory rolling window)
    book_history:   list = []
    volume_history: list = []
    price_history:  list = []

    # Last postmortem result for continuity chain
    yesterday_pm: dict = {}
    try:
        with open(POSTMORTEM_FILE) as f:
            yesterday_pm = json.load(f)
    except Exception:
        pass

    # Stored confidence/outcome pairs for calibration
    confidence_log: list = []
    outcome_log:    list = []

    loop_count = 0

    while True:
        try:
            now      = time.time()
            today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            utc_hour = datetime.now(timezone.utc).hour
            loop_count += 1

            # ── Gather fresh data ──────────────────────────────
            episodes      = reader.get_recent_episodes(20)
            pnl_summary   = reader.get_pnl_summary()
            regime_table  = reader.get_regime_pnl_table()
            training      = reader.get_training_progress()
            config_live   = reader.get_config_live()

            # Read current indicators from overlay file if bot wrote it
            current_ind = {}
            try:
                with open("current_indicators.json") as f:
                    current_ind = json.load(f)
            except Exception:
                pass

            # Enrich pnl_summary with LIVE portfolio data from current_indicators
            # (pnl_events table only updates on trades — can go stale for hours)
            if current_ind:
                live_holdings = current_ind.get("holdings", {})
                live_total = sum(h.get("value", 0) for h in live_holdings.values())
                live_cash = current_ind.get("cash_usd", pnl_summary.get("cash", 0))
                pnl_summary["cash"] = live_cash
                pnl_summary["live_portfolio_value"] = live_total + live_cash
                pnl_summary["live_holdings"] = {c: h.get("value", 0) for c, h in live_holdings.items()}
                pnl_summary["cash_pct"] = round(live_cash / max(live_total + live_cash, 1) * 100, 1)
                pnl_summary["data_age"] = current_ind.get("_written", "unknown")

            # ── LAYER 1: TACTICAL OVERLAY (every 4 min) ───────
            # [STRIPPED] if now - ws.last_tactical >= TACTICAL_INTERVAL_SEC and current_ind:
            # [STRIPPED] log.info("━" * 40)
            # [STRIPPED] log.info("LAYER 1 — TACTICAL OVERLAY")
            # [STRIPPED] prompt   = prompts.tactical_overlay(
            # [STRIPPED] current_ind, pnl_summary, episodes, regime_table, training
            # [STRIPPED] )
            # [STRIPPED] response = bridge.call(prompt, "TACTICAL")
            # [STRIPPED] if response:
            # [STRIPPED] write_overlay(response)
            # [STRIPPED] ws.last_tactical = now
            # [STRIPPED] ws.save()

                    # Track confidence for calibration
            # [STRIPPED] if response.get("confidence"):
            # [STRIPPED] confidence_log.append({
            # [STRIPPED] "action": response.get("action_override"),
            # [STRIPPED] "confidence": response.get("confidence")
            # [STRIPPED] })

            # ── LAYER 2: REGIME NARRATION (every 30 min) ──────
            # [STRIPPED] if now - ws.last_regime >= REGIME_INTERVAL_SEC and current_ind:
            # [STRIPPED] log.info("━" * 40)
            # [STRIPPED] log.info("LAYER 2 — REGIME NARRATION")
            # [STRIPPED] prompt   = prompts.regime_narration(
            # [STRIPPED] regime_table, episodes, current_ind, pnl_summary
            # [STRIPPED] )
            # [STRIPPED] response = bridge.call(prompt, "REGIME")
            # [STRIPPED] if response:
                    # Write regime guidance into overlay with extended validity
            # [STRIPPED] response["valid_until_cycles"] = 15
            # [STRIPPED] response["overlay_type"]       = "regime"
            # [STRIPPED] write_overlay(response, "regime_overlay.json")
            # [STRIPPED] ws.last_regime = now
            # [STRIPPED] ws.save()
            # [STRIPPED] log.info(f"Regime: {response.get('regime_human_label')} | "
            # [STRIPPED] f"Edge: {response.get('regime_historical_edge','?')}")

            # ── LAYER 3: STRATEGY DRIFT CHECK (every 6h) ──────
            # [STRIPPED] if now - ws.last_drift >= DRIFT_INTERVAL_SEC:
            # [STRIPPED] log.info("━" * 40)
            # [STRIPPED] log.info("LAYER 3 — STRATEGY DRIFT CHECK")

            # [STRIPPED] all_week = reader.get_all_episodes_today()
            # [STRIPPED] pnl_curve = []
            # [STRIPPED] try:
            # [STRIPPED] conn = sqlite3.connect(BOT_DB)
            # [STRIPPED] rows = conn.execute("""
            # [STRIPPED] SELECT realized, fees_total, timestamp
            # [STRIPPED] FROM pnl_events ORDER BY id DESC LIMIT 50
            # [STRIPPED] """).fetchall()
            # [STRIPPED] conn.close()
            # [STRIPPED] pnl_curve = [{"realized": r[0], "fees": r[1], "ts": r[2]} for r in reversed(rows)]
            # [STRIPPED] except Exception:
            # [STRIPPED] pass

            # [STRIPPED] prompt   = prompts.strategy_drift_check(all_week, training, config_live, pnl_curve)
            # [STRIPPED] response = bridge.call(prompt, "DRIFT")
            # [STRIPPED] if response:
            # [STRIPPED] if response.get("drift_detected"):
            # [STRIPPED] log.warning(f"DRIFT DETECTED: {response.get('drift_description')}")
            # [STRIPPED] mutations = response.get("config_mutations", {})
            # [STRIPPED] reasoning = response.get("config_mutation_reasoning", {})
            # [STRIPPED] write_config_mutations(mutations, reasoning)

            # [STRIPPED] ws.last_drift = now
            # [STRIPPED] ws.save()
            # [STRIPPED] log.info(f"Strategy health: {response.get('health_score')} | "
            # [STRIPPED] f"Capital efficiency: {response.get('capital_efficiency_score')}")

            # ── LAYER 4: NIGHTLY POSTMORTEM (once at midnight UTC) ─
            # [STRIPPED] if utc_hour == POSTMORTEM_UTC_HOUR and today != ws.last_postmortem:
            # [STRIPPED] log.info("━" * 40)
            # [STRIPPED] log.info("LAYER 4 — NIGHTLY POSTMORTEM")

                # Mark as done immediately to prevent infinite retry loop
            # [STRIPPED] ws.last_postmortem = today
            # [STRIPPED] ws.save()

            # [STRIPPED] today_eps = reader.get_all_episodes_today()
            # [STRIPPED] if today_eps:
            # [STRIPPED] prompt   = prompts.nightly_postmortem(
            # [STRIPPED] today_eps, pnl_summary, regime_table,
            # [STRIPPED] training, config_live, yesterday_pm
            # [STRIPPED] )
            # [STRIPPED] response = bridge.call(prompt, "POSTMORTEM")
            # [STRIPPED] if response:
            # [STRIPPED] with open(POSTMORTEM_FILE, "w") as f:
            # [STRIPPED] json.dump(response, f, indent=2)
            # [STRIPPED] yesterday_pm = response
            # [STRIPPED] ws.last_postmortem = today
            # [STRIPPED] ws.save()

                        # Apply immediate config changes from postmortem
            # [STRIPPED] mutations = response.get("immediate_config_changes", {})
            # [STRIPPED] reasoning = response.get("immediate_config_reasoning", {})
            # [STRIPPED] write_config_mutations(mutations, reasoning)

                        # Run meta-learning injection based on postmortem
            # [STRIPPED] meta_prompt = prompts.meta_learning_injection(
            # [STRIPPED] response, training, regime_table
            # [STRIPPED] )
            # [STRIPPED] meta_resp = bridge.call(meta_prompt, "META_LEARN")
            # [STRIPPED] if meta_resp:
            # [STRIPPED] examples = meta_resp.get("synthetic_examples", [])
            # [STRIPPED] if examples:
            # [STRIPPED] inject_synthetic_examples(examples)

            # [STRIPPED] grade = response.get("performance_grade", "?")
            # [STRIPPED] days  = response.get("days_to_target_at_current_pace")
            # [STRIPPED] log.info(f"Postmortem grade: {grade} | Days to target: {days}")

                # Generate daily accountability report (always, even without episodes)
            # [STRIPPED] try:
            # [STRIPPED] from daily_report import generate_daily_report
            # [STRIPPED] report = generate_daily_report()
            # [STRIPPED] log.info(f"Daily report generated: {len(report)} chars")
            # [STRIPPED] except Exception as rpt_err:
            # [STRIPPED] log.warning(f"Daily report failed: {rpt_err}")

            # ── LAYER 5: ASYMMETRY DEEP DIVE (every 2h) ───────
            # [STRIPPED] if now - ws.last_asymmetry >= 7200:
            # [STRIPPED] log.info("━" * 40)
            # [STRIPPED] log.info("LAYER 5 — ASYMMETRY DEEP DIVE")

                # Collect price history from current_ind if available
            # [STRIPPED] if current_ind:
            # [STRIPPED] price_history.append({
            # [STRIPPED] "price": current_ind.get("price"),
            # [STRIPPED] "rsi": current_ind.get("rsi"),
            # [STRIPPED] "volume": current_ind.get("cur_vol"),
            # [STRIPPED] "atr": current_ind.get("atr"),
            # [STRIPPED] "ts": datetime.now(timezone.utc).isoformat()
            # [STRIPPED] })
            # [STRIPPED] if len(price_history) > 40:
            # [STRIPPED] price_history = price_history[-40:]

            # [STRIPPED] recent_fills = episodes[:10]
            # [STRIPPED] prompt  = prompts.asymmetry_deep_dive(
            # [STRIPPED] book_history[-10:], volume_history[-20:],
            # [STRIPPED] price_history, recent_fills
            # [STRIPPED] )
            # [STRIPPED] response = bridge.call(prompt, "ASYMMETRY")
            # [STRIPPED] if response:
                    # Write any new suggested rules to config
            # [STRIPPED] new_rule = response.get("suggested_new_rule")
            # [STRIPPED] if new_rule:
            # [STRIPPED] write_config_mutations(
            # [STRIPPED] {"_suggested_rule": new_rule},
            # [STRIPPED] {"_suggested_rule": response.get("strongest_asymmetry", "")}
            # [STRIPPED] )
            # [STRIPPED] ws.last_asymmetry = now
            # [STRIPPED] ws.save()
            # [STRIPPED] log.info(f"Asymmetry: {response.get('strongest_asymmetry','none')} | "
            # [STRIPPED] f"Edge: {response.get('strongest_asymmetry_edge_estimate',0):.3f}")

            # ── LAYER 6: CONFIDENCE CALIBRATION (every 3h) ────
            # [STRIPPED] if now - ws.last_calibration >= 10800 and len(confidence_log) >= 10:
            # [STRIPPED] log.info("━" * 40)
            # [STRIPPED] log.info("LAYER 6 — CONFIDENCE CALIBRATION")

            # [STRIPPED] recent_outcomes = reader.get_recent_episodes(50)
            # [STRIPPED] outcome_log = recent_outcomes

            # [STRIPPED] prompt   = prompts.confidence_calibration(
            # [STRIPPED] confidence_log[-50:], outcome_log, training
            # [STRIPPED] )
            # [STRIPPED] response = bridge.call(prompt, "CALIBRATION")
            # [STRIPPED] if response:
                    # Update confidence floor if recommended
            # [STRIPPED] new_floor = response.get("confidence_floor_recommendation")
            # [STRIPPED] new_entropy = response.get("recommended_entropy_coeff")
            # [STRIPPED] mutations = {}
            # [STRIPPED] reasoning = {}
            # [STRIPPED] if new_floor and abs(new_floor - 0.52) > 0.03:
            # [STRIPPED] mutations["CONFIDENCE_FLOOR"]         = new_floor
            # [STRIPPED] reasoning["CONFIDENCE_FLOOR"]         = response.get("calibration_narrative", "")
            # [STRIPPED] if new_entropy and abs(new_entropy - 0.01) > 0.003:
            # [STRIPPED] mutations["ENTROPY_COEFF"]            = new_entropy
            # [STRIPPED] reasoning["ENTROPY_COEFF"]            = response.get("entropy_assessment", "")
            # [STRIPPED] write_config_mutations(mutations, reasoning)
            # [STRIPPED] ws.last_calibration = now
            # [STRIPPED] ws.save()
            # [STRIPPED] log.info(f"Calibration: {response.get('calibration_quality')} | "
            # [STRIPPED] f"Reliable threshold: {response.get('reliable_threshold')}")

            # ── LAYER 7: EVOLUTION (every 6h) — big picture strategy updates ──
            # [STRIPPED] if now - ws.last_drift >= 21600:  # reuse drift timer (6h)
            # [STRIPPED] log.info("━" * 40)
            # [STRIPPED] log.info("LAYER 7 — STRATEGIC EVOLUTION")

                # Gather learning engine status
            # [STRIPPED] learner_status = {}
            # [STRIPPED] try:
            # [STRIPPED] import sqlite3 as _sq
            # [STRIPPED] _lc = _sq.connect("adaptive_learner.db")
            # [STRIPPED] _ls = _lc.execute("SELECT * FROM learner_state WHERE id=1").fetchone()
            # [STRIPPED] if _ls:
            # [STRIPPED] learner_status = {
            # [STRIPPED] "total_trades": _ls[1], "total_wins": _ls[2],
            # [STRIPPED] "model_accuracy": _ls[3], "confidence": _ls[4],
            # [STRIPPED] }
                    # Override with actual counts from trade_features (source of truth)
            # [STRIPPED] _actual = _lc.execute(
            # [STRIPPED] "SELECT COUNT(*), SUM(CASE WHEN won=1 THEN 1 ELSE 0 END) FROM trade_features"
            # [STRIPPED] ).fetchone()
            # [STRIPPED] if _actual and _actual[0]:
            # [STRIPPED] learner_status["total_trades"] = _actual[0]
            # [STRIPPED] learner_status["total_wins"] = _actual[1] or 0
            # [STRIPPED] learner_status["win_rate"] = learner_status["total_wins"] / max(_actual[0], 1)
            # [STRIPPED] _strats = _lc.execute(
            # [STRIPPED] "SELECT strategy, COUNT(*), SUM(CASE WHEN won=1 THEN 1 ELSE 0 END), SUM(pnl) "
            # [STRIPPED] "FROM trade_features GROUP BY strategy"
            # [STRIPPED] ).fetchall()
            # [STRIPPED] learner_status["strategies"] = [
            # [STRIPPED] {"name": s[0], "trades": s[1], "wins": s[2], "pnl": round(s[3] or 0, 4)}
            # [STRIPPED] for s in _strats
            # [STRIPPED] ]
            # [STRIPPED] _lc.close()
            # [STRIPPED] except: pass

            # [STRIPPED] evo_prompt = f"""
            # [STRIPPED] {PromptLibrary.SYSTEM_IDENTITY}

            # [STRIPPED] TASK: STRATEGIC_EVOLUTION — analyze performance and recommend changes to accelerate toward $100K profit goal.

            # [STRIPPED] CURRENT PORTFOLIO STATE:
            # [STRIPPED] {json.dumps(pnl_summary, indent=2)}

            # [STRIPPED] LEARNING ENGINE STATUS:
            # [STRIPPED] {json.dumps(learner_status, indent=2)}

            # [STRIPPED] RECENT TRADE EPISODES:
            # [STRIPPED] {json.dumps(episodes[-20:], indent=2)}

            # [STRIPPED] CURRENT INDICATORS:
            # [STRIPPED] {json.dumps(current_ind, indent=2)}

            # [STRIPPED] THE $100K GOAL:
            # [STRIPPED] - Current profit from baseline: check portfolio_value - 6700
            # [STRIPPED] - Goal: $100,000 profit
            # [STRIPPED] - Every decision should be evaluated by: does this get us to $100K faster?

            # [STRIPPED] ANSWER THESE SPECIFICALLY:
            # [STRIPPED] 1. Which strategies are WORKING? (positive Sharpe, >50% WR) Increase their allocation.
            # [STRIPPED] 2. Which strategies are FAILING? (negative Sharpe, <40% WR) Kill them or reduce allocation.
            # [STRIPPED] 3. What's the SINGLE highest-impact change to accelerate toward $100K?
            # [STRIPPED] 4. Is the bot being too cautious or too aggressive given its current performance?
            # [STRIPPED] 5. Are there coins in the portfolio that should be exited immediately? Which ones and why?
            # [STRIPPED] 6. What new strategy or rule would improve the win rate by 5%+ based on the trade history patterns?

            # [STRIPPED] {{
            # [STRIPPED] "working_strategies": [],
            # [STRIPPED] "failing_strategies": [],
            # [STRIPPED] "highest_impact_change": "",
            # [STRIPPED] "risk_assessment": "",
            # [STRIPPED] "immediate_exits": [],
            # [STRIPPED] "new_rule": null,
            # [STRIPPED] "config_mutations": {{}},
            # [STRIPPED] "config_reasoning": {{}},
            # [STRIPPED] "estimated_days_to_100k": null,
            # [STRIPPED] "evolution_summary": ""
            # [STRIPPED] }}
            # [STRIPPED] """
            # [STRIPPED] response = bridge.call(evo_prompt, "EVOLUTION")
            # [STRIPPED] if response:
                    # Apply config mutations
            # [STRIPPED] mutations = response.get("config_mutations", {})
            # [STRIPPED] reasoning = response.get("config_reasoning", {})
            # [STRIPPED] if mutations:
            # [STRIPPED] write_config_mutations(mutations, reasoning)

                    # Log evolution
            # [STRIPPED] evo_log = []
            # [STRIPPED] try:
            # [STRIPPED] with open("evolution_log.json") as f:
            # [STRIPPED] evo_log = json.load(f)
            # [STRIPPED] except: pass
            # [STRIPPED] evo_log.append({
            # [STRIPPED] "ts": datetime.now(timezone.utc).isoformat(),
            # [STRIPPED] "summary": response.get("evolution_summary", ""),
            # [STRIPPED] "highest_impact": response.get("highest_impact_change", ""),
            # [STRIPPED] "days_to_100k": response.get("estimated_days_to_100k"),
            # [STRIPPED] "working": response.get("working_strategies", []),
            # [STRIPPED] "failing": response.get("failing_strategies", []),
            # [STRIPPED] })
            # [STRIPPED] with open("evolution_log.json", "w") as f:
            # [STRIPPED] json.dump(evo_log, f, indent=2)

            # [STRIPPED] ws.last_drift = now  # reuse drift timer
            # [STRIPPED] ws.save()
            # [STRIPPED] log.info(f"Evolution: {response.get('evolution_summary', '?')[:100]}")
            # [STRIPPED] log.info(f"Days to $100K: {response.get('estimated_days_to_100k', '?')}")
            # [STRIPPED] log.info(f"Highest impact: {response.get('highest_impact_change', '?')[:100]}")

            # ── SYSTEM AUDITOR — autonomous oversight (every 30 min) ──
            try:
                if now - ws.last_audit >= AUDIT_INTERVAL_SEC:
                    from system_auditor import run_audit
                    audit_result = run_audit(bridge)
                    ws.last_audit = now
                    ws.save()
                    if audit_result:
                        log.info("SYSTEM AUDIT complete — Grade: %s" % audit_result.get("grade", "?"))
            except Exception as audit_err:
                import traceback
                log.warning("[AUDIT] Error: %s\n%s" % (audit_err, traceback.format_exc()))

            # ── LAYER 8: HYPOTHESIS GENERATION (every 2h) ──
            if now - ws.last_hyp_gen >= HYPOTHESIS_GEN_SEC and current_ind:
                log.info("━" * 40)
                log.info("LAYER 8 — HYPOTHESIS GENERATION")
                try:
                    from hypothesis_engine import HypothesisStore
                    hyp_store = HypothesisStore()

                    # Gather context for Claude
                    active_hyps = hyp_store.get_active()
                    promoted = hyp_store.get_promoted()
                    lessons = hyp_store.get_lessons(10)
                    strat_perf = []
                    try:
                        import sqlite3 as _sq2
                        _lc2 = _sq2.connect("adaptive_learner.db")
                        _sp = _lc2.execute(
                            "SELECT strategy, COUNT(*) as n, SUM(CASE WHEN won=1 THEN 1 ELSE 0 END) as w, ROUND(SUM(pnl),2) as p "
                            "FROM trade_features GROUP BY strategy ORDER BY p DESC"
                        ).fetchall()
                        strat_perf = [{"strategy": r[0], "trades": r[1], "wins": r[2], "pnl": r[3]} for r in _sp]
                        _lc2.close()
                    except: pass

                    # Add backtest results so Claude knows what worked historically
                    backtest_data = []
                    try:
                        import sqlite3 as _sq3
                        if os.path.exists("backtest_results.db"):
                            _bc = _sq3.connect("backtest_results.db")
                            backtest_data = [dict(r) for r in _bc.execute(
                                "SELECT hypothesis_name, verdict, simulated_trades, simulated_wins, "
                                "simulated_pnl, peak_gain_avg FROM backtest_runs ORDER BY id DESC LIMIT 10"
                            ).fetchall()]
                            _bc.row_factory = _sq3.Row
                            _bc.close()
                    except: pass

                    # Add exit learning data
                    exit_learning = ""
                    try:
                        import sqlite3 as _sq4
                        _ec = _sq4.connect("hypothesis_engine.db")
                        near_misses = _ec.execute(
                            "SELECT coin, ROUND(peak_gain_pct*100,1), ROUND(pnl_pct*100,1), ROUND(hold_sec/60,0) "
                            "FROM hypothesis_trades WHERE thesis_correct=1 AND pnl < 0 "
                            "ORDER BY peak_gain_pct DESC LIMIT 5"
                        ).fetchall()
                        _ec.close()
                        if near_misses:
                            exit_learning = "\n\nEXIT LEARNING — these trades picked WINNERS but failed to capture:\n"
                            for nm in near_misses:
                                exit_learning += f"  {nm[0]}: peaked +{nm[1]}% but closed at {nm[2]}% (held {nm[3]}min)\n"
                            exit_learning += "Generate hypotheses that would catch these same setups with TIGHTER exits.\n"
                    except: pass

                    # Get exit learning data for smarter hypothesis generation
                    exit_insights = {}
                    try:
                        exit_insights = hyp_store.get_exit_insights()
                    except: pass

                    prompt = build_hypothesis_gen_prompt(
                        current_ind, pnl_summary, lessons, active_hyps, promoted, strat_perf)
                    prompt += exit_learning

                    # Append ML model insights so Claude uses data-proven signals
                    try:
                        model_insights = json.load(open("model_insights.json"))
                        if model_insights.get("top_features"):
                            prompt += "\n\nML MODEL INSIGHTS (%.0f%% accurate on %d trades):\n" % (
                                model_insights.get("accuracy", 0)*100,
                                model_insights.get("sample_size", 0))
                            prompt += "Most predictive features of winning trades:\n"
                            for feat, imp in model_insights["top_features"].items():
                                prompt += "  %s: importance=%.3f\n" % (feat, imp)
                            prompt += "Generate hypotheses that use these HIGH-IMPORTANCE features.\n"
                    except: pass

                    # Append exit insights so Claude learns from past trades
                    if exit_insights:
                        prompt += "\n\nEXIT INSIGHTS FROM REAL TRADES:\n"
                        if exit_insights.get("best_trades"):
                            prompt += "BEST TRADES (replicate these):\n"
                            for bt in exit_insights["best_trades"]:
                                prompt += f"  {bt['coin']}: ${bt['pnl']:.2f} in {bt.get('hold_sec',0)/3600:.1f}h — {bt['conditions'][:60]}\n"
                        if exit_insights.get("missed_gains"):
                            prompt += "MISSED GAINS (thesis right, exit wrong — fix the exit):\n"
                            for mg in exit_insights["missed_gains"]:
                                prompt += f"  {mg['coin']}: peaked {mg['peaked']} but closed {mg['closed']}\n"
                        if exit_insights.get("winning_condition_keys"):
                            prompt += f"WINNING CONDITIONS USE THESE KEYS: {exit_insights['winning_condition_keys']}\n"
                            prompt += "Generate hypotheses that use THESE proven keys, not random ones.\n"


                    # Append runner analysis data (historical + live)
                    try:
                        ra = json.load(open("runner_analysis.json"))
                        prompt += f"\n\nHISTORICAL RUNNERS ({ra.get('total_runs', 0)} runs >15% in 7 days):\n"
                        prompt += f"Avg gain: {ra.get('avg_gain', 0):.0f}% | Avg hours to peak: {ra.get('avg_hours_to_peak', 0):.0f}h\n"
                        prompt += f"Avg entry: ${ra.get('avg_entry_price', 0):.6f} | Avg hurst: {ra.get('avg_hurst_before', 0):.3f}\n"
                    except: pass
                    try:
                        rl = json.load(open("runner_live.json"))
                        sigs = rl.get("signals", [])
                        if sigs:
                            prompt += f"\nLIVE RUNNER SIGNALS RIGHT NOW ({len(sigs)} coins matching pre-run pattern):\n"
                            prompt += json.dumps(sigs[:5], default=str) + "\n"
                            prompt += "These coins are showing runner patterns NOW. Consider creating hypotheses to test them.\n"
                    except: pass

                    # Append backtest context
                    if backtest_data:
                        prompt += f"\n\nBACKTEST RESULTS (historical testing — use this to generate better hypotheses):\n{json.dumps(backtest_data, indent=2, default=str)}\n"
                        prompt += "Hypotheses marked PASS in backtesting should be prioritized. FAIL = don't repeat those conditions.\n"

                    response = bridge.call(prompt, "HYPOTHESIS_GEN")

                    if response and isinstance(response, list):
                        for spec in response[:3]:
                            hid = hyp_store.create_hypothesis(spec)
                            if hid:
                                log.info(f"  NEW HYPOTHESIS: {spec.get('name', '?')} — {spec.get('thesis', '?')[:80]}")
                    elif response and isinstance(response, dict) and "hypotheses" in response:
                        for spec in response["hypotheses"][:3]:
                            hid = hyp_store.create_hypothesis(spec)
                            if hid:
                                log.info(f"  NEW HYPOTHESIS: {spec.get('name', '?')} — {spec.get('thesis', '?')[:80]}")

                    ws.last_hyp_gen = now
                    ws.save()
                    summary = hyp_store.get_summary()
                    log.info(f"  Hypotheses: {summary['active']} active, {summary['promoted']} promoted, {summary['killed']} killed")
                except Exception as he:
                    import traceback
                    log.warning(f"[Hyp Gen] Error: {he}\n{traceback.format_exc()}")
                    ws.last_hyp_gen = now
                    ws.save()

            # ── LAYER 8b: HYPOTHESIS REVIEW (every 6h) ──
            # [STRIPPED] if now - ws.last_hyp_review >= HYPOTHESIS_REVIEW_SEC:
            # [STRIPPED] log.info("━" * 40)
            # [STRIPPED] log.info("LAYER 8b — HYPOTHESIS REVIEW")
            # [STRIPPED] try:
            # [STRIPPED] from hypothesis_engine import HypothesisStore
            # [STRIPPED] hyp_store = HypothesisStore()
            # [STRIPPED] active_hyps = hyp_store.get_active()
            # [STRIPPED] promoted = hyp_store.get_promoted()
            # [STRIPPED] lessons = hyp_store.get_lessons(5)

            # [STRIPPED] if active_hyps:
            # [STRIPPED] prompt = build_hypothesis_review_prompt(active_hyps, promoted, lessons, [])
            # [STRIPPED] response = bridge.call(prompt, "HYPOTHESIS_REVIEW")

            # [STRIPPED] if response:
            # [STRIPPED] for review in response.get("reviews", []):
            # [STRIPPED] hid = review.get("hypothesis_id", "")
            # [STRIPPED] action = review.get("action", "")
            # [STRIPPED] reason = review.get("reason", "")
                                # PROTECTION: don't kill hypotheses with < 5 trades
                                # They haven't had enough data to prove or disprove
            # [STRIPPED] if action == "kill":
            # [STRIPPED] hyp_data = next((h for h in active_hyps if h["id"] == hid), None)
            # [STRIPPED] trades = hyp_data.get("trades", 0) if hyp_data else 0
            # [STRIPPED] if trades < 5:
            # [STRIPPED] log.info(f"  Review {hid}: BLOCKED kill (only {trades} trades, need 5)")
            # [STRIPPED] continue
            # [STRIPPED] hyp_store.kill(hid, lesson=reason, failure_mode="claude_review")
            # [STRIPPED] elif action == "promote":
            # [STRIPPED] hyp_store.promote(hid)
            # [STRIPPED] log.info(f"  Review {hid}: {action} — {reason[:60]}")

                            # Breed new hypothesis if suggested
            # [STRIPPED] breed = response.get("new_breed")
            # [STRIPPED] if breed and isinstance(breed, dict):
            # [STRIPPED] breed["generation"] = breed.get("generation", 2)
            # [STRIPPED] hyp_store.create_hypothesis(breed)
            # [STRIPPED] log.info(f"  BRED: {breed.get('name', '?')}")

                            # Weekly maintenance
            # [STRIPPED] hyp_store.decay_promoted_weights()
            # [STRIPPED] hyp_store.demote_weakest_promoted()

            # [STRIPPED] meta = response.get("meta_insight", "")
            # [STRIPPED] if meta:
            # [STRIPPED] log.info(f"  Meta-insight: {meta[:100]}")

            # [STRIPPED] ws.last_hyp_review = now
            # [STRIPPED] ws.save()
            # [STRIPPED] except Exception as he:
            # [STRIPPED] log.warning(f"[Hyp Review] Error: {he}")
            # [STRIPPED] ws.last_hyp_review = now
            # [STRIPPED] ws.save()

            # ── LAYER 9: AUTOPILOT — self-healing + self-improving (every 15 min) ──
            # [STRIPPED] if loop_count % 240 == 0 and loop_count > 0:  # every 240 loops × 30s = ~2h
            # [STRIPPED] log.info("━" * 40)
            # [STRIPPED] log.info("LAYER 9 — AUTOPILOT (self-healing)")
            # [STRIPPED] try:
            # [STRIPPED] from auto_pilot import AutoPilot
            # [STRIPPED] pilot = AutoPilot()
            # [STRIPPED] result = pilot.run_cycle(bridge)
            # [STRIPPED] if result.get("status") == "fixed":
            # [STRIPPED] log.info(f"  AUTOPILOT FIXED: {result.get('diagnosis', '?')[:80]}")
            # [STRIPPED] log.info(f"  Applied {result.get('actions', 0)} fixes")
            # [STRIPPED] elif result.get("errors", 0) > 0:
            # [STRIPPED] log.info(f"  AUTOPILOT: {result.get('severity', '?')} — {result.get('diagnosis', '?')[:80]}")
            # [STRIPPED] else:
            # [STRIPPED] log.info(f"  AUTOPILOT: All clear")
            # [STRIPPED] except Exception as ap_err:
            # [STRIPPED] log.warning(f"[AutoPilot] Error: {ap_err}")

            # ── LAYER 10: ORCHESTRATOR DIAGNOSIS (when requested) ──
            # [STRIPPED] if loop_count % 60 == 0:  # check every ~30 min (was 10min)
            # [STRIPPED] try:
            # [STRIPPED] if os.path.exists("orchestrator_request.json"):
            # [STRIPPED] with open("orchestrator_request.json") as f:
            # [STRIPPED] req = json.load(f)
            # [STRIPPED] os.remove("orchestrator_request.json")

            # [STRIPPED] log.info("━" * 40)
            # [STRIPPED] log.info("LAYER 10 — ORCHESTRATOR DIAGNOSIS")

                        # Build context-rich prompt
            # [STRIPPED] diag_prompt = f"""{PromptLibrary.SHORT_IDENTITY}

            # [STRIPPED] TASK: The orchestrator has detected issues and needs your diagnosis.

            # [STRIPPED] QUESTIONS FROM ORCHESTRATOR:
            # [STRIPPED] {json.dumps(req.get('questions', []), indent=2)}

            # [STRIPPED] CONTEXT:
            # [STRIPPED] {json.dumps(req.get('context', {}), indent=2, default=str)}

            # [STRIPPED] CURRENT INDICATORS:
            # [STRIPPED] {json.dumps(current_ind, indent=2, default=str)}

            # [STRIPPED] Respond with JSON:
            # [STRIPPED] {{
            # [STRIPPED] "diagnosis": "what is the #1 issue right now",
            # [STRIPPED] "action": "specific code change or config change to fix it",
            # [STRIPPED] "new_hypothesis": null or {{"name": "...", "thesis": "...", "conditions": {{}}, "action": "BUY"}},
            # [STRIPPED] "exit_recommendation": "how should trailing stops be adjusted based on data",
            # [STRIPPED] "velocity_plan": "specific plan to increase $/day"
            # [STRIPPED] }}
            # [STRIPPED] """
            # [STRIPPED] response = bridge.call(diag_prompt, "ORCH_DIAGNOSIS")
            # [STRIPPED] if response:
            # [STRIPPED] log.info(f"  Diagnosis: {response.get('diagnosis', '?')[:100]}")
            # [STRIPPED] log.info(f"  Action: {response.get('action', '?')[:100]}")
            # [STRIPPED] log.info(f"  Exit rec: {response.get('exit_recommendation', '?')[:100]}")
            # [STRIPPED] log.info(f"  Velocity plan: {response.get('velocity_plan', '?')[:100]}")

                            # Create hypothesis if suggested
            # [STRIPPED] new_hyp = response.get("new_hypothesis")
            # [STRIPPED] if new_hyp and isinstance(new_hyp, dict) and new_hyp.get("conditions"):
            # [STRIPPED] try:
            # [STRIPPED] from hypothesis_engine import HypothesisStore
            # [STRIPPED] HypothesisStore().create_hypothesis(new_hyp)
            # [STRIPPED] log.info(f"  Created hypothesis from diagnosis: {new_hyp.get('name', '?')}")
            # [STRIPPED] except: pass
            # [STRIPPED] except Exception as diag_err:
            # [STRIPPED] log.debug(f"[Orch Diag] Error: {diag_err}")

            # ── Health log every 10 loops ──────────────────────
            # [STRIPPED] if loop_count % 10 == 0:
            # [STRIPPED] health = bridge.health()
            # [STRIPPED] log.info(
            # [STRIPPED] f"Bridge health: {health['success_rate']:.0%} success | "
            # [STRIPPED] f"avg {health['avg_latency_sec']}s | "
            # [STRIPPED] f"{health['calls']} calls total"
            # [STRIPPED] )


            # ── LAYER 9: THEORY ANALYSIS — Claude discovers breakout patterns ──
            # Fires every 30 min OR immediately when pending snapshots exist
            try:
                from theory_engine import TheoryEngine
                _te = TheoryEngine()
                _pending = _te.get_pending_snapshots(limit=2)
                _should_analyze = len(_pending) > 0 and (now - ws.last_theory >= 120)  # min 2 min gap
                if not _should_analyze:
                    _should_analyze = now - ws.last_theory >= THEORY_ANALYSIS_SEC and len(_pending) > 0

                if _should_analyze:
                    log.info("━" * 40)
                    log.info("LAYER 9 — THEORY ANALYSIS (%d pending snapshots)" % len(_pending))

                    for snap in _pending:
                        snap_type = snap.get("snapshot_type", "BREAKOUT")
                        coin = snap.get("coin", "?")
                        gain = snap.get("gain_pct", 0)
                        snap_id = snap["id"]

                        try:
                            indicators = json.loads(snap.get("indicators_json", "[]"))
                            candles = json.loads(snap.get("candles_json", "[]"))
                        except json.JSONDecodeError as _jde:
                            log.warning(f"  [THEORY] Snapshot #{snap['id']} JSON decode error: {_jde}")
                            indicators = []
                            candles = []

                        if not indicators or len(indicators) < 20:
                            log.warning(f"  [THEORY] Snapshot #{snap_id} {coin}: insufficient data, skipping")
                            _te.store_theories(snap_id, [], "Insufficient candle data")
                            continue

                        # Build candle-by-candle table for Claude (1-min resolution)
                        table_lines = ["Idx | Price | Volume | RSI | MACD_H | BB_Pos | BB_W | EMA9>21 | VWAP_D | VolR | Vel | Accel"]
                        table_lines.append("-" * 120)
                        for i, ind in enumerate(indicators):
                            ema_cross = "BULL" if ind.get("ema_9", 0) > ind.get("ema_21", 0) else "BEAR"
                            table_lines.append(
                                "%3d | %10.6f | %10.0f | %5.1f | %+.6f | %.2f | %.3f | %4s | %+.3f | %.1f | %+.4f | %+.4f" % (
                                    i, ind.get("price", 0), ind.get("volume", 0),
                                    ind.get("rsi", 50),
                                    ind.get("macd_histogram", 0), ind.get("bb_position", 0.5),
                                    ind.get("bb_width", 0), ema_cross,
                                    ind.get("vwap_distance", 0), ind.get("vol_ratio", 1),
                                    ind.get("velocity_short", 0), ind.get("acceleration", 0)))
                        candle_table = "\n".join(table_lines)

                        if snap_type == "BREAKOUT":
                            # Include realtime WS data if available
                            _guard_raw = snap.get("guard_data_json", "{}")
                            try:
                                _rt_data = json.loads(_guard_raw) if _guard_raw else {}
                            except json.JSONDecodeError:
                                _rt_data = {}
                            _rt_section = ""
                            if _rt_data:
                                _rt_lines = []
                                if "spread" in _rt_data:
                                    _rt_lines.append(f"Bid-Ask Spread: {_rt_data['spread']:.6f} ({_rt_data['spread']*100:.4f}%)")
                                if "book_imbalance" in _rt_data:
                                    _bi = _rt_data['book_imbalance']
                                    _label = "BUY pressure" if _bi > 0.55 else "SELL pressure" if _bi < 0.45 else "balanced"
                                    _rt_lines.append(f"Order Book Imbalance: {_bi:.3f} ({_label})")
                                if _rt_lines:
                                    _rt_section = "\n\nREAL-TIME WebSocket data at time of detection:\n" + "\n".join(_rt_lines)

                            prompt = f"""You are APEX, the AI trading strategist. Analyze this breakout to discover the EARLIEST predictive signal combination.

COIN: {coin} ran +{gain:.0f}% — a significant breakout.

Here are 1-minute candles with computed indicators covering ~3 hours before and during the run:

{candle_table}{_rt_section}

ANALYSIS REQUIRED:
1. At what candle index did this breakout become PREDICTABLE with >70% confidence? Look for the EARLIEST combination of signals.
2. What specific signal combination defines this entry point? Use ONLY these keys: rsi, macd_histogram, macd_line, bb_position, bb_width, vwap_distance, vol_ratio, velocity_short, acceleration, ema_9, ema_21, spread, book_imbalance
3. How many minutes before the peak did this signal appear? (each candle = 1 minute)
4. Create 1-3 theories with different signal combinations (conservative, moderate, aggressive).

Respond with ONLY this JSON (no other text):
{{
  "analysis": "2-3 sentence explanation of what happened",
  "earliest_signal_candle_index": 15,
  "theories": [
    {{
      "name": "short_descriptive_name",
      "theory_type": "ENTRY",
      "description": "why this combination predicts breakouts",
      "signals": {{
        "rsi": {{"op": ">", "val": 60}},
        "vol_ratio": {{"op": ">", "val": 2.0}}
      }},
      "signal_lead_min": 45,
      "optimal_window_min": 15,
      "source_gain_pct": {gain}
    }}
  ]
}}

RULES:
- Use conditions with op: ">", "<", ">=", "<="
- Max 4 signals per theory (simpler = more generalizable)
- The signals should be LEADING indicators, not lagging
- Focus on what changed BEFORE the big move, not during it
- signal_lead_min = minutes before peak (1 candle = 1 minute)"""

                        else:  # EXIT snapshot
                            guard_data = snap.get("guard_data_json", "{}")
                            prompt = f"""You are APEX, the AI trading strategist. Analyze this trade exit to discover the OPTIMAL exit signal.

COIN: {coin} | Peak gain: +{gain:.0f}%

1-minute candles with indicators covering the trade (~3 hours, each candle = 1 minute):

{candle_table}

Guard postmortem (tick-level WebSocket data during the run):
{guard_data[:1500]}

ANALYSIS REQUIRED:
1. At what candle did the reversal become CERTAIN (>80% confidence)?
2. What indicator combination defines the optimal exit trigger?
3. What % of the peak gain would this exit have captured?

Respond with ONLY this JSON (no other text):
{{
  "analysis": "2-3 sentence explanation of the reversal",
  "optimal_exit_candle_index": 25,
  "theories": [
    {{
      "name": "short_descriptive_name",
      "theory_type": "EXIT",
      "description": "why this exit signal works",
      "signals": {{}},
      "exit_trigger": {{
        "tick_rsi": {{"op": "<", "val": 40}},
        "consecutive_lower_highs": {{"op": ">", "val": 3}}
      }},
      "capture_pct": 0.75,
      "source_gain_pct": {gain}
    }}
  ]
}}

RULES:
- Exit triggers MUST use ONLY these exact keys: tick_rsi, tick_macd, tick_bb_position, consecutive_lower_highs, spread_ratio, volume_declining, rsi, macd_histogram, bb_position, bb_width, vol_ratio
- Do NOT invent new key names. Any key not in the list above will be rejected.
- Max 3 signals per exit trigger
- Focus on LEADING reversal indicators (1 candle = 1 minute)"""

                        log.info(f"  Analyzing {snap_type} snapshot #{snap_id}: {coin} +{gain:.0f}%")
                        response = bridge.call(prompt, "THEORY_ANALYSIS")

                        if response and isinstance(response, dict):
                            theories = response.get("theories", [])
                            analysis = response.get("analysis", "")
                            if theories:
                                _te.store_theories(snap_id, theories, analysis)
                                log.info(f"  Generated {len(theories)} theories from {coin} +{gain:.0f}%")
                                for t in theories:
                                    log.info(f"    Theory: '{t.get('name', '?')}' [{t.get('theory_type', '?')}] "
                                             f"signals={list(t.get('signals', t.get('exit_trigger', {})).keys())}")
                            else:
                                _te.store_theories(snap_id, [], analysis)
                                log.warning(f"  No theories generated for {coin}")
                        else:
                            log.warning(f"  Claude returned no valid response for {coin}")
                            _te.store_theories(snap_id, [], "No valid response")

                    ws.last_theory = now
                    ws.save()

                    te_summary = _te.get_summary()
                    log.info(f"  Theory Engine: {te_summary['total_theories']} theories | "
                             f"{te_summary['by_status']} | {te_summary['pending_analysis']} pending")

            except Exception as te_err:
                log.warning(f"[THEORY] Layer 9 error: {te_err}")
                import traceback; traceback.print_exc()

            # ── TRADING DIRECTOR — one decision every 30 min ──
            if loop_count % 60 == 0 and loop_count > 0:  # every 60 loops × 30s = 30min
                log.info("━" * 40)
                log.info("TRADING DIRECTOR — making one decision")
                try:
                    from trading_director import TradingDirector
                    director = TradingDirector()
                    result = director.run_cycle(bridge)
                    if result.get("decision"):
                        log.info("  Decision: %s" % result["decision"][:80])
                        log.info("  Type: %s → %s" % (result.get("type", "?"), result.get("result", {}).get("status", "?")))
                except Exception as e:
                    log.warning("[Director] Error: %s" % e, exc_info=True)

            # ── AI RESEARCHER — data-driven strategy optimization (every 6h) ──
            if loop_count % 720 == 360 and loop_count > 0:  # every 720 loops × 30s = 6h, offset from hyp_gen
                log.info("━" * 40)
                log.info("AI RESEARCHER — analyzing trade data")
                try:
                    from ai_researcher import AIResearcher
                    researcher = AIResearcher()
                    findings = researcher.run_research_cycle()

                    # Log key findings
                    ta = findings.get("trade_analysis", {})
                    if ta.get("total_trades"):
                        log.info("  Trades: %d | WR: %.0f%% | PnL: $%.2f" % (
                            ta["total_trades"], ta.get("win_rate", 0)*100, ta.get("total_pnl", 0)))

                    sp = findings.get("signal_patterns", {})
                    if sp.get("patterns"):
                        log.info("  Top signal patterns:")
                        for name, p in list(sp["patterns"].items())[:3]:
                            log.info("    %s: effect=%.2f (%s)" % (name, p["effect_size"], p["direction"]))

                    model = findings.get("model", {})
                    if model.get("accuracy"):
                        log.info("  ML model: %.0f%% accuracy" % (model["accuracy"]*100))

                    maint = findings.get("maintenance", {})
                    if maint.get("killed_stale"):
                        log.info("  Killed %d stale hypotheses" % maint["killed_stale"])

                except Exception as e:
                    log.warning("[Research] Error: %s" % e, exc_info=True)

            # Check Telegram for commands from human
            try:
                import notifier
                notifier.poll_and_respond()
            except Exception as _tg_err:
                log.debug("[Telegram] poll error: %s" % _tg_err)

            time.sleep(30)   # check conditions every 30s

        except KeyboardInterrupt:
            log.info("Worker shutting down cleanly.")
            ws.save()
            break
        except Exception as e:
            log.error(f"Worker loop error: {e}", exc_info=True)
            time.sleep(60)


if __name__ == "__main__":
    main()
