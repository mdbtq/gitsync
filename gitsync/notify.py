"""Logging setup and best-effort desktop notifications (macOS)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path


def setup_logging(log_file: Path, verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("gitsync")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError as exc:  # logging to file is a convenience, never fatal
        logger.warning("could not open log file %s: %s", log_file, exc)

    return logger


def notify(title: str, message: str) -> None:
    """Show a desktop notification if the platform supports it; silent otherwise."""
    if sys.platform == "darwin" and shutil.which("osascript"):
        script = f'display notification {_quote(message)} with title {_quote(title)}'
        subprocess.run(["osascript", "-e", script], capture_output=True)
    elif shutil.which("notify-send"):  # Linux desktops
        subprocess.run(["notify-send", title, message], capture_output=True)


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
