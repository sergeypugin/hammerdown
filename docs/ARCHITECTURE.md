# Architecture

This document describes the high-level architecture and data flow of `hammerdown`.

## Pipeline Overview

When you pass one or multiple documents to `hammerdown`, the converter runs through a straightforward pipeline:

```mermaid
flowchart TD
    subgraph L1 [Layer 1: Entrypoint & CLI]
        A[Input Document] --> B[CLI / Python API]
        B --> C[Path Normalization]
    end

    subgraph L2 [Layer 2: Specialized Parsers]
        C --> D{Format Selector}
        D -->|PDF, EPUB, MOBI| E[PDF Engine]
        D -->|DOCX, DOC, ODT| F[Word & ODF Engine]
        D -->|XLSX, XLS, CSV| G[Spreadsheet Engine]
        D -->|PPTX, PPT| H[Presentation Engine]
        D -->|MD, TXT, LOG| I[Text Engine]

        F --> F1[Math Parser: OMML & MathML to LaTeX]
        F --> F2[Chart Parser: DrawingML to Vector SVG]

        G --> G1[Table Engine: Matrix Segmentation]

        I --> I1[Base64 Image Decoder]
    end

    subgraph L3 [Layer 3: Asset Storage]
        E -->|XREF Images| J[hammerdown_images/]
        F2 -->|Chart SVG| J
        I1 -->|PNG / JPEG| J
    end

    subgraph L4 [Layer 4: Central Post-Processing in core.py]
        E --> K[Raw Markdown Text]
        F1 --> K
        F --> K
        G1 --> K
        H --> K
        I --> K

        K --> M[Line Ending & Trailing Whitespace Cleanup]
    end

    subgraph L5 [Layer 5: Disk Output]
        M --> N[Write Markdown File: stem_ext.md]
        J --> O[Extracted Asset Files]
    end
```

## System Layers

The codebase is split into three main layers:

1. **CLI and entrypoint** (`hammerdown.cli`, `hammerdown.__main__`):
   - parses command-line arguments (`--in-place`, `--force`, `--quiet`, etc.)
   - triggers OS file pickers when run without arguments
   - registers system file-manager context menu handlers

2. **Core orchestration** (`hammerdown.core`):
   - manages output filenames (`<name>_<ext>.md`)
   - creates output directories and manages collision protection
   - exposes high-level functions `to_markdown()` and `convert_file()`
   - re-exports specialized parser functions for Python developers

3. **Parsers** (`hammerdown.parsers`):
   - `pdf.py`: PDF and e-book parsing via PyMuPDF and PyMuPDF4LLM, extracting raw images
   - `office.py`: DOCX, XLSX, PPTX extraction, plus fallback runners for older formats (.doc, .xls, .ppt)
   - `odt.py`: native OpenDocument Text reader with formula and image extraction
   - `math.py`: conversion of equation XML trees (Word OMML and MathML) into standard LaTeX math formulas using symbol mappings in `symbols.json`
   - `charts.py`: conversion of embedded office charts into standalone SVG vector images
   - `tables.py`: intelligent detection, trimming, and segmentation of complex and sparse table matrices into clean Markdown tables
   - `text.py`: encoding detection, CSV dialect sniffing, and base64 image extraction
