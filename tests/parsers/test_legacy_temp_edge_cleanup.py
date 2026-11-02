from __future__ import annotations

from pathlib import Path
import subprocess
from typing import cast

import pytest

import hammerdown.parsers.office.legacy as legacy


class _Completed:
    stdout = ""
    stderr = ""


def _temp_dir_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    created: list[Path] = []

    def make_temp_dir() -> str:
        directory = tmp_path / f"temp-{len(created)}"
        directory.mkdir()
        created.append(directory)
        return str(directory)

    monkeypatch.setattr(legacy.tempfile, "mkdtemp", make_temp_dir)
    return created


@pytest.mark.parametrize(
    ("attempt", "executable", "extension"),
    [
        (legacy._convert_via_soffice_attempt, "_find_soffice", "docx"),
        (legacy._convert_via_ms_office_nt_attempt, "_find_powershell", "xlsx"),
    ],
)
def test_setup_failure_cleans_temp_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attempt,
    executable: str,
    extension: str,
) -> None:
    created = _temp_dir_factory(tmp_path, monkeypatch)
    monkeypatch.setattr(legacy, executable, lambda: "converter")

    def fail_resolve(self: Path) -> Path:
        raise RuntimeError("path setup failed")

    monkeypatch.setattr(Path, "resolve", fail_resolve)

    with pytest.raises(RuntimeError, match="path setup failed"):
        attempt(str(tmp_path / "source.doc"), extension)

    assert len(created) == 1
    assert not created[0].exists()


@pytest.mark.parametrize("use_context_manager", [False, True])
def test_direct_conversion_result_owns_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    use_context_manager: bool,
) -> None:
    temp_dir = tmp_path / "owned"
    temp_dir.mkdir()
    converted_path = temp_dir / "source.docx"
    converted_path.write_bytes(b"converted")
    cleaned: list[bool] = []

    def cleanup() -> None:
        cleaned.append(True)
        legacy._cleanup_temp_dir(str(temp_dir))

    monkeypatch.setattr(
        legacy,
        "_convert_via_soffice_attempt",
        lambda *args: legacy._ConversionAttempt(
            "LibreOffice", "converted", str(converted_path), cleanup=cleanup
        ),
    )

    result = legacy._convert_legacy_office(str(tmp_path / "source.doc"), "docx")

    owned_result = cast(legacy._OwnedConvertedPath, result)
    assert isinstance(owned_result, str)
    assert owned_result == str(converted_path)
    assert temp_dir.exists()
    if use_context_manager:
        with owned_result as owned:
            assert owned == str(converted_path)
    else:
        owned_result.close()
    assert cleaned == [True]
    assert not temp_dir.exists()
    owned_result.close()
    assert cleaned == [True]


@pytest.mark.parametrize(
    "exception",
    [subprocess.CalledProcessError(1, "converter"), subprocess.TimeoutExpired("converter", 120)],
)
def test_direct_converter_failure_and_timeout_clean_temp_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exception: Exception,
) -> None:
    created = _temp_dir_factory(tmp_path, monkeypatch)
    monkeypatch.setattr(legacy, "_find_soffice", lambda: "converter")
    monkeypatch.setattr(
        legacy.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(exception),
    )

    result = legacy._convert_via_soffice_attempt(str(tmp_path / "source.doc"), "docx")

    assert result.status == "failed"
    assert not created[0].exists()


def test_direct_api_returns_none_after_all_converters_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.doc"
    source.write_bytes(b"legacy")
    monkeypatch.setattr(
        legacy,
        "_convert_via_ms_office_nt_attempt",
        lambda *args: legacy._ConversionAttempt("Microsoft Office", "failed"),
    )
    monkeypatch.setattr(
        legacy,
        "_convert_via_soffice_attempt",
        lambda *args: legacy._ConversionAttempt("LibreOffice", "failed"),
    )

    assert legacy._convert_legacy_office(str(source), "docx") is None


@pytest.mark.parametrize("use_context_manager", [False, True])
def test_direct_api_cleanup_is_available_for_ms_office_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    use_context_manager: bool,
) -> None:
    temp_dir = tmp_path / "ms-owned"
    temp_dir.mkdir()
    converted_path = temp_dir / "source.docx"
    converted_path.write_bytes(b"converted")
    monkeypatch.setattr(legacy, "os", type("OS", (), {"name": "nt"})())
    monkeypatch.setattr(
        legacy,
        "_convert_via_ms_office_nt_attempt",
        lambda *args: legacy._ConversionAttempt(
            "Microsoft Office",
            "converted",
            str(converted_path),
            cleanup=lambda: legacy._cleanup_temp_dir(str(temp_dir)),
        ),
    )
    monkeypatch.setattr(
        legacy,
        "_convert_via_soffice_attempt",
        lambda *args: legacy._ConversionAttempt("LibreOffice", "not_found"),
    )

    result = legacy._convert_legacy_office(str(tmp_path / "source.doc"), "docx")
    owned_result = cast(legacy._OwnedConvertedPath, result)
    assert isinstance(owned_result, str)
    if use_context_manager:
        with owned_result:
            pass
    else:
        owned_result.close()
    assert not temp_dir.exists()


@pytest.mark.parametrize("attempt", [legacy._convert_via_soffice_attempt, legacy._convert_via_ms_office_nt_attempt])
def test_converter_success_keeps_temp_dir_until_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attempt,
) -> None:
    created = _temp_dir_factory(tmp_path, monkeypatch)
    monkeypatch.setattr(legacy, "_find_soffice", lambda: "converter")
    monkeypatch.setattr(legacy, "_find_powershell", lambda: "converter")
    monkeypatch.setattr(legacy.subprocess, "run", lambda *args, **kwargs: _Completed())

    def create_output(*args, **kwargs):
        extension = "xlsx" if attempt is legacy._convert_via_ms_office_nt_attempt else "docx"
        (created[0] / f"source.{extension}").write_bytes(b"converted")
        return _Completed()

    monkeypatch.setattr(legacy.subprocess, "run", create_output)
    result = attempt(str(tmp_path / "source.doc"), "xlsx" if attempt is legacy._convert_via_ms_office_nt_attempt else "docx")

    assert result.status == "converted"
    assert created[0].exists()
    assert result.cleanup is not None
    result.cleanup()
    assert not created[0].exists()


def test_direct_api_consume_failure_still_cleans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temp_dir = tmp_path / "consume-failure"
    temp_dir.mkdir()
    converted_path = temp_dir / "source.docx"
    converted_path.write_bytes(b"converted")
    monkeypatch.setattr(
        legacy,
        "_convert_via_soffice_attempt",
        lambda *args: legacy._ConversionAttempt(
            "LibreOffice", "converted", str(converted_path), cleanup=lambda: legacy._cleanup_temp_dir(str(temp_dir))
        ),
    )

    with pytest.raises(ValueError, match="consumer failed"):
        legacy._convert_legacy_office(
            str(tmp_path / "source.doc"), "docx", lambda path: (_ for _ in ()).throw(ValueError("consumer failed"))
        )

    assert not temp_dir.exists()


@pytest.mark.parametrize("timeout", [subprocess.TimeoutExpired("converter", 120)])
def test_ms_office_timeout_cleans_temp_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    timeout: subprocess.TimeoutExpired,
) -> None:
    created = _temp_dir_factory(tmp_path, monkeypatch)
    monkeypatch.setattr(legacy, "_find_powershell", lambda: "powershell")
    monkeypatch.setattr(
        legacy.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(timeout),
    )

    result = legacy._convert_via_ms_office_nt_attempt(str(tmp_path / "source.xls"), "xlsx")

    assert result.status == "failed"
    assert not created[0].exists()


__all__ = []
