from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
import urllib.error

from .github import GitHubAcquired, acquire_github, parse_github_locator
from .path_utils import normalize_path
from .google_drive import download_google_url, is_google_drive_url


@dataclass(frozen=True)
class AcquiredInput:
    original: str
    local_path: Path | None
    provenance: dict[str, str]
    error: str | None = None


@dataclass(frozen=True)
class AcquisitionResult:
    inputs: tuple[AcquiredInput, ...]
    local_paths: tuple[str, ...]
    errors: tuple[tuple[str, str], ...]


def is_github_locator(value: str, *, allow_repository_root: bool = False) -> bool:
    return parse_github_locator(value, allow_repository_root=allow_repository_root) is not None


def _existing_local_path(value: str) -> Path | None:
    try:
        candidate = Path(normalize_path(value)).resolve()
    except (OSError, ValueError):
        return None
    return candidate if candidate.exists() else None


def validate_local_inputs(
    raw_inputs: Sequence[str],
    *,
    allow_github_repository_root: bool = False,
    google_url_checker=is_google_drive_url,
) -> tuple[tuple[str, str], ...]:
    errors: list[tuple[str, str]] = []
    for raw in raw_inputs:
        if google_url_checker(raw) or is_github_locator(raw, allow_repository_root=allow_github_repository_root):
            continue
        if _existing_local_path(raw) is None:
            errors.append((raw, "file or directory not found"))
    return tuple(errors)


def acquire_inputs(
    raw_inputs: Sequence[str],
    staging_dir: Path,
    *,
    allow_github_repository_root: bool = False,
    google_downloader=download_google_url,
    google_url_checker=is_google_drive_url,
    github_acquirer=acquire_github,
) -> AcquisitionResult:
    staging_dir.mkdir(parents=True, exist_ok=True)
    cache: dict[str, AcquiredInput] = {}
    resolved: list[AcquiredInput] = []
    errors: list[tuple[str, str]] = []
    for raw in raw_inputs:
        if raw in cache:
            item = cache[raw]
            resolved.append(item)
            if item.error:
                errors.append((raw, item.error))
            continue
        kind = "local"
        try:
            local_candidate = _existing_local_path(raw)
            if local_candidate is not None:
                item = AcquiredInput(raw, local_candidate, {"kind": kind, "original": raw})
            elif google_url_checker(raw):
                kind = "google"
                local = google_downloader(raw, staging_dir)
                if local is None:
                    raise ValueError("unsupported Google Drive link")
                item = AcquiredInput(raw, local.resolve(), {"kind": kind, "original": raw})
            elif is_github_locator(raw, allow_repository_root=allow_github_repository_root):
                kind = "github"
                acquired: GitHubAcquired = github_acquirer(
                    raw,
                    staging_dir,
                    allow_repository_root=allow_github_repository_root,
                )
                item = AcquiredInput(raw, acquired.root.resolve(), {"kind": kind, **acquired.provenance})
            else:
                item = AcquiredInput(
                    raw,
                    None,
                    {"kind": kind, "original": raw},
                    "file or directory not found",
                )
        except Exception as exc:
            if kind == "google" and isinstance(exc, urllib.error.HTTPError):
                if exc.code in (401, 403):
                    category = "access denied"
                elif exc.code == 404:
                    category = "not found"
                elif exc.code == 429:
                    category = "rate limited"
                elif 500 <= exc.code <= 599:
                    category = "server error"
                else:
                    category = "HTTP error"
                message = f"{category} (HTTP {exc.code})"
            elif kind in {"google", "github"}:
                message = f"acquisition error: {exc}"
            else:
                message = str(exc)
            item = AcquiredInput(raw, None, {"kind": kind, "original": raw}, message)
        cache[raw] = item
        resolved.append(item)
        if item.error:
            errors.append((raw, item.error))
    local_paths = tuple(str(item.local_path) if item.local_path is not None else item.original for item in resolved if item.error is None)
    return AcquisitionResult(tuple(resolved), local_paths, tuple(errors))
