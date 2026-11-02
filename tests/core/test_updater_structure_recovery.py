from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from hammerdown.core.updater import _install_binary, _recover_windows_update, _update_binary


class FakeResponse:
    def __init__(self, value: object) -> None:
        self.value = value
        self.headers: dict[str, str] = {}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def read(self, _size: int = -1) -> bytes:
        if isinstance(self.value, bytes):
            return self.value
        return json.dumps(self.value).encode()


def test_malformed_release_metadata_returns_false_without_follow_up_work() -> None:
    malformed_releases = [
        None,
        [],
        {"tag_name": 99, "assets": []},
        {"tag_name": "not-a-version", "assets": []},
        {"tag_name": "99.0.0", "assets": {}},
        {"tag_name": "99.0.0", "assets": ["asset"]},
    ]

    for release in malformed_releases:
        with (
            patch("hammerdown.core.updater.urllib.request.urlopen", return_value=FakeResponse(release)),
            patch("hammerdown.core.updater._fetch_checksum") as fetch_checksum,
            patch("hammerdown.core.updater._install_binary") as install,
            patch("hammerdown.core.updater.is_windows", return_value=False),
            patch("hammerdown.core.updater.is_macos", return_value=False),
        ):
            assert _update_binary(lambda: True) is False

        fetch_checksum.assert_not_called()
        install.assert_not_called()




def test_windows_pending_update_restores_missing_target(tmp_path: Path) -> None:
    target = tmp_path / "hammerdown.exe"
    backup = tmp_path / "hammerdown.exe.old"
    marker = tmp_path / "hammerdown.exe.update"
    backup.write_bytes(b"old")
    marker.write_text("pending", encoding="ascii")

    with (
        patch.object(sys, "executable", str(target)),
        patch("hammerdown.core.updater.is_windows", return_value=True),
    ):
        assert _recover_windows_update() is True
        assert _recover_windows_update() is True

    assert target.read_bytes() == b"old"
    assert not backup.exists()
    assert not marker.exists()


def test_windows_pending_update_cleans_stale_marker_when_target_exists(tmp_path: Path) -> None:
    target = tmp_path / "hammerdown.exe"
    backup = tmp_path / "hammerdown.exe.old"
    marker = tmp_path / "hammerdown.exe.update"
    target.write_bytes(b"new")
    backup.write_bytes(b"old")
    marker.write_text("pending", encoding="ascii")

    with (
        patch.object(sys, "executable", str(target)),
        patch("hammerdown.core.updater.is_windows", return_value=True),
    ):
        assert _recover_windows_update() is True

    assert target.read_bytes() == b"new"
    assert not backup.exists()
    assert not marker.exists()


def test_windows_pending_update_recovery_failure_keeps_backup_and_marker(tmp_path: Path) -> None:
    target = tmp_path / "hammerdown.exe"
    backup = tmp_path / "hammerdown.exe.old"
    marker = tmp_path / "hammerdown.exe.update"
    backup.write_bytes(b"old")
    marker.write_text("pending", encoding="ascii")

    with (
        patch.object(sys, "executable", str(target)),
        patch("hammerdown.core.updater.is_windows", return_value=True),
        patch("hammerdown.core.updater.os.replace", side_effect=OSError("restore failed")),
    ):
        assert _recover_windows_update() is False

    assert not target.exists()
    assert backup.read_bytes() == b"old"
    assert marker.exists()


def test_windows_copy_failure_keeps_existing_executable(tmp_path: Path) -> None:
    target = tmp_path / "hammerdown.exe"
    download = tmp_path / "download.exe"
    target.write_bytes(b"old")
    download.write_bytes(b"new")

    with (
        patch.object(sys, "executable", str(target)),
        patch("hammerdown.core.updater.is_windows", return_value=True),
        patch("hammerdown.core.updater.shutil.copy2", side_effect=OSError("copy failed")),
    ):
        with pytest.raises(OSError):
            _install_binary(download)

    assert target.read_bytes() == b"old"
    assert not (tmp_path / "hammerdown.exe.old").exists()


def test_windows_helper_is_launched_after_staging(tmp_path: Path) -> None:
    target = tmp_path / "hammerdown.exe"
    download = tmp_path / "download.exe"
    target.write_bytes(b"old")
    download.write_bytes(b"new")

    with (
        patch.object(sys, "executable", str(target)),
        patch("hammerdown.core.updater.is_windows", return_value=True),
        patch("hammerdown.core.updater.subprocess.Popen") as popen,
    ):
        _install_binary(download)

    command = popen.call_args.args[0]
    assert command[0] == "powershell.exe"
    assert "-WindowStyle" in command
    assert "Hidden" in command
    assert str(target) in command
    assert str(target.parent / ".hammerdown.exe.new") in command
    assert str(os.getpid()) in command
    assert target.read_bytes() == b"old"
    assert (tmp_path / "hammerdown.exe.update").exists()
    assert (tmp_path / "hammerdown.exe.update.ps1").exists()
    popen.assert_called_once()


def test_windows_helper_launch_failure_keeps_target_and_cleans_pending_state(tmp_path: Path) -> None:
    target = tmp_path / "hammerdown.exe"
    download = tmp_path / "download.exe"
    target.write_bytes(b"old")
    download.write_bytes(b"new")

    with (
        patch.object(sys, "executable", str(target)),
        patch("hammerdown.core.updater.is_windows", return_value=True),
        patch("hammerdown.core.updater.subprocess.Popen", side_effect=OSError("launch failed")),
    ):
        with pytest.raises(OSError):
            _install_binary(download)

    assert target.read_bytes() == b"old"
    assert not (tmp_path / ".hammerdown.exe.new").exists()
    assert not (tmp_path / "hammerdown.exe.update").exists()
    assert not (tmp_path / "hammerdown.exe.update.ps1").exists()
