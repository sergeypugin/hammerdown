from __future__ import annotations

from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

from hammerdown.parsers.math import mathml_to_latex
from hammerdown.parsers.odt import convert_odt
from hammerdown.parsers.office import convert_docx


def test_docx_preserves_formula_and_table_order(tmp_path: Path) -> None:
    source = Path("tests/inputs/report.docx")
    markdown, images = convert_docx(str(source), str(tmp_path))

    assert markdown is not None
    assert images == 0
    assert r"\frac{1}{N}" in markdown
    assert r"\sum_{i=1}^{N}" in markdown
    assert "$$l=(12,66±0,51)" in markdown
    assert markdown.index("8. Результаты прямых измерений") < markdown.index("| Actors |")
    assert markdown.index("| Actors |") < markdown.index("9. Расчет результатов")


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
        <text:p>Inline <draw:object xlink:href="Object 1/"/> formula</text:p>
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
    assert (tmp_path / "images" / "img_sample_000.png").read_bytes() == b"image data"
    assert "![Image](images/img_sample_000.png)" in markdown
    assert "Inline $\\frac{1}{N}$ formula" in markdown
    assert "$$\\frac{1}{N}$$" in markdown
    assert markdown.index("$$\\frac{1}{N}$$") < markdown.index("| Header |")
