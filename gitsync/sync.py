"""Core sync logic: one bidirectional pass over a single git working tree."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .config import RepoConfig
from .gitutil import (
    current_branch,
    git,
    is_dirty,
    is_git_repo,
    remote_branch_exists,
    remote_exists,
)


class Status(Enum):
    OK = "ok"              # sync completed (may or may not have transferred anything)
    SKIPPED = "skipped"    # nothing attempted (e.g. branch not in the allow-list)
    CONFLICT = "conflict"  # merge conflict left for manual resolution
    ERROR = "error"        # something went wrong (not a repo, network, etc.)


@dataclass
class SyncResult:
    repo: Path
    status: Status
    message: str


def _commit_message() -> str:
    host = socket.gethostname()
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    return f"gitsync: auto-commit on {host} at {stamp}"


def sync_repo(repo: RepoConfig) -> SyncResult:
    """Run a full bidirectional sync pass for one repository.

    Order of operations is chosen so local work is committed *before* any merge,
    guaranteeing that nothing in the working tree can be lost:

    1. fetch the remote
    2. commit any local changes
    3. merge the remote branch into the local branch
    4. push

    Repos configured with a ``branches`` allow-list are skipped entirely while a
    branch outside it is checked out — no fetch, no commit, no push.
    """
    path = repo.path
    fail = lambda msg: SyncResult(path, Status.ERROR, msg)

    if not path.exists():
        return fail(f"path does not exist: {path}")
    if not is_git_repo(path):
        return fail(f"not a git repository: {path}")
    if not remote_exists(path, repo.remote):
        return fail(f"remote {repo.remote!r} not configured")

    branch = current_branch(path)
    if branch is None:
        return fail("detached HEAD; check out a branch to sync")

    # Checked before anything touches the network or the working tree, so an
    # excluded branch is left exactly as the user left it.
    if not repo.syncs_branch(branch):
        return SyncResult(
            path, Status.SKIPPED, f"branch {branch!r} is not configured for syncing"
        )

    fetch = git(path, "fetch", "--quiet", repo.remote, branch)
    # A missing remote branch is fine (first push); other fetch errors are not.
    if not fetch.ok and remote_branch_exists(path, repo.remote, branch):
        return fail(f"fetch failed: {fetch.stderr}")

    committed = False
    if is_dirty(path):
        git(path, "add", "-A", check=True)
        commit = git(path, "commit", "-m", _commit_message())
        # An empty commit (only ignored/unmergeable changes) is a no-op, not an error.
        committed = commit.ok

    if not remote_branch_exists(path, repo.remote, branch):
        return _push(path, repo.remote, branch, set_upstream=True)

    result = _merge(path, repo, branch)
    if result is not None:
        return result

    return _push(path, repo.remote, branch, moved=committed)


def _merge(path: Path, repo: RepoConfig, branch: str) -> SyncResult | None:
    """Merge the remote branch in. Returns a SyncResult only on conflict/error."""
    remote_ref = f"{repo.remote}/{branch}"

    args = ["merge", "--no-edit"]
    if repo.conflict in ("ours", "theirs"):
        args += ["-X", repo.conflict]
    args.append(remote_ref)

    merge = git(path, *args)
    if merge.ok:
        return None

    # Merge failed. With ours/theirs the only non-conflict failure is unusual,
    # but in every case an in-progress merge means unresolved conflicts.
    if is_dirty(path) or git(path, "rev-parse", "--verify", "-q", "MERGE_HEAD").ok:
        git(path, "merge", "--abort")
        return SyncResult(
            path,
            Status.CONFLICT,
            f"merge conflict with {remote_ref}; resolve manually then re-run",
        )
    return SyncResult(path, Status.ERROR, f"merge failed: {merge.stderr}")


def _push(
    path: Path,
    remote: str,
    branch: str,
    *,
    set_upstream: bool = False,
    moved: bool = True,
) -> SyncResult:
    # Nothing new to publish: local and remote already match.
    if not set_upstream and not moved:
        ahead = git(path, "rev-list", "--count", f"{remote}/{branch}..HEAD").stdout
        if ahead == "0":
            return SyncResult(path, Status.OK, "up to date")

    args = ["push"]
    if set_upstream:
        args += ["--set-upstream"]
    args += [remote, branch]

    push = git(path, *args)
    if push.ok:
        return SyncResult(path, Status.OK, "synced")
    return SyncResult(path, Status.ERROR, f"push failed: {push.stderr}")
