from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

WINDOWS_TERMINAL_TITLE = "Hammerdown"


def find_windows_terminal() -> str | None:
    """Return the system-resolved Windows Terminal launcher, when available."""
    return shutil.which("wt.exe") or shutil.which("wt")


def _console_interpreter() -> str:
    """Return the console interpreter for a worker started by a windowed one."""
    executable = Path(sys.executable)
    if os.name == "nt" and executable.name.lower() == "pythonw.exe":
        console = executable.with_name("python.exe")
        if console.is_file():
            return str(console)
    return str(executable)


def build_context_worker_command(
    files: Sequence[str],
    *,
    merge: str | None = None,
    merge_auto: bool = False,
    tree: bool = False,
    all_formats: bool = False,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    filter_queue: Sequence[tuple[str, str]] | None = None,
    overwrite: bool = False,
    skip_existing: bool = False,
    yes: bool = False,
    no: bool = False,
    output_dir: str | None = None,
) -> list[str]:
    """Build a command that runs the selected files outside the IPC coordinator."""
    if getattr(sys, "frozen", False):
        command = [sys.executable]
    else:
        command = [_console_interpreter(), "-m", "hammerdown"]

    command.extend(("--context-worker", "--right-click"))
    if tree:
        command.append("--tree")
    if all_formats:
        command.append("--all-formats")
    if merge_auto:
        command.append("--merge-auto")
    if filter_queue is None:
        for pattern in include:
            command.extend(("--include", pattern))
        for pattern in exclude:
            command.extend(("--exclude", pattern))
    else:
        for kind, pattern in filter_queue:
            command.extend((f"--{kind}", pattern))
    if overwrite:
        command.append("--overwrite")
    if skip_existing:
        command.append("--skip-existing")
    if yes:
        command.append("--yes")
    if no:
        command.append("--no")
    if output_dir:
        command.extend(("--output-dir", output_dir))
    if merge:
        command.extend(("--merge", merge))
    command.extend(files)
    return command


def build_windows_terminal_command(
    files: Sequence[str],
    *,
    terminal: str,
    merge: str | None = None,
    merge_auto: bool = False,
    tree: bool = False,
    all_formats: bool = False,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    filter_queue: Sequence[tuple[str, str]] | None = None,
    overwrite: bool = False,
    skip_existing: bool = False,
    yes: bool = False,
    no: bool = False,
    output_dir: str | None = None,
    tab_color: str | None = None,
) -> list[str]:
    """Build a Windows Terminal command that opens an independent Hammerdown window."""
    worker_command = build_context_worker_command(
        files,
        merge=merge,
        merge_auto=merge_auto,
        tree=tree,
        all_formats=all_formats,
        include=include,
        exclude=exclude,
        filter_queue=filter_queue,
        overwrite=overwrite,
        skip_existing=skip_existing,
        yes=yes,
        no=no,
        output_dir=output_dir,
    )
    command = [terminal, "-w", "new", "new-tab", "--title", WINDOWS_TERMINAL_TITLE]
    if tab_color:
        command.extend(("--tabColor", tab_color))
    return [*command, "--", *worker_command]


def launch_context_worker(
    files: Sequence[str],
    *,
    merge: str | None = None,
    merge_auto: bool = False,
    tree: bool = False,
    all_formats: bool = False,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    filter_queue: Sequence[tuple[str, str]] | None = None,
    overwrite: bool = False,
    skip_existing: bool = False,
    yes: bool = False,
    no: bool = False,
    output_dir: str | None = None,
    tab_color: str | None = None,
) -> bool:
    """Open the collected Explorer selection in one Windows Terminal window."""
    terminal = find_windows_terminal()
    if terminal is None:
        return False

    command = build_windows_terminal_command(
        files,
        terminal=terminal,
        merge=merge,
        merge_auto=merge_auto,
        tree=tree,
        all_formats=all_formats,
        include=include,
        exclude=exclude,
        filter_queue=filter_queue,
        overwrite=overwrite,
        skip_existing=skip_existing,
        yes=yes,
        no=no,
        output_dir=output_dir,
        tab_color=tab_color,
    )
    environment = os.environ.copy()
    if getattr(sys, "frozen", False):
        environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"

    try:
        subprocess.Popen(command, env=environment, close_fds=True)
    except OSError:
        return False
    return True
