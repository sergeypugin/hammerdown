# Conversion Time Estimation and Benchmarks

This document describes the empirical benchmarks and the estimation model used by `hammerdown` to calculate estimated conversion times (ETA -- Estimated Time of Arrival) and format processing durations.

## Benchmark Results

The following measurements were gathered across standard sample inputs on a 64-bit multi-core system:

| File | Format | Size | Units | Total Time | Time per Unit |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `lab1.pdf` | PDF | 107 KB | 4 pages | 2.70s | 0.68s / page |
| `lab2.pdf` | PDF | 492 KB | 7 pages | 5.69s | 0.81s / page |
| `lab3.pdf` | PDF | 81 KB | 2 pages | 1.60s | 0.80s / page |
| `lab4.pdf` | PDF | 314 KB | 3 pages | 2.89s | 0.96s / page |
| `report.pdf` | PDF | 501 KB | 9 pages | 11.35s | 1.26s / page |
| `report.doc` | DOC | 71 KB | External engine convert | 0.81s | < 1.0s total |
| `report.odt` | ODT | 76 KB | Tables, math, images | 0.04s | < 0.05s total |
| `report.docx` | DOCX | 71 KB | Tables, math, charts | 0.04s | < 0.05s total |
| `actors.xlsx` | XLSX | 21 KB | Multiple worksheets | 0.37s | < 0.5s total |
| `actors.csv` | CSV | 4.2 KB | 100 rows | 0.002s | Instantaneous |
| `LMS.md` | Markdown | 24 KB | Embedded base64 images | 0.005s | Instantaneous |
| `sample.txt` | Text | 120 B | Plain text | 0.004s | Instantaneous |

## Estimation Model

When `hammerdown` starts converting a file, it checks the structure of the file before launching CPU-heavy extraction:

### PDF and E-books

For `.pdf`, `.epub`, `.mobi`, `.fb2`, and `.xps` files, `hammerdown` reads the document catalog via PyMuPDF to count the total number of pages $N_{\text{pages}}$.

Because PyMuPDF4LLM performs layout analysis and reading-order reconstruction, the average duration per page is approximately 0.85--1.00 seconds. The estimation is calculated as:

$$\text{Estimated Time} = \max(1.0,\; N_{\text{pages}} \times 0.9)$$

Example log:
```text
Processing report.pdf (9 pages, est. ~8s)...
Completed report.pdf in 10s (saved 1 images)
```

### Presentations

For `.pptx` slides, `hammerdown` inspects slide count $N_{\text{slides}}$ via `python-pptx`:

$$\text{Estimated Time} = \max(1.0,\; N_{\text{slides}} \times 0.1)$$

### Other Formats

Word documents (`.docx`), OpenDocument files (`.odt`), spreadsheets (`.xlsx`), and text/Markdown files typically convert in less than a second on modern systems. For legacy formats (`.doc`, `.xls`, `.ppt`), conversion depends on headless office application startup times (~0.8--1.5s).

## Human-Readable Duration Formatting

Conversion durations are displayed in human-readable notation rather than fixed decimal seconds:

- under 1 second: formatted with decimal precision (for example, `0.04s` or `0.85s`)
- between 1 and 59 seconds: rounded to full seconds (for example, `14s` or `45s`)
- between 1 minute and 59 minutes: formatted as `XmYs` (for example, `1m10s`, `5m30s`, or `2m` if exact)
- 1 hour and above: formatted as `XhYm` (for example, `1h30m`, `2h15m`, or `3h` if exact)
