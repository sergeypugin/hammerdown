from __future__ import annotations

import os
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from hammerdown.core import convert_file

# Matches the file id inside a Google Docs or Google Drive file URL.
_GOOGLE_DOCS_RE = re.compile(r"docs\.google\.com/(document|spreadsheets|presentation)/d/([a-zA-Z0-9_-]+)")
_GOOGLE_DRIVE_FILE_RE = re.compile(r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)")
_GOOGLE_DRIVE_FOLDER_RE = re.compile(r"drive\.google\.com/drive/(?:u/\d+/)?folders/([a-zA-Z0-9_-]+)")

_USER_AGENT = "Mozilla/5.0 (compatible; hammerdown/3.1)"

# Drive folders and generic "View" pages are not files: we do not support them.
_DRIVE_VIEW_MARKERS = ("/drive/folders/", "/drive/u/")


def is_google_drive_url(value: str) -> bool:
    """Return True when *value* looks like a Google Docs or Drive URL."""
    lowered = value.lower()
    return "docs.google.com" in lowered or "drive.google.com" in lowered


def extract_file_id(value: str) -> str | None:
    """Return the file id for a Google Docs/Drive file URL, or None for folders."""
    docs_match = _GOOGLE_DOCS_RE.search(value)
    if docs_match:
        return docs_match.group(2)
    file_match = _GOOGLE_DRIVE_FILE_RE.search(value)
    if file_match:
        return file_match.group(1)
    # Explicitly reject folder/share URLs: these need Drive API/authentication.
    if _GOOGLE_DRIVE_FOLDER_RE.search(value) or any(marker in value for marker in _DRIVE_VIEW_MARKERS):
        return None
    return None


def build_export_url(value: str, file_id: str) -> str | None:
    """Build the export URL for the file id.

    Google Docs, Sheets and Slides are exported as HTML. A generic Drive file
    falls back to the `uc` download endpoint, which may return a binary or a
    rendered document depending on the file type.
    """
    lowered = value.lower()
    if "docs.google.com/spreadsheets" in lowered:
        return f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=html"
    if "docs.google.com/presentation" in lowered:
        return f"https://docs.google.com/presentation/d/{file_id}/export?format=html"
    if "docs.google.com/document" in lowered:
        return f"https://docs.google.com/document/d/{file_id}/export?format=html"
    if "drive.google.com/file" in lowered:
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    return None


def download_google_url(value: str, target_dir: str | os.PathLike[str]) -> Path | None:
    """Download a Google Docs/Drive *file* URL and return a local path.

    The remote HTML is written into *target_dir* so it can be fed to the
    existing conversion pipeline. Folders are not supported.
    """
    file_id = extract_file_id(value)
    if not file_id:
        return None

    export_url = build_export_url(value, file_id)
    if not export_url:
        return None

    try:
        request = urllib.request.Request(export_url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()

        target_path = Path(target_dir)
        target_path.mkdir(parents=True, exist_ok=True)
        out_path = target_path / f"google_{file_id}.html"
        out_path.write_bytes(payload)
        return out_path
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return None
