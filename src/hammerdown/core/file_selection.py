from __future__ import annotations

import subprocess

from . import SUPPORTED_EXTENSIONS
from .platform_utils import is_windows


def _select_files() -> list[str]:
    if is_windows():
        selected = _select_files_windows()
        if selected is not None:
            return selected
    return _select_files_tkinter()


def _select_files_windows() -> list[str] | None:
    try:
        pattern = ";".join(f"*{ext}" for ext in SUPPORTED_EXTENSIONS)
        ps_files = (
            "Add-Type -AssemblyName PresentationFramework | Out-Null;"
            "$dialog = New-Object Microsoft.Win32.OpenFileDialog;"
            f"$dialog.Filter = 'Supported Documents|{pattern}|All Files (*.*)|*.*';"
            "$dialog.Multiselect = $true;"
            "$dialog.Title = 'Select documents to convert';"
            "if ($dialog.ShowDialog() -eq $true) { $dialog.FileNames }"
        )
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_files],
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    if res.returncode != 0:
        return None
    return [line.strip() for line in (res.stdout or "").splitlines() if line.strip()]


def _select_files_tkinter() -> list[str]:
    try:
        from tkinter import Tk, filedialog

        root = Tk()
        root.withdraw()
        try:
            return list(filedialog.askopenfilenames(title="Select documents to convert"))
        finally:
            root.destroy()
    except Exception:
        return []
