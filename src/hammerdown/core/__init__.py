from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
import sys
import tempfile
import time
from typing import Callable

from .estimates import describe, get_conversion_estimate, get_conversion_estimate_seconds
from ..parsers import CONVERTERS
from ..parsers.charts import render_chart_svg
from ..parsers.math import mathml_to_latex, omml_to_latex
from ..parsers.office import (
    convert_doc,
    convert_docx,
    convert_odt,
    convert_ppt,
    convert_pptx,
    convert_xls,
    convert_xlsx,
)
from ..parsers.pdf import convert_pdf_or_ebook
from ..parsers.tables import render_table_regions
from ..parsers.text import convert_csv, convert_txt_or_md
from .description import APP_DESCRIPTION
from .resources import embed_temporary_resources, token_count
from .formatting import format_duration, format_progress_bar
from .path_utils import normalize_path
from .google_drive import (
    download_google_url,
    extract_file_id,
    is_google_drive_url,
    build_export_url,
    fetch_google_title,
    sanitize_filename,
    get_google_file_info,
)
from .ipc import IPCCoordinator, try_delegate_to_coordinator

logger = logging.getLogger("hammerdown")

ProgressCallback = Callable[[int, int, str], None]
CompletionCallback = Callable[[bool, float, int, int], None]

APP_NAME: str = "hammerdown"


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
    return converter(str(source), target_dir_path, progress_callback=progress_callback)


def convert_file(
    file_path: str | os.PathLike[str],
    overwrite: bool = False,
    skip_existing: bool = False,
    progress_callback: ProgressCallback | None = None,
    completion_callback: CompletionCallback | None = None,
    batch_mode: bool = False,
    target_dir: str | os.PathLike[str] | None = None,
    stdout: bool = False,
    asset_dir: str | os.PathLike[str] | None = None,
    write_markdown: bool = True,
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

    if stdout and (overwrite or skip_existing or target_dir is not None or asset_dir is not None):
        reason = "stdout mode cannot be combined with overwrite, skip-existing, or output directories"
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
    resource_dir = Path(normalize_path(asset_dir)) if asset_dir is not None else out_dir

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

    if write_markdown:
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

    _, est_hint = describe(source)

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
        md_text, saved_images = converter(str(source), str(resource_dir), progress_callback=active_callback)

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
            cleaned_md = embed_temporary_resources(cleaned_md, Path(temporary_dir.name))

        counted_tokens = token_count(cleaned_md)

        if stdout:
            if temporary_dir is None:
                raise RuntimeError("temporary output directory is required for stdout conversion")
            duration = time.monotonic() - started_at
            if completion_callback:
                completion_callback(True, duration, saved_images, counted_tokens)
            temporary_dir.cleanup()
            return ConversionResult(
                True,
                markdown=cleaned_md,
                images=saved_images,
                tokens=counted_tokens,
                duration=duration,
            )

        should_write_markdown = write_markdown or out_md == source
        if should_write_markdown:
            out_md.write_text(cleaned_md, encoding="utf-8", newline="\n")
        duration = time.monotonic() - started_at
        if completion_callback:
            completion_callback(True, duration, saved_images, counted_tokens)

        token_info = f", ~{counted_tokens:_} tokens" if counted_tokens > 0 else ""
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
            tokens=counted_tokens,
            duration=duration,
            output_path=out_md if should_write_markdown else None,
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


__all__ = [
    "APP_DESCRIPTION",
    "APP_NAME",
    "DEFAULT_OVERWRITE",
    "DEFAULT_SKIP_EXISTING",
    "SUPPORTED_EXTENSIONS",
    "TEXT_EXTENSIONS",
    "CompletionCallback",
    "ConversionResult",
    "ProgressCallback",
    "convert_csv",
    "convert_doc",
    "convert_docx",
    "convert_file",
    "convert_odt",
    "convert_pdf_or_ebook",
    "convert_ppt",
    "convert_pptx",
    "convert_txt_or_md",
    "convert_xls",
    "convert_xlsx",
    "download_google_url",
    "extract_file_id",
    "get_conversion_estimate",
    "get_conversion_estimate_seconds",
    "is_google_drive_url",
    "mathml_to_latex",
    "omml_to_latex",
    "render_chart_svg",
    "render_table_regions",
    "to_markdown",
    "IPCCoordinator",
    "try_delegate_to_coordinator",
    "build_export_url",
    "fetch_google_title",
    "sanitize_filename",
    "get_google_file_info",
]
