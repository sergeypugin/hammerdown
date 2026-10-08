from __future__ import annotations

import argparse
import csv
import io
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Sequence

__version__ = "1.1.0"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("hammerdown")


def normalize_path(path_str: str | os.PathLike[str]) -> str:
    value = os.fspath(path_str).strip().strip("'\"")
    if not value:
        return ""

    if os.name == "nt" and value.lower().startswith("/mnt/"):
        parts = value.split("/")
        if len(parts) >= 3 and len(parts[2]) == 1:
            value = f"{parts[2].upper()}:\\" + "\\".join(parts[3:])
    elif os.name != "nt":
        match = re.match(r"^([A-Za-z]):[\\/](.*)$", value)
        if match:
            value = f"/mnt/{match.group(1).lower()}/{match.group(2).replace(chr(92), '/') }"

    return str(Path(value).expanduser().resolve())


def convert_pdf_or_ebook(file_path: str, out_dir: str, stem: str) -> tuple[str | None, int]:
    try:
        import pymupdf  # type: ignore
        import pymupdf4llm  # type: ignore
    except ImportError:
        logger.error("PDF support requires pymupdf and pymupdf4llm")
        return None, 0

    img_dir = Path(out_dir) / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    saved_imgs = 0
    extracted_xrefs: set[int] = set()
    with pymupdf.open(file_path) as doc:
        for page_number in range(len(doc)):
            page = doc[page_number]
            for img_info in page.get_images():
                xref = img_info[0]
                if xref in extracted_xrefs:
                    continue

                img_data = doc.extract_image(xref)
                if img_data["width"] < 50 or img_data["height"] < 50:
                    continue

                img_name = f"{stem}_p{page_number:03d}_xref{xref}.{img_data['ext']}"
                (img_dir / img_name).write_bytes(img_data["image"])
                extracted_xrefs.add(xref)
                saved_imgs += 1

    md_text = pymupdf4llm.to_markdown(file_path, write_images=False)
    return str(md_text), saved_imgs


def convert_docx(docx_path: str, out_dir: str) -> tuple[str | None, int]:
    try:
        import docx  # type: ignore
    except ImportError:
        logger.error("DOCX support requires python-docx")
        return None, 0

    doc = docx.Document(docx_path)
    lines: list[str] = []
    for paragraph in doc.paragraphs:
        if paragraph.text.strip():
            lines.append(paragraph.text)

    for table in doc.tables:
        if not table.rows:
            continue
        header_cells = [cell.text.strip() for cell in table.rows[0].cells]
        lines.append(f"| {' | '.join(header_cells)} |")
        lines.append(f"| {' | '.join(['---'] * len(header_cells))} |")
        for row in table.rows[1:]:
            row_text = " | ".join(cell.text.strip() for cell in row.cells)
            lines.append(f"| {row_text} |")

    return "\n\n".join(lines), 0


def convert_xlsx(xlsx_path: str, out_dir: str) -> tuple[str | None, int]:
    try:
        import openpyxl  # type: ignore
    except ImportError:
        logger.error("XLSX support requires openpyxl")
        return None, 0

    workbook = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    lines: list[str] = []
    for sheet in workbook.sheetnames:
        lines.append(f"# Sheet: {sheet}\n")
        rows = workbook[sheet].iter_rows(values_only=True)
        header = next(rows, None)
        if header is None:
            continue
        header_cells = [str(cell) if cell is not None else "" for cell in header]
        lines.append(f"| {' | '.join(header_cells)} |")
        lines.append(f"| {' | '.join(['---'] * len(header_cells))} |")
        for row in rows:
            if any(row):
                row_text = " | ".join(str(cell) if cell is not None else "" for cell in row)
                lines.append(f"| {row_text} |")
        lines.append("\n")
    workbook.close()
    return "\n".join(lines), 0


def convert_pptx(pptx_path: str, out_dir: str) -> tuple[str | None, int]:
    try:
        from pptx import Presentation  # type: ignore
    except ImportError:
        logger.error("PPTX support requires python-pptx")
        return None, 0

    presentation = Presentation(pptx_path)
    lines: list[str] = []
    for slide_idx, slide in enumerate(list(presentation.slides), start=1):
        lines.append(f"## Slide {slide_idx}\n")
        for shape in slide.shapes:
            if getattr(shape, "has_table", False):
                table = getattr(shape, "table", None)
                if table is None:
                    continue
                rows = list(table.rows)
                if rows:
                    header = [cell.text.strip() for cell in rows[0].cells]
                    lines.append(f"| {' | '.join(header)} |")
                    lines.append(f"| {' | '.join(['---'] * len(header))} |")
                    for row in rows[1:]:
                        lines.append(f"| {' | '.join(cell.text.strip() for cell in row.cells)} |")
            elif getattr(shape, "has_text_frame", False):
                text_frame = getattr(shape, "text_frame", None)
                if text_frame is None:
                    continue
                for paragraph in text_frame.paragraphs:
                    text = paragraph.text.strip()
                    if text:
                        lines.append(text)
        lines.append("")

    return "\n".join(lines), 0


def _convert_via_soffice(file_path: str, out_ext: str) -> str | None:
    soffice_bin = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice_bin and os.name == "nt":
        common_paths = [
            Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "LibreOffice" / "program" / "soffice.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")) / "LibreOffice" / "program" / "soffice.exe",
        ]
        for p in common_paths:
            if p.is_file():
                soffice_bin = str(p)
                break

    if not soffice_bin:
        return None

    temp_dir = tempfile.mkdtemp()
    cmd = [
        soffice_bin,
        "--headless",
        "--convert-to",
        out_ext,
        "--outdir",
        temp_dir,
        file_path,
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        converted_file = Path(temp_dir) / f"{Path(file_path).stem}.{out_ext}"
        if converted_file.is_file():
            return str(converted_file)
    except Exception:
        pass
    return None


def convert_doc(doc_path: str, out_dir: str) -> tuple[str | None, int]:
    if zipfile.is_zipfile(doc_path):
        return convert_docx(doc_path, out_dir)

    converted = _convert_via_soffice(doc_path, "docx")
    if converted:
        return convert_docx(converted, out_dir)

    if os.name == "nt":
        try:
            import win32com.client  # type: ignore
            word = win32com.client.Dispatch("Word.Application")
            word.Visible = False
            temp_file = Path(tempfile.mkdtemp()) / f"{Path(doc_path).stem}.docx"
            doc = word.Documents.Open(str(Path(doc_path).resolve()))
            doc.SaveAs2(str(temp_file.resolve()), FileFormat=16)
            doc.Close()
            word.Quit()
            if temp_file.is_file():
                return convert_docx(str(temp_file), out_dir)
        except Exception:
            pass

    logger.error("Legacy .doc format requires LibreOffice or Microsoft Word to be installed")
    return None, 0


def convert_xls(xls_path: str, out_dir: str) -> tuple[str | None, int]:
    if zipfile.is_zipfile(xls_path):
        return convert_xlsx(xls_path, out_dir)

    converted = _convert_via_soffice(xls_path, "xlsx")
    if converted:
        return convert_xlsx(converted, out_dir)

    if os.name == "nt":
        try:
            import win32com.client  # type: ignore
            excel = win32com.client.Dispatch("Excel.Application")
            excel.Visible = False
            temp_file = Path(tempfile.mkdtemp()) / f"{Path(xls_path).stem}.xlsx"
            wb = excel.Workbooks.Open(str(Path(xls_path).resolve()))
            wb.SaveAs(str(temp_file.resolve()), FileFormat=51)
            wb.Close()
            excel.Quit()
            if temp_file.is_file():
                return convert_xlsx(str(temp_file), out_dir)
        except Exception:
            pass

    logger.error("Legacy .xls format requires LibreOffice or Microsoft Excel to be installed")
    return None, 0


def convert_ppt(ppt_path: str, out_dir: str) -> tuple[str | None, int]:
    if zipfile.is_zipfile(ppt_path):
        return convert_pptx(ppt_path, out_dir)

    converted = _convert_via_soffice(ppt_path, "pptx")
    if converted:
        return convert_pptx(converted, out_dir)

    if os.name == "nt":
        try:
            import win32com.client  # type: ignore
            powerpoint = win32com.client.Dispatch("PowerPoint.Application")
            temp_file = Path(tempfile.mkdtemp()) / f"{Path(ppt_path).stem}.pptx"
            ppt = powerpoint.Presentations.Open(str(Path(ppt_path).resolve()), WithWindow=False)
            ppt.SaveAs(str(temp_file.resolve()), FileFormat=24)
            ppt.Close()
            powerpoint.Quit()
            if temp_file.is_file():
                return convert_pptx(str(temp_file), out_dir)
        except Exception:
            pass

    logger.error("Legacy .ppt format requires LibreOffice or Microsoft PowerPoint to be installed")
    return None, 0


def convert_txt_or_md(file_path: str, out_dir: str) -> tuple[str | None, int]:
    raw = Path(file_path).read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1251", "cp1252", "latin-1"):
        try:
            return raw.decode(enc), 0
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), 0


def convert_csv(csv_path: str, out_dir: str) -> tuple[str | None, int]:
    if zipfile.is_zipfile(csv_path):
        try:
            import openpyxl  # type: ignore
            data = Path(csv_path).read_bytes()
            workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
            lines: list[str] = []
            for sheet in workbook.sheetnames:
                lines.append(f"# Sheet: {sheet}\n")
                rows = workbook[sheet].iter_rows(values_only=True)
                header = next(rows, None)
                if header is None:
                    continue
                header_cells = [str(cell) if cell is not None else "" for cell in header]
                lines.append(f"| {' | '.join(header_cells)} |")
                lines.append(f"| {' | '.join(['---'] * len(header_cells))} |")
                for row in rows:
                    if any(row):
                        row_text = " | ".join(str(cell) if cell is not None else "" for cell in row)
                        lines.append(f"| {row_text} |")
                lines.append("\n")
            workbook.close()
            return "\n".join(lines), 0
        except Exception:
            pass

    raw = Path(csv_path).read_bytes()
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1251", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        text = raw.decode("utf-8", errors="replace")

    sample = text[:2048]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except Exception:
        if ";" in sample and "," not in sample:
            delimiter = ";"
        elif "\t" in sample and "," not in sample:
            delimiter = "\t"

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return "", 0

    lines = []
    header = [cell.strip() for cell in rows[0]]
    lines.append(f"| {' | '.join(header)} |")
    lines.append(f"| {' | '.join(['---'] * len(header))} |")
    for row in rows[1:]:
        if any(cell.strip() for cell in row):
            cells = [cell.strip() for cell in row]
            lines.append(f"| {' | '.join(cells)} |")

    return "\n".join(lines), 0


def convert_file(file_path: str | os.PathLike[str]) -> bool:
    normalized_path = normalize_path(file_path)
    source = Path(normalized_path)
    if not source.is_file():
        logger.error("File not found: %s", normalized_path)
        return False

    stem = source.stem
    extension = source.suffix.lower()
    ext_clean = extension.lstrip(".")

    folder_name = f"MD_{stem}_{ext_clean}" if ext_clean else f"MD_{stem}"
    out_dir = source.parent / folder_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / f"{stem}.md"

    converters = {
        ".pdf": convert_pdf_or_ebook,
        ".epub": convert_pdf_or_ebook,
        ".mobi": convert_pdf_or_ebook,
        ".fb2": convert_pdf_or_ebook,
        ".xps": convert_pdf_or_ebook,
        ".docx": convert_docx,
        ".doc": convert_doc,
        ".xlsx": convert_xlsx,
        ".xls": convert_xls,
        ".pptx": convert_pptx,
        ".ppt": convert_ppt,
        ".csv": convert_csv,
        ".txt": convert_txt_or_md,
        ".md": convert_txt_or_md,
        ".log": convert_txt_or_md,
    }
    converter = converters.get(extension)
    if converter is None:
        logger.error("Unsupported format: %s", extension or "(no extension)")
        return False

    logger.info("Processing %s...", source.name)
    started_at = time.monotonic()
    try:
        if extension in {".pdf", ".epub", ".mobi", ".fb2", ".xps"}:
            md_text, saved_images = converter(str(source), str(out_dir), stem)
        else:
            md_text, saved_images = converter(str(source), str(out_dir))
        if md_text is None:
            return False

        # Trim trailing whitespace on each line and ensure a single final newline
        normalized_text = md_text.replace("\r\n", "\n").replace("\r", "\n")
        trimmed_lines = [line.rstrip() for line in normalized_text.split("\n")]
        cleaned_md = "\n".join(trimmed_lines).rstrip() + "\n"
        out_md.write_text(cleaned_md, encoding="utf-8", newline="\n")
        logger.info(
            "Completed %s in %.2fs (saved %d images)",
            source.name,
            time.monotonic() - started_at,
            saved_images,
        )
        return True
    except Exception:
        logger.exception("Failed to convert %s", source.name)
        return False


def _installed_command() -> tuple[Path, str]:
    if os.name == "nt":
        app_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Programs" / "hammerdown"
    else:
        app_dir = Path.home() / ".local" / "share" / "hammerdown"
    app_dir.mkdir(parents=True, exist_ok=True)

    if getattr(sys, "frozen", False):
        suffix = ".exe" if os.name == "nt" else ""
        target = app_dir / f"hammerdown{suffix}"
        if Path(sys.executable).resolve() != target.resolve():
            shutil.move(sys.executable, target)
        return app_dir, str(target)

    target = app_dir / "converter.py"
    shutil.copy2(Path(__file__).resolve(), target)
    return app_dir, f'"{sys.executable}" "{target}"'


def _install_windows(command: str) -> None:
    import winreg

    key_path = r"Software\Classes\SystemFileAssociations\.pdf\shell\Convert to Markdown"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Convert to Markdown")
        winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, command.split('"')[1])
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'{command} --quiet "%1"')


def _install_unix(command: str) -> None:
    bin_dir = Path.home() / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher = bin_dir / "hammerdown"
    launcher.write_text(f"#!/bin/sh\nexec {command} \"$@\"\n", encoding="utf-8")
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    if sys.platform.startswith("linux"):
        nautilus_dir = Path.home() / ".local" / "share" / "nautilus" / "scripts"
        nautilus_dir.mkdir(parents=True, exist_ok=True)
        script = nautilus_dir / "Convert to Markdown"
        script.write_text('exec "$HOME/.local/bin/hammerdown" --quiet "$@"\n', encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install() -> bool:
    try:
        _, command = _installed_command()
        if os.name == "nt":
            _install_windows(command)
        else:
            _install_unix(command)
        logger.info("hammerdown installed. Restart the file manager if its menu does not update.")
        return True
    except (OSError, ImportError) as exc:
        logger.error("Installation failed: %s", exc)
        return False


def _remove_registry_tree(root: Any, path: str) -> None:
    import winreg

    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _remove_registry_tree(root, f"{path}\\{child}")
        winreg.DeleteKey(root, path)
    except FileNotFoundError:
        pass


def uninstall() -> bool:
    try:
        if os.name == "nt":
            import winreg

            _remove_registry_tree(
                winreg.HKEY_CURRENT_USER,
                r"Software\Classes\SystemFileAssociations\.pdf\shell\Convert to Markdown",
            )
            install_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Programs" / "hammerdown"
        else:
            (Path.home() / ".local" / "bin" / "hammerdown").unlink(missing_ok=True)
            (Path.home() / ".local" / "share" / "nautilus" / "scripts" / "Convert to Markdown").unlink(missing_ok=True)
            install_dir = Path.home() / ".local" / "share" / "hammerdown"

        try:
            if install_dir.exists():
                shutil.rmtree(install_dir)
        except OSError:
            logger.warning("Could not remove installed program files at %s", install_dir)
        logger.info("hammerdown integration uninstalled")
        return True
    except (OSError, ImportError) as exc:
        logger.error("Uninstallation failed: %s", exc)
        return False


def update() -> bool:
    if not getattr(sys, "frozen", False):
        logger.info("Updating Python package via pip...")
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "git+https://github.com/sergeypugin/hammerdown.git"]
        try:
            subprocess.check_call(cmd)
            logger.info("Successfully updated hammerdown package.")
            return True
        except subprocess.CalledProcessError as exc:
            logger.error("Failed to update via pip: %s", exc)
            return False

    import json
    import urllib.request

    url = "https://api.github.com/repos/sergeypugin/hammerdown/releases/latest"
    req = urllib.request.Request(url, headers={"User-Agent": "hammerdown"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        latest_tag = data.get("tag_name", "").lstrip("v")
        if latest_tag and latest_tag <= __version__:
            logger.info("hammerdown is already at the latest version (%s)", __version__)
            return True

        logger.info("New version available: %s (current: %s)", latest_tag, __version__)
        asset_name = "hammerdown-windows-x64.exe" if os.name == "nt" else "hammerdown-linux-x64"
        if sys.platform == "darwin":
            asset_name = "hammerdown-macos-arm64" if "arm" in os.uname().machine.lower() else "hammerdown-macos-x64"

        download_url = None
        for asset in data.get("assets", []):
            if asset.get("name") == asset_name:
                download_url = asset.get("browser_download_url")
                break

        if not download_url:
            logger.error("No release asset found matching %s", asset_name)
            return False

        logger.info("Downloading %s...", download_url)
        temp_exe = Path(tempfile.gettempdir()) / f"hammerdown-update{'.exe' if os.name == 'nt' else ''}"
        with urllib.request.urlopen(download_url, timeout=30) as resp, open(temp_exe, "wb") as f:
            f.write(resp.read())

        target = Path(sys.executable)
        if os.name == "nt":
            old_exe = target.with_suffix(".exe.old")
            if old_exe.exists():
                try:
                    old_exe.unlink()
                except OSError:
                    pass
            target.rename(old_exe)
            shutil.copy2(temp_exe, target)
        else:
            shutil.copy2(temp_exe, target)
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        logger.info("hammerdown successfully updated to version %s!", latest_tag)
        return True
    except Exception as exc:
        logger.error("Failed to update: %s", exc)
        return False


def _select_files() -> Sequence[str]:
    if os.name == "nt":
        try:
            ps_script = (
                "Add-Type -AssemblyName PresentationFramework | Out-Null;"
                "$dialog = New-Object Microsoft.Win32.OpenFileDialog;"
                "$dialog.Filter = 'Supported Documents|*.pdf;*.docx;*.doc;*.xlsx;*.xls;*.pptx;*.ppt;*.txt;*.md;*.log;*.csv|All Files (*.*)|*.*';"
                "$dialog.Multiselect = $true;"
                "$dialog.Title = 'Select documents to convert';"
                "if ($dialog.ShowDialog() -eq $true) { $dialog.FileNames }"
            )
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                return [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
        except Exception:
            pass

    try:
        from tkinter import Tk, filedialog

        root = Tk()
        root.withdraw()
        try:
            return filedialog.askopenfilenames(title="Select documents to convert")
        finally:
            root.destroy()
    except Exception as exc:
        logger.error("No files were provided and the file dialog is unavailable: %s", exc)
        return ()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hammerdown",
        description="Convert PDF and office documents to Markdown",
    )
    parser.add_argument("--version", action="version", version=f"hammerdown {__version__}")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--install", action="store_true", help="Install the file-manager integration")
    action.add_argument("--uninstall", action="store_true", help="Remove the file-manager integration")
    action.add_argument("--update", action="store_true", help="Update md-maker to the latest version")
    parser.add_argument("--quiet", action="store_true", help="Suppress routine conversion messages")
    parser.add_argument("files", nargs="*", help="Files to convert")
    args = parser.parse_args(argv)

    if args.quiet:
        logger.setLevel(logging.ERROR)
    if args.install:
        return 0 if install() else 1
    if args.uninstall:
        return 0 if uninstall() else 1
    if args.update:
        return 0 if update() else 1

    files = args.files or _select_files()
    if not files:
        return 0

    started_at = time.monotonic()
    results = [convert_file(file_path) for file_path in files]
    failed_count = results.count(False)
    if len(files) > 1 and not args.quiet:
        logger.info(
            "Batch conversion finished in %.2fs: %d succeeded, %d failed",
            time.monotonic() - started_at,
            len(files) - failed_count,
            failed_count,
        )
    return 1 if failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
