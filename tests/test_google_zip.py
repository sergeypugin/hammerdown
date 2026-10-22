import base64
import zipfile
from pathlib import Path
from hammerdown.core import convert_file

HTML_WITH_TABLE_AND_LISTS_AND_IMAGES = """
<html>
<body>
    <h1>Title</h1>
    <p>Hello <a href="http://example.com">link</a></p>

    <table>
        <tr>
            <th>Column A</th>
            <th>Column B</th>
        </tr>
        <tr>
            <td>
                Cell with image:
                <img src="images/img_table.png" alt="Table image">
            </td>
            <td>Plain cell</td>
        </tr>
    </table>

    <ul>
        <li>
            List item with image:
            <img src="images/img_list.png" alt="List image">
        </li>
        <li>Second item</li>
    </ul>

    <p>
        Remote image stays as-is:
        <img src="https://lh3.googleusercontent.com/remote.png" alt="Remote">
    </p>
</body>
</html>
"""


def _build_html_body() -> str:
    return HTML_WITH_TABLE_AND_LISTS_AND_IMAGES


def test_google_zip_conversion(tmp_path: Path):
    zip_path = tmp_path / "test_doc.zip"
    html_content = """
    <html>
    <body>
        <h1>Title</h1>
        <p>Hello <a href="http://example.com">link</a></p>
        <img src="images/img1.png" alt="Test image">
    </body>
    </html>
    """

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("test_doc.html", html_content)
        zf.writestr("images/img1.png", b"fake_png_data")

    out_dir = tmp_path / "out"
    res = convert_file(zip_path, target_dir=out_dir)

    assert res.success
    assert res.images == 1

    out_md = out_dir / "hm_test_doc_zip.md"
    assert out_md.is_file()

    content = out_md.read_text(encoding="utf-8")
    assert "# Title" in content
    assert "Hello [link](http://example.com)" in content
    assert "![Test image](hm_images_test_doc_zip/img_000.png)" in content

    img_file = out_dir / "hm_images_test_doc_zip" / "img_000.png"
    assert img_file.is_file()
    assert img_file.read_bytes() == b"fake_png_data"


def test_html_images_inside_tables_and_lists(tmp_path: Path):
    """Images nested inside table cells and list items must be emitted as
    Markdown image links, and remote URLs must be left untouched."""
    html_path = tmp_path / "inline_images.html"
    html_path.write_text(_build_html_body(), encoding="utf-8")

    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "img_table.png").write_bytes(b"table_png")
    (tmp_path / "images" / "img_list.png").write_bytes(b"list_png")

    out_dir = tmp_path / "out"
    res = convert_file(html_path, target_dir=out_dir)

    assert res.success
    assert res.images == 2

    out_md = out_dir / "hm_inline_images_html.md"
    assert out_md.is_file()

    content = out_md.read_text(encoding="utf-8")
    assert "![Table image](hm_images_inline_images_html/img_000.png)" in content
    assert "![List image](hm_images_inline_images_html/img_001.png)" in content
    assert "![Remote](https://lh3.googleusercontent.com/remote.png)" in content
    assert "Hello [link](http://example.com)" in content


def test_google_zip_without_images_folder(tmp_path: Path):
    """Google Drive can export a ZIP without an images/ folder. The conversion
    must still succeed and leave the original image src untouched."""
    zip_path = tmp_path / "no_images.zip"
    html_content = """
    <html>
    <body>
        <h1>Title without images</h1>
        <p>Plain text content.</p>
        <img src="images/missing.png" alt="Missing image">
    </body>
    </html>
    """

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("no_images.html", html_content)

    out_dir = tmp_path / "out"
    res = convert_file(zip_path, target_dir=out_dir)

    assert res.success
    assert res.images == 0

    out_md = out_dir / "hm_no_images_zip.md"
    assert out_md.is_file()

    content = out_md.read_text(encoding="utf-8")
    assert "# Title without images" in content
    assert "![Missing image](images/missing.png)" in content


def test_data_image_is_written_to_disk(tmp_path: Path):
    """An HTML export that inlines every picture as a base64 data URI must not
    keep the huge payload in the Markdown; it is extracted to a file instead."""
    encoded = base64.b64encode(b"fake png bytes").decode("ascii")
    html_path = tmp_path / "data_img.html"
    html_path.write_text(
        f"<html><body><p><img src=\"data:image/png;base64,{encoded}\" alt=\"Inline\"></p></body></html>",
        encoding="utf-8",
    )

    out_dir = tmp_path / "out"
    res = convert_file(html_path, target_dir=out_dir)

    assert res.success
    assert res.images == 1

    out_md = out_dir / "hm_data_img_html.md"
    assert out_md.is_file()
    content = out_md.read_text(encoding="utf-8")
    assert "![Inline](hm_images_data_img_html/img_000.png)" in content
    assert "data:image/" not in content

    img_file = out_dir / "hm_images_data_img_html" / "img_000.png"
    assert img_file.is_file()
    assert img_file.read_bytes() == b"fake png bytes"
