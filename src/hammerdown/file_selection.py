from __future__ import annotations


import os
import subprocess
from typing import Sequence

from hammerdown import SUPPORTED_EXTENSIONS

def _select_files() -> Sequence[str]:
    selected_paths: list[str] = []

    if os.name == "nt":
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
            if res.returncode == 0 and res.stdout.strip():
                selected_paths.extend([line.strip() for line in res.stdout.strip().splitlines() if line.strip()])
                return selected_paths
        except Exception:
            pass

    try:
        from tkinter import Tk, filedialog

        root = Tk()
        root.withdraw()
        try:
            files = filedialog.askopenfilenames(title="Select documents to convert")
            if files:
                selected_paths.extend(files)
        finally:
            root.destroy()
    except Exception:
        pass

    return selected_paths
