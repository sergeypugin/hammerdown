from __future__ import annotations

import logging
import shutil
import stat
from pathlib import Path

logger = logging.getLogger("hammerdown")


def _install_launcher(command: str, home_dir: Path | None = None) -> Path:
    home = home_dir or Path.home()
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher = bin_dir / "hammerdown"
    launcher.write_text(f'#!/bin/sh\nexec {command} "$@"\n', encoding="utf-8")
    try:
        launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass
    return launcher


def _quote_if_needed(value: str | Path) -> str:
    text = str(value)
    return f'"{text}"' if " " in text else text


def _remove_install_dir(path: Path) -> None:
    if path.exists():
        try:
            shutil.rmtree(path)
        except OSError:
            logger.warning("Could not remove installed program files at %s", path)
