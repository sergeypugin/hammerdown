from __future__ import annotations

import base64
from pathlib import Path

import pytest

from hammerdown.cli import main


def test_output_dir_preserves_nested_layout_and_extracts_images(tmp_path: Path):
    source_root = tmp_path / "source"
    nested = source_root / "nested"
    nested.mkdir(parents=True)
    source = nested / "notes.txt"
    image = base64.b64encode(b"sample image bytes").decode("ascii")
    source.write_text(f"![sample](data:image/png;base64,{image})\n", encoding="utf-8")
    output_root = tmp_path / "output"

    assert main(["-o", str(output_root), str(source_root)]) == 0

    markdown = output_root / "nested" / "hm_notes_txt.md"
    image_file = output_root / "nested" / "hm_images_notes_txt" / "embedded_img_0.png"
    assert markdown.is_file()
    assert image_file.read_bytes() == b"sample image bytes"
    assert "hm_images_notes_txt/embedded_img_0.png" in markdown.read_text(encoding="utf-8")


def test_base64_image_extraction_preserves_supported_mime_extensions(tmp_path: Path):
    svg = base64.b64encode(b"<svg></svg>").decode("ascii")
    jpeg = base64.b64encode(b"jpeg bytes").decode("ascii")
    source = tmp_path / "images.md"
    source.write_text(
        f"![svg](data:image/svg+xml;base64,{svg})\n![jpeg](data:image/jpeg;base64,{jpeg})\n",
        encoding="utf-8",
    )

    assert main([str(source)]) == 0
    output = tmp_path / "hm_images_images_md"
    assert (output / "embedded_img_0.svg").read_bytes() == b"<svg></svg>"
    assert (output / "embedded_img_1.jpeg").read_bytes() == b"jpeg bytes"
    converted = tmp_path / "hm_images_md.md"
    markdown = converted.read_text(encoding="utf-8")
    assert "hm_images_images_md/embedded_img_0.svg" in markdown
    assert "hm_images_images_md/embedded_img_1.jpeg" in markdown


def test_skip_existing_checks_output_dir_target(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "notes.txt").write_text("new content\n", encoding="utf-8")
    output_root = tmp_path / "output"
    target = output_root / "hm_notes_txt.md"
    target.parent.mkdir(parents=True)
    target.write_text("keep existing\n", encoding="utf-8")

    assert main(["--skip-existing", "-o", str(output_root), str(source_root)]) == 0
    assert target.read_text(encoding="utf-8") == "keep existing\n"


def test_merge_reads_converted_markdown_from_output_dir(tmp_path: Path):
    source_root = tmp_path / "source"
    nested = source_root / "deep"
    nested.mkdir(parents=True)
    (nested / "notes.txt").write_text("converted content\n", encoding="utf-8")
    output_root = tmp_path / "output"
    merged = output_root / "combined.md"

    assert main(["-o", str(output_root), "--merge", str(merged), str(source_root)]) == 0

    assert merged.is_file()
    content = merged.read_text(encoding="utf-8")
    assert "FILE: deep/notes.txt" in content
    assert "# notes.txt" not in content
    assert "converted content" in content


def test_merge_creates_missing_parent_directory(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("content\n", encoding="utf-8")
    merged = tmp_path / "out" / "nested" / "combined.md"

    assert main(["-m", str(merged), str(source)]) == 0
    assert merged.is_file()
    assert "FILE: notes.txt" in merged.read_text(encoding="utf-8")


def test_merge_preserves_source_h1_headings(tmp_path: Path):
    source = tmp_path / "notes.md"
    source.write_text("# Original heading\n\ntext\n", encoding="utf-8")
    merged = tmp_path / "combined.md"

    assert main(["-m", str(merged), str(source)]) == 0
    content = merged.read_text(encoding="utf-8")
    assert "FILE: notes.md" in content
    assert "# Original heading" in content
    assert "# notes.txt" not in content


def test_skip_existing_preserves_existing_merge_target(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("new source content\n", encoding="utf-8")
    merged = tmp_path / "combined.md"
    merged.write_text("keep merge output\n", encoding="utf-8")

    assert main(["--skip-existing", "--merge", str(merged), str(source)]) == 0
    assert merged.read_text(encoding="utf-8") == "keep merge output\n"


def test_output_dir_file_is_rejected(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("content\n", encoding="utf-8")
    output_file = tmp_path / "output.txt"
    output_file.write_text("not a directory\n", encoding="utf-8")

    assert main(["-o", str(output_file), str(source)]) == 1


def test_repeated_identical_output_dirs_are_allowed(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("content\n", encoding="utf-8")
    output_root = tmp_path / "output"

    assert main(["-o", str(output_root), "--output-dir", str(output_root), str(source)]) == 0
    assert (output_root / "hm_notes_txt.md").is_file()


def test_repeated_different_output_dirs_are_rejected(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("content\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main(["-o", str(tmp_path / "first"), "-o", str(tmp_path / "second"), str(source)])

    assert exc.value.code == 2


@pytest.mark.parametrize(
    "options",
    [
        ["--force", "--skip-existing"],
        ["-w", "--skip-existing"],
        ["-i", "-o", "output"],
        ["-w", "-o", "output"],
    ],
)
def test_conflicting_flags_are_rejected(tmp_path: Path, options: list[str]):
    source = tmp_path / "notes.txt"
    source.write_text("content\n", encoding="utf-8")
    normalized_options = [str(tmp_path / item) if item == "output" else item for item in options]

    with pytest.raises(SystemExit) as exc:
        main([*normalized_options, str(source)])

    assert exc.value.code == 2


def test_repeating_skip_existing_and_force_is_idempotent(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("initial\n", encoding="utf-8")
    target = tmp_path / "hm_notes_txt.md"
    target.write_text("keep existing\n", encoding="utf-8")

    assert main(["--skip-existing", "--skip-existing", str(source)]) == 0
    assert target.read_text(encoding="utf-8") == "keep existing\n"

    assert main(["--force", "--force", str(source)]) == 0
    assert target.read_text(encoding="utf-8") == "initial\n"
