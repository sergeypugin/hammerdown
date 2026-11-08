from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import sys
import time
from typing import Callable, Literal

from ..parsers import CONVERTERS
from .estimates import describe
from .formatting import format_progress_bar
from .output import OutputStaging, replace_staged_outputs
from .path_utils import get_images_dir_name
from .resources import token_count

logger_name = "hammerdown"
logger = logging.getLogger(logger_name)

ProgressCallback = Callable[[int, int, str], None]
PreparedStatus = Literal["prepared", "skipped", "committed", "failed", "aborted"]


@dataclass(frozen=True)
class ConversionJob:
    """Immutable description of one ordinary file conversion."""

    source: Path
    output_path: Path
    resource_dir: Path
    skip_existing: bool = False
    batch_mode: bool = False
    input_index: int | None = None
    category: str | None = None

    @property
    def identity(self) -> tuple[int | None, Path]:
        return self.input_index, self.source


@dataclass
class PreparedConversion:
    """Prepared output owned by one job until it is committed or aborted."""

    job: ConversionJob
    source: Path
    output_path: Path
    staged_markdown: Path | None = None
    staged_assets: Path | None = None
    images: int = 0
    tokens: int = 0
    duration: float = 0.0
    status: PreparedStatus = "prepared"
    error: str | None = None
    cleanup_error: str | None = None
    reported_output_path: Path | None = None
    staging: OutputStaging | None = None
    _started_at: float | None = field(default=None, repr=False)

    @property
    def success(self) -> bool:
        return self.status in {"prepared", "skipped", "committed"}

    def __bool__(self) -> bool:
        return self.success

    def commit(self) -> PreparedConversion:
        """Publish this job's outputs once and release its staging directory."""
        if self.status != "prepared":
            return self

        replacements: list[tuple[Path | None, Path]] = []
        if self.staged_markdown is not None:
            replacements.append((self.staged_markdown, self.output_path))
        replacements.append((self.staged_assets, self.job.resource_dir / get_images_dir_name(self.source)))

        try:
            replace_staged_outputs(replacements)
        except Exception as exc:
            self.status = "failed"
            self.error = f"failed to commit {self.source.name}: {exc}"
            self._cleanup_staging()
            self._finish_duration()
            return self

        self.status = "committed"
        self._cleanup_staging()
        self._finish_duration()
        return self

    def _finish_duration(self) -> None:
        if self._started_at is not None:
            self.duration = time.monotonic() - self._started_at
            self._started_at = None

    def abort(self) -> PreparedConversion:
        """Discard prepared outputs. Repeating the operation is safe."""
        if self.status == "prepared":
            self.status = "aborted"
        self._cleanup_staging()
        return self

    def _cleanup_staging(self) -> None:
        if self.staging is not None:
            staging = self.staging
            cleanup_error = _cleanup_staging(staging)
            self.cleanup_error = cleanup_error or self.cleanup_error
            if cleanup_error is None:
                self.staging = None


def _cleanup_staging(staging: OutputStaging) -> str | None:
    try:
        staging.cleanup()
    except Exception as exc:
        message = f"failed to clean staging {staging.path}: {exc}"
        try:
            logger.warning("%s", message)
        except Exception:
            pass
        return message
    return None


def failed_conversion(
    job: ConversionJob,
    error: str,
    *,
    output_path: Path | None = None,
    duration: float = 0.0,
    cleanup_error: str | None = None,
    staging: OutputStaging | None = None,
) -> PreparedConversion:
    return PreparedConversion(
        job=job,
        source=job.source,
        output_path=output_path or job.output_path,
        status="failed",
        error=error,
        cleanup_error=cleanup_error,
        reported_output_path=output_path,
        staging=staging,
        duration=duration,
    )


def skipped_conversion(job: ConversionJob) -> PreparedConversion:
    return PreparedConversion(
        job=job,
        source=job.source,
        output_path=job.output_path,
        status="skipped",
    )


def prepare_conversion(
    job: ConversionJob,
    progress_callback: ProgressCallback | None = None,
) -> PreparedConversion:
    """Run parser work into job-local staging without publishing final outputs."""
    source = job.source
    converter = CONVERTERS.get(source.suffix.lower())
    if not source.is_file():
        return failed_conversion(job, f"file not found: {source}")

    if converter is None:
        return failed_conversion(job, f"unsupported format: {source.suffix.lower() or '(no extension)'}")

    if job.skip_existing and job.output_path.is_dir():
        return failed_conversion(
            job,
            f"output path is a directory: {job.output_path}",
            output_path=job.output_path,
        )
    if job.skip_existing and job.output_path.is_file():
        return skipped_conversion(job)

    staging = OutputStaging.create(
        job.resource_dir.parent,
        prefix=f".hammerdown-{source.stem}-{source.suffix.lower().lstrip('.') or 'file'}-",
    )
    conversion_resource_dir = staging.path

    try:
        _, estimate_hint = describe(source)
    except KeyboardInterrupt as interruption:
        cleanup_error = _cleanup_staging(staging)
        if cleanup_error is not None:
            setattr(interruption, "cleanup_error", cleanup_error)
            setattr(interruption, "staging", staging)
        raise
    except Exception:
        cleanup_error = _cleanup_staging(staging)
        return failed_conversion(
            job,
            f"failed to convert {source.name}",
            cleanup_error=cleanup_error,
            staging=staging if cleanup_error is not None else None,
        )

    import logging

    is_tty = sys.stdout.isatty() and logging.getLogger(logger_name).isEnabledFor(logging.INFO) and not job.batch_mode
    if is_tty:
        print(f'\nProcessing "{source.name}"{estimate_hint}...\n')
        if source.suffix.lower() in {".doc", ".xls", ".ppt"}:
            sys.stdout.write("[ ] Converting via Office automation...")
            sys.stdout.flush()
            last_len = 35
        else:
            last_len = 0
    elif not job.batch_mode:
        logging.getLogger(logger_name).info("Processing %s%s...", source.name, estimate_hint)
        last_len = 0
    else:
        last_len = 0

    last_pct = -1

    def report_progress(current: int, total: int, unit: str = "pages") -> None:
        nonlocal last_len, last_pct
        if progress_callback is not None:
            progress_callback(current, total, unit)
        if total <= 0:
            return
        pct = int((current / total) * 100)
        if is_tty:
            bar = format_progress_bar(current, total, unit=unit)
            sys.stdout.write(chr(13) + bar.ljust(last_len))
            sys.stdout.flush()
            last_len = max(last_len, len(bar))
        elif progress_callback is None and pct > last_pct:
            last_pct = pct
            logging.getLogger(logger_name).info(
                "Processing %s: %d/%d %s (%d%%)...",
                source.name,
                current,
                total,
                unit,
                pct,
            )

    started_at = time.monotonic()
    try:
        markdown, saved_images = converter(
            str(source),
            str(conversion_resource_dir),
            progress_callback=report_progress,
        )
        if is_tty and last_len > 0:
            sys.stdout.write(f"\r{' ' * last_len}\r")
            sys.stdout.flush()

        if markdown is None:
            duration = time.monotonic() - started_at
            cleanup_error = _cleanup_staging(staging)
            if is_tty:
                print(f"[x] Failed to convert {source.name}")
            return failed_conversion(
                job,
                f"conversion failed for {source.name}",
                duration=duration,
                cleanup_error=cleanup_error,
                staging=staging if cleanup_error is not None else None,
            )

        normalized = markdown.replace("\r\n", "\n").replace("\r", "\n")
        cleaned = "\n".join(line.rstrip() for line in normalized.split("\n")).rstrip() + "\n"
        counted_tokens = token_count(cleaned)
        staged_markdown = conversion_resource_dir / job.output_path.name
        staged_markdown.write_text(cleaned, encoding="utf-8", newline="\n")
        staged_assets_path = conversion_resource_dir / get_images_dir_name(source)
        staged_assets = staged_assets_path if staged_assets_path.is_dir() else None
        duration = time.monotonic() - started_at

        return PreparedConversion(
            job=job,
            source=source,
            output_path=job.output_path,
            staged_markdown=staged_markdown,
            staged_assets=staged_assets,
            images=saved_images,
            tokens=counted_tokens,
            duration=duration,
            staging=staging,
            _started_at=started_at,
        )
    except KeyboardInterrupt as interruption:
        cleanup_error = _cleanup_staging(staging)
        if cleanup_error is not None:
            setattr(interruption, "cleanup_error", cleanup_error)
            setattr(interruption, "staging", staging)
        if is_tty and last_len > 0:
            sys.stdout.write(f"\r{' ' * last_len}\r")
            sys.stdout.flush()
        raise
    except Exception:
        duration = time.monotonic() - started_at
        cleanup_error = _cleanup_staging(staging)
        if is_tty:
            if last_len > 0:
                sys.stdout.write(f"\r{' ' * last_len}\r")
                sys.stdout.flush()
            print(f"[x] Failed to convert {source.name}")
        return failed_conversion(
            job,
            f"failed to convert {source.name}",
            duration=duration,
            cleanup_error=cleanup_error,
            staging=staging if cleanup_error is not None else None,
        )
