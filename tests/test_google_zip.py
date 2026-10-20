import zipfile
from pathlib import Path
from hammerdown.core import convert_file

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
    assert "![Test image](hm_images_test_doc_1.png)" in content

    img_file = out_dir / "hm_images_test_doc_1.png"
    assert img_file.is_file()
    assert img_file.read_bytes() == b"fake_png_data"
