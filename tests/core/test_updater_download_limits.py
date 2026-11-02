from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

from hammerdown.core.updater import (
    MAX_BINARY_BYTES,
    MAX_CHECKSUM_BYTES,
    MAX_RELEASE_METADATA_BYTES,
    _fetch_checksum,
    _update_binary,
)


class FakeResponse:
    def __init__(self, chunks: list[bytes], headers: dict[str, str] | None = None) -> None:
        self._chunks = iter(chunks)
        self.headers = headers or {}
        self.read_calls = 0

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def read(self, _size: int = -1) -> bytes:
        self.read_calls += 1
        return next(self._chunks, b"")


def test_checksum_sidecar_rejects_oversized_content_length() -> None:
    response = FakeResponse([], {"Content-Length": str(MAX_CHECKSUM_BYTES + 1)})
    assets: list[dict[str, object]] = [{
        "name": "SHA256SUMS.txt",
        "browser_download_url": "https://example.test/checksums",
    }]

    with patch("hammerdown.core.updater.urllib.request.urlopen", return_value=response):
        assert _fetch_checksum(assets, "hammerdown-linux-x64") is None

    assert response.read_calls == 0


def test_checksum_sidecar_rejects_oversized_stream() -> None:
    response = FakeResponse([b"a" * MAX_CHECKSUM_BYTES, b"b"])
    assets: list[dict[str, object]] = [{
        "name": "SHA256SUMS.txt",
        "browser_download_url": "https://example.test/checksums",
    }]

    with patch("hammerdown.core.updater.urllib.request.urlopen", return_value=response):
        assert _fetch_checksum(assets, "hammerdown-linux-x64") is None


def test_release_metadata_rejects_oversized_content_length_before_install() -> None:
    response = FakeResponse([], {"Content-Length": str(MAX_RELEASE_METADATA_BYTES + 1)})

    with (
        patch("hammerdown.core.updater.urllib.request.urlopen", return_value=response),
        patch("hammerdown.core.updater._fetch_checksum") as fetch_checksum,
        patch("hammerdown.core.updater._install_binary") as install,
        patch("hammerdown.core.updater.is_windows", return_value=False),
        patch("hammerdown.core.updater.is_macos", return_value=False),
    ):
        assert _update_binary(lambda: True) is False

    fetch_checksum.assert_not_called()
    install.assert_not_called()
def _release(asset: dict[str, object]) -> FakeResponse:
    return FakeResponse(
        [
            json.dumps(
                {
                    "tag_name": "99.0.0",
                    "assets": [asset],
                }
            ).encode()
        ]
    )


def _binary_asset() -> dict[str, object]:
    return {
        "name": "hammerdown-linux-x64",
        "browser_download_url": "https://example.test/hammerdown",
        "digest": "sha256:" + ("0" * 64),
    }


def test_binary_rejects_oversized_content_length_before_install() -> None:
    binary = FakeResponse([], {"Content-Length": str(MAX_BINARY_BYTES + 1)})
    asset = _binary_asset()

    with (
        patch("hammerdown.core.updater.urllib.request.urlopen", side_effect=[_release(asset), binary]),
        patch("hammerdown.core.updater._fetch_checksum", return_value=None),
        patch("hammerdown.core.updater._install_binary") as install,
        patch("hammerdown.core.updater.is_windows", return_value=False),
        patch("hammerdown.core.updater.is_macos", return_value=False),
        patch("hammerdown.core.updater.__version__", "1.0.0"),
    ):
        assert _update_binary(lambda: True) is False

    install.assert_not_called()
    assert binary.read_calls == 0


def test_binary_rejects_oversized_stream_before_install() -> None:
    binary = FakeResponse([b"a" * MAX_BINARY_BYTES, b"b"])
    asset = _binary_asset()

    with (
        patch("hammerdown.core.updater.urllib.request.urlopen", side_effect=[_release(asset), binary]),
        patch("hammerdown.core.updater._fetch_checksum", return_value=None),
        patch("hammerdown.core.updater._install_binary") as install,
        patch("hammerdown.core.updater.is_windows", return_value=False),
        patch("hammerdown.core.updater.is_macos", return_value=False),
        patch("hammerdown.core.updater.__version__", "1.0.0"),
    ):
        assert _update_binary(lambda: True) is False

    install.assert_not_called()

