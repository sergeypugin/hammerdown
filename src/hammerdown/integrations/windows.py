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
    merge_icon_path = ""
    if getattr(sys, "frozen", False):
        icon_path = sys.executable
        merge_icon_path = sys.executable
    else:
        try:
            pkg_icon = Path(__file__).resolve().parent.parent / "icon.ico"
            merge_pkg_icon = Path(__file__).resolve().parent.parent / "icon_merge_orange.ico"
            if pkg_icon.is_file():
                icon_path = str(pkg_icon)
            if merge_pkg_icon.is_file():
                merge_icon_path = str(merge_pkg_icon)
        except Exception:
            pass
        if not icon_path:
            icon_path = command.split('"')[1]
        if not merge_icon_path:
            merge_icon_path = icon_path

    # Regular "Hammer down file" verb (single file or multi-select without merge)
    all_files_path = r"Software\Classes\AllFilesystemObjects\shell\hammerdown"

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
                # Explorer hides a verb when AppliesTo does not match every
                # selected item, so the filter is removed and unsupported
                # files are reported by the batch summary instead.
                try:
                    winreg.DeleteValue(key, "AppliesTo")
                except FileNotFoundError:
                    pass

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'{command} --coordinator --right-click %1')

    # "Hammer down and merge" verb (multi-select, merges into single markdown)
    merge_path = r"Software\Classes\AllFilesystemObjects\shell\hammerdown_merge"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, merge_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Hammer down and merge")
        # Document = pass all selected files in one invocation
        winreg.SetValueEx(key, "MultiSelectModel", 0, winreg.REG_SZ, "Document")
        # Use distinct orange icon for merge verb
        if merge_icon_path:
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, merge_icon_path)
        try:
            winreg.DeleteValue(key, "AppliesTo")
        except FileNotFoundError:
            pass
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, merge_path + r"\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'{command} --coordinator --right-click --merge-auto')

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
        # chcp 65001 sets UTF-8 code page so %* expands Unicode filenames correctly
        cmd_file.write_text(f'@echo off\nchcp 65001 >nul\n{command} --coordinator --right-click %*\n', encoding="utf-8")

        merge_cmd_file = sendto_dir / "Hammer down and merge.cmd"
        merge_cmd_file.write_text(f'@echo off\nchcp 65001 >nul\n{command} --coordinator --right-click --merge-auto %*\n', encoding="utf-8")

    install_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Programs" / "hammerdown"
    legacy_launcher = install_dir / "hammerdown_sendto.cmd"
    if legacy_launcher.is_file():
        legacy_launcher.write_text(f'@echo off\nchcp 65001 >nul\n{command} --coordinator --right-click %*\n', encoding="utf-8")


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
    _remove_registry_tree(winreg.HKEY_CURRENT_USER, r"Software\Classes\AllFilesystemObjects\shell\hammerdown_merge")
    _remove_registry_tree(winreg.HKEY_CURRENT_USER, r"Software\Classes\Directory\shell\hammerdown")
    _remove_registry_tree(winreg.HKEY_CURRENT_USER, r"Software\Classes\Directory\Background\shell\hammerdown")
    sendto_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "Microsoft" / "Windows" / "SendTo"
    (sendto_dir / "Hammer down.cmd").unlink(missing_ok=True)
    (sendto_dir / "Hammer down and merge.cmd").unlink(missing_ok=True)
    (sendto_dir / "Hammer down.lnk").unlink(missing_ok=True)
    install_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Programs" / "hammerdown"
    _remove_install_dir(install_dir)