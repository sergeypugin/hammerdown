from __future__ import annotations

from pathlib import Path
import time

from hammerdown.core.job import ConversionJob, PreparedConversion
from hammerdown.core.work_unit_scheduler import WorkUnitScheduler


def _job(root: Path, name: str, index: int) -> ConversionJob:
    source = root / name
    source.write_bytes(b"input")
    return ConversionJob(
        source=source,
        output_path=root / f"hm_{source.stem}_{source.suffix.lstrip('.')}.md",
        resource_dir=root,
        batch_mode=True,
        input_index=index,
    )


def test_pdf_chunks_are_published_in_page_order(monkeypatch, tmp_path: Path) -> None:
    pdf_job = _job(tmp_path, "book.pdf", 0)
    monkeypatch.setattr(
        "hammerdown.core.work_unit_scheduler.get_pdf_page_count",
        lambda _path: 70,
    )

    def convert(_source: str, pages: list[int], output: str) -> int:
        time.sleep((70 - pages[0]) / 5000)
        Path(output).write_text("".join(f"page-{page}\n" for page in pages), encoding="utf-8")
        return 0

    monkeypatch.setattr("hammerdown.core.work_unit_scheduler.convert_pdf_chunk", convert)

    results = WorkUnitScheduler(
        max_workers=4,
        in_flight_limit=4,
        heavy_limit=4,
        pdf_limit=2,
    ).run([pdf_job])

    assert [result.status for result in results] == ["committed"]
    assert pdf_job.output_path.read_text(encoding="utf-8") == "".join(
        f"page-{page}\n" for page in range(70)
    )


def test_pdf_chunk_failure_does_not_publish_partial_output(monkeypatch, tmp_path: Path) -> None:
    pdf_job = _job(tmp_path, "broken.pdf", 0)
    monkeypatch.setattr(
        "hammerdown.core.work_unit_scheduler.get_pdf_page_count",
        lambda _path: 65,
    )

    def convert(_source: str, pages: list[int], output: str) -> int:
        if pages[0] == 32:
            raise RuntimeError("synthetic chunk failure")
        Path(output).write_text("ok\n", encoding="utf-8")
        return 0

    monkeypatch.setattr("hammerdown.core.work_unit_scheduler.convert_pdf_chunk", convert)

    results = WorkUnitScheduler(
        max_workers=4,
        in_flight_limit=4,
        heavy_limit=4,
        pdf_limit=2,
        chunk_size_pages=32,
    ).run([pdf_job])

    assert results[0].status == "failed"
    assert not pdf_job.output_path.exists()
    assert not list(tmp_path.glob(".hammerdown-broken-pdf-units-*"))


def test_text_units_share_pool_without_becoming_pdf_chunks(monkeypatch, tmp_path: Path) -> None:
    pdf_job = _job(tmp_path, "book.pdf", 0)
    text_job = _job(tmp_path, "notes.txt", 1)
    monkeypatch.setattr(
        "hammerdown.core.work_unit_scheduler.get_pdf_page_count",
        lambda _path: 96,
    )

    def convert(_source: str, pages: list[int], output: str) -> int:
        Path(output).write_text(f"chunk-{pages[0]}\n", encoding="utf-8")
        return 0

    def prepare(job: ConversionJob, **_kwargs: object) -> PreparedConversion:
        staging = __import__("hammerdown.core.output", fromlist=["OutputStaging"]).OutputStaging.create(
            tmp_path, prefix=".text-unit-"
        )
        staged = staging.path / job.output_path.name
        staged.write_text("text\n", encoding="utf-8")
        return PreparedConversion(
            job=job,
            source=job.source,
            output_path=job.output_path,
            staged_markdown=staged,
            staging=staging,
        )

    monkeypatch.setattr("hammerdown.core.work_unit_scheduler.convert_pdf_chunk", convert)
    results = WorkUnitScheduler(
        max_workers=4,
        in_flight_limit=4,
        heavy_limit=4,
        pdf_limit=2,
        chunk_size_pages=32,
        prepare_fn=prepare,
    ).run([pdf_job, text_job])

    assert [result.status for result in results] == ["committed", "committed"]
    assert pdf_job.output_path.read_text(encoding="utf-8") == "chunk-0\nchunk-32\nchunk-64\n"
    assert text_job.output_path.read_text(encoding="utf-8") == "text\n"
