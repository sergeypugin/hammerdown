from __future__ import annotations

import base64
import logging
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
import sys
import tempfile
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

DEFAULT_OVERWRITE: bool = True
DEFAULT_SKIP_EXISTING: bool = False


@dataclass(frozen=True)
class ConversionResult:
    success: bool
    markdown: str | None = None
    images: int = 0
    tokens: int = 0
    duration: float = 0.0
    error: str | None = None
    output_path: Path | None = None

    def __bool__(self) -> bool:
        return self.success


def _embed_temporary_resources(markdown: str, temporary_dir: Path) -> str:
    resources: dict[str, str] = {}
    for resource in temporary_dir.rglob("*"):
        if not resource.is_file():
            continue
        relative = resource.relative_to(temporary_dir).as_posix()
        mime_type = mimetypes.guess_type(resource.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(resource.read_bytes()).decode("ascii")
        resources[relative] = f"data:{mime_type};base64,{encoded}"

    embedded = markdown
    for relative, data_uri in sorted(resources.items(), key=lambda item: len(item[0]), reverse=True):
        embedded = embedded.replace(relative, data_uri)
        embedded = embedded.replace(relative.replace("/", "\\"), data_uri)
    return embedded


def _token_count(markdown: str) -> int:
    try:
        if getattr(sys, "frozen", False) and not os.environ.get("TIKTOKEN_CACHE_DIR"):
            bundle_dir = getattr(sys, "_MEIPASS", None)
            bundled_cache = Path(bundle_dir) / "data-gym-cache" if bundle_dir else None
            if bundled_cache and bundled_cache.is_dir():
                os.environ["TIKTOKEN_CACHE_DIR"] = str(bundled_cache)

        import tiktoken
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(markdown, disallowed_special=()))
    except Exception as exc:
        logger.warning("Token counting unavailable: %s", exc)
        return 0


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


def get_conversion_estimate_seconds(file_path: Path) -> float | None:
    """Estimate conversion time from lightweight document metadata."""
    extension = file_path.suffix.lower()
    if extension in {".pdf", ".epub", ".mobi", ".fb2", ".xps"}:
        try:
            import pymupdf
            with pymupdf.open(str(file_path)) as doc:
                return max(1.0, len(doc) * 0.9)
        except Exception:
            return None
    if extension == ".docx":
        try:
            import re
            import zipfile

            with zipfile.ZipFile(str(file_path)) as archive:
                try:
                    app_xml = archive.read("docProps/app.xml").decode("utf-8")
                    match = re.search(r"<Pages>(\d+)</Pages>", app_xml)
                    if match:
                        return max(1.0, int(match.group(1)) * 0.4)
                    document_size = archive.getinfo("word/document.xml").file_size
                    return max(1.0, document_size / 50000)
                except Exception:
                    pass
        except Exception:
            return None
        return None
    if extension == ".pptx":
        try:
            import zipfile

            with zipfile.ZipFile(str(file_path)) as archive:
                slides = [
                    name for name in archive.namelist()
                    if name.startswith("ppt/slides/slide") and name.endswith(".xml")
                ]
                return max(1.0, len(slides) * 0.2)
        except Exception:
            return None
    if extension == ".odt":
        try:
            import zipfile

            with zipfile.ZipFile(str(file_path)) as archive:
                content_size = archive.getinfo("content.xml").file_size
                return max(1.0, content_size / 50000)
        except Exception:
            return None
    if extension == ".xlsx":
        try:
            import zipfile

            with zipfile.ZipFile(str(file_path)) as archive:
                sheets = [
                    name for name in archive.namelist()
                    if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
                ]
                return max(1.0, len(sheets) * 0.5)
        except Exception:
            return None
    if extension in {".doc", ".xls", ".ppt"}:
        try:
            size_mb = file_path.stat().st_size / (1024 * 1024)
            return 10.0 + size_mb * 2.0
        except OSError:
            return None
    if extension in {".txt", ".md", ".log", ".csv"}:
        return 0.5
    return None


def get_conversion_estimate(file_path: Path) -> str:
    """Return a display hint for the estimated conversion duration."""
    estimate = get_conversion_estimate_seconds(file_path)
    return f"~{format_duration(estimate)}" if estimate is not None else ""


def convert_file(
    file_path: str | os.PathLike[str],
    overwrite: bool = False,
    skip_existing: bool = False,
    progress_callback: ProgressCallback | None = None,
    completion_callback: CompletionCallback | None = None,
    batch_mode: bool = False,
    target_dir: str | os.PathLike[str] | None = None,
    stdout: bool = False,
) -> ConversionResult:
    normalized_path = normalize_path(file_path)
    source = Path(normalized_path)
    if not source.is_file():
        reason = f"file not found: {normalized_path}"
        logger.error("%s", reason)
        if completion_callback:
            completion_callback(False, 0.0, 0, 0)
        return ConversionResult(False, error=reason)

    stem = source.stem
    extension = source.suffix.lower()
    ext_clean = extension.lstrip(".")

    if stdout and (overwrite or skip_existing or target_dir is not None):
        reason = "stdout mode cannot be combined with overwrite, skip-existing, or an output directory"
        logger.error("%s", reason)
        if completion_callback:
            completion_callback(False, 0.0, 0, 0)
        return ConversionResult(False, error=reason)

    temporary_dir: tempfile.TemporaryDirectory[str] | None = None
    if stdout:
        temporary_dir = tempfile.TemporaryDirectory(prefix="hammerdown-stdout-")
        out_dir = Path(temporary_dir.name)
    else:
        out_dir = Path(normalize_path(target_dir)) if target_dir is not None else source.parent

    out_md_name = f"hm_{stem}_{ext_clean}.md" if ext_clean else f"hm_{stem}.md"
    out_md = out_dir / out_md_name
    # Handle explicit source overwrite for text-like files

    is_text = extension in TEXT_EXTENSIONS
    if overwrite:
        if target_dir is not None:
            reason = "--overwrite cannot be combined with an output directory"
            logger.error("%s", reason)
            if completion_callback:
                completion_callback(False, 0.0, 0, 0)
            return ConversionResult(False, error=reason)
        if is_text:
            out_md = source
        elif not batch_mode:
            logger.warning("Overwrite flag ignored for binary format: %s", extension)

    if skip_existing and out_md.exists() and out_md != source:
        logger.info("Skipping %s (output already exists: %s)", source.name, out_md.name)
        if completion_callback:
            completion_callback(True, 0.0, 0, 0)
        return ConversionResult(True, duration=0.0, output_path=out_md)

    out_dir.mkdir(parents=True, exist_ok=True)

    converter = CONVERTERS.get(extension)
    if converter is None:
        reason = f"unsupported format: {extension or '(no extension)'}"
        logger.error("%s", reason)
        if completion_callback:
            completion_callback(False, 0.0, 0, 0)
        if temporary_dir is not None:
            temporary_dir.cleanup()
        return ConversionResult(False, error=reason)

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
            reason = f"conversion failed for {source.name}"
            if is_tty:
                print(f"[x] Failed to convert {source.name}")
            if completion_callback:
                completion_callback(False, time.monotonic() - started_at, 0, 0)
            if temporary_dir is not None:
                temporary_dir.cleanup()
            return ConversionResult(False, error=reason)

        # Trim trailing whitespace on each line and ensure a single final newline
        normalized_text = md_text.replace("\r\n", "\n").replace("\r", "\n")
        trimmed_lines = [line.rstrip() for line in normalized_text.split("\n")]
        cleaned_md = "\n".join(trimmed_lines).rstrip() + "\n"

        if stdout and temporary_dir is not None:
            cleaned_md = _embed_temporary_resources(cleaned_md, Path(temporary_dir.name))

        token_count = _token_count(cleaned_md)

        if stdout:
            duration = time.monotonic() - started_at
            if completion_callback:
                completion_callback(True, duration, saved_images, token_count)
            temporary_dir.cleanup()
            return ConversionResult(
                True,
                markdown=cleaned_md,
                images=saved_images,
                tokens=token_count,
                duration=duration,
            )

        out_md.write_text(cleaned_md, encoding="utf-8", newline="\n")
        duration = time.monotonic() - started_at
        if completion_callback:
            completion_callback(True, duration, saved_images, token_count)

        token_info = f", ~{token_count:_} tokens" if token_count > 0 else ""
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
        return ConversionResult(
            True,
            markdown=cleaned_md,
            images=saved_images,
            tokens=token_count,
            duration=duration,
            output_path=out_md,
        )
    except Exception:
        duration = time.monotonic() - started_at
        if completion_callback:
            completion_callback(False, duration, 0, 0)
        if is_tty and last_len > 0:
            sys.stdout.write(f"\r{' ' * last_len}\r")
            sys.stdout.flush()
        if is_tty:
            print(f"[x] Failed to convert {source.name}")
        if temporary_dir is not None:
            temporary_dir.cleanup()
        return ConversionResult(False, duration=duration, error=f"failed to convert {source.name}")
