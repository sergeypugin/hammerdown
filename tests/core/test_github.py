from __future__ import annotations

from email.message import Message
from io import BytesIO
from pathlib import Path
import urllib.error
import zipfile

import pytest

from hammerdown.core import github


def _http_error(url: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "Error", Message(), None)


def _assert_unsupported(value: str) -> None:
    reason = github.github_url_rejection_reason(value)
    assert reason is not None and "unsupported GitHub URL" in reason


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
        "https://github.com/a/b/commits/main",
        "https://raw.githubusercontent.com/a/b/main/file.txt",
        "https://github.com/a/b/blob/main",
        "https://github.com/a/b",
    ],
)
def test_parse_github_locator_rejects_noncanonical_urls(value: str) -> None:
    assert github.parse_github_locator(value) is None


@pytest.mark.parametrize(
    "value,ref,subpath,kind",
    [
        ("https://github.com/a/b/tree/main#section", "main", "", "tree"),
        ("https://github.com/a/b/tree/main/docs#L42", "main", "docs", "tree"),
        ("https://github.com/a/b/tree/main?x=1&y=2", "main", "", "tree"),
        ("https://github.com/a/b/tree/main/", "main", "", "tree"),
        ("https://github.com/a/b/tree/main/docs/", "main", "docs", "tree"),
        ("https://github.com/a/b/blob/main/docs/readme.md", "main", "docs/readme.md", "blob"),
        ("https://github.com/a/b/blob/main/docs/readme.md#L12-anchor", "main", "docs/readme.md", "blob"),
        ("https://github.com/a/b/blob/main/file.txt/", "main", "file.txt", "blob"),
        ("https://www.github.com/a/b/tree/main", "main", "", "tree"),
    ],
)
def test_parse_github_locator_accepts_browser_forms(value: str, ref: str, subpath: str, kind: str) -> None:
    locator = github.parse_github_locator(value)
    assert locator is not None, value
    assert locator.ref == ref
    assert locator.subpath == subpath
    assert locator.kind == kind


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
        if "/commits/main%2Fdocs" in url:
            raise _http_error(url, 404)
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
    assert acquired.locator.ref == "main"
    assert acquired.locator.subpath == "docs"
    assert acquired.provenance["subpath"] == "docs"
    assert acquired.provenance["commit"] == "abc123"
    assert ["/commits/main%2Fdocs" in call for call in calls] == [True, False, False]


class _FakeResponse(BytesIO):
    def __init__(self, url: str, payload: bytes):
        super().__init__(payload)
        self.headers = {}
        self._url = url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def geturl(self):
        return self._url


def _zip_with(files: dict[str, str]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _fake_open_for(resolved_refs: set[str], archive: bytes):
    def fake_open(url: str, deadline: float):
        if "/commits/" in url:
            ref = url.rsplit("/commits/", 1)[1]
            if ref not in resolved_refs:
                raise _http_error(url, 404)
            return _FakeResponse(url, b'{"sha":"sha123"}')
        return _FakeResponse(url, archive)

    return fake_open


def test_acquire_github_blob_returns_file(tmp_path: Path, monkeypatch) -> None:
    archive = _zip_with({"owner-repository-sha/docs/readme.md": "# hello"})
    monkeypatch.setattr(github, "_open", _fake_open_for({"main"}, archive))
    acquired = github.acquire_github(
        "https://github.com/owner/repository/blob/main/docs/readme.md",
        tmp_path / "stage",
    )

    assert acquired.root.is_file()
    assert acquired.root.read_text(encoding="utf-8") == "# hello"
    assert acquired.locator.kind == "blob"
    assert "/blob/main/docs/readme.md" in acquired.provenance["locator"]


def test_acquire_github_blob_rejects_directory(tmp_path: Path, monkeypatch) -> None:
    archive = _zip_with({"owner-repository-sha/docs/readme.md": "# hello"})
    monkeypatch.setattr(github, "_open", _fake_open_for({"main"}, archive))
    with pytest.raises(ValueError, match="is a directory"):
        github.acquire_github(
            "https://github.com/owner/repository/blob/main/docs",
            tmp_path / "stage",
        )
    assert not (tmp_path / "stage" / ".github-extracted").exists()


def test_acquire_github_blob_rejects_missing_file(tmp_path: Path, monkeypatch) -> None:
    archive = _zip_with({"owner-repository-sha/docs/readme.md": "# hello"})
    monkeypatch.setattr(github, "_open", _fake_open_for({"main"}, archive))
    with pytest.raises(ValueError, match="does not exist"):
        github.acquire_github(
            "https://github.com/owner/repository/blob/main/missing.txt",
            tmp_path / "stage",
        )


def test_acquire_github_resolves_slashed_branch(tmp_path: Path, monkeypatch) -> None:
    archive = _zip_with({"owner-repository-sha/1.0/doc.md": "text"})
    monkeypatch.setattr(github, "_open", _fake_open_for({"release"}, archive))
    acquired = github.acquire_github(
        "https://github.com/owner/repository/tree/release/1.0",
        tmp_path / "stage",
    )

    assert acquired.locator.ref == "release"
    assert acquired.locator.subpath == "1.0"
    assert acquired.resolved_commit == "sha123"


def test_acquire_github_prefers_longest_ref_match(tmp_path: Path, monkeypatch) -> None:
    archive = _zip_with({"owner-repository-sha/file.txt": "text"})

    def fake_open(url: str, deadline: float):
        if url.endswith("/commits/release%2F1.0%2Ffile.txt"):
            raise _http_error(url, 404)
        if url.endswith("/commits/release%2F1.0"):
            return _FakeResponse(url, b'{"sha":"sha789"}')
        if "/commits/" in url:
            raise _http_error(url, 404)
        return _FakeResponse(url, archive)

    monkeypatch.setattr(github, "_open", fake_open)
    acquired = github.acquire_github(
        "https://github.com/owner/repository/tree/release/1.0/file.txt",
        tmp_path / "stage",
    )

    assert acquired.locator.ref == "release/1.0"
    assert acquired.locator.subpath == "file.txt"
    assert acquired.resolved_commit == "sha789"


def test_acquire_github_sha_permalink_skips_ref_walk(tmp_path: Path, monkeypatch) -> None:
    sha = "90cbf25af0be883c34b7cac52c188c8fa5defcad"
    archive = _zip_with({f"repository-{sha}/docs/guide.md": "guide"})
    calls: list[str] = []

    def fake_open(url: str, deadline: float):
        calls.append(url)
        if "/commits/" in url:
            return _FakeResponse(url, b'{"sha":"sha123"}')
        return _FakeResponse(url, archive)

    monkeypatch.setattr(github, "_open", fake_open)
    acquired = github.acquire_github(
        f"https://github.com/owner/repository/tree/{sha}/docs",
        tmp_path / "stage",
    )

    assert acquired.locator.ref == sha
    assert acquired.locator.subpath == "docs"
    assert len(calls) == 2
    assert calls[0].endswith(f"/commits/{sha}")


def test_resolve_commit_reports_missing_ref(monkeypatch) -> None:
    def fake_open(url: str, deadline: float):
        raise _http_error(url, 404)

    monkeypatch.setattr(github, "_open", fake_open)
    locator = github.parse_github_locator("https://github.com/owner/repository/tree/release/1.0")
    assert locator is not None
    with pytest.raises(ValueError, match="ref does not exist: release/1.0"):
        github._resolve_commit(locator, deadline=10.0)


def test_resolve_commit_propagates_rate_limit(monkeypatch) -> None:
    def fake_open(url: str, deadline: float):
        raise _http_error(url, 403)

    monkeypatch.setattr(github, "_open", fake_open)
    locator = github.parse_github_locator("https://github.com/owner/repository/tree/main/docs")
    assert locator is not None
    with pytest.raises(urllib.error.HTTPError):
        github._resolve_commit(locator, deadline=10.0)


def test_github_url_rejection_reason_forms() -> None:
    assert github.github_url_rejection_reason("https://github.com/owner/repo") == "GitHub repository root link requires tree mode"
    assert github.github_url_rejection_reason("https://github.com/owner/repo", allow_repository_root=True) is None
    _assert_unsupported("https://github.com/owner/repo/issues/1")
    _assert_unsupported("https://raw.githubusercontent.com/a/b/main/f.txt")
    _assert_unsupported("github.com/owner/repo/tree/main")
    _assert_unsupported("http://github.com/a/b/tree/main")
    assert github.github_url_rejection_reason("notes/readme.md") is None
    assert github.github_url_rejection_reason("owner/repo") is None
    assert github.github_url_rejection_reason("C:\\tmp\\file.txt") is None
