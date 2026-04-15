"""Unit tests for hooks/stop.py -- the Stop hook logic.

Tests: stop_hook_active guard, file queueing, paused session, mtime update,
graceful handling of missing session.json, duplicate deduplication.
"""

import json
import os
import sys
import time

import pytest

# Run stop.py as a subprocess to test full I/O contract
STOP_HOOK_PATH = os.path.join(os.path.dirname(__file__), "..", "hooks", "stop.py")


def _write_session(tmp_path, session: dict) -> None:
    tailtest = tmp_path / ".tailtest"
    tailtest.mkdir(exist_ok=True)
    with open(tailtest / "session.json", "w") as fh:
        json.dump(session, fh)


def _base_session(tmp_path, **kwargs) -> dict:
    session = {
        "session_id": "test-session",
        "started_at": "2026-01-01T00:00:00Z",
        "project_root": str(tmp_path),
        "runners": {"python": {"command": "pytest", "test_location": "tests/"}},
        "depth": "standard",
        "paused": False,
        "pending_files": [],
        "touched_files": [],
        "fix_attempts": {},
        "deferred_failures": [],
        "generated_tests": {},
        "packages": {},
        "turn_start_mtime": time.time() - 10,  # 10 seconds ago
    }
    session.update(kwargs)
    return session


def _run_hook(tmp_path, event: dict) -> dict:
    import subprocess
    result = subprocess.run(
        [sys.executable, STOP_HOOK_PATH],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, f"Hook exited non-zero: {result.stderr}"
    return json.loads(result.stdout)


def _event(tmp_path, stop_hook_active: bool = False) -> dict:
    return {
        "session_id": "test-session",
        "cwd": str(tmp_path),
        "stop_hook_active": stop_hook_active,
        "last_assistant_message": "I created billing.py",
        "transcript_path": str(tmp_path / "transcript.jsonl"),
    }


# ---------------------------------------------------------------------------
# stop_hook_active guard
# ---------------------------------------------------------------------------


class TestStopHookActiveGuard:
    def test_stop_hook_active_returns_continue(self, tmp_path):
        _write_session(tmp_path, _base_session(tmp_path))
        out = _run_hook(tmp_path, _event(tmp_path, stop_hook_active=True))
        assert out["decision"] == "continue"

    def test_stop_hook_active_does_not_modify_session(self, tmp_path):
        session = _base_session(tmp_path)
        _write_session(tmp_path, session)
        original_mtime = session["turn_start_mtime"]
        _run_hook(tmp_path, _event(tmp_path, stop_hook_active=True))
        with open(tmp_path / ".tailtest" / "session.json") as fh:
            saved = json.load(fh)
        assert saved["turn_start_mtime"] == original_mtime

    def test_stop_hook_active_does_not_queue_files(self, tmp_path):
        session = _base_session(tmp_path, turn_start_mtime=0.0)
        _write_session(tmp_path, session)
        # Create a file that would normally be queued
        src = tmp_path / "billing.py"
        src.write_text("def billing(): pass\n")
        _run_hook(tmp_path, _event(tmp_path, stop_hook_active=True))
        with open(tmp_path / ".tailtest" / "session.json") as fh:
            saved = json.load(fh)
        assert saved["pending_files"] == []


# ---------------------------------------------------------------------------
# No files changed
# ---------------------------------------------------------------------------


class TestNoFilesChanged:
    def test_no_files_returns_continue(self, tmp_path):
        session = _base_session(tmp_path)
        _write_session(tmp_path, session)
        # No source files written -- nothing changed after turn_start_mtime
        out = _run_hook(tmp_path, _event(tmp_path))
        assert out["decision"] == "continue"


# ---------------------------------------------------------------------------
# Python file queued
# ---------------------------------------------------------------------------


class TestPythonFileQueued:
    def test_python_file_returns_block(self, tmp_path):
        session = _base_session(tmp_path, turn_start_mtime=time.time() - 10)
        _write_session(tmp_path, session)
        # Write a Python file now (after session start)
        src_dir = tmp_path / "services"
        src_dir.mkdir()
        src = src_dir / "billing.py"
        src.write_text("def billing(): pass\n")
        out = _run_hook(tmp_path, _event(tmp_path))
        assert out["decision"] == "block"
        assert "reason" in out
        assert "billing.py" in out["reason"]

    def test_python_file_appears_in_session_pending(self, tmp_path):
        session = _base_session(tmp_path, turn_start_mtime=time.time() - 10)
        _write_session(tmp_path, session)
        src = tmp_path / "billing.py"
        src.write_text("def billing(): pass\n")
        _run_hook(tmp_path, _event(tmp_path))
        with open(tmp_path / ".tailtest" / "session.json") as fh:
            saved = json.load(fh)
        paths = [p["path"] for p in saved["pending_files"]]
        assert "billing.py" in paths

    def test_python_file_language_is_python(self, tmp_path):
        session = _base_session(tmp_path, turn_start_mtime=time.time() - 10)
        _write_session(tmp_path, session)
        src = tmp_path / "billing.py"
        src.write_text("def billing(): pass\n")
        _run_hook(tmp_path, _event(tmp_path))
        with open(tmp_path / ".tailtest" / "session.json") as fh:
            saved = json.load(fh)
        entry = next(p for p in saved["pending_files"] if "billing.py" in p["path"])
        assert entry["language"] == "python"


# ---------------------------------------------------------------------------
# Paused session
# ---------------------------------------------------------------------------


class TestPausedSession:
    def test_paused_session_returns_continue(self, tmp_path):
        session = _base_session(tmp_path, paused=True, turn_start_mtime=time.time() - 10)
        _write_session(tmp_path, session)
        src = tmp_path / "billing.py"
        src.write_text("def billing(): pass\n")
        out = _run_hook(tmp_path, _event(tmp_path))
        assert out["decision"] == "continue"

    def test_paused_session_does_not_queue_files(self, tmp_path):
        session = _base_session(tmp_path, paused=True, turn_start_mtime=time.time() - 10)
        _write_session(tmp_path, session)
        src = tmp_path / "billing.py"
        src.write_text("def billing(): pass\n")
        _run_hook(tmp_path, _event(tmp_path))
        with open(tmp_path / ".tailtest" / "session.json") as fh:
            saved = json.load(fh)
        assert saved["pending_files"] == []


# ---------------------------------------------------------------------------
# turn_start_mtime updated
# ---------------------------------------------------------------------------


class TestTurnStartMtimeUpdated:
    def test_mtime_updated_after_run(self, tmp_path):
        before = time.time() - 10
        session = _base_session(tmp_path, turn_start_mtime=before)
        _write_session(tmp_path, session)
        _run_hook(tmp_path, _event(tmp_path))
        with open(tmp_path / ".tailtest" / "session.json") as fh:
            saved = json.load(fh)
        assert saved["turn_start_mtime"] > before


# ---------------------------------------------------------------------------
# Missing session.json
# ---------------------------------------------------------------------------


class TestNoSessionJson:
    def test_no_session_json_returns_continue(self, tmp_path):
        # No session.json created -- graceful no-op
        out = _run_hook(tmp_path, _event(tmp_path))
        assert out["decision"] == "continue"

    def test_no_session_json_exits_cleanly(self, tmp_path):
        import subprocess
        result = subprocess.run(
            [sys.executable, STOP_HOOK_PATH],
            input=json.dumps({"cwd": str(tmp_path), "stop_hook_active": False}),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# Duplicate pending files not re-added
# ---------------------------------------------------------------------------


class TestDuplicatePendingFilesNotAdded:
    def test_existing_pending_not_duplicated(self, tmp_path):
        src = tmp_path / "billing.py"
        src.write_text("def billing(): pass\n")
        session = _base_session(
            tmp_path,
            turn_start_mtime=time.time() - 10,
            pending_files=[{"path": "billing.py", "language": "python", "status": "new-file"}],
        )
        _write_session(tmp_path, session)
        _run_hook(tmp_path, _event(tmp_path))
        with open(tmp_path / ".tailtest" / "session.json") as fh:
            saved = json.load(fh)
        paths = [p["path"] for p in saved["pending_files"]]
        assert paths.count("billing.py") == 1

    def test_all_already_pending_returns_continue(self, tmp_path):
        src = tmp_path / "billing.py"
        src.write_text("def billing(): pass\n")
        session = _base_session(
            tmp_path,
            turn_start_mtime=time.time() - 10,
            pending_files=[{"path": "billing.py", "language": "python", "status": "new-file"}],
        )
        _write_session(tmp_path, session)
        out = _run_hook(tmp_path, _event(tmp_path))
        # All detected files were already in pending -- no new files, so continue
        assert out["decision"] == "continue"
