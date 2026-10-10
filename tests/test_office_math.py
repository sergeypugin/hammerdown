from __future__ import annotations

from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

from hammerdown.parsers.math import mathml_to_latex, omml_to_latex
from hammerdown.parsers.odt import convert_odt
from hammerdown.parsers.office import convert_docx


def test_docx_preserves_formula_and_table_order(tmp_path: Path) -> None:
    source = Path("tests/inputs/report.docx")
    markdown, images = convert_docx(str(source), str(tmp_path))

    assert markdown is not None
    assert images == 1
    assert r"\frac{1}{N}" in markdown
    assert r"\sum_{i=1}^{N}" in markdown
    assert (
        r"\rho(12) \approx \frac{1}{2{,}891\sqrt{2\pi}}\cdot\exp(-\frac{(12 - 12.66)^{2}}{2\cdot2{,}891^{2}})\approx0{,}13"
        in markdown
    )

    assert r"$$l=(12{,}66\pm0{,}51)" in markdown
    assert markdown.index("8. Результаты прямых измерений") < markdown.index("| Actors |")
    assert markdown.index("| Actors |") < markdown.index("9. Расчет результатов")
    lines = markdown.splitlines()
    actors_header = next(index for index, line in enumerate(lines) if line.startswith("| Actors |"))
    assert lines[actors_header + 1].startswith("| --- |")
    assert lines[actors_header + 2].startswith("| surname |")
    assert lines[actors_header + 3].startswith("| Holland |")
    chart_link = "![Гистограмма распределения длин имён и функция Гаусса](hammerdown_images_report_docx/chart_000.svg)"
    assert chart_link in markdown
    assert markdown.index("График 1 – Гистограмма и функция Гаусса") < markdown.index(chart_link)
    assert markdown.index(chart_link) < markdown.index("12. ")
    chart_path = tmp_path / "hammerdown_images_report_docx" / "chart_000.svg"
    assert ET.parse(chart_path).getroot().tag.endswith("svg")



def test_omml_normalizes_greek_symbols_functions_and_decimal_commas() -> None:
    omml = (
        '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
        "<m:r><m:t>ρ exp 2,891</m:t></m:r></m:oMath>"
    )

    assert omml_to_latex(ET.fromstring(omml)) == r"\rho \exp 2{,}891"


def test_odt_normalizes_gaussian_math_from_adjacent_tokens(tmp_path: Path) -> None:
    source = Path("tests/inputs/report.odt")
    markdown, _ = convert_odt(str(source), str(tmp_path))

    assert markdown is not None
    assert r"\cdot\exp(-\frac{(12-12.66)^{2}}{2\cdot2{,}891^{2}})" in markdown


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
    assert (tmp_path / "hammerdown_images_sample_odt" / "img_000.png").read_bytes() == b"image data"
    assert "![Image](hammerdown_images_sample_odt/img_000.png)" in markdown
    assert "inline $\\frac{1}{N}$ formula" in markdown
    assert "$$\\frac{1}{N}$$" in markdown
    assert markdown.index("$$\\frac{1}{N}$$") < markdown.index("| Header |")
