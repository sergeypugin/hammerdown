from __future__ import annotations

import base64
from pathlib import Path

import hammerdown.core as core
from hammerdown.cli import main
from hammerdown.core.discovery import discover_paths, discover_tree


def _image_uri(value: str) -> str:
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def test_normal_conversion_replaces_deterministic_markdown_and_assets(tmp_path: Path) -> None:
    source = tmp_path / "file.txt"
    source.write_text("first\n", encoding="utf-8")

    assert core.convert_file(source)
    target = tmp_path / "hm_file_txt.md"
    assert target.read_text(encoding="utf-8") == "first\n"

    source.write_text("second\n", encoding="utf-8")
    assert core.convert_file(source)
    assert target.read_text(encoding="utf-8") == "second\n"


def test_skip_existing_only_checks_target_and_preserves_all_outputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.md"
    source.write_text(
        f"![one]({_image_uri('one')})\n![two]({_image_uri('two')})\n",
        encoding="utf-8",
    )
    assert core.convert_file(source)

    target = tmp_path / "hm_source_md.md"
    assets = tmp_path / "hm_images_source_md"
    target.write_text("stale markdown\n", encoding="utf-8")
    (assets / "stale.png").write_bytes(b"stale asset")
    before_target = target.read_bytes()
    before_assets = {path.relative_to(assets): path.read_bytes() for path in assets.rglob("*") if path.is_file()}

    def unexpected_conversion(*_args, **_kwargs):
        raise AssertionError("skip-existing must not invoke the converter")

    monkeypatch.setitem(core.CONVERTERS, ".md", unexpected_conversion)
    source.write_text(f"![new]({_image_uri('new')})\n", encoding="utf-8")

    result = core.convert_file(source, skip_existing=True)

    assert result.success
    assert result.output_path == target
    assert target.read_bytes() == before_target
    assert {path.relative_to(assets): path.read_bytes() for path in assets.rglob("*") if path.is_file()} == before_assets


def test_markdown_output_directory_is_rejected_without_replacing_contents(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("new content\n", encoding="utf-8")
    target = tmp_path / "hm_source_txt.md"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("keep me\n", encoding="utf-8")

    result = core.convert_file(source)

    assert not result.success
    assert target.is_dir()
    assert marker.read_text(encoding="utf-8") == "keep me\n"


def test_skip_existing_rejects_directory_target_without_modifying_contents(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("new content\n", encoding="utf-8")
    target = tmp_path / "hm_source_txt.md"
    target.mkdir()
    marker = target / "stale.txt"
    marker.write_text("stale contents\n", encoding="utf-8")

    result = core.convert_file(source, skip_existing=True)

    assert not result.success
    assert result.output_path == target
    assert "is a directory" in (result.error or "")
    assert target.is_dir()
    assert marker.read_text(encoding="utf-8") == "stale contents\n"


def test_generated_outputs_are_silent_in_directory_discovery(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("source\n", encoding="utf-8")
    generated = tmp_path / "hm_source_txt.md"
    generated.write_text("generated\n", encoding="utf-8")
    merged = tmp_path / "hammerdowned.md"
    merged.write_text("merged\n", encoding="utf-8")

    for discover in (discover_paths, discover_tree):
        result = discover([str(tmp_path)])

        assert {Path(target.path).name for target in result.targets} == {source.name}
        assert result.skipped == []
        assert {Path(path).name for path in result.generated_outputs} == {
            generated.name,
            merged.name,
        }


def test_direct_generated_output_is_not_converted_or_nested(tmp_path: Path) -> None:
    generated = tmp_path / "hm_file_ext.md"
    generated.write_text("already generated\n", encoding="utf-8")

    result = core.convert_file(generated)

    assert not result
    assert result.error == "generated output is not an input resource: hm_file_ext.md"
    assert not (tmp_path / "hm_hm_file_ext_md.md").exists()


def test_direct_hammerdowned_output_is_not_converted(tmp_path: Path) -> None:
    generated = tmp_path / "hammerdowned.md"
    generated.write_text("already merged\n", encoding="utf-8")

    result = core.convert_file(generated)

    assert not result
    assert "generated output is not an input resource" in (result.error or "")
    assert not (tmp_path / "hm_hammerdowned_md.md").exists()


def test_generated_only_directory_is_reported_as_no_input(tmp_path: Path, capsys) -> None:
    (tmp_path / "hm_file_txt.md").write_text("generated\n", encoding="utf-8")
    (tmp_path / "hammerdowned.md").write_text("merged\n", encoding="utf-8")

    assert main([str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "generated" in captured.out.lower()
    assert "skipped files" not in captured.out.lower()


def test_generated_output_is_an_error_when_selected_directly(tmp_path: Path, capsys) -> None:
    generated = tmp_path / "hm_file_txt.md"
    generated.write_text("generated\n", encoding="utf-8")

    assert main([str(generated)]) == 1
    captured = capsys.readouterr()
    assert "generated output is not an input" in captured.out.lower()
    assert "skipped files" not in captured.out.lower()
    assert not (tmp_path / "hm_hm_file_txt_md.md").exists()


def test_output_dir_skip_checks_target_instead_of_source(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = source_root / "file.txt"
    source.write_text("new source\n", encoding="utf-8")
    output_root = tmp_path / "output"
    target = output_root / "hm_file_txt.md"
    target.parent.mkdir()
    target.write_text("existing target\n", encoding="utf-8")

    assert main(["--skip-existing", "-o", str(output_root), str(source_root)]) == 0
    assert target.read_text(encoding="utf-8") == "existing target\n"
    assert not (source_root / "hm_file_txt.md").exists()


def test_custom_merge_target_is_excluded_from_directory_reruns(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = project / "source.txt"
    source.write_text("source content\n", encoding="utf-8")
    target = project / "custom.md"

    assert main(["--merge", str(target), str(project)]) == 0
    first_content = target.read_text(encoding="utf-8")
    assert "FILE: source.txt" in first_content
    assert "FILE: custom.md" not in first_content

    assert main(["--merge", str(target), str(project)]) == 0

    content = target.read_text(encoding="utf-8")
    assert "FILE: source.txt" in content
    assert "FILE: custom.md" not in content


def test_explicit_merge_target_as_source_still_errors(tmp_path: Path, caplog) -> None:
    target = tmp_path / "custom.md"
    target.write_text("existing merge output\n", encoding="utf-8")

    assert main(["--merge", str(target), str(target)]) == 1
    assert "merge target cannot be one of the source files" in caplog.text.lower()
