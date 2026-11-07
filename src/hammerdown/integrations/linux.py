from __future__ import annotations

import shutil
import stat
import subprocess
from pathlib import Path

from ._common import _install_launcher, _quote_desktop_exec, _quote_if_needed, _remove_install_dir

_HICOLOR_ICON_NAMES: tuple[str, ...] = (
    "hammerdown.png",
    "hammerdown_merge.png",
    "hammerdown_tree.png",
    "hammerdown_tree_all.png",
)

LINUX_MIME_TYPES: tuple[str, ...] = (
    "application/pdf",
    "application/epub+zip",
    "application/x-mobipocket-ebook",
    "application/x-fictionbook+xml",
    "application/vnd.ms-xpsdocument",
    "application/oxps",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-powerpoint",
    "text/csv",
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "text/x-log",
    "text/html",
    "text/htm",
    "application/zip",
    "inode/directory",
)


def _desktop_file_content(exec_cmd: str) -> str:
    mimes = ";".join(LINUX_MIME_TYPES) + ";"
    return (
        "[Desktop Entry]\n"
        "Version=1.0\n"
        "Type=Application\n"
        "Name=Hammerdown\n"
        "GenericName=Document to Markdown Converter\n"
        "Comment=Convert PDF and office documents to Markdown\n"
        f"Exec={exec_cmd} %F\n"
        "Icon=hammerdown\n"
        "Terminal=false\n"
        f"MimeType={mimes}\n"
        "Categories=Utility;Office;\n"
        "StartupNotify=false\n"
        "NoDisplay=false\n"
        "Actions=Merge;Tree;TreeAll;\n"
        "\n"
        "[Desktop Action Merge]\n"
        "Name=Hammerdown and merge\n"
        "Icon=hammerdown_merge\n"
        "Exec=" + exec_cmd + " --coordinator --right-click --merge-auto %F\n"
        "\n"
        "[Desktop Action Tree]\n"
        "Name=Hammerdown tree\n"
        "Icon=hammerdown_tree\n"
        "Exec=" + exec_cmd + " --tree %F\n"
        "\n"
        "[Desktop Action TreeAll]\n"
        "Name=Hammerdown tree with all formats\n"
        "Icon=hammerdown_tree_all\n"
        "Exec=" + exec_cmd + " --tree --all-formats %F\n"
    )


def _kde_servicemenu_content(exec_cmd: str) -> str:
    mimes = ";".join(LINUX_MIME_TYPES) + ";"
    return (
        "[Desktop Entry]\n"
        "Type=Service\n"
        "ServiceTypes=KonqPopupMenu/Plugin\n"
        f"MimeType={mimes}\n"
        "Actions=HammerDown;HammerDownMerge;HammerDownTree;HammerDownTreeAll;\n"
        "X-KDE-Priority=TopLevel\n"
        "X-KDE-Submenu=Hammerdown\n"
        "\n"
        "[Desktop Action HammerDown]\n"
        "Name=Hammerdown\n"
        "Icon=hammerdown\n"
        f"Exec={exec_cmd} %F\n"
        "\n"
        "[Desktop Action HammerDownMerge]\n"
        "Name=Hammerdown and merge\n"
        "Icon=hammerdown_merge\n"
        f"Exec={exec_cmd} --coordinator --right-click --merge-auto %F\n"
        "\n"
        "[Desktop Action HammerDownTree]\n"
        "Name=Hammerdown tree\n"
        "Icon=hammerdown_tree\n"
        f"Exec={exec_cmd} --tree %F\n"
        "\n"
        "[Desktop Action HammerDownTreeAll]\n"
        "Name=Hammerdown tree with all formats\n"
        "Icon=hammerdown_tree_all\n"
        f"Exec={exec_cmd} --tree --all-formats %F\n"
    )


def _find_icon_pngs() -> dict[str, Path]:
    pkg_dir = Path(__file__).resolve().parent.parent / "assets"
    root_assets = Path(__file__).resolve().parent.parent.parent.parent / "assets"

    mapping = {
        "hammerdown.png": ["icon.png"],
        "hammerdown_merge.png": ["icon_merge_darkred.png", "icon_merge_orange.png", "icon.png"],
        "hammerdown_tree.png": ["icon_tree_blue.png", "icon.png"],
        "hammerdown_tree_all.png": ["icon_tree_all_maroon.png", "icon.png"],
    }

    found: dict[str, Path] = {}
    for target_name, candidates in mapping.items():
        for cand in candidates:
            for parent in (pkg_dir, root_assets):
                p = parent / cand
                if p.is_file():
                    found[target_name] = p
                    break
            if target_name in found:
                break
    return found


def _install_linux(command: str, home_dir: Path | None = None) -> None:
    home = home_dir or Path.home()
    launcher = _install_launcher(command, home)
    exec_cmd = _quote_desktop_exec(launcher)

    apps_dir = home / ".local" / "share" / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    (apps_dir / "hammerdown.desktop").write_text(_desktop_file_content(exec_cmd), encoding="utf-8")

    kde6_dir = home / ".local" / "share" / "kio" / "servicemenus"
    kde6_dir.mkdir(parents=True, exist_ok=True)
    (kde6_dir / "hammerdown.desktop").write_text(_kde_servicemenu_content(exec_cmd), encoding="utf-8")

    kde5_dir = home / ".local" / "share" / "kservices5" / "ServiceMenus"
    kde5_dir.mkdir(parents=True, exist_ok=True)
    (kde5_dir / "hammerdown.desktop").write_text(_kde_servicemenu_content(exec_cmd), encoding="utf-8")

    for script_parent in (
        home / ".local" / "share" / "nautilus" / "scripts",
        home / ".local" / "share" / "nemo" / "scripts",
        home / ".config" / "caja" / "scripts",
    ):
        script_parent.mkdir(parents=True, exist_ok=True)
        
        # Standard conversion
        script_file = script_parent / "Hammerdown"
        script_file.write_text(f'exec {_quote_if_needed(launcher)} "$@"\n', encoding="utf-8")
        try:
            script_file.chmod(script_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            pass

        # Merge mode
        merge_script = script_parent / "Hammerdown and merge"
        merge_script.write_text(f'exec {_quote_if_needed(launcher)} --coordinator --right-click --merge-auto "$@"\n', encoding="utf-8")
        try:
            merge_script.chmod(merge_script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            pass

        # Tree mode
        tree_script = script_parent / "Hammerdown tree"
        tree_script.write_text(f'exec {_quote_if_needed(launcher)} --tree "$@"\n', encoding="utf-8")
        try:
            tree_script.chmod(tree_script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            pass

        # Tree with all formats
        tree_all_script = script_parent / "Hammerdown tree with all formats"
        tree_all_script.write_text(f'exec {_quote_if_needed(launcher)} --tree --all-formats "$@"\n', encoding="utf-8")
        try:
            tree_all_script.chmod(tree_all_script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            pass

    icon_map = _find_icon_pngs()
    icon_dest_dir = home / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    icon_dest_dir.mkdir(parents=True, exist_ok=True)
    app_dir = home / ".local" / "share" / "hammerdown"
    app_dir.mkdir(parents=True, exist_ok=True)

    for target_name, src_path in icon_map.items():
        try:
            shutil.copy2(src_path, icon_dest_dir / target_name)
        except OSError:
            pass
        try:
            shutil.copy2(src_path, app_dir / target_name)
        except OSError:
            pass

    update_db = shutil.which("update-desktop-database")
    if update_db:
        try:
            subprocess.run([update_db, str(apps_dir)], capture_output=True, check=False)
        except Exception:
            pass


def _uninstall_linux(home_dir: Path | None = None) -> None:
    home = home_dir or Path.home()
    (home / ".local" / "bin" / "hammerdown").unlink(missing_ok=True)
    (home / ".local" / "share" / "applications" / "hammerdown.desktop").unlink(missing_ok=True)
    (home / ".local" / "share" / "kio" / "servicemenus" / "hammerdown.desktop").unlink(missing_ok=True)
    (home / ".local" / "share" / "kservices5" / "ServiceMenus" / "hammerdown.desktop").unlink(missing_ok=True)
    (home / ".local" / "share" / "nautilus" / "scripts" / "Hammerdown").unlink(missing_ok=True)
    (home / ".local" / "share" / "nautilus" / "scripts" / "Hammerdown and merge").unlink(missing_ok=True)
    (home / ".local" / "share" / "nautilus" / "scripts" / "Hammerdown tree").unlink(missing_ok=True)
    (home / ".local" / "share" / "nautilus" / "scripts" / "Hammerdown tree with all formats").unlink(missing_ok=True)
    (home / ".local" / "share" / "nautilus" / "scripts" / "Hammer down file").unlink(missing_ok=True)
    (home / ".local" / "share" / "nautilus" / "scripts" / "Convert to Markdown").unlink(missing_ok=True)
    (home / ".local" / "share" / "nemo" / "scripts" / "Hammerdown").unlink(missing_ok=True)
    (home / ".local" / "share" / "nemo" / "scripts" / "Hammerdown and merge").unlink(missing_ok=True)
    (home / ".local" / "share" / "nemo" / "scripts" / "Hammerdown tree").unlink(missing_ok=True)
    (home / ".local" / "share" / "nemo" / "scripts" / "Hammerdown tree with all formats").unlink(missing_ok=True)
    (home / ".local" / "share" / "nemo" / "scripts" / "Hammer down file").unlink(missing_ok=True)
    (home / ".config" / "caja" / "scripts" / "Hammerdown").unlink(missing_ok=True)
    (home / ".config" / "caja" / "scripts" / "Hammerdown and merge").unlink(missing_ok=True)
    (home / ".config" / "caja" / "scripts" / "Hammerdown tree").unlink(missing_ok=True)
    (home / ".config" / "caja" / "scripts" / "Hammerdown tree with all formats").unlink(missing_ok=True)
    (home / ".config" / "caja" / "scripts" / "Hammer down file").unlink(missing_ok=True)
    icon_dir = home / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    for icon_name in _HICOLOR_ICON_NAMES:
        (icon_dir / icon_name).unlink(missing_ok=True)

    _remove_install_dir(home / ".local" / "share" / "hammerdown")

    update_db = shutil.which("update-desktop-database")
    if update_db:
        try:
            subprocess.run([update_db, str(home / ".local" / "share" / "applications")], capture_output=True, check=False)
        except Exception:
            pass
