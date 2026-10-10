from __future__ import annotations

import concurrent.futures
import logging
import os
from pathlib import Path

from hammerdown.utils import get_images_dir_name

logger = logging.getLogger("hammerdown")


def convert_pdf_or_ebook(file_path: str, out_dir: str) -> tuple[str | None, int]:
    try:
        import pymupdf  # type: ignore
        import pymupdf4llm  # type: ignore
    except ImportError:
        logger.error("PDF support requires pymupdf and pymupdf4llm")
        return None, 0

    img_dir_name = get_images_dir_name(file_path)
    img_dir = Path(out_dir) / img_dir_name

    saved_imgs = 0
    extracted_xrefs: set[int] = set()
    image_tasks: list[tuple[Path, bytes]] = []

    with pymupdf.open(file_path) as doc:
        page_count = len(doc)
        for page_number in range(page_count):
            page = doc[page_number]
            for img_info in page.get_images():
                xref = img_info[0]
                if xref in extracted_xrefs:
                    continue

                img_data = doc.extract_image(xref)
                if img_data["width"] < 50 or img_data["height"] < 50:
                    continue

                img_name = f"img_p{page_number:03d}_xref{xref}.{img_data['ext']}"
                image_tasks.append((img_dir / img_name, img_data["image"]))
                extracted_xrefs.add(xref)
                saved_imgs += 1

    if image_tasks:
        img_dir.mkdir(parents=True, exist_ok=True)

        def _write_image(task: tuple[Path, bytes]) -> None:
            target_path, img_bytes = task
            target_path.write_bytes(img_bytes)

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(image_tasks), 8)) as executor:
            list(executor.map(_write_image, image_tasks))

    if page_count > 1:
        cpu_cnt = os.cpu_count() or 4
        chunk_size = max(2, (page_count + cpu_cnt - 1) // cpu_cnt)
        page_chunks = [
            list(range(i, min(i + chunk_size, page_count)))
            for i in range(0, page_count, chunk_size)
        ]

        def _convert_chunk(pages: list[int]) -> str:
            res = pymupdf4llm.to_markdown(file_path, pages=pages, write_images=False, use_ocr=False)
            return str(res)

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(page_chunks), cpu_cnt)) as executor:
            chunk_results = list(executor.map(_convert_chunk, page_chunks))
        md_text = "".join(chunk_results)
    else:
        md_text = pymupdf4llm.to_markdown(file_path, write_images=False, use_ocr=False)

    return str(md_text), saved_imgs


CONVERTERS = {
    ".pdf": convert_pdf_or_ebook,
    ".epub": convert_pdf_or_ebook,
    ".mobi": convert_pdf_or_ebook,
    ".fb2": convert_pdf_or_ebook,
    ".xps": convert_pdf_or_ebook,
}
