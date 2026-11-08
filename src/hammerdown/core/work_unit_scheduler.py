from __future__ import annotations

from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
import logging
from pathlib import Path
import os
import threading
import time
from typing import Callable, Iterator, Sequence

import psutil

from ..parsers.pdf import convert_pdf_chunk, get_pdf_page_count
from .job import ConversionJob, PreparedConversion, failed_conversion, prepare_conversion
from .output import OutputStaging
from .path_utils import get_images_dir_name
from .resources import token_count

logger = logging.getLogger("hammerdown")

PDF_EXTENSIONS = {".pdf", ".epub", ".mobi", ".fb2", ".xps"}
ProgressCallback = Callable[[ConversionJob, int, int, str], None]
StartCallback = Callable[[ConversionJob], None]
CompleteCallback = Callable[[ConversionJob, PreparedConversion], None]


@dataclass
class _PdfPlan:
    job_index: int
    job: ConversionJob
    staging: OutputStaging
    chunk_paths: list[Path]
    page_count: int
    started_at: float = field(default_factory=time.monotonic)
    completed_chunks: set[int] = field(default_factory=set)
    completed_pages: int = 0
    failure: str | None = None


@dataclass(frozen=True)
class _WorkUnit:
    job_index: int
    job: ConversionJob
    plan: _PdfPlan | None = None
    chunk_index: int = -1
    pages: tuple[int, ...] = ()
    output_path: Path | None = None


class WorkUnitScheduler:
    """Bounded scheduler for atomic files and PDF page chunks."""

    def __init__(
        self,
        *,
        max_workers: int | None = None,
        in_flight_limit: int | None = None,
        heavy_limit: int | None = None,
        legacy_limit: int = 1,
        pdf_limit: int = 2,
        cancel_on_error: bool = False,
        prepare_fn: Callable[..., PreparedConversion] = prepare_conversion,
        chunk_size_pages: int = 100,
    ) -> None:
        cpu = os.cpu_count() or 4
        self.max_workers = max(1, max_workers if max_workers is not None else min(cpu, 8))
        self.in_flight_limit = max(1, in_flight_limit if in_flight_limit is not None else self.max_workers)
        self.heavy_limit = max(1, heavy_limit if heavy_limit is not None else self.max_workers)
        self.legacy_limit = max(1, legacy_limit)
        self.pdf_limit = max(1, pdf_limit)
        self.cancel_on_error = cancel_on_error
        self.prepare_fn = prepare_fn
        self.chunk_size_pages = max(1, chunk_size_pages)
        self._cancelled = threading.Event()
        self._active_prepared: dict[int, PreparedConversion] = {}
        self._lock = threading.Lock()
        self.max_in_flight_observed = 0
        self.max_concurrency_observed = 0
        self._active_running = 0
        self.committed_order: list[ConversionJob] = []

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def active_prepared_count(self) -> int:
        with self._lock:
            return len(self._active_prepared)

    @property
    def max_active_prepared_observed(self) -> int:
        return 0

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            prepared = list(self._active_prepared.values())
            self._active_prepared.clear()
        for item in prepared:
            item.abort()

    def _plan(self, jobs: Sequence[ConversionJob]) -> tuple[list[_WorkUnit], dict[int, PreparedConversion]]:
        parents: list[list[_WorkUnit]] = []
        immediate: dict[int, PreparedConversion] = {}
        for position, job in enumerate(jobs):
            key = position
            if job.skip_existing and job.output_path.is_dir():
                immediate[key] = failed_conversion(job, f"output path is a directory: {job.output_path}")
                parents.append([])
                continue
            if job.skip_existing and job.output_path.is_file():
                immediate[key] = PreparedConversion(job=job, source=job.source, output_path=job.output_path, status="skipped")
                parents.append([])
                continue
            if job.source.suffix.lower() not in PDF_EXTENSIONS:
                parents.append([_WorkUnit(job_index=position, job=job)])
                continue
            try:
                page_count = get_pdf_page_count(str(job.source))
            except Exception as exc:
                immediate[key] = failed_conversion(job, f"failed to inspect {job.source.name}: {exc}")
                parents.append([])
                continue
            if page_count <= 1:
                parents.append([_WorkUnit(job_index=position, job=job)])
                continue
            staging = OutputStaging.create(job.resource_dir.parent, prefix=f".hammerdown-{job.source.stem}-pdf-units-")
            chunk_count = (page_count + self.chunk_size_pages - 1) // self.chunk_size_pages
            plan = _PdfPlan(
                job_index=position,
                job=job,
                staging=staging,
                page_count=page_count,
                chunk_paths=[staging.path / f"chunk-{index:05d}.md" for index in range(chunk_count)],
            )
            parents.append([
                _WorkUnit(
                    job_index=position,
                    job=job,
                    plan=plan,
                    chunk_index=index,
                    pages=tuple(range(start, min(start + self.chunk_size_pages, page_count))),
                    output_path=plan.chunk_paths[index],
                )
                for index, start in enumerate(range(0, page_count, self.chunk_size_pages))
            ])

        units: list[_WorkUnit] = []
        round_index = 0
        while True:
            added = False
            for parent in parents:
                if round_index < len(parent):
                    units.append(parent[round_index])
                    added = True
            if not added:
                return units, immediate
            round_index += 1

    @staticmethod
    def _category(unit: _WorkUnit) -> str:
        suffix = unit.job.source.suffix.lower()
        if suffix in PDF_EXTENSIONS:
            return "pdf"
        if suffix in {".doc", ".xls", ".ppt"}:
            return "legacy"
        return "heavy"

    def _execute(self, unit: _WorkUnit, on_progress: ProgressCallback | None) -> tuple[_WorkUnit, PreparedConversion | None, int, str | None]:
        if self._cancelled.is_set():
            return unit, None, 0, "cancelled"
        with self._lock:
            self._active_running += 1
            self.max_concurrency_observed = max(self.max_concurrency_observed, self._active_running)
        try:
            if unit.plan is None:
                prepared = self.prepare_fn(
                    unit.job,
                    progress_callback=None if on_progress is None else lambda current, total, label: on_progress(unit.job, current, total, label),
                )
                return unit, prepared, 0, None
            assert unit.output_path is not None
            warnings = convert_pdf_chunk(str(unit.job.source), list(unit.pages), str(unit.output_path))
            return unit, None, warnings, None
        except MemoryError:
            return unit, None, 0, "MemoryError: System ran out of memory during conversion"
        except Exception as exc:
            return unit, None, 0, str(exc)
        finally:
            with self._lock:
                self._active_running -= 1

    def _assemble(self, plan: _PdfPlan) -> PreparedConversion:
        if plan.failure is not None:
            plan.staging.cleanup()
            return failed_conversion(plan.job, f"failed to convert {plan.job.source.name}: {plan.failure}")
        try:
            text = "".join(path.read_text(encoding="utf-8") for path in plan.chunk_paths)
            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            cleaned = "\n".join(line.rstrip() for line in normalized.split("\n")).rstrip() + "\n"
            staged = plan.staging.path / plan.job.output_path.name
            staged.write_text(cleaned, encoding="utf-8", newline="\n")
            asset_dir = plan.staging.path / get_images_dir_name(plan.job.source)
            return PreparedConversion(
                job=plan.job,
                source=plan.job.source,
                output_path=plan.job.output_path,
                staged_markdown=staged,
                staged_assets=asset_dir if asset_dir.is_dir() else None,
                tokens=token_count(cleaned),
                duration=time.monotonic() - plan.started_at,
                staging=plan.staging,
            )
        except Exception as exc:
            plan.staging.cleanup()
            return failed_conversion(plan.job, f"failed to assemble {plan.job.source.name}: {exc}")

    def schedule(
        self,
        jobs: Sequence[ConversionJob],
        *,
        on_start: StartCallback | None = None,
        on_progress: ProgressCallback | None = None,
        on_complete: CompleteCallback | None = None,
        auto_commit: bool = True,
    ) -> Iterator[PreparedConversion]:
        if not jobs:
            return
        units, immediate = self._plan(jobs)
        results: dict[int, PreparedConversion] = {}
        queues: dict[str, deque[_WorkUnit]] = {"pdf": deque(), "legacy": deque(), "heavy": deque()}
        for unit in units:
            queues[self._category(unit)].append(unit)
        active: dict[Future[tuple[_WorkUnit, PreparedConversion | None, int, str | None]], _WorkUnit] = {}
        active_counts = {"pdf": 0, "legacy": 0, "heavy": 0}
        started: set[int] = set()
        executor = ThreadPoolExecutor(max_workers=self.max_workers)

        def dispatch() -> None:
            # Dynamic RAM Safety Guard: pause dispatch if available RAM is dangerously low (< 500 MB)
            available_mb = psutil.virtual_memory().available // (1024 * 1024)
            if available_mb < 500 and len(active) > 0:
                logger.warning("Low available memory (%d MB). Throttling dispatch...", available_mb)
                return

            while len(active) < min(self.max_workers, self.in_flight_limit):
                selected: _WorkUnit | None = None
                for category in ("pdf", "heavy", "legacy"):
                    if not queues[category]:
                        continue
                    limit = self.pdf_limit if category == "pdf" else self.legacy_limit if category == "legacy" else self.heavy_limit
                    if active_counts[category] < limit:
                        selected = queues[category].popleft()
                        break
                if selected is None:
                    return
                key = selected.job_index
                if key not in started and on_start is not None:
                    on_start(selected.job)
                    started.add(key)
                future = executor.submit(self._execute, selected, on_progress)
                active[future] = selected
                active_counts[self._category(selected)] += 1
                self.max_in_flight_observed = max(self.max_in_flight_observed, len(active))

        try:
            for position, job in enumerate(jobs):
                key = position
                if key not in immediate:
                    while key not in results:
                        dispatch()
                        if not active:
                            results[key] = failed_conversion(job, "scheduler produced no result")
                            break
                        done, _ = wait(tuple(active), return_when=FIRST_COMPLETED)
                        for future in done:
                            unit = active.pop(future)
                            active_counts[self._category(unit)] -= 1
                            completed, prepared, _warnings, error = future.result()
                            
                            # Hard Fallback: Reduce limits if MemoryError occurred
                            if error and "MemoryError" in error:
                                logger.error("Memory error caught. Falling back to safe sequential limits.")
                                self.max_workers = 1
                                self.in_flight_limit = 1
                                self.pdf_limit = 1
                                self.heavy_limit = 1

                            unit_key = completed.job_index
                            if completed.plan is None:
                                results[unit_key] = prepared or failed_conversion(completed.job, f"failed to convert {completed.job.source.name}: {error or 'unknown error'}")
                                if self.cancel_on_error and not results[unit_key].success:
                                    self._cancelled.set()
                            else:
                                plan = completed.plan
                                plan.completed_chunks.add(completed.chunk_index)
                                plan.completed_pages += len(completed.pages)
                                if error is not None:
                                    plan.failure = error
                                    if self.cancel_on_error:
                                        self._cancelled.set()
                                if on_progress is not None:
                                    on_progress(plan.job, plan.completed_pages, plan.page_count, "pages")
                                if len(plan.completed_chunks) == len(plan.chunk_paths):
                                    results[unit_key] = self._assemble(plan)
                                    if self.cancel_on_error and not results[unit_key].success:
                                        self._cancelled.set()
                        dispatch()
                if key in immediate:
                    result = immediate[key]
                else:
                    result = results.pop(key)
                
                if auto_commit and result.status == "prepared":
                    result = result.commit()
                
                if result.status == "committed":
                    self.committed_order.append(job)
                
                if on_complete is not None:
                    on_complete(job, result)
                yield result
        finally:
            self._cancelled.set()
            executor.shutdown(wait=True, cancel_futures=True)
            self.cancel()
            for parent in units:
                if parent.plan is not None and parent.plan.staging.path.exists():
                    parent.plan.staging.cleanup()

    def run(
        self,
        jobs: Sequence[ConversionJob],
        *,
        on_start: StartCallback | None = None,
        on_progress: ProgressCallback | None = None,
        on_complete: CompleteCallback | None = None,
    ) -> list[PreparedConversion]:
        return list(
            self.schedule(
                jobs,
                on_start=on_start,
                on_progress=on_progress,
                on_complete=on_complete,
            )
        )


__all__ = ["WorkUnitScheduler"]
