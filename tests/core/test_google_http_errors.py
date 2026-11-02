from __future__ import annotations

import argparse
from email.message import Message
from urllib.error import HTTPError, URLError

import pytest

import hammerdown.batch as batch


GOOGLE_URL = "https://docs.google.com/document/d/google-error/edit"


def _batch_args(url: str) -> argparse.Namespace:
    return argparse.Namespace(
        files=[url],
        include=[],
        exclude=[],
        overwrite=False,
        skip_existing=False,
        output_dir=None,
        merge=None,
        merge_auto=False,
        tree=False,
        all_formats=False,
        stdout=False,
        confirm=False,
        include_gitignored=False,
        coordinator=False,
        context_worker=False,
        right_click=False,
    )


def _http_error(status: int) -> HTTPError:
    return HTTPError(GOOGLE_URL, status, "response", Message(), None)


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (401, "access denied"),
        (403, "access denied"),
        (404, "not found"),
        (429, "rate limited"),
        (500, "server error"),
        (503, "server error"),
        (400, "HTTP error"),
        (418, "HTTP error"),
    ],
)
def test_google_http_errors_are_classified(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    status: int,
    category: str,
) -> None:
    monkeypatch.setattr(batch, "is_google_drive_url", lambda value: value == GOOGLE_URL)
    monkeypatch.setattr(batch, "download_google_url", lambda value, target_dir: (_ for _ in ()).throw(_http_error(status)))

    assert batch.run_batch(_batch_args(GOOGLE_URL)) == 1

    assert f"{category} (HTTP {status})" in caplog.text


@pytest.mark.parametrize("error", [URLError("offline"), ValueError("too large")])
def test_google_non_http_download_errors_keep_existing_reason(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
) -> None:
    monkeypatch.setattr(batch, "is_google_drive_url", lambda value: value == GOOGLE_URL)
    monkeypatch.setattr(batch, "download_google_url", lambda value, target_dir: (_ for _ in ()).throw(error))

    assert batch.run_batch(_batch_args(GOOGLE_URL)) == 1

    assert str(error) in caplog.text
    assert "access denied" not in caplog.text
    assert "not found" not in caplog.text
    assert "rate limited" not in caplog.text
    assert "server error" not in caplog.text

@pytest.mark.parametrize("status", [499, 600])
def test_google_http_error_boundaries_are_other_http_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    status: int,
) -> None:
    monkeypatch.setattr(batch, "is_google_drive_url", lambda value: value == GOOGLE_URL)
    monkeypatch.setattr(batch, "download_google_url", lambda value, target_dir: (_ for _ in ()).throw(_http_error(status)))

    assert batch.run_batch(_batch_args(GOOGLE_URL)) == 1

    assert f"HTTP error (HTTP {status})" in caplog.text
    assert "server error" not in caplog.text
