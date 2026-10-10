# Architecture

This document describes the high-level architecture and processing pipeline of `hammerdown`.

## Pipeline Overview

When you convert a document with `hammerdown`, processing follows three stages:

```mermaid
flowchart TD
    subgraph S1 [1. Input Handling]
        A[Input Document] --> B[CLI / File Dialog / Python API]
        B --> C[Path Normalization]
    end

    subgraph S2 [2. Content Parsing & Extraction]
        C --> D{Format Router}

        D -->|PDF, EPUB| P_PDF[PDF Engine<br>Text layout & XREF images]
        D -->|DOCX, DOC, ODT| P_DOC[Word & ODF Engine<br>Math to LaTeX & Charts to SVG]
        D -->|XLSX, XLS| P_SHEET[Spreadsheet Engine<br>Matrix segmentation to tables]
        D -->|PPTX, PPT| P_PPT[Presentation Engine<br>Slides & text frames]
        D -->|MD, TXT, LOG, CSV| P_TXT[Text Engine<br>Encoding & base64 images]

        P_PDF --> IMG[Extracted Images]
        P_DOC --> SVG[Chart SVGs]
        P_TXT --> B64[Decoded Images]

        P_PDF --> MD_RAW[Raw Markdown Content]
        P_DOC --> MD_RAW
        P_SHEET --> MD_RAW
        P_PPT --> MD_RAW
        P_TXT --> MD_RAW
    end

    subgraph S3 [3. Post-Processing & Output]
        IMG --> ASSETS[hammerdown_images_stem_ext/]
        SVG --> ASSETS
        B64 --> ASSETS

        MD_RAW --> CLEAN[Whitespace Trimming & Newline Normalization]
        CLEAN --> OUT_FILE[stem_ext.md]
    end
```

## Pipeline Stages

The conversion pipeline consists of three corresponding stages:

### 1. Input Handling

- **Input Document**: source document path supplied by user or script
- **CLI / File Dialog / Python API**: parses flags (`-i`, `-f`, `-q`, `-v`), opens graphical file picker if no files are passed, or accepts direct Python calls
- **Path Normalization**: resolves Windows and WSL paths, strips quotes, and verifies file existence

### 2. Content Parsing & Extraction

- **Format Router**: detects file extension and delegates work to the corresponding parser
- **PDF Engine**: extracts document layout via PyMuPDF4LLM and original raster images by XREF via PyMuPDF
- **Word & ODF Engine**: extracts text and tables, translates equations (OMML and MathML) into LaTeX via `symbols.json`, and renders DrawingML charts as SVG
- **Spreadsheet Engine**: segments cell matrices, trims empty borders, and builds clean Markdown tables
- **Presentation Engine**: converts slides, headers, and text frames into structured sections
- **Text Engine**: auto-detects encodings and decodes inline base64 images into standalone image files

### 3. Post-Processing & Output

- **Asset Storage (`hammerdown_images_<stem>_<ext>/`)**: writes raster images, SVG charts, and decoded pictures to disk
- **Whitespace Trimming & Newline Normalization**: converts line endings to `\n`, strips trailing whitespace on every line, and guarantees a final newline
- **File Output (`<stem>_<ext>.md`)**: writes the final Markdown document next to the source file (or overwrites plain-text source files when `-w`/`--overwrite` is enabled)

## Cascade Parser Pipeline for Legacy Formats

Documents with legacy extensions (`.doc`, `.xls`, `.ppt`) are processed through a multi-tier fallback cascade designed primarily for execution speed and broad format compatibility.

```mermaid
flowchart TD
    INPUT[Legacy Office File<br>.doc / .xls / .ppt] --> CHECK{Is Zip Container?}

    CHECK -->|Yes| TIER1[Tier 1: Pure-Python Parser<br>python-docx / openpyxl / python-pptx]
    TIER1 -->|Success ~170 ms| SUCCESS[Extracted Markdown & Assets]
    TIER1 -->|Failed / Not OpenXML| TIER2

    CHECK -->|No / True Binary| TIER2[Tier 2: Headless LibreOffice<br>soffice -env:UserInstallation]
    TIER2 -->|Converted to OpenXML| TIER1
    TIER2 -->|Not Installed / Failed| WIN_CHECK{Is Windows?}

    WIN_CHECK -->|Yes| TIER3[Tier 3: Windows COM Automation<br>win32com.client Word/Excel/PowerPoint]
    TIER3 -->|Converted to OpenXML| TIER1
    TIER3 -->|Failed / Office Unavailable| FAIL[Error: Office Converter Required]

    WIN_CHECK -->|No| FAIL
```

Launching external office suites (such as LibreOffice or Microsoft Word) incurs high startup latency and system overhead. Whenever files are structured as XML archives underneath, parsing them directly in pure Python takes ~170 ms compared to ~5,320 ms via LibreOffice `--` delivering over 30x faster conversions without requiring external software installations.

The processing cascade proceeds as follows:
1. tier 1 (fast in-memory Python parsing): inspects whether the input is a valid zip package. If parsing succeeds via `python-docx`, `openpyxl`, or `python-pptx`, conversion completes in milliseconds in pure Python
2. tier 2 (headless LibreOffice conversion): if in-memory parsing fails or the file is true binary legacy format (OLE2 or BIFF), `hammerdown` invokes headless LibreOffice (`soffice`) with isolated user profiles (`-env:UserInstallation`) to export modern OpenXML formats
3. tier 3 (Windows COM automation): on Windows systems where LibreOffice is not found, the converter falls back to native Microsoft Word, Excel, or PowerPoint automation through `win32com.client`
