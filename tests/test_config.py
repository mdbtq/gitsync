"""Tests for gitsync.config.load."""

from __future__ import annotations

from pathlib import Path

import pytest

from gitsync.config import DEFAULT_LOG_PATH, Config, ConfigError, RepoConfig, load


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_load_valid_config(tmp_path):
    cfg = write_config(
        tmp_path,
        'interval = 60\n'
        'log_file = "/tmp/example.log"\n'
        '\n'
        '[[repo]]\n'
        'path = "/srv/dotfiles"\n'
        'remote = "upstream"\n'
        'conflict = "theirs"\n',
    )

    config = load(cfg)

    assert isinstance(config, Config)
    assert config.interval == 60
    assert config.log_file == Path("/tmp/example.log")
    assert config.repos == [
        RepoConfig(path=Path("/srv/dotfiles"), remote="upstream", conflict="theirs")
    ]


def test_load_missing_file_raises(tmp_path):
    missing = tmp_path / "nope.toml"

    with pytest.raises(ConfigError) as exc:
        load(missing)

    assert str(missing) in str(exc.value)


def test_load_repo_without_path_raises(tmp_path):
    cfg = write_config(tmp_path, '[[repo]]\nremote = "origin"\n')

    with pytest.raises(ConfigError, match="missing required key 'path'"):
        load(cfg)


def test_load_repo_without_path_reports_its_index(tmp_path):
    cfg = write_config(
        tmp_path,
        '[[repo]]\npath = "/a"\n\n[[repo]]\nremote = "origin"\n',
    )

    with pytest.raises(ConfigError, match=r"\[\[repo\]\] #2"):
        load(cfg)


def test_load_invalid_conflict_strategy_raises(tmp_path):
    cfg = write_config(tmp_path, '[[repo]]\npath = "/a"\nconflict = "mine"\n')

    with pytest.raises(ConfigError) as exc:
        load(cfg)

    message = str(exc.value)
    assert "'mine'" in message
    assert "manual, ours, theirs" in message


def test_load_applies_defaults(tmp_path):
    cfg = write_config(tmp_path, '[[repo]]\npath = "/a"\n')

    config = load(cfg)

    assert config.interval == 300
    assert config.log_file == DEFAULT_LOG_PATH
    assert config.repos[0].remote == "origin"
    assert config.repos[0].conflict == "manual"


def test_load_expands_tilde_in_repo_path(tmp_path, isolated_home):
    cfg = write_config(tmp_path, '[[repo]]\npath = "~/Notes"\n')

    config = load(cfg)

    assert config.repos[0].path == Path.home() / "Notes"
    assert "~" not in str(config.repos[0].path)


def test_load_expands_tilde_in_log_file(tmp_path, isolated_home):
    cfg = write_config(tmp_path, 'log_file = "~/logs/gitsync.log"\n')

    config = load(cfg)

    assert config.log_file == Path.home() / "logs" / "gitsync.log"


def test_load_empty_config_yields_no_repos(tmp_path):
    cfg = write_config(tmp_path, "")

    config = load(cfg)

    assert config.repos == []
    assert config.interval == 300


def test_load_the_shipped_example_config(example_config_text, tmp_path):
    cfg = write_config(tmp_path, example_config_text)

    config = load(cfg)

    assert config.interval == 300
    assert [r.conflict for r in config.repos] == ["manual", "theirs", "manual"]
    assert [r.path.name for r in config.repos] == [".dotfiles", "Notes", "work"]
    assert [r.branches for r in config.repos] == [(), (), ("main", "release/*")]


# --------------------------------------------------------------------------
# branches allow-list
# --------------------------------------------------------------------------

def test_load_parses_branches_into_a_tuple(tmp_path):
    cfg = write_config(
        tmp_path, '[[repo]]\npath = "/a"\nbranches = ["main", "release/*"]\n'
    )

    repo = load(cfg).repos[0]

    assert repo.branches == ("main", "release/*")
    assert isinstance(repo.branches, tuple)


def test_load_defaults_branches_to_empty(tmp_path):
    cfg = write_config(tmp_path, '[[repo]]\npath = "/a"\n')

    assert load(cfg).repos[0].branches == ()


def test_load_accepts_an_explicitly_empty_branches_list(tmp_path):
    cfg = write_config(tmp_path, '[[repo]]\npath = "/a"\nbranches = []\n')

    assert load(cfg).repos[0].branches == ()


def test_load_rejects_a_bare_string_for_branches(tmp_path):
    """TOML accepts it, but fnmatch would then iterate it per character."""
    cfg = write_config(tmp_path, '[[repo]]\npath = "/a"\nbranches = "main"\n')

    with pytest.raises(ConfigError, match="must be a list of strings"):
        load(cfg)


def test_load_rejects_non_string_entries_in_branches(tmp_path):
    cfg = write_config(tmp_path, '[[repo]]\npath = "/a"\nbranches = [1, 2]\n')

    with pytest.raises(ConfigError, match="must be a list of strings"):
        load(cfg)


def test_load_rejects_a_mixed_branches_list(tmp_path):
    cfg = write_config(tmp_path, '[[repo]]\npath = "/a"\nbranches = ["main", 3]\n')

    with pytest.raises(ConfigError, match="must be a list of strings"):
        load(cfg)


class TestSyncsBranch:
    def test_empty_allow_list_permits_any_branch(self):
        repo = RepoConfig(path=Path("/a"))

        assert repo.syncs_branch("main")
        assert repo.syncs_branch("feature/x")
        assert repo.syncs_branch("anything-at-all")

    def test_exact_name_matches(self):
        repo = RepoConfig(path=Path("/a"), branches=("main", "develop"))

        assert repo.syncs_branch("main")
        assert repo.syncs_branch("develop")

    def test_non_matching_branch_is_rejected(self):
        repo = RepoConfig(path=Path("/a"), branches=("main",))

        assert not repo.syncs_branch("feature/x")

    def test_glob_matches(self):
        repo = RepoConfig(path=Path("/a"), branches=("release/*",))

        assert repo.syncs_branch("release/1.0")
        assert repo.syncs_branch("release/next")
        assert not repo.syncs_branch("release")
        assert not repo.syncs_branch("hotfix/1.0")

    def test_matching_is_case_sensitive(self):
        repo = RepoConfig(path=Path("/a"), branches=("main",))

        assert repo.syncs_branch("main")
        assert not repo.syncs_branch("Main")
        assert not repo.syncs_branch("MAIN")

    def test_glob_matching_is_case_sensitive(self):
        repo = RepoConfig(path=Path("/a"), branches=("release/*",))

        assert not repo.syncs_branch("Release/1.0")

    def test_any_pattern_in_the_list_may_match(self):
        repo = RepoConfig(path=Path("/a"), branches=("main", "release/*"))

        assert repo.syncs_branch("main")
        assert repo.syncs_branch("release/1.0")
        assert not repo.syncs_branch("feature/x")
