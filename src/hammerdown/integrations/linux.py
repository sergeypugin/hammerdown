from __future__ import annotations

import logging
import shutil
import stat
import subprocess
from pathlib import Path

logger = logging.getLogger("hammerdown")

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
    "inode/directory",
)


def _desktop_file_content(exec_cmd: str) -> str:
    mimes = ";".join(LINUX_MIME_TYPES) + ";"
    return (
        "[Desktop Entry]\n"
        "Version=1.0\n"
        "Type=Application\n"
        "Name=Hammer down\n"
        "GenericName=Document to Markdown Converter\n"
        "Comment=Convert PDF and office documents to Markdown\n"
        f"Exec={exec_cmd} %F\n"
        "Icon=hammerdown\n"
        "Terminal=false\n"
        f"MimeType={mimes}\n"
        "Categories=Utility;Office;\n"
        "StartupNotify=false\n"
        "NoDisplay=false\n"
    )


def _kde_servicemenu_content(exec_cmd: str) -> str:
    mimes = ";".join(LINUX_MIME_TYPES) + ";"
    return (
        "[Desktop Entry]\n"
        "Type=Service\n"
        "ServiceTypes=KonqPopupMenu/Plugin\n"
        f"MimeType={mimes}\n"
        "Actions=HammerDown;\n"
        "X-KDE-Priority=TopLevel\n"
        "X-KDE-Submenu=\n"
        "\n"
        "[Desktop Action HammerDown]\n"
        "Name=Hammer down file\n"
        "Icon=hammerdown\n"
        f"Exec={exec_cmd} %F\n"
    )


def _find_icon_png() -> Path | None:
    pkg_dir = Path(__file__).resolve().parent.parent
    candidates = [
        pkg_dir / "icon.png",
        pkg_dir.parent.parent / "assets" / "icon.png",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


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


def _install_linux(command: str, home_dir: Path | None = None) -> None:
    home = home_dir or Path.home()
    launcher = _install_launcher(command, home)
    exec_cmd = f'"{launcher}"' if " " in str(launcher) else str(launcher)

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
        script_file = script_parent / "Hammer down file"
        script_file.write_text(f'exec "{launcher}" "$@"\n', encoding="utf-8")
        try:
            script_file.chmod(script_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            pass

    icon_src = _find_icon_png()
    if icon_src:
        icon_dest_dir = home / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps"
        icon_dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(icon_src, icon_dest_dir / "hammerdown.png")
        except OSError:
            pass

        app_dir = home / ".local" / "share" / "hammerdown"
        app_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(icon_src, app_dir / "hammerdown.png")
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
    (home / ".local" / "share" / "nautilus" / "scripts" / "Hammer down file").unlink(missing_ok=True)
    (home / ".local" / "share" / "nautilus" / "scripts" / "Convert to Markdown").unlink(missing_ok=True)
    (home / ".local" / "share" / "nemo" / "scripts" / "Hammer down file").unlink(missing_ok=True)
    (home / ".config" / "caja" / "scripts" / "Hammer down file").unlink(missing_ok=True)
    (home / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps" / "hammerdown.png").unlink(missing_ok=True)

    install_dir = home / ".local" / "share" / "hammerdown"
    if install_dir.exists():
        try:
            shutil.rmtree(install_dir)
        except OSError:
            logger.warning("Could not remove installed program files at %s", install_dir)

    update_db = shutil.which("update-desktop-database")
    if update_db:
        try:
            subprocess.run([update_db, str(home / ".local" / "share" / "applications")], capture_output=True, check=False)
        except Exception:
            pass
