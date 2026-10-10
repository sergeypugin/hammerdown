from __future__ import annotations

import argparse
import concurrent.futures
import logging
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Sequence

from hammerdown import SUPPORTED_EXTENSIONS, __version__
from hammerdown.utils import format_duration, normalize_path

logger = logging.getLogger("hammerdown")


def _installed_command() -> tuple[Path, str]:
    if os.name == "nt":
        app_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Programs" / "hammerdown"
    else:
        app_dir = Path.home() / ".local" / "share" / "hammerdown"
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
        # Try to use installed icon.ico from the package directory if running as Python script
        try:
            pkg_icon = Path(__file__).resolve().parent / "icon.ico"
            if pkg_icon.is_file():
                icon_path = str(pkg_icon)
        except Exception:
            pass
        if not icon_path:
            icon_path = command.split('"')[1]

    extensions = list(SUPPORTED_EXTENSIONS)
    for ext in extensions:
        key_path = rf"Software\Classes\SystemFileAssociations\{ext}\shell\hammerdown"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Hammer down file")
            if icon_path:
                winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_path)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'{command} "%1"')


def _install_unix(command: str) -> None:
    bin_dir = Path.home() / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher = bin_dir / "hammerdown"
    launcher.write_text(f"#!/bin/sh\nexec {command} \"$@\"\n", encoding="utf-8")
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    if sys.platform.startswith("linux"):
        nautilus_dir = Path.home() / ".local" / "share" / "nautilus" / "scripts"
        nautilus_dir.mkdir(parents=True, exist_ok=True)
        script = nautilus_dir / "Hammer down file"
        script.write_text('exec "$HOME/.local/bin/hammerdown" "$@"\n', encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install() -> bool:
    try:
        _, command = _installed_command()
        if os.name == "nt":
            _install_windows(command)
        else:
            _install_unix(command)
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


def uninstall() -> bool:
    try:
        if os.name == "nt":
            import winreg

            extensions = [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".txt", ".md", ".log", ".csv"]
            for ext in extensions:
                _remove_registry_tree(
                    winreg.HKEY_CURRENT_USER,
                    rf"Software\Classes\SystemFileAssociations\{ext}\shell\hammerdown",
                )
                _remove_registry_tree(
                    winreg.HKEY_CURRENT_USER,
                    rf"Software\Classes\SystemFileAssociations\{ext}\shell\Convert to Markdown",
                )
            install_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Programs" / "hammerdown"
        else:
            (Path.home() / ".local" / "bin" / "hammerdown").unlink(missing_ok=True)
            (Path.home() / ".local" / "share" / "nautilus" / "scripts" / "Hammer down file").unlink(missing_ok=True)
            (Path.home() / ".local" / "share" / "nautilus" / "scripts" / "Convert to Markdown").unlink(missing_ok=True)
            install_dir = Path.home() / ".local" / "share" / "hammerdown"

        try:
            if install_dir.exists():
                shutil.rmtree(install_dir)
        except OSError:
            logger.warning("Could not remove installed program files at %s", install_dir)
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


def _process_single_file(args_tuple: tuple[str, bool, bool, bool, bool]) -> bool:
    from hammerdown.core import convert_file

    file_path, force, in_place, quiet, overwrite = args_tuple
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    if quiet:
        logger.setLevel(logging.ERROR)
    return convert_file(file_path, force=force, in_place=in_place, overwrite=overwrite)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hammerdown",
        description="Convert PDF and office documents to Markdown",
    )
    parser.add_argument("-v", "--version", action="version", version=f"hammerdown {__version__}")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--install", action="store_true", help="Install the file-manager integration")
    action.add_argument("--uninstall", action="store_true", help="Remove the file-manager integration")
    parser.add_argument("--update", action="store_true", help="Update hammerdown to the latest version")
    parser.add_argument("-i", "--in-place", action="store_true", help="Save output Markdown and images in the same directory as the input file")
    parser.add_argument("-w", "--overwrite", action="store_true", help="Overwrite input text file in-place instead of creating a copy")
    parser.add_argument("-f", "--force", action="store_true", help="Overwrite existing output directories/files")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress routine conversion messages")
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

    files = args.files or _select_files()
    if not files:
        return 0

    from hammerdown.core import convert_file

    started_at = time.monotonic()
    results: list[bool] = []
    if len(files) == 1:
        results.append(convert_file(files[0], force=args.force, in_place=args.in_place, overwrite=args.overwrite))
    else:
        max_workers = min(len(files), os.cpu_count() or 4)
        worker_args = [(f, args.force, args.in_place, args.quiet, args.overwrite) for f in files]
        try:
            with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
                results = list(executor.map(_process_single_file, worker_args))
        except Exception:
            results = [convert_file(f, force=args.force, in_place=args.in_place, overwrite=args.overwrite) for f in files]

    failed_count = results.count(False)
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
