from __future__ import annotations

import concurrent.futures
import logging
import os
import threading
from typing import Callable

logger = logging.getLogger("hammerdown")

ProgressCallback = Callable[[int, int, str], None]

# Raising this cap gave no stable throughput gain in 30-page benchmarks,
# so keep the native page pool bounded.
PDF_WORKER_CAP = 4
PDF_CHUNK_SIZE_PAGES: int | None = 32


def get_pdf_page_count(file_path: str) -> int:
    """Return the page count without starting a conversion worker."""
    import pymupdf  # type: ignore

    with pymupdf.open(file_path) as doc:
        return len(doc)


def convert_pdf_chunk(file_path: str, pages: list[int], output_path: str) -> int:
    """Convert one page chunk and write the result to a worker-owned file."""
    try:
        import pymupdf4llm  # type: ignore
    except ImportError:
        logger.error("PDF support requires pymupdf4llm")
        raise

    warnings = 0
    try:
        markdown = str(
            pymupdf4llm.to_markdown(
                file_path,
                pages=pages,
                write_images=False,
                use_ocr=False,
            )
        )
    except Exception:
        parts: list[str] = []
        for page in pages:
            try:
                parts.append(
                    str(
                        pymupdf4llm.to_markdown(
                            file_path,
                            pages=[page],
                            write_images=False,
                            use_ocr=False,
                        )
                    )
                )
            except Exception:
                warnings += 1
                parts.append(f"\n\n<!-- Warning: failed to parse page {page + 1} -->\n\n")
        markdown = "".join(parts)

    from pathlib import Path

    Path(output_path).write_text(markdown, encoding="utf-8", newline="\n")
    return warnings


def convert_pdf_or_ebook(
    file_path: str,
    out_dir: str,
    progress_callback: ProgressCallback | None = None,
) -> tuple[str | None, int]:
    try:
        import pymupdf  # type: ignore
        import pymupdf4llm  # type: ignore
    except ImportError:
        logger.error("PDF support requires pymupdf and pymupdf4llm")
        return None, 0

    with pymupdf.open(file_path) as doc:
        page_count = len(doc)

    if page_count > 1:
        cpu_cnt = os.cpu_count() or 4
        if PDF_CHUNK_SIZE_PAGES is None:
            chunk_size = max(2, (page_count + cpu_cnt - 1) // cpu_cnt)
        else:
            if not isinstance(PDF_CHUNK_SIZE_PAGES, int) or isinstance(PDF_CHUNK_SIZE_PAGES, bool):
                raise ValueError("PDF_CHUNK_SIZE_PAGES must be a positive integer or None")
            if PDF_CHUNK_SIZE_PAGES <= 0:
                raise ValueError("PDF_CHUNK_SIZE_PAGES must be a positive integer or None")
            chunk_size = PDF_CHUNK_SIZE_PAGES
        page_chunks = [
            list(range(i, min(i + chunk_size, page_count)))
            for i in range(0, page_count, chunk_size)
        ]

        completed_pages = 0
        progress_lock = threading.Lock()

        def _convert_single_page_safe(page_idx: int) -> str:
            nonlocal completed_pages
            try:
                res = pymupdf4llm.to_markdown(file_path, pages=[page_idx], write_images=False, use_ocr=False)
                res_str = str(res)
            except Exception:
                res_str = f"\n\n<!-- Warning: failed to parse page {page_idx + 1} -->\n\n"
            with progress_lock:
                completed_pages += 1
                if progress_callback:
                    progress_callback(completed_pages, page_count, "pages")
            return res_str

        def _convert_chunk_worker(pages: list[int]) -> str:
            nonlocal completed_pages
            try:
                res = pymupdf4llm.to_markdown(file_path, pages=pages, write_images=False, use_ocr=False)
                with progress_lock:
                    completed_pages += len(pages)
                    if progress_callback:
                        progress_callback(completed_pages, page_count, "pages")
                return str(res)
            except Exception:
                # If a multi-page chunk fails, fall back to safe per-page extraction
                sub_results = [_convert_single_page_safe(p) for p in pages]
                return "".join(sub_results)

        if progress_callback:
            progress_callback(0, page_count, "pages")

        worker_count = min(len(page_chunks), cpu_cnt, PDF_WORKER_CAP)
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_chunk = [executor.submit(_convert_chunk_worker, chunk) for chunk in page_chunks]
            chunk_results = [f.result() for f in future_to_chunk]
        md_text = "".join(chunk_results)
    else:
        if progress_callback:
            progress_callback(0, page_count, "pages")
        md_text = pymupdf4llm.to_markdown(file_path, write_images=False, use_ocr=False)
        if progress_callback:
            progress_callback(page_count, page_count, "pages")

    return str(md_text), 0


CONVERTERS = {
    ".pdf": convert_pdf_or_ebook,
    ".epub": convert_pdf_or_ebook,
    ".mobi": convert_pdf_or_ebook,
    ".fb2": convert_pdf_or_ebook,
    ".xps": convert_pdf_or_ebook,
}
