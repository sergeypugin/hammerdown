from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path

from hammerdown import __version__
from hammerdown.platform_utils import is_macos, is_windows

logger = logging.getLogger("hammerdown")

PACKAGE_NAME = "hammerdown"
RELEASES_API = f"https://api.github.com/repos/sergeypugin/{PACKAGE_NAME}/releases/latest"
GIT_PACKAGE = f"git+https://github.com/sergeypugin/{PACKAGE_NAME}.git"

MACHO_MAGIC = (
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xce",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
)


def _clean_pip_temp() -> None:
    if not is_windows():
        return
    temp_dir = Path(tempfile.gettempdir())
    for path in temp_dir.glob("pip-uninstall-*"):
        shutil.rmtree(path, ignore_errors=True)


def _version_tuple(value: str) -> tuple[int, ...]:
    head = value.strip().lstrip("vV").split("-", 1)[0].split("+", 1)[0]
    parts: list[int] = []
    for chunk in head.split("."):
        match = re.match(r"\d+", chunk)
        if match is None:
            break
        parts.append(int(match.group()))
    return tuple(parts)


def _is_newer(candidate: str, current: str) -> bool:
    candidate_parts = _version_tuple(candidate)
    if not candidate_parts:
        return False
    return candidate_parts > _version_tuple(current)


def _asset_name() -> str:
    if is_windows():
        return "hammerdown-windows-x64.exe"
    if is_macos():
        machine = platform.machine().lower()
        if "arm" in machine or "aarch64" in machine:
            return "hammerdown-macos-arm64"
        return "hammerdown-macos-x64"
    return "hammerdown-linux-x64"


def _verify_download(payload: bytes, asset: dict[str, object], expected_sha256: str | None = None) -> None:
    actual = hashlib.sha256(payload).hexdigest()
    if expected_sha256:
        if actual != expected_sha256:
            raise RuntimeError("downloaded asset failed checksum verification")
        return

    digest = asset.get("digest")
    if isinstance(digest, str) and digest.startswith("sha256:"):
        if actual != digest.split(":", 1)[1].lower():
            raise RuntimeError("downloaded asset failed checksum verification")
        return

    size = asset.get("size")
    if isinstance(size, int) and size != len(payload):
        raise RuntimeError(f"downloaded asset has unexpected size ({len(payload)} bytes, expected {size})")


def _fetch_checksum(assets: list[dict[str, object]], asset_name: str) -> str | None:
    entry = next((item for item in assets if item.get("name") == "SHA256SUMS.txt"), None)
    url = entry.get("browser_download_url") if entry else None
    if not isinstance(url, str) or not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            listing = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("Could not download release checksums: %s", exc)
        return None

    for line in listing.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[-1].lstrip("*").endswith(asset_name):
            return fields[0].lower()
    return None


def _verify_executable(payload: bytes) -> None:
    if is_windows():
        if not payload.startswith(b"MZ"):
            raise RuntimeError("downloaded asset is not a Windows executable")
    elif is_macos():
        if not payload.startswith(MACHO_MAGIC):
            raise RuntimeError("downloaded asset is not a macOS executable")
    elif not payload.startswith(b"\x7fELF"):
        raise RuntimeError("downloaded asset is not a Linux executable")


def _refresh_integration(install_callback: Callable[[], bool]) -> None:
    try:
        if not install_callback():
            logger.warning("The file-manager integration could not be refreshed; run --install manually")
    except Exception as exc:
        logger.warning("Refreshing the file-manager integration failed: %s", exc)


def _install_binary(download_path: Path) -> None:
    target = Path(sys.executable)
    if is_windows():
        backup = Path(f"{target}.old")
        backup.unlink(missing_ok=True)
        target.rename(backup)
        try:
            shutil.copy2(download_path, target)
        except OSError:
            try:
                shutil.move(str(backup), str(target))
            except OSError:
                logger.error("Rollback failed; the previous executable remains at %s", backup)
            raise
        return

    # Replacing the running executable in place fails with ETXTBSY, so stage the
    # new binary next to the target and swap it in with an atomic rename.
    staged = target.parent / f".{target.name}.new"
    shutil.copy2(download_path, staged)
    staged.chmod(staged.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(staged, target)


def _update_package(install_callback: Callable[[], bool]) -> bool:
    logger.info("Updating Python package via pip...")
    _clean_pip_temp()
    commands = [
        [sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir", PACKAGE_NAME],
        [sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir", GIT_PACKAGE],
    ]
    last_error: Exception | None = None
    for command in commands:
        try:
            subprocess.check_call(command)
        except subprocess.CalledProcessError as exc:
            last_error = exc
            continue
        _clean_pip_temp()
        _refresh_integration(install_callback)
        logger.info("Successfully updated hammerdown package.")
        return True
    logger.error("Failed to update via pip: %s", last_error)
    return False


def _update_binary(install_callback: Callable[[], bool]) -> bool:
    asset_name = _asset_name()
    request = urllib.request.Request(RELEASES_API, headers={"User-Agent": PACKAGE_NAME})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            release = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        logger.error("Failed to query the latest release: %s", exc)
        return False

    latest_tag = str(release.get("tag_name", "")).lstrip("vV")
    if not _is_newer(latest_tag, __version__):
        logger.info("hammerdown is already at the latest version (%s)", __version__)
        return True

    asset = next((item for item in release.get("assets", []) if item.get("name") == asset_name), None)
    if asset is None:
        logger.error("No release asset found matching %s", asset_name)
        return False

    download_url = asset.get("browser_download_url")
    if not isinstance(download_url, str) or not download_url:
        logger.error("Release asset %s has no download URL", asset_name)
        return False

    logger.info("New version available: %s (current: %s)", latest_tag, __version__)
    logger.info("Downloading %s...", download_url)

    expected_sha256 = _fetch_checksum(release.get("assets", []), asset_name)

    temp_dir = Path(tempfile.mkdtemp(prefix="hammerdown-update-"))
    try:
        download_path = temp_dir / ("hammerdown.exe" if is_windows() else "hammerdown")
        try:
            with urllib.request.urlopen(download_url, timeout=60) as response:
                payload = response.read()
            _verify_download(payload, asset, expected_sha256)
            _verify_executable(payload)
            download_path.write_bytes(payload)
        except Exception as exc:
            logger.error("Failed to download the update: %s", exc)
            return False

        try:
            _install_binary(download_path)
        except OSError as exc:
            logger.error("Failed to install the update: %s", exc)
            return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    _refresh_integration(install_callback)
    logger.info("hammerdown successfully updated to version %s!", latest_tag)
    return True


def update(install_callback: Callable[[], bool] | None = None) -> bool:
    if install_callback is None:
        from hammerdown.integrations import install as install_callback

    if getattr(sys, "frozen", False):
        return _update_binary(install_callback)
    return _update_package(install_callback)
