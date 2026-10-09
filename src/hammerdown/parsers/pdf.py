from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("hammerdown")


def convert_pdf_or_ebook(file_path: str, out_dir: str) -> tuple[str | None, int]:
    try:
        import pymupdf  # type: ignore
        import pymupdf4llm  # type: ignore
    except ImportError:
        logger.error("PDF support requires pymupdf and pymupdf4llm")
        return None, 0

    stem = Path(file_path).stem
    img_dir = Path(out_dir) / "hammerdown_images"
    img_dir.mkdir(parents=True, exist_ok=True)

    saved_imgs = 0
    extracted_xrefs: set[int] = set()
    with pymupdf.open(file_path) as doc:
        for page_number in range(len(doc)):
            page = doc[page_number]
            for img_info in page.get_images():
                xref = img_info[0]
                if xref in extracted_xrefs:
                    continue

                img_data = doc.extract_image(xref)
                if img_data["width"] < 50 or img_data["height"] < 50:
                    continue

                img_name = f"{stem}_p{page_number:03d}_xref{xref}.{img_data['ext']}"
                (img_dir / img_name).write_bytes(img_data["image"])
                extracted_xrefs.add(xref)
                saved_imgs += 1

    md_text = pymupdf4llm.to_markdown(file_path, write_images=False)
    return str(md_text), saved_imgs


CONVERTERS = {
    ".pdf": convert_pdf_or_ebook,
    ".epub": convert_pdf_or_ebook,
    ".mobi": convert_pdf_or_ebook,
    ".fb2": convert_pdf_or_ebook,
    ".xps": convert_pdf_or_ebook,
}
