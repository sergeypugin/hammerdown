from __future__ import annotations

import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import NamedTuple

# Matches the file id inside a Google Docs or Google Drive file URL.
_GOOGLE_DOCS_RE = re.compile(r"docs\.google\.com/(document|spreadsheets|presentation)/d/([a-zA-Z0-9_-]+)")
_GOOGLE_DRIVE_FILE_RE = re.compile(r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)")
_GOOGLE_DRIVE_FOLDER_RE = re.compile(r"drive\.google\.com/drive/(?:u/\d+/)?folders/([a-zA-Z0-9_-]+)")

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# Drive folders and generic "View" pages are not files: we do not support them.
_DRIVE_VIEW_MARKERS = ("/drive/folders/", "/drive/u/")

class GoogleFileInfo(NamedTuple):
    file_id: str
    doc_type: str  # 'gdoc', 'gsheets', 'gslides', 'gfile'
    title: str | None = None

def is_google_drive_url(value: str) -> bool:
    """Return True when *value* looks like a downloadable Google Docs or Drive file URL."""
    return get_google_file_info(value) is not None


def get_google_file_info(url: str) -> GoogleFileInfo | None:
    """Extract file ID and determine document type from a Google URL."""
    docs_match = _GOOGLE_DOCS_RE.search(url)
    if docs_match:
        doc_type_map = {
            "document": "gdoc",
            "spreadsheets": "gsheets",
            "presentation": "gslides",
        }
        return GoogleFileInfo(docs_match.group(2), doc_type_map.get(docs_match.group(1), "gdoc"))

    file_match = _GOOGLE_DRIVE_FILE_RE.search(url)
    if file_match:
        return GoogleFileInfo(file_match.group(1), "gfile")

    return None


def extract_file_id(value: str) -> str | None:
    """Return the file id for a Google Docs/Drive file URL, or None for folders."""
    docs_match = _GOOGLE_DOCS_RE.search(value)
    if docs_match:
        return docs_match.group(2)
    file_match = _GOOGLE_DRIVE_FILE_RE.search(value)
    if file_match:
        return file_match.group(1)
    if _GOOGLE_DRIVE_FOLDER_RE.search(value) or any(marker in value for marker in _DRIVE_VIEW_MARKERS):
        return None
    return None


def build_export_url(value: str, file_id: str) -> str | None:
    """Build the export URL for the file id."""
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

def fetch_google_title(url: str) -> str | None:
    """Fetch the document title from the Google Doc/Drive page metadata."""
    # Use the /edit or /view URL to get the UI page which contains metadata.
    # If the URL is already an export URL, this won't work well, but we usually
    # get the UI URL from the user.
    ui_url = url
    if "/export" in url:
        file_id = extract_file_id(url)
        if not file_id:
            return None
        if "docs.google.com/document" in url:
            ui_url = f"https://docs.google.com/document/d/{file_id}/edit"
        elif "docs.google.com/spreadsheets" in url:
            ui_url = f"https://docs.google.com/spreadsheets/d/{file_id}/edit"
        elif "docs.google.com/presentation" in url:
            ui_url = f"https://docs.google.com/presentation/d/{file_id}/edit"
        elif "drive.google.com" in url:
            ui_url = f"https://drive.google.com/file/d/{file_id}/view"

    try:
        request = urllib.request.Request(ui_url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=10) as response:
            # Read just enough to find the title/og:title
            chunk = response.read(65536).decode("utf-8", errors="ignore")

        # Prefer og:title (clean name) over <title> (has " - Google Docs" suffix)
        og_match = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']', chunk, re.I)
        if not og_match:
            og_match = re.search(r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:title["\']', chunk, re.I)

        if og_match:
            return og_match.group(1).strip()

        title_match = re.search(r"<title>([^<]+)</title>", chunk, re.I)
        if title_match:
            title = title_match.group(1).strip()
            # Clean up common suffixes
            for suffix in (" - Google Docs", " - Google Таблицы", " - Google Презентации", " - Google Sheets", " - Google Slides", " - Google Drive"):
                if title.endswith(suffix):
                    title = title[: -len(suffix)]
            return title
    except Exception:
        pass
    return None

def sanitize_filename(name: str) -> str:
    """Remove characters that are invalid in Windows filenames."""
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip()

def download_google_url(value: str, target_dir: str | os.PathLike[str]) -> Path | None:
    """Download a Google Docs/Drive *file* URL and return a local path."""
    info = get_google_file_info(value)
    if not info:
        return None

    export_url = build_export_url(value, info.file_id)
    if not export_url:
        return None

    try:
        sys.stderr.write(f"[ ] Downloading Google {info.doc_type}...\r")
        sys.stderr.flush()

        request = urllib.request.Request(export_url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()

        target_path = Path(target_dir)
        target_path.mkdir(parents=True, exist_ok=True)

        title = fetch_google_title(value)
        if title:
            safe_title = sanitize_filename(title)
            filename = f"{safe_title}.{info.doc_type}"
        else:
            filename = f"google_{info.file_id}.{info.doc_type}"

        out_path = target_path / filename
        out_path.write_bytes(payload)
        return out_path
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        # Re-raise to let batch.py handle it with better messages
        raise e
    finally:
        sys.stderr.write(" " * 40 + "\r")
        sys.stderr.flush()
