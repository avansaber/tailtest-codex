"""Unit tests for hooks/post_tool_use.py -- the PostToolUse hook (v4.9.0+).

Tests cover:
- tool name filtering (mutating vs non-mutating)
- apply_patch payload parsing (unified diff + Codex envelope)
- mtime sweep fallback when payload yields no paths
- intelligence filter (is_filtered, language detection, runner gating)
- pause and missing-session graceful exit
- loop guard against generated test files
- pending_files merge + dedup
- additionalContext output shape
"""

import json
import os
import subprocess
import sys
import time

import pytest

POST_TOOL_HOOK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "hooks", "post_tool_use.py"
)


def _write_session(tmp_path, session: dict) -> None:
    tailtest = tmp_path / ".tailtest"
    tailtest.mkdir(exist_ok=True)
    with open(tailtest / "session.json", "w") as fh:
        json.dump(session, fh)


def _load_session(tmp_path) -> dict:
    with open(tmp_path / ".tailtest" / "session.json") as fh:
        return json.load(fh)


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
        "turn_start_mtime": time.time() - 100,
    }
    session.update(kwargs)
    return session


def _run_hook(tmp_path, event: dict) -> tuple[int, dict]:
    """Run the hook and return (exit_code, parsed_stdout_or_empty)."""
    result = subprocess.run(
        [sys.executable, POST_TOOL_HOOK_PATH],
        input=json.dumps(event),
        capture_output=True,
        check=False,
        text=True,
        cwd=str(tmp_path),
    )
    out: dict = {}
    if result.stdout.strip():
        try:
            out = json.loads(result.stdout)
        except json.JSONDecodeError:
            out = {"raw": result.stdout}
    return result.returncode, out


def _event(
    tmp_path,
    tool_name: str = "apply_patch",
    tool_input: dict | None = None,
    tool_response: dict | None = None,
) -> dict:
    return {
        "session_id": "test-session",
        "cwd": str(tmp_path),
        "tool_name": tool_name,
        "tool_input": tool_input or {},
        "tool_response": tool_response or {},
    }


def _make_py(tmp_path, rel: str, content: str = "def f():\n    pass\n") -> str:
    abs_path = tmp_path / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content)
    return str(abs_path)


def _git(tmp_path, *args: str) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", *args],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"git unavailable or failed: {result.stderr}")
    return result


def _init_git_repo(tmp_path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "tailtest@example.invalid")
    _git(tmp_path, "config", "user.name", "Tailtest")


# -- tool-name filter --------------------------------------------------------


def test_skips_non_mutating_tool(tmp_path):
    """Tools outside the file-mutating whitelist exit silently."""
    _write_session(tmp_path, _base_session(tmp_path))
    _make_py(tmp_path, "src/m.py")
    code, out = _run_hook(tmp_path, _event(tmp_path, tool_name="read_file"))
    assert code == 0
    assert out == {}


def test_skips_unknown_tool(tmp_path):
    _write_session(tmp_path, _base_session(tmp_path))
    _make_py(tmp_path, "src/m.py")
    code, out = _run_hook(tmp_path, _event(tmp_path, tool_name="future_unknown_tool"))
    assert code == 0
    assert out == {}


# -- apply_patch payload parsing --------------------------------------------


def test_apply_patch_unified_diff_extracts_path(tmp_path):
    _write_session(tmp_path, _base_session(tmp_path))
    _make_py(tmp_path, "src/m.py")
    patch = (
        "diff --git a/src/m.py b/src/m.py\n"
        "index abc..def 100644\n"
        "--- a/src/m.py\n"
        "+++ b/src/m.py\n"
        "@@ -1,2 +1,3 @@\n"
        " def f():\n"
        "+    return 1\n"
        "     pass\n"
    )
    code, out = _run_hook(
        tmp_path,
        _event(tmp_path, tool_input={"patch": patch}),
    )
    assert code == 0
    assert "hookSpecificOutput" in out
    assert "src/m.py" in out["hookSpecificOutput"]["additionalContext"]
    session = _load_session(tmp_path)
    assert any(p["path"] == "src/m.py" for p in session["pending_files"])


def test_apply_patch_codex_envelope_extracts_path(tmp_path):
    """The `*** Update File: path` envelope form Codex sometimes uses."""
    _write_session(tmp_path, _base_session(tmp_path))
    _make_py(tmp_path, "src/u.py")
    patch = (
        "*** Begin Patch\n"
        "*** Update File: src/u.py\n"
        "@@\n"
        " def f():\n"
        "-    pass\n"
        "+    return 2\n"
        "*** End Patch\n"
    )
    code, out = _run_hook(
        tmp_path,
        _event(tmp_path, tool_input={"patch": patch}),
    )
    assert code == 0
    assert "src/u.py" in out["hookSpecificOutput"]["additionalContext"]


def test_apply_patch_add_file_envelope(tmp_path):
    _write_session(tmp_path, _base_session(tmp_path))
    _make_py(tmp_path, "src/new.py")
    patch = (
        "*** Begin Patch\n*** Add File: src/new.py\n+def g(): return 1\n*** End Patch\n"
    )
    code, out = _run_hook(
        tmp_path,
        _event(tmp_path, tool_input={"patch": patch}),
    )
    assert code == 0
    assert "src/new.py" in out["hookSpecificOutput"]["additionalContext"]


def test_apply_patch_input_alias_field(tmp_path):
    """Some Codex variants put the patch under tool_input.input instead."""
    _write_session(tmp_path, _base_session(tmp_path))
    _make_py(tmp_path, "src/alias.py")
    patch = "diff --git a/src/alias.py b/src/alias.py\n"
    code, out = _run_hook(
        tmp_path,
        _event(tmp_path, tool_input={"input": patch}),
    )
    assert code == 0
    assert "src/alias.py" in out["hookSpecificOutput"]["additionalContext"]


def test_apply_patch_command_alias_extracts_path_despite_future_watermark(tmp_path):
    """Codex puts apply_patch text in tool_input.command."""
    _write_session(
        tmp_path,
        _base_session(tmp_path, post_tool_last_fire_mtime=time.time() + 3600),
    )
    _make_py(tmp_path, "src/command.py")
    patch = "*** Begin Patch\n*** Update File: src/command.py\n@@\n*** End Patch\n"

    code, out = _run_hook(
        tmp_path,
        _event(tmp_path, tool_input={"command": patch}),
    )

    assert code == 0
    assert "src/command.py" in out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert any(
        p["path"] == "src/command.py" for p in _load_session(tmp_path)["pending_files"]
    )


def test_apply_patch_empty_payload_falls_back_to_sweep(tmp_path):
    """No patch text means we should fall back to mtime sweep."""
    session = _base_session(tmp_path)
    session["turn_start_mtime"] = time.time() - 5
    _write_session(tmp_path, session)
    # Create file AFTER turn_start_mtime so sweep finds it
    time.sleep(0.05)
    _make_py(tmp_path, "src/swept.py")
    code, out = _run_hook(
        tmp_path,
        _event(tmp_path, tool_input={}),
    )
    assert code == 0
    assert "hookSpecificOutput" in out
    assert "src/swept.py" in out["hookSpecificOutput"]["additionalContext"]


def test_shell_tool_uses_mtime_sweep(tmp_path):
    session = _base_session(tmp_path)
    session["turn_start_mtime"] = time.time() - 5
    _write_session(tmp_path, session)
    time.sleep(0.05)
    _make_py(tmp_path, "src/via_shell.py")
    code, out = _run_hook(
        tmp_path,
        _event(tmp_path, tool_name="shell", tool_input={"cmd": "..."}),
    )
    assert code == 0
    assert "src/via_shell.py" in out["hookSpecificOutput"]["additionalContext"]


def test_canonical_bash_tool_uses_mtime_sweep(tmp_path):
    """Codex reports shell and unified-exec hooks under the Bash tool name."""
    session = _base_session(tmp_path)
    session["turn_start_mtime"] = time.time() - 5
    _write_session(tmp_path, session)
    time.sleep(0.05)
    _make_py(tmp_path, "src/via_bash.py")
    code, out = _run_hook(
        tmp_path,
        _event(
            tmp_path,
            tool_name="Bash",
            tool_input={"command": "python -c \"open('src/via_bash.py', 'w')\""},
        ),
    )
    assert code == 0
    assert "src/via_bash.py" in out["hookSpecificOutput"]["additionalContext"]


def test_bash_command_patch_like_text_does_not_parse_as_patch(tmp_path):
    """Shell command text is untrusted command data, not a patch payload."""
    _write_session(
        tmp_path,
        _base_session(tmp_path, post_tool_last_fire_mtime=time.time() + 3600),
    )
    _make_py(tmp_path, "src/not_changed.py")
    patch_like_command = (
        "*** Begin Patch\n*** Update File: src/not_changed.py\n@@\n*** End Patch\n"
    )

    code, out = _run_hook(
        tmp_path,
        _event(
            tmp_path,
            tool_name="Bash",
            tool_input={"command": patch_like_command},
        ),
    )

    assert code == 0
    assert out == {}
    assert _load_session(tmp_path)["pending_files"] == []


def test_shell_mtime_sweep_skips_clean_tracked_file_churn(tmp_path):
    _init_git_repo(tmp_path)
    src = tmp_path / "src" / "clean.py"
    src.parent.mkdir()
    src.write_text("def clean():\n    return 1\n")
    _git(tmp_path, "add", "src/clean.py")
    _git(tmp_path, "commit", "-m", "init")
    baseline = time.time() - 5
    os.utime(src, None)
    session = _base_session(
        tmp_path,
        turn_start_mtime=baseline,
        post_tool_last_fire_mtime=baseline,
    )
    _write_session(tmp_path, session)

    code, out = _run_hook(
        tmp_path,
        _event(tmp_path, tool_name="Bash", tool_input={"command": "git pull"}),
    )

    assert code == 0
    assert out == {}
    assert _load_session(tmp_path)["pending_files"] == []


def test_shell_mtime_sweep_queues_dirty_tracked_file_as_legacy(tmp_path):
    _init_git_repo(tmp_path)
    src = tmp_path / "src" / "dirty.py"
    src.parent.mkdir()
    src.write_text("def dirty():\n    return 1\n")
    _git(tmp_path, "add", "src/dirty.py")
    _git(tmp_path, "commit", "-m", "init")
    baseline = time.time()
    time.sleep(0.05)
    src.write_text("def dirty():\n    return 2\n")
    session = _base_session(
        tmp_path,
        turn_start_mtime=baseline,
        post_tool_last_fire_mtime=baseline,
    )
    _write_session(tmp_path, session)

    code, out = _run_hook(
        tmp_path,
        _event(tmp_path, tool_name="Bash", tool_input={"command": "python edit.py"}),
    )

    assert code == 0
    assert "src/dirty.py" in out["hookSpecificOutput"]["additionalContext"]
    assert '"status": "legacy-file"' in out["hookSpecificOutput"]["additionalContext"]
    assert _load_session(tmp_path)["pending_files"] == [
        {"path": "src/dirty.py", "language": "python", "status": "legacy-file"}
    ]


# -- session state handling -------------------------------------------------


def test_paused_session_exits_silent(tmp_path):
    session = _base_session(tmp_path, paused=True)
    _write_session(tmp_path, session)
    _make_py(tmp_path, "src/m.py")
    patch = "diff --git a/src/m.py b/src/m.py\n"
    code, out = _run_hook(
        tmp_path,
        _event(tmp_path, tool_input={"patch": patch}),
    )
    assert code == 0
    assert out == {}


def test_no_session_exits_silent(tmp_path):
    """If .tailtest/session.json doesn't exist, hook is a no-op."""
    _make_py(tmp_path, "src/m.py")
    patch = "diff --git a/src/m.py b/src/m.py\n"
    code, out = _run_hook(
        tmp_path,
        _event(tmp_path, tool_input={"patch": patch}),
    )
    assert code == 0
    assert out == {}


def test_empty_session_exits_silent(tmp_path):
    """If session has no runners and no id, treat as inactive."""
    _write_session(tmp_path, {"paused": False})
    _make_py(tmp_path, "src/m.py")
    patch = "diff --git a/src/m.py b/src/m.py\n"
    code, out = _run_hook(
        tmp_path,
        _event(tmp_path, tool_input={"patch": patch}),
    )
    assert code == 0
    assert out == {}


# -- intelligence filter ----------------------------------------------------


def test_filtered_file_not_queued(tmp_path):
    """Test files themselves should not be queued."""
    _write_session(tmp_path, _base_session(tmp_path))
    _make_py(tmp_path, "tests/test_x.py")
    patch = "diff --git a/tests/test_x.py b/tests/test_x.py\n"
    code, out = _run_hook(
        tmp_path,
        _event(tmp_path, tool_input={"patch": patch}),
    )
    assert code == 0
    assert out == {}
    session = _load_session(tmp_path)
    assert session["pending_files"] == []


def test_unknown_language_not_queued(tmp_path):
    _write_session(tmp_path, _base_session(tmp_path))
    p = tmp_path / "notes.txt"
    p.write_text("not code")
    patch = "diff --git a/notes.txt b/notes.txt\n"
    code, out = _run_hook(
        tmp_path,
        _event(tmp_path, tool_input={"patch": patch}),
    )
    assert code == 0
    assert out == {}


def test_runner_required_language_without_runner_skipped(tmp_path):
    """Java needs an explicit runner; without one, skip."""
    session = _base_session(tmp_path)
    # Note: only python runner is configured, no java
    _write_session(tmp_path, session)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "X.java").write_text("class X {}\n")
    patch = "diff --git a/src/X.java b/src/X.java\n"
    code, out = _run_hook(
        tmp_path,
        _event(tmp_path, tool_input={"patch": patch}),
    )
    assert code == 0
    assert out == {}


# -- loop guard -------------------------------------------------------------


def test_generated_test_file_not_requeued(tmp_path):
    """If apply_patch modifies a file that is a generated test, do not queue it."""
    session = _base_session(tmp_path)
    session["generated_tests"] = {"src/m.py": "tests/test_m.py"}
    _write_session(tmp_path, session)
    _make_py(tmp_path, "tests/test_m.py")
    patch = "diff --git a/tests/test_m.py b/tests/test_m.py\n"
    code, out = _run_hook(
        tmp_path,
        _event(tmp_path, tool_input={"patch": patch}),
    )
    assert code == 0
    assert out == {}


# -- pending_files merge ---------------------------------------------------


def test_existing_pending_file_not_duplicated(tmp_path):
    session = _base_session(tmp_path)
    session["pending_files"] = [
        {"path": "src/m.py", "language": "python", "status": "new-file"}
    ]
    _write_session(tmp_path, session)
    _make_py(tmp_path, "src/m.py")
    patch = "diff --git a/src/m.py b/src/m.py\n"
    code, out = _run_hook(
        tmp_path,
        _event(tmp_path, tool_input={"patch": patch}),
    )
    assert code == 0
    # Already pending = nothing newly queued = silent
    assert out == {}
    session = _load_session(tmp_path)
    assert len([p for p in session["pending_files"] if p["path"] == "src/m.py"]) == 1


def test_multi_file_patch_queues_all(tmp_path):
    _write_session(tmp_path, _base_session(tmp_path))
    _make_py(tmp_path, "src/a.py")
    _make_py(tmp_path, "src/b.py")
    patch = "diff --git a/src/a.py b/src/a.py\ndiff --git a/src/b.py b/src/b.py\n"
    code, out = _run_hook(
        tmp_path,
        _event(tmp_path, tool_input={"patch": patch}),
    )
    assert code == 0
    note = out["hookSpecificOutput"]["additionalContext"]
    assert "src/a.py" in note
    assert "src/b.py" in note
    assert '"status": "new-file"' in note
    assert "queued 2 file(s)" in note
    session = _load_session(tmp_path)
    paths = sorted(p["path"] for p in session["pending_files"])
    assert paths == ["src/a.py", "src/b.py"]


# -- output shape ----------------------------------------------------------


def test_output_uses_hook_specific_output_shape(tmp_path):
    """Output must be the additionalContext envelope, not decision=block."""
    _write_session(tmp_path, _base_session(tmp_path))
    _make_py(tmp_path, "src/x.py")
    patch = "diff --git a/src/x.py b/src/x.py\n"
    code, out = _run_hook(
        tmp_path,
        _event(tmp_path, tool_input={"patch": patch}),
    )
    assert code == 0
    assert "hookSpecificOutput" in out
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "additionalContext" in out["hookSpecificOutput"]
    # Must NOT be a blocking decision; mid-turn surfacing is non-blocking.
    assert "decision" not in out


def test_post_tool_watermark_advanced(tmp_path):
    """Each fire should advance post_tool_last_fire_mtime."""
    session = _base_session(tmp_path)
    session["post_tool_last_fire_mtime"] = 1.0
    _write_session(tmp_path, session)
    _make_py(tmp_path, "src/m.py")
    patch = "diff --git a/src/m.py b/src/m.py\n"
    _run_hook(tmp_path, _event(tmp_path, tool_input={"patch": patch}))
    session = _load_session(tmp_path)
    assert session["post_tool_last_fire_mtime"] > 1.0


def test_malformed_event_exits_silent(tmp_path):
    """A garbage stdin payload should not crash; should exit silent."""
    result = subprocess.run(
        [sys.executable, POST_TOOL_HOOK_PATH],
        input="not json {{{",
        capture_output=True,
        check=False,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""
