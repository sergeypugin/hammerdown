from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
from typing import Callable, Literal

from .presentation import convert_pptx
from .spreadsheet import convert_xlsx
from .word import convert_docx
from hammerdown.core.path_utils import get_images_dir_name

logger = logging.getLogger("hammerdown")
ProgressCallback = Callable[[int, int, str], None]
AttemptStatus = Literal["converted", "not_found", "failed", "no_output"]


@dataclass(frozen=True)
class _ConversionAttempt:
    converter: str
    status: AttemptStatus
    path: str | None = None
    detail: str = ""


def _format_process_output(stdout: str | None, stderr: str | None) -> str:
    details = " ".join(part.strip() for part in (stdout or "", stderr or "") if part and part.strip())
    if len(details) > 1200:
        return details[:1197] + "..."
    return details


def _find_soffice() -> str | None:
    """Find the LibreOffice executable in PATH and common installation locations."""
    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if executable:
        return executable

    candidates: list[Path] = []
    if os.name == "nt":
        for variable in ("PROGRAMW6432", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(variable)
            if base:
                candidates.append(Path(base) / "LibreOffice" / "program" / "soffice.exe")
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.extend(
                [
                    Path(local_app_data) / "Programs" / "LibreOffice" / "program" / "soffice.exe",
                    Path(local_app_data) / "LibreOffice" / "program" / "soffice.exe",
                ]
            )
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            candidates.append(Path(user_profile) / "scoop" / "apps" / "libreoffice" / "current" / "program" / "soffice.exe")
        chocolatey_install = os.environ.get("ChocolateyInstall")
        if chocolatey_install:
            candidates.append(Path(chocolatey_install) / "bin" / "soffice.exe")

        try:
            import winreg

            registry_locations = (
                r"Software\LibreOffice\UNO\InstallPath",
                r"Software\WOW6432Node\LibreOffice\UNO\InstallPath",
            )
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for location in registry_locations:
                    try:
                        with winreg.OpenKey(hive, location) as key:
                            value, _ = winreg.QueryValueEx(key, "")
                        install_path = Path(str(value))
                        candidates.extend(
                            [
                                install_path / "soffice.exe",
                                install_path / "program" / "soffice.exe",
                            ]
                        )
                    except OSError:
                        continue
        except ImportError:
            pass
    elif os.name == "posix" and os.uname().sysname == "Darwin":
        candidates.append(Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"))

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            return str(resolved)
    return None


def _find_powershell() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")


def _com_unavailable(detail: str) -> bool:
    lowered = detail.lower()
    return "class not registered" in lowered or "0x80040154" in lowered


def _convert_via_soffice_attempt(file_path: str, out_ext: str) -> _ConversionAttempt:
    soffice_bin = _find_soffice()
    if not soffice_bin:
        return _ConversionAttempt("LibreOffice", "not_found", detail="LibreOffice executable was not found")

    temp_dir = tempfile.mkdtemp()
    user_dir_uri = Path(temp_dir).resolve().as_uri()
    cmd = [
        soffice_bin,
        f"-env:UserInstallation={user_dir_uri}",
        "--headless",
        "--convert-to",
        out_ext,
        "--outdir",
        temp_dir,
        file_path,
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)
        converted_file = Path(temp_dir) / f"{Path(file_path).stem}.{out_ext}"
        output = _format_process_output(result.stdout, result.stderr)
        if converted_file.is_file():
            return _ConversionAttempt("LibreOffice", "converted", str(converted_file), output)
        detail = "LibreOffice finished without creating the converted file"
        if output:
            detail = f"{detail}: {output}"
        return _ConversionAttempt("LibreOffice", "no_output", detail=detail)
    except subprocess.CalledProcessError as exc:
        detail = _format_process_output(exc.stdout, exc.stderr) or f"process exited with code {exc.returncode}"
        return _ConversionAttempt("LibreOffice", "failed", detail=detail)
    except subprocess.TimeoutExpired:
        return _ConversionAttempt("LibreOffice", "failed", detail="conversion timed out after 120 seconds")
    except FileNotFoundError as exc:
        return _ConversionAttempt("LibreOffice", "not_found", detail=f"could not start LibreOffice: {exc}")
    except OSError as exc:
        return _ConversionAttempt("LibreOffice", "failed", detail=f"could not start LibreOffice: {exc}")


def _convert_via_ms_office_nt_attempt(file_path: str, out_ext: str) -> _ConversionAttempt:
    powershell = _find_powershell()
    if not powershell:
        return _ConversionAttempt("Microsoft Office", "not_found", detail="PowerShell was not found")

    app_map = {
        "docx": (
            "Word.Application",
            "SaveAs2",
            16,
            "$app.Documents.Open($source, $false, $true, $false)",
            True,
        ),
        "xlsx": (
            "Excel.Application",
            "SaveAs",
            51,
            "$app.Workbooks.Open($source, 0, $true)",
            True,
        ),
        "pptx": (
            "PowerPoint.Application",
            "SaveAs",
            24,
            "$app.Presentations.Open($source, $true, $false, $false)",
            False,
        ),
    }
    app_id, save_method, file_format, open_expression, hide_app = app_map[out_ext]

    def quote_ps(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    temp_dir = tempfile.mkdtemp()
    temp_file = Path(temp_dir) / f"{Path(file_path).stem}.{out_ext}"
    source = quote_ps(str(Path(file_path).resolve()))
    destination = quote_ps(str(temp_file.resolve()))
    ps_cmd = f"""
    $ErrorActionPreference = 'Stop'
    $app = $null
    $document = $null
    try {{
        $app = New-Object -ComObject {app_id}
        if ({str(hide_app).lower()}) {{ $app.Visible = $false }}
        if ($app.PSObject.Properties['DisplayAlerts']) {{ $app.DisplayAlerts = 0 }}
        $source = {source}
        $destination = {destination}
        $document = {open_expression}
        $document.{save_method}($destination, {file_format})
        $document.Close()
    }} finally {{
        if ($null -ne $document) {{ try {{ $document.Close() }} catch {{ }} }}
        if ($null -ne $app) {{ try {{ $app.Quit() }} catch {{ }} }}
    }}
    """

    try:
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        output = _format_process_output(result.stdout, result.stderr)
        if temp_file.is_file():
            return _ConversionAttempt("Microsoft Office", "converted", str(temp_file), output)
        detail = "Microsoft Office finished without creating the converted file"
        if output:
            detail = f"{detail}: {output}"
        return _ConversionAttempt("Microsoft Office", "no_output", detail=detail)
    except subprocess.CalledProcessError as exc:
        detail = _format_process_output(exc.stdout, exc.stderr) or f"process exited with code {exc.returncode}"
        status: AttemptStatus = "not_found" if _com_unavailable(detail) else "failed"
        return _ConversionAttempt("Microsoft Office", status, detail=detail)
    except subprocess.TimeoutExpired:
        return _ConversionAttempt("Microsoft Office", "failed", detail="conversion timed out after 120 seconds")
    except FileNotFoundError as exc:
        return _ConversionAttempt("Microsoft Office", "not_found", detail=f"PowerShell could not be started: {exc}")
    except OSError as exc:
        return _ConversionAttempt("Microsoft Office", "failed", detail=f"PowerShell could not be started: {exc}")


def _log_failed_attempt(attempt: _ConversionAttempt, file_name: str) -> None:
    if attempt.status == "not_found":
        return
    detail = attempt.detail or "no additional details"
    logger.warning("%s conversion for %s: %s", attempt.converter, file_name, detail)


def _convert_legacy_office(file_path: str, out_ext: str) -> str | None:
    file_name = Path(file_path).name
    attempts: list[_ConversionAttempt] = []
    if os.name == "nt":
        microsoft = _convert_via_ms_office_nt_attempt(file_path, out_ext)
        attempts.append(microsoft)
        if microsoft.status == "converted":
            return microsoft.path
        _log_failed_attempt(microsoft, file_name)

    libreoffice = _convert_via_soffice_attempt(file_path, out_ext)
    attempts.append(libreoffice)
    if libreoffice.status == "converted":
        return libreoffice.path
    _log_failed_attempt(libreoffice, file_name)

    available_attempts = [attempt for attempt in attempts if attempt.status != "not_found"]
    if available_attempts:
        details = "; ".join(
            f"{attempt.converter}: {attempt.detail or attempt.status}"
            for attempt in available_attempts
        )
        logger.error("Could not convert %s: legacy office conversion failed (%s)", file_name, details)
    elif os.name == "nt":
        logger.error(
            "Could not convert %s: legacy formats require LibreOffice or Microsoft Office, "
            "but no usable converter was found",
            file_name,
        )
    else:
        logger.error(
            "Could not convert %s: legacy formats require LibreOffice, but no usable converter was found",
            file_name,
        )
    return None


def convert_doc(
    doc_path: str,
    out_dir: str,
    progress_callback: ProgressCallback | None = None,
) -> tuple[str | None, int]:
    img_dir_name = get_images_dir_name(doc_path)
    if zipfile.is_zipfile(doc_path):
        try:
            res = convert_docx(doc_path, out_dir, images_dir_name=img_dir_name, progress_callback=progress_callback)
            if res[0] is not None:
                return res
            logger.warning("DOCX-compatible file %s did not produce Markdown; trying legacy conversion", Path(doc_path).name)
        except Exception as exc:
            logger.warning("DOCX-compatible parsing failed for %s: %s; trying legacy conversion", Path(doc_path).name, exc)

    converted = _convert_legacy_office(doc_path, "docx")
    if converted:
        return convert_docx(converted, out_dir, images_dir_name=img_dir_name, progress_callback=progress_callback)
    return None, 0


def convert_xls(
    xls_path: str,
    out_dir: str,
    progress_callback: ProgressCallback | None = None,
) -> tuple[str | None, int]:
    if zipfile.is_zipfile(xls_path):
        try:
            res = convert_xlsx(xls_path, out_dir, progress_callback=progress_callback)
            if res[0] is not None:
                return res
            logger.warning("XLSX-compatible file %s did not produce Markdown; trying legacy conversion", Path(xls_path).name)
        except Exception as exc:
            logger.warning("XLSX-compatible parsing failed for %s: %s; trying legacy conversion", Path(xls_path).name, exc)

    converted = _convert_legacy_office(xls_path, "xlsx")
    if converted:
        return convert_xlsx(converted, out_dir, progress_callback=progress_callback)
    return None, 0


def convert_ppt(
    ppt_path: str,
    out_dir: str,
    progress_callback: ProgressCallback | None = None,
) -> tuple[str | None, int]:
    if zipfile.is_zipfile(ppt_path):
        try:
            res = convert_pptx(ppt_path, out_dir, progress_callback=progress_callback)
            if res[0] is not None:
                return res
            logger.warning("PPTX-compatible file %s did not produce Markdown; trying legacy conversion", Path(ppt_path).name)
        except Exception as exc:
            logger.warning("PPTX-compatible parsing failed for %s: %s; trying legacy conversion", Path(ppt_path).name, exc)

    converted = _convert_legacy_office(ppt_path, "pptx")
    if converted:
        return convert_pptx(converted, out_dir, progress_callback=progress_callback)
    return None, 0
