from __future__ import annotations

import argparse
import concurrent.futures
import logging
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Sequence

from hammerdown import APP_DESCRIPTION, APP_NAME, SUPPORTED_EXTENSIONS, TEXT_EXTENSIONS, __version__
from hammerdown.ipc import IPCCoordinator, try_delegate_to_coordinator
from hammerdown.utils import format_duration, normalize_path

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


def _installed_command(home_dir: Path | None = None) -> tuple[Path, str]:
    home = home_dir or Path.home()
    if os.name == "nt":
        app_dir = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local")) / "Programs" / "hammerdown"
    else:
        app_dir = home / ".local" / "share" / "hammerdown"
    app_dir.mkdir(parents=True, exist_ok=True)

    if getattr(sys, "frozen", False):
        suffix = ".exe" if os.name == "nt" else ""
        target = app_dir / f"hammerdown{suffix}"
        if Path(sys.executable).resolve() != target.resolve():
            shutil.move(sys.executable, target)
        return app_dir, str(target)

    # In a structured package, we find out where to copy/point. Since it's a package,
    # python -m hammerdown or the script is installed. But let's copy the launcher CLI file or point to the package launcher.
    # To keep exact behavior for dev installs, we copy a booster/loader script or the cli.py.
    # Let's find out how the original copy of converter.py was run:
    # it was pointing python to converter.py.
    # Now it can copy a file that runs the package.
    # But for a module install (non-frozen), we can write a small runner file or copy this cli.py.
    # Let's write a simple launcher inside the app_dir.
    target = app_dir / "hammerdown_runner.py"
    target.write_text("import sys\nfrom hammerdown.cli import main\nif __name__ == '__main__': sys.exit(main())", encoding="utf-8")
    return app_dir, f'"{sys.executable}" "{target}"'


def _install_windows(command: str) -> None:
    import winreg

    icon_path = ""
    if getattr(sys, "frozen", False):
        icon_path = sys.executable
    else:
        try:
            pkg_icon = Path(__file__).resolve().parent / "icon.ico"
            if pkg_icon.is_file():
                icon_path = str(pkg_icon)
        except Exception:
            pass
        if not icon_path:
            icon_path = command.split('"')[1]

    targets = [
        *(rf"Software\Classes\SystemFileAssociations\{ext}\shell\hammerdown" for ext in SUPPORTED_EXTENSIONS),
        r"Software\Classes\Directory\shell\hammerdown",
    ]
    for key_path in targets:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Hammer down file")
            if icon_path:
                winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_path)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'{command} --coordinator "%1"')

    bg_key_path = r"Software\Classes\Directory\Background\shell\hammerdown"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, bg_key_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Hammer down directory")
        if icon_path:
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_path)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, bg_key_path + r"\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'{command} --coordinator "%V"')

    sendto_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "Microsoft" / "Windows" / "SendTo"
    if sendto_dir.is_dir():
        cmd_file = sendto_dir / "Hammer down.cmd"
        cmd_file.write_text(f'@echo off\n{command} --coordinator %*\n', encoding="utf-8")


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
    pkg_dir = Path(__file__).resolve().parent
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


def _create_macos_workflow(workflow_dir: Path, launcher: Path | str) -> None:
    contents_dir = workflow_dir / "Contents"
    contents_dir.mkdir(parents=True, exist_ok=True)

    info_data = {
        "CFBundleIdentifier": "com.hammerdown.quickaction",
        "CFBundleName": "Hammer down",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "NSServices": [
            {
                "NSBackgroundColorName": "background",
                "NSIconName": "NSTouchBarDocument",
                "NSMenuItem": {
                    "default": "Hammer down",
                },
                "NSMessage": "runWorkflowAsService",
                "NSRequiredContext": {
                    "NSApplicationIdentifier": "com.apple.finder",
                },
                "NSSendFileTypes": [
                    "public.item",
                ],
            }
        ],
    }
    with open(contents_dir / "Info.plist", "wb") as fp:
        plistlib.dump(info_data, fp, fmt=plistlib.FMT_XML)

    exec_target = f'"{launcher}"' if " " in str(launcher) else str(launcher)
    wflow_data = {
        "AMApplicationBuild": "523",
        "AMApplicationVersion": "2.10",
        "AMDocumentVersion": "2",
        "actions": [
            {
                "action": {
                    "AMAccepts": {
                        "Container": "List",
                        "Optional": True,
                        "Types": ["com.apple.cocoa.path"],
                    },
                    "AMActionVersion": "2.0.3",
                    "AMApplication": ["Automator"],
                    "AMCategory": "AMCategoryUtilities",
                    "AMParameterProperties": {
                        "COMMAND_STRING": {},
                        "CheckedForUserDefaultShell": {},
                        "inputMethod": {},
                        "shell": {},
                        "source": {},
                    },
                    "AMProvides": {
                        "Container": "List",
                        "Types": ["com.apple.cocoa.path"],
                    },
                    "ActionBundlePath": "/System/Library/Automator/Run Shell Script.action",
                    "ActionName": "Run Shell Script",
                    "ActionParameters": {
                        "COMMAND_STRING": f'exec {exec_target} "$@"',
                        "CheckedForUserDefaultShell": True,
                        "inputMethod": 1,
                        "shell": "/bin/sh",
                        "source": "",
                    },
                    "BundleIdentifier": "com.apple.RunShellScript",
                    "CFBundleIdentifier": "com.apple.RunShellScript",
                    "Class Name": "RunShellScriptAction",
                    "InputUUID": str(uuid.uuid4()),
                    "Keywords": ["Shell", "Script", "Command", "Run", "Unix"],
                    "OutputUUID": str(uuid.uuid4()),
                    "UUID": str(uuid.uuid4()),
                    "UnlocalizedApplications": ["Automator"],
                }
            }
        ],
        "connectors": {},
        "workflowMetaData": {
            "applicationBundleIDsByPath": {},
            "applicationPaths": [],
            "inputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "outputTypeIdentifier": "com.apple.Automator.nothing",
            "presentationMode": 15,
            "processesInput": False,
            "serviceApplicationBundleID": "com.apple.finder",
            "serviceApplicationPath": "/System/Library/CoreServices/Finder.app",
            "serviceInputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
            "serviceProcessesInput": False,
            "systemImageName": "NSTouchBarDocument",
            "useAutomaticInputType": False,
            "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
        },
    }
    with open(contents_dir / "document.wflow", "wb") as fp:
        plistlib.dump(wflow_data, fp, fmt=plistlib.FMT_XML)


def _create_macos_droplet(app_dest: Path, launcher: Path | str) -> bool:
    osacompile = shutil.which("osacompile")
    if not osacompile:
        return False

    app_dest.parent.mkdir(parents=True, exist_ok=True)
    if app_dest.exists():
        try:
            shutil.rmtree(app_dest)
        except OSError:
            pass

    exec_target = f'"{launcher}"' if " " in str(launcher) else str(launcher)
    applescript_source = (
        'on run\n'
        '    set chosenFiles to choose file with prompt "Select documents to convert:" with multiple selections allowed\n'
        '    open chosenFiles\n'
        'end run\n'
        '\n'
        'on open droppedItems\n'
        f'    set cmd to {repr(exec_target)}\n'
        '    repeat with anItem in droppedItems\n'
        '        set cmd to cmd & " " & quoted form of (POSIX path of anItem)\n'
        '    end repeat\n'
        '    do shell script cmd\n'
        'end open\n'
    )

    try:
        subprocess.run(
            [osacompile, "-o", str(app_dest), "-e", applescript_source],
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return False

    info_plist_path = app_dest / "Contents" / "Info.plist"
    if info_plist_path.is_file():
        try:
            with open(info_plist_path, "rb") as fp:
                info_data = plistlib.load(fp)
            info_data["CFBundleDocumentTypes"] = [
                {
                    "CFBundleTypeName": "Supported Documents",
                    "CFBundleTypeRole": "Viewer",
                    "LSHandlerRank": "Alternate",
                    "LSItemContentTypes": [
                        "public.item",
                        "public.content",
                        "public.data",
                    ],
                }
            ]
            with open(info_plist_path, "wb") as fp:
                plistlib.dump(info_data, fp, fmt=plistlib.FMT_XML)
        except Exception:
            pass

    lsregister = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
    if Path(lsregister).is_file():
        try:
            subprocess.run([lsregister, "-f", str(app_dest)], capture_output=True, check=False)
        except Exception:
            pass

    return True


def _install_macos(command: str, home_dir: Path | None = None) -> None:
    home = home_dir or Path.home()
    launcher = _install_launcher(command, home)

    services_dir = home / "Library" / "Services"
    services_dir.mkdir(parents=True, exist_ok=True)
    _create_macos_workflow(services_dir / "Hammer down.workflow", launcher)

    app_dest = home / "Applications" / "Hammer down.app"
    _create_macos_droplet(app_dest, launcher)

    if sys.platform == "darwin":
        pbs_path = "/System/Library/CoreServices/pbs"
        if Path(pbs_path).is_file():
            try:
                subprocess.run([pbs_path, "-flush"], capture_output=True, check=False)
            except Exception:
                pass


def _install_unix(command: str) -> None:
    if sys.platform == "darwin":
        _install_macos(command)
    else:
        _install_linux(command)


def install() -> bool:
    try:
        _, command = _installed_command()
        if os.name == "nt":
            _install_windows(command)
        elif sys.platform == "darwin":
            _install_macos(command)
        else:
            _install_linux(command)
        logger.info("hammerdown installed successfully.")
        return True
    except (OSError, ImportError) as exc:
        logger.error("Installation failed: %s", exc)
        return False


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
        _remove_registry_tree(
            winreg.HKEY_CURRENT_USER,
            rf"Software\Classes\SystemFileAssociations\{ext}\shell\hammerdown",
        )
        _remove_registry_tree(
            winreg.HKEY_CURRENT_USER,
            rf"Software\Classes\SystemFileAssociations\{ext}\shell\Convert to Markdown",
        )
    _remove_registry_tree(winreg.HKEY_CURRENT_USER, r"Software\Classes\Directory\shell\hammerdown")
    _remove_registry_tree(winreg.HKEY_CURRENT_USER, r"Software\Classes\Directory\Background\shell\hammerdown")
    sendto_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "Microsoft" / "Windows" / "SendTo"
    (sendto_dir / "Hammer down.cmd").unlink(missing_ok=True)
    (sendto_dir / "Hammer down.lnk").unlink(missing_ok=True)
    install_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Programs" / "hammerdown"
    if install_dir.exists():
        try:
            shutil.rmtree(install_dir)
        except OSError:
            logger.warning("Could not remove installed program files at %s", install_dir)


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


def _uninstall_macos(home_dir: Path | None = None) -> None:
    home = home_dir or Path.home()
    (home / ".local" / "bin" / "hammerdown").unlink(missing_ok=True)
    workflow_path = home / "Library" / "Services" / "Hammer down.workflow"
    if workflow_path.exists():
        try:
            shutil.rmtree(workflow_path)
        except OSError:
            pass

    legacy_workflow = home / "Library" / "Services" / "Hammer down file.workflow"
    if legacy_workflow.exists():
        try:
            shutil.rmtree(legacy_workflow)
        except OSError:
            pass

    app_path = home / "Applications" / "Hammer down.app"
    if app_path.exists():
        try:
            shutil.rmtree(app_path)
        except OSError:
            pass

    install_dir = home / ".local" / "share" / "hammerdown"
    if install_dir.exists():
        try:
            shutil.rmtree(install_dir)
        except OSError:
            logger.warning("Could not remove installed program files at %s", install_dir)

    if sys.platform == "darwin":
        pbs_path = "/System/Library/CoreServices/pbs"
        if Path(pbs_path).is_file():
            try:
                subprocess.run([pbs_path, "-flush"], capture_output=True, check=False)
            except Exception:
                pass


def uninstall() -> bool:
    try:
        if os.name == "nt":
            _uninstall_windows()
        elif sys.platform == "darwin":
            _uninstall_macos()
        else:
            _uninstall_linux()
        logger.info("hammerdown integration uninstalled")
        return True
    except (OSError, ImportError) as exc:
        logger.error("Uninstallation failed: %s", exc)
        return False


def _clean_pip_temp() -> None:
    if os.name == "nt":
        temp_dir = Path(tempfile.gettempdir())
        for p in temp_dir.glob("pip-uninstall-*"):
            try:
                shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass


def update() -> bool:
    if not getattr(sys, "frozen", False):
        logger.info("Updating Python package via pip...")
        _clean_pip_temp()
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir", "hammerdown"]
        try:
            subprocess.check_call(cmd)
            _clean_pip_temp()
            install()
            logger.info("Successfully updated hammerdown package.")
            return True
        except subprocess.CalledProcessError:
            cmd_git = [sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir", "git+https://github.com/sergeypugin/hammerdown.git"]
            try:
                subprocess.check_call(cmd_git)
                _clean_pip_temp()
                install()
                logger.info("Successfully updated hammerdown package.")
                return True
            except subprocess.CalledProcessError as exc:
                logger.error("Failed to update via pip: %s", exc)
                return False

    import json
    import urllib.request

    url = "https://api.github.com/repos/sergeypugin/hammerdown/releases/latest"
    req = urllib.request.Request(url, headers={"User-Agent": "hammerdown"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        latest_tag = data.get("tag_name", "").lstrip("v")
        if latest_tag and latest_tag <= __version__:
            logger.info("hammerdown is already at the latest version (%s)", __version__)
            return True

        logger.info("New version available: %s (current: %s)", latest_tag, __version__)
        asset_name = "hammerdown-windows-x64.exe" if os.name == "nt" else "hammerdown-linux-x64"
        if sys.platform == "darwin":
            asset_name = "hammerdown-macos-arm64" if "arm" in os.uname().machine.lower() else "hammerdown-macos-x64"

        download_url = None
        for asset in data.get("assets", []):
            if asset.get("name") == asset_name:
                download_url = asset.get("browser_download_url")
                break

        if not download_url:
            logger.error("No release asset found matching %s", asset_name)
            return False

        logger.info("Downloading %s...", download_url)
        temp_exe = Path(tempfile.gettempdir()) / f"hammerdown-update{'.exe' if os.name == 'nt' else ''}"
        with urllib.request.urlopen(download_url, timeout=30) as resp, open(temp_exe, "wb") as f:
            f.write(resp.read())

        target = Path(sys.executable)
        if os.name == "nt":
            old_exe = target.with_suffix(".exe.old")
            if old_exe.exists():
                try:
                    old_exe.unlink()
                except OSError:
                    pass
            target.rename(old_exe)
            shutil.copy2(temp_exe, target)
        else:
            shutil.copy2(temp_exe, target)
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        logger.info("hammerdown successfully updated to version %s!", latest_tag)
        install()
        return True
    except Exception as exc:
        logger.error("Failed to update: %s", exc)
        return False


def _select_files() -> Sequence[str]:
    if os.name == "nt":
        try:
            pattern = ";".join(f"*{ext}" for ext in SUPPORTED_EXTENSIONS)
            ps_script = (
                "Add-Type -AssemblyName PresentationFramework | Out-Null;"
                "$dialog = New-Object Microsoft.Win32.OpenFileDialog;"
                f"$dialog.Filter = 'Supported Documents|{pattern}|All Files (*.*)|*.*';"
                "$dialog.Multiselect = $true;"
                "$dialog.Title = 'Select documents to convert';"
                "if ($dialog.ShowDialog() -eq $true) { $dialog.FileNames }"
            )
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                stdout = result.stdout.strip()
                return [line.strip() for line in stdout.splitlines() if line.strip()] if stdout else ()
        except Exception:
            pass

    try:
        from tkinter import Tk, filedialog

        root = Tk()
        root.withdraw()
        try:
            return filedialog.askopenfilenames(title="Select documents to convert")
        finally:
            root.destroy()
    except Exception as exc:
        logger.error("No files were provided and the file dialog is unavailable: %s", exc)
        return ()




def _expand_paths(paths: Sequence[str]) -> list[str]:
    expanded: list[str] = []
    for raw in paths:
        p = Path(normalize_path(raw))
        if p.is_dir():
            for root, _, filenames in os.walk(p):
                for f in sorted(filenames):
                    if f.startswith("~$") or f.startswith("."):
                        continue
                    file_path = Path(root) / f
                    if file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                        expanded.append(str(file_path))
        elif p.is_file():
            expanded.append(str(p))
        else:
            expanded.append(raw)
    return expanded


def _merge_converted_files(
    files: Sequence[str],
    results: Sequence[bool],
    merge_target: str,
    overwrite_sources: bool = False,
) -> None:
    merged_sections: list[str] = []
    for file_path, succeeded in zip(files, results):
        if not succeeded:
            continue
        source = Path(normalize_path(file_path))
        stem = source.stem
        ext_clean = source.suffix.lower().lstrip(".")
        out_md_name = f"hm_{stem}_{ext_clean}.md" if ext_clean else f"hm_{stem}.md"
        out_md = source.parent / out_md_name
        if overwrite_sources and source.suffix.lower() in TEXT_EXTENSIONS:
            out_md = source
        if out_md.is_file():
            content = out_md.read_text(encoding="utf-8").strip()
            section = f"# {source.name}\n\n{content}" if content else f"# {source.name}"
            merged_sections.append(section)

    if merged_sections:
        dest = Path(normalize_path(merge_target))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n\n".join(merged_sections) + "\n", encoding="utf-8", newline="\n")
        logger.info("Merged %d documents into %s", len(merged_sections), dest.name)


def _process_single_file(args_tuple: tuple[str, bool, bool, bool, bool]) -> bool:
    from hammerdown.core import convert_file

    file_path, in_place, quiet, overwrite, skip_existing = args_tuple
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    if quiet:
        logger.setLevel(logging.ERROR)
    return convert_file(
        file_path,
        in_place=in_place,
        overwrite=overwrite,
        skip_existing=skip_existing,
    )


def main(argv: Sequence[str] | None = None) -> int:
    if os.name == "nt" and "--coordinator" in sys.argv:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE = 0

    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=APP_DESCRIPTION,
    )
    parser.add_argument("-v", "--version", action="version", version=f"{APP_NAME} {__version__}")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--install", action="store_true", help="Install the file-manager integration")
    action.add_argument("--uninstall", action="store_true", help="Remove the file-manager integration")
    parser.add_argument("--update", action="store_true", help="Update hammerdown to the latest version")
    parser.add_argument("-i", "--in-place", action="store_true", help="Save output Markdown and images in the same directory as the input file")
    parser.add_argument("-w", "--overwrite", action="store_true", help="Overwrite input text file in-place instead of creating a copy")
    parser.add_argument("-s", "--skip-existing", action="store_true", help="Skip conversion if target markdown file already exists")
    parser.add_argument("-m", "--merge", metavar="OUTPUT_MD", help="Merge all converted Markdown documents into a single target Markdown file")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress routine conversion messages")
    parser.add_argument("--coordinator", action="store_true", help="Enable single-instance coordinator mode for batch invocation")
    parser.add_argument("files", nargs="*", help="Files to convert")
    args = parser.parse_args(argv)

    if not logger.handlers:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.quiet:
        logger.setLevel(logging.ERROR)
    if args.install:
        return 0 if install() else 1
    if args.uninstall:
        return 0 if uninstall() else 1
    if args.update:
        return 0 if update() else 1

    raw_files = args.files or _select_files()
    if not raw_files:
        return 0

    files = _expand_paths(raw_files)
    if not files:
        logger.info("No supported documents found to convert")
        return 0

    files.sort()

    use_ipc = args.coordinator or os.environ.get("HAMMERDOWN_COORDINATOR") == "1"
    options = {
        "in_place": args.in_place,
        "overwrite": args.overwrite,
        "skip_existing": args.skip_existing,
        "quiet": args.quiet,
    }

    if use_ipc and try_delegate_to_coordinator(files, options):
        logger.info("Delegated %d files to active hammerdown coordinator", len(files))
        return 0

    coordinator = IPCCoordinator() if use_ipc else None
    if coordinator and coordinator.start():
        if os.name == "nt":
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 5)  # SW_SHOW = 5
                ctypes.windll.user32.SetForegroundWindow(hwnd)

        files = coordinator.collect_files(files, assembly_timeout=0.35)
    elif use_ipc:
        # We delegated successfully, just exit.
        return 0

    from hammerdown.core import convert_file

    started_at = time.monotonic()
    results: list[bool] = []
    try:
        # To maintain ordered output and clean progress bars, we process sequentially in TTY/batch mode.
        # Parallel processing via ProcessPoolExecutor causes interleaved log output and messy progress bars.
        for f in files:
            results.append(
                convert_file(
                    f,
                    in_place=args.in_place,
                    overwrite=args.overwrite,
                    skip_existing=args.skip_existing,
                )
            )
    finally:
        if coordinator:
            coordinator.stop()

    failed_count = results.count(False)
    if args.merge and any(results):
        _merge_converted_files(files, results, args.merge, overwrite_sources=args.overwrite)

    if len(files) > 1 and not args.quiet:
        duration = time.monotonic() - started_at
        logger.info(
            "Batch conversion finished in %s: %d succeeded, %d failed",
            format_duration(duration),
            len(files) - failed_count,
            failed_count,
        )
    return 1 if failed_count else 0


if __name__ == "__main__":
    sys.exit(main())
