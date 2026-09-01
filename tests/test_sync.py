"""Integration tests for sync_repo against real git repositories.

These build a bare repo in ``tmp_path`` as the "remote" and clone it twice to
simulate two machines. The git CLI is deliberately not mocked: the interesting
behaviour is exactly what git does with merges and pushes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gitsync.config import RepoConfig
from gitsync.gitutil import git, is_dirty
from gitsync.sync import Status, sync_repo

from conftest import GIT_AVAILABLE, configure_identity, run_git

pytestmark = pytest.mark.skipif(not GIT_AVAILABLE, reason="git binary not available")


@pytest.fixture
def remote(tmp_path) -> Path:
    """A bare repository standing in for the shared remote."""
    path = tmp_path / "remote.git"
    path.mkdir()
    run_git(path, "init", "--bare", "--initial-branch=main", "--quiet")
    return path


@pytest.fixture
def clones(tmp_path, remote) -> tuple[Path, Path]:
    """Two clones of ``remote``, both on ``main`` with one shared commit."""
    one = tmp_path / "machine-one"
    run_git(tmp_path, "clone", "--quiet", str(remote), str(one))
    configure_identity(one)
    (one / "notes.md").write_text("line one\nline two\nline three\n")
    run_git(one, "add", "-A")
    run_git(one, "commit", "--quiet", "-m", "seed")
    run_git(one, "push", "--quiet", "--set-upstream", "origin", "main")

    two = tmp_path / "machine-two"
    run_git(tmp_path, "clone", "--quiet", str(remote), str(two))
    configure_identity(two)
    return one, two


def repo_config(
    path: Path, conflict: str = "manual", branches: tuple[str, ...] = ()
) -> RepoConfig:
    return RepoConfig(path=path, conflict=conflict, branches=branches)


def read_remote(remote: Path, filename: str, branch: str = "main") -> str:
    return git(remote, "show", f"{branch}:{filename}").stdout


def in_progress_merge(path: Path) -> bool:
    return (path / ".git" / "MERGE_HEAD").exists()


# --------------------------------------------------------------------------
# happy paths
# --------------------------------------------------------------------------

def test_clean_sync_is_a_no_op(clones):
    one, _ = clones

    result = sync_repo(repo_config(one))

    assert result.status is Status.OK
    assert result.message == "up to date"


def test_local_changes_are_committed_and_pushed(clones, remote):
    one, _ = clones
    (one / "notes.md").write_text("line one changed\nline two\nline three\n")

    result = sync_repo(repo_config(one))

    assert result.status is Status.OK
    assert result.message == "synced"
    assert not is_dirty(one)
    assert read_remote(remote, "notes.md").startswith("line one changed")
    assert "gitsync: auto-commit on" in git(one, "log", "-1", "--pretty=%s").stdout


def test_an_untracked_file_is_committed_and_pushed(clones, remote):
    one, _ = clones
    (one / "new.md").write_text("brand new\n")

    result = sync_repo(repo_config(one))

    assert result.status is Status.OK
    assert read_remote(remote, "new.md") == "brand new"


def test_remote_changes_are_merged_in(clones):
    one, two = clones
    (two / "notes.md").write_text("line one\nline two\nline three\nline four\n")
    run_git(two, "add", "-A")
    run_git(two, "commit", "--quiet", "-m", "from machine two")
    run_git(two, "push", "--quiet", "origin", "main")

    result = sync_repo(repo_config(one))

    assert result.status is Status.OK
    assert (one / "notes.md").read_text().endswith("line four\n")


def test_non_conflicting_changes_from_both_sides_are_merged(clones, remote):
    one, two = clones
    (two / "from-two.md").write_text("two\n")
    run_git(two, "add", "-A")
    run_git(two, "commit", "--quiet", "-m", "from two")
    run_git(two, "push", "--quiet", "origin", "main")

    (one / "from-one.md").write_text("one\n")

    result = sync_repo(repo_config(one))

    assert result.status is Status.OK
    assert result.message == "synced"
    assert (one / "from-two.md").exists()
    assert read_remote(remote, "from-one.md") == "one"
    assert read_remote(remote, "from-two.md") == "two"


def test_first_push_of_a_branch_without_an_upstream(clones, remote):
    one, _ = clones
    run_git(one, "checkout", "--quiet", "-b", "side")
    (one / "side.md").write_text("side work\n")

    result = sync_repo(repo_config(one))

    assert result.status is Status.OK
    assert result.message == "synced"
    assert read_remote(remote, "side.md", branch="side") == "side work"
    assert git(one, "rev-parse", "--abbrev-ref", "side@{upstream}").stdout == "origin/side"


def test_a_second_pass_after_a_first_push_is_a_no_op(clones):
    one, _ = clones
    run_git(one, "checkout", "--quiet", "-b", "side")
    (one / "side.md").write_text("side work\n")

    assert sync_repo(repo_config(one)).status is Status.OK
    second = sync_repo(repo_config(one))

    assert second.status is Status.OK
    assert second.message == "up to date"


# --------------------------------------------------------------------------
# conflicts
# --------------------------------------------------------------------------

def make_conflict(clones) -> Path:
    """Both machines edit the same line; only machine two has pushed."""
    one, two = clones
    (two / "notes.md").write_text("line one from TWO\nline two\nline three\n")
    run_git(two, "add", "-A")
    run_git(two, "commit", "--quiet", "-m", "two edits line one")
    run_git(two, "push", "--quiet", "origin", "main")

    (one / "notes.md").write_text("line one from ONE\nline two\nline three\n")
    return one


def test_manual_conflict_reports_and_leaves_no_merge_in_progress(clones):
    one = make_conflict(clones)

    result = sync_repo(repo_config(one, conflict="manual"))

    assert result.status is Status.CONFLICT
    assert "resolve manually" in result.message
    assert not in_progress_merge(one)
    assert "<<<<<<<" not in (one / "notes.md").read_text()
    # The local edit was committed before the merge, so nothing was lost.
    assert (one / "notes.md").read_text().startswith("line one from ONE")


def test_manual_conflict_does_not_push(clones, remote):
    one = make_conflict(clones)

    assert sync_repo(repo_config(one, conflict="manual")).status is Status.CONFLICT
    assert read_remote(remote, "notes.md").startswith("line one from TWO")


def test_conflict_ours_keeps_the_local_side_and_pushes(clones, remote):
    one = make_conflict(clones)

    result = sync_repo(repo_config(one, conflict="ours"))

    assert result.status is Status.OK
    assert result.message == "synced"
    assert (one / "notes.md").read_text().startswith("line one from ONE")
    assert not in_progress_merge(one)
    assert read_remote(remote, "notes.md").startswith("line one from ONE")


def test_conflict_theirs_keeps_the_remote_side_and_pushes(clones, remote):
    one = make_conflict(clones)

    result = sync_repo(repo_config(one, conflict="theirs"))

    assert result.status is Status.OK
    assert result.message == "synced"
    assert (one / "notes.md").read_text().startswith("line one from TWO")
    assert not in_progress_merge(one)
    assert read_remote(remote, "notes.md").startswith("line one from TWO")


def test_ours_and_theirs_still_merge_non_conflicting_changes(clones):
    one, two = clones
    (two / "notes.md").write_text("line one from TWO\nline two\nline three\nline four\n")
    run_git(two, "add", "-A")
    run_git(two, "commit", "--quiet", "-m", "two edits")
    run_git(two, "push", "--quiet", "origin", "main")

    (one / "notes.md").write_text("line one from ONE\nline two\nline three\n")

    assert sync_repo(repo_config(one, conflict="ours")).status is Status.OK
    text = (one / "notes.md").read_text()

    assert text.startswith("line one from ONE")  # the clashing hunk: ours
    assert "line four" in text  # the non-clashing hunk: merged in anyway


# --------------------------------------------------------------------------
# error paths
# --------------------------------------------------------------------------

def test_missing_path_is_an_error(tmp_path):
    missing = tmp_path / "not-here"

    result = sync_repo(repo_config(missing))

    assert result.status is Status.ERROR
    assert "does not exist" in result.message


def test_a_plain_directory_is_an_error(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()

    result = sync_repo(repo_config(plain))

    assert result.status is Status.ERROR
    assert "not a git repository" in result.message


def test_a_repo_without_the_configured_remote_is_an_error(git_repo):
    result = sync_repo(repo_config(git_repo))

    assert result.status is Status.ERROR
    assert "not configured" in result.message


def test_detached_head_is_an_error(clones):
    one, _ = clones
    run_git(one, "checkout", "--quiet", "--detach", "HEAD")

    result = sync_repo(repo_config(one))

    assert result.status is Status.ERROR
    assert "detached HEAD" in result.message


def test_an_unreachable_remote_is_an_error(clones, remote):
    one, _ = clones
    run_git(one, "remote", "set-url", "origin", str(remote) + "-gone")

    result = sync_repo(repo_config(one))

    assert result.status is Status.ERROR


# --------------------------------------------------------------------------
# branch allow-list
# --------------------------------------------------------------------------

def remote_branches(remote: Path) -> list[str]:
    out = git(remote, "for-each-ref", "--format=%(refname:short)", "refs/heads").stdout
    return out.split()


def test_an_excluded_branch_leaves_the_repo_completely_untouched(clones, remote):
    """The allow-list check runs before fetch/commit/merge/push."""
    one, _ = clones
    run_git(one, "checkout", "--quiet", "-b", "feature/x")
    (one / "notes.md").write_text("uncommitted work in progress\n")
    (one / "scratch.txt").write_text("untracked\n")

    head_before = git(one, "rev-parse", "HEAD").stdout
    porcelain_before = git(one, "status", "--porcelain").stdout
    remote_before = remote_branches(remote)

    result = sync_repo(repo_config(one, branches=("main",)))

    assert result.status is Status.SKIPPED
    assert "feature/x" in result.message
    assert git(one, "rev-parse", "HEAD").stdout == head_before
    assert git(one, "status", "--porcelain").stdout == porcelain_before
    assert (one / "notes.md").read_text() == "uncommitted work in progress\n"
    assert (one / "scratch.txt").read_text() == "untracked\n"
    assert remote_branches(remote) == remote_before
    assert "feature/x" not in remote_branches(remote)


def test_an_allowed_branch_still_syncs_normally(clones, remote):
    one, _ = clones
    run_git(one, "checkout", "--quiet", "-b", "feature/x")
    (one / "notes.md").write_text("wip\n")

    assert sync_repo(repo_config(one, branches=("main",))).status is Status.SKIPPED

    run_git(one, "checkout", "--quiet", "--force", "main")
    (one / "notes.md").write_text("work on main\n")

    result = sync_repo(repo_config(one, branches=("main",)))

    assert result.status is Status.OK
    assert result.message == "synced"
    assert read_remote(remote, "notes.md") == "work on main"


def test_a_glob_allowed_branch_syncs_and_reaches_the_remote(clones, remote):
    one, _ = clones
    run_git(one, "checkout", "--quiet", "-b", "release/1.0")
    (one / "release-notes.md").write_text("1.0\n")

    result = sync_repo(repo_config(one, branches=("main", "release/*")))

    assert result.status is Status.OK
    assert result.message == "synced"
    assert "release/1.0" in remote_branches(remote)
    assert read_remote(remote, "release-notes.md", branch="release/1.0") == "1.0"


def test_an_empty_allow_list_does_not_restrict_anything(clones):
    one, _ = clones
    run_git(one, "checkout", "--quiet", "-b", "feature/x")

    result = sync_repo(repo_config(one, branches=()))

    assert result.status is not Status.SKIPPED


def test_the_allow_list_check_runs_before_the_remote_is_reached(clones, remote):
    """An excluded branch is skipped even with a broken remote URL."""
    one, _ = clones
    run_git(one, "checkout", "--quiet", "-b", "feature/x")
    run_git(one, "remote", "set-url", "origin", str(remote) + "-gone")

    result = sync_repo(repo_config(one, branches=("main",)))

    assert result.status is Status.SKIPPED
