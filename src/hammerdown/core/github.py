from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import time
from urllib.parse import quote, unquote, urlparse
import urllib.error
import urllib.request
import zipfile

MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_EXTRACTED_BYTES = 250 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 100_000
MAX_PATH_DEPTH = 32
DEFAULT_DEADLINE_SECONDS = 120.0
_ALLOWED_HOSTS = {"github.com", "api.github.com", "codeload.github.com"}
_GITHUB_URL_HOSTS = {"github.com", "www.github.com", "raw.githubusercontent.com"}
_FULL_COMMIT_SHA = re.compile(r"[0-9a-fA-F]{40}")
_USER_AGENT = "Hammerdown/4"
GITHUB_USAGE_HINT = (
    "use https://github.com/OWNER/REPO, https://github.com/OWNER/REPO/tree/REF[/SUBPATH], "
    "or https://github.com/OWNER/REPO/blob/REF/PATH/TO/FILE"
)


@dataclass(frozen=True)
class GitHubLocator:
    owner: str
    repository: str
    ref: str | None = None
    subpath: str = ""
    kind: str = "tree"

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
        location = f"https://github.com/{self.locator.repository_slug}/{self.locator.kind}/{self.locator.ref or self.resolved_commit}"
        if self.locator.subpath:
            location = f"{location}/{self.locator.subpath}"
        return {
            "locator": location,
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
    hostname = parsed.hostname
    if hostname is not None and hostname.startswith("www."):
        hostname = hostname[4:]
    if parsed.scheme != "https" or hostname != "github.com" or parsed.username is not None or parsed.password is not None or port is not None:
        return None
    # fragments (#L142) and query strings (?plain=1) are browser navigation noise
    path = parsed.path
    while path.endswith("/"):
        path = path[:-1]
    parts = _decode_segments(path)
    if parts is None:
        return None
    if len(parts) == 2 and allow_repository_root:
        return GitHubLocator(parts[0], parts[1])
    if len(parts) < 4 or parts[2] not in ("tree", "blob"):
        return None
    if not all(_safe_component(part) for part in parts[:4]):
        return None
    subpath = "/".join(parts[4:])
    if parts[2] == "blob" and not subpath:
        return None
    return GitHubLocator(parts[0], parts[1], parts[3], subpath, parts[2])


def looks_like_github_url(value: str) -> bool:
    candidate = value.strip()
    if not candidate or "\x00" in candidate:
        return False
    if "://" in candidate:
        parsed = urlparse(candidate)
        try:
            parsed.port
        except ValueError:
            return True
        return parsed.hostname in _GITHUB_URL_HOSTS
    lower = candidate.lower()
    return lower.startswith("github.com/") or lower.startswith("www.github.com/")


def github_url_rejection_reason(value: str, *, allow_repository_root: bool = False) -> str | None:
    candidate = value.strip()
    lower = candidate.lower()
    if "://" not in candidate and not lower.startswith(("github.com/", "www.github.com/")):
        # bare "owner/repo" is a valid local relative path, so a failed local
        # lookup keeps its plain "file or directory not found" message
        return None
    if parse_github_locator(candidate, allow_repository_root=True) is not None:
        return None if allow_repository_root else "GitHub repository root link requires tree mode"
    if looks_like_github_url(candidate):
        return f"unsupported GitHub URL ({GITHUB_USAGE_HINT})"
    return None


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


def _fetch_commit_sha(owner: str, repository: str, ref: str, deadline: float) -> str:
    slug = quote(f"{owner}/{repository}", safe="/")
    endpoint = f"https://api.github.com/repos/{slug}/commits/{quote(ref, safe='')}"
    with _open(endpoint, deadline) as response:
        data = json.load(response)
    sha = data.get("sha")
    if not isinstance(sha, str) or not sha:
        raise ValueError("GitHub response did not contain a commit SHA")
    return sha


def _ref_candidates(locator: GitHubLocator) -> list[tuple[str, str]]:
    # parse splits the URL remainder provisionally into ref + subpath, but a
    # branch name may itself contain slashes (tree/release/1.0/doc). GitHub and
    # git resolve the ambiguity longest-match-first, so try the full remainder
    # as a ref first and shorten it step by step. A 40-hex commit SHA can never
    # be the prefix of a longer ref worth trying, so permalinks skip the walk.
    segments = [locator.ref] if locator.ref else []
    if locator.subpath:
        segments.extend(locator.subpath.split("/"))
    if len(segments) <= 1:
        return [("/".join(segments), "")]
    if _FULL_COMMIT_SHA.fullmatch(segments[0]):
        return [(segments[0], "/".join(segments[1:]))]
    return [
        ("/".join(segments[:count]), "/".join(segments[count:]))
        for count in range(len(segments), 0, -1)
    ]


def _resolve_commit_with_split(locator: GitHubLocator, deadline: float) -> tuple[str, GitHubLocator]:
    if locator.ref is None:
        endpoint = f"https://api.github.com/repos/{quote(locator.repository_slug, safe='/')}"
        with _open(endpoint, deadline) as response:
            data = json.load(response)
        branch = data.get("default_branch")
        if not isinstance(branch, str) or not _safe_component(branch):
            raise ValueError("GitHub repository has no usable default branch")
        return _resolve_commit_with_split(
            GitHubLocator(locator.owner, locator.repository, branch, "", locator.kind), deadline
        )
    last_error: Exception | None = None
    for candidate_ref, candidate_subpath in _ref_candidates(locator):
        try:
            sha = _fetch_commit_sha(locator.owner, locator.repository, candidate_ref, deadline)
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404, 422):
                last_error = exc
                continue
            raise
        return sha, GitHubLocator(locator.owner, locator.repository, candidate_ref, candidate_subpath, locator.kind)
    remainder = "/".join([locator.ref, *locator.subpath.split("/")]) if locator.subpath else locator.ref
    raise ValueError(f"GitHub ref does not exist: {remainder}") from last_error


def _resolve_commit(locator: GitHubLocator, deadline: float) -> str:
    return _resolve_commit_with_split(locator, deadline)[0]


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
                try:
                    with source.open(member, "r") as input_stream, target.open("xb") as output_stream:
                        while chunk := input_stream.read(64 * 1024):
                            written += len(chunk)
                            if written > MAX_EXTRACTED_BYTES:
                                raise ValueError("GitHub archive exceeds extracted byte limit")
                            output_stream.write(chunk)
                except OSError as exc:
                    raise ValueError("GitHub archive contains conflicting entries") from exc
        return extraction / next(iter(roots))
    except Exception:
        shutil.rmtree(extraction, ignore_errors=True)
        raise


def acquire_github(value: str, destination: Path, *, allow_repository_root: bool = False, deadline_seconds: float = DEFAULT_DEADLINE_SECONDS) -> GitHubAcquired:
    locator = parse_github_locator(value, allow_repository_root=allow_repository_root)
    if locator is None:
        raise ValueError(f"unsupported GitHub locator ({GITHUB_USAGE_HINT})")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + deadline_seconds
    resolved_commit, resolved_locator = _resolve_commit_with_split(locator, deadline)
    archive_url = f"https://codeload.github.com/{quote(resolved_locator.repository_slug, safe='/')}/zip/{quote(resolved_commit, safe='')}"
    archive = _download_archive(archive_url, destination, deadline)
    try:
        root = _extract_archive(archive, destination)
    finally:
        archive.unlink(missing_ok=True)
    selected = root / resolved_locator.subpath if resolved_locator.subpath else root
    if resolved_locator.kind == "blob":
        if selected.is_dir():
            shutil.rmtree(root.parent, ignore_errors=True)
            raise ValueError(f"GitHub blob path is a directory; use a /tree/ link: {resolved_locator.subpath}")
        if not selected.is_file():
            shutil.rmtree(root.parent, ignore_errors=True)
            raise ValueError(f"GitHub file does not exist in the repository: {resolved_locator.subpath}")
    elif not selected.exists():
        shutil.rmtree(root.parent, ignore_errors=True)
        raise ValueError(f"GitHub subpath does not exist: {resolved_locator.subpath}")
    return GitHubAcquired(selected, resolved_locator, resolved_commit, archive_url)
