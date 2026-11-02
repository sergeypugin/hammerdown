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
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from .. import __version__
from .platform_utils import is_macos, is_windows

logger = logging.getLogger("hammerdown")

PACKAGE_NAME = "hammerdown"
RELEASES_API = f"https://api.github.com/repos/sergeypugin/{PACKAGE_NAME}/releases/latest"
GIT_PACKAGE = f"git+https://github.com/sergeypugin/{PACKAGE_NAME}.git"
MAX_RELEASE_METADATA_BYTES = 1 * 1024 * 1024
MAX_CHECKSUM_BYTES = 1 * 1024 * 1024
MAX_BINARY_BYTES = 256 * 1024 * 1024
_DOWNLOAD_CHUNK_BYTES = 64 * 1024
_WINDOWS_UPDATE_SCRIPT = """param(
    [int]$ParentPid,
    [string]$Target,
    [string]$Staged,
    [string]$Backup,
    [string]$Marker
)

try {
    while (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) {
        Start-Sleep -Milliseconds 100
    }

    if (Test-Path -LiteralPath $Target) {
        [System.IO.File]::Replace($Staged, $Target, $Backup, $true)
    } else {
        [System.IO.File]::Move($Staged, $Target)
    }

    Remove-Item -LiteralPath $Marker -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $Backup -Force -ErrorAction SilentlyContinue
    exit 0
} catch {
    if (-not (Test-Path -LiteralPath $Target) -and (Test-Path -LiteralPath $Backup)) {
        try {
            [System.IO.File]::Move($Backup, $Target)
        } catch {}
    }
    exit 1
} finally {
    Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
}
"""


MACHO_MAGIC = (
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xce",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
)


class _ReadableResponse(Protocol):
    headers: Mapping[str, str]

    def read(self, size: int) -> bytes: ...


def _content_length(response: _ReadableResponse) -> int | None:
    value = response.headers.get("Content-Length")
    if value is None:
        return None
    return int(value)


def _read_bounded(response: _ReadableResponse, limit: int) -> bytes:
    content_length = _content_length(response)
    if content_length is not None and content_length > limit:
        raise ValueError(f"response exceeds the {limit} byte limit")

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(_DOWNLOAD_CHUNK_BYTES)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise ValueError(f"response exceeds the {limit} byte limit")
        chunks.append(chunk)


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


def _validate_release_metadata(release: object) -> tuple[str, list[dict[str, object]]] | None:
    if not isinstance(release, Mapping):
        return None

    tag_name = release.get("tag_name")
    assets = release.get("assets")
    if not isinstance(tag_name, str) or not tag_name.strip() or not _version_tuple(tag_name):
        return None
    if not isinstance(assets, list) or any(not isinstance(asset, dict) for asset in assets):
        return None

    return tag_name, assets


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
    if isinstance(expected_sha256, str) and re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        if actual != expected_sha256.lower():
            raise RuntimeError("downloaded asset failed checksum verification")
        return

    digest = asset.get("digest")
    if isinstance(digest, str) and digest.startswith("sha256:"):
        asset_sha256 = digest.removeprefix("sha256:")
        if re.fullmatch(r"[0-9a-fA-F]{64}", asset_sha256) is not None:
            if actual != asset_sha256.lower():
                raise RuntimeError("downloaded asset failed checksum verification")
            return

    size = asset.get("size")
    if isinstance(size, int) and size != len(payload):
        raise RuntimeError(f"downloaded asset has unexpected size ({len(payload)} bytes, expected {size})")
    raise RuntimeError("downloaded asset has no valid SHA-256 checksum")


def _fetch_checksum(assets: list[dict[str, object]], asset_name: str) -> str | None:
    entry = next((item for item in assets if item.get("name") == "SHA256SUMS.txt"), None)
    url = entry.get("browser_download_url") if entry else None
    if not isinstance(url, str) or not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            listing = _read_bounded(response, MAX_CHECKSUM_BYTES).decode("utf-8", errors="replace")
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


def _durably_flush(path: Path) -> None:
    with path.open("rb+") as file:
        file.flush()
        os.fsync(file.fileno())


def _recover_windows_update() -> bool:
    if not is_windows():
        return True

    target = Path(sys.executable)
    marker = Path(f"{target}.update")
    if not marker.exists():
        return True

    staged = target.parent / f".{target.name}.new"
    backup = Path(f"{target}.old")
    if not target.exists():
        if not backup.exists():
            logger.error("Pending update has neither an executable nor a backup at %s", target)
            return False
        try:
            os.replace(backup, target)
        except OSError as exc:
            logger.error("Could not recover the previous executable: %s", exc)
            return False
        marker.unlink(missing_ok=True)
        staged.unlink(missing_ok=True)
        return True

    try:
        marker.unlink()
    except OSError as exc:
        logger.warning("Could not remove stale update marker: %s", exc)
    try:
        backup.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Could not remove stale executable backup: %s", exc)
    try:
        staged.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Could not remove stale staged executable: %s", exc)
    return True


def _windows_update_command(
    script: Path, target: Path, staged: Path, backup: Path, marker: Path
) -> list[str]:
    return [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle",
        "Hidden",
        "-File",
        str(script),
        str(os.getpid()),
        str(target),
        str(staged),
        str(backup),
        str(marker),
    ]


def _schedule_windows_update(download_path: Path, target: Path) -> None:
    staged = target.parent / f".{target.name}.new"
    backup = Path(f"{target}.old")
    marker = Path(f"{target}.update")
    script = Path(f"{target}.update.ps1")

    try:
        shutil.copy2(download_path, staged)
        _durably_flush(staged)
        script.write_text(_WINDOWS_UPDATE_SCRIPT, encoding="ascii")
        _durably_flush(script)
        marker.write_text("pending", encoding="ascii")
        _durably_flush(marker)

        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(
            _windows_update_command(script, target, staged, backup, marker),
            close_fds=True,
            creationflags=creation_flags,
        )
    except OSError:
        staged.unlink(missing_ok=True)
        script.unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
        raise
def _install_binary(download_path: Path) -> None:
    target = Path(sys.executable)
    if is_windows():
        _schedule_windows_update(download_path, target)
        return

    staged = target.parent / f".{target.name}.new"
    staged.chmod(staged.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    try:
        os.replace(staged, target)
    finally:
        staged.unlink(missing_ok=True)


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
    if not _recover_windows_update():
        return False

    asset_name = _asset_name()
    request = urllib.request.Request(RELEASES_API, headers={"User-Agent": PACKAGE_NAME})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            release = json.loads(_read_bounded(response, MAX_RELEASE_METADATA_BYTES).decode("utf-8"))
    except Exception as exc:
        logger.error("Failed to query the latest release: %s", exc)
        return False

    metadata = _validate_release_metadata(release)
    if metadata is None:
        logger.error("Latest release metadata is malformed")
        return False
    raw_tag, assets = metadata
    latest_tag = raw_tag.lstrip("vV")
    if not _is_newer(latest_tag, __version__):
        logger.info("hammerdown is already at the latest version (%s)", __version__)
        return True

    asset = next((item for item in assets if item.get("name") == asset_name), None)
    if asset is None:
        logger.error("No release asset found matching %s", asset_name)
        return False

    download_url = asset.get("browser_download_url")
    if not isinstance(download_url, str) or not download_url:
        logger.error("Release asset %s has no download URL", asset_name)
        return False

    logger.info("New version available: %s (current: %s)", latest_tag, __version__)
    logger.info("Downloading %s...", download_url)

    expected_sha256 = _fetch_checksum(assets, asset_name)

    temp_dir = Path(tempfile.mkdtemp(prefix="hammerdown-update-"))
    try:
        download_path = temp_dir / ("hammerdown.exe" if is_windows() else "hammerdown")
        try:
            with urllib.request.urlopen(download_url, timeout=60) as response:
                payload = _read_bounded(response, MAX_BINARY_BYTES)
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
