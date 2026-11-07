from __future__ import annotations

from pathlib import Path

import hammerdown.cli
import hammerdown.batch as batch


def test_tokens_report_does_not_convert_or_write(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello report", encoding="utf-8")
    called = False

    def unexpected(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("report mode must not convert")

    monkeypatch.setattr(batch, "convert_file", unexpected)
    assert hammerdown.cli.main(["--tokens", str(source)]) == 0
    captured = capsys.readouterr()
    assert "Tokens" in captured.out
    assert "generated Markdown tokens: unavailable" in captured.out
    assert not called
    assert not (tmp_path / "source.md").exists()


def test_combined_report_modes_use_one_discovery_pass(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello report", encoding="utf-8")
    calls = 0
    actual = batch.discover_tree

    def discover(*args, **kwargs):
        nonlocal calls
        calls += 1
        return actual(*args, **kwargs)

    monkeypatch.setattr(batch, "discover_tree", discover)
    assert hammerdown.cli.main(["--tokens", "--time", "--dir-struct", str(source)]) == 0
    assert calls == 1
    output = capsys.readouterr().out
    assert "Tokens" in output
    assert "Time" in output
    assert "Structure" in output


def test_report_surfaces_remote_acquisition_error_before_conversion(tmp_path: Path, monkeypatch, capsys) -> None:
    source = "https://github.com/owner/repository/tree/main"
    monkeypatch.setattr(batch, "acquire_github", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("blocked")))
    assert hammerdown.cli.main(["--tokens", "--tree", source]) == 1
    assert "acquisition error: blocked" in capsys.readouterr().out


def test_dir_struct_surfaces_remote_acquisition_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(batch, "acquire_github", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("blocked")))
    assert hammerdown.cli.main(["--dir-struct", "owner/repository"]) == 1
    assert "acquisition error: blocked" in capsys.readouterr().out
