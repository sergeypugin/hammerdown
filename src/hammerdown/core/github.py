from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import time
from urllib.parse import quote, unquote, urlparse
import urllib.request
import zipfile

MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_EXTRACTED_BYTES = 250 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 100_000
MAX_PATH_DEPTH = 32
DEFAULT_DEADLINE_SECONDS = 120.0
_ALLOWED_HOSTS = {"github.com", "api.github.com", "codeload.github.com"}
_USER_AGENT = "Hammerdown/4"


@dataclass(frozen=True)
class GitHubLocator:
    owner: str
    repository: str
    ref: str | None = None
    subpath: str = ""

    @property
    def repository_slug(self) -> str:
        return f"{self.owner}/{self.repository}"


@dataclass(frozen=True)
class GitHubAcquired:
    root: Path
    locator: GitHubLocator
    resolved_commit: str
    source_url: str

    @property
    def provenance(self) -> dict[str, str]:
        return {
            "locator": f"https://github.com/{self.locator.repository_slug}/tree/{self.locator.ref or self.resolved_commit}",
            "ref": self.locator.ref or self.resolved_commit,
            "commit": self.resolved_commit,
            "subpath": self.locator.subpath,
            "source_url": self.source_url,
        }


def _safe_component(value: str) -> bool:
    return bool(value) and value not in {".", ".."} and "\x00" not in value and "/" not in value and "\\" not in value and not any(ord(char) < 32 or char.isspace() for char in value)


def _decode_segments(path: str) -> list[str] | None:
    if not path or not path.startswith("/") or path.endswith("/"):
        return None
    encoded = path[1:].split("/")
    if any(not part for part in encoded):
        return None
    decoded = [unquote(part) for part in encoded]
    if any(not _safe_component(part) for part in decoded):
        return None
    return decoded


def parse_github_locator(value: str, *, allow_repository_root: bool = False) -> GitHubLocator | None:
    if "\x00" in value:
        return None
    if "://" not in value:
        parts = value.split("/")
        if len(parts) == 2 and all(_safe_component(part) for part in parts):
            return GitHubLocator(parts[0], parts[1]) if allow_repository_root else None
        return None
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username is not None or parsed.password is not None or port is not None or parsed.query or parsed.fragment:
        return None
    parts = _decode_segments(parsed.path)
    if parts is None:
        return None
    if len(parts) == 2 and allow_repository_root:
        return GitHubLocator(parts[0], parts[1])
    if len(parts) < 4 or parts[2] != "tree":
        return None
    if not all(_safe_component(part) for part in parts[:4]):
        return None
    return GitHubLocator(parts[0], parts[1], parts[3], "/".join(parts[4:]))


def _validate_url(url: str, *, final: bool = False) -> None:
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("GitHub URL has an invalid port") from exc
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS or parsed.username is not None or parsed.password is not None or port is not None:
        suffix = "final URL" if final else "request URL"
        raise ValueError(f"GitHub {suffix} leaves the allowed HTTPS hosts")


class _AllowedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str, deadline: float):
    _validate_url(url)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("GitHub acquisition deadline exceeded")
    opener = urllib.request.build_opener(_AllowedRedirectHandler)
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    response = opener.open(request, timeout=min(30.0, remaining))
    _validate_url(response.geturl(), final=True)
    return response


def _resolve_commit(locator: GitHubLocator, deadline: float) -> str:
    if locator.ref is None:
        endpoint = f"https://api.github.com/repos/{quote(locator.repository_slug, safe='/')}"
    else:
        endpoint = f"https://api.github.com/repos/{quote(locator.repository_slug, safe='/')}/commits/{quote(locator.ref, safe='')}"
    with _open(endpoint, deadline) as response:
        data = json.load(response)
    if locator.ref is None:
        branch = data.get("default_branch")
        if not isinstance(branch, str) or not _safe_component(branch):
            raise ValueError("GitHub repository has no usable default branch")
        return _resolve_commit(GitHubLocator(locator.owner, locator.repository, branch, locator.subpath), deadline)
    sha = data.get("sha")
    if not isinstance(sha, str) or not sha:
        raise ValueError("GitHub response did not contain a commit SHA")
    return sha


def _download_archive(url: str, destination: Path, deadline: float) -> Path:
    temporary: Path | None = None
    try:
        with _open(url, deadline) as response:
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    declared = int(content_length)
                except ValueError as exc:
                    raise ValueError("GitHub archive response has invalid Content-Length") from exc
                if declared < 0 or declared > MAX_ARCHIVE_BYTES:
                    raise ValueError("GitHub archive exceeds compressed byte limit")
            with tempfile.NamedTemporaryFile(dir=destination, prefix=".github-", delete=False) as stream:
                temporary = Path(stream.name)
                total = 0
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("GitHub acquisition deadline exceeded")
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES:
                        raise ValueError("GitHub archive exceeds compressed byte limit")
                    stream.write(chunk)
        return temporary
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _safe_member(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    if "\x00" in normalized:
        raise ValueError("GitHub archive contains a NUL path")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts) or len(path.parts) > MAX_PATH_DEPTH or (path.parts and ":" in path.parts[0]):
        raise ValueError("GitHub archive contains an unsafe path")
    return path


def _extract_archive(archive: Path, destination: Path) -> Path:
    extraction = destination / ".github-extracted"
    extraction.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(archive) as source:
            members = source.infolist()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise ValueError("GitHub archive contains too many files")
            validated = [(member, _safe_member(member.filename)) for member in members]
            roots = {path.parts[0] for _, path in validated if path.parts}
            if len(roots) != 1:
                raise ValueError("GitHub archive has an unexpected root")
            declared_total = 0
            for member, _ in validated:
                if member.is_dir():
                    continue
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("GitHub archive contains a symlink")
                declared_total += member.file_size
                if declared_total > MAX_EXTRACTED_BYTES:
                    raise ValueError("GitHub archive exceeds extracted byte limit")
            written = 0
            for member, path in validated:
                target = extraction.joinpath(*path.parts)
                if not target.resolve().is_relative_to(extraction.resolve()):
                    raise ValueError("GitHub archive contains an unsafe path")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member, "r") as input_stream, target.open("xb") as output_stream:
                    while chunk := input_stream.read(64 * 1024):
                        written += len(chunk)
                        if written > MAX_EXTRACTED_BYTES:
                            raise ValueError("GitHub archive exceeds extracted byte limit")
                        output_stream.write(chunk)
        return extraction / next(iter(roots))
    except Exception:
        shutil.rmtree(extraction, ignore_errors=True)
        raise


def acquire_github(value: str, destination: Path, *, allow_repository_root: bool = False, deadline_seconds: float = DEFAULT_DEADLINE_SECONDS) -> GitHubAcquired:
    locator = parse_github_locator(value, allow_repository_root=allow_repository_root)
    if locator is None:
        raise ValueError("unsupported GitHub locator; use https://github.com/OWNER/REPO/tree/REF[/SUBPATH]")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + deadline_seconds
    resolved_commit = _resolve_commit(locator, deadline)
    archive_url = f"https://codeload.github.com/{quote(locator.repository_slug, safe='/')}/zip/{quote(resolved_commit, safe='')}"
    archive = _download_archive(archive_url, destination, deadline)
    try:
        root = _extract_archive(archive, destination)
    finally:
        archive.unlink(missing_ok=True)
    selected = root / locator.subpath if locator.subpath else root
    if not selected.exists():
        shutil.rmtree(root.parent, ignore_errors=True)
        raise ValueError(f"GitHub subpath does not exist: {locator.subpath}")
    return GitHubAcquired(selected, locator, resolved_commit, archive_url)
