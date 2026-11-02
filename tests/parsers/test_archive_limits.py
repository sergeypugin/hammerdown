from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

import hammerdown.parsers.archive as archive


def _write_zip(path: Path, members: list[tuple[str, bytes]]) -> None:
    with zipfile.ZipFile(path, "w") as zip_ref:
        for name, content in members:
            zip_ref.writestr(name, content)


@pytest.mark.parametrize("member_name", ["../outside.html", "nested/../../outside.html", r"..\\outside.html", r"C:\\outside.html", "/outside.html"])
def test_convert_zip_rejects_unsafe_member_paths(
    tmp_path: Path,
    member_name: str,
) -> None:
    archive_path = tmp_path / "unsafe.zip"
    asset_dir = tmp_path / "assets"
    _write_zip(archive_path, [(member_name, b"<p>unsafe</p>")])

    result = archive.convert_zip(archive_path, asset_dir)

    assert result == (None, 0)
    assert not asset_dir.exists()


def test_convert_zip_rejects_too_many_members(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archive, "MAX_ZIP_MEMBERS", 2)
    archive_path = tmp_path / "many.zip"
    asset_dir = tmp_path / "assets"
    _write_zip(archive_path, [(f"file-{index}.txt", b"x") for index in range(3)])

    result = archive.convert_zip(archive_path, asset_dir)

    assert result == (None, 0)
    assert not asset_dir.exists()


def test_convert_zip_rejects_cumulative_uncompressed_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(archive, "MAX_ZIP_UNCOMPRESSED_SIZE", 5)
    archive_path = tmp_path / "large.zip"
    asset_dir = tmp_path / "assets"
    _write_zip(archive_path, [("one.html", b"123"), ("two.txt", b"456")])

    result = archive.convert_zip(archive_path, asset_dir)

    assert result == (None, 0)
    assert not asset_dir.exists()


def test_convert_zip_preserves_html_and_asset_conversion(tmp_path: Path) -> None:
    archive_path = tmp_path / "valid.zip"
    asset_dir = tmp_path / "assets"
    html = b'<html><body><h1>Title</h1><img src="images/picture.png" alt="Picture"></body></html>'
    _write_zip(
        archive_path,
        [
            ("nested/index.html", html),
            ("nested/images/picture.png", b"png data"),
        ],
    )

    markdown, saved_images = archive.convert_zip(archive_path, asset_dir)

    assert markdown is not None
    assert "# Title" in markdown
    assert "![Picture]" in markdown
    assert saved_images == 1
    image_dir = asset_dir / archive.get_images_dir_name(archive_path)
    assert list(image_dir.glob("img_*.png"))
