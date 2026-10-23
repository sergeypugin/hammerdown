from pathlib import Path

import pytest
from hammerdown.google_drive import (
    extract_file_id,
    is_google_drive_url,
    build_export_url,
)


def test_parses_document_url():
    url = "https://docs.google.com/document/d/11ccQ3H0NNVfMtdiKW1Zxq0woOfk9o-2p0VcKhj4Bz_A/edit?tab=t.0#heading=h.9mwlljg4j1r9"
    assert is_google_drive_url(url)
    file_id = extract_file_id(url)
    assert file_id == "11ccQ3H0NNVfMtdiKW1Zxq0woOfk9o-2p0VcKhj4Bz_A"
    assert build_export_url(url, file_id) == (
        "https://docs.google.com/document/d/11ccQ3H0NNVfMtdiKW1Zxq0woOfk9o-2p0VcKhj4Bz_A/export?format=html"
    )


def test_parses_spreadsheet_url():
    url = "https://docs.google.com/spreadsheets/d/abcdEFG-1234/edit#gid=0"
    file_id = extract_file_id(url)
    assert file_id == "abcdEFG-1234"
    assert build_export_url(url, file_id) == (
        "https://docs.google.com/spreadsheets/d/abcdEFG-1234/export?format=html"
    )


def test_parses_presentation_url():
    url = "https://docs.google.com/presentation/d/xyz-rst-987/edit#slide=id.p"
    file_id = extract_file_id(url)
    assert file_id == "xyz-rst-987"
    assert build_export_url(url, file_id) == (
        "https://docs.google.com/presentation/d/xyz-rst-987/export?format=html"
    )


def test_parses_drive_file_url():
    url = "https://drive.google.com/file/d/ABC123/view?usp=sharing"
    file_id = extract_file_id(url)
    assert file_id == "ABC123"
    assert build_export_url(url, file_id) == (
        "https://drive.google.com/uc?export=download&id=ABC123"
    )


def test_rejects_folder_url():
    url = "https://drive.google.com/drive/folders/10tqaz0bVhVFP-MBV1izVWk0ypUDAd_Qb?usp=sharing"
    assert not is_google_drive_url(url)
    assert extract_file_id(url) is None
    assert build_export_url(url, "") is None


def test_rejects_non_drive_url():
    assert not is_google_drive_url("https://github.com/band-of-four/cheatsheets")
    assert extract_file_id("https://github.com/band-of-four/cheatsheets") is None


def test_rejects_u_folder_url():
    url = "https://drive.google.com/drive/u/0/folders/XYZ"
    assert extract_file_id(url) is None


def test_batch_writes_google_markdown_next_to_cwd(tmp_path: Path, monkeypatch):
    """Converting a Google Drive URL without -o must write the Markdown to the
    current directory, not into the temporary staging folder that is removed
    afterwards. This is a regression test for the disappearing output bug."""
    import argparse

    from hammerdown.batch import run_batch

    staging = tmp_path / "staging"
    staging.mkdir()
    downloaded = staging / "MyDocument.gdoc"
    downloaded.write_text("<html><body><h1>Source</h1></body></html>", encoding="utf-8")

    fake_download = lambda value, target_dir: downloaded
    monkeypatch.setattr("hammerdown.batch.download_google_url", fake_download)
    monkeypatch.chdir(tmp_path)

    args = argparse.Namespace(
        files=["https://docs.google.com/document/d/ABC123/edit"],
        merge=None,
        output_dir=None,
        overwrite=False,
        skip_existing=False,
        include=[],
        exclude=[],
        stdout=False,
        confirm=False,
        coordinator=False,
        right_click=False,
    )
    assert run_batch(args) == 0
    assert (tmp_path / "hm_MyDocument_gdoc.md").is_file()
