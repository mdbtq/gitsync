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
        elif result.status is Status.SKIPPED:
            # A normal state (e.g. working on a feature branch), not a problem:
            # logged for the record, but never notified and never non-zero.
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
        if not repo.syncs_branch(branch):
            print(f"  -  {path}  [{branch}]  not synced (branch excluded)")
            continue
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


def cmd_remove(args: argparse.Namespace) -> int:
    path = Path(args.directory).expanduser().resolve()
    config_path = args.config or DEFAULT_CONFIG_PATH

    if not config_path.exists():
        print(f"error: no config at {config_path}", file=sys.stderr)
        return 2

    lines = config_path.read_text().splitlines(keepends=True)
    block = _find_repo_block(lines, path)
    if block is None:
        print(f"{path} is not configured.", file=sys.stderr)
        return 1

    start, end = block
    del lines[start:end]
    config_path.write_text("".join(lines))
    print(f"Removed {path} from {config_path}")
    print("The directory itself was left untouched.")
    return 0


def _find_repo_block(lines: list[str], path: Path) -> tuple[int, int] | None:
    """Locate the ``[[repo]]`` block for ``path`` as a ``[start, end)`` line range.

    Works on the raw text rather than a parsed document so that comments and
    formatting elsewhere in the file survive the edit. The range starts at the
    ``[[repo]]`` header (including any comment lines directly above it) and ends
    just before the next table header.

    Trailing blank lines are taken with the block, but the blank line *above* it
    is left alone: that one separates the preceding section from what follows,
    so absorbing it would weld the previous section onto the next block.
    """
    for i, line in enumerate(lines):
        if line.strip() != "[[repo]]":
            continue
        end = len(lines)
        for j in range(i + 1, len(lines)):
            if lines[j].lstrip().startswith("["):
                end = j
                break
        if _block_path(lines[i:end]) != path:
            continue
        # Absorb comment lines immediately above the header: they document this
        # block, not the one that follows it.
        start = i
        while start > 0 and lines[start - 1].strip().startswith("#"):
            start -= 1
        # A block owns exactly one blank separator. Prefer the one below it; if
        # there is none (this is the last block) fall back to the one above, so
        # the file neither gains a double blank line nor loses its spacing.
        while end < len(lines) and not lines[end].strip():
            end += 1
        if end == len(lines):
            while start > 0 and not lines[start - 1].strip():
                start -= 1
        return start, end
    return None


def _block_path(block: list[str]) -> Path | None:
    """Resolve the ``path`` key of a single ``[[repo]]`` block, if it has one."""
    try:
        entry = tomllib.loads("".join(block)).get("repo", [{}])[0]
    except tomllib.TOMLDecodeError:
        return None
    raw = entry.get("path")
    return Path(raw).expanduser().resolve() if raw else None


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


DESCRIPTION = """\
Keep local git working trees in sync across machines.

Each pass commits your local changes, merges the remote branch and pushes,
per directory registered in the config."""

EPILOG = f"""\
examples:
  gitsync add ~/.dotfiles     register a git working tree
  gitsync status              show clean / ahead / behind / local changes
  gitsync sync                run one pass over all repos
  gitsync install             run `gitsync sync` in the background (macOS)
  gitsync remove ~/Notes      stop syncing it; the directory stays put

config:
  {DEFAULT_CONFIG_PATH}
  Per repo you can set `remote`, `conflict` (manual | ours | theirs) and
  `branches` (exact names or globs) — see config.example.toml.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gitsync",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"gitsync {__version__}")
    parser.add_argument(
        "-c", "--config", type=lambda p: Path(p).expanduser(),
        help=f"config file (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")

    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.add_parser("sync", help="run one sync pass over all repos").set_defaults(func=cmd_sync)
    sub.add_parser("status", help="show the state of each repo").set_defaults(func=cmd_status)

    add = sub.add_parser("add", help="add a git directory to the config")
    add.add_argument("directory", help="path to a git working tree")
    add.set_defaults(func=cmd_add)

    remove = sub.add_parser("remove", help="stop syncing a directory (leaves it in place)")
    remove.add_argument("directory", help="path to a configured working tree")
    remove.set_defaults(func=cmd_remove)

    sub.add_parser("install", help="install background agent (macOS/launchd)").set_defaults(func=cmd_install)
    sub.add_parser("uninstall", help="remove the background agent").set_defaults(func=cmd_uninstall)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # No subcommand: show the overview instead of an argparse usage error, so
    # a bare `gitsync` tells you what the tool does and what it can do.
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
