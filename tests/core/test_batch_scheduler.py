from __future__ import annotations

import argparse
from collections.abc import Generator
from typing import Any
from pathlib import Path
import threading
import time
from typing import cast

import pytest

import hammerdown.batch as batch_module
from hammerdown.core.job import ConversionJob, PreparedConversion
from hammerdown.core.output import OutputStaging
from hammerdown.core.scheduler import BatchScheduler, classify_format, create_scheduler, should_use_concurrent_scheduler


def _job(root: Path, name: str, index: int) -> ConversionJob:
    source = root / name
    return ConversionJob(
        source=source,
        output_path=root / f"{name}.md",
        resource_dir=root,
        input_index=index,
    )


def _prepared(job: ConversionJob, staging: OutputStaging | None = None) -> PreparedConversion:
    return PreparedConversion(
        job=job,
        source=job.source,
        output_path=job.output_path,
        staging=staging,
    )


def _staged_prepared(job: ConversionJob) -> PreparedConversion:
    staging = OutputStaging.create(job.resource_dir.parent, prefix=".batch-scheduler-test-")
    staged_markdown = staging.path / job.output_path.name
    staged_markdown.write_text(f"converted {job.source.name}\n", encoding="utf-8")
    return PreparedConversion(
        job=job,
        source=job.source,
        output_path=job.output_path,
        staged_markdown=staged_markdown,
        staging=staging,
    )


def _batch_namespace(files: list[str]) -> argparse.Namespace:
    return argparse.Namespace(
        files=files, include=[], exclude=[], overwrite=False, skip_existing=False,
        output_dir=None, merge=None, merge_auto=False, tree=False, dir_struct=False,
        all_formats=False, stdout=False, confirm=False, include_gitignored=False,
        coordinator=False, context_worker=False, right_click=False, tokens=False,
        report_time=False,
    )


def test_heavy_and_legacy_jobs_obey_bounded_concurrency(tmp_path: Path) -> None:
    jobs = [
        _job(tmp_path, f"heavy-{index}.docx", index)
        for index in range(4)
    ] + [
        _job(tmp_path, f"legacy-{index}.doc", index + 4)
        for index in range(4)
    ]
    lock = threading.Lock()
    active = {"heavy": 0, "legacy": 0}
    observed = {"heavy": 0, "legacy": 0}
    started = {"heavy": 0, "legacy": 0}

    def prepare(job: ConversionJob, **_kwargs: object) -> PreparedConversion:
        category = "legacy" if job.source.suffix == ".doc" else "heavy"
        with lock:
            active[category] += 1
            started[category] += 1
            observed[category] = max(observed[category], active[category])
        time.sleep(0.03)
        with lock:
            active[category] -= 1
        return _prepared(job)

    scheduler = BatchScheduler(
        max_workers=4,
        heavy_limit=2,
        legacy_limit=1,
        prepare_fn=prepare,
    )

    results = scheduler.run(jobs)

    assert len(results) == len(jobs)
    assert 1 < observed["heavy"] <= 2
    assert observed["legacy"] == 1
    assert scheduler.max_concurrency_observed <= 4



def test_text_jobs_do_not_consume_heavy_permits(tmp_path: Path) -> None:
    jobs = [
        _job(tmp_path, "heavy.pdf", 0),
        _job(tmp_path, "notes.txt", 1),
    ]
    heavy_started = threading.Event()
    text_started = threading.Event()

    def prepare(job: ConversionJob, **_kwargs: object) -> PreparedConversion:
        if job.source.suffix == ".pdf":
            heavy_started.set()
            assert text_started.wait(timeout=2)
        else:
            assert heavy_started.wait(timeout=2)
            text_started.set()
        return _prepared(job)

    scheduler = BatchScheduler(
        max_workers=2,
        in_flight_limit=2,
        heavy_limit=1,
        prepare_fn=prepare,
    )

    results = scheduler.run(jobs)

    assert len(results) == 2
    assert [result.status for result in results] == ["committed", "committed"]
    assert scheduler.max_concurrency_observed == 2
    assert scheduler.committed_order == jobs


def test_results_and_commits_keep_input_order_when_completion_differs(tmp_path: Path) -> None:
    jobs = [_job(tmp_path, f"job-{index}.pdf", index) for index in range(3)]
    finished: list[int] = []
    finish_lock = threading.Lock()

    def prepare(job: ConversionJob, **_kwargs: object) -> PreparedConversion:
        delays = {0: 0.06, 1: 0.03, 2: 0.0}
        time.sleep(delays[job.input_index or 0])
        with finish_lock:
            finished.append(job.input_index or 0)
        return _prepared(job)

    scheduler = BatchScheduler(
        max_workers=3,
        in_flight_limit=3,
        heavy_limit=3,
        pdf_limit=3,
        prepare_fn=prepare,
    )

    results = scheduler.run(jobs)

    assert finished == [2, 1, 0]
    assert [result.job.input_index for result in results] == [0, 1, 2]
    assert scheduler.committed_order == jobs
    assert [result.status for result in results] == ["committed"] * 3



def test_bounded_window_preserves_result_and_commit_order(tmp_path: Path) -> None:
    jobs = [_job(tmp_path, f"bounded-{index}.docx", index) for index in range(3)]
    second_finished = threading.Event()

    def prepare(job: ConversionJob, **_kwargs: object) -> PreparedConversion:
        index = job.input_index or 0
        if index == 0:
            assert second_finished.wait(timeout=2)
        elif index == 1:
            second_finished.set()
        return _prepared(job)

    scheduler = BatchScheduler(
        max_workers=3,
        in_flight_limit=2,
        heavy_limit=3,
        prepare_fn=prepare,
    )

    results = scheduler.run(jobs)

    assert [result.job.input_index for result in results] == [0, 1, 2]
    assert scheduler.committed_order == jobs
    assert scheduler.max_in_flight_observed == 2
    assert scheduler.max_active_prepared_observed <= 2


def test_closing_schedule_aborts_all_prepared_staging(tmp_path: Path) -> None:
    jobs = [_job(tmp_path, f"job-{index}.docx", index) for index in range(5)]
    created: list[OutputStaging] = []
    all_prepared = threading.Event()
    lock = threading.Lock()

    def prepare(job: ConversionJob, **_kwargs: object) -> PreparedConversion:
        staging = OutputStaging.create(tmp_path, prefix=f".scheduler-{job.input_index}-")
        (staging.path / "partial.md").write_text("partial", encoding="utf-8")
        with lock:
            created.append(staging)
            if len(created) == 2:
                all_prepared.set()
        return _prepared(job, staging)

    scheduler = BatchScheduler(
        max_workers=3,
        in_flight_limit=2,
        heavy_limit=3,
        prepare_fn=prepare,
    )
    scheduled = cast(Generator[PreparedConversion, None, None], scheduler.schedule(jobs))

    first = next(scheduled)
    assert first.status == "committed"
    assert all_prepared.wait(timeout=2)

    scheduled.close()

    assert scheduler.is_cancelled
    assert scheduler.active_prepared_count == 0
    assert len(created) == 2
    assert scheduler.max_in_flight_observed == 2
    assert scheduler.max_active_prepared_observed <= 2
    assert scheduler.committed_order == [jobs[0]]
    assert all(not staging.path.exists() for staging in created)


def test_scheduler_propagates_keyboard_interrupt_and_cleans_prepared_staging(tmp_path: Path) -> None:
    jobs = [_job(tmp_path, f"job-{index}.docx", index) for index in range(2)]
    staging_created = threading.Event()
    staging_paths: list[Path] = []

    def prepare(job: ConversionJob, **_kwargs: object) -> PreparedConversion:
        if job.input_index == 0:
            assert staging_created.wait(timeout=30)
            raise KeyboardInterrupt
        staging = OutputStaging.create(tmp_path, prefix=".scheduler-ready-")
        staging_paths.append(staging.path)
        staging_created.set()
        return _prepared(job, staging)

    scheduler = BatchScheduler(max_workers=2, heavy_limit=2, prepare_fn=prepare)

    with pytest.raises(KeyboardInterrupt):
        scheduler.run(jobs)

    assert scheduler.is_cancelled
    assert scheduler.active_prepared_count == 0
    assert staging_paths and all(not path.exists() for path in staging_paths)


@pytest.mark.parametrize("mode", ["dir_struct", "stdout"])
def test_special_modes_use_sequential_scheduler(mode: str) -> None:
    assert not should_use_concurrent_scheduler(**{mode: True})
    scheduler = create_scheduler(
        merge=mode == "merge",
        tree=mode == "tree",
        dir_struct=mode == "dir_struct",
        stdout=mode == "stdout",
    )
    assert scheduler.sequential
    assert scheduler.max_workers == 1
    assert scheduler.heavy_limit == 1
    assert scheduler.legacy_limit == 1
    assert scheduler.in_flight_limit == 1


@pytest.mark.parametrize("mode", ["merge", "tree"])
def test_merge_and_tree_use_concurrent_scheduler(mode: str) -> None:
    assert should_use_concurrent_scheduler(**{mode: True})
    scheduler = create_scheduler(
        merge=mode == "merge",
        tree=mode == "tree",
    )
    assert not scheduler.sequential
    assert scheduler.max_workers >= 1


def test_ordinary_mode_uses_concurrent_scheduler() -> None:
    assert should_use_concurrent_scheduler()
    scheduler = create_scheduler(max_workers=3, heavy_limit=2, legacy_limit=2)
    assert not scheduler.sequential
    assert scheduler.max_workers == 3
    assert scheduler.heavy_limit == 2
    assert scheduler.legacy_limit == 2
    assert scheduler.in_flight_limit == 2


def test_pdf_jobs_use_a_separate_default_permit(tmp_path: Path) -> None:
    jobs = [_job(tmp_path, f"document-{index}.pdf", index) for index in range(3)]
    lock = threading.Lock()
    active = 0
    observed = 0

    def prepare(job: ConversionJob, **_kwargs: object) -> PreparedConversion:
        nonlocal active, observed
        with lock:
            active += 1
            observed = max(observed, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return _prepared(job)

    scheduler = BatchScheduler(
        max_workers=3,
        in_flight_limit=3,
        heavy_limit=3,
        prepare_fn=prepare,
    )

    assert scheduler.pdf_limit == 1
    results = scheduler.run(jobs)

    assert len(results) == 3
    assert observed == 1


def test_non_pdf_heavy_jobs_are_not_serialized_by_pdf_permit(tmp_path: Path) -> None:
    jobs = [
        _job(tmp_path, "document.docx", 0),
        _job(tmp_path, "table.xlsx", 1),
        _job(tmp_path, "notes.odt", 2),
    ]
    started = threading.Barrier(3)
    lock = threading.Lock()
    active = 0
    observed = 0

    def prepare(job: ConversionJob, **_kwargs: object) -> PreparedConversion:
        nonlocal active, observed
        with lock:
            active += 1
            observed = max(observed, active)
        try:
            started.wait(timeout=2)
        finally:
            with lock:
                active -= 1
        return _prepared(job)

    scheduler = BatchScheduler(
        max_workers=3,
        in_flight_limit=3,
        heavy_limit=3,
        prepare_fn=prepare,
    )

    results = scheduler.run(jobs)

    assert len(results) == 3
    assert observed == 3


def test_pdf_limit_still_respects_heavy_limit(tmp_path: Path) -> None:
    jobs = [
        _job(tmp_path, "document-0.pdf", 0),
        _job(tmp_path, "document-1.pdf", 1),
        _job(tmp_path, "document-2.docx", 2),
    ]
    lock = threading.Lock()
    active = 0
    observed = 0

    def prepare(job: ConversionJob, **_kwargs: object) -> PreparedConversion:
        nonlocal active, observed
        with lock:
            active += 1
            observed = max(observed, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return _prepared(job)

    scheduler = BatchScheduler(
        max_workers=3,
        in_flight_limit=3,
        heavy_limit=2,
        prepare_fn=prepare,
    )

    scheduler.run(jobs)

    assert observed <= 2


def test_prepare_exception_does_not_cancel_following_jobs_when_disabled(tmp_path: Path) -> None:
    jobs = [_job(tmp_path, "broken.docx", 0), _job(tmp_path, "healthy.docx", 1)]

    def prepare(job: ConversionJob, **_kwargs: object) -> PreparedConversion:
        if job.input_index == 0:
            raise RuntimeError("prepare failed")
        return _prepared(job)

    scheduler = BatchScheduler(
        max_workers=2,
        in_flight_limit=2,
        heavy_limit=2,
        cancel_on_error=False,
        prepare_fn=prepare,
    )

    results = scheduler.run(jobs)

    assert [result.status for result in results] == ["failed", "committed"]
    assert scheduler.committed_order == [jobs[1]]


def test_failed_commit_is_not_reported_as_committed(tmp_path: Path) -> None:
    jobs = [_job(tmp_path, "good.docx", 0), _job(tmp_path, "commit-fails.docx", 1)]

    def prepare(job: ConversionJob, **_kwargs: object) -> PreparedConversion:
        prepared = _prepared(job)
        if job.input_index == 1:
            def fail_commit() -> PreparedConversion:
                prepared.status = "failed"
                prepared.error = "commit failed"
                return prepared

            prepared.commit = fail_commit  # type: ignore[method-assign]
        return prepared

    scheduler = BatchScheduler(
        max_workers=2,
        in_flight_limit=2,
        heavy_limit=2,
        prepare_fn=prepare,
    )

    results = scheduler.run(jobs)

    assert [result.status for result in results] == ["committed", "failed"]
    assert scheduler.committed_order == [jobs[0]]


def test_pdf_like_extensions_share_pdf_permit_with_non_pdf_heavy_jobs(tmp_path: Path) -> None:
    extensions = [".pdf", ".epub", ".mobi", ".fb2", ".xps"]
    assert all(classify_format(tmp_path / f"document{extension}") == "heavy" for extension in extensions)
    jobs = [_job(tmp_path, f"document{extension}", index) for index, extension in enumerate(extensions)]
    jobs.append(_job(tmp_path, "regular.docx", len(jobs)))
    lock = threading.Lock()
    active_pdf = 0
    max_active_pdf = 0
    regular_started = threading.Event()

    def prepare(job: ConversionJob, **_kwargs: object) -> PreparedConversion:
        nonlocal active_pdf, max_active_pdf
        if job.source.suffix.lower() in extensions:
            with lock:
                active_pdf += 1
                max_active_pdf = max(max_active_pdf, active_pdf)
            try:
                assert regular_started.wait(timeout=2)
            finally:
                with lock:
                    active_pdf -= 1
        else:
            regular_started.set()
        return _prepared(job)

    scheduler = BatchScheduler(
        max_workers=6,
        in_flight_limit=6,
        heavy_limit=2,
        pdf_limit=1,
        prepare_fn=prepare,
    )

    results = scheduler.run(jobs)

    assert len(results) == len(jobs)
    assert max_active_pdf == 1
    assert results[-1].status == "committed"


def test_pdf_waiters_do_not_hold_heavy_permits_and_starve_non_pdf(tmp_path: Path) -> None:
    jobs = [
        _job(tmp_path, "first.pdf", 0),
        _job(tmp_path, "second.pdf", 1),
        _job(tmp_path, "regular.docx", 2),
    ]
    regular_started = threading.Event()

    def prepare(job: ConversionJob, **_kwargs: object) -> PreparedConversion:
        if job.source.suffix == ".pdf":
            assert regular_started.wait(timeout=2)
        else:
            regular_started.set()
        return _prepared(job)

    scheduler = BatchScheduler(
        max_workers=3,
        in_flight_limit=3,
        heavy_limit=2,
        pdf_limit=1,
        prepare_fn=prepare,
    )

    results = scheduler.run(jobs)

    assert [result.status for result in results] == ["committed"] * 3


def test_batch_mixed_pdf_and_office_jobs_commit_in_input_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sources = [
        tmp_path / "slow.pdf",
        tmp_path / "fast.docx",
        tmp_path / "medium.epub",
        tmp_path / "notes.txt",
    ]
    for source in sources:
        source.write_bytes(b"input")
    delays = {".pdf": 0.06, ".docx": 0.0, ".epub": 0.03, ".txt": 0.0}
    events: list[str] = []

    def prepare(job: ConversionJob, **_kwargs: object) -> PreparedConversion:
        time.sleep(delays[job.source.suffix])
        events.append(job.source.name)
        return _staged_prepared(job)

    created_schedulers: list[BatchScheduler] = []
    real_factory = create_scheduler

    def factory(**kwargs: Any) -> BatchScheduler:
        scheduler = real_factory(**kwargs)
        created_schedulers.append(scheduler)
        return scheduler

    monkeypatch.setattr(batch_module, "create_scheduler", factory)
    monkeypatch.setattr(batch_module, "_prepare_conversion", lambda job, **_kwargs: prepare(job))
    args = _batch_namespace([str(source) for source in sources])

    assert batch_module.run_batch(args) == 0
    assert events == ["fast.docx", "notes.txt", "medium.epub", "slow.pdf"]
    assert len(created_schedulers) == 1
    assert [job.source.name for job in created_schedulers[0].committed_order] == [
        "fast.docx", "medium.epub", "notes.txt", "slow.pdf"
    ]
    assert all(batch_module.get_output_path(source).is_file() for source in sources)


def test_batch_ebook_extensions_are_scheduled_as_pdf_like(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    extensions = [".pdf", ".epub", ".mobi", ".fb2", ".xps"]
    sources = [tmp_path / f"document{extension}" for extension in extensions]
    for source in sources:
        source.write_bytes(b"input")
    lock = threading.Lock()
    active = 0
    observed = 0

    def prepare(job: ConversionJob, **_kwargs: object) -> PreparedConversion:
        nonlocal active, observed
        with lock:
            active += 1
            observed = max(observed, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return _staged_prepared(job)

    monkeypatch.setattr(batch_module, "_prepare_conversion", prepare)
    args = _batch_namespace([str(source) for source in sources])

    assert batch_module.run_batch(args) == 0
    assert observed == 1
    assert all(batch_module.get_output_path(source).is_file() for source in sources)


def test_batch_commit_error_is_reported_and_does_not_stop_other_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = [tmp_path / "bad.docx", tmp_path / "good.docx"]
    for source in sources:
        source.write_bytes(b"input")

    def prepare(job: ConversionJob, **_kwargs: object) -> PreparedConversion:
        prepared = _prepared(job)
        if job.source.name == "bad.docx":
            prepared.staging = OutputStaging.create(tmp_path, prefix=".commit-error-")

            def fail_commit() -> PreparedConversion:
                prepared.status = "failed"
                prepared.error = "commit failed"
                prepared.abort()
                return prepared

            prepared.commit = fail_commit  # type: ignore[method-assign]
        if job.source.name == "good.docx":
            return _staged_prepared(job)
        return prepared

    monkeypatch.setattr(batch_module, "_prepare_conversion", prepare)
    args = _batch_namespace([str(source) for source in sources])

    assert batch_module.run_batch(args) == 1
    assert batch_module.get_output_path(sources[1]).is_file()
    assert not list(tmp_path.glob(".commit-error-*"))


def test_batch_releases_permits_and_continues_after_prepare_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = [tmp_path / "broken.docx", tmp_path / "working.docx"]
    for source in sources:
        source.write_bytes(b"input")
    working_started = threading.Event()

    def prepare(job: ConversionJob, **_kwargs: object) -> PreparedConversion:
        if job.source.name == "broken.docx":
            raise RuntimeError("parser crashed")
        working_started.set()
        return _staged_prepared(job)

    monkeypatch.setattr(batch_module, "_prepare_conversion", prepare)
    args = _batch_namespace([str(source) for source in sources])

    assert batch_module.run_batch(args) == 1
    assert working_started.is_set()
    assert batch_module.get_output_path(sources[1]).is_file()


def test_force_sequential_env_overrides_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAMMERDOWN_FORCE_SEQUENTIAL", "1")
    assert not should_use_concurrent_scheduler(merge=True)
    assert not should_use_concurrent_scheduler(tree=True)
    assert not should_use_concurrent_scheduler()
    assert create_scheduler(merge=True).sequential


def test_workers_env_forces_worker_count(monkeypatch: pytest.MonkeyPatch) -> None:
    from hammerdown.core.scheduler import calculate_optimal_workers

    monkeypatch.setenv("HAMMERDOWN_WORKERS", "3")
    assert calculate_optimal_workers() == 3
    monkeypatch.setenv("HAMMERDOWN_WORKERS", "bogus")
    assert calculate_optimal_workers() >= 1
