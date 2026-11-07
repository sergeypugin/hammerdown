from __future__ import annotations

import base64
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import hammerdown.core as core
import hammerdown.batch as batch
import hammerdown.core.output as output_module
import hammerdown.core.job as job_module
from hammerdown.core.job import ConversionJob, PreparedConversion, prepare_conversion


def _image_uri(value: str) -> str:
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _job(
    source: Path,
    *,
    output_dir: Path | None = None,
    skip_existing: bool = False,
    input_index: int | None = None,
) -> ConversionJob:
    target_dir = output_dir or source.parent
    return ConversionJob(
        source=source,
        output_path=core.get_output_path(source, target_dir),
        resource_dir=target_dir,
        skip_existing=skip_existing,
        input_index=input_index,
    )


def test_prepare_result_has_identity_and_publishes_only_on_commit(tmp_path: Path) -> None:
    source = tmp_path / "note.txt"
    source.write_text("prepared content\n", encoding="utf-8")
    conversion_job = _job(source, input_index=7)

    with pytest.raises(FrozenInstanceError):
        conversion_job.source = source  # type: ignore[misc]

    prepared = prepare_conversion(conversion_job)

    assert prepared.job is conversion_job
    assert conversion_job.identity == (7, source)
    assert prepared.status == "prepared"
    assert prepared.staging is not None
    assert prepared.staging.path.is_dir()
    assert not conversion_job.output_path.exists()
    assert prepared.staged_markdown is not None
    assert prepared.staged_markdown.is_file()
    assert not hasattr(prepared, "markdown")
    assert prepared.staged_markdown.read_text(encoding="utf-8") == "prepared content\n"
    assert not conversion_job.output_path.exists()

    committed = prepared.commit()

    assert committed.status == "committed"
    assert conversion_job.output_path.read_text(encoding="utf-8") == "prepared content\n"
    assert prepared.staging is None
    assert not list(tmp_path.glob(".hammerdown-note-txt-*"))
    prepared.abort()
    assert committed.status == "committed"


def test_prepare_commit_preserves_markdown_asset_output_parity(tmp_path: Path) -> None:
    source = tmp_path / "embedded.md"
    source.write_text(
        f"# title\n\n![asset]({_image_uri('asset bytes')})\n",
        encoding="utf-8",
    )
    expected = core.convert_file(source)
    expected_markdown = expected.markdown
    expected_output = expected.output_path
    assert expected_output is not None
    expected_assets = {
        path.relative_to(tmp_path / "hm_images_embedded_md"): path.read_bytes()
        for path in (tmp_path / "hm_images_embedded_md").rglob("*")
        if path.is_file()
    }
    expected_output.unlink()
    for path in (tmp_path / "hm_images_embedded_md").rglob("*"):
        if path.is_file():
            path.unlink()
    (tmp_path / "hm_images_embedded_md").rmdir()

    prepared = prepare_conversion(_job(source))
    assert prepared.staged_markdown is not None
    assert expected_markdown is not None
    assert prepared.staged_markdown.read_bytes() == expected_markdown.encode("utf-8")
    assert prepared.output_path == expected_output
    assert prepared.images == expected.images
    assert prepared.commit().success

    actual_assets = {
        path.relative_to(tmp_path / "hm_images_embedded_md"): path.read_bytes()
        for path in (tmp_path / "hm_images_embedded_md").rglob("*")
        if path.is_file()
    }
    assert prepared.output_path.read_text(encoding="utf-8") == expected_markdown
    assert actual_assets == expected_assets


def test_prepare_skip_existing_and_abort_cleanup_are_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "skip.txt"
    source.write_text("new\n", encoding="utf-8")
    target = tmp_path / "hm_skip_txt.md"
    target.write_text("existing\n", encoding="utf-8")

    skipped = prepare_conversion(_job(source, skip_existing=True))
    assert skipped.status == "skipped"
    assert skipped.output_path == target
    assert skipped.staging is None
    skipped.abort()
    assert target.read_text(encoding="utf-8") == "existing\n"

    source.write_text("prepared\n", encoding="utf-8")
    prepared = prepare_conversion(_job(source))
    staging_path = prepared.staging.path if prepared.staging is not None else None
    prepared.abort()
    prepared.abort()
    assert prepared.status == "aborted"
    assert staging_path is not None
    assert not staging_path.exists()
    assert not target.read_text(encoding="utf-8") == "prepared\n"


def test_prepare_parser_failure_cleans_job_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "broken.txt"
    source.write_text("broken\n", encoding="utf-8")
    created: list[Path] = []
    real_create = job_module.OutputStaging.create

    def record_create(parent: Path, prefix: str):
        staging = real_create(parent, prefix)
        created.append(staging.path)
        return staging

    def fail_converter(*_args: object, **_kwargs: object):
        raise RuntimeError("parser failure")

    monkeypatch.setattr(job_module.OutputStaging, "create", record_create)
    monkeypatch.setitem(job_module.CONVERTERS, ".txt", fail_converter)

    prepared = prepare_conversion(_job(source))

    assert prepared.status == "failed"
    assert prepared.error == "failed to convert broken.txt"
    assert created and not created[0].exists()
    assert not (tmp_path / "hm_broken_txt.md").exists()


def test_prepare_keyboard_interrupt_during_estimate_cleans_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "estimate-interrupted.txt"
    source.write_text("interrupted\n", encoding="utf-8")
    created: list[Path] = []
    real_create = job_module.OutputStaging.create

    def record_create(parent: Path, prefix: str):
        staging = real_create(parent, prefix)
        created.append(staging.path)
        return staging

    def interrupt_describe(_source: Path):
        raise KeyboardInterrupt

    monkeypatch.setattr(job_module.OutputStaging, "create", record_create)
    monkeypatch.setattr(job_module, "describe", interrupt_describe)

    with pytest.raises(KeyboardInterrupt):
        prepare_conversion(_job(source))

    assert created and not created[0].exists()


def test_prepare_keyboard_interrupt_cleans_staging_and_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "interrupted.txt"
    source.write_text("interrupted\n", encoding="utf-8")
    created: list[Path] = []
    real_create = job_module.OutputStaging.create

    def record_create(parent: Path, prefix: str):
        staging = real_create(parent, prefix)
        created.append(staging.path)
        return staging

    def interrupt_converter(*_args: object, **_kwargs: object):
        raise KeyboardInterrupt

    monkeypatch.setattr(job_module.OutputStaging, "create", record_create)
    monkeypatch.setitem(job_module.CONVERTERS, ".txt", interrupt_converter)

    with pytest.raises(KeyboardInterrupt):
        prepare_conversion(_job(source))

    assert created and not created[0].exists()
    assert not (tmp_path / "hm_interrupted_txt.md").exists()


def test_prepare_keyboard_interrupt_retains_staging_when_cleanup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "interrupted-cleanup.txt"
    source.write_text("interrupted\n", encoding="utf-8")
    created: list[output_module.OutputStaging] = []
    real_create = job_module.OutputStaging.create
    real_cleanup = output_module.OutputStaging.cleanup

    def record_create(parent: Path, prefix: str):
        staging = real_create(parent, prefix)
        created.append(staging)
        return staging

    def fail_cleanup(_self: output_module.OutputStaging) -> None:
        raise OSError("temporary cleanup problem")

    def interrupt_converter(*_args: object, **_kwargs: object):
        raise KeyboardInterrupt

    monkeypatch.setattr(job_module.OutputStaging, "create", record_create)
    monkeypatch.setattr(job_module.OutputStaging, "cleanup", fail_cleanup)
    monkeypatch.setitem(job_module.CONVERTERS, ".txt", interrupt_converter)

    with pytest.raises(KeyboardInterrupt) as raised:
        prepare_conversion(_job(source))

    interruption = raised.value
    assert getattr(interruption, "cleanup_error")
    assert created and getattr(interruption, "staging") is created[0]
    assert created[0].path.is_dir()

    monkeypatch.setattr(job_module.OutputStaging, "cleanup", real_cleanup)
    created[0].cleanup()
    assert not created[0].path.exists()


def test_prepare_commit_failure_cleans_staging_and_preserves_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "commit.txt"
    source.write_text("new\n", encoding="utf-8")
    target = tmp_path / "hm_commit_txt.md"
    target.write_text("old\n", encoding="utf-8")
    prepared = prepare_conversion(_job(source))
    staging_path = prepared.staging.path if prepared.staging is not None else None

    def fail_replace(_replacements: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(job_module, "replace_staged_outputs", fail_replace)
    committed = prepared.commit()

    assert committed.status == "failed"
    assert committed.error == "failed to commit commit.txt: replace failed"
    assert target.read_text(encoding="utf-8") == "old\n"
    assert staging_path is not None
    assert not staging_path.exists()
    committed.abort()


def test_batch_ordinary_path_keeps_input_index_accounting(tmp_path: Path, monkeypatch) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first\n", encoding="utf-8")
    second.write_text("second\n", encoding="utf-8")
    observed: list[tuple[int | None, str]] = []
    original_prepare = job_module.prepare_conversion

    def capture_prepare(
        conversion_job: ConversionJob,
        progress_callback=None,
    ) -> PreparedConversion:
        observed.append((conversion_job.input_index, conversion_job.source.name))
        return original_prepare(conversion_job, progress_callback=progress_callback)

    monkeypatch.setattr("hammerdown.batch._prepare_conversion", capture_prepare)

    from hammerdown.batch import convert_files

    assert convert_files([first, second]) == 0
    assert observed == [(0, "first.txt"), (1, "second.txt")]


def test_prepare_reports_progress_synchronously_without_retaining_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "progress.txt"
    source.write_text("progress\n", encoding="utf-8")
    events: list[tuple[int, int, str]] = []
    events_seen_in_converter: list[int] = []

    def converter(_source: str, _target: str, progress_callback=None):
        assert progress_callback is not None
        for current in (1, 2, 3):
            progress_callback(current, 3, "pages")
            events_seen_in_converter.append(len(events))
        return "ready", 0

    monkeypatch.setitem(job_module.CONVERTERS, ".txt", converter)
    prepared = prepare_conversion(
        _job(source),
        progress_callback=lambda current, total, unit: events.append((current, total, unit)),
    )

    assert events == [(1, 3, "pages"), (2, 3, "pages"), (3, 3, "pages")]
    assert events_seen_in_converter == [1, 2, 3]
    assert not hasattr(prepared, "progress_events")
    prepared.abort()


def test_convert_file_keeps_synchronous_progress_and_completion_callbacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "legacy.txt"
    source.write_text("legacy\n", encoding="utf-8")
    events: list[tuple[str, int]] = []

    def converter(_source: str, _target: str, progress_callback=None):
        assert progress_callback is not None
        progress_callback(1, 2, "pages")
        events.append(("converted", 1))
        progress_callback(2, 2, "pages")
        return "legacy", 0

    monkeypatch.setitem(core.CONVERTERS, ".txt", converter)
    result = core.convert_file(
        source,
        progress_callback=lambda current, _total, _unit: events.append(("progress", current)),
        completion_callback=lambda success, _duration, _images, _tokens: events.append(("complete", int(success))),
    )

    assert result.success
    assert events == [
        ("progress", 1),
        ("converted", 1),
        ("progress", 2),
        ("complete", 1),
    ]


def test_prepare_duration_excludes_describe_and_progress_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "duration.txt"
    source.write_text("duration\n", encoding="utf-8")
    clock = [100.0]

    def describe(_source: Path):
        clock[0] += 20.0
        return None, ""

    def converter(_source: str, _target: str, progress_callback=None):
        clock[0] += 3.0
        return "duration", 0

    def replace_outputs(_replacements) -> None:
        clock[0] += 7.0

    monkeypatch.setattr(job_module, "describe", describe)
    monkeypatch.setattr(job_module, "replace_staged_outputs", replace_outputs)
    monkeypatch.setattr(job_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setitem(job_module.CONVERTERS, ".txt", converter)

    prepared = prepare_conversion(_job(source))

    assert prepared.duration == 3.0
    assert prepared.commit().success
    assert prepared.duration == 10.0


def test_cleanup_failure_does_not_skip_batch_completion_or_mask_conversion_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "cleanup.txt"
    source.write_text("cleanup\n", encoding="utf-8")
    real_cleanup = job_module.OutputStaging.cleanup
    captured: list[PreparedConversion] = []
    ui_instances = []

    def cleanup_then_fail(staging) -> None:
        real_cleanup(staging)
        raise OSError("intentional cleanup failure")

    def fail_converter(*_args: object, **_kwargs: object):
        raise RuntimeError("intentional parser failure")

    class RecordingUI(batch.BatchUI):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.can_redraw = False
            self.completions: list[tuple[bool, str | float]] = []
            ui_instances.append(self)

        def complete_file(self, index, success, duration, images=0, tokens=0, info=""):
            self.completions.append((success, duration))
            super().complete_file(index, success, duration, images, tokens, info)

    original_prepare = job_module.prepare_conversion

    def capture_prepare(conversion_job, progress_callback=None):
        prepared = original_prepare(conversion_job, progress_callback=progress_callback)
        captured.append(prepared)
        return prepared

    monkeypatch.setattr(job_module.OutputStaging, "cleanup", cleanup_then_fail)
    monkeypatch.setitem(job_module.CONVERTERS, ".txt", fail_converter)
    monkeypatch.setattr(batch, "_prepare_conversion", capture_prepare)
    monkeypatch.setattr(batch, "BatchUI", RecordingUI)

    assert batch.convert_files([source]) == 1
    assert len(captured) == 1
    assert captured[0].status == "failed"
    assert captured[0].error == "failed to convert cleanup.txt"
    assert captured[0].cleanup_error is not None
    assert "intentional cleanup failure" in captured[0].cleanup_error
    assert captured[0].staging is not None
    assert len(ui_instances) == 1
    assert ui_instances[0].completions and len(ui_instances[0].completions) == 1
    assert ui_instances[0].completions[0][0] is False
    assert len(ui_instances[0].errors) == 1
    assert ui_instances[0].errors[0] == ("cleanup.txt", "failed to convert cleanup.txt")
    assert ui_instances[0].converted_count == 0


def test_batch_output_dir_commits_embedded_image_assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "embedded.md"
    source.write_text(f"# title\n\n![asset]({_image_uri('asset bytes')})\n", encoding="utf-8")
    expected_dir = tmp_path / "expected"
    output_dir = tmp_path / "output"
    expected = core.convert_file(source, target_dir=expected_dir)
    expected_output = expected.output_path
    assert expected_output is not None
    assert expected.markdown is not None
    expected_assets_dir = expected_dir / "hm_images_embedded_md"
    expected_assets = {
        path.relative_to(expected_assets_dir): path.read_bytes()
        for path in expected_assets_dir.rglob("*")
        if path.is_file()
    }
    staged_markdown: list[bytes] = []
    original_prepare = job_module.prepare_conversion

    def capture_prepare(conversion_job, progress_callback=None):
        prepared = original_prepare(conversion_job, progress_callback=progress_callback)
        assert prepared.staged_markdown is not None
        staged_markdown.append(prepared.staged_markdown.read_bytes())
        return prepared

    monkeypatch.setattr(batch, "_prepare_conversion", capture_prepare)
    monkeypatch.chdir(tmp_path)

    assert batch.convert_files([source], output_dir=output_dir) == 0

    output_path = core.get_output_path(source, output_dir)
    assets_dir = output_dir / "hm_images_embedded_md"
    actual_assets = {
        path.relative_to(assets_dir): path.read_bytes()
        for path in assets_dir.rglob("*")
        if path.is_file()
    }
    assert staged_markdown == [expected.markdown.encode("utf-8")]
    assert output_path.read_text(encoding="utf-8") == expected.markdown
    assert actual_assets == expected_assets
    assert not list(tmp_path.glob(".hammerdown-*"))


def test_batch_partial_commit_failure_rolls_back_outputs_and_counts_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "embedded.md"
    source.write_text(f"# new\n\n![asset]({_image_uri('new bytes')})\n", encoding="utf-8")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    output_path = core.get_output_path(source, output_dir)
    output_path.write_text("old markdown\n", encoding="utf-8")
    assets_dir = output_dir / "hm_images_embedded_md"
    assets_dir.mkdir()
    (assets_dir / "previous.png").write_bytes(b"old asset")
    markdown_before = output_path.read_bytes()
    assets_before = {
        path.relative_to(assets_dir): path.read_bytes()
        for path in assets_dir.rglob("*")
        if path.is_file()
    }
    real_replace = output_module.os.replace
    attempted_asset_install: list[bool] = []
    ui_instances = []

    class RecordingUI(batch.BatchUI):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.can_redraw = False
            self.completions: list[tuple[bool, str | float]] = []
            ui_instances.append(self)

        def complete_file(self, index, success, duration, images=0, tokens=0, info=""):
            self.completions.append((success, duration))
            super().complete_file(index, success, duration, images, tokens, info)

    def fail_asset_install(source_path: str | Path, target_path: str | Path) -> None:
        staged = Path(source_path)
        if (
            staged.name == assets_dir.name
            and staged.parent.name.startswith(".hammerdown-")
            and not attempted_asset_install
        ):
            attempted_asset_install.append(True)
            raise OSError("intentional asset install failure")
        real_replace(source_path, target_path)

    monkeypatch.setattr(output_module.os, "replace", fail_asset_install)
    monkeypatch.setattr(batch, "BatchUI", RecordingUI)
    monkeypatch.chdir(tmp_path)

    assert batch.convert_files([source], output_dir=output_dir) == 1

    assert attempted_asset_install == [True]
    assert output_path.read_bytes() == markdown_before
    assert {
        path.relative_to(assets_dir): path.read_bytes()
        for path in assets_dir.rglob("*")
        if path.is_file()
    } == assets_before
    assert len(ui_instances) == 1
    ui = ui_instances[0]
    assert len(ui.completions) == 1
    assert ui.completions[0][0] is False
    assert ui.converted_count == 0
    assert ui.image_count == 0
    assert ui.skipped_count == 0
    assert ui.errors == [("embedded.md", "failed to commit embedded.md: intentional asset install failure")]
    assert not list(output_dir.glob(".*.hammerdown-backup-*"))
    assert not list(tmp_path.glob(".hammerdown-*"))


def test_batch_commit_cleanup_warning_preserves_staging_for_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    import logging

    source = tmp_path / "cleanup-retry.txt"
    source.write_text("published\n", encoding="utf-8")
    captured: list[PreparedConversion] = []
    ui_instances = []
    real_cleanup = job_module.OutputStaging.cleanup
    cleanup_calls = 0

    def fail_before_cleanup(staging) -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        if cleanup_calls == 1:
            raise OSError("temporary cleanup problem")
        real_cleanup(staging)

    class RecordingUI(batch.BatchUI):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.can_redraw = False
            self.completions = []
            ui_instances.append(self)

        def complete_file(self, index, success, duration, images=0, tokens=0, info=""):
            self.completions.append((success, duration))
            super().complete_file(index, success, duration, images, tokens, info)

    original_prepare = job_module.prepare_conversion

    def capture_prepare(conversion_job, progress_callback=None):
        result = original_prepare(conversion_job, progress_callback=progress_callback)
        captured.append(result)
        return result

    monkeypatch.setattr(job_module.OutputStaging, "cleanup", fail_before_cleanup)
    monkeypatch.setattr(batch, "_prepare_conversion", capture_prepare)
    monkeypatch.setattr(batch, "BatchUI", RecordingUI)
    monkeypatch.chdir(tmp_path)

    with caplog.at_level(logging.WARNING, logger="hammerdown"):
        result = batch.convert_files([source])

    assert result == 0
    assert len(captured) == 1
    prepared = captured[0]
    assert prepared.status == "committed"
    assert prepared.cleanup_error is not None
    assert "temporary cleanup problem" in prepared.cleanup_error
    assert prepared.staging is not None
    staging_path = prepared.staging.path
    assert staging_path.is_dir()
    assert core.get_output_path(source).read_text(encoding="utf-8") == "published\n"
    assert any("Staging cleanup failed" in record.message for record in caplog.records)
    assert len(ui_instances) == 1
    assert ui_instances[0].completions and len(ui_instances[0].completions) == 1
    assert ui_instances[0].completions[0][0] is True
    assert ui_instances[0].converted_count == 1
    assert ui_instances[0].errors == []

    prepared.abort()

    assert prepared.status == "committed"
    assert prepared.staging is None
    assert not staging_path.exists()
