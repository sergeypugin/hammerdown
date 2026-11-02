from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from hammerdown.core.google_drive import (
    MAX_GOOGLE_DOWNLOAD_BYTES,
    download_google_url,
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


def _google_url() -> str:
    return "https://docs.google.com/document/d/ABC123/edit"


def test_rejects_content_length_before_reading(tmp_path: Path) -> None:
    response = FakeResponse([], {"Content-Length": str(MAX_GOOGLE_DOWNLOAD_BYTES + 1)})

    with (
        patch("hammerdown.core.google_drive.fetch_google_title", return_value="Document"),
        patch("hammerdown.core.google_drive.urllib.request.urlopen", return_value=response),
        pytest.raises(ValueError, match="download exceeds"),
    ):
        download_google_url(_google_url(), tmp_path)

    assert response.read_calls == 0
    assert list(tmp_path.iterdir()) == []


def test_rejects_stream_after_limit_and_cleans_partial_file(tmp_path: Path) -> None:
    response = FakeResponse(
        [b"a" * MAX_GOOGLE_DOWNLOAD_BYTES, b"b"],
        {"Content-Length": str(MAX_GOOGLE_DOWNLOAD_BYTES)},
    )

    with (
        patch("hammerdown.core.google_drive.fetch_google_title", return_value="Document"),
        patch("hammerdown.core.google_drive.urllib.request.urlopen", return_value=response),
        pytest.raises(ValueError, match="download exceeds"),
    ):
        download_google_url(_google_url(), tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_streams_download_and_preserves_title_and_type(tmp_path: Path) -> None:
    response = FakeResponse([b"hello ", b"world"], {"Content-Length": "11"})

    with (
        patch("hammerdown.core.google_drive.fetch_google_title", return_value="My Document"),
        patch("hammerdown.core.google_drive.urllib.request.urlopen", return_value=response),
    ):
        result = download_google_url(_google_url(), tmp_path)

    assert result is not None
    assert result == tmp_path / "My Document.gdoc"
    assert result.read_bytes() == b"hello world"
    assert response.read_calls == 3


def test_http_errors_are_propagated(tmp_path: Path) -> None:
    from email.message import Message
    from urllib.error import HTTPError

    error = HTTPError("https://docs.google.com/export", 403, "Forbidden", Message(), None)
    with (
        patch("hammerdown.core.google_drive.fetch_google_title", return_value="Document"),
        patch("hammerdown.core.google_drive.urllib.request.urlopen", side_effect=error),
        pytest.raises(HTTPError) as raised,
    ):
        download_google_url(_google_url(), tmp_path)

    assert raised.value is error
    assert list(tmp_path.iterdir()) == []

