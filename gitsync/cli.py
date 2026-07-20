"""Command-line entry point for gitsync."""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from . import __version__, launchd
from .config import DEFAULT_CONFIG_PATH, Config, ConfigError, RepoConfig, load
from .gitutil import current_branch, git, is_dirty, is_git_repo
from .notify import notify, setup_logging
from .sync import Status, sync_repo


def _load_config(args: argparse.Namespace) -> Config:
    try:
        return load(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)


def cmd_sync(args: argparse.Namespace) -> int:
    config = _load_config(args)
    logger = setup_logging(config.log_file, verbose=args.verbose)

    if not config.repos:
        logger.warning("no repositories configured in %s", args.config or DEFAULT_CONFIG_PATH)
        return 0

    exit_code = 0
    for repo in config.repos:
        result = sync_repo(repo)
        if result.status is Status.OK:
            logger.info("%s: %s", result.repo, result.message)
        elif result.status is Status.CONFLICT:
            logger.warning("%s: %s", result.repo, result.message)
            notify("gitsync: conflict", f"{result.repo}\n{result.message}")
            exit_code = 1
        else:
            logger.error("%s: %s", result.repo, result.message)
            notify("gitsync: error", f"{result.repo}\n{result.message}")
            exit_code = 1
    return exit_code


def cmd_status(args: argparse.Namespace) -> int:
    config = _load_config(args)
    if not config.repos:
        print("No repositories configured.")
        return 0

    for repo in config.repos:
        path = repo.path
        if not path.exists() or not is_git_repo(path):
            print(f"  ?  {path}  (not a git repository)")
            continue
        branch = current_branch(path) or "(detached)"
        flags = []
        if is_dirty(path):
            flags.append("local changes")
        counts = git(path, "rev-list", "--left-right", "--count", f"{repo.remote}/{branch}...HEAD")
        if counts.ok and counts.stdout:
            behind, ahead = counts.stdout.split()
            if ahead != "0":
                flags.append(f"{ahead} ahead")
            if behind != "0":
                flags.append(f"{behind} behind")
        state = ", ".join(flags) if flags else "clean"
        print(f"  •  {path}  [{branch}]  {state}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    path = Path(args.directory).expanduser().resolve()
    if not is_git_repo(path):
        print(f"error: {path} is not a git repository", file=sys.stderr)
        return 2

    config_path = args.config or DEFAULT_CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)

    existing = _read_paths(config_path)
    if str(path) in existing:
        print(f"{path} is already configured.")
        return 0

    block = f'\n[[repo]]\npath = "{path}"\n'
    if not config_path.exists():
        block = "interval = 300\n" + block
    with config_path.open("a") as fh:
        fh.write(block)
    print(f"Added {path} to {config_path}")
    return 0


def _read_paths(config_path: Path) -> set[str]:
    if not config_path.exists():
        return set()
    with config_path.open("rb") as fh:
        raw = tomllib.load(fh)
    return {
        str(Path(entry["path"]).expanduser().resolve())
        for entry in raw.get("repo", [])
        if "path" in entry
    }


def cmd_install(args: argparse.Namespace) -> int:
    config = _load_config(args)
    if sys.platform != "darwin":
        print("error: `install` currently supports macOS (launchd) only", file=sys.stderr)
        return 2
    plist = launchd.install(config.interval, config.log_file)
    print(f"Installed background agent: {plist}")
    print(f"Runs `gitsync sync` every {config.interval}s. Logs: {config.log_file}")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    if launchd.uninstall():
        print("Removed background agent.")
    else:
        print("No background agent was installed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gitsync", description=__doc__)
    parser.add_argument("--version", action="version", version=f"gitsync {__version__}")
    parser.add_argument(
        "-c", "--config", type=lambda p: Path(p).expanduser(),
        help=f"config file (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sync", help="run one sync pass over all repos").set_defaults(func=cmd_sync)
    sub.add_parser("status", help="show the state of each repo").set_defaults(func=cmd_status)

    add = sub.add_parser("add", help="add a git directory to the config")
    add.add_argument("directory", help="path to a git working tree")
    add.set_defaults(func=cmd_add)

    sub.add_parser("install", help="install background agent (macOS/launchd)").set_defaults(func=cmd_install)
    sub.add_parser("uninstall", help="remove the background agent").set_defaults(func=cmd_uninstall)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
