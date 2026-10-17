from __future__ import annotations

import re
import zipfile
from pathlib import Path

from hammerdown.formatting import format_duration

PDF_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".epub", ".mobi", ".fb2", ".xps"})
LEGACY_EXTENSIONS: frozenset[str] = frozenset({".doc", ".xls", ".ppt"})
# Distinct from core.TEXT_EXTENSIONS, which drives in-place overwrite behaviour.
FAST_TEXT_EXTENSIONS: frozenset[str] = frozenset({".txt", ".md", ".log", ".csv"})

_DOCX_PAGES_PATTERN = re.compile(r"<Pages>(\d+)</Pages>")


def _pdf_page_count(file_path: Path) -> int | None:
    try:
        import pymupdf  # type: ignore

        with pymupdf.open(str(file_path)) as document:
            return len(document)
    except Exception:
        return None


def _zip_member_size(file_path: Path, member: str) -> int | None:
    try:
        with zipfile.ZipFile(str(file_path)) as archive:
            return archive.getinfo(member).file_size
    except Exception:
        return None


def _zip_member_count(file_path: Path, prefix: str, suffix: str) -> int | None:
    try:
        with zipfile.ZipFile(str(file_path)) as archive:
            return sum(1 for name in archive.namelist() if name.startswith(prefix) and name.endswith(suffix))
    except Exception:
        return None


def _docx_page_count(file_path: Path) -> int | None:
    try:
        with zipfile.ZipFile(str(file_path)) as archive:
            try:
                app_xml = archive.read("docProps/app.xml").decode("utf-8")
            except KeyError:
                return None
    except Exception:
        return None
    match = _DOCX_PAGES_PATTERN.search(app_xml)
    return int(match.group(1)) if match else None


def describe(file_path: Path) -> tuple[float | None, str]:
    """Return the estimated duration in seconds and a display hint suffix.

    Both values come from lightweight document metadata so that the estimate is
    available before any expensive conversion work starts. The hint is empty
    when the estimate cannot be computed.
    """
    extension = file_path.suffix.lower()

    if extension in PDF_EXTENSIONS:
        pages = _pdf_page_count(file_path)
        if pages is None:
            return None, ""
        seconds = max(1.0, pages * 0.9)
        return seconds, f" ({pages} pages, est. ~{format_duration(seconds)})"

    if extension == ".docx":
        pages = _docx_page_count(file_path)
        if pages is not None:
            seconds = max(1.0, pages * 0.4)
            return seconds, f" ({pages} pages, est. ~{format_duration(seconds)})"
        document_size = _zip_member_size(file_path, "word/document.xml")
        if document_size is None:
            return None, ""
        seconds = max(1.0, document_size / 50000)
        return seconds, f" (est. ~{format_duration(seconds)})"

    if extension == ".pptx":
        slides = _zip_member_count(file_path, "ppt/slides/slide", ".xml")
        if slides is None:
            return None, ""
        seconds = max(1.0, slides * 0.2)
        return seconds, f" ({slides} slides, est. ~{format_duration(seconds)})"

    if extension == ".xlsx":
        sheets = _zip_member_count(file_path, "xl/worksheets/sheet", ".xml")
        if sheets is None:
            return None, ""
        seconds = max(1.0, sheets * 0.5)
        return seconds, f" ({sheets} sheets, est. ~{format_duration(seconds)})"

    if extension == ".odt":
        content_size = _zip_member_size(file_path, "content.xml")
        if content_size is None:
            return None, ""
        seconds = max(1.0, content_size / 50000)
        return seconds, f" (est. ~{format_duration(seconds)})"

    if extension in LEGACY_EXTENSIONS:
        try:
            size_mb = file_path.stat().st_size / (1024 * 1024)
        except OSError:
            return None, ""
        seconds = 10.0 + size_mb * 2.0
        return seconds, f" (legacy format, est. ~{format_duration(seconds)})"

    if extension in FAST_TEXT_EXTENSIONS:
        return 0.5, " (fast text conversion)"

    return None, ""


def get_conversion_estimate_seconds(file_path: Path) -> float | None:
    """Estimate conversion time from lightweight document metadata."""
    return describe(file_path)[0]


def get_conversion_estimate(file_path: Path) -> str:
    """Return a display hint for the estimated conversion duration."""
    seconds = describe(file_path)[0]
    return f"~{format_duration(seconds)}" if seconds is not None else ""
