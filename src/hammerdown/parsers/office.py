from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

logger = logging.getLogger("hammerdown")


def _convert_via_soffice(file_path: str, out_ext: str) -> str | None:
    soffice_bin = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice_bin and os.name == "nt":
        common_paths = [
            Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "LibreOffice" / "program" / "soffice.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")) / "LibreOffice" / "program" / "soffice.exe",
        ]
        for p in common_paths:
            if p.is_file():
                soffice_bin = str(p)
                break

    if not soffice_bin:
        return None

    temp_dir = tempfile.mkdtemp()
    cmd = [
        soffice_bin,
        "--headless",
        "--convert-to",
        out_ext,
        "--outdir",
        temp_dir,
        file_path,
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        converted_file = Path(temp_dir) / f"{Path(file_path).stem}.{out_ext}"
        if converted_file.is_file():
            return str(converted_file)
    except Exception:
        pass
    return None


def convert_docx(docx_path: str, out_dir: str) -> tuple[str | None, int]:
    try:
        import docx  # type: ignore
    except ImportError:
        logger.error("DOCX support requires python-docx")
        return None, 0

    doc = docx.Document(docx_path)
    lines: list[str] = []
    for paragraph in doc.paragraphs:
        if paragraph.text.strip():
            lines.append(paragraph.text)

    for table in doc.tables:
        if not table.rows:
            continue
        header_cells = [cell.text.strip() for cell in table.rows[0].cells]
        lines.append(f"| {' | '.join(header_cells)} |")
        lines.append(f"| {' | '.join(['---'] * len(header_cells))} |")
        for row in table.rows[1:]:
            row_text = " | ".join(cell.text.strip() for cell in row.cells)
            lines.append(f"| {row_text} |")

    return "\n\n".join(lines), 0


def convert_xlsx(xlsx_path: str, out_dir: str) -> tuple[str | None, int]:
    try:
        import openpyxl  # type: ignore
    except ImportError:
        logger.error("XLSX support requires openpyxl")
        return None, 0

    workbook = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    lines: list[str] = []
    for sheet in workbook.sheetnames:
        lines.append(f"# Sheet: {sheet}\n")
        rows = workbook[sheet].iter_rows(values_only=True)
        header = next(rows, None)
        if header is None:
            continue
        header_cells = [str(cell) if cell is not None else "" for cell in header]
        lines.append(f"| {' | '.join(header_cells)} |")
        lines.append(f"| {' | '.join(['---'] * len(header_cells))} |")
        for row in rows:
            if any(row):
                row_text = " | ".join(str(cell) if cell is not None else "" for cell in row)
                lines.append(f"| {row_text} |")
        lines.append("\n")
    workbook.close()
    return "\n".join(lines), 0


def convert_pptx(pptx_path: str, out_dir: str) -> tuple[str | None, int]:
    try:
        from pptx import Presentation  # type: ignore
    except ImportError:
        logger.error("PPTX support requires python-pptx")
        return None, 0

    presentation = Presentation(pptx_path)
    lines: list[str] = []
    for slide_idx, slide in enumerate(list(presentation.slides), start=1):
        lines.append(f"## Slide {slide_idx}\n")
        for shape in slide.shapes:
            if getattr(shape, "has_table", False):
                table = getattr(shape, "table", None)
                if table is None:
                    continue
                rows = list(table.rows)
                if rows:
                    header = [cell.text.strip() for cell in rows[0].cells]
                    lines.append(f"| {' | '.join(header)} |")
                    lines.append(f"| {' | '.join(['---'] * len(header))} |")
                    for row in rows[1:]:
                        lines.append(f"| {' | '.join(cell.text.strip() for cell in row.cells)} |")
            elif getattr(shape, "has_text_frame", False):
                text_frame = getattr(shape, "text_frame", None)
                if text_frame is None:
                    continue
                for paragraph in text_frame.paragraphs:
                    text = paragraph.text.strip()
                    if text:
                        lines.append(text)
        lines.append("")

    return "\n".join(lines), 0


def convert_doc(doc_path: str, out_dir: str) -> tuple[str | None, int]:
    if zipfile.is_zipfile(doc_path):
        return convert_docx(doc_path, out_dir)

    converted = _convert_via_soffice(doc_path, "docx")
    if converted:
        return convert_docx(converted, out_dir)

    if os.name == "nt":
        try:
            import win32com.client  # type: ignore
            word = win32com.client.Dispatch("Word.Application")
            word.Visible = False
            temp_file = Path(tempfile.mkdtemp()) / f"{Path(doc_path).stem}.docx"
            doc = word.Documents.Open(str(Path(doc_path).resolve()))
            doc.SaveAs2(str(temp_file.resolve()), FileFormat=16)
            doc.Close()
            word.Quit()
            if temp_file.is_file():
                return convert_docx(str(temp_file), out_dir)
        except Exception:
            pass

    logger.error("Legacy .doc format requires LibreOffice or Microsoft Word to be installed")
    return None, 0


def convert_xls(xls_path: str, out_dir: str) -> tuple[str | None, int]:
    if zipfile.is_zipfile(xls_path):
        return convert_xlsx(xls_path, out_dir)

    converted = _convert_via_soffice(xls_path, "xlsx")
    if converted:
        return convert_xlsx(converted, out_dir)

    if os.name == "nt":
        try:
            import win32com.client  # type: ignore
            excel = win32com.client.Dispatch("Excel.Application")
            excel.Visible = False
            temp_file = Path(tempfile.mkdtemp()) / f"{Path(xls_path).stem}.xlsx"
            wb = excel.Workbooks.Open(str(Path(xls_path).resolve()))
            wb.SaveAs(str(temp_file.resolve()), FileFormat=51)
            wb.Close()
            excel.Quit()
            if temp_file.is_file():
                return convert_xlsx(str(temp_file), out_dir)
        except Exception:
            pass

    logger.error("Legacy .xls format requires LibreOffice or Microsoft Excel to be installed")
    return None, 0


def convert_ppt(ppt_path: str, out_dir: str) -> tuple[str | None, int]:
    if zipfile.is_zipfile(ppt_path):
        return convert_pptx(ppt_path, out_dir)

    converted = _convert_via_soffice(ppt_path, "pptx")
    if converted:
        return convert_pptx(converted, out_dir)

    if os.name == "nt":
        try:
            import win32com.client  # type: ignore
            powerpoint = win32com.client.Dispatch("PowerPoint.Application")
            temp_file = Path(tempfile.mkdtemp()) / f"{Path(ppt_path).stem}.pptx"
            ppt = powerpoint.Presentations.Open(str(Path(ppt_path).resolve()), WithWindow=False)
            ppt.SaveAs(str(temp_file.resolve()), FileFormat=24)
            ppt.Close()
            powerpoint.Quit()
            if temp_file.is_file():
                return convert_pptx(str(temp_file), out_dir)
        except Exception:
            pass

    logger.error("Legacy .ppt format requires LibreOffice or Microsoft PowerPoint to be installed")
    return None, 0
