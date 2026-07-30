import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
HOOKS_PATH = PLUGIN_ROOT / "hooks" / "hooks.json"


def _hooks() -> dict:
    return json.loads(HOOKS_PATH.read_text(encoding="utf-8"))["hooks"]


def test_session_start_matcher_covers_every_supported_start_source():
    matcher = _hooks()["SessionStart"][0]["matcher"]

    for source in ("startup", "resume", "compact"):
        assert re.fullmatch(matcher, source), source


def test_post_tool_use_matcher_covers_supported_mutating_tools_only():
    matcher = _hooks()["PostToolUse"][0]["matcher"]

    for tool_name in ("Bash", "apply_patch", "Edit", "Write"):
        assert re.fullmatch(matcher, tool_name), tool_name
    assert not re.fullmatch(matcher, "Read")


def test_hook_commands_resolve_scripts_inside_plugin_bundle():
    for groups in _hooks().values():
        for group in groups:
            for handler in group["hooks"]:
                assert "${PLUGIN_ROOT}" in handler["command"]
                assert "%PLUGIN_ROOT%" in handler["commandWindows"]
                assert "$HOME" not in handler["command"]
                script_name = Path(handler["command"].rsplit("/", 1)[-1].rstrip('"'))
                assert (PLUGIN_ROOT / "hooks" / script_name).is_file()


@pytest.mark.skipif(os.name != "nt", reason="Windows command override")
def test_windows_manifest_command_executes_session_start_hook(tmp_path):
    handler = _hooks()["SessionStart"][0]["hooks"][0]
    env = os.environ.copy()
    env["PLUGIN_ROOT"] = str(PLUGIN_ROOT)

    result = subprocess.run(
        f'cmd.exe /D /S /C "{handler["commandWindows"]}"',
        input=json.dumps({"source": "startup", "cwd": str(tmp_path)}),
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (
        json.loads(result.stdout)["hookSpecificOutput"]["hookEventName"]
        == "SessionStart"
    )


def test_initializer_materializes_absolute_project_hook_commands(tmp_path):
    git_bash = Path(os.environ.get("ProgramFiles", "")) / "Git" / "bin" / "bash.exe"
    bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
    if not bash or (os.name == "nt" and "system32" in bash.lower()):
        pytest.skip("bash is unavailable")

    result = subprocess.run(
        [bash, str(PLUGIN_ROOT / "scripts" / "init.sh")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    installed = json.loads((tmp_path / ".codex" / "hooks.json").read_text())
    for groups in installed["hooks"].values():
        for group in groups:
            for handler in group["hooks"]:
                assert "PLUGIN_ROOT" not in handler["command"]
                assert "PLUGIN_ROOT" not in handler["commandWindows"]
                match = re.search(r'"([^"\n]+\.py)"', handler["commandWindows"])
                assert match
                assert Path(match.group(1)).is_file()
