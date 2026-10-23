from __future__ import annotations

import os
import sys
from typing import Sequence


def _bind_console_streams() -> bool:
    try:
        stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")
        stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        stderr = open("CONOUT$", "w", encoding="utf-8", errors="backslashreplace", buffering=1)
    except OSError:
        return False

    for stream, descriptor in ((stdin, 0), (stdout, 1), (stderr, 2)):
        try:
            os.dup2(stream.fileno(), descriptor)
        except OSError:
            pass

    sys.stdin = sys.__stdin__ = stdin
    sys.stdout = sys.__stdout__ = stdout
    sys.stderr = sys.__stderr__ = stderr
    return True


def attach_parent_console(argv: Sequence[str] | None = None) -> bool:
    """Bind a windowed Windows process to its parent terminal when one exists.

    Console and redirected runs keep their original streams so that
    ``hammerdown --stdout > output.md`` still works. A windowed process without
    a console keeps silent streams instead of ``None`` so logging stays safe.
    """
    if os.name != "nt":
        return False

    arguments = tuple(argv if argv is not None else sys.argv[1:])
    if "--coordinator" in arguments:
        _bind_silent_streams()
        return False
    if sys.stdout is not None and sys.stderr is not None:
        return True

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.AttachConsole.argtypes = (wintypes.DWORD,)
    kernel32.AttachConsole.restype = wintypes.BOOL
    attached = bool(kernel32.AttachConsole(wintypes.DWORD(-1).value))
    if attached or ctypes.get_last_error() == 5:
        if _bind_console_streams():
            return True

    _bind_silent_streams()
    return False


def _bind_silent_streams() -> None:
    """Give a windowed process writable streams that discard output."""
    if sys.stdout is None:
        sys.stdout = sys.__stdout__ = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = sys.__stderr__ = open(os.devnull, "w", encoding="utf-8")
    if sys.stdin is None:
        sys.stdin = sys.__stdin__ = open(os.devnull, "r", encoding="utf-8")
