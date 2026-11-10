from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

import hammerdown.batch as batch_module
import hammerdown.cli
from hammerdown.batch import convert_files


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


def test_fresh_merge_target_does_not_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path)
    target = tmp_path / "hammerdowned.md"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", FakeStdin(tty=False))

    def fail_prompt(target: Path) -> bool:
        raise AssertionError("prompt must not run for a fresh target")

    monkeypatch.setattr(batch_module, "confirm_merge_overwrite", fail_prompt)

    assert convert_files([source], merge=target) == 0
    assert "source text" in target.read_text(encoding="utf-8")


def test_existing_merge_target_with_yes_overwrites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path)
    target = tmp_path / "hammerdowned.md"
    target.write_text("previous merge\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", FakeStdin(tty=False))

    assert convert_files([source], merge=target, yes=True) == 0
    assert "source text" in target.read_text(encoding="utf-8")


def test_existing_merge_target_with_no_skips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path)
    target = tmp_path / "hammerdowned.md"
    target.write_text("previous merge\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    stdin = FakeStdin(tty=False, answers=["y\n"])
    monkeypatch.setattr(sys, "stdin", stdin)

    assert convert_files([source], merge=target, no=True) == 0
    assert stdin.prompts == 0
    assert target.read_text(encoding="utf-8") == "previous merge\n"


def test_existing_merge_target_non_tty_fails_fast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    source = _source(tmp_path)
    target = tmp_path / "hammerdowned.md"
    target.write_text("previous merge\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", FakeStdin(tty=False))

    with caplog.at_level(logging.ERROR, logger="hammerdown"):
        assert convert_files([source], merge=target) == 1

    assert "merge target hammerdowned.md already exists; re-run with --skip-existing to keep it, --yes to overwrite it, or -m <path> for a different file" in caplog.text
    assert target.read_text(encoding="utf-8") == "previous merge\n"


def test_existing_merge_target_interactive_no_answer_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _source(tmp_path)
    target = tmp_path / "hammerdowned.md"
    target.write_text("previous merge\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    stdin = FakeStdin(tty=True, answers=["n\n"])
    monkeypatch.setattr(sys, "stdin", stdin)

    assert convert_files([source], merge=target) == 0
    assert target.read_text(encoding="utf-8") == "previous merge\n"
    assert stdin.prompts == 1
    assert "merge target hammerdowned.md already exists." in capsys.readouterr().err


def test_existing_merge_target_prompt_eof_fails_fast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    source = _source(tmp_path)
    target = tmp_path / "hammerdowned.md"
    target.write_text("previous merge\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    stdin = FakeStdin(tty=True)
    monkeypatch.setattr(sys, "stdin", stdin)

    with caplog.at_level(logging.ERROR, logger="hammerdown"):
        assert convert_files([source], merge=target) == 1

    assert "re-run with --skip-existing to keep it, --yes to overwrite it" in caplog.text
    assert target.read_text(encoding="utf-8") == "previous merge\n"
    assert stdin.prompts == 1


def test_existing_merge_target_prompt_interrupt_fails_fast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    source = _source(tmp_path)
    target = tmp_path / "hammerdowned.md"
    target.write_text("previous merge\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    def raise_interrupt() -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", raise_interrupt)

    with caplog.at_level(logging.ERROR, logger="hammerdown"):
        assert convert_files([source], merge=target) == 1

    assert "re-run with --skip-existing to keep it, --yes to overwrite it" in caplog.text
    assert target.read_text(encoding="utf-8") == "previous merge\n"


def test_existing_merge_target_interactive_empty_answer_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    target = tmp_path / "hammerdowned.md"
    target.write_text("previous merge\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    stdin = FakeStdin(tty=True, answers=["\n"])
    monkeypatch.setattr(sys, "stdin", stdin)

    assert convert_files([source], merge=target) == 0
    assert target.read_text(encoding="utf-8") == "previous merge\n"
    assert stdin.prompts == 1


def test_existing_merge_target_interactive_yes_answer_overwrites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path)
    target = tmp_path / "hammerdowned.md"
    target.write_text("previous merge\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    stdin = FakeStdin(tty=True, answers=["y\n"])
    monkeypatch.setattr(sys, "stdin", stdin)

    assert convert_files([source], merge=target) == 0
    assert "source text" in target.read_text(encoding="utf-8")


def test_existing_merge_target_interactive_invalid_answer_reasks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path)
    target = tmp_path / "hammerdowned.md"
    target.write_text("previous merge\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    stdin = FakeStdin(tty=True, answers=["maybe\n", "n\n"])
    monkeypatch.setattr(sys, "stdin", stdin)

    assert convert_files([source], merge=target) == 0
    assert target.read_text(encoding="utf-8") == "previous merge\n"
    assert stdin.prompts == 2


def test_skip_existing_still_skips_existing_merge_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path)
    target = tmp_path / "hammerdowned.md"
    target.write_text("previous merge\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", FakeStdin(tty=False))

    assert convert_files([source], merge=target, skip_existing=True) == 0
    assert target.read_text(encoding="utf-8") == "previous merge\n"


def test_tree_mode_existing_target_with_yes_overwrites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path)
    target = tmp_path / "hammerdowned.md"
    target.write_text("previous tree\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", FakeStdin(tty=False))

    assert hammerdown.cli.main(["--tree", "--yes", str(source)]) == 0
    assert "source text" in target.read_text(encoding="utf-8")


def test_tree_mode_existing_target_non_tty_fails_fast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    source = _source(tmp_path)
    target = tmp_path / "hammerdowned.md"
    target.write_text("previous tree\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", FakeStdin(tty=False))

    with caplog.at_level(logging.ERROR, logger="hammerdown"):
        assert hammerdown.cli.main(["--tree", str(source)]) == 1

    assert "merge target hammerdowned.md already exists" in caplog.text
    assert target.read_text(encoding="utf-8") == "previous tree\n"


def test_yes_with_skip_existing_raises_value_error(tmp_path: Path) -> None:
    source = _source(tmp_path)
    with pytest.raises(ValueError, match="yes cannot be combined with skip_existing"):
        convert_files([source], merge="hammerdowned.md", yes=True, skip_existing=True)


def test_yes_with_no_raises_value_error(tmp_path: Path) -> None:
    source = _source(tmp_path)
    with pytest.raises(ValueError, match="yes cannot be combined with no"):
        convert_files([source], merge="hammerdowned.md", yes=True, no=True)


@pytest.mark.parametrize("argv", [["-y", "-n"], ["-y", "--skip-existing"]])
def test_cli_rejects_yes_conflicts(tmp_path: Path, argv: list[str]) -> None:
    source = _source(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        hammerdown.cli.main([*argv, "--merge", "hammerdowned.md", str(source)])
    assert excinfo.value.code == 2
