"""Install/remove a launchd agent that runs `gitsync sync` on an interval (macOS)."""

from __future__ import annotations

import subprocess
import sys
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
