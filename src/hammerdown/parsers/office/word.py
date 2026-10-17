from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Callable

from hammerdown.parsers.charts import render_chart_svg
from hammerdown.parsers.markdown_render import is_math_glue, render_markdown_table
from hammerdown.parsers.math import MATH_NS as _MATH_NS
from hammerdown.parsers.math import math_text as _math_text
from hammerdown.parsers.math import omml_to_latex as _omml_to_latex
from hammerdown.parsers.math import xml_name as _xml_name
from hammerdown.utils import get_images_dir_name

logger = logging.getLogger("hammerdown")
ProgressCallback = Callable[[int, int, str], None]

_ALNUM_RE = re.compile(r"[\w\d]")
_NUMERIC_RE = re.compile(r"^[0-9\s.,=≈\+\-\*\/±]+$")
_PLAIN_TEXT_RE = re.compile(r"^[ \w\d\.]+$")


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
            if latex.strip() and _ALNUM_RE.search(latex) and _PLAIN_TEXT_RE.match(latex.strip()):
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
            if curr_math and is_math_glue(part):
                curr_math.append(part)
            else:
                flush_math()
                parts.append(part)
    flush_math()

    formulas = [part for part in parts if isinstance(part, tuple)]
    text_content = "".join(part for part in parts if isinstance(part, str))
    if not formulas:
        return text_content

    is_standalone = not force_inline and len(_ALNUM_RE.findall(text_content)) < 10

    if is_standalone:
        rendered_parts = []
        for part in parts:
            if isinstance(part, tuple):
                rendered_parts.append(part[1])
            else:
                if part.strip():
                    if _NUMERIC_RE.match(part):
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
            rendered_rows: list[list[str]] = []
            for row in table.rows:
                cells = []
                for cell in row.cells:
                    cell_paragraphs = [
                        _render_word_paragraph(paragraph._p, doc.part.rels, chart_links, force_inline=True)
                        for paragraph in cell.paragraphs
                    ]
                    cells.append(" ".join(text for text in cell_paragraphs if text))
                rendered_rows.append(cells)
            if rendered_rows:
                blocks.append("\n".join(render_markdown_table(rendered_rows)))
        if progress_callback:
            progress_callback(elem_idx, total_elements, "elements")

    return "\n\n".join(blocks), saved_images
