# Desktop and File-Manager Integration

| ![Convert to Markdown](assets/action_convert.png) | ![Merge](assets/action_merge.png) | ![Tree](assets/action_tree.png) | ![Tree with all formats](assets/action_tree_all.png) |
| :---: | :---: | :---: | :---: |
| Convert to Markdown | Merge | Tree | Tree with all formats |

The four actions above are added to your file manager by `hammerdown --install`, using the same icons as the context-menu buttons. They convert documents and source trees to Markdown without typing a command.

## The four actions

Every action accepts a multi-file selection; folders expand recursively and unsupported files are reported and skipped. The actions run headless on Linux and macOS, while Windows hands the run to a terminal window (see below).

- **Convert to Markdown** writes one Markdown file per source: `report.pdf` becomes `hm_report_pdf.md` next to the source, `notes.txt` becomes `hm_notes_txt.md`, and extracted images go into `hm_images_report_pdf/`. Each run creates separate files, so outputs from different runs never collide
- **Merge** converts the whole selection and concatenates it into one Markdown document, defaulting to `hammerdowned.md` written next to the selected files
- **Tree** gathers the selection into one Gitingest-like tree document of text and source-code files, also defaulting to `hammerdowned.md` in the common parent folder of the selection; supported binary documents are not included
- **Tree with all formats** runs the same tree pass but additionally includes Hammerdown's supported document formats (PDF, DOCX, and so on); unknown binary files remain skipped

> [!important]
> merge and tree actions always write the same target file (`hammerdowned.md`) next to the selected files and replace it on every run, so a later run with different files or options overwrites the previous output. Treat that file as a disposable snapshot, not as storage. For Markdown copies you want to keep, use the convert-to-markdown action instead: it writes `hm_<stem>_<ext>.md` next to each source and keeps different runs separate

### When to use which action

| Goal | Action |
| :--- | :--- |
| Keep a Markdown copy of each document | Convert to Markdown |
| Feed a whole selection or folder to an LLM as one block | Merge |
| Snapshot a source tree of text and code files | Tree |
| Same, but including supported binary documents | Tree with all formats |

## Windows

`hammerdown --install` on Windows:

- registers a cascading **Hammerdown** submenu in the File Explorer context menu; it appears when you right-click any selected file or folder, and when you right-click empty space inside a folder (HKCU registry keys, so no administrator rights are needed)
- adds the four actions to the submenu with the icons shown above, each accepting a multi-file selection
- creates four **Send to** commands in `%APPDATA%\Microsoft\Windows\SendTo`: `Hammerdown`, `Hammerdown and merge`, `Hammerdown tree`, and `Hammerdown tree with all formats`
- copies the action icons to `%LOCALAPPDATA%\hammerdown`

When an action runs, the selection is collected by a single-instance coordinator (paths picked within a 2.0-second window are assembled into one batch) and the batch opens in one Windows Terminal window titled `Hammerdown` (`wt -w new new-tab --title Hammerdown`). If Windows Terminal is not installed, a regular console window titled `Hammerdown` is allocated instead. Progress, warnings, and the overwrite confirmation for merge and tree targets are shown in that window.

## Linux

`hammerdown --install` on Linux:

- writes a launcher script to `~/.local/bin/hammerdown`
- registers a KDE service menu with a cascading **Hammerdown** submenu (`X-KDE-Submenu=Hammerdown`) containing the four actions, in `~/.local/share/kio/servicemenus/hammerdown.desktop` (KDE Frameworks 6) and `~/.local/share/kservices5/ServiceMenus/hammerdown.desktop` (Plasma 5)
- installs four scripts for Nautilus, Nemo, and Caja in `~/.local/share/nautilus/scripts/`, `~/.local/share/nemo/scripts/`, and `~/.config/caja/scripts/`: `Hammerdown`, `Hammerdown and merge`, `Hammerdown tree`, and `Hammerdown tree with all formats`
- adds an application entry with the same merge and tree actions to `~/.local/share/applications/hammerdown.desktop` and copies the icons into the hicolor icon theme, then refreshes the desktop database

The scripts run without a window: the output files simply appear next to the selection.

## macOS

`hammerdown --install` on macOS:

- creates four Quick Action workflows in `~/Library/Services/`: `Hammerdown`, `Hammerdown and merge`, `Hammerdown tree`, and `Hammerdown tree with all formats`. Right-click files in Finder and pick them under Quick Actions (the Services menu on older macOS versions)
- builds a droplet application `~/Applications/Hammerdown.app` (when `osacompile` is available): drag files onto it to convert them, or open the app directly to pick files in a dialog
- flushes the Services cache so the new Quick Actions appear immediately

Quick Actions and the droplet run without a window; the output files appear next to the selected items.

## Unsupported platforms

File-manager integration is only available on Windows, macOS, and Linux. On other systems (for example FreeBSD), `hammerdown --install` and `hammerdown --uninstall` print an explanatory message and exit with status `1`. The command-line interface still works there: run `hammerdown <files>` or `hammerdown -m output.md <files>`.

## Uninstall

`hammerdown --uninstall` removes the integration installed on the current platform:

- Windows: the registry submenu, the four Send to commands, the action icons in `%LOCALAPPDATA%\hammerdown`, and leftover legacy entries
- Linux: the launcher, the KDE service menus, the Nautilus, Nemo, and Caja scripts, the desktop entry, the hicolor icons, and `~/.local/share/hammerdown`
- macOS: the launcher, the four Quick Action workflows in `~/Library/Services/`, the droplet in `~/Applications/`, and `~/.local/share/hammerdown`

The command exits with status `1` if uninstalling fails or if the platform is unsupported. Converted Markdown files are never removed.

See the [CLI Reference](CLI.md) for the full option set behind these actions, and the [README](../README.md) for installation of the package itself.
