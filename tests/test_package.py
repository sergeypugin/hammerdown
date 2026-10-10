from pathlib import Path

import hammerdown
from hammerdown.cli import main
from hammerdown.core import convert_file, to_markdown
from hammerdown.utils import normalize_path


def test_package_exports():
    assert hasattr(hammerdown, "to_markdown")
    assert hasattr(hammerdown, "convert_file")
    assert hasattr(hammerdown, "convert_docx")
    assert hasattr(hammerdown, "convert_doc")
    assert hasattr(hammerdown, "convert_odt")
    assert hasattr(hammerdown, "convert_xlsx")
    assert hasattr(hammerdown, "convert_xls")
    assert hasattr(hammerdown, "convert_pptx")
    assert hasattr(hammerdown, "convert_ppt")
    assert hasattr(hammerdown, "convert_pdf_or_ebook")
    assert hasattr(hammerdown, "convert_csv")
    assert hasattr(hammerdown, "convert_txt_or_md")
    assert hasattr(hammerdown, "render_table_regions")
    assert hasattr(hammerdown, "render_chart_svg")
    assert hasattr(hammerdown, "omml_to_latex")
    assert hasattr(hammerdown, "mathml_to_latex")
    assert hasattr(hammerdown, "SUPPORTED_EXTENSIONS")
    assert hasattr(hammerdown, "__version__")


def test_to_markdown_plain_text(tmp_path: Path):
    source = tmp_path / "hello.txt"
    source.write_text("Hello world!", encoding="utf-8")

    text, saved_images = to_markdown(source)
    assert text == "Hello world!"
    assert saved_images == 0


def test_convert_file_package(tmp_path: Path):
    source = tmp_path / "doc.txt"
    source.write_text("package test", encoding="utf-8")

    assert convert_file(source)
    out_file = tmp_path / "doc_txt.md"
    assert out_file.is_file()
    assert out_file.read_text(encoding="utf-8") == "package test\n"


def test_progress_callback(tmp_path: Path):
    from hammerdown.utils import format_progress_bar

    bar = format_progress_bar(5, 10, unit="pages", bar_length=10)
    assert "[█████░░░░░] 50% (5/10 pages)" == bar

    source = tmp_path / "report.docx"
    import docx
    doc = docx.Document()
    doc.add_paragraph("Paragraph 1")
    doc.add_paragraph("Paragraph 2")
    doc.save(str(source))

    calls: list[tuple[int, int, str]] = []

    def on_progress(current: int, total: int, unit: str):
        calls.append((current, total, unit))

    text, images = to_markdown(source, progress_callback=on_progress)
    assert text is not None
    assert len(calls) > 0
    assert calls[-1][0] == calls[-1][1]  # final call reaches 100%
