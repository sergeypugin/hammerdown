from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

from docx import Document

from hammerdown.parsers.math import mathml_to_latex, omml_to_latex
from hammerdown.parsers.odt import convert_odt
from hammerdown.parsers.office import convert_docx


def test_docx_preserves_formula_and_table_order(tmp_path: Path) -> None:
    source = Path("tests/inputs/report.docx")
    docx_path = tmp_path / source.name
    doc = Document(str(source))
    chart_tag = "{http://schemas.openxmlformats.org/drawingml/2006/chart}chart"
    chart_paragraph = next(
        element for element in doc.element.body if any(node.tag == chart_tag for node in element.iter())
    )
    duplicate_paragraph = deepcopy(chart_paragraph)
    duplicate_chart = next(node for node in duplicate_paragraph.iter() if node.tag == chart_tag)
    chart_relation = next(relation for relation in doc.part.rels.values() if relation.reltype.endswith("/chart"))
    duplicate_relation_id = "rId100"
    doc.part.rels.add_relationship(chart_relation.reltype, chart_relation.target_part, duplicate_relation_id)
    duplicate_chart.set(
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", duplicate_relation_id
    )
    body = doc.element.body
    body.insert(list(body).index(chart_paragraph) + 1, duplicate_paragraph)
    doc.save(str(docx_path))

    markdown, images = convert_docx(str(docx_path), str(tmp_path))

    assert markdown is not None
    assert images == 2
    assert r"\frac{1}{N}" in markdown
    assert r"\sum\_{i=1}^{N}" in markdown
    assert (
        r"\rho(12) \approx \frac{1}{2.891\sqrt{2\pi}}\cdot\exp(-\frac{(12 - 12.66)^{2}}{2\cdot2.891^{2}})\approx0.13"
        in markdown
    )

    assert r"$$l=(12.66\pm0.51)" in markdown
    assert markdown.index("8. Результаты прямых измерений") < markdown.index("| Actors |")
    assert markdown.index("| Actors |") < markdown.index("9. Расчет результатов")
    lines = markdown.splitlines()
    actors_header = next(index for index, line in enumerate(lines) if line.startswith("| Actors |"))
    assert lines[actors_header + 1].startswith("| --- |")
    assert lines[actors_header + 2].startswith("| surname |")
    assert lines[actors_header + 3].startswith("| Holland |")
    chart_link_1 = "![Гистограмма распределения длин имён и функция Гаусса](hm_images_report_docx/chart_001.svg)"
    chart_link_2 = "![Гистограмма распределения длин имён и функция Гаусса](hm_images_report_docx/chart_002.svg)"
    assert chart_link_1 in markdown
    assert chart_link_2 in markdown
    assert markdown.index("График 1 – Гистограмма и функция Гаусса") < markdown.index(chart_link_1)
    assert markdown.index(chart_link_1) < markdown.index(chart_link_2) < markdown.index("12. ")
    for image_name in ("chart_001.svg", "chart_002.svg"):
        chart_path = tmp_path / "hm_images_report_docx" / image_name
        assert ET.parse(chart_path).getroot().tag.endswith("svg")



def test_omml_normalizes_greek_symbols_functions_and_decimal_commas() -> None:
    omml = (
        '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
        "<m:r><m:t>ρ exp 2,891</m:t></m:r></m:oMath>"
    )

    assert omml_to_latex(ET.fromstring(omml)) == r"\rho \exp 2.891"


def test_odt_normalizes_gaussian_math_from_adjacent_tokens(tmp_path: Path) -> None:
    source = Path("tests/inputs/report.odt")
    markdown, _ = convert_odt(str(source), str(tmp_path))

    assert markdown is not None
    assert r"\cdot\exp(-\frac{(12-12.66)^{2}}{2\cdot2.891^{2}})" in markdown


def test_mathml_fraction_and_sum() -> None:
    mathml = (
        '<math xmlns="http://www.w3.org/1998/Math/MathML">'
        "<mfrac><mn>1</mn><mi>N</mi></mfrac>"
        "<munderover><mo>∑</mo><mi>i=1</mi><mi>N</mi></munderover>"
        "<msub><mi>l</mi><mi>i</mi></msub></math>"
    )

    result = mathml_to_latex(ET.fromstring(mathml))
    assert result == r"\frac{1}{N}\sum_{i=1}^{N}l_{i}"


def test_odt_uses_inline_and_display_math_and_keeps_tables_ordered(tmp_path: Path) -> None:
    odt_path = tmp_path / "sample.odt"
    content = """<office:document-content
        xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
        xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
        xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
        xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
        xmlns:xlink="http://www.w3.org/1999/xlink">
      <office:body><office:text>
        <text:p>This is a long sentence that contains an inline <draw:object xlink:href="Object 1/"/> formula and enough text to exceed the threshold.</text:p>
        <text:p><draw:object xlink:href="Object 1/"/></text:p>
        <table:table>
          <table:table-row><table:table-cell><text:p>Header</text:p></table:table-cell></table:table-row>
          <table:table-row><table:table-cell><text:p>Value</text:p></table:table-cell></table:table-row>
        </table:table>
      </office:text></office:body>
    </office:document-content>"""
    formula = (
        '<math xmlns="http://www.w3.org/1998/Math/MathML">'
        "<mfrac><mn>1</mn><mi>N</mi></mfrac></math>"
    )
    styles = """<office:document-styles
        xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
        xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
        xmlns:xlink="http://www.w3.org/1999/xlink">
      <draw:image xlink:href="Pictures/logo.png"/>
    </office:document-styles>"""
    with zipfile.ZipFile(odt_path, "w") as archive:
        archive.writestr("content.xml", content)
        archive.writestr("styles.xml", styles)
        archive.writestr("Pictures/logo.png", b"image data")
        archive.writestr("Object 1/content.xml", formula)

    markdown, images = convert_odt(str(odt_path), str(tmp_path))

    assert markdown is not None
    assert images == 1
    assert (tmp_path / "hm_images_sample_odt" / "img_001.png").read_bytes() == b"image data"
    assert "![Image](hm_images_sample_odt/img_001.png)" in markdown
    assert "contains an inline $\\frac{1}{N}$ formula" in markdown
    assert "$$\\frac{1}{N}$$" in markdown
    assert markdown.index("$$\\frac{1}{N}$$") < markdown.index("| Header |")
