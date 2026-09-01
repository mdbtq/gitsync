# gitsync

Keep one or more local directories in sync across machines, using **git as the
source of truth**. Point it at directories that are git working trees (dotfiles,
notes, config), and gitsync commits your local changes, pulls everyone else's,
and pushes — automatically, in the background.

It is a thin, dependency-free wrapper around `git`. There is no server to run:
each machine syncs against a shared remote (GitHub, a private git host, a bare
repo on a NAS, …).

## How it works

Each pass, per configured directory:

1. **fetch** the remote
2. **commit** any local changes (auto message: hostname + timestamp) — done
   *before* merging, so nothing in your working tree can be lost
3. **merge** the remote branch into your local branch
4. **push**

### Conflicts

Two machines can edit the same line before syncing. Per repo you choose how a
merge conflict is handled:

| `conflict` | behaviour |
|------------|-----------|
| `manual` (default) | abort the merge, **do not push**, and send a desktop notification. Nothing is lost; you resolve it by hand, then the next pass continues. |
| `theirs` | on conflicting hunks, keep the remote version |
| `ours` | on conflicting hunks, keep this machine's version |

`manual` never discards data. `ours`/`theirs` only affect the lines that
actually clash — non-conflicting changes from both sides are always merged.

### Limiting which branches sync

By default gitsync syncs whatever branch is checked out. To restrict a repo to
specific branches, list them — exact names or globs:

```toml
[[repo]]
path = "~/work"
branches = ["main", "release/*"]
```

While any other branch is checked out that repo is skipped entirely: no fetch,
no auto-commit, no push, and the working tree is left exactly as you left it.
Skipping is a normal state, so it is logged but never notified and never fails
the run — you can work on a feature branch all day without gitsync touching it
or nagging you. Omit `branches` to keep syncing every branch.

## Install

Requires Python ≥ 3.11 and `git`.

Install it globally so `gitsync` works from any directory:

```sh
uv tool install --editable .    # from this directory; editable = code changes apply live
```

Alternatives:

```sh
pip install -e .                # into the current environment
# or run without installing:  python -m gitsync ...
```

## Usage

Run `gitsync` with no arguments for the same overview on the command line.

### Commands

| command | what it does |
|---------|--------------|
| `gitsync add <dir>` | register a git working tree in the config |
| `gitsync remove <dir>` | stop syncing a directory; the directory stays put |
| `gitsync status` | whether the background agent is scheduled, then per repo: branch, clean / local changes / ahead / behind |
| `gitsync sync` | run one pass over all repos (fetch, commit, merge, push) |
| `gitsync install` | install the background agent (macOS/launchd) |
| `gitsync uninstall` | remove the background agent |

`remove` only edits the config — it never touches the directory or its git
history, so the repo keeps working as a normal git checkout. It also works for
a directory you have already deleted.

### Global options

| option | what it does |
|--------|--------------|
| `-c`, `--config <file>` | use a different config file (default: `~/.config/gitsync/config.toml`) |
| `-v`, `--verbose` | debug logging |
| `--version` | print the version |
| `-h`, `--help` | help; also works per command, e.g. `gitsync add --help` |

### Typical session

```sh
gitsync add ~/.dotfiles     # register a git working tree
gitsync add ~/Notes
gitsync status              # show clean / ahead / behind / local changes
gitsync sync                # run one pass over all repos
gitsync install             # from here on it runs by itself
```

### Config

Config lives at `~/.config/gitsync/config.toml` (see `config.example.toml`).

| key | scope | meaning |
|-----|-------|---------|
| `interval` | global | seconds between background passes (default: `300`) |
| `log_file` | global | log location (default: `~/.local/state/gitsync/gitsync.log`) |
| `path` | `[[repo]]` | the working tree to sync (required) |
| `remote` | `[[repo]]` | git remote to sync against (default: `origin`) |
| `conflict` | `[[repo]]` | `manual` (default) \| `ours` \| `theirs` — see [Conflicts](#conflicts) |
| `branches` | `[[repo]]` | branches this repo may sync, exact names or globs — see [Limiting which branches sync](#limiting-which-branches-sync) |

### Exit codes

`sync` exits `0` when every repo synced or was skipped, `1` when any repo hit a
conflict or an error (each one also raises a desktop notification), and `2` on a
bad config or invalid arguments.

### Run it automatically (macOS)

```sh
gitsync install            # launchd agent, runs `gitsync sync` every `interval`s
gitsync uninstall
```

Each tick starts a fresh `gitsync sync` that re-reads the config, so `add` and
`remove` take effect on the next pass — no restart needed.

`interval` and `log_file` are the exception: they are written into the launchd
plist at install time, not read at runtime. After changing either one, re-run
`gitsync install` to rewrite and reload the agent.

On Linux, schedule `gitsync sync` with cron or a systemd timer.

## Notes & limitations

- Each directory must already be a git repo with a remote and a checked-out
  branch. gitsync syncs whatever branch is currently checked out, unless the
  repo sets `branches` (see above).
- Large or binary files work but get no special handling — git is not ideal for
  big binaries (consider git-lfs separately).
- The background agent runs on an interval; it is not real-time. Lower
  `interval` for snappier syncing at the cost of more git traffic.
