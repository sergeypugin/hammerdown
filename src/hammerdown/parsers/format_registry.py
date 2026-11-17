from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from .html import convert_html
from .office import (
    convert_doc,
    convert_docx,
    convert_odt,
    convert_ppt,
    convert_pptx,
    convert_xls,
    convert_xlsx,
)
from .pdf import convert_pdf_or_ebook
from .text import convert_csv, convert_txt_or_md
from .archive import convert_zip

FormatKind = Literal["pdf", "office", "text", "html", "archive"]
EstimateKind = Literal[
    "pdf_pages",
    "docx_metadata",
    "pptx_slides",
    "xlsx_sheets",
    "odt_size",
    "legacy_size",
    "fast_text",
    "none",
]


@dataclass(frozen=True)
class FormatSpec:
    extension: str
    converter: Callable[..., Any]
    kind: FormatKind
    estimate_kind: EstimateKind
    overwrite_source: bool


FORMAT_SPECS: tuple[FormatSpec, ...] = (
    FormatSpec(".pdf", convert_pdf_or_ebook, "pdf", "pdf_pages", False),
    FormatSpec(".epub", convert_pdf_or_ebook, "pdf", "pdf_pages", False),
    FormatSpec(".mobi", convert_pdf_or_ebook, "pdf", "pdf_pages", False),
    FormatSpec(".fb2", convert_pdf_or_ebook, "pdf", "pdf_pages", False),
    FormatSpec(".xps", convert_pdf_or_ebook, "pdf", "pdf_pages", False),
    FormatSpec(".docx", convert_docx, "office", "docx_metadata", False),
    FormatSpec(".doc", convert_doc, "office", "legacy_size", False),
    FormatSpec(".odt", convert_odt, "office", "odt_size", False),
    FormatSpec(".xlsx", convert_xlsx, "office", "xlsx_sheets", False),
    FormatSpec(".xls", convert_xls, "office", "legacy_size", False),
    FormatSpec(".pptx", convert_pptx, "office", "pptx_slides", False),
    FormatSpec(".ppt", convert_ppt, "office", "legacy_size", False),
    FormatSpec(".csv", convert_csv, "text", "fast_text", True),
    FormatSpec(".txt", convert_txt_or_md, "text", "fast_text", True),
    FormatSpec(".md", convert_txt_or_md, "text", "fast_text", True),
    FormatSpec(".log", convert_txt_or_md, "text", "fast_text", True),
    FormatSpec(".html", convert_html, "html", "none", False),
    FormatSpec(".htm", convert_html, "html", "none", False),
    FormatSpec(".gdoc", convert_html, "html", "none", False),
    FormatSpec(".gsheets", convert_html, "html", "none", False),
    FormatSpec(".gslides", convert_html, "html", "none", False),
    FormatSpec(".gfile", convert_html, "html", "none", False),
    FormatSpec(".zip", convert_zip, "archive", "none", False),
)

CONVERTERS = {spec.extension: spec.converter for spec in FORMAT_SPECS}

# Binary formats that Hammerdown converts (merge mode marks them as convertible).
CONVERTIBLE_BINARY_FORMATS = {".pdf", ".docx", ".xlsx", ".doc", ".xls", ".pptx", ".ppt", ".odt"}

# Binary formats that tree mode never includes by content sniff, convertible or not.
BINARY_FORMATS = {
    ".pdf", ".docx", ".xlsx", ".doc", ".xls", ".pptx", ".ppt", ".odt", ".epub", ".mobi",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico", ".tiff",
    ".mp3", ".mp4", ".wav", ".flac", ".m4a", ".aac", ".wma", ".avi", ".mov", ".mkv",
    ".exe", ".dll", ".so", ".dylib", ".app", ".apk",
    ".bin", ".dat", ".db", ".sqlite",
}

__all__ = ["CONVERTERS", "FORMAT_SPECS", "BINARY_FORMATS", "CONVERTIBLE_BINARY_FORMATS", "EstimateKind", "FormatKind", "FormatSpec"]
