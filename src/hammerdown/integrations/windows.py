from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from hammerdown import SUPPORTED_EXTENSIONS

from ._common import _remove_install_dir


def _install_windows(command: str) -> None:
    import winreg

    icon_path = ""
    if getattr(sys, "frozen", False):
        icon_path = sys.executable
    else:
        try:
            pkg_icon = Path(__file__).resolve().parent.parent / "icon.ico"
            if pkg_icon.is_file():
                icon_path = str(pkg_icon)
        except Exception:
            pass
        if not icon_path:
            icon_path = command.split('"')[1]

    all_files_path = r"Software\Classes\AllFilesystemObjects\shell\hammerdown"
    aqs_filter = " OR ".join(f"System.FileExtension:={ext}" for ext in SUPPORTED_EXTENSIONS)

    targets = [
        all_files_path,
        r"Software\Classes\Directory\shell\hammerdown",
    ]
    for key_path in targets:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Hammer down file")
            if icon_path:
                winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_path)

            if key_path == all_files_path:
                winreg.SetValueEx(key, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
                winreg.SetValueEx(key, "AppliesTo", 0, winreg.REG_SZ, aqs_filter)

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'{command} --coordinator --right-click "%1"')

    bg_key_path = r"Software\Classes\Directory\Background\shell\hammerdown"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, bg_key_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Hammer down directory")
        if icon_path:
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_path)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, bg_key_path + r"\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'{command} --coordinator --right-click "%V"')

    sendto_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "Microsoft" / "Windows" / "SendTo"
    if sendto_dir.is_dir():
        cmd_file = sendto_dir / "Hammer down.cmd"
        cmd_file.write_text(f'@echo off\n{command} --coordinator --right-click %*\n', encoding="utf-8")


def _remove_registry_tree(root: Any, path: str) -> None:
    import winreg

    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _remove_registry_tree(root, f"{path}\\{child}")
        winreg.DeleteKey(root, path)
    except FileNotFoundError:
        pass


def _uninstall_windows() -> None:
    import winreg

    for ext in SUPPORTED_EXTENSIONS:
        _remove_registry_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\SystemFileAssociations\{ext}\shell\hammerdown")
        _remove_registry_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\SystemFileAssociations\{ext}\shell\Convert to Markdown")
    _remove_registry_tree(winreg.HKEY_CURRENT_USER, r"Software\Classes\AllFilesystemObjects\shell\hammerdown")
    _remove_registry_tree(winreg.HKEY_CURRENT_USER, r"Software\Classes\Directory\shell\hammerdown")
    _remove_registry_tree(winreg.HKEY_CURRENT_USER, r"Software\Classes\Directory\Background\shell\hammerdown")
    sendto_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "Microsoft" / "Windows" / "SendTo"
    (sendto_dir / "Hammer down.cmd").unlink(missing_ok=True)
    (sendto_dir / "Hammer down.lnk").unlink(missing_ok=True)
    install_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Programs" / "hammerdown"
    _remove_install_dir(install_dir)
