"""Install/remove a launchd agent that runs `gitsync sync` on an interval (macOS)."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from plistlib import dump as plist_dump

LABEL = "com.gitsync.agent"
PLIST_PATH = Path("~/Library/LaunchAgents").expanduser() / f"{LABEL}.plist"

# launchd runs with a minimal PATH; make sure git and a few common prefixes resolve.
_LAUNCHD_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"


def _plist(interval: int, log_file: Path) -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "gitsync", "sync"],
        "StartInterval": interval,
        "RunAtLoad": True,
        "EnvironmentVariables": {"PATH": _LAUNCHD_PATH},
        "StandardOutPath": str(log_file),
        "StandardErrorPath": str(log_file),
    }


def install(interval: int, log_file: Path) -> Path:
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with PLIST_PATH.open("wb") as fh:
        plist_dump(_plist(interval, log_file), fh)

    # Reload so a re-install picks up changes.
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
    subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=True)
    return PLIST_PATH


def uninstall() -> bool:
    if not PLIST_PATH.exists():
        return False
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
    PLIST_PATH.unlink()
    return True


@dataclass(frozen=True)
class AgentStatus:
    """What launchd knows about the background agent right now."""

    installed: bool  # the plist exists on disk
    loaded: bool  # launchd has the job registered
    last_exit: int | None  # exit status of the most recent run, if any
    supported: bool = True  # launchd agents exist on macOS only

    def describe(self) -> str:
        if not self.supported:
            return "not supported on this platform (macOS/launchd only)"
        if not self.installed:
            return "not installed (run `gitsync install`)"
        if not self.loaded:
            return "installed but not loaded (run `gitsync install` to reload)"
        if self.last_exit:
            return f"scheduled, but the last run exited {self.last_exit}"
        return "scheduled"


def status() -> AgentStatus:
    """Report whether the launchd agent is installed and loaded.

    ``launchctl list <label>`` exits non-zero when the job is unknown to
    launchd, which is the distinction that matters: a plist can sit on disk
    without being loaded (e.g. after a manual `launchctl unload`), and then no
    syncing happens even though `gitsync install` was run at some point.
    """
    if sys.platform != "darwin":
        return AgentStatus(
            installed=False, loaded=False, last_exit=None, supported=False
        )

    installed = PLIST_PATH.exists()
    proc = subprocess.run(
        ["launchctl", "list", LABEL], capture_output=True, text=True
    )
    if proc.returncode != 0:
        return AgentStatus(installed=installed, loaded=False, last_exit=None)
    return AgentStatus(
        installed=installed, loaded=True, last_exit=_last_exit(proc.stdout)
    )


def _last_exit(output: str) -> int | None:
    """Pull ``LastExitStatus`` out of `launchctl list` output, if present."""
    for line in output.splitlines():
        key, _, value = line.partition("=")
        if key.strip().strip('"') == "LastExitStatus":
            try:
                return int(value.strip().rstrip(";"))
            except ValueError:
                return None
    return None
