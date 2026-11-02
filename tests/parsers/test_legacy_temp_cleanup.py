from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

import hammerdown.parsers.office.legacy as legacy


class _Completed:
    stdout = ""
    stderr = ""


def _temp_dir_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[Path]]:
    created: list[Path] = []

    def make_temp_dir() -> str:
        directory = tmp_path / f"temp-{len(created)}"
        directory.mkdir()
        created.append(directory)
        return str(directory)

    monkeypatch.setattr(legacy.tempfile, "mkdtemp", make_temp_dir)
    return tmp_path, created


@pytest.mark.parametrize(
    ("attempt", "extension", "executable_attr", "output_name"),
    [
        (legacy._convert_via_soffice_attempt, "docx", "_find_soffice", "source.docx"),
        (legacy._convert_via_ms_office_nt_attempt, "docx", "_find_powershell", "source.docx"),
    ],
)
def test_success_cleanup_waits_for_consumer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attempt,
    extension: str,
    executable_attr: str,
    output_name: str,
) -> None:
    _, created = _temp_dir_factory(tmp_path, monkeypatch)
    monkeypatch.setattr(legacy, executable_attr, lambda: "converter")

    def run(*args, **kwargs):
        output = created[0] / output_name
        output.write_bytes(b"converted")
        return _Completed()

    monkeypatch.setattr(legacy.subprocess, "run", run)
    result = attempt(str(tmp_path / "source.doc"), extension)

    assert result.status == "converted"
    assert result.path is not None
    assert Path(result.path).is_file()
    assert created[0].is_dir()

    assert result.cleanup is not None
    result.cleanup()
    assert not created[0].exists()


@pytest.mark.parametrize(
    ("attempt", "extension", "executable_attr"),
    [
        (legacy._convert_via_soffice_attempt, "docx", "_find_soffice"),
        (legacy._convert_via_ms_office_nt_attempt, "docx", "_find_powershell"),
    ],
)
def test_no_output_cleans_temp_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attempt,
    extension: str,
    executable_attr: str,
) -> None:
    _, created = _temp_dir_factory(tmp_path, monkeypatch)
    monkeypatch.setattr(legacy, executable_attr, lambda: "converter")
    monkeypatch.setattr(legacy.subprocess, "run", lambda *args, **kwargs: _Completed())

    result = attempt(str(tmp_path / "source.doc"), extension)

    assert result.status == "no_output"
    assert not created[0].exists()


@pytest.mark.parametrize("exception", [subprocess.CalledProcessError(1, "converter"), OSError("start failed")])
def test_soffice_failure_cleans_temp_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exception: Exception,
) -> None:
    _, created = _temp_dir_factory(tmp_path, monkeypatch)
    monkeypatch.setattr(legacy, "_find_soffice", lambda: "converter")
    monkeypatch.setattr(legacy.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(exception))

    result = legacy._convert_via_soffice_attempt(str(tmp_path / "source.doc"), "docx")

    assert result.status == "failed"
    assert not created[0].exists()


def test_ms_office_timeout_cleans_temp_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, created = _temp_dir_factory(tmp_path, monkeypatch)
    monkeypatch.setattr(legacy, "_find_powershell", lambda: "powershell")
    monkeypatch.setattr(
        legacy.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("powershell", 120)),
    )

    result = legacy._convert_via_ms_office_nt_attempt(str(tmp_path / "source.xls"), "xlsx")

    assert result.status == "failed"
    assert not created[0].exists()


def test_consuming_conversion_cleans_after_parser_returns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, created = _temp_dir_factory(tmp_path, monkeypatch)
    temp_dir = tmp_path / "temp-0"
    temp_dir.mkdir()
    created.append(temp_dir)
    monkeypatch.setattr(
        legacy,
        "_convert_via_soffice_attempt",
        lambda *args: legacy._ConversionAttempt(
            "LibreOffice",
            "converted",
            str(temp_dir / "source.docx"),
            cleanup=lambda: legacy._cleanup_temp_dir(str(temp_dir)),
        ),
    )
    (temp_dir / "source.docx").write_bytes(b"converted")
    seen: list[str] = []
    monkeypatch.setattr(
        legacy,
        "convert_docx",
        lambda path, *args, **kwargs: (seen.append(path) or ("markdown", 0)),
    )
    monkeypatch.setattr(legacy.zipfile, "is_zipfile", lambda path: False)

    result = legacy.convert_doc(str(tmp_path / "source.doc"), str(tmp_path))

    assert result == ("markdown", 0)
    assert seen == [str(temp_dir / "source.docx")]
    assert not temp_dir.exists()
