from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

from hammerdown.parsers import pdf


class _Document:
    def __init__(self, page_count: int) -> None:
        self.page_count = page_count

    def __enter__(self) -> _Document:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def __len__(self) -> int:
        return self.page_count


class _Future:
    def __init__(self, value: str) -> None:
        self.value = value

    def result(self) -> str:
        return self.value


class _Executor:
    instances: list[_Executor] = []

    def __init__(self, max_workers: int) -> None:
        self.max_workers = max_workers
        self.submitted: list[list[int]] = []
        self.__class__.instances.append(self)

    def __enter__(self) -> _Executor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def submit(self, function: Any, pages: list[int]) -> _Future:
        self.submitted.append(pages)
        return _Future(function(pages))


def test_pdf_uses_default_32_page_chunks_and_caps_inner_executor(monkeypatch: Any, tmp_path: Path) -> None:
    pymupdf = types.SimpleNamespace(open=lambda _path: _Document(75))
    pymupdf4llm = types.SimpleNamespace(
        to_markdown=lambda _path, pages=None, **_kwargs: "".join(str(page) for page in (pages or []))
    )
    monkeypatch.setitem(sys.modules, "pymupdf", pymupdf)
    monkeypatch.setitem(sys.modules, "pymupdf4llm", pymupdf4llm)
    monkeypatch.setattr(pdf.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(pdf.concurrent.futures, "ThreadPoolExecutor", _Executor)
    _Executor.instances.clear()

    markdown, error_count = pdf.convert_pdf_or_ebook(str(tmp_path / "input.pdf"), str(tmp_path))

    assert error_count == 0
    assert markdown == "".join(str(page) for page in range(75))
    executor = _Executor.instances[0]
    assert executor.max_workers == 3
    assert executor.submitted == [
        list(range(0, 32)),
        list(range(32, 64)),
        list(range(64, 75)),
    ]


def test_two_page_pdf_stays_one_chunk(monkeypatch: Any, tmp_path: Path) -> None:
    pymupdf = types.SimpleNamespace(open=lambda _path: _Document(2))
    pymupdf4llm = types.SimpleNamespace(
        to_markdown=lambda _path, pages=None, **_kwargs: "".join(str(page) for page in (pages or []))
    )
    monkeypatch.setitem(sys.modules, "pymupdf", pymupdf)
    monkeypatch.setitem(sys.modules, "pymupdf4llm", pymupdf4llm)
    monkeypatch.setattr(pdf.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(pdf.concurrent.futures, "ThreadPoolExecutor", _Executor)
    _Executor.instances.clear()

    markdown, error_count = pdf.convert_pdf_or_ebook(str(tmp_path / "input.pdf"), str(tmp_path))

    assert error_count == 0
    assert markdown == "01"
    executor = _Executor.instances[0]
    assert executor.max_workers == 1
    assert executor.submitted == [[0, 1]]


def test_pdf_uses_fixed_chunk_size(monkeypatch: Any, tmp_path: Path) -> None:
    pymupdf = types.SimpleNamespace(open=lambda _path: _Document(25))
    pymupdf4llm = types.SimpleNamespace(
        to_markdown=lambda _path, pages=None, **_kwargs: "".join(str(page) for page in (pages or []))
    )
    monkeypatch.setitem(sys.modules, "pymupdf", pymupdf)
    monkeypatch.setitem(sys.modules, "pymupdf4llm", pymupdf4llm)
    monkeypatch.setattr(pdf.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(pdf, "PDF_CHUNK_SIZE_PAGES", 8)
    monkeypatch.setattr(pdf.concurrent.futures, "ThreadPoolExecutor", _Executor)
    _Executor.instances.clear()

    markdown, error_count = pdf.convert_pdf_or_ebook(str(tmp_path / "input.pdf"), str(tmp_path))

    assert error_count == 0
    assert markdown == "0123456789101112131415161718192021222324"
    executor = _Executor.instances[0]
    assert executor.max_workers == 4
    assert executor.submitted == [
        list(range(0, 8)),
        list(range(8, 16)),
        list(range(16, 24)),
        [24],
    ]
