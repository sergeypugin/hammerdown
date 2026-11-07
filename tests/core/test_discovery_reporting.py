from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

import hammerdown.cli
import hammerdown.batch as batch


class _FakePrepared:
    def __init__(self, job):
        self.job = job
        self.source = job.source
        self.output_path = job.output_path
        self.images = 0
        self.tokens = 0
        self.duration = 0.01
        self.status = "prepared"
        self.success = True
        self.error = None

    def commit(self):
        self.status = "committed"
        return self


def _selection(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "source"
    root.mkdir()
    (root / ".gitignore").write_text("hidden.txt\n", encoding="utf-8")
    hidden = root / "hidden.txt"
    hidden.write_text("hidden content", encoding="utf-8")
    visible = root / "visible.txt"
    visible.write_text("visible content", encoding="utf-8")
    return root, hidden, visible


def test_public_api_include_gitignored_selects_extra_files(tmp_path: Path, monkeypatch, capsys) -> None:
    root, hidden, visible = _selection(tmp_path)
    selected: list[list[str]] = []

    def capture(files, _raw_inputs):
        selected.append(list(files))
        return 0

    monkeypatch.setattr(batch, "run_stdout_conversion", capture)

    assert batch.convert_files([root], stdout=True) == 0
    assert batch.convert_files([root], stdout=True, include_gitignored=True) == 0

    assert {Path(path).name for path in selected[0]} == {visible.name}
    assert {Path(path).name for path in selected[1]} == {hidden.name, visible.name}
    assert hidden.name not in capsys.readouterr().err


def test_cli_include_gitignored_reaches_discovery(tmp_path: Path, monkeypatch, capsys) -> None:
    root, hidden, visible = _selection(tmp_path)
    selected: list[str] = []

    def capture(files, _raw_inputs):
        selected.extend(files)
        sys.stdout.write("markdown output")
        return 0

    monkeypatch.setattr(batch, "run_stdout_conversion", capture)

    assert hammerdown.cli.main(["--stdout", "--include-gitignored", str(root)]) == 0

    captured = capsys.readouterr()
    assert {Path(path).name for path in selected} == {hidden.name, visible.name}
    assert captured.out == "markdown output"
    assert str(root / ".gitignore") in captured.err


def test_ignore_file_report_precedes_conversion(tmp_path: Path, monkeypatch, capsys) -> None:
    root, _, visible = _selection(tmp_path)
    observed: list[str] = []

    def prepare(job, progress_callback=None):
        output = capsys.readouterr().out
        observed.append(output)
        assert "Ignore files used (1)" in output
        assert str(root / ".gitignore") in output
        return _FakePrepared(job)

    monkeypatch.setattr(batch, "_prepare_conversion", prepare)

    assert batch.convert_files([visible]) == 0
    assert observed


def test_skips_are_reported_but_gitignored_files_are_not(tmp_path: Path, monkeypatch, capsys) -> None:
    root, hidden, visible = _selection(tmp_path)
    filtered = root / "filtered.txt"
    filtered.write_text("filtered", encoding="utf-8")

    def capture(files, _raw_inputs):
        assert [Path(path).name for path in files] == [visible.name]
        sys.stdout.write("only markdown")
        return 0

    monkeypatch.setattr(batch, "run_stdout_conversion", capture)

    assert batch.convert_files([root], stdout=True, exclude=["filtered.txt"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "only markdown"
    assert "Skipped files (1)" in captured.err
    assert "filtered.txt" in captured.err
    assert hidden.name not in captured.err
    assert str(root / ".gitignore") in captured.err


def test_tree_discovery_honors_include_gitignored(tmp_path: Path, monkeypatch) -> None:
    root, hidden, _ = _selection(tmp_path)
    merged = tmp_path / "merged.md"
    converted: list[str] = []

    def convert(path, **kwargs):
        converted.append(Path(path).name)
        kwargs["completion_callback"](True, 0.01, 0, 0)
        return SimpleNamespace(success=True, markdown="content", error=None)

    monkeypatch.setattr(batch, "convert_file", convert)
    args = argparse.Namespace(
        files=[str(root)],
        merge=str(merged),
        merge_auto=False,
        tree=True,
        all_formats=False,
        overwrite=False,
        output_dir=None,
        include=[],
        exclude=[],
        include_gitignored=True,
        stdout=False,
        confirm=False,
        skip_existing=False,
        coordinator=False,
        context_worker=False,
        right_click=False,
    )

    assert batch.run_batch(args) == 0
    assert hidden.name in converted


def test_coordinator_rescan_preserves_include_gitignored(tmp_path: Path, monkeypatch) -> None:
    root, hidden, _ = _selection(tmp_path)
    discovered_flags: list[bool] = []
    actual_discover = batch.discover_paths

    def capture_discover(paths, **kwargs):
        discovered_flags.append(kwargs["include_gitignored"])
        return actual_discover(paths, **kwargs)

    class Coordinator:
        def start(self):
            return True

        def collect_files(self, _files, assembly_timeout):
            return []

        def stop(self):
            pass

    converted: list[str] = []

    monkeypatch.setattr(batch, "discover_paths", capture_discover)
    monkeypatch.setattr(batch, "IPCCoordinator", Coordinator)
    monkeypatch.setattr(batch, "hand_off_to_windows_terminal", lambda *_args: False)
    monkeypatch.setattr(batch, "_ensure_console_window", lambda: None)
    def prepare(job, progress_callback=None):
        converted.append(job.source.name)
        return _FakePrepared(job)

    monkeypatch.setattr(batch, "_prepare_conversion", prepare)
    monkeypatch.setattr("builtins.input", lambda: "")
    args = argparse.Namespace(
        files=[str(root)],
        merge=None,
        merge_auto=False,
        tree=False,
        all_formats=False,
        overwrite=False,
        output_dir=None,
        include=[],
        exclude=[],
        include_gitignored=True,
        stdout=False,
        confirm=False,
        skip_existing=False,
        coordinator=True,
        context_worker=False,
        right_click=False,
    )

    assert batch.run_batch(args) == 0
    assert discovered_flags == [True, True]
    assert hidden.name in converted


def test_include_gitignored_does_not_delegate_to_coordinator_without_option_support(
    tmp_path: Path, monkeypatch
) -> None:
    root, hidden, _ = _selection(tmp_path)
    converted: list[str] = []

    class Coordinator:
        def start(self):
            return False

    def unexpected_delegate(*_args, **_kwargs):
        raise AssertionError("include_gitignored must not be delegated without IPC support")

    monkeypatch.setattr(batch, "IPCCoordinator", Coordinator)
    monkeypatch.setattr(batch, "try_delegate_to_coordinator", unexpected_delegate)
    def prepare(job, progress_callback=None):
        converted.append(job.source.name)
        return _FakePrepared(job)

    monkeypatch.setattr(batch, "_prepare_conversion", prepare)
    monkeypatch.setattr("builtins.input", lambda: "")
    args = argparse.Namespace(
        files=[str(root)],
        merge=None,
        merge_auto=False,
        tree=False,
        all_formats=False,
        overwrite=False,
        output_dir=None,
        include=[],
        exclude=[],
        include_gitignored=True,
        stdout=False,
        confirm=False,
        skip_existing=False,
        coordinator=True,
        context_worker=False,
        right_click=False,
    )

    assert batch.run_batch(args) == 0
    assert hidden.name in converted


def test_explicit_unsupported_source_is_an_error_but_directory_skip_is_not(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    root = tmp_path / "source"
    root.mkdir()
    unsupported = root / "unsupported.bin"
    unsupported.write_bytes(b"unknown")
    monkeypatch.setattr(batch, "run_stdout_conversion", lambda *_args: 0)

    assert batch.convert_files([unsupported], stdout=True) == 1
    explicit_error = capsys.readouterr().err
    assert "unsupported format" in explicit_error

    assert batch.convert_files([root], stdout=True) == 0
    directory_skip = capsys.readouterr().err
    assert "Skipped files (1)" in directory_skip
    assert "unsupported.bin" in directory_skip
    assert "[!]" not in directory_skip
