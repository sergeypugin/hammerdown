from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
import time
from typing import Callable
from hammerdown.parsers import CONVERTERS
from hammerdown.parsers.charts import render_chart_svg
from hammerdown.parsers.math import mathml_to_latex, omml_to_latex
from hammerdown.parsers.office import (
    convert_doc,
    convert_docx,
    convert_odt,
    convert_ppt,
    convert_pptx,
    convert_xls,
    convert_xlsx,
)
from hammerdown.parsers.pdf import convert_pdf_or_ebook
from hammerdown.parsers.tables import render_table_regions
from hammerdown.parsers.text import convert_csv, convert_txt_or_md
from hammerdown.utils import format_duration, format_progress_bar, normalize_path

logger = logging.getLogger("hammerdown")

ProgressCallback = Callable[[int, int, str], None]
CompletionCallback = Callable[[bool, float, int, int], None]

APP_NAME: str = "hammerdown"
APP_DESCRIPTION: str = "Convert PDF and office documents to Markdown"

SUPPORTED_EXTENSIONS: tuple[str, ...] = tuple(CONVERTERS)
TEXT_EXTENSIONS: tuple[str, ...] = (".txt", ".md")

DEFAULT_IN_PLACE: bool = False
DEFAULT_OVERWRITE: bool = True
DEFAULT_SKIP_EXISTING: bool = False
DEFAULT_QUIET: bool = False


def to_markdown(
    file_path: str | os.PathLike[str],
    target_dir: str | os.PathLike[str] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[str | None, int]:
    normalized_path = normalize_path(file_path)
    source = Path(normalized_path)
    if not source.is_file():
        logger.error("File not found: %s", normalized_path)
        return None, 0

    extension = source.suffix.lower()
    converter = CONVERTERS.get(extension)
    if converter is None:
        logger.error("Unsupported format: %s", extension or "(no extension)")
        return None, 0

    target_dir_path = str(target_dir) if target_dir is not None else str(source.parent)
    try:
        return converter(str(source), target_dir_path, progress_callback=progress_callback)
    except TypeError:
        return converter(str(source), target_dir_path)


def get_conversion_estimate(file_path: Path) -> str:
    """Calculate an estimated conversion duration hint."""
    extension = file_path.suffix.lower()
    if extension in {".pdf", ".epub", ".mobi", ".fb2", ".xps"}:
        try:
            import pymupdf
            with pymupdf.open(str(file_path)) as doc:
                page_count = len(doc)
            est_seconds = max(1.0, page_count * 0.9)
            return f"(est. ~{format_duration(est_seconds)})"
        except Exception:
            return ""
    elif extension == ".docx":
        try:
            import zipfile
            import re
            with zipfile.ZipFile(str(file_path)) as z:
                try:
                    app_xml = z.read("docProps/app.xml").decode("utf-8")
                    match = re.search(r"<Pages>(\d+)</Pages>", app_xml)
                    if match:
                        page_count = int(match.group(1))
                        est_seconds = max(1.0, page_count * 0.4)
                        return f"(est. ~{format_duration(est_seconds)})"
                except Exception:
                    pass
        except Exception:
            pass
    elif extension == ".pptx":
        try:
            import zipfile
            import re
            with zipfile.ZipFile(str(file_path)) as z:
                slides = [name for name in z.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")]
                slide_count = len(slides)
                est_seconds = max(1.0, slide_count * 0.2)
                return f"(est. ~{format_duration(est_seconds)})"
        except Exception:
            pass
    elif extension == ".xlsx":
        try:
            import zipfile
            with zipfile.ZipFile(str(file_path)) as z:
                sheets = [name for name in z.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")]
                sheet_count = len(sheets)
                est_seconds = max(1.0, sheet_count * 0.5)
                return f"(est. ~{format_duration(est_seconds)})"
        except Exception:
            pass
    elif extension in {".doc", ".xls", ".ppt"}:
        size_mb = file_path.stat().st_size / (1024 * 1024)
        est_seconds = 10.0 + (size_mb * 2.0)
        return f"(est. ~{format_duration(est_seconds)})"
    elif extension in {".txt", ".md", ".log", ".csv"}:
        return "(fast conversion)"
    return ""


def convert_file(
    file_path: str | os.PathLike[str],
    in_place: bool = True,
    overwrite: bool = False,
    skip_existing: bool = False,
    progress_callback: ProgressCallback | None = None,
    completion_callback: CompletionCallback | None = None,
    batch_mode: bool = False,
) -> bool:
    normalized_path = normalize_path(file_path)
    source = Path(normalized_path)
    if not source.is_file():
        logger.error("File not found: %s", normalized_path)
        return False

    stem = source.stem
    extension = source.suffix.lower()
    ext_clean = extension.lstrip(".")

    out_dir = source.parent
    out_md_name = f"hm_{stem}_{ext_clean}.md" if ext_clean else f"hm_{stem}.md"
    out_md = out_dir / out_md_name

    # Handle explicit source overwrite for text-like files
    is_text = extension in TEXT_EXTENSIONS
    if overwrite:
        if is_text:
            out_md = source
        else:
            logger.warning("Overwrite flag ignored for binary format: %s", extension)

    if skip_existing and out_md.exists() and out_md != source:
        logger.info("Skipping %s (output already exists: %s)", source.name, out_md.name)
        return True

    out_dir.mkdir(parents=True, exist_ok=True)

    converter = CONVERTERS.get(extension)
    if converter is None:
        logger.error("Unsupported format: %s", extension or "(no extension)")
        return False

    est_hint = ""
    if extension in {".pdf", ".epub", ".mobi", ".fb2", ".xps"}:
        try:
            import pymupdf  # type: ignore
            with pymupdf.open(str(source)) as doc:
                page_count = len(doc)
            est_seconds = max(1.0, page_count * 0.9)
            est_hint = f" ({page_count} pages, est. ~{format_duration(est_seconds)})"
        except Exception:
            pass
    elif extension == ".docx":
        try:
            import zipfile
            import re
            with zipfile.ZipFile(str(source)) as z:
                try:
                    app_xml = z.read("docProps/app.xml").decode("utf-8")
                    match = re.search(r"<Pages>(\d+)</Pages>", app_xml)
                    if match:
                        page_count = int(match.group(1))
                        est_seconds = max(1.0, page_count * 0.4)
                        est_hint = f" ({page_count} pages, est. ~{format_duration(est_seconds)})"
                    else:
                        # Fallback: estimate from document.xml size
                        doc_xml_size = z.getinfo("word/document.xml").file_size
                        est_seconds = max(1.0, doc_xml_size / 50000)
                        est_hint = f" (est. ~{format_duration(est_seconds)})"
                except Exception:
                    pass
        except Exception:
            pass
    elif extension == ".pptx":
        try:
            import zipfile
            import re
            with zipfile.ZipFile(str(source)) as z:
                slides = [name for name in z.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")]
                slide_count = len(slides)
                est_seconds = max(1.0, slide_count * 0.2)
                est_hint = f" ({slide_count} slides, est. ~{format_duration(est_seconds)})"
        except Exception:
            pass
    elif extension == ".xlsx":
        try:
            import zipfile
            with zipfile.ZipFile(str(source)) as z:
                sheets = [name for name in z.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")]
                sheet_count = len(sheets)
                est_seconds = max(1.0, sheet_count * 0.5)
                est_hint = f" ({sheet_count} sheets, est. ~{format_duration(est_seconds)})"
        except Exception:
            pass
    elif extension in {".doc", ".xls", ".ppt"}:
        # Legacy formats require conversion via Word/LibreOffice
        size_mb = source.stat().st_size / (1024 * 1024)
        est_seconds = 10.0 + (size_mb * 2.0)
        est_hint = f" (legacy format, est. ~{format_duration(est_seconds)})"
    elif extension == ".odt":
        try:
            import zipfile
            with zipfile.ZipFile(str(source)) as z:
                content_size = z.getinfo("content.xml").file_size
                est_seconds = max(1.0, content_size / 50000)
                est_hint = f" (est. ~{format_duration(est_seconds)})"
        except Exception:
            pass
    elif extension in {".txt", ".md", ".log", ".csv"}:
        # Instant or near-instant text processing
        est_hint = " (fast text conversion)"

    is_tty = sys.stdout.isatty() and logger.isEnabledFor(logging.INFO) and not batch_mode
    if is_tty:
        print(f'\nProcessing "{source.name}"{est_hint}...\n')
        if extension in {".doc", ".xls", ".ppt"}:
            sys.stdout.write("[ ] Converting via Office automation...")
            sys.stdout.flush()
            last_len = 35
    elif not batch_mode:
        logger.info("Processing %s%s...", source.name, est_hint)

    started_at = time.monotonic()

    active_callback = progress_callback
    last_len = 0
    last_pct = -1

    if active_callback is None:
        def default_progress_handler(current: int, total: int, unit: str = "pages") -> None:
            nonlocal last_len, last_pct
            if total <= 0:
                return
            pct = int((current / total) * 100)
            if is_tty:
                bar_str = format_progress_bar(current, total, unit=unit)
                # Keep active bar cleanly formatted
                sys.stdout.write(f"\r{bar_str}".ljust(last_len))
                sys.stdout.flush()
                last_len = max(last_len, len(bar_str))
            else:
                if pct > last_pct:
                    last_pct = pct
                    logger.info("Processing %s: %d/%d %s (%d%%)...", source.name, current, total, unit, pct)

        active_callback = default_progress_handler

    try:
        try:
            md_text, saved_images = converter(str(source), str(out_dir), progress_callback=active_callback)
        except TypeError:
            md_text, saved_images = converter(str(source), str(out_dir))

        if is_tty and last_len > 0:
            sys.stdout.write(f"\r{' ' * last_len}\r")
            sys.stdout.flush()

        if md_text is None:
            if is_tty:
                print(f"[x] Failed to convert {source.name}")
            if completion_callback:
                completion_callback(False, time.monotonic() - started_at, 0, 0)
            return False

        # Trim trailing whitespace on each line and ensure a single final newline
        normalized_text = md_text.replace("\r\n", "\n").replace("\r", "\n")
        trimmed_lines = [line.rstrip() for line in normalized_text.split("\n")]
        cleaned_md = "\n".join(trimmed_lines).rstrip() + "\n"

        token_count = 0
        try:
            if getattr(sys, "frozen", False) and not os.environ.get("TIKTOKEN_CACHE_DIR"):
                bundle_dir = getattr(sys, "_MEIPASS", None)
                bundled_cache = Path(bundle_dir) / "data-gym-cache" if bundle_dir else None
                if bundled_cache and bundled_cache.is_dir():
                    os.environ["TIKTOKEN_CACHE_DIR"] = str(bundled_cache)

            import tiktoken
            encoding = tiktoken.get_encoding("cl100k_base")
            token_count = len(encoding.encode(cleaned_md, disallowed_special=()))
        except Exception as exc:
            logger.warning("Token counting unavailable for %s: %s", source.name, exc)

        out_md.write_text(cleaned_md, encoding="utf-8", newline="\n")
        duration = time.monotonic() - started_at
        if completion_callback:
            completion_callback(True, duration, saved_images, token_count)

        token_info = f", ~{token_count} tokens" if token_count > 0 else ""
        if is_tty:
            print(f"[x] Completed {source.name} in {format_duration(duration)} ({saved_images} images{token_info})")
        elif not batch_mode:
            logger.info(
                "Completed %s in %s (%d images%s)",
                source.name,
                format_duration(duration),
                saved_images,
                token_info,
            )
        return True
    except Exception:
        duration = time.monotonic() - started_at
        if completion_callback:
            completion_callback(False, duration, 0, 0)
        if is_tty and last_len > 0:
            sys.stdout.write(f"\r{' ' * last_len}\r")
            sys.stdout.flush()
        if is_tty:
            print(f"[x] Failed to convert {source.name}")
        logger.exception("Failed to convert %s", source.name)
        return False
