import json
import os
import re
import shutil
import stat
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
                command = handler["command"]
                command_windows = handler["commandWindows"]
                assert "${PLUGIN_ROOT}" in command
                assert "%PLUGIN_ROOT%" in command_windows
                assert "TAILTEST_PROJECT_CWD" in command
                assert "TAILTEST_PROJECT_CWD" in command_windows
                assert "cd --" in command
                assert "cd /d" in command_windows
                assert "$HOME" not in command
                script_name = Path(command.rsplit("/", 1)[-1].rstrip('"'))
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
    assert (tmp_path / ".tailtest" / "session.json").is_file()
    assert not (tmp_path / "AGENTS.md").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows executable lookup")
@pytest.mark.parametrize("event_name", ["SessionStart", "PostToolUse", "Stop"])
def test_windows_manifest_commands_ignore_project_python_shim(tmp_path, event_name):
    marker = f"SHADOW_PYTHON_{event_name}"
    (tmp_path / "python.cmd").write_text(
        f"@echo off\r\necho {marker}\r\nexit /b 0\r\n",
        encoding="utf-8",
    )
    handler = _hooks()[event_name][0]["hooks"][0]
    env = os.environ.copy()
    env["PLUGIN_ROOT"] = str(PLUGIN_ROOT)

    result = subprocess.run(
        f'cmd.exe /D /S /C "{handler["commandWindows"]}"',
        input="{}",
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert marker not in result.stdout


def test_initializer_materializes_absolute_project_hook_commands(tmp_path):
    git_bash = Path(os.environ.get("ProgramFiles", "")) / "Git" / "bin" / "bash.exe"
    bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
    if not bash or (
        os.name == "nt"
        and Path(bash).name.lower() == "bash.exe"
        and "system32" in bash.lower()
    ):
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

    if os.name == "nt":
        marker = "SHADOW_PYTHON_INITIALIZED"
        (tmp_path / "python.cmd").write_text(
            f"@echo off\r\necho {marker}\r\nexit /b 0\r\n",
            encoding="utf-8",
        )
        command = installed["hooks"]["SessionStart"][0]["hooks"][0]["commandWindows"]
        hook = subprocess.run(
            f'cmd.exe /D /S /C "{command}"',
            input=json.dumps({"source": "startup", "cwd": str(tmp_path)}),
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert hook.returncode == 0, hook.stderr
        assert marker not in hook.stdout


def test_initializer_does_not_execute_project_path_helpers(tmp_path):
    git_bash = Path(os.environ.get("ProgramFiles", "")) / "Git" / "bin" / "bash.exe"
    bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
    if not bash or (
        os.name == "nt"
        and Path(bash).name.lower() == "bash.exe"
        and "system32" in bash.lower()
    ):
        pytest.skip("bash is unavailable")

    marker = tmp_path / "project-path-helper-ran"
    for name in (
        "dirname",
        "python3",
        "python",
        "cygpath",
        "readlink",
        "mkdir",
        "mktemp",
        "rm",
        "cmp",
        "cp",
        "grep",
    ):
        helper = tmp_path / name
        helper.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' 'fake-{name}-ran' >> \"$TAILTEST_INIT_MARKER\"\n"
            "exit 0\n",
            encoding="utf-8",
        )
        helper.chmod(helper.stat().st_mode | stat.S_IEXEC)

    env = os.environ.copy()
    env["PATH"] = str(tmp_path) + os.pathsep + env.get("PATH", "")
    env["TAILTEST_INIT_MARKER"] = str(marker)

    result = subprocess.run(
        [bash, str(PLUGIN_ROOT / "scripts" / "init.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert not marker.exists(), marker.read_text(encoding="utf-8")
    assert result.returncode == 0, result.stderr
    installed = json.loads((tmp_path / ".codex" / "hooks.json").read_text())
    assert "SessionStart" in installed["hooks"]


def test_initializer_does_not_execute_project_symlinked_readlink_helper(
    tmp_path, tmp_path_factory
):
    git_bash = Path(os.environ.get("ProgramFiles", "")) / "Git" / "bin" / "bash.exe"
    bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
    if not bash or (
        os.name == "nt"
        and Path(bash).name.lower() == "bash.exe"
        and "system32" in bash.lower()
    ):
        pytest.skip("bash is unavailable")

    marker = tmp_path / "project-readlink-helper-ran"
    project_readlink = tmp_path / "readlink"
    project_readlink.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' 'fake-readlink-ran' >> \"$TAILTEST_INIT_MARKER\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    project_readlink.chmod(project_readlink.stat().st_mode | stat.S_IEXEC)

    outside_bin = tmp_path_factory.mktemp("outside-bin")
    outside_readlink = outside_bin / "readlink"
    try:
        outside_readlink.symlink_to(project_readlink)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    env = os.environ.copy()
    env["PATH"] = os.pathsep.join(
        [str(outside_bin), str(tmp_path), env.get("PATH", "")]
    )
    env["TAILTEST_INIT_MARKER"] = str(marker)

    result = subprocess.run(
        [bash, str(PLUGIN_ROOT / "scripts" / "init.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert not marker.exists(), marker.read_text(encoding="utf-8")
    assert result.returncode == 0, result.stderr
    installed = json.loads((tmp_path / ".codex" / "hooks.json").read_text())
    assert "SessionStart" in installed["hooks"]


def test_initializer_preserves_conflicting_hooks_as_sidecar(tmp_path):
    git_bash = Path(os.environ.get("ProgramFiles", "")) / "Git" / "bin" / "bash.exe"
    bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
    if not bash or (
        os.name == "nt"
        and Path(bash).name.lower() == "bash.exe"
        and "system32" in bash.lower()
    ):
        pytest.skip("bash is unavailable")

    existing = tmp_path / ".codex" / "hooks.json"
    existing.parent.mkdir()
    existing.write_text('{"hooks":{"Stop":[]}}', encoding="utf-8")

    result = subprocess.run(
        [bash, str(PLUGIN_ROOT / "scripts" / "init.sh")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert existing.read_text(encoding="utf-8") == '{"hooks":{"Stop":[]}}'
    sidecar = existing.with_name("hooks.json.tailtest")
    assert sidecar.is_file()
    assert "PLUGIN_ROOT" not in sidecar.read_text(encoding="utf-8")


def test_initializer_fails_cleanly_when_python_is_unavailable(
    tmp_path, tmp_path_factory
):
    git_bash = Path(os.environ.get("ProgramFiles", "")) / "Git" / "bin" / "bash.exe"
    bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
    if not bash or (
        os.name == "nt"
        and Path(bash).name.lower() == "bash.exe"
        and "system32" in bash.lower()
    ):
        pytest.skip("bash is unavailable")

    fake_bin = tmp_path_factory.mktemp("no-python-bin")
    for name in ("python", "python3"):
        fake_python = fake_bin / name
        fake_python.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        fake_python.chmod(fake_python.stat().st_mode | stat.S_IEXEC)
    env = os.environ.copy()
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")

    result = subprocess.run(
        [bash, str(PLUGIN_ROOT / "scripts" / "init.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Python is required" in result.stdout
