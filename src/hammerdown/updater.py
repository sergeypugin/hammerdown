from __future__ import annotations

import logging
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from hammerdown import __version__

logger = logging.getLogger("hammerdown")


def _clean_pip_temp() -> None:
    if os.name == "nt":
        temp_dir = Path(tempfile.gettempdir())
        for p in temp_dir.glob("pip-uninstall-*"):
            try:
                shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass


def update(install_callback: Callable[[], bool] | None = None) -> bool:
    if install_callback is None:
        from hammerdown.integrations import install as install_callback

    if not getattr(sys, "frozen", False):
        logger.info("Updating Python package via pip...")
        _clean_pip_temp()
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir", "hammerdown"]
        try:
            subprocess.check_call(cmd)
            _clean_pip_temp()
            install_callback()
            logger.info("Successfully updated hammerdown package.")
            return True
        except subprocess.CalledProcessError:
            cmd_git = [sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir", "git+https://github.com/sergeypugin/hammerdown.git"]
            try:
                subprocess.check_call(cmd_git)
                _clean_pip_temp()
                install_callback()
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
        install_callback()
        return True
    except Exception as exc:
        logger.error("Failed to update: %s", exc)
        return False
