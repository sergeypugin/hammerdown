from __future__ import annotations

import logging
import shlex
import shutil
import stat
from pathlib import Path

logger = logging.getLogger("hammerdown")


def _install_launcher(command: str, home_dir: Path | None = None) -> Path:
    home = home_dir or Path.home()
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher = bin_dir / "hammerdown"
    launcher_command = shlex.quote(command) if Path(command).is_absolute() else command
    launcher.write_text(f'#!/bin/sh\nexec {launcher_command} "$@"\n', encoding="utf-8")
    try:
        launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass
    return launcher


def _quote_if_needed(value: str | Path) -> str:
    return shlex.quote(str(value))


def _quote_desktop_exec(value: str | Path) -> str:
    text = str(value).replace("%", "%%")
    if not any(char.isspace() or char in '"\\\\`$><~|&;*?#()' for char in text):
        return text
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    for char in "`$":
        escaped = escaped.replace(char, "\\" + char)
    return f'"{escaped}"'


def _quote_applescript_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _remove_install_dir(path: Path) -> None:
    if path.exists():
        try:
            shutil.rmtree(path)
        except OSError:
            logger.warning("Could not remove installed program files at %s", path)
