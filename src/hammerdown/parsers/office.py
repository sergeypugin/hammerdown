from __future__ import annotations

import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile
from typing import Callable

from hammerdown.parsers.charts import render_chart_svg
from hammerdown.parsers.math import MATH_NS as _MATH_NS
from hammerdown.parsers.math import math_text as _math_text
from hammerdown.parsers.math import omml_to_latex as _omml_to_latex
from hammerdown.parsers.math import xml_name as _xml_name
from hammerdown.parsers.odt import convert_odt
from hammerdown.parsers.tables import render_table_regions
from hammerdown.utils import get_images_dir_name

logger = logging.getLogger("hammerdown")

ProgressCallback = Callable[[int, int, str], None]


def _find_soffice() -> str | None:
    """Find LibreOffice executable path across different operating systems."""
    # 1. Check PATH
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        return soffice

    # 2. Windows specific search
    if os.name == "nt":
        prog_files = [
            os.environ.get("PROGRAMFILES", "C:\\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"),
        ]
        for base in prog_files:
            path = Path(base) / "LibreOffice" / "program" / "soffice.exe"
            if path.is_file():
                return str(path)

    # 3. macOS specific search
    if os.name == "posix" and os.uname().sysname == "Darwin":
        path = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
        if path.is_file():
            return str(path)

    return None


def _convert_via_soffice(file_path: str, out_ext: str) -> str | None:
    """Convert document using LibreOffice headless mode."""
    soffice_bin = _find_soffice()
    if not soffice_bin:
        return None

    temp_dir = tempfile.mkdtemp()
    user_dir_uri = Path(temp_dir).resolve().as_uri()
    cmd = [
        soffice_bin,
        f"-env:UserInstallation={user_dir_uri}",
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


def _convert_via_ms_office_nt(file_path: str, out_ext: str) -> str | None:
    app_map = {
        "docx": (
            "Word.Application",
            "SaveAs2",
            16,
            "$app.Documents.Open($source, $false, $true, $false)",
            True,
        ),
        "xlsx": (
            "Excel.Application",
            "SaveAs",
            51,
            "$app.Workbooks.Open($source, 0, $true)",
            True,
        ),
        "pptx": (
            "PowerPoint.Application",
            "SaveAs",
            24,
            "$app.Presentations.Open($source, $true, $false, $false)",
            False,
        ),
    }
    app_id, save_method, file_format, open_expression, hide_app = app_map[out_ext]

    def quote_ps(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    temp_dir = tempfile.mkdtemp()
    temp_file = Path(temp_dir) / f"{Path(file_path).stem}.{out_ext}"
    source = quote_ps(str(Path(file_path).resolve()))
    destination = quote_ps(str(temp_file.resolve()))
    ps_cmd = f"""
    $ErrorActionPreference = 'Stop'
    $app = $null
    $document = $null
    try {{
        $app = New-Object -ComObject {app_id}
        if ({str(hide_app).lower()}) {{ $app.Visible = $false }}
        $source = {source}
        $destination = {destination}
        $document = {open_expression}
        $document.{save_method}($destination, {file_format})
        $document.Close()
    }} finally {{
        if ($null -ne $document) {{ try {{ $document.Close() }} catch {{ }} }}
        if ($null -ne $app) {{ try {{ $app.Quit() }} catch {{ }} }}
    }}
    """

    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            check=True,
            timeout=120,
        )
        if temp_file.is_file():
            return str(temp_file)
    except Exception as exc:
        logger.debug("MS Office conversion via PowerShell failed: %s", exc)

    return None


def _convert_legacy_office(file_path: str, out_ext: str) -> str | None:
    if os.name == "nt":
        converted = _convert_via_ms_office_nt(file_path, out_ext)
        if converted:
            return converted
    return _convert_via_soffice(file_path, out_ext)


def _render_word_node(node, relationships, chart_links=None) -> str | tuple[str, str]:
    tag = _xml_name(node)
    if tag == "r":
        rPr = node.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rPr")
        vert = None
        if rPr is not None:
            va = rPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}vertAlign")
            if va is not None:
                vert = va.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val")

        res = _render_word_children(node, relationships, chart_links)
        if vert in {"subscript", "superscript"}:
            latex = res[1] if isinstance(res, tuple) else res
            if latex.strip() and re.search(r"[\w\d]", latex) and re.match(r"^[ \w\d\.]+$", latex.strip()):
                prefix = "_" if vert == "subscript" else "^"
                return ("inline", f"{prefix}{{{latex.strip()}}}")
        return res

    if tag == "chart":
        relation_id = node.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        return chart_links.get(relation_id, "") if chart_links else ""
    if tag == "t":
        return node.text or ""
    if tag == "tab":
        return "\t"
    if tag in {"br", "cr"}:
        return "\n"
    if tag == "oMath":
        return ("inline", _omml_to_latex(node).strip())
    if tag == "oMathPara":
        formula = " ".join(_omml_to_latex(math).strip() for math in node.findall(f".//{_MATH_NS}oMath"))
        return ("display", formula.strip())
    if tag == "hyperlink":
        rendered = _render_word_children(node, relationships, chart_links)
        relation_id = node.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        url = relationships[relation_id].target_ref if relation_id in relationships else ""
        if url and rendered and isinstance(rendered, str):
            return f"[{rendered}]({url})"
        return rendered
    if tag.endswith("Pr") or tag in {"pPr", "sectPr"}:
        return ""
    return _render_word_children(node, relationships, chart_links)


def _render_word_children(node, relationships, chart_links=None, force_inline=False) -> str | tuple[str, str]:
    raw_parts = [_render_word_node(child, relationships, chart_links) for child in node]

    parts: list[str | tuple[str, str]] = []
    curr_math: list[str] = []

    def flush_math() -> None:
        if curr_math:
            combined = "".join(curr_math)
            parts.append(("inline", _math_text(combined).strip()))
            curr_math.clear()

    for part in raw_parts:
        if isinstance(part, tuple):
            mode, latex = part
            if mode == "display":
                flush_math()
                parts.append(part)
            else:
                curr_math.append(latex)
        elif isinstance(part, str):
            stripped = part.strip()
            if not stripped:
                is_glue = True
            elif not re.match(r"^[0-9\s=\+\-\*\/±≈\.,_():;\[\]!<>|–\w\.]+$", stripped):
                is_glue = False
            else:
                words = re.findall(r"\w+", stripped)
                is_glue = all(
                    len(w) <= 4 or w.lower() in {"max", "min", "sin", "cos", "tan", "log", "ln", "exp", "lim", "det", "arg"}
                    for w in words
                )

            if curr_math and is_glue:
                curr_math.append(part)
            else:
                flush_math()
                parts.append(part)
    flush_math()

    formulas = [part for part in parts if isinstance(part, tuple)]
    text_content = "".join(part for part in parts if isinstance(part, str))
    if not formulas:
        return text_content

    is_standalone = not force_inline and len(re.findall(r"[\w\d]", text_content)) < 10

    if is_standalone:
        rendered_parts = []
        for part in parts:
            if isinstance(part, tuple):
                rendered_parts.append(part[1])
            else:
                if part.strip():
                    if re.match(r"^[0-9\s.,=≈\+\-\*\/±]+$", part):
                        rendered_parts.append(part)
                    else:
                        rendered_parts.append(_math_text(part))
                else:
                    rendered_parts.append(part)
        return f"$${''.join(rendered_parts).strip()}$$"

    rendered = []
    for part in parts:
        if isinstance(part, tuple):
            mode, latex = part
            delimiter = "$$" if mode == "display" else "$"
            if delimiter == "$":
                latex = latex.replace("_", r"\_")
            rendered.append(f"{delimiter}{latex}{delimiter}")
        else:
            rendered.append(part)
    return "".join(rendered)


def _render_word_paragraph(element, relationships, chart_links=None, force_inline=False) -> str:
    rendered = _render_word_children(element, relationships, chart_links, force_inline=force_inline)
    return rendered.strip() if isinstance(rendered, str) else ""


def convert_docx(
    docx_path: str,
    out_dir: str,
    images_dir_name: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[str | None, int]:
    try:
        import docx  # type: ignore
        from docx.table import Table
    except ImportError:
        logger.error("DOCX support requires python-docx")
        return None, 0

    doc = docx.Document(docx_path)
    chart_links: dict[str, str] = {}
    saved_images = 0
    img_dir_name = images_dir_name or get_images_dir_name(docx_path)
    image_dir = Path(out_dir) / img_dir_name
    for relation_id, relation in doc.part.rels.items():
        if not relation.reltype.endswith("/chart"):
            continue
        rendered_chart = render_chart_svg(relation.target_part.blob)
        if rendered_chart is None:
            continue
        title, svg = rendered_chart
        image_dir.mkdir(parents=True, exist_ok=True)
        image_name = f"chart_{saved_images:03d}.svg"
        (image_dir / image_name).write_text(svg, encoding="utf-8")
        chart_links[relation_id] = f"![{title}]({img_dir_name}/{image_name})"
        saved_images += 1

    blocks: list[str] = []
    body_elements = list(doc.element.body)
    total_elements = len(body_elements)
    if progress_callback:
        progress_callback(0, total_elements, "elements")

    for elem_idx, element in enumerate(body_elements, start=1):
        tag = _xml_name(element)
        if tag == "p":
            text = _render_word_paragraph(element, doc.part.rels, chart_links)
            if text:
                blocks.append(text)
        elif tag == "tbl":
            table = Table(element, doc)
            rows = []
            for row_index, row in enumerate(table.rows):
                cells = []
                for cell in row.cells:
                    cell_paragraphs = [
                        _render_word_paragraph(paragraph._p, doc.part.rels, chart_links, force_inline=True)
                        for paragraph in cell.paragraphs
                    ]
                    cells.append(" ".join(text for text in cell_paragraphs if text).replace("|", "\\|"))
                rows.append(f"| {' | '.join(cells)} |")
                if row_index == 0:
                    rows.append(f"| {' | '.join(['---'] * len(cells))} |")
            if rows:
                blocks.append("\n".join(rows))
        if progress_callback:
            progress_callback(elem_idx, total_elements, "elements")

    return "\n\n".join(blocks), saved_images


def convert_xlsx(
    xlsx_path: str,
    out_dir: str,
    progress_callback: ProgressCallback | None = None,
) -> tuple[str | None, int]:
    try:
        import openpyxl  # type: ignore
    except ImportError:
        logger.error("XLSX support requires openpyxl")
        return None, 0

    workbook = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    formula_workbook = openpyxl.load_workbook(xlsx_path, data_only=False, read_only=True)
    blocks: list[str] = []
    total_sheets = len(workbook.sheetnames)
    if progress_callback:
        progress_callback(0, total_sheets, "sheets")

    for sheet_idx, sheet in enumerate(workbook.sheetnames, start=1):
        blocks.append(f"# Sheet: {sheet}")
        data_sheet = workbook[sheet]
        formula_sheet = formula_workbook[sheet]
        rows = []
        for data_row, formula_row in zip(data_sheet.iter_rows(), formula_sheet.iter_rows()):
            row = []
            for data_cell, formula_cell in zip(data_row, formula_row):
                value = data_cell.value
                if value is None and formula_cell.data_type == "f":
                    value = formula_cell.value
                row.append(value)
            rows.append(row)
        blocks.extend(render_table_regions(rows))
        if progress_callback:
            progress_callback(sheet_idx, total_sheets, "sheets")
    workbook.close()
    formula_workbook.close()
    return "\n\n".join(blocks), 0


def convert_pptx(
    pptx_path: str,
    out_dir: str,
    progress_callback: ProgressCallback | None = None,
) -> tuple[str | None, int]:
    try:
        from pptx import Presentation  # type: ignore
    except ImportError:
        logger.error("PPTX support requires python-pptx")
        return None, 0

    presentation = Presentation(pptx_path)
    lines: list[str] = []
    slides_list = list(presentation.slides)
    total_slides = len(slides_list)
    if progress_callback:
        progress_callback(0, total_slides, "slides")

    for slide_idx, slide in enumerate(slides_list, start=1):
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
        if progress_callback:
            progress_callback(slide_idx, total_slides, "slides")

    return "\n".join(lines), 0


def convert_doc(
    doc_path: str,
    out_dir: str,
    progress_callback: ProgressCallback | None = None,
) -> tuple[str | None, int]:
    img_dir_name = get_images_dir_name(doc_path)
    if zipfile.is_zipfile(doc_path):
        try:
            res = convert_docx(doc_path, out_dir, images_dir_name=img_dir_name, progress_callback=progress_callback)
            if res[0] is not None:
                return res
        except Exception:
            pass

    converted = _convert_legacy_office(doc_path, "docx")

    if converted:
        return convert_docx(converted, out_dir, images_dir_name=img_dir_name, progress_callback=progress_callback)

    logger.error("Legacy .doc format requires LibreOffice or Microsoft Word to be installed for conversion. Tip: use modern .docx for native support.")
    return None, 0


def convert_xls(
    xls_path: str,
    out_dir: str,
    progress_callback: ProgressCallback | None = None,
) -> tuple[str | None, int]:
    if zipfile.is_zipfile(xls_path):
        try:
            res = convert_xlsx(xls_path, out_dir, progress_callback=progress_callback)
            if res[0] is not None:
                return res
        except Exception:
            pass

    converted = _convert_legacy_office(xls_path, "xlsx")

    if converted:
        return convert_xlsx(converted, out_dir, progress_callback=progress_callback)

    logger.error("Legacy .xls format requires LibreOffice or Microsoft Excel to be installed for conversion. Tip: use modern .xlsx for native support.")
    return None, 0


def convert_ppt(
    ppt_path: str,
    out_dir: str,
    progress_callback: ProgressCallback | None = None,
) -> tuple[str | None, int]:
    if zipfile.is_zipfile(ppt_path):
        try:
            res = convert_pptx(ppt_path, out_dir, progress_callback=progress_callback)
            if res[0] is not None:
                return res
        except Exception:
            pass

    converted = _convert_legacy_office(ppt_path, "pptx")

    if converted:
        return convert_pptx(converted, out_dir, progress_callback=progress_callback)

    logger.error("Legacy .ppt format requires LibreOffice or Microsoft PowerPoint to be installed for conversion. Tip: use modern .pptx for native support.")
    return None, 0


CONVERTERS = {
    ".docx": convert_docx,
    ".doc": convert_doc,
    ".odt": convert_odt,
    ".xlsx": convert_xlsx,
    ".xls": convert_xls,
    ".pptx": convert_pptx,
    ".ppt": convert_ppt,
}
