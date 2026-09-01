"""Configuration loading for gitsync.

The config is a small TOML file. A minimal example::

    interval = 300

    [[repo]]
    path = "~/.dotfiles"

    [[repo]]
    path = "~/Notes"
    conflict = "theirs"
    branches = ["main"]
"""

from __future__ import annotations

import fnmatch
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFLICT_STRATEGIES = ("manual", "ours", "theirs")

DEFAULT_CONFIG_PATH = Path(
    os.environ.get("GITSYNC_CONFIG")
    or Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")) / "gitsync" / "config.toml"
).expanduser()

DEFAULT_LOG_PATH = Path(
    os.environ.get("XDG_STATE_HOME", "~/.local/state")
).expanduser() / "gitsync" / "gitsync.log"


class ConfigError(Exception):
    """Raised when the config file is missing or invalid."""


@dataclass(frozen=True)
class RepoConfig:
    path: Path
    remote: str = "origin"
    # How to resolve a merge conflict during an automated sync:
    #   "manual"  -> abort the merge, do not push, notify (never loses data)
    #   "ours"    -> prefer this machine's version on conflicting hunks
    #   "theirs"  -> prefer the remote version on conflicting hunks
    conflict: str = "manual"
    # Branches this repo may sync, as exact names or globs ("release/*").
    # Empty means no restriction: sync whatever branch is checked out.
    branches: tuple[str, ...] = ()

    def syncs_branch(self, branch: str) -> bool:
        """True if ``branch`` is allowed to sync for this repo."""
        if not self.branches:
            return True
        return any(fnmatch.fnmatchcase(branch, pat) for pat in self.branches)


@dataclass(frozen=True)
class Config:
    repos: list[RepoConfig] = field(default_factory=list)
    interval: int = 300  # seconds between passes, used by the background agent
    log_file: Path = DEFAULT_LOG_PATH


def load(path: Path | None = None) -> Config:
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise ConfigError(
            f"No config found at {path}. Create one or run `gitsync add <dir>`."
        )

    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    repos: list[RepoConfig] = []
    for i, entry in enumerate(raw.get("repo", [])):
        if "path" not in entry:
            raise ConfigError(f"[[repo]] #{i + 1} is missing required key 'path'")
        conflict = entry.get("conflict", "manual")
        if conflict not in CONFLICT_STRATEGIES:
            raise ConfigError(
                f"Invalid conflict strategy {conflict!r} for {entry['path']}; "
                f"expected one of {', '.join(CONFLICT_STRATEGIES)}"
            )
        branches = entry.get("branches", [])
        if isinstance(branches, str) or not all(isinstance(b, str) for b in branches):
            raise ConfigError(
                f"'branches' for {entry['path']} must be a list of strings, "
                f'e.g. branches = ["main"]'
            )
        repos.append(
            RepoConfig(
                path=Path(entry["path"]).expanduser(),
                remote=entry.get("remote", "origin"),
                conflict=conflict,
                branches=tuple(branches),
            )
        )

    log_file = raw.get("log_file")
    return Config(
        repos=repos,
        interval=int(raw.get("interval", 300)),
        log_file=Path(log_file).expanduser() if log_file else DEFAULT_LOG_PATH,
    )
