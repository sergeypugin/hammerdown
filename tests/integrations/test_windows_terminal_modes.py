from __future__ import annotations

import argparse

import pytest

import hammerdown.batch as batch
from hammerdown.core.filters import OrderedFilterValues
from hammerdown.integrations.windows_terminal import (
    WINDOWS_TERMINAL_TITLE,
    build_windows_terminal_command,
)


@pytest.mark.parametrize(
    ("mode", "merge", "merge_auto", "tree", "all_formats"),
    [
        ("ordinary", None, False, False, False),
        ("merge", None, True, False, False),
        ("explicit-merge", "combined.md", False, False, False),
        ("tree", None, False, True, False),
        ("tree-all", None, False, True, True),
    ],
)
def test_handoff_forwards_conversion_modes(monkeypatch, mode, merge, merge_auto, tree, all_formats):
    captured: dict[str, object] = {}

    def fake_launch(files, **kwargs):
        captured["files"] = files
        captured.update(kwargs)
        return True

    monkeypatch.setattr(batch, "is_windows", lambda: True)
    monkeypatch.setattr("hammerdown.integrations.windows_terminal.launch_context_worker", fake_launch)

    args = argparse.Namespace(
        coordinator=True,
        context_worker=False,
        include_gitignored=False,
        merge=merge,
        tree=tree,
        all_formats=all_formats,
        include=["*.txt"],
        exclude=["draft/**"],
        overwrite=True,
        skip_existing=True,
        output_dir="out",
    )

    assert batch.hand_off_to_windows_terminal(["one.txt", "two.txt"], args, merge_auto) is True
    assert captured == {
        "files": ["one.txt", "two.txt"],
        "merge": merge,
        "merge_auto": merge_auto,
        "tree": tree,
        "all_formats": all_formats,
        "include": ["*.txt"],
        "exclude": ["draft/**"],
        "overwrite": True,
        "skip_existing": True,
        "yes": False,
        "no": False,
        "output_dir": "out",
    }, mode


def test_handoff_forwards_ordered_filter_queue(monkeypatch):
    captured: dict[str, object] = {}

    def fake_launch(files, **kwargs):
        captured["files"] = files
        captured.update(kwargs)
        return True

    monkeypatch.setattr(batch, "is_windows", lambda: True)
    monkeypatch.setattr("hammerdown.integrations.windows_terminal.launch_context_worker", fake_launch)

    args = argparse.Namespace(
        coordinator=True,
        context_worker=False,
        include_gitignored=False,
        merge=None,
        tree=False,
        all_formats=False,
        include=OrderedFilterValues(["keep.log"]),
        exclude=OrderedFilterValues(["*.log"]),
        overwrite=False,
        skip_existing=False,
        output_dir=None,
    )
    args.include.filter_queue = [("exclude", "*.log"), ("include", "keep.log")]
    assert batch.hand_off_to_windows_terminal(["one.txt"], args, False) is True
    assert captured["filter_queue"] == [("exclude", "*.log"), ("include", "keep.log")]


def test_windows_terminal_argv_preserves_ordered_filter_queue(monkeypatch):
    monkeypatch.setattr("hammerdown.integrations.windows_terminal._console_interpreter", lambda: "python.exe")

    command = build_windows_terminal_command(
        ["one.txt"],
        terminal="wt.exe",
        include=["keep.log"],
        exclude=["*.log"],
        filter_queue=[("exclude", "*.log"), ("include", "keep.log")],
    )

    assert command == [
        "wt.exe",
        "-w",
        "new",
        "new-tab",
        "--title",
        WINDOWS_TERMINAL_TITLE,
        "--",
        "python.exe",
        "-m",
        "hammerdown",
        "--context-worker",
        "--right-click",
        "--exclude",
        "*.log",
        "--include",
        "keep.log",
        "one.txt",
    ]


@pytest.mark.parametrize(
    ("merge", "merge_auto", "tree", "all_formats"),
    [
        (None, False, False, False),
        (None, True, False, False),
        ("combined.md", False, False, False),
        (None, False, True, False),
        (None, False, True, True),
    ],
)
def test_windows_terminal_argv_contains_forwarded_modes(
    merge, merge_auto, tree, all_formats, monkeypatch
):
    monkeypatch.setattr("hammerdown.integrations.windows_terminal._console_interpreter", lambda: "python.exe")

    command = build_windows_terminal_command(
        ["one.txt", "two.txt"],
        terminal="wt.exe",
        merge=merge,
        merge_auto=merge_auto,
        tree=tree,
        all_formats=all_formats,
        include=["*.txt"],
        exclude=["draft/**"],
        overwrite=True,
        skip_existing=True,
        output_dir="out",
    )

    expected = [
        "wt.exe",
        "-w",
        "new",
        "new-tab",
        "--title",
        WINDOWS_TERMINAL_TITLE,
        "--",
        "python.exe",
        "-m",
        "hammerdown",
        "--context-worker",
        "--right-click",
    ]
    if tree:
        expected.append("--tree")
        if all_formats:
            expected.append("--all-formats")
    if merge_auto:
        expected.append("--merge-auto")
    expected.extend(
        (
            "--include",
            "*.txt",
            "--exclude",
            "draft/**",
            "--overwrite",
            "--skip-existing",
            "--output-dir",
            "out",
        )
    )
    if merge:
        expected.extend(("--merge", merge))
    expected.extend(("one.txt", "two.txt"))

    assert command == expected
