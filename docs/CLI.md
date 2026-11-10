# CLI Reference

| ![Convert to Markdown](assets/action_convert.png) | ![Merge](assets/action_merge.png) | ![Tree](assets/action_tree.png) | ![Tree with all formats](assets/action_tree_all.png) |
| :---: | :---: | :---: | :---: |
| Convert to Markdown | Merge | Tree | Tree with all formats |

The four file-manager actions installed by `hammerdown --install` map to the modes documented below: a plain run, `-m`/`--merge`, `--tree`, and `--tree --all-formats`.

`hammerdown` has one command-line entry point that turns documents into Markdown. A single invocation can convert files one by one into `hm_*.md` outputs, merge many documents into one Markdown target (`-m`/`--merge`), gather a whole source tree into one document (`--tree`), stream a merged document to stdout (`--stdout`), or print a report without converting (`--tokens`, `--time`, `--dir-struct`). Separate management options install, remove, and update the file-manager integration (`--install`, `--uninstall`, `--update`/`--upgrade`). Every option below is verified against the parser in `src/hammerdown/cli.py`, including defaults, conflicts, and exit codes.

## Quick start

Install the package, then print the built-in help (the option list, the tool description, and the supported formats):

```sh
pip install hammerdown
hammerdown --help
```

One verified example per mode; each is explained in [Conversion modes](#conversion-modes):

```sh
hammerdown notes.txt
hammerdown -m summary.md project/
hammerdown --tree project/
hammerdown --stdout project/ > summary.md
hammerdown --tokens project/
hammerdown --install
```

Running `hammerdown` with no arguments prints the version, the tool description, the supported formats, and the `--help` hint to stderr, then exits `0`. A conversion invocation needs at least one input resource: flags without any path (for example `hammerdown --tree` or `hammerdown -m anything.ext`) fail with `no input resources were provided` and exit code `2`.

## Option reference

| Option | Effect | Default | Cannot combine with |
| --- | --- | --- | --- |
| `-h`, `--help` | show the help text and exit | | |
| `-v`, `--version` | print the version (for example `hammerdown 4.0.0`) and exit | | |
| `--install` | install the file-manager integration | | `--uninstall` (mutually exclusive) |
| `--uninstall` | remove the file-manager integration | | `--install` |
| `--update`, `--upgrade` | update hammerdown to the latest version | | |
| `-i`, `--include PATTERN` | include paths matching a GitWildMatch pattern; repeatable | everything included | |
| `-e`, `--exclude PATTERN` | exclude paths matching a GitWildMatch pattern; repeatable | nothing excluded | |
| `-w`, `--overwrite` | rewrite plain-text source files (`.txt`, `.md`, `.log`, `.csv`) in place | off | `-s`, `-o`, `--merge`, `--tree`, `--stdout`, report modes |
| `-s`, `--skip-existing` | skip conversion when the target Markdown file already exists | off | `-w`, `--stdout`, report modes |
| `-o`, `--output-dir DIR` | write Markdown and images under `DIR`, preserving the relative layout of the input tree | next to each source | `-w`, `--merge`, `--stdout`, `--tree`, report modes |
| `--include-gitignored` | bypass repository `.gitignore` and `.gitingestignore` rules | off | |
| `--tree` | gather the selection into one Markdown tree document | off | `-o`, `-w`, `--dir-struct` |
| `--all-formats` | include supported binary documents (PDF, DOCX, and so on) in tree discovery | off | requires `--tree` or `--dir-struct` |
| `-m [OUTPUT_MD]`, `--merge [OUTPUT_MD]` | merge converted documents into `OUTPUT_MD` | `hammerdowned.md` | `-w`, `-o`, `--stdout`, report modes |
| `--stdout` | write the merged Markdown document to stdout | off | `--merge`, `-o`, `-w`, `-s` |
| `--tokens` | report source and estimated token counts without converting | off | `--merge`, `--stdout`, `-o`, `-w`, `-s` |
| `--time` | report conversion time estimates without converting | off | `--merge`, `--stdout`, `-o`, `-w`, `-s` |
| `--dir-struct` | report the selected directory structure without converting | off | `--merge`, `--stdout`, `-o`, `-w`, `-s`, `--tree` |
| `--confirm` | show a preflight estimate and ask for confirmation before `--stdout` | off | requires `--stdout` |
| `-y`, `--yes` | overwrite an existing merge/tree target without asking | off | `-n`, `-s` |
| `-n`, `--no` | keep an existing merge/tree target and exit `0` without converting | off | `-y` |
| `files` | input resources: files, directories, Google Docs/Drive links, GitHub references | required for conversion runs | |

Behavior notes verified against the parser:

- option names are case-insensitive, including short and long forms (`--TREE` is accepted as `--tree`); option values, paths, and filter patterns keep the case supplied by the caller
- long options require exactly two dashes: single-dash long forms (`-include`) and abbreviated long forms (`--tre`) are rejected with a suggestion, even when the abbreviation is unambiguous
- there is no `-t` short option for tree mode: `-t` is rejected with `unrecognized option '-t'; did you mean '--tree'?`
- `-i`/`-e` may be repeated; each repetition appends to one ordered filter queue (see [Filters and ignore rules](#filters-and-ignore-rules))
- `-o`/`--output-dir` may be repeated only with the same directory; two different directories are rejected
- a merge or tree run whose target file already exists prints the existing output's frontmatter metadata and then asks `Overwrite <name>? [y/n]` in a terminal; `-y` answers it in advance, `-n` keeps the existing target and exits `0`, and a non-interactive run without either flag fails with exit code `1` instead of waiting for input
- use `--` to end option parsing when an input path starts with `-`
- conflicts are validated before any discovery starts, so a conflicting command fails with exit code `2` without converting anything

> [!note]
> `--coordinator`, `--context-worker`, `--right-click`, and `--merge-auto` are hidden internal options (they are suppressed from `--help`) used by the file-manager context-menu integration to hand an Explorer selection between processes. They are not part of the user-facing CLI, some combinations are rejected in coordinator mode (for example `-o` and `--stdout`), and they may change at any time. The environment variables `HAMMERDOWN_COORDINATOR` and `HAMMERDOWN_IPC_PIPE` belong to the same internal machinery.

## Conversion modes

### Per-file conversion

Pass files or directories; every discovered convertible file becomes one Markdown file next to the source (or under `-o/--output-dir`), with extracted images in a sibling asset folder. Directories are traversed recursively, canonical duplicates (a file plus its containing directory, overlapping roots) are processed once, and files in unsupported formats are reported in the `Skipped files` panel instead of failing the run. Convert one or several files:

```sh
hammerdown report.pdf
hammerdown report.docx workbook.xlsx slides.pptx
```

Public Google Docs, Sheets, Slides, and Drive file links are downloaded to a temporary staging folder, converted, and removed; the resulting Markdown is written to the working directory or to `-o/--output-dir`.

### Merge mode (`-m`, `--merge`)

`-m`/`--merge` treats the argument immediately after it as the output Markdown file and never as an input resource, then converts one or more source resources and concatenates them into that target. With the target omitted, `-m` alone uses `hammerdowned.md`. Both placements work because options and resources may be intermixed:

```sh
hammerdown -m summary.md project/report.pdf project/drafts/
hammerdown project/report.pdf project/drafts/ -m
```

`hammerdown -m report.pdf` therefore treats `report.pdf` as the output and fails with `no input resources were provided`. The target starts with a YAML frontmatter metadata block, followed by two parts: a `Directory structure:` tree of every source relative to their common root, then one block per document, each introduced by a line of 48 `=` characters, a `FILE:` line with the relative path, and the separator again:

```text
Directory structure:
================================================
FILE: notes.txt
================================================
alpha meeting notes
```

The frontmatter records the provenance of the run, so a stale target is easy to tell from a fresh one:

```markdown
---
tool: 'hammerdown'
version: '4.0.0'
date: '2026-11-10T21:34:05+03:00'
mode: 'merge'
source: 'C:/Users/serge/project'
inputs:
  - 'folder1'
  - 'folder1/folder2'
  - 'folder3'
files: 42
tokens_estimate: 15200
---
```

Field semantics:

- `tool`: always `hammerdown`
- `version`: hammerdown version that produced the file
- `date`: conversion date and time, local ISO 8601 with timezone offset
- `mode`: operation flags only -- `merge`, `tree`, or `tree --all-formats`
- `source`: resolved common root directory of all inputs (forward slashes); the per-file directory tree in the body is relative to it
- `inputs`: raw command-line arguments exactly as passed, one YAML list item each; written as `inputs: []` when empty
- `files`: number of discovered sources
- `tokens_estimate`: approximate output token count, plain integer, computed with the same rules as `--tokens` (exact counts for text sources, size//4 estimate for known binary formats); the metadata block itself is not counted in it

Extracted assets are not mixed with the originals: for the target `summary.md`, images are written into `hm_merged_into_summary_images/` next to the target, in subfolders that mirror each document's relative path, and links are rewritten accordingly. The target is assembled in a staging file during the run and committed atomically when the batch finishes; if the run is interrupted, the previous target is left untouched, never a partial file. An advisory lock file prevents two processes from merging into one target at the same time.

Additional merge behavior:

- `--merge` is rejected together with `--overwrite` and with `-o/--output-dir`, so plain-text sources are never modified during a merge
- with `-s`/`--skip-existing`, the whole run is skipped when the target already exists; the target and its asset directory are left untouched even if stale
- a custom target inside a recursively selected directory is excluded from discovery, so a rerun does not merge the previous output into itself; explicitly passing the target as a source is an error

### Tree mode (`--tree`, `--all-formats`)

`--tree` gathers the selection into one combined Markdown document using Gitingest-like text and code collection: text and source-code files are included, while Hammerdown's binary document formats are not. `--all-formats` extends tree discovery with the supported document formats; unknown binary files remain skipped. Tree mode always writes one target: `hammerdowned.md` in the working directory by default, or the file passed with `-m`. It is not a per-file conversion mode. The target starts with the YAML frontmatter metadata block described in the merge mode section, with `mode` set to `tree` or `tree --all-formats`.

```sh
hammerdown --tree project/
hammerdown project/ --tree --all-formats
hammerdown --tree -m handbook.md project/
```

`--tree` and `--all-formats` may appear before, between, or after resource arguments. `--all-formats` without `--tree` or `--dir-struct` is rejected. Tree mode rejects `-o/--output-dir` and `-w/--overwrite`.

### Streaming to stdout (`--stdout`, `--confirm`)

`--stdout` produces the same merged document as `-m`, writes it to stdout, and creates no intermediate `hm_*.md` files. With a single file it emits just that file's raw Markdown, with no merge header or separators; with multiple files it emits the full merged document with directory tree and per-file separators. Assets are inlined as base64 data URIs, so the stream is self-contained. Progress output is suppressed, errors go to stderr, and the exit code is `1` when any document failed.

```sh
hammerdown --stdout project/ > summary.md
```

`--confirm` prints a preflight estimate before anything is written: missing paths first, then a line with the file count, a token estimate for text sources (`.txt`, `.md`, `.log`, `.csv` only, since binary sizes say nothing about their output), and an estimated duration. The prompt accepts `y` and `yes`, rejects `n` and `no`, and re-asks on anything else; without an interactive stdin it cancels safely instead of waiting, and a cancelled preflight exits `1`.

### Report modes (`--tokens`, `--time`, `--dir-struct`)

The three report modes print a preflight report and exit without converting anything. They may be combined freely; a single run prints one section per requested mode. All of them conflict with `--merge`, `--stdout`, `-o/--output-dir`, `-w/--overwrite`, and `-s/--skip-existing`, and `--dir-struct` additionally conflicts with `--tree`. The report reflects the same discovery as a real run, including filters and ignore rules; the exit code is `1` when discovery reports errors such as missing paths.

- `--tokens` prints `exact source tokens` (counted from text files), `estimated binary tokens` (file size divided by four for known binary formats), plus `unknown`, `unsupported`, `operational errors`, and a `generated Markdown tokens` line
- `--time` prints the estimated `range` with a `confidence` level and the number of files whose estimate is `unknown`; estimates come from lightweight document metadata (page, slide, or sheet counts) read before any conversion starts
- `--dir-struct` prints the selected directory structure with `entries` and `displayed` counts, truncated at 100 entries with a `... N more entries` note; the listing shows every path discovery saw, including files dropped by command-line filters or safety exclusions

```sh
hammerdown --tokens --time project/
hammerdown --dir-struct project/
```

### Installation and updates (`--install`, `--uninstall`, `--update`/`--upgrade`)

`--install` registers the file-manager context-menu integration, `--uninstall` removes it, and the two are mutually exclusive. On unsupported platforms both exit `1` with an error. `--update` and `--upgrade` are aliases that fetch the latest release, replace the installation, and refresh the integration through the install step; they need network access. See the README for the list of supported platforms and desktop environments.

## Output naming and assets

Per-file outputs use deterministic names derived from the source name: `report.docx` becomes `hm_report_docx.md` and `notes.txt` becomes `hm_notes_txt.md`. The source extension is part of the name and normalized to lowercase, so identical stems in different formats do not collide. Extracted assets live in a sibling folder, `hm_images_report_docx/` for `report.docx`; relative image links in the Markdown point into that folder. PDF conversion produces text-only Markdown without an asset folder, and asset folders are created only where a format exposes separate assets.

For merge and tree targets the asset folder is named after the target: `hm_merged_into_summary_images/` for `summary.md`, `hm_merged_into_hammerdowned_images/` for the default target, with per-document subfolders mirroring the source layout.

A successful normal rerun replaces the Markdown target and the complete corresponding `hm_images_*` directory; stale files and old asset extensions are removed, and an old asset directory is removed when the new conversion produces no assets. `--skip-existing` instead preserves the existing target and its asset directory as a unit, even when stale.

## Overwrite and skip-existing semantics

Without flags, an existing `hm_*.md` output is overwritten on a rerun together with its asset directory. `-w/--overwrite` goes further for plain-text sources: `.txt`, `.md`, `.log`, and `.csv` files are rewritten in place, so the source file itself becomes the Markdown output and no `hm_*.md` copy is created. For other formats the flag is ignored with a warning (`Overwrite flag ignored for binary format`). `-w` conflicts with `-s`, `-o`, `--merge`, `--tree`, and `--stdout`.

`-s/--skip-existing` checks only the Markdown target: when it exists, conversion of that file is skipped and both the target and its asset directory stay untouched, even if stale. In merge mode, an existing target skips the whole run.

For merge and tree targets without `-s`, an interactive terminal asks before overwriting: it first prints `Existing output was generated with:` followed by the existing file's frontmatter block, then asks `Overwrite <name>? [y/n]`. `-y`/`--yes` overwrites without asking, and `-n`/`--no` keeps the existing target and exits `0`. A non-interactive run without `--yes`, `--no`, or `--skip-existing` still fails fast with exit `1` and the same error text, plus a `(hammerdown <version>, converted <date>, mode <mode>)` suffix when the existing target has frontmatter.

> [!warning]
> merge and tree modes always write the same target file (`hammerdowned.md` unless `-m` sets one) and replace it on every run, frontmatter included, so the metadata always reflects the latest run and the target is a generated snapshot rather than durable storage. If you need Markdown copies for long-term storage, use ordinary per-file conversion instead

## Filters and ignore rules

`-i`/`-e` patterns use GitWildMatch syntax as implemented by `pathspec`; they are not regular expressions. Patterns are matched against paths relative to the selected resource context. Repeated `-i` and `-e` options form one ordered queue in the order they appear: a path starts included when no include option is present and excluded when one is; each matching `-e` excludes it and each later matching `-i` includes it again, so the last matching operation decides and a later include can restore a path excluded earlier.

Pattern values may contain comma- or whitespace-separated patterns, and matching surrounding single or double quotes are stripped; an unterminated quote is rejected with a parser error. Quote pattern arguments so the shell does not expand glob characters.

```sh
hammerdown -i 'src/**/*.py, docs/**/*.md' -e '**/generated/**' -i 'src/generated/keep.py' project/
```

For each selected resource, Hammerdown applies `.gitignore` and `.gitingestignore` files found from the selected root up to the nearest Git root, plus nested ignore files below that root; nested rules apply to their own subtree and support negation. Ignore files above the Git root and global Git ignore configuration are not applied, and rules from outermost to innermost are evaluated with the last matching rule winning. The `Ignore files used` panel lists every discovered ignore file before processing, including when `--include-gitignored` bypasses their rules.

`--include-gitignored` disables only these repository ignore files; command-line filters, safety exclusions, and format rules still apply. Safety exclusions always drop hidden entries (for example `.git` and dot-files) and generated outputs: files named `hm_*.md` or `hammerdowned.md` are excluded from recursive discovery, explicitly passing one is an error, and a directory containing only generated outputs fails because no input resources remain.

## Exit codes and environment variables

| Code | Meaning |
| --- | --- |
| `0` | success, including skipped runs and the no-argument description |
| `1` | conversion or runtime failure: any failed document, merge commit failure, discovery errors in report modes, unsupported platform for `--install`/`--uninstall`, or a cancelled `--confirm` |
| `2` | CLI usage error: unknown options, rejected abbreviations, conflicting flags, or no input resources |

An interrupted run (Ctrl+C) prints `Cancelled.` and exits with `130`.

Environment overrides:

| Variable | Effect | Default |
| --- | --- | --- |
| `HAMMERDOWN_WORKERS` | integer `>= 1` forcing the worker count for concurrent scheduling | computed from CPU count (capped at 6) and available memory |
| `HAMMERDOWN_PDF_CHUNK_PAGES` | integer `>= 1` setting the page-chunk size for parallel PDF conversion | `32` |
| `HAMMERDOWN_PDF_LIMIT` | integer `>= 1` bounding concurrent PDF chunk workers | `2` |
| `HAMMERDOWN_FORCE_SEQUENTIAL` | set to `1` to disable the concurrent scheduler entirely | unset |

Invalid values are ignored and the defaults apply.

## Worked examples

Each example below was verified against the current CLI on small text fixtures; binary formats follow the same flow per the format registry but were not converted during documentation.

Per-file conversion of a directory into a separate output tree; `.py` sources are listed under `Skipped files` as `unsupported format`, and the outputs keep the relative layout (`out/hm_notes_txt.md`, `out/src/hm_keep_txt.md`):

```sh
hammerdown -o out/ project/
```

Merge a directory into an explicit target, or into the default `hammerdowned.md` when the target is omitted:

```sh
hammerdown -m summary.md project/
hammerdown project/ -m
```

Tree mode over a project, with and without binary documents; rerunning either command replaces `hammerdowned.md` (see the warning above):

```sh
hammerdown --tree project/
hammerdown project/ --tree --all-formats
```

Stream a self-contained document for piping, optionally with a preflight prompt:

```sh
hammerdown --stdout project/ > summary.md
hammerdown --stdout --confirm project/ > summary.md
```

Estimate cost without converting; `--tokens` and `--time` combine, and `--dir-struct` lists the whole selected layout:

```sh
hammerdown --tokens --time project/
hammerdown --dir-struct project/
```

Ordered filters: `-i 'src/**/*.txt'` starts the selection empty, `-e '**/generated/**'` drops the generated subtree, and the final `-i 'src/generated/build.txt'` restores one file from it, demonstrating last-match-wins:

```sh
hammerdown --dir-struct -i 'src/**/*.txt' -e '**/generated/**' -i 'src/generated/build.txt' project/
```

Rewrite plain-text sources in place, or keep existing outputs on a rerun:

```sh
hammerdown -w drafts/
hammerdown -s -o out/ project/
```
