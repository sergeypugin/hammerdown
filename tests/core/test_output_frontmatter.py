from __future__ import annotations

import base64
import logging
import sys
from pathlib import Path

import pytest

import hammerdown
import hammerdown.cli
from hammerdown.batch import convert_files
from hammerdown.core.merge import (
    MergeSession,
    OutputMetadata,
    append_merged_document,
    initialize_merge_file,
    merge_asset_paths,
)
from hammerdown.core.preflight import estimate_source_tokens
from hammerdown.core.resources import token_count


class FakeStdin:
    def __init__(self, tty: bool = False, answers: list[str] | None = None):
        self.is_tty = tty
        self.answers = list(answers or [])
        self.prompts = 0

    def isatty(self) -> bool:
        return self.is_tty

    def readline(self) -> str:
        self.prompts += 1
        return self.answers.pop(0) if self.answers else ""


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "doc.txt"
    source.write_text("source text\n", encoding="utf-8")
    return source


def _frontmatter(text: str) -> list[str]:
    lines = text.split("\n")
    assert lines[0] == "---"
    end = lines.index("---", 1)
    return lines[1:end]


def test_merge_output_starts_with_frontmatter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path)
    target = tmp_path / "hammerdowned.md"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", FakeStdin())

    assert convert_files([source], merge=target) == 0

    text = target.read_text(encoding="utf-8")
    lines = text.split("\n")
    block = _frontmatter(text)
    assert "tool: 'hammerdown'" in block
    assert f"version: '{hammerdown.__version__}'" in block
    assert "mode: 'merge'" in block
    assert any(line.startswith("date: '") for line in block)
    assert f"source: '{tmp_path.as_posix()}'" in block
    assert "inputs:" in block
    assert f"  - '{source}'" in block
    assert "files: 1" in block
    assert any(line.startswith("tokens_estimate: ") for line in block)
    end = lines.index("---", 1)
    assert lines[end + 1] == ""
    assert lines[end + 2] == "Directory structure:"


def test_tree_output_records_tree_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", FakeStdin())

    assert hammerdown.cli.main(["--tree", str(source)]) == 0

    block = _frontmatter((tmp_path / "hammerdowned.md").read_text(encoding="utf-8"))
    assert "mode: 'tree'" in block
    assert "files: 1" in block


def test_folder_arguments_recorded_verbatim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "folder1").mkdir()
    (tmp_path / "folder1" / "a.txt").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "folder1" / "folder2").mkdir()
    (tmp_path / "folder1" / "folder2" / "b.txt").write_text("beta\n", encoding="utf-8")
    (tmp_path / "folder3").mkdir()
    (tmp_path / "folder3" / "c.txt").write_text("gamma\n", encoding="utf-8")
    target = tmp_path / "hammerdowned.md"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", FakeStdin())

    assert convert_files(["folder1", "folder1/folder2", "folder3"], merge=target) == 0

    block = _frontmatter(target.read_text(encoding="utf-8"))
    assert "mode: 'merge'" in block
    assert "  - 'folder1'" in block
    assert "  - 'folder1/folder2'" in block
    assert "  - 'folder3'" in block
    assert "files: 3" in block


def test_session_without_metadata_writes_no_frontmatter(tmp_path: Path) -> None:
    source = _source(tmp_path)
    target = tmp_path / "merged.md"
    owner = MergeSession(target)
    initialize_merge_file(target, [source], tmp_path, owner)
    _, asset_prefix = merge_asset_paths(source, tmp_path, target, owner)
    append_merged_document(target, source, "content", tmp_path, asset_prefix, session=owner)
    owner.finish()

    text = target.read_text(encoding="utf-8")
    assert text.startswith("Directory structure:")
    assert "content" in text


def test_initialize_uses_session_metadata(tmp_path: Path) -> None:
    source = _source(tmp_path)
    target = tmp_path / "merged.md"
    owner = MergeSession(
        target,
        metadata=OutputMetadata(mode="tree --all-formats", inputs=("folder1", "folder1/folder2")),
    )
    initialize_merge_file(target, [source], tmp_path, owner)

    block = _frontmatter(owner._state.staged_target.read_text(encoding="utf-8"))
    assert "mode: 'tree --all-formats'" in block
    assert "  - 'folder1'" in block
    assert "  - 'folder1/folder2'" in block


def test_overwrite_prompt_shows_existing_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _source(tmp_path)
    target = tmp_path / "hammerdowned.md"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", FakeStdin())
    assert convert_files([source], merge=target) == 0

    stdin = FakeStdin(tty=True, answers=["n\n"])
    monkeypatch.setattr(sys, "stdin", stdin)
    assert convert_files([source], merge=target) == 0

    err = capsys.readouterr().err
    assert "Existing output was generated with:" in err
    assert f"version: '{hammerdown.__version__}'" in err
    assert "mode: 'merge'" in err
    assert target.read_text(encoding="utf-8").startswith("---")


def test_non_tty_error_mentions_previous_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    source = _source(tmp_path)
    target = tmp_path / "hammerdowned.md"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", FakeStdin())
    assert convert_files([source], merge=target) == 0

    monkeypatch.setattr(sys, "stdin", FakeStdin(tty=False))
    with caplog.at_level(logging.ERROR, logger="hammerdown"):
        assert convert_files([source], merge=target) == 1

    assert f"hammerdown {hammerdown.__version__}" in caplog.text
    assert "mode merge" in caplog.text


def test_estimate_source_tokens_matches_report_rules(tmp_path: Path) -> None:
    text_file = tmp_path / "a.txt"
    text_file.write_text("word " * 100, encoding="utf-8")
    assert estimate_source_tokens([text_file]) == token_count("word " * 100)

    binary = tmp_path / "b.pdf"
    binary.write_bytes(b"\x00" * 4096)
    assert estimate_source_tokens([binary]) == 1024

    missing = tmp_path / "missing.pdf"
    assert estimate_source_tokens([text_file, missing]) == token_count("word " * 100)


def test_finish_recounts_tokens_from_generated_output(tmp_path: Path) -> None:
    payload = base64.b64encode(b"x" * 6000).decode("ascii")
    source = tmp_path / "doc.md"
    source.write_text(f"# Title\n\n![img](data:image/png;base64,{payload})\n", encoding="utf-8")
    target = tmp_path / "merged.md"
    owner = MergeSession(target, metadata=OutputMetadata(mode="merge"))
    initialize_merge_file(target, [source], tmp_path, owner)
    _, asset_prefix = merge_asset_paths(source, tmp_path, target, owner)
    append_merged_document(
        target,
        source,
        "# Title\n\n![img](hm_images_doc/embedded_img_1.png)\n",
        tmp_path,
        asset_prefix,
        session=owner,
    )
    owner.finish()

    text = target.read_text(encoding="utf-8")
    block = _frontmatter(text)
    value = int(next(line.split(": ", 1)[1] for line in block if line.startswith("tokens_estimate:")))
    assert value != estimate_source_tokens([source])
    body = text.split("\n---\n", 1)[1]
    assert value == token_count(body)


def test_finish_keeps_source_estimate_when_counting_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    target = tmp_path / "merged.md"
    owner = MergeSession(target, metadata=OutputMetadata(mode="merge"))
    initialize_merge_file(target, [source], tmp_path, owner)
    _, asset_prefix = merge_asset_paths(source, tmp_path, target, owner)
    append_merged_document(target, source, "content", tmp_path, asset_prefix, session=owner)
    expected = estimate_source_tokens([source])

    monkeypatch.setattr("hammerdown.core.resources.token_count", lambda _text: 0)
    owner.finish()

    assert f"tokens_estimate: {expected}" in _frontmatter(target.read_text(encoding="utf-8"))


def test_finish_discards_staging_when_errors_and_target_existed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    fake_pdf = tmp_path / "broken.pdf"
    fake_pdf.write_bytes(b"not a pdf")
    target = tmp_path / "hammerdowned.md"
    target.write_text("previous merge\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", FakeStdin())

    assert convert_files([source, fake_pdf], merge=target, yes=True) == 1

    assert target.read_text(encoding="utf-8") == "previous merge\n"
