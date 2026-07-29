import io
import json
import sys
import time

from hooks import session_start as session_start_hook
from hooks.lib.session import save_session


def _base_session(project_root: str, turn_start_mtime: float) -> dict:
    return {
        "session_id": "session-123",
        "started_at": "2026-07-29T00:00:00+00:00",
        "project_root": project_root,
        "runners": {"python": {"command": "pytest", "test_location": "tests/"}},
        "depth": "standard",
        "paused": False,
        "report_path": ".tailtest/reports/session-123.md",
        "pending_files": [{"path": "src/app.py", "language": "python", "status": "new-file"}],
        "touched_files": [],
        "fix_attempts": {"src/app.py": 2},
        "deferred_failures": [],
        "generated_tests": {"src/app.py": "tests/test_app.py"},
        "packages": {},
        "turn_start_mtime": turn_start_mtime,
    }


def _run_session_start(tmp_path, monkeypatch, capsys, payload: dict) -> dict:
    monkeypatch.setattr(session_start_hook, "read_agents_md", lambda _plugin_root: "")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    session_start_hook.main()
    out = capsys.readouterr().out.strip()
    return json.loads(out) if out else {}


def test_compact_rebases_mtime_watermarks_and_preserves_session_state(tmp_path, monkeypatch, capsys):
    before_turn = time.time() - 300
    before_post = time.time() - 150
    session = _base_session(str(tmp_path), before_turn)
    session["post_tool_last_fire_mtime"] = before_post
    save_session(str(tmp_path), session)

    out = _run_session_start(
        tmp_path,
        monkeypatch,
        capsys,
        {"source": "compact", "cwd": str(tmp_path)},
    )

    with open(tmp_path / ".tailtest" / "session.json") as fh:
        saved = json.load(fh)

    assert saved["pending_files"] == session["pending_files"]
    assert saved["fix_attempts"] == session["fix_attempts"]
    assert saved["generated_tests"] == session["generated_tests"]
    assert saved["turn_start_mtime"] > before_turn
    assert saved["post_tool_last_fire_mtime"] > before_post
    assert saved["turn_start_mtime"] == saved["post_tool_last_fire_mtime"]

    note = out["hookSpecificOutput"]["additionalContext"]
    assert "compaction" in note
    assert "src/app.py" in note


def test_compact_adds_post_tool_watermark_when_session_never_saw_a_post_tool_event(tmp_path, monkeypatch, capsys):
    before_turn = time.time() - 300
    session = _base_session(str(tmp_path), before_turn)
    save_session(str(tmp_path), session)

    _run_session_start(
        tmp_path,
        monkeypatch,
        capsys,
        {"source": "compact", "cwd": str(tmp_path)},
    )

    with open(tmp_path / ".tailtest" / "session.json") as fh:
        saved = json.load(fh)

    assert saved["turn_start_mtime"] > before_turn
    assert saved["post_tool_last_fire_mtime"] == saved["turn_start_mtime"]
