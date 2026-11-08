from __future__ import annotations
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
import logging
import os
from pathlib import Path
import threading
from typing import Callable, Iterator, Literal, Sequence, cast
import psutil

from .job import ConversionJob, PreparedConversion, failed_conversion, prepare_conversion
from .work_unit_scheduler import WorkUnitScheduler

logger = logging.getLogger("hammerdown")

FormatCategory = Literal["heavy", "legacy", "text"]
PDF_EXTENSIONS = {".pdf", ".epub", ".mobi", ".fb2", ".xps"}

ProgressCallback = Callable[[ConversionJob, int, int, str], None]
StartCallback = Callable[[ConversionJob], None]
CompleteCallback = Callable[[ConversionJob, PreparedConversion], None]

def calculate_optimal_workers(
    mb_per_worker: int = 300,
    system_reserve_mb: int = 700
) -> int:
    """Calculate the optimal number of workers based on CPU and available RAM."""
    cpu_limit = min(os.cpu_count() or 4, 6)
    available_mb = psutil.virtual_memory().available // (1024 * 1024)
    ram_limit = max(1, (available_mb - system_reserve_mb) // mb_per_worker)
    return min(cpu_limit, ram_limit)

def classify_format(job_or_path: ConversionJob | Path | str) -> FormatCategory:
    source = job_or_path.source if isinstance(job_or_path, ConversionJob) else Path(job_or_path)
    ext = source.suffix.lower()
    if ext in {".doc", ".xls", ".ppt"}:
        return "legacy"
    if ext in {".txt", ".md", ".log", ".csv", ".html", ".htm"}:
        return "text"
    return "heavy"


def should_use_concurrent_scheduler(
    *,
    merge: bool = False,
    tree: bool = False,
    dir_struct: bool = False,
    stdout: bool = False,
    use_work_units: bool = False,
) -> bool:
    if dir_struct or stdout:
        return False
    return True


class _CancelledException(BaseException):
    pass


class BatchScheduler:
    def __init__(
        self,
        *,
        max_workers: int | None = None,
        in_flight_limit: int | None = None,
        heavy_limit: int | None = None,
        pdf_limit: int = 1,
        legacy_limit: int = 1,
        cancel_on_error: bool = False,
        sequential: bool = False,
        prepare_fn: Callable[..., PreparedConversion] = prepare_conversion,
    ) -> None:
        cpu = os.cpu_count() or 4
        self.max_workers = 1 if sequential else max(1, max_workers if max_workers is not None else cpu)
        self.in_flight_limit = 1 if sequential else max(
            1, in_flight_limit if in_flight_limit is not None else min(self.max_workers, 2)
        )
        self.heavy_limit = 1 if sequential else max(1, heavy_limit if heavy_limit is not None else min(self.max_workers, cpu))
        self.pdf_limit = 1 if sequential else max(1, pdf_limit)
        self.legacy_limit = 1 if sequential else max(1, legacy_limit)
        self.cancel_on_error = cancel_on_error
        self.sequential = sequential
        self.prepare_fn = prepare_fn
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._active_prepared: dict[int, PreparedConversion] = {}
        self._max_active_prepared_observed = 0
        self.max_in_flight_observed = 0
        self._permit_condition = threading.Condition(self._lock)
        self._active_heavy_permits = 0
        self._active_pdf_permits = 0
        self._active_legacy_permits = 0
        self._active_running: int = 0
        self.max_concurrency_observed: int = 0
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
        with self._lock:
            return self._max_active_prepared_observed

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            prepared_items = list(self._active_prepared.values())
            self._active_prepared.clear()
        with self._permit_condition:
            self._permit_condition.notify_all()
        for prepared in prepared_items:
            try:
                prepared.abort()
            except Exception as exc:
                logger.warning("Failed to abort prepared job during cancellation: %s", exc)

    @contextmanager
    def _acquire_permits(self, job: ConversionJob):
        category = classify_format(job)
        needs_heavy = category in {"heavy", "legacy"}
        needs_pdf = category == "heavy" and job.source.suffix.lower() in PDF_EXTENSIONS
        needs_legacy = category == "legacy"
        with self._permit_condition:
            while not self._cancelled.is_set() and (
                (needs_heavy and self._active_heavy_permits >= self.heavy_limit)
                or (needs_pdf and self._active_pdf_permits >= self.pdf_limit)
                or (needs_legacy and self._active_legacy_permits >= self.legacy_limit)
            ):
                self._permit_condition.wait(timeout=0.05)
            if self._cancelled.is_set():
                raise _CancelledException()
            if needs_heavy:
                self._active_heavy_permits += 1
            if needs_pdf:
                self._active_pdf_permits += 1
            if needs_legacy:
                self._active_legacy_permits += 1
        try:
            yield
        finally:
            with self._permit_condition:
                if needs_pdf:
                    self._active_pdf_permits -= 1
                if needs_heavy:
                    self._active_heavy_permits -= 1
                if needs_legacy:
                    self._active_legacy_permits -= 1
                self._permit_condition.notify_all()

    def _execute_job(
        self,
        job: ConversionJob,
        on_start: StartCallback | None,
        on_progress: ProgressCallback | None,
    ) -> PreparedConversion:
        if self._cancelled.is_set():
            return failed_conversion(job, "cancelled")

        def progress_cb(current: int, total: int, unit: str = "pages") -> None:
            if on_progress is not None and not self._cancelled.is_set():
                on_progress(job, current, total, unit)

        try:
            with self._acquire_permits(job):
                if self._cancelled.is_set():
                    return failed_conversion(job, "cancelled")
                with self._lock:
                    self._active_running += 1
                    if self._active_running > self.max_concurrency_observed:
                        self.max_concurrency_observed = self._active_running
                try:
                    if on_start is not None and not self._cancelled.is_set():
                        on_start(job)
                    prepared = self.prepare_fn(job, progress_callback=progress_cb)
                finally:
                    with self._lock:
                        self._active_running -= 1
                with self._lock:
                    if self._cancelled.is_set():
                        prepared.abort()
                        return prepared
                    self._active_prepared[id(prepared)] = prepared
                    self._max_active_prepared_observed = max(
                        self._max_active_prepared_observed, len(self._active_prepared)
                    )
                return prepared
        except _CancelledException:
            return failed_conversion(job, "cancelled")
        except KeyboardInterrupt:
            self.cancel()
            raise
        except Exception as exc:
            if self.cancel_on_error:
                self.cancel()
            raise

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
        if self.sequential:
            yield from self._schedule_sequential(
                jobs,
                on_start=on_start,
                on_progress=on_progress,
                on_complete=on_complete,
                auto_commit=auto_commit,
            )
            return
        executor = ThreadPoolExecutor(max_workers=self.max_workers)
        futures: deque[tuple[ConversionJob, Future[PreparedConversion]]] = deque()
        job_iterator = iter(jobs)

        def fill_window() -> None:
            while len(futures) < self.in_flight_limit and not self._cancelled.is_set():
                try:
                    job = next(job_iterator)
                except StopIteration:
                    return
                future = executor.submit(self._execute_job, job, on_start, on_progress)
                futures.append((job, future))
                self.max_in_flight_observed = max(self.max_in_flight_observed, len(futures))

        try:
            while True:
                fill_window()
                if not futures or self._cancelled.is_set():
                    break
                job, future = futures[0]
                try:
                    prepared = future.result()
                except KeyboardInterrupt:
                    self.cancel()
                    raise
                except Exception as exc:
                    if self.cancel_on_error:
                        self.cancel()
                        raise
                    prepared = failed_conversion(job, f"failed to convert {job.source.name}: {exc}")
                futures.popleft()
                with self._lock:
                    self._active_prepared.pop(id(prepared), None)
                if self._cancelled.is_set():
                    prepared.abort()
                    break
                if auto_commit and prepared.status == "prepared":
                    prepared = prepared.commit()
                if prepared.status == "committed":
                    self.committed_order.append(job)
                if on_complete is not None:
                    on_complete(job, prepared)
                yield prepared
                if self.cancel_on_error and not prepared.success:
                    self.cancel()
                    break
        except BaseException:
            self.cancel()
            raise
        finally:
            self.cancel()
            executor.shutdown(wait=False, cancel_futures=True)

    def _schedule_sequential(
        self,
        jobs: Sequence[ConversionJob],
        *,
        on_start: StartCallback | None = None,
        on_progress: ProgressCallback | None = None,
        on_complete: CompleteCallback | None = None,
        auto_commit: bool = True,
    ) -> Iterator[PreparedConversion]:
        for job in jobs:
            if self._cancelled.is_set():
                break
            def progress_cb(current: int, total: int, unit: str = "pages") -> None:
                if on_progress is not None and not self._cancelled.is_set():
                    on_progress(job, current, total, unit)
            with self._lock:
                self._active_running += 1
                if self._active_running > self.max_concurrency_observed:
                    self.max_concurrency_observed = self._active_running
            try:
                if on_start is not None and not self._cancelled.is_set():
                    on_start(job)
                prepared = self.prepare_fn(job, progress_callback=progress_cb)
            except KeyboardInterrupt:
                self.cancel()
                raise
            except Exception as exc:
                if self.cancel_on_error:
                    self.cancel()
                    raise
                prepared = failed_conversion(job, f"failed to convert {job.source.name}: {exc}")
            finally:
                with self._lock:
                    self._active_running -= 1
            if self._cancelled.is_set():
                prepared.abort()
                break
            if auto_commit and prepared.status == "prepared":
                prepared = prepared.commit()
            if prepared.status == "committed":
                self.committed_order.append(job)
            if on_complete is not None:
                on_complete(job, prepared)
            yield prepared
            if self.cancel_on_error and not prepared.success:
                self.cancel()
                break

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


def create_scheduler(
    *,
    merge: bool = False,
    tree: bool = False,
    dir_struct: bool = False,
    stdout: bool = False,
    max_workers: int | None = None,
    in_flight_limit: int | None = None,
    heavy_limit: int | None = None,
    pdf_limit: int = 1,
    legacy_limit: int = 1,
    cancel_on_error: bool = False,
    prepare_fn: Callable[..., PreparedConversion] = prepare_conversion,
    use_work_units: bool = False,
    work_unit_max_workers: int | None = None,
    work_unit_in_flight_limit: int | None = None,
    work_unit_pdf_limit: int = 2,
) -> BatchScheduler:
    sequential = not should_use_concurrent_scheduler(
        merge=merge,
        tree=tree,
        dir_struct=dir_struct,
        stdout=stdout,
    )
    if use_work_units and not sequential:
        return cast(
            BatchScheduler,
            WorkUnitScheduler(
                max_workers=work_unit_max_workers or max_workers,
                in_flight_limit=work_unit_in_flight_limit,
                heavy_limit=heavy_limit,
                pdf_limit=work_unit_pdf_limit,
                legacy_limit=legacy_limit,
                cancel_on_error=cancel_on_error,
                prepare_fn=prepare_fn,
            ),
        )
    return BatchScheduler(
        max_workers=1 if sequential else max_workers,
        in_flight_limit=1 if sequential else in_flight_limit,
        heavy_limit=1 if sequential else heavy_limit,
        pdf_limit=1 if sequential else pdf_limit,
        legacy_limit=1 if sequential else legacy_limit,
        cancel_on_error=cancel_on_error,
        sequential=sequential,
        prepare_fn=prepare_fn,
    )

__all__ = [
    "BatchScheduler",
    "FormatCategory",
    "calculate_optimal_workers",
    "classify_format",
    "create_scheduler",
    "should_use_concurrent_scheduler",
]
