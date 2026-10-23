# -*- mode: python ; coding: utf-8 -*-
# pyright: reportMissingImports=false, reportMissingModuleSource=false, reportUndefinedVariable=false
import hashlib
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all
from tiktoken.load import read_file_cached

cache_dir = Path(SPECPATH) / "build" / "tiktoken-cache"
bpe_url = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
bpe_cache_file = cache_dir / hashlib.sha1(bpe_url.encode()).hexdigest()
cache_dir.mkdir(parents=True, exist_ok=True)
bpe_cache_file.write_bytes(read_file_cached(bpe_url))
os.environ["TIKTOKEN_CACHE_DIR"] = str(cache_dir)
import tiktoken

tiktoken.get_encoding("cl100k_base")
if not bpe_cache_file.is_file():
    raise RuntimeError(f"tiktoken cache file was not created: {bpe_cache_file}")

datas = [(str(bpe_cache_file), "data-gym-cache")]
binaries = []
hiddenimports = ["tiktoken_ext.openai_public"]
tmp_ret = collect_all("pymupdf")
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all("pymupdf4llm")
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all("onnxruntime")
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all("tiktoken")
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all("regex")
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all("rich")
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all("hammerdown")
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

a = Analysis(
    ["src/hammerdown/__main__.py"],
    # The entry script is executed by PyInstaller as a top-level __main__
    # module, so it cannot use relative imports. src/ goes on the search path
    # to make the hammerdown package importable in the frozen app.
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=os.environ.get("HAMMERDOWN_EXECUTABLE", "hammerdown"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Windows Explorer launches one process per selected file, so the binary
    # must not own a console: a GUI-subsystem executable attaches to the
    # caller's terminal when there is one and stays silent otherwise. Set
    # HAMMERDOWN_CONSOLE=1 for a local build that always shows a console.
    # Linux and macOS executables keep console=True; the flag is a Windows
    # PE-subsystem switch and does not change how Unix binaries behave.
    console=not (os.name == "nt" and os.environ.get("HAMMERDOWN_CONSOLE", "0") != "1"),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets/icon.ico"],
)
