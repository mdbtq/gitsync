"""Shared fixtures.

Every test must stay inside ``tmp_path``: no test may read or write the user's
real ``~/.config``, real repositories, or the network. The ``isolated_home``
fixture is autouse so that any accidental ``~`` expansion lands in ``tmp_path``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

GIT_AVAILABLE = shutil.which("git") is not None


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Point HOME and the XDG dirs at tmp_path so nothing can escape.

    gitsync resolves ``~`` in config paths; without this a bug in a test could
    write into the user's real home directory.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.delenv("GITSYNC_CONFIG", raising=False)
    return home


@pytest.fixture
def example_config_text() -> str:
    """The repo's own config.example.toml: a realistic comment-heavy fixture."""
    return (REPO_ROOT / "config.example.toml").read_text()


def run_git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def init_repo(path: Path) -> Path:
    """Create a git working tree at ``path`` with one commit on ``main``."""
    path.mkdir(parents=True, exist_ok=True)
    run_git(path, "init", "--initial-branch=main", "--quiet")
    configure_identity(path)
    (path / "README.md").write_text("hello\n")
    run_git(path, "add", "-A")
    run_git(path, "commit", "--quiet", "-m", "initial")
    return path


def configure_identity(path: Path) -> None:
    """Set a local identity so commits work regardless of the CI environment."""
    run_git(path, "config", "user.name", "gitsync tests")
    run_git(path, "config", "user.email", "tests@example.invalid")
    run_git(path, "config", "commit.gpgsign", "false")


@pytest.fixture
def git_repo(tmp_path) -> Path:
    return init_repo(tmp_path / "repo")
