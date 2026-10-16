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


def test_merge_rejects_output_dir(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "notes.txt").write_text("converted content\n", encoding="utf-8")
    output_root = tmp_path / "output"
    merged = tmp_path / "combined.md"

    with pytest.raises(SystemExit) as exc:
        main(["-o", str(output_root), "--merge", str(merged), str(source_root)])

    assert exc.value.code == 2
    assert not merged.exists()


def test_merge_writes_assets_under_namespaced_tree_without_per_file_markdown(tmp_path: Path):
    source = tmp_path / "file1.md"
    nested = tmp_path / "src"
    nested.mkdir()
    nested_source = nested / "f2.md"
    image = base64.b64encode(b"file one image").decode("ascii")
    nested_image = base64.b64encode(b"file two image").decode("ascii")
    source.write_text(f"![one](data:image/png;base64,{image})\n", encoding="utf-8")
    nested_source.write_text(f"![two](data:image/png;base64,{nested_image})\n", encoding="utf-8")
    merged = tmp_path / "o.md"

    assert main(["--merge", str(merged), str(source), str(nested_source)]) == 0

    asset_root = tmp_path / "hm_merged_into_o_images"
    first_image = asset_root / "hm_images_file1_md" / "embedded_img_0.png"
    second_image = asset_root / "src" / "hm_images_f2_md" / "embedded_img_0.png"
    assert first_image.read_bytes() == b"file one image"
    assert second_image.read_bytes() == b"file two image"
    assert not (tmp_path / "hm_file1_md.md").exists()
    assert not (nested / "hm_f2_md.md").exists()

    content = merged.read_text(encoding="utf-8")
    assert "hm_merged_into_o_images/hm_images_file1_md/embedded_img_0.png" in content
    assert "hm_merged_into_o_images/src/hm_images_f2_md/embedded_img_0.png" in content


def test_merge_rejects_overwrite(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("content\n", encoding="utf-8")
    merged = tmp_path / "combined.md"

    with pytest.raises(SystemExit) as exc:
        main(["--overwrite", "--merge", str(merged), str(source)])

    assert exc.value.code == 2


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
        ["-w", "--skip-existing"],
        ["-w", "-o", "output"],
        ["--stdout", "--output-dir", "output"],
        ["--stdout", "--overwrite"],
        ["--stdout", "--skip-existing"],
        ["--stdout", "--merge", "merged.md"],
        ["--confirm"],
    ],
)
def test_conflicting_flags_are_rejected(tmp_path: Path, options: list[str]):
    source = tmp_path / "notes.txt"
    source.write_text("content\n", encoding="utf-8")
    normalized_options = [str(tmp_path / item) if item == "output" else item for item in options]

    with pytest.raises(SystemExit) as exc:
        main([*normalized_options, str(source)])

    assert exc.value.code == 2


def test_include_can_be_combined_with_output_directory(tmp_path: Path, capsys):
    root = tmp_path / "source"
    root.mkdir()
    (root / "keep.txt").write_text("keep", encoding="utf-8")
    (root / "other.txt").write_text("other", encoding="utf-8")
    output = tmp_path / "output"

    assert main(["-i", "keep", "-o", str(output), str(root)]) == 0
    capsys.readouterr()

    assert (output / "hm_keep_txt.md").is_file()
    assert not (output / "hm_other_txt.md").exists()
