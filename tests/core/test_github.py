from __future__ import annotations

from io import BytesIO
from pathlib import Path
import zipfile

import pytest

from hammerdown.core import github


def test_parse_github_tree_locator() -> None:
    locator = github.parse_github_locator(
        "https://github.com/sergeypugin/ITMO/tree/90cbf25af0be883c34b7cac52c188c8fa5defcad/2_DB/rubezh"
    )
    assert locator is not None
    assert locator.owner == "sergeypugin"
    assert locator.repository == "ITMO"
    assert locator.ref == "90cbf25af0be883c34b7cac52c188c8fa5defcad"
    assert locator.subpath == "2_DB/rubezh"


@pytest.mark.parametrize(
    "value",
    [
        "http://github.com/a/b/tree/main",
        "https://github.com/a/b/tree/main/../secret",
        "https://github.com/a/b/tree/main/%2Fsecret",
        "https://user:pass@github.com/a/b/tree/main",
        "https://github.com:443/a/b/tree/main",
        "https://github.com/a/b/blob/main/file.txt",
        "https://github.com/a/b/tree/main?x=1",
        "https://github.com/a/b/tree/main/",
    ],
)
def test_parse_github_locator_rejects_noncanonical_urls(value: str) -> None:
    assert github.parse_github_locator(value) is None


def test_repository_root_requires_explicit_mode() -> None:
    value = "https://github.com/owner/repository"
    assert github.parse_github_locator(value) is None
    assert github.parse_github_locator(value, allow_repository_root=True) is not None


def _archive(path: Path, member: str = "owner-repository-sha/file.txt", data: bytes = b"ok") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, data)


def test_extract_archive_preserves_existing_destination_on_failure(tmp_path: Path) -> None:
    destination = tmp_path / "destination"
    destination.mkdir()
    keep = destination / "keep.txt"
    keep.write_text("keep", encoding="utf-8")
    archive = tmp_path / "bad.zip"
    _archive(archive, "../escape.txt")

    with pytest.raises(ValueError, match="unsafe path"):
        github._extract_archive(archive, destination)

    assert keep.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "escape.txt").exists()
    assert not (destination / ".github-extracted").exists()


def test_acquire_github_returns_commit_and_provenance(tmp_path: Path, monkeypatch) -> None:
    archive_bytes = BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("owner-repository-sha/docs/readme.txt", "hello")

    class Response(BytesIO):
        def __init__(self, payload: bytes, url: str):
            super().__init__(payload)
            self.headers = {}
            self._url = url

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

        def geturl(self):
            return self._url

    calls: list[str] = []

    def fake_open(url: str, deadline: float):
        calls.append(url)
        if "/commits/" in url:
            return Response(b'{"sha":"abc123"}', url)
        return Response(archive_bytes.getvalue(), url)

    monkeypatch.setattr(github, "_open", fake_open)
    acquired = github.acquire_github(
        "https://github.com/owner/repository/tree/main/docs",
        tmp_path / "stage",
    )

    assert acquired.root.joinpath("readme.txt").read_text(encoding="utf-8") == "hello"
    assert acquired.resolved_commit == "abc123"
    assert acquired.provenance["subpath"] == "docs"
    assert acquired.provenance["commit"] == "abc123"
    assert len(calls) == 2
