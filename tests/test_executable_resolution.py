import os
import shutil
import sys
from pathlib import Path

import pytest

from hooks.lib import scanner, session
from hooks.lib.executables import resolve_trusted_executable


def _install_executable(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    suffix = ".exe" if os.name == "nt" else ""
    target = directory / f"{name}{suffix}"
    if os.name == "nt":
        shutil.copy2(sys.executable, target)
    else:
        target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        target.chmod(0o755)
    return target


def test_resolver_skips_project_contained_path_entries(tmp_path, monkeypatch):
    project = tmp_path / "project"
    trusted_bin = tmp_path / "trusted-bin"
    project.mkdir()
    project_git = _install_executable(project, "git")
    trusted_git = _install_executable(trusted_bin, "git")
    monkeypatch.setenv("PATH", os.pathsep.join((str(project), str(trusted_bin))))
    if os.name == "nt":
        monkeypatch.setenv("PATHEXT", ".EXE")
    monkeypatch.chdir(project)

    resolved = resolve_trusted_executable("git", str(project))

    assert resolved is not None
    assert Path(resolved).samefile(trusted_git)
    assert not Path(resolved).samefile(project_git)


def test_resolver_returns_none_when_only_match_is_inside_project(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    _install_executable(project, "git")
    monkeypatch.setenv("PATH", str(project))
    if os.name == "nt":
        monkeypatch.setenv("PATHEXT", ".EXE")

    assert resolve_trusted_executable("git", str(project)) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows current-directory lookup")
def test_scanner_does_not_execute_project_git_exe(tmp_path, monkeypatch):
    project = tmp_path / "scanner-project"
    project.mkdir()
    (project / ".git").mkdir()
    shutil.copy2(sys.executable, project / "git.exe")
    (project / "rev-parse").write_text(
        "from pathlib import Path\n"
        "Path('rev-parse-called').write_text('called')\n"
        "print('true')\n",
        encoding="utf-8",
    )
    (project / "status").write_text(
        "from pathlib import Path\nPath('status-called').write_text('called')\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(project)

    scanner._git_changed_paths(str(project))

    assert not (project / "rev-parse-called").exists()
    assert not (project / "status-called").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows current-directory lookup")
def test_status_does_not_execute_project_git_exe(tmp_path, monkeypatch):
    project = tmp_path / "status-project"
    project.mkdir()
    (project / ".git").mkdir()
    source = project / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    shutil.copy2(sys.executable, project / "git.exe")
    (project / "ls-files").write_text(
        "from pathlib import Path\nPath('ls-files-called').write_text('called')\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(project)

    session.is_git_tracked(str(source), str(project))

    assert not (project / "ls-files-called").exists()
