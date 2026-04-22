"""
tests/test_worker.py — Unit tests for the testable pure-Python logic in worker.py.

Does NOT test the Claude Code bridge (requires subprocess), DB readers (require SQLite),
or the NKN bot system (different process). Tests the JSON extractor and WorkerState
round-trip, which are pure functions with no external dependencies.

Run with: python3 -m pytest tests/test_worker.py -v
"""
from __future__ import annotations

import json
import pytest


# ── ClaudeCodeBridge._extract_json ────────────────────────────────────────────

class TestExtractJson:
    @pytest.fixture
    def extract(self):
        from worker import ClaudeCodeBridge
        return ClaudeCodeBridge._extract_json

    def test_raw_json_object(self, extract):
        raw = '{"verdict": "REJECT", "n": 5}'
        result = extract(raw)
        assert result == {"verdict": "REJECT", "n": 5}

    def test_raw_json_array(self, extract):
        raw = '[{"name": "hyp1"}, {"name": "hyp2"}]'
        result = extract(raw)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_json_inside_fences(self, extract):
        raw = 'Here is the result:\n```json\n{"action": "BUY"}\n```'
        result = extract(raw)
        assert result == {"action": "BUY"}

    def test_json_inside_fences_no_lang(self, extract):
        raw = 'Result:\n```\n{"action": "HOLD"}\n```'
        result = extract(raw)
        assert result == {"action": "HOLD"}

    def test_json_embedded_in_prose(self, extract):
        raw = 'The answer is: {"score": 0.9, "reason": "good"} — use this.'
        result = extract(raw)
        assert result == {"score": 0.9, "reason": "good"}

    def test_nested_json(self, extract):
        raw = '{"outer": {"inner": [1, 2, 3]}, "flag": true}'
        result = extract(raw)
        assert result["outer"]["inner"] == [1, 2, 3]

    def test_returns_none_on_no_json(self, extract):
        result = extract("This is just plain text with no JSON whatsoever.")
        assert result is None

    def test_returns_none_on_empty(self, extract):
        result = extract("")
        assert result is None

    def test_partial_json_returns_none(self, extract):
        result = extract('{"incomplete": ')
        assert result is None

    def test_float_values(self, extract):
        raw = '{"ev": 0.0123, "wr": 0.65}'
        result = extract(raw)
        assert abs(result["ev"] - 0.0123) < 1e-9

    def test_nested_braces_not_confused(self, extract):
        raw = '{"outer": {"a": 1, "b": {"c": 2}}}'
        result = extract(raw)
        assert result["outer"]["b"]["c"] == 2


# ── WorkerState round-trip ─────────────────────────────────────────────────────

class TestWorkerState:
    def test_save_and_load(self, tmp_path, monkeypatch):
        import worker
        monkeypatch.setattr(worker, "WORKER_STATE", str(tmp_path / "worker_state.json"))

        from worker import WorkerState
        ws = WorkerState()
        ws.last_tactical = 1234567890.0
        ws.last_regime   = 9876543210.5
        ws.last_postmortem = "2026-04-22"
        ws.save()

        ws2 = WorkerState()
        assert ws2.last_tactical == 1234567890.0
        assert ws2.last_regime   == 9876543210.5
        assert ws2.last_postmortem == "2026-04-22"

    def test_load_missing_file_uses_defaults(self, tmp_path, monkeypatch):
        import worker
        monkeypatch.setattr(worker, "WORKER_STATE", str(tmp_path / "no_such_file.json"))

        from worker import WorkerState
        ws = WorkerState()
        assert ws.last_tactical   == 0.0
        assert ws.last_regime     == 0.0
        assert ws.last_postmortem == ""

    def test_save_is_valid_json(self, tmp_path, monkeypatch):
        import worker
        path = tmp_path / "worker_state.json"
        monkeypatch.setattr(worker, "WORKER_STATE", str(path))

        from worker import WorkerState
        ws = WorkerState()
        ws.last_tactical = 42.0
        ws.save()

        raw = path.read_text()
        parsed = json.loads(raw)
        assert parsed["last_tactical"] == 42.0


# ── DataReader constructor safety ─────────────────────────────────────────────

class TestDataReaderConstructor:
    def test_default_constructor_does_not_purge(self, tmp_path, monkeypatch):
        """The default constructor must NOT delete any rows (regression guard)."""
        import sqlite3
        import worker

        db_path = str(tmp_path / "brain.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE episodes (id INTEGER PRIMARY KEY, net_pnl REAL)")
        conn.execute("INSERT INTO episodes (net_pnl) VALUES (-100)")  # would be deleted under old behavior
        conn.execute("INSERT INTO episodes (net_pnl) VALUES (5)")
        conn.commit()
        conn.close()

        monkeypatch.setattr(worker, "BRAIN_DB", db_path)
        from worker import DataReader
        DataReader()  # must NOT purge anything

        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        conn.close()
        assert count == 2  # both rows still present

    def test_explicit_purge_removes_low_pnl(self, tmp_path, monkeypatch):
        import sqlite3
        import worker

        db_path = str(tmp_path / "brain.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE episodes (id INTEGER PRIMARY KEY, net_pnl REAL)")
        conn.execute("INSERT INTO episodes (net_pnl) VALUES (-100)")
        conn.execute("INSERT INTO episodes (net_pnl) VALUES (5)")
        conn.commit()
        conn.close()

        monkeypatch.setattr(worker, "BRAIN_DB", db_path)
        from worker import DataReader
        deleted = DataReader(purge_poison=True).purge_poisoned_episodes()
        # purge_poison=True calls purge in __init__, then we call it again manually
        # — the second call finds 0 rows to delete

        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        conn.close()
        assert count == 1  # only the +5 row survives
