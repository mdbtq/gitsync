"""Tests for how `gitsync sync` and `gitsync status` treat a skipped repo."""

from __future__ import annotations

from pathlib import Path

import pytest

from gitsync import cli
from gitsync.cli import main
from gitsync.sync import Status, SyncResult

from conftest import GIT_AVAILABLE, init_repo, run_git

pytestmark = pytest.mark.skipif(not GIT_AVAILABLE, reason="git binary not available")


@pytest.fixture
def no_notify(monkeypatch):
    """Capture desktop notifications instead of sending them."""
    sent = []
    monkeypatch.setattr(cli, "notify", lambda *args: sent.append(args))
    return sent


@pytest.fixture
def cfg_with_repo(tmp_path):
    """A config pointing at one repo with a local bare remote, logs in tmp_path.

    The remote is a bare repo on disk, so nothing here touches the network.
    """
    bare = tmp_path / "remote.git"
    bare.mkdir()
    run_git(bare, "init", "--bare", "--initial-branch=main", "--quiet")

    repo = init_repo(tmp_path / "repo")
    run_git(repo, "remote", "add", "origin", str(bare))
    run_git(repo, "push", "--quiet", "--set-upstream", "origin", "main")

    cfg = tmp_path / "config.toml"
    log = tmp_path / "gitsync.log"
    cfg.write_text(
        f'log_file = "{log}"\n\n[[repo]]\npath = "{repo}"\nbranches = ["main"]\n'
    )
    return cfg, repo


def test_cmd_sync_with_a_skipped_repo_exits_zero_and_does_not_notify(
    cfg_with_repo, no_notify, monkeypatch
):
    cfg, repo = cfg_with_repo
    run_git(repo, "checkout", "--quiet", "-b", "feature/x")
    monkeypatch.setattr(
        cli,
        "sync_repo",
        lambda r: SyncResult(r.path, Status.SKIPPED, "branch 'feature/x' is not configured for syncing"),
    )

    assert main(["-c", str(cfg), "sync"]) == 0
    assert no_notify == []


def test_cmd_sync_with_a_real_skipped_repo_exits_zero_and_does_not_notify(
    cfg_with_repo, no_notify
):
    """The same, driven end to end through the real sync_repo."""
    cfg, repo = cfg_with_repo
    run_git(repo, "checkout", "--quiet", "-b", "feature/x")
    (repo / "wip.txt").write_text("wip\n")

    head_before = run_git(repo, "rev-parse", "HEAD")

    assert main(["-c", str(cfg), "sync"]) == 0
    assert no_notify == []
    # The repo was left exactly as it was.
    assert (repo / "wip.txt").read_text() == "wip\n"
    assert run_git(repo, "rev-parse", "HEAD") == head_before


def test_cmd_sync_notifies_and_exits_nonzero_on_a_conflict(cfg_with_repo, no_notify, monkeypatch):
    cfg, repo = cfg_with_repo
    monkeypatch.setattr(
        cli, "sync_repo", lambda r: SyncResult(r.path, Status.CONFLICT, "boom")
    )

    assert main(["-c", str(cfg), "sync"]) == 1
    assert len(no_notify) == 1


def test_cmd_sync_notifies_and_exits_nonzero_on_an_error(cfg_with_repo, no_notify, monkeypatch):
    cfg, repo = cfg_with_repo
    monkeypatch.setattr(
        cli, "sync_repo", lambda r: SyncResult(r.path, Status.ERROR, "boom")
    )

    assert main(["-c", str(cfg), "sync"]) == 1
    assert len(no_notify) == 1


def test_cmd_sync_with_no_repos_configured_exits_zero(tmp_path, no_notify):
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'log_file = "{tmp_path / "gitsync.log"}"\n')

    assert main(["-c", str(cfg), "sync"]) == 0
    assert no_notify == []


def test_cmd_status_marks_an_excluded_branch(cfg_with_repo, capsys):
    cfg, repo = cfg_with_repo
    run_git(repo, "checkout", "--quiet", "-b", "feature/x")

    assert main(["-c", str(cfg), "status"]) == 0
    out = capsys.readouterr().out

    assert "not synced (branch excluded)" in out
    assert "feature/x" in out


def test_cmd_status_reports_a_normal_repo(cfg_with_repo, capsys):
    cfg, repo = cfg_with_repo

    assert main(["-c", str(cfg), "status"]) == 0
    out = capsys.readouterr().out

    assert "not synced (branch excluded)" not in out
    assert "[main]" in out
    assert "clean" in out


def test_cmd_status_flags_local_changes(cfg_with_repo, capsys):
    cfg, repo = cfg_with_repo
    (repo / "README.md").write_text("changed\n")

    assert main(["-c", str(cfg), "status"]) == 0

    assert "local changes" in capsys.readouterr().out


def test_cmd_status_marks_a_missing_repo(tmp_path, capsys):
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'[[repo]]\npath = "{tmp_path / "gone"}"\n')

    assert main(["-c", str(cfg), "status"]) == 0

    assert "not a git repository" in capsys.readouterr().out


def test_a_missing_config_exits_2(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["-c", str(tmp_path / "nope.toml"), "sync"])

    assert exc.value.code == 2
