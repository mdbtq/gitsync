"""Tests for the config-file editing commands (`add` / `remove`).

These assert on the EXACT resulting file text, not merely that the result still
parses: the blank-line and comment handling in ``_find_repo_block`` is the part
that has regressed before.

Every invocation passes ``-c`` explicitly so ``DEFAULT_CONFIG_PATH`` is never
touched.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from gitsync import launchd
from gitsync.cli import main

from conftest import init_repo

THREE_REPOS = (
    "interval = 300\n"
    "\n"
    "[[repo]]\n"
    'path = "/tmp/a"\n'
    "\n"
    "[[repo]]\n"
    'path = "/tmp/b"\n'
    "\n"
    "[[repo]]\n"
    'path = "/tmp/c"\n'
)


@pytest.fixture
def cfg(tmp_path) -> Path:
    return tmp_path / "config.toml"


def write(cfg: Path, text: str) -> Path:
    cfg.write_text(text)
    return cfg


def remove(cfg: Path, directory: str) -> int:
    return main(["-c", str(cfg), "remove", directory])


def add(cfg: Path, directory: str) -> int:
    return main(["-c", str(cfg), "add", directory])


# --------------------------------------------------------------------------
# remove: which lines a block owns
# --------------------------------------------------------------------------

def test_remove_first_block(cfg):
    write(cfg, THREE_REPOS)

    assert remove(cfg, "/tmp/a") == 0
    assert cfg.read_text() == (
        "interval = 300\n"
        "\n"
        "[[repo]]\n"
        'path = "/tmp/b"\n'
        "\n"
        "[[repo]]\n"
        'path = "/tmp/c"\n'
    )


def test_remove_middle_block(cfg):
    write(cfg, THREE_REPOS)

    assert remove(cfg, "/tmp/b") == 0
    assert cfg.read_text() == (
        "interval = 300\n"
        "\n"
        "[[repo]]\n"
        'path = "/tmp/a"\n'
        "\n"
        "[[repo]]\n"
        'path = "/tmp/c"\n'
    )


def test_remove_last_block(cfg):
    write(cfg, THREE_REPOS)

    assert remove(cfg, "/tmp/c") == 0
    assert cfg.read_text() == (
        "interval = 300\n"
        "\n"
        "[[repo]]\n"
        'path = "/tmp/a"\n'
        "\n"
        "[[repo]]\n"
        'path = "/tmp/b"\n'
    )


def test_remove_only_block_leaves_the_preamble(cfg):
    write(cfg, 'interval = 300\n\n[[repo]]\npath = "/tmp/a"\n')

    assert remove(cfg, "/tmp/a") == 0
    assert cfg.read_text() == "interval = 300\n"


def test_remove_the_single_block_of_a_file_with_nothing_else(cfg):
    write(cfg, '[[repo]]\npath = "/tmp/a"\n')

    assert remove(cfg, "/tmp/a") == 0
    assert cfg.read_text() == ""


def test_remove_last_repo_keeps_a_trailing_non_repo_table(cfg):
    write(
        cfg,
        "interval = 300\n"
        "\n"
        "[[repo]]\n"
        'path = "/tmp/a"\n'
        "\n"
        "[[repo]]\n"
        'path = "/tmp/b"\n'
        "\n"
        "[other]\n"
        "key = 1\n",
    )

    assert remove(cfg, "/tmp/b") == 0
    assert cfg.read_text() == (
        "interval = 300\n"
        "\n"
        "[[repo]]\n"
        'path = "/tmp/a"\n'
        "\n"
        "[other]\n"
        "key = 1\n"
    )


def test_remove_first_repo_keeps_a_trailing_non_repo_table(cfg):
    write(
        cfg,
        "interval = 300\n"
        "\n"
        "[[repo]]\n"
        'path = "/tmp/a"\n'
        "\n"
        "[other]\n"
        "key = 1\n",
    )

    assert remove(cfg, "/tmp/a") == 0
    assert cfg.read_text() == "interval = 300\n\n[other]\nkey = 1\n"


def test_remove_takes_comment_lines_directly_above_the_header(cfg):
    write(
        cfg,
        "interval = 300\n"
        "\n"
        "# my notes directory\n"
        "# added 2024-01-01\n"
        "[[repo]]\n"
        'path = "/tmp/a"\n'
        "\n"
        "[[repo]]\n"
        'path = "/tmp/b"\n',
    )

    assert remove(cfg, "/tmp/a") == 0
    assert cfg.read_text() == 'interval = 300\n\n[[repo]]\npath = "/tmp/b"\n'


def test_remove_keeps_a_comment_separated_from_the_header_by_a_blank_line(cfg):
    """A comment with a blank line under it documents the section, not the block."""
    write(
        cfg,
        "# repositories below\n"
        "\n"
        "[[repo]]\n"
        'path = "/tmp/a"\n'
        "\n"
        "[[repo]]\n"
        'path = "/tmp/b"\n',
    )

    assert remove(cfg, "/tmp/a") == 0
    assert cfg.read_text() == '# repositories below\n\n[[repo]]\npath = "/tmp/b"\n'


def test_remove_consumes_exactly_one_blank_separator(cfg):
    """No double blank line left behind and no two sections welded together."""
    write(cfg, THREE_REPOS)

    assert remove(cfg, "/tmp/b") == 0
    text = cfg.read_text()

    assert "\n\n\n" not in text
    assert '"/tmp/a"\n\n[[repo]]' in text


def test_remove_does_not_weld_the_preamble_onto_the_next_block(cfg):
    write(cfg, THREE_REPOS)

    assert remove(cfg, "/tmp/a") == 0
    text = cfg.read_text()

    assert "interval = 300\n\n[[repo]]" in text
    assert "interval = 300\n[[repo]]" not in text


def test_remove_keeps_inline_keys_of_the_block(cfg):
    """Only the target block goes; a sibling's extra keys are untouched."""
    write(
        cfg,
        "[[repo]]\n"
        'path = "/tmp/a"\n'
        'remote = "upstream"\n'
        "\n"
        "[[repo]]\n"
        'path = "/tmp/b"\n'
        'conflict = "theirs"\n',
    )

    assert remove(cfg, "/tmp/a") == 0
    assert cfg.read_text() == '[[repo]]\npath = "/tmp/b"\nconflict = "theirs"\n'


# --------------------------------------------------------------------------
# remove: failure and matching behaviour
# --------------------------------------------------------------------------

def test_remove_unconfigured_path_exits_1_and_leaves_the_file_untouched(cfg):
    write(cfg, THREE_REPOS)
    before = cfg.read_bytes()

    assert remove(cfg, "/tmp/nowhere") == 1
    assert cfg.read_bytes() == before


def test_remove_without_a_config_file_exits_2(cfg):
    assert remove(cfg, "/tmp/a") == 2
    assert not cfg.exists()


def test_remove_matches_a_tilde_path_written_in_the_config(cfg, isolated_home):
    write(cfg, '[[repo]]\npath = "~/Notes"\n')

    assert remove(cfg, str(isolated_home / "Notes")) == 0
    assert cfg.read_text() == ""


def test_remove_matches_an_absolute_path_given_as_a_tilde_argument(cfg, isolated_home):
    notes = isolated_home / "Notes"
    write(cfg, f'[[repo]]\npath = "{notes}"\n')

    assert remove(cfg, "~/Notes") == 0
    assert cfg.read_text() == ""


def test_remove_matches_despite_a_trailing_slash(cfg, isolated_home):
    write(cfg, '[[repo]]\npath = "~/Notes"\n')

    assert remove(cfg, str(isolated_home / "Notes") + "/") == 0
    assert cfg.read_text() == ""


def test_remove_works_for_a_directory_that_does_not_exist_on_disk(cfg, tmp_path):
    """Unlike `add`, `remove` does not require a valid git repo."""
    gone = tmp_path / "deleted-long-ago"
    assert not gone.exists()
    write(cfg, f'[[repo]]\npath = "{gone}"\n')

    assert remove(cfg, str(gone)) == 0
    assert cfg.read_text() == ""


def test_remove_leaves_the_directory_in_place(cfg, git_repo):
    write(cfg, f'[[repo]]\npath = "{git_repo}"\n')

    assert remove(cfg, str(git_repo)) == 0
    assert (git_repo / ".git").is_dir()
    assert (git_repo / "README.md").exists()


# --------------------------------------------------------------------------
# the shipped example config as a realistic, comment-heavy fixture
# --------------------------------------------------------------------------

def test_remove_last_block_of_the_example_config(cfg, example_config_text):
    write(cfg, example_config_text)

    assert remove(cfg, "~/work") == 0
    text = cfg.read_text()

    assert '"~/work"' not in text
    assert '"~/.dotfiles"' in text
    assert '"~/Notes"' in text
    # The header comments of the whole file survive.
    assert text.startswith("# gitsync configuration\n")
    assert "# One [[repo]] block per directory." in text
    # The removed block's own comment lines went with it.
    assert "# Only sync these branches" not in text
    assert "branches" not in text
    # The file now ends with the surviving block, with no stray blank line.
    assert text.endswith(
        "[[repo]]\n"
        'path = "~/Notes"\n'
        'conflict = "theirs"       # on a clash, prefer whatever came from the remote\n'
    )
    assert "\n\n\n" not in text


def test_remove_middle_block_of_the_example_config(cfg, example_config_text):
    write(cfg, example_config_text)

    assert remove(cfg, "~/Notes") == 0
    text = cfg.read_text()

    assert '"~/Notes"' not in text
    assert '"~/.dotfiles"' in text
    # The two neighbouring blocks are still separated by exactly one blank line.
    assert (
        '# conflict = "manual"    # manual | ours | theirs (default: manual)\n'
        "\n"
        "[[repo]]\n"
        'path = "~/work"\n'
    ) in text
    assert "\n\n\n" not in text


def test_remove_first_block_of_the_example_config(cfg, example_config_text):
    write(cfg, example_config_text)

    assert remove(cfg, "~/.dotfiles") == 0
    text = cfg.read_text()

    assert '"~/.dotfiles"' not in text
    # The commented-out defaults belonged to the removed block and go with it.
    assert '# remote = "origin"' not in text
    # The section comment above the removed block, separated by a blank line,
    # documents the section rather than the block, so it stays.
    assert "# One [[repo]] block per directory." in text
    assert (
        "# with a remote configured (e.g. `git clone` or `git remote add origin ...`).\n"
        "\n"
        "[[repo]]\n"
        'path = "~/Notes"\n'
    ) in text
    assert "\n\n\n" not in text


def test_removing_every_block_of_the_example_config_keeps_the_preamble(
    cfg, example_config_text
):
    write(cfg, example_config_text)

    for directory in ("~/.dotfiles", "~/Notes", "~/work"):
        assert remove(cfg, directory) == 0
    text = cfg.read_text()

    # Only the prose mention of [[repo]] in the preamble is left.
    assert text.count("[[repo]]") == 1
    assert "# One [[repo]] block per directory." in text
    assert "interval = 300\n" in text
    assert "path =" not in text
    assert "\n\n\n" not in text


# --------------------------------------------------------------------------
# add
# --------------------------------------------------------------------------

def test_add_creates_the_config_file(cfg, git_repo):
    assert add(cfg, str(git_repo)) == 0
    assert cfg.read_text() == f'interval = 300\n\n[[repo]]\npath = "{git_repo}"\n'


def test_add_creates_missing_parent_directories(tmp_path, git_repo):
    cfg = tmp_path / "nested" / "deeper" / "config.toml"

    assert add(cfg, str(git_repo)) == 0
    assert cfg.exists()


def test_add_appends_to_an_existing_config(cfg, git_repo):
    write(cfg, 'interval = 60\n\n[[repo]]\npath = "/tmp/a"\n')

    assert add(cfg, str(git_repo)) == 0
    assert cfg.read_text() == (
        "interval = 60\n"
        "\n"
        "[[repo]]\n"
        'path = "/tmp/a"\n'
        "\n"
        "[[repo]]\n"
        f'path = "{git_repo}"\n'
    )


def test_add_rejects_a_non_git_directory(cfg, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()

    assert add(cfg, str(plain)) == 2
    assert not cfg.exists()


def test_add_is_idempotent(cfg, git_repo):
    assert add(cfg, str(git_repo)) == 0
    before = cfg.read_bytes()

    assert add(cfg, str(git_repo)) == 0
    assert cfg.read_bytes() == before


def test_add_then_remove_round_trips_byte_identically(cfg, tmp_path):
    write(cfg, 'interval = 300\n\n[[repo]]\npath = "/tmp/a"\n')
    before = cfg.read_bytes()
    repo = init_repo(tmp_path / "extra")

    assert add(cfg, str(repo)) == 0
    assert cfg.read_bytes() != before

    assert remove(cfg, str(repo)) == 0
    assert cfg.read_bytes() == before


def test_add_then_remove_round_trips_on_a_fresh_config(cfg, git_repo):
    assert add(cfg, str(git_repo)) == 0
    assert remove(cfg, str(git_repo)) == 0
    assert cfg.read_text() == "interval = 300\n"


def test_add_then_remove_round_trips_on_the_example_config(
    cfg, example_config_text, tmp_path
):
    write(cfg, example_config_text)
    before = cfg.read_bytes()
    repo = init_repo(tmp_path / "extra")

    assert add(cfg, str(repo)) == 0
    assert remove(cfg, str(repo)) == 0
    assert cfg.read_bytes() == before


def test_add_resolves_a_tilde_argument(cfg, isolated_home):
    repo = init_repo(isolated_home / "Notes")

    assert add(cfg, "~/Notes") == 0
    assert f'path = "{repo}"' in cfg.read_text()


def test_bare_invocation_prints_the_command_overview(capsys):
    """A bare `gitsync` is a request for orientation, not a usage error."""
    assert main([]) == 0

    out = capsys.readouterr().out
    for command in ("sync", "status", "add", "remove", "install", "uninstall"):
        assert command in out


# --------------------------------------------------------------------------
# status: the background agent line
# --------------------------------------------------------------------------

@pytest.fixture
def plist(tmp_path, monkeypatch) -> Path:
    """Redirect the agent plist into tmp_path.

    ``PLIST_PATH`` resolves ``~`` at import time, so the autouse ``HOME``
    override does not reach it; it has to be patched on the module.
    """
    path = tmp_path / "com.gitsync.agent.plist"
    monkeypatch.setattr(launchd, "PLIST_PATH", path)
    return path


def fake_launchctl(monkeypatch, *, returncode: int, stdout: str = "") -> None:
    """Stand in for `launchctl list`, so tests never touch the real launchd."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        launchd.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0], returncode, stdout, ""),
    )


def status(cfg: Path) -> int:
    return main(["-c", str(cfg), "status"])


def test_status_reports_a_loaded_agent(cfg, plist, monkeypatch, capsys):
    write(cfg, "interval = 300\n")
    plist.write_text("")
    fake_launchctl(monkeypatch, returncode=0, stdout='\t"LastExitStatus" = 0;\n')

    assert status(cfg) == 0

    out = capsys.readouterr().out
    assert "scheduled" in out
    assert "every 300s" in out


def test_status_distinguishes_installed_from_loaded(cfg, plist, monkeypatch, capsys):
    """A plist on disk that launchd does not know about means nothing syncs."""
    write(cfg, "interval = 300\n")
    plist.write_text("")
    fake_launchctl(monkeypatch, returncode=113)

    assert status(cfg) == 0
    assert "installed but not loaded" in capsys.readouterr().out


def test_status_reports_a_missing_agent(cfg, plist, monkeypatch, capsys):
    write(cfg, "interval = 300\n")
    fake_launchctl(monkeypatch, returncode=113)

    assert status(cfg) == 0

    out = capsys.readouterr().out
    assert "not installed" in out
    assert "every 300s" not in out


def test_status_surfaces_a_failing_last_run(cfg, plist, monkeypatch, capsys):
    write(cfg, "interval = 300\n")
    plist.write_text("")
    fake_launchctl(monkeypatch, returncode=0, stdout='\t"LastExitStatus" = 1;\n')

    assert status(cfg) == 0
    assert "the last run exited 1" in capsys.readouterr().out


def test_status_says_so_on_a_non_macos_platform(cfg, plist, monkeypatch, capsys):
    write(cfg, "interval = 300\n")
    monkeypatch.setattr(sys, "platform", "linux")

    assert status(cfg) == 0
    assert "not supported on this platform" in capsys.readouterr().out
