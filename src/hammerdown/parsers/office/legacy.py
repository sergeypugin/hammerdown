from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
from typing import Callable

from .presentation import convert_pptx
from .spreadsheet import convert_xlsx
from .word import convert_docx
from hammerdown.utils import get_images_dir_name

logger = logging.getLogger("hammerdown")
ProgressCallback = Callable[[int, int, str], None]


def _find_soffice() -> str | None:
    """Find LibreOffice executable path across different operating systems."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        return soffice

    if os.name == "nt":
        prog_files = [
            os.environ.get("PROGRAMFILES", "C:\\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"),
        ]
        for base in prog_files:
            path = Path(base) / "LibreOffice" / "program" / "soffice.exe"
            if path.is_file():
                return str(path)

    if os.name == "posix" and os.uname().sysname == "Darwin":
        path = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
        if path.is_file():
            return str(path)

    return None


def _convert_via_soffice(file_path: str, out_ext: str) -> str | None:
    """Convert document using LibreOffice headless mode."""
    soffice_bin = _find_soffice()
    if not soffice_bin:
        return None

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
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        converted_file = Path(temp_dir) / f"{Path(file_path).stem}.{out_ext}"
        if converted_file.is_file():
            return str(converted_file)
        logger.warning("LibreOffice did not create the converted %s file for %s", out_ext, Path(file_path).name)
        if result.stdout.strip() or result.stderr.strip():
            logger.debug("LibreOffice output: %s", (result.stdout + " " + result.stderr).strip())
    except subprocess.CalledProcessError as exc:
        details = (exc.stdout or "") + " " + (exc.stderr or "")
        logger.warning("LibreOffice failed to convert %s: %s", Path(file_path).name, details.strip() or exc)
    except OSError as exc:
        logger.warning("LibreOffice could not be started for %s: %s", Path(file_path).name, exc)
    return None


def _convert_via_ms_office_nt(file_path: str, out_ext: str) -> str | None:
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
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        if temp_file.is_file():
            return str(temp_file)
        logger.warning("Microsoft Office did not create the converted %s file for %s", out_ext, Path(file_path).name)
        if result.stdout.strip() or result.stderr.strip():
            logger.debug("Microsoft Office output: %s", (result.stdout + " " + result.stderr).strip())
    except subprocess.CalledProcessError as exc:
        details = (exc.stdout or "") + " " + (exc.stderr or "")
        logger.warning("Microsoft Office failed to convert %s: %s", Path(file_path).name, details.strip() or exc)
    except subprocess.TimeoutExpired:
        logger.warning("Microsoft Office timed out while converting %s", Path(file_path).name)
    except OSError as exc:
        logger.warning("PowerShell could not start Microsoft Office conversion for %s: %s", Path(file_path).name, exc)

    return None


def _convert_legacy_office(file_path: str, out_ext: str) -> str | None:
    if os.name == "nt":
        converted = _convert_via_ms_office_nt(file_path, out_ext)
        if converted:
            return converted
        logger.info(
            "Microsoft Office conversion was unavailable or failed for %s; trying LibreOffice",
            Path(file_path).name,
        )

    converted = _convert_via_soffice(file_path, out_ext)
    if converted:
        return converted

    logger.error(
        "Could not convert %s. Open it once in Microsoft Office to complete any first-run setup, "
        "then retry, or install LibreOffice for headless conversion.",
        Path(file_path).name,
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
        except Exception:
            pass

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
        except Exception:
            pass

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
        except Exception:
            pass

    converted = _convert_legacy_office(ppt_path, "pptx")

    if converted:
        return convert_pptx(converted, out_dir, progress_callback=progress_callback)

    return None, 0
