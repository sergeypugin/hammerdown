from __future__ import annotations

import concurrent.futures
import logging
import os
import threading
from typing import Callable

logger = logging.getLogger("hammerdown")

ProgressCallback = Callable[[int, int, str], None]


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
        chunk_size = max(2, (page_count + cpu_cnt - 1) // cpu_cnt)
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

        worker_count = min(len(page_chunks), cpu_cnt)
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
