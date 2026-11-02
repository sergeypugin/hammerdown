from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import hammerdown.cli

SECTION_SEPARATOR = "=" * 48

def test_tree_cli_renders_source_code_targets_with_and_without_all_formats(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    contents = {
        "source.py": "print('python')\n",
        "data.json": '{"ok": true}\n',
        "main.rs": "fn main() {}\n",
    }
    for name, content in contents.items():
        (project / name).write_text(content, encoding="utf-8")

    for all_formats in (False, True):
        output = tmp_path / f"tree-{all_formats}.md"
        args = ["--tree", "--merge", str(output)]
        if all_formats:
            args.insert(1, "--all-formats")
        assert hammerdown.cli.main([*args, str(project)]) == 0
        rendered = output.read_text(encoding="utf-8")
        for name, content in contents.items():
            assert f"FILE: {name}" in rendered
            assert content.strip() in rendered



def test_tree_writes_default_output_path_and_exact_content(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.txt").write_text("alpha\n", encoding="utf-8")
    (project / "b.md").write_text("# beta\n", encoding="utf-8")

    result = hammerdown.cli.main(["--tree", str(project)])

    assert result == 0
    output = tmp_path / "hammerdowned.md"
    assert output.is_file()
    assert not (tmp_path / "hammerdounded.md").exists()
    assert output.read_text(encoding="utf-8") == (
        "Directory structure:\n"
        "\u2514\u2500\u2500 project/\n"
        "    \u251c\u2500\u2500 a.txt\n"
        "    \u2514\u2500\u2500 b.md\n"
        "\n"
        f"{SECTION_SEPARATOR}\n"
        "FILE: a.txt\n"
        f"{SECTION_SEPARATOR}\n"
        "alpha\n"
        "\n"
        f"{SECTION_SEPARATOR}\n"
        "FILE: b.md\n"
        f"{SECTION_SEPARATOR}\n"
        "# beta\n"
    )


def test_tree_success_checks_archive_conversion_and_exact_binary_marker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    archive = tmp_path / "archive.zip"
    with ZipFile(archive, "w") as archive_file:
        archive_file.writestr("index.html", "<html><body>archive content</body></html>")

    result = hammerdown.cli.main(["--tree", "--all-formats", str(archive)])

    assert result == 0
    content = (tmp_path / "hammerdowned.md").read_text(encoding="utf-8")
    marker = "[Binary file] Can be converted with hammerdown: NO"
    assert content.count(marker) == 1
    assert "FILE: archive.zip" in content
    assert "archive content" in content


def test_tree_custom_merge_target_is_excluded_from_directory_reruns(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    source = project / "source.txt"
    source.write_text("source content\n", encoding="utf-8")
    target = project / "custom.md"

    assert hammerdown.cli.main(["--tree", "--merge", str(target), str(project)]) == 0
    first_content = target.read_text(encoding="utf-8")
    assert "FILE: source.txt" in first_content
    assert "FILE: custom.md" not in first_content

    assert hammerdown.cli.main(["--tree", "--merge", str(target), str(project)]) == 0

    content = target.read_text(encoding="utf-8")
    assert "FILE: source.txt" in content
    assert "FILE: custom.md" not in content


def test_tree_failure_checks_result_marker_and_concrete_error(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.chdir(tmp_path)
    archive = tmp_path / "archive.zip"
    archive.write_bytes(b"not a zip archive")

    result = hammerdown.cli.main(["--tree", "--all-formats", str(archive)])

    assert result == 1
    content = (tmp_path / "hammerdowned.md").read_text(encoding="utf-8")
    assert content.count("[Binary file] Can be converted with hammerdown: NO") == 1
    assert "[!] File conversion failed: conversion failed for archive.zip" in content

    output = capsys.readouterr().out
    assert "Error list (1)" in output
    assert "archive.zip" in output
    assert "conversion failed for archive.zip" in output
