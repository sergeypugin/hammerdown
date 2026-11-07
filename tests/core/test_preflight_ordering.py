from __future__ import annotations

from pathlib import Path

import pytest

import hammerdown.cli
import hammerdown.batch as batch


def test_cli_conflict_rejects_before_batch_or_acquisition(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("text", encoding="utf-8")
    called = False

    def unexpected(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("batch/acquisition must not run")

    monkeypatch.setattr(hammerdown.cli, "run_batch", unexpected)
    with pytest.raises(SystemExit) as exc:
        hammerdown.cli.main(["--tokens", "--merge", "out.md", str(source)])
    assert exc.value.code == 2
    assert not called


def test_invalid_filter_rejects_before_acquisition(monkeypatch, tmp_path: Path) -> None:
    called = False

    def unexpected(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("acquisition must not run")

    monkeypatch.setattr(batch, "acquire_inputs", unexpected)
    with pytest.raises(ValueError, match="invalid filter pattern"):
        batch.convert_files(["https://github.com/o/r/tree/main"], include=["unterminated\""])
    assert not called


def test_invalid_local_input_blocks_remote_acquisition(monkeypatch, tmp_path: Path) -> None:
    called = False

    def unexpected(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("remote acquisition must not run")

    monkeypatch.setattr(batch, "acquire_inputs", unexpected)
    assert hammerdown.cli.main([
        "https://github.com/o/r/tree/main",
        str(tmp_path / "missing.txt"),
        "--tokens",
    ]) == 1
    assert not called


def test_existing_owner_repo_path_wins_over_github_shorthand(tmp_path: Path, monkeypatch) -> None:
    local = tmp_path / "owner" / "repo"
    local.mkdir(parents=True)
    source = local / "notes.txt"
    source.write_text("local", encoding="utf-8")
    called = False

    def unexpected(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("existing local path must not be acquired remotely")

    monkeypatch.setattr(batch, "acquire_github", unexpected)
    args = type("Args", (), {
        "files": [str(local)], "merge": None, "merge_auto": False,
        "tree": True, "dir_struct": True, "all_formats": False,
        "overwrite": False, "output_dir": None, "include": [], "exclude": [],
        "include_gitignored": False, "stdout": False, "confirm": False,
        "skip_existing": False, "coordinator": False, "context_worker": False,
        "right_click": False, "tokens": False, "report_time": False,
    })()
    # Direct batch call is intentionally avoided: tree+dir-struct is a CLI conflict.
    assert hammerdown.cli.main(["--dir-struct", str(local)]) == 0
    assert not called


def test_dir_struct_is_no_write_and_reports_tree(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "folder"
    root.mkdir()
    (root / "notes.txt").write_text("notes", encoding="utf-8")
    (root / "ignored.bin").write_bytes(b"binary")
    monkeypatch.setattr(batch, "convert_file", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not convert")))

    assert hammerdown.cli.main(["--dir-struct", str(root)]) == 0
    output = capsys.readouterr().out
    assert "notes.txt" in output
    assert not (root / "hm_notes_txt.md").exists()


def test_dir_struct_allows_github_shorthand_only_in_structure_mode(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_acquire(value, destination, **kwargs):
        calls.append(value)
        raise ValueError("stop")

    monkeypatch.setattr(batch, "acquire_github", fake_acquire)
    assert hammerdown.cli.main(["--dir-struct", "owner/repo"]) == 1
    assert calls == ["owner/repo"]
