from __future__ import annotations

import logging
import os
from pathlib import Path

import hammerdown.parsers.office.legacy as legacy


def test_legacy_conversion_reports_missing_converters(tmp_path: Path, monkeypatch, caplog) -> None:
    source = tmp_path / "broken.doc"
    source.write_bytes(b"not a document")
    missing = legacy._ConversionAttempt("Microsoft Office", "not_found", detail="not installed")
    monkeypatch.setattr(legacy, "_convert_via_ms_office_nt_attempt", lambda *args: missing)
    monkeypatch.setattr(
        legacy,
        "_convert_via_soffice_attempt",
        lambda *args: legacy._ConversionAttempt("LibreOffice", "not_found", detail="not installed"),
    )

    with caplog.at_level(logging.ERROR, logger="hammerdown"):
        result = legacy._convert_legacy_office(str(source), "docx")

    assert result is None
    assert "no usable converter was found" in caplog.text
    assert "legacy office conversion failed" not in caplog.text


def test_legacy_conversion_preserves_converter_failure_reason(tmp_path: Path, monkeypatch, caplog) -> None:
    source = tmp_path / "broken.doc"
    source.write_bytes(b"not a document")
    monkeypatch.setattr(
        legacy,
        "_convert_via_ms_office_nt_attempt",
        lambda *args: legacy._ConversionAttempt(
            "Microsoft Office", "failed", detail="document is corrupted"
        ),
    )
    monkeypatch.setattr(
        legacy,
        "_convert_via_soffice_attempt",
        lambda *args: legacy._ConversionAttempt(
            "LibreOffice", "failed", detail="source file could not be loaded"
        ),
    )

    with caplog.at_level(logging.ERROR, logger="hammerdown"):
        result = legacy._convert_legacy_office(str(source), "docx")

    assert result is None
    assert "legacy office conversion failed" in caplog.text
    assert "source file could not be loaded" in caplog.text
    if os.name == "nt":
        assert "document is corrupted" in caplog.text
    else:
        assert "Microsoft Office" not in caplog.text
    assert "install LibreOffice" not in caplog.text


def test_legacy_conversion_uses_successful_fallback(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "document.doc"
    source.write_bytes(b"legacy")
    expected = tmp_path / "converted.docx"
    monkeypatch.setattr(
        legacy,
        "_convert_via_ms_office_nt_attempt",
        lambda *args: legacy._ConversionAttempt("Microsoft Office", "not_found"),
    )
    monkeypatch.setattr(
        legacy,
        "_convert_via_soffice_attempt",
        lambda *args: legacy._ConversionAttempt("LibreOffice", "converted", str(expected)),
    )

    assert legacy._convert_legacy_office(str(source), "docx") == str(expected)
