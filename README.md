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

```sh
gitsync add ~/.dotfiles     # register a git working tree
gitsync add ~/Notes
gitsync status              # show clean / ahead / behind / local changes
gitsync sync                # run one pass over all repos
gitsync remove ~/Notes      # stop syncing it; the directory stays put
```

`remove` only edits the config — it never touches the directory or its git
history, so the repo keeps working as a normal git checkout. It also works for
a directory you have already deleted.

Config lives at `~/.config/gitsync/config.toml` (see `config.example.toml`).

### Run it automatically (macOS)

```sh
gitsync install            # launchd agent, runs `gitsync sync` every `interval`s
gitsync uninstall
```

On Linux, schedule `gitsync sync` with cron or a systemd timer.

## Notes & limitations

- Each directory must already be a git repo with a remote and a checked-out
  branch. gitsync syncs whatever branch is currently checked out.
- Large or binary files work but get no special handling — git is not ideal for
  big binaries (consider git-lfs separately).
- The background agent runs on an interval; it is not real-time. Lower
  `interval` for snappier syncing at the cost of more git traffic.
