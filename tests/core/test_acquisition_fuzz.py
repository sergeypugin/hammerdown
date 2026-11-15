from __future__ import annotations

import random
import re
from io import BytesIO
from pathlib import Path

import pytest

from hammerdown.core.google_drive import (
    build_export_url,
    extract_file_id,
    fetch_google_title,
    get_google_file_info,
    is_google_drive_url,
    sanitize_filename,
)
from hammerdown.core.github import (
    GitHubLocator,
    _download_archive,
    _resolve_commit,
    _validate_url,
    acquire_github,
)

DOC_TYPES = ["document", "spreadsheets", "presentation"]
IDS = ["abc123", "A" * 44, "a-b_c.d", "%", "..", "\x00", "a\tb", "", "id with spaces", "éè"]
HOSTS = [
    "docs.google.com",
    "drive.google.com",
    "drive.google.com/a/example.com",
    "docs.google.com.evil.com",
    "https://docs.google.com",
    "drive.google.com",
    "localhost",
    "127.0.0.1",
    "[::1]",
    "",
    "d o c s . g o o g l e . c o m",
]
PATH_BITS = ["/d/{id}/edit", "/d/{id}/view", "/d/{id}/export?format=html", "/d/{id}/", "/folders/{id}", "/drive/folders/{id}", "/uc?export=download&id={id}", ""]
QUERY_BITS = ["", "?usp=sharing", "?foo=bar&id={id}", "?id={id}#frag", "#gid=0", "&"]
FRAGMENT_BITS = ["", "#heading=h.xyz", "#frag?more", "#"]


def _make_url(rng: random.Random) -> str:
    host = rng.choice(HOSTS)
    path_template = rng.choice(PATH_BITS)
    query = rng.choice(QUERY_BITS)
    fragment = rng.choice(FRAGMENT_BITS)
    file_id = rng.choice(IDS)
    path = path_template.format(id=file_id)
    return f"https://{host}{path}{query}{fragment}"


def test_google_url_parsers_fuzz_never_raise() -> None:
    rng = random.Random(111)
    for _ in range(3000):
        value = _make_url(rng)
        try:
            is_google_drive_url(value)
            get_google_file_info(value)
            extract_file_id(value)
            build_export_url(value, rng.choice(IDS) if rng.random() < 0.7 else "")
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"google url parser raised {exc!r} for {value!r}")


def test_google_url_parsers_invariants() -> None:
    expected_types = {"document": "gdoc", "spreadsheets": "gsheets", "presentation": "gslides"}
    for dtype, doc_type in expected_types.items():
        info = get_google_file_info(f"https://docs.google.com/{dtype}/d/abc123/edit")
        assert info is not None
        assert info.file_id == "abc123"
        assert info.doc_type == doc_type
    info = get_google_file_info("https://drive.google.com/file/d/abc123/view")
    assert info is not None
    assert info.file_id == "abc123"
    assert info.doc_type == "gfile"
    # folders and view pages return no file id
    assert extract_file_id("https://drive.google.com/drive/folders/abc123") is None
    assert extract_file_id("https://drive.google.com/drive/u/0/folders/abc123") is None
    assert get_google_file_info("https://drive.google.com/drive/folders/abc123") is None
    fragment_info = get_google_file_info("https://docs.google.com/document/d/abc123/edit#heading=h.xyz")
    assert fragment_info is not None and fragment_info.file_id == "abc123"


def test_sanitize_filename_fuzz() -> None:
    rng = random.Random(222)
    pool = ['<>:"/\\|?*', "\x00\x01\x02", "CON", "PRN", "CON ", " CON", " . ", "...", "", " " * 10, "a" * 300, "тест", "rép"]
    extensions = ["gdoc", "gsheets", "gslides", "gfile"]
    for _ in range(1500):
        name = "".join(rng.choice(pool) for _ in range(rng.randint(0, 8)))
        try:
            result = sanitize_filename(name)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"sanitize_filename({name!r}) raised {exc!r}")
        assert "<" not in result and ">" not in result and ":" not in result
        assert '"' not in result and "/" not in result and "\\" not in result
        assert "|" not in result and "?" not in result and "*" not in result
        # download_google_url always appends ".{doc_type}", so the final name must be valid
        filename = f"{result}.{rng.choice(extensions)}"
        assert not filename.endswith((".", " "))


def test_fetch_google_title_fuzz_mocks(monkeypatch) -> None:
    import html

    rng = random.Random(333)
    titles = [
        "My Report - Google Docs",
        "My Таблицы - Google Таблицы",
        "Моя Präsentation - Google Презентации",
        "Untitled spreadsheet - Google Sheets",
        "My Slides - Google Slides",
        'My "quoted" doc - Google Drive',
        "<script>alert(1)</script>",
        "",
    ]
    templates = [
        '<meta property="og:title" content="{t}">',
        '<meta content="{t}" property="og:title">',
        "<title>{t}</title>",
        "<!doctype html><title>{t}</title>",
        "",
        "no title here",
    ]

    class FakeResponse(BytesIO):
        def __init__(self, payload: bytes):
            super().__init__(payload)
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def geturl(self):
            return "https://docs.google.com/document/d/abc123/edit"

    def fake_urlopen(request, timeout=10):
        if rng.random() < 0.15:
            raise OSError("simulated network failure")
        return FakeResponse(body.encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    for _ in range(800):
        title = rng.choice(titles)
        body = rng.choice(templates).format(t=html.escape(title, quote=True))
        try:
            result = fetch_google_title("https://docs.google.com/document/d/abc123/edit")
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"fetch_google_title raised {exc!r}")
        if result is not None:
            assert isinstance(result, str)
            assert result == result.strip()


def test_validate_url_fuzz_never_raises() -> None:
    rng = random.Random(444)
    pool = HOSTS + PATH_BITS + IDS + QUERY_BITS + FRAGMENT_BITS
    for _ in range(1500):
        value = "".join(rng.choice(pool) for _ in range(rng.randint(0, 10)))
        try:
            _validate_url(value)
        except ValueError:
            pass
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"_validate_url({value!r}) raised {exc!r}")


def test_validate_url_invariants() -> None:
    # Only github hosts survive; anything else is rejected with ValueError.
    _validate_url("https://github.com/owner/repo")
    _validate_url("https://api.github.com/repos/o/r/commits/main")
    for bad in [
        "https://evil.com/",
        "http://github.com/o/r",
        "https://github.com:8080/o/r",
        "https://user:pass@github.com/o/r",
        "https://github.com.evil.com/o/r",
    ]:
        with pytest.raises(ValueError):
            _validate_url(bad)


class _FakeCommitResponse(BytesIO):
    def __init__(self, payload: bytes, url: str, *, fail: bool = False):
        super().__init__(payload)
        self.headers = {}
        self._url = url
        self._fail = fail

    def __enter__(self):
        if self._fail:
            raise OSError("simulated commit fetch failure")
        return self

    def __exit__(self, *args) -> None:
        return None

    def geturl(self):
        return self._url


def test_resolve_commit_fuzz_never_raises(monkeypatch, tmp_path: Path) -> None:
    rng = random.Random(555)

    def fake_open(url, deadline):
        return _FakeCommitResponse(
            b'{"sha":"abc123"}',
            url,
            fail=rng.random() < 0.2,
        )

    monkeypatch.setattr("hammerdown.core.github._open", fake_open)
    for _ in range(200):
        locator = GitHubLocator(
            owner=rng.choice(["owner", "own er", "x" * 200, ""]),
            repository=rng.choice(["repo", "repo.git", ""]),
            ref=rng.choice(["main", "master", "v1.0", ""]),
            subpath=rng.choice(["docs", "", "docs/../.."]),
        )
        try:
            sha = _resolve_commit(locator, deadline=10.0)
        except Exception:
            continue
        assert isinstance(sha, str) and sha


class _FakeArchiveResponse(BytesIO):
    def __init__(self, payload: bytes, url: str, *, fail: bool = False):
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload))}
        self._url = url
        self._fail = fail

    def __enter__(self):
        if self._fail:
            raise OSError("simulated archive fetch failure")
        return self

    def __exit__(self, *args) -> None:
        return None

    def geturl(self):
        return self._url


def test_download_archive_fuzz_never_raises(monkeypatch, tmp_path: Path) -> None:
    rng = random.Random(666)
    archive_bytes = BytesIO(b"not a zip")

    def fake_open(url, deadline):
        return _FakeArchiveResponse(
            archive_bytes.getvalue(),
            url,
            fail=rng.random() < 0.2,
        )

    monkeypatch.setattr("hammerdown.core.github._open", fake_open)
    destination = tmp_path / "stage"
    destination.mkdir(parents=True)
    hosts = ["o/r", "own er/repo", ""]
    refs = ["main", "", "x" * 40]
    for _ in range(200):
        slug = rng.choice(hosts)
        ref = rng.choice(refs)
        url = f"https://codeload.github.com/{slug}/zip/{ref}"
        try:
            _download_archive(url, destination, deadline=10.0)
        except Exception:
            continue


def test_acquire_github_fuzz_network_failures(monkeypatch, tmp_path: Path) -> None:
    rng = random.Random(777)

    def fake_open(url, deadline):
        if "/commits/" in url:
            return _FakeCommitResponse(b'{"sha":"abc123"}', url)
        if rng.random() < 0.3:
            raise OSError("simulated archive failure")
        return _FakeArchiveResponse(BytesIO(b"not a zip").getvalue(), url)

    monkeypatch.setattr("hammerdown.core.github._open", fake_open)
    for _ in range(150):
        try:
            acquired = acquire_github(
                f"https://github.com/{rng.choice(['o/r', 'own er/repo'])}/tree/main/docs",
                tmp_path / "stage",
            )
        except Exception:
            continue
        assert acquired.resolved_commit == "abc123"
