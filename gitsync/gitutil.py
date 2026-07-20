"""Thin, testable wrappers around the git CLI."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(Exception):
    """A git command exited non-zero."""


@dataclass
class GitResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def git(cwd: Path, *args: str, check: bool = False) -> GitResult:
    """Run a git command in ``cwd`` and capture its output."""
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    result = GitResult(proc.returncode, proc.stdout.strip(), proc.stderr.strip())
    if check and not result.ok:
        raise GitError(
            f"git {' '.join(args)} failed in {cwd}: {result.stderr or result.stdout}"
        )
    return result


def is_git_repo(cwd: Path) -> bool:
    return git(cwd, "rev-parse", "--is-inside-work-tree").stdout == "true"


def current_branch(cwd: Path) -> str | None:
    """Return the checked-out branch, or None if detached."""
    res = git(cwd, "symbolic-ref", "--short", "-q", "HEAD")
    return res.stdout or None


def is_dirty(cwd: Path) -> bool:
    """True if there are staged, unstaged, or untracked changes."""
    return bool(git(cwd, "status", "--porcelain").stdout)


def remote_exists(cwd: Path, remote: str) -> bool:
    return remote in git(cwd, "remote").stdout.split()


def remote_branch_exists(cwd: Path, remote: str, branch: str) -> bool:
    return git(
        cwd, "rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}"
    ).ok
