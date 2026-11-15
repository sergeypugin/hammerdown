from __future__ import annotations

import random
import shutil
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from hammerdown.core.acquisition import AcquisitionResult, acquire_inputs
from hammerdown.core.github import GitHubLocator, _extract_archive, _safe_member, parse_github_locator
from hammerdown.core.google_drive import is_google_drive_url

URL_SEGMENTS = [
    "tree", "blob", "main", "master", "refs", "heads", "..", ".", "%2e%2e",
    "a b", "a\tb", "repos", "%41", "%2541", "%", "%zz", "%2", "\x00", "",
    "owner", "repository", "docs", "x" * 300, "..\\", "\\", "?q=1", "#frag",
    "'", '"', ";", "@", ":", "тест", "rép",
]
SCHEMES = ["https", "http", "HTTPS", "ftp", "file", "", "https:"]
HOST_BITS = ["github.com", "GITHUB.COM", "api.github.com", "evil.com", "github.com.", ""]
AUTH_BITS = ["", "user:pass@", "user@", ":pass@"]
PORT_BITS = ["", ":443", ":0", ":8080", ":abc", ":99999"]
SUFFIX_BITS = ["", "?x=1", "#L1", "?a=b#c", "/"]
TERMINATORS = [ValueError, TimeoutError, OSError, RuntimeError, zipfile.BadZipFile]


def _random_url(rng: random.Random, *, depth: int | None = None) -> str:
    head = rng.choice(AUTH_BITS) + rng.choice(HOST_BITS) + rng.choice(PORT_BITS)
    if rng.random() < 0.9:
        head = rng.choice(SCHEMES) + "://" + head
    count = depth if depth is not None else rng.randint(0, 7)
    segments = [rng.choice(URL_SEGMENTS) for _ in range(count)]
    return "/".join([head, *segments]) + rng.choice(SUFFIX_BITS)


def _assert_safe_locator(locator: GitHubLocator) -> None:
    for field in (locator.owner, locator.repository, locator.ref or "", locator.subpath):
        assert "\x00" not in field
        assert "\\" not in field
    assert locator.owner not in {"", ".", ".."}
    assert locator.repository not in {"", ".", ".."}
    for segment in locator.subpath.split("/"):
        if segment:
            assert segment not in {".", ".."}
            assert not any(ord(char) < 32 or char.isspace() for char in segment)


def test_parse_github_locator_fuzz_never_raises() -> None:
    rng = random.Random(20261115)
    for _ in range(2000):
        value = _random_url(rng)
        try:
            locator = parse_github_locator(value, allow_repository_root=rng.random() < 0.5)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"parse_github_locator({value!r}) raised {exc!r}")
        if locator is not None:
            _assert_safe_locator(locator)


def test_parse_github_locator_shorthand_fuzz() -> None:
    rng = random.Random(42)
    for _ in range(500):
        parts = [rng.choice(URL_SEGMENTS), rng.choice(URL_SEGMENTS)]
        try:
            locator = parse_github_locator("/".join(parts), allow_repository_root=True)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"parse_github_locator({parts!r}) raised {exc!r}")
        if locator is not None:
            _assert_safe_locator(locator)


def test_parse_github_locator_accepts_canonical_forms() -> None:
    canonical = [
        ("https://github.com/owner/repo/tree/main", "main", ""),
        ("https://github.com/owner/repo/tree/main/sub/dir", "main", "sub/dir"),
        ("https://github.com/owner/repo/tree/v1.0.0", "v1.0.0", ""),
    ]
    for value, ref, subpath in canonical:
        locator = parse_github_locator(value)
        assert locator is not None, value
        assert locator.ref == ref
        assert locator.subpath == subpath
    root = parse_github_locator("https://github.com/owner/repo", allow_repository_root=True)
    assert root is not None
    assert root.ref is None and root.subpath == ""
    # an encoded slash is ambiguous with a subpath separator and must be rejected
    assert parse_github_locator("https://github.com/owner/repo/tree/feature%2Fx") is None


def _paths_under(root: Path) -> set[Path]:
    if not root.exists():
        return set()
    return {path.resolve() for path in root.rglob("*")}


def _fuzz_zip_bytes(rng: random.Random, count: int, *, benign: bool = False) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for index in range(count):
            if benign:
                name = f"root/file{index}.txt"
                info = zipfile.ZipInfo(name)
                info.external_attr = 0o644 << 16
                archive.writestr(info, f"payload {index}")
                continue
            name = rng.choice([
                f"root/file{index}.txt", "../evil.txt", "/abs.txt", "..\\evil.txt",
                "root/../../out.txt", "/".join(["deep"] * 20) + f"/f{index}.txt",
                "root/dup.txt", "root/sub/", "", "root/ space.txt",
            ])
            info = zipfile.ZipInfo(name)
            if rng.random() < 0.15:
                info.external_attr = 0o120777 << 16
                payload = b"../target.txt"
            else:
                info.external_attr = 0o644 << 16
                payload = f"payload {index}".encode()
            archive.writestr(info, payload)
    return buffer.getvalue()


def _archive_file(tmp_path: Path, data: bytes, name: str) -> Path:
    archive_path = tmp_path / name
    archive_path.write_bytes(data)
    return archive_path


def test_extract_archive_fuzz_hostile_names(tmp_path: Path) -> None:
    rng = random.Random(777)
    destination = tmp_path / "dest"
    escaped_all: set[Path] = set()
    for iteration in range(120):
        destination.mkdir(parents=True)
        before = _paths_under(tmp_path)
        archive = _archive_file(tmp_path, _fuzz_zip_bytes(rng, rng.randint(1, 12)), f"a{iteration}.zip")
        try:
            _extract_archive(archive, destination)
        except ValueError:
            pass
        new_paths = _paths_under(tmp_path) - before
        allowed_root = (destination / ".github-extracted").resolve()
        escaped = {
            path for path in new_paths
            if path != allowed_root and allowed_root not in path.parents
        }
        escaped_all |= escaped
        shutil.rmtree(destination, ignore_errors=True)
        archive.unlink()
    assert not escaped_all, f"archive escaped sandbox: {escaped_all}"


def test_extract_archive_fuzz_benign_success(tmp_path: Path) -> None:
    rng = random.Random(778)
    destination = tmp_path / "dest"
    escaped_all: set[Path] = set()
    for iteration in range(20):
        destination.mkdir(parents=True)
        before = _paths_under(tmp_path)
        archive = _archive_file(tmp_path, _fuzz_zip_bytes(rng, rng.randint(1, 8), benign=True), f"b{iteration}.zip")
        result_root = _extract_archive(archive, destination)
        after = _paths_under(tmp_path) - before
        allowed_root = (destination / ".github-extracted").resolve()
        escaped = {
            path for path in after
            if path != allowed_root and allowed_root not in path.parents
        }
        escaped_all |= escaped
        assert result_root.is_dir()
        shutil.rmtree(destination)
        archive.unlink()
    assert not escaped_all, f"archive escaped sandbox: {escaped_all}"


def test_extract_archive_rejects_symlink_member(tmp_path: Path) -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("root/link")
        info.external_attr = 0o120777 << 16
        archive.writestr(info, "../outside.txt")
        archive.writestr("root/keep.txt", "keep")
    archive = _archive_file(tmp_path, buffer.getvalue(), "symlink.zip")
    destination = tmp_path / "dest"
    destination.mkdir()
    with pytest.raises(ValueError, match="symlink"):
        _extract_archive(archive, destination)


def test_extract_archive_rejects_duplicate_entries(tmp_path: Path) -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for _ in range(2):
            info = zipfile.ZipInfo("root/dup.txt")
            info.external_attr = 0o644 << 16
            archive.writestr(info, "payload")
    archive = _archive_file(tmp_path, buffer.getvalue(), "dup.zip")
    destination = tmp_path / "dest"
    destination.mkdir()
    with pytest.raises(ValueError, match="conflicting"):
        _extract_archive(archive, destination)


def test_safe_member_fuzz_never_returns_unsafe_path() -> None:
    rng = random.Random(99)
    pool = URL_SEGMENTS + ["root/../../x", "/etc/passwd", "C:\\windows\\evil", "a/" * 40 + "b"]
    for _ in range(1000):
        if rng.random() < 0.7:
            name = rng.choice(pool)
        else:
            name = "/".join(rng.choice(pool) for _ in range(rng.randint(1, 5)))
        try:
            path = _safe_member(name)
        except ValueError:
            continue
        assert not path.is_absolute()
        assert ".." not in path.parts
        assert "" not in path.parts
        assert len(path.parts) <= 32


def test_acquire_inputs_fuzz_downloader_exceptions(tmp_path: Path) -> None:
    rng = random.Random(1234)
    local = tmp_path / "local.txt"
    local.write_text("local", encoding="utf-8")
    raw_inputs = [
        str(local), str(tmp_path / "missing.txt"), "",
        "https://github.com/o/r/tree/main/x", "owner/repo",
        "https://docs.google.com/document/d/id/edit", "not a path at all \x00",
    ]

    def raising_downloader(url: str, staging: Path):
        raise rng.choice(TERMINATORS)("simulated failure")

    def raising_acquirer(*args: object, **kwargs: object):
        raise rng.choice(TERMINATORS)("simulated failure")

    result = acquire_inputs(
        raw_inputs,
        tmp_path / "stage",
        google_downloader=raising_downloader,
        github_acquirer=raising_acquirer,
    )
    assert isinstance(result, AcquisitionResult)
    for item in result.inputs:
        if item.local_path is None:
            assert item.error
            assert isinstance(item.error, str)
    assert str(local) in result.local_paths


def test_acquire_inputs_propagates_keyboard_interrupt(tmp_path: Path) -> None:
    def interrupted(url: str, staging: Path):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        acquire_inputs(
            ["https://docs.google.com/document/d/id/edit"],
            tmp_path / "stage",
            google_downloader=interrupted,
        )


def test_is_google_drive_url_fuzz_never_raises() -> None:
    rng = random.Random(555)
    for _ in range(1500):
        value = _random_url(rng, depth=rng.randint(0, 9))
        try:
            is_google_drive_url(value)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"is_google_drive_url({value!r}) raised {exc!r}")
