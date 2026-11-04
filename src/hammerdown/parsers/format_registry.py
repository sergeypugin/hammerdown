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
TreePolicy = Literal["all_formats", "text_convertible", "source_code"]
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
    tree_policy: TreePolicy
    estimate_kind: EstimateKind
    overwrite_source: bool


FORMAT_SPECS: tuple[FormatSpec, ...] = (
    FormatSpec(".pdf", convert_pdf_or_ebook, "pdf", "all_formats", "pdf_pages", False),
    FormatSpec(".epub", convert_pdf_or_ebook, "pdf", "all_formats", "pdf_pages", False),
    FormatSpec(".mobi", convert_pdf_or_ebook, "pdf", "all_formats", "pdf_pages", False),
    FormatSpec(".fb2", convert_pdf_or_ebook, "pdf", "all_formats", "pdf_pages", False),
    FormatSpec(".xps", convert_pdf_or_ebook, "pdf", "all_formats", "pdf_pages", False),
    FormatSpec(".docx", convert_docx, "office", "all_formats", "docx_metadata", False),
    FormatSpec(".doc", convert_doc, "office", "all_formats", "legacy_size", False),
    FormatSpec(".odt", convert_odt, "office", "all_formats", "odt_size", False),
    FormatSpec(".xlsx", convert_xlsx, "office", "all_formats", "xlsx_sheets", False),
    FormatSpec(".xls", convert_xls, "office", "all_formats", "legacy_size", False),
    FormatSpec(".pptx", convert_pptx, "office", "all_formats", "pptx_slides", False),
    FormatSpec(".ppt", convert_ppt, "office", "all_formats", "legacy_size", False),
    FormatSpec(".csv", convert_csv, "text", "text_convertible", "fast_text", True),
    FormatSpec(".txt", convert_txt_or_md, "text", "text_convertible", "fast_text", True),
    FormatSpec(".md", convert_txt_or_md, "text", "text_convertible", "fast_text", True),
    FormatSpec(".log", convert_txt_or_md, "text", "source_code", "fast_text", True),
    FormatSpec(".html", convert_html, "html", "text_convertible", "none", False),
    FormatSpec(".htm", convert_html, "html", "text_convertible", "none", False),
    FormatSpec(".gdoc", convert_html, "html", "all_formats", "none", False),
    FormatSpec(".gsheets", convert_html, "html", "all_formats", "none", False),
    FormatSpec(".gslides", convert_html, "html", "all_formats", "none", False),
    FormatSpec(".gfile", convert_html, "html", "all_formats", "none", False),
    FormatSpec(".zip", convert_zip, "archive", "all_formats", "none", False),
)

CONVERTERS = {spec.extension: spec.converter for spec in FORMAT_SPECS}

__all__ = ["CONVERTERS", "FORMAT_SPECS", "EstimateKind", "FormatKind", "FormatSpec", "TreePolicy"]
