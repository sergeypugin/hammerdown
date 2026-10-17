from __future__ import annotations

import plistlib
import shutil
import subprocess
import uuid
from pathlib import Path

from hammerdown.platform_utils import is_macos

from ._common import _install_launcher, _quote_if_needed, _remove_install_dir


def _remove_silently(path: Path) -> None:
    if path.exists():
        try:
            shutil.rmtree(path)
        except OSError:
            pass


def _create_macos_workflow(workflow_dir: Path, launcher: Path | str) -> None:
    contents_dir = workflow_dir / "Contents"
    contents_dir.mkdir(parents=True, exist_ok=True)

    info_data = {
        "CFBundleIdentifier": "com.hammerdown.quickaction",
        "CFBundleName": "Hammer down",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "NSServices": [
            {
                "NSBackgroundColorName": "background",
                "NSIconName": "NSTouchBarDocument",
                "NSMenuItem": {"default": "Hammer down"},
                "NSMessage": "runWorkflowAsService",
                "NSRequiredContext": {"NSApplicationIdentifier": "com.apple.finder"},
                "NSSendFileTypes": ["public.item"],
            }
        ],
    }
    with open(contents_dir / "Info.plist", "wb") as fp:
        plistlib.dump(info_data, fp, fmt=plistlib.FMT_XML)

    exec_target = _quote_if_needed(launcher)
    wflow_data = {
        "AMApplicationBuild": "523",
        "AMApplicationVersion": "2.10",
        "AMDocumentVersion": "2",
        "actions": [
            {
                "action": {
                    "AMAccepts": {"Container": "List", "Optional": True, "Types": ["com.apple.cocoa.path"]},
                    "AMActionVersion": "2.0.3",
                    "AMApplication": ["Automator"],
                    "AMCategory": "AMCategoryUtilities",
                    "AMParameterProperties": {
                        "COMMAND_STRING": {},
                        "CheckedForUserDefaultShell": {},
                        "inputMethod": {},
                        "shell": {},
                        "source": {},
                    },
                    "AMProvides": {"Container": "List", "Types": ["com.apple.cocoa.path"]},
                    "ActionBundlePath": "/System/Library/Automator/Run Shell Script.action",
                    "ActionName": "Run Shell Script",
                    "ActionParameters": {
                        "COMMAND_STRING": f'exec {exec_target} "$@"',
                        "CheckedForUserDefaultShell": True,
                        "inputMethod": 1,
                        "shell": "/bin/sh",
                        "source": "",
                    },
                    "BundleIdentifier": "com.apple.RunShellScript",
                    "CFBundleIdentifier": "com.apple.RunShellScript",
                    "Class Name": "RunShellScriptAction",
                    "InputUUID": str(uuid.uuid4()),
                    "Keywords": ["Shell", "Script", "Command", "Run", "Unix"],
                    "OutputUUID": str(uuid.uuid4()),
                    "UUID": str(uuid.uuid4()),
                    "UnlocalizedApplications": ["Automator"],
                }
            }
        ],
        "connectors": {},
        "workflowMetaData": {
            "applicationBundleIDsByPath": {},
            "applicationPaths": [],
            "inputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "outputTypeIdentifier": "com.apple.Automator.nothing",
            "presentationMode": 15,
            "processesInput": False,
            "serviceApplicationBundleID": "com.apple.finder",
            "serviceApplicationPath": "/System/Library/CoreServices/Finder.app",
            "serviceInputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
            "serviceProcessesInput": False,
            "systemImageName": "NSTouchBarDocument",
            "useAutomaticInputType": False,
            "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
        },
    }
    with open(contents_dir / "document.wflow", "wb") as fp:
        plistlib.dump(wflow_data, fp, fmt=plistlib.FMT_XML)


def _create_macos_droplet(app_dest: Path, launcher: Path | str) -> bool:
    osacompile = shutil.which("osacompile")
    if not osacompile:
        return False

    app_dest.parent.mkdir(parents=True, exist_ok=True)
    _remove_silently(app_dest)

    exec_target = _quote_if_needed(launcher)
    applescript_source = (
        'on run\n'
        '    set chosenFiles to choose file with prompt "Select documents to convert:" with multiple selections allowed\n'
        '    open chosenFiles\n'
        'end run\n'
        '\n'
        'on open droppedItems\n'
        f'    set cmd to {repr(exec_target)}\n'
        '    repeat with anItem in droppedItems\n'
        '        set cmd to cmd & " " & quoted form of (POSIX path of anItem)\n'
        '    end repeat\n'
        '    do shell script cmd\n'
        'end open\n'
    )

    try:
        subprocess.run([osacompile, "-o", str(app_dest), "-e", applescript_source], capture_output=True, check=True)
    except (subprocess.CalledProcessError, OSError):
        return False

    info_plist_path = app_dest / "Contents" / "Info.plist"
    if info_plist_path.is_file():
        try:
            with open(info_plist_path, "rb") as fp:
                info_data = plistlib.load(fp)
            info_data["CFBundleDocumentTypes"] = [
                {
                    "CFBundleTypeName": "Supported Documents",
                    "CFBundleTypeRole": "Viewer",
                    "LSHandlerRank": "Alternate",
                    "LSItemContentTypes": ["public.item", "public.content", "public.data"],
                }
            ]
            with open(info_plist_path, "wb") as fp:
                plistlib.dump(info_data, fp, fmt=plistlib.FMT_XML)
        except Exception:
            pass

    lsregister = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
    if Path(lsregister).is_file():
        try:
            subprocess.run([lsregister, "-f", str(app_dest)], capture_output=True, check=False)
        except Exception:
            pass

    return True


def _install_macos(command: str, home_dir: Path | None = None) -> None:
    home = home_dir or Path.home()
    launcher = _install_launcher(command, home)

    services_dir = home / "Library" / "Services"
    services_dir.mkdir(parents=True, exist_ok=True)
    _create_macos_workflow(services_dir / "Hammer down.workflow", launcher)

    app_dest = home / "Applications" / "Hammer down.app"
    _create_macos_droplet(app_dest, launcher)

    if is_macos():
        pbs_path = "/System/Library/CoreServices/pbs"
        if Path(pbs_path).is_file():
            try:
                subprocess.run([pbs_path, "-flush"], capture_output=True, check=False)
            except Exception:
                pass


def _uninstall_macos(home_dir: Path | None = None) -> None:
    home = home_dir or Path.home()
    (home / ".local" / "bin" / "hammerdown").unlink(missing_ok=True)
    _remove_silently(home / "Library" / "Services" / "Hammer down.workflow")
    _remove_silently(home / "Library" / "Services" / "Hammer down file.workflow")
    _remove_silently(home / "Applications" / "Hammer down.app")
    _remove_install_dir(home / ".local" / "share" / "hammerdown")

    if is_macos():
        pbs_path = "/System/Library/CoreServices/pbs"
        if Path(pbs_path).is_file():
            try:
                subprocess.run([pbs_path, "-flush"], capture_output=True, check=False)
            except Exception:
                pass
