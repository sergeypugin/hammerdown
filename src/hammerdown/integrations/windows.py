from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from hammerdown import SUPPORTED_EXTENSIONS

from ._common import _remove_install_dir


def _install_windows(command: str) -> None:
    import winreg

    app_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "hammerdown"
    app_dir.mkdir(parents=True, exist_ok=True)

    # Locate package icons
    icon_path = ""
    merge_icon_path = ""
    tree_icon_path = ""
    tree_all_icon_path = ""

    assets_dir: Path | None = None
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates = [Path(meipass) / "hammerdown" / "assets", Path(meipass) / "assets"]
        else:
            exe_parent = Path(sys.executable).parent
            candidates = [exe_parent / "hammerdown" / "assets", exe_parent / "assets"]
        for d in candidates:
            if d.is_dir():
                assets_dir = d
                break
    if assets_dir is None:
        p = Path(__file__).resolve().parent.parent / "assets"
        if p.is_dir():
            assets_dir = p

    if assets_dir:
        import shutil

        for filename in ("icon.ico", "icon_merge_darkred.ico", "icon_tree_blue.ico", "icon_tree_all_maroon.ico"):
            src = assets_dir / filename
            if src.is_file():
                try:
                    shutil.copy2(src, app_dir / filename)
                except OSError:
                    pass

    if (app_dir / "icon.ico").is_file():
        icon_path = str(app_dir / "icon.ico")
    if (app_dir / "icon_merge_darkred.ico").is_file():
        merge_icon_path = str(app_dir / "icon_merge_darkred.ico")
    if (app_dir / "icon_tree_blue.ico").is_file():
        tree_icon_path = str(app_dir / "icon_tree_blue.ico")
    if (app_dir / "icon_tree_all_maroon.ico").is_file():
        tree_all_icon_path = str(app_dir / "icon_tree_all_maroon.ico")

    if getattr(sys, "frozen", False):
        if not icon_path:
            icon_path = sys.executable
        if not merge_icon_path:
            merge_icon_path = icon_path
        if not tree_icon_path:
            tree_icon_path = icon_path
        if not tree_all_icon_path:
            tree_all_icon_path = icon_path

    # Thoroughly cleanup all legacy and current verb entries across all registry hives
    verbs_to_clean = ["hammerdown", "hammerdown_merge", "hammerdown_tree", "hammerdown_tree_all", "Convert to Markdown"]
    for verb in verbs_to_clean:
        _remove_registry_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\*\shell\{verb}")
        _remove_registry_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\AllFilesystemObjects\shell\{verb}")
        _remove_registry_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\Directory\shell\{verb}")
        _remove_registry_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\Directory\Background\shell\{verb}")
        for ext in SUPPORTED_EXTENSIONS:
            _remove_registry_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\SystemFileAssociations\{ext}\shell\{verb}")
            _remove_registry_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\.{ext}\shell\{verb}")

    # 1. "Hammerdown" (Standard conversion)
    hd_path = r"Software\Classes\AllFilesystemObjects\shell\hammerdown"
    targets = [hd_path, r"Software\Classes\Directory\shell\hammerdown"]
    for key_path in targets:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Hammerdown")
            if icon_path:
                winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_path)
            winreg.SetValueEx(key, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'{command} --coordinator --right-click "%1"')

    # 2. "Hammerdown and merge" (Dark red icon)
    merge_path = r"Software\Classes\AllFilesystemObjects\shell\hammerdown_merge"
    for key_path in (merge_path, r"Software\Classes\Directory\shell\hammerdown_merge"):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Hammerdown and merge")
            winreg.SetValueEx(key, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
            if merge_icon_path:
                winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, merge_icon_path)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'{command} --coordinator --right-click --merge-auto "%1"')

    # 3. "Hammerdown tree" (Blue icon)
    tree_path = r"Software\Classes\AllFilesystemObjects\shell\hammerdown_tree"
    for key_path in (tree_path, r"Software\Classes\Directory\shell\hammerdown_tree"):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Hammerdown tree")
            winreg.SetValueEx(key, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
            if tree_icon_path:
                winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, tree_icon_path)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'{command} --coordinator --right-click --tree "%1"')

    # 4. "Hammerdown tree with all formats" (Maroon icon)
    tree_all_path = r"Software\Classes\AllFilesystemObjects\shell\hammerdown_tree_all"
    for key_path in (tree_all_path, r"Software\Classes\Directory\shell\hammerdown_tree_all"):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Hammerdown tree with all formats")
            winreg.SetValueEx(key, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
            if tree_all_icon_path:
                winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, tree_all_icon_path)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'{command} --coordinator --right-click --tree --all-formats "%1"')

    bg_key_path = r"Software\Classes\Directory\Background\shell\hammerdown"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, bg_key_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Hammerdown")
        if icon_path:
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_path)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, bg_key_path + r"\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'{command} --coordinator --right-click "%V"')

    # Merge verb for Directory Background
    bg_merge_key_path = r"Software\Classes\Directory\Background\shell\hammerdown_merge"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, bg_merge_key_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Hammerdown and merge")
        if merge_icon_path:
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, merge_icon_path)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, bg_merge_key_path + r"\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'{command} --coordinator --right-click --merge-auto "%V"')

    # Tree verb for Directory Background
    bg_tree_key_path = r"Software\Classes\Directory\Background\shell\hammerdown_tree"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, bg_tree_key_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Hammerdown tree")
        if tree_icon_path:
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, tree_icon_path)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, bg_tree_key_path + r"\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'{command} --coordinator --right-click --tree "%V"')

    # Tree with all formats verb for Directory Background
    bg_tree_all_key_path = r"Software\Classes\Directory\Background\shell\hammerdown_tree_all"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, bg_tree_all_key_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Hammerdown tree with all formats")
        if tree_all_icon_path:
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, tree_all_icon_path)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, bg_tree_all_key_path + r"\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'{command} --coordinator --right-click --tree --all-formats "%V"')

    sendto_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "Microsoft" / "Windows" / "SendTo"
    if sendto_dir.is_dir():
        cmd_file = sendto_dir / "Hammerdown.cmd"
        cmd_file.write_text(f'@echo off\nchcp 65001 >nul\n{command} --coordinator --right-click %*\n', encoding="utf-8")

        merge_cmd_file = sendto_dir / "Hammerdown and merge.cmd"
        merge_cmd_file.write_text(f'@echo off\nchcp 65001 >nul\n{command} --coordinator --right-click --merge-auto %*\n', encoding="utf-8")

        tree_cmd_file = sendto_dir / "Hammerdown tree.cmd"
        tree_cmd_file.write_text(f'@echo off\nchcp 65001 >nul\n{command} --coordinator --right-click --tree %*\n', encoding="utf-8")

        tree_all_cmd_file = sendto_dir / "Hammerdown tree with all formats.cmd"
        tree_all_cmd_file.write_text(f'@echo off\nchcp 65001 >nul\n{command} --coordinator --right-click --tree --all-formats %*\n', encoding="utf-8")

        # Cleanup legacy SendTo shortcuts
        (sendto_dir / "Hammer down.cmd").unlink(missing_ok=True)
        (sendto_dir / "Hammer down and merge.cmd").unlink(missing_ok=True)
        (sendto_dir / "Hammer down.lnk").unlink(missing_ok=True)

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

    verbs_to_clean = ["hammerdown", "hammerdown_merge", "hammerdown_tree", "hammerdown_tree_all", "Convert to Markdown"]
    for verb in verbs_to_clean:
        _remove_registry_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\*\shell\{verb}")
        _remove_registry_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\AllFilesystemObjects\shell\{verb}")
        _remove_registry_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\Directory\shell\{verb}")
        _remove_registry_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\Directory\Background\shell\{verb}")
        for ext in SUPPORTED_EXTENSIONS:
            _remove_registry_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\SystemFileAssociations\{ext}\shell\{verb}")
            _remove_registry_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\.{ext}\shell\{verb}")
    sendto_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "Microsoft" / "Windows" / "SendTo"
    (sendto_dir / "Hammerdown.cmd").unlink(missing_ok=True)
    (sendto_dir / "Hammerdown and merge.cmd").unlink(missing_ok=True)
    (sendto_dir / "Hammerdown tree.cmd").unlink(missing_ok=True)
    (sendto_dir / "Hammerdown tree with all formats.cmd").unlink(missing_ok=True)
    (sendto_dir / "Hammer down.cmd").unlink(missing_ok=True)
    (sendto_dir / "Hammer down and merge.cmd").unlink(missing_ok=True)
    (sendto_dir / "Hammer down.lnk").unlink(missing_ok=True)
    install_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Programs" / "hammerdown"
    _remove_install_dir(install_dir)