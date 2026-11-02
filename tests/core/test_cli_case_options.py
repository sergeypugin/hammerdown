from __future__ import annotations

import pytest

import hammerdown.cli


def _capture_batch(monkeypatch):
    captured = {}

    def capture(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(hammerdown.cli, "run_batch", capture)
    return captured


@pytest.mark.parametrize("version_option", ["-v", "-V", "--VERSION", "--vErSiOn"])
def test_version_options_are_case_insensitive(version_option: str, capsys):
    with pytest.raises(SystemExit) as exc:
        hammerdown.cli.main([version_option])

    assert exc.value.code == 0
    assert f"hammerdown {hammerdown.cli.__version__}" in capsys.readouterr().out


def test_mixed_case_long_options_preserve_values(monkeypatch):
    captured = _capture_batch(monkeypatch)

    assert (
        hammerdown.cli.main(
            [
                "--tReE",
                "--aLl-FoRmAtS",
                "--iNcLuDe=Include/CaseSensitive.TXT",
                "--eXcLuDe",
                "Exclude/CaseSensitive.LOG",
                "Mixed/Resource.TXT",
            ]
        )
        == 0
    )

    args = captured["args"]
    assert args.tree is True
    assert args.all_formats is True
    assert args.include == ["Include/CaseSensitive.TXT"]
    assert args.exclude == ["Exclude/CaseSensitive.LOG"]
    assert args.files == ["Mixed/Resource.TXT"]


def test_mixed_case_options_work_between_resources(monkeypatch):
    captured = _capture_batch(monkeypatch)

    assert (
        hammerdown.cli.main(
            [
                "First/Resource.TXT",
                "-T",
                "Second/Resource.TXT",
                "-I",
                "Pattern/Case",
                "--ALL-FORMATS",
            ]
        )
        == 0
    )

    args = captured["args"]
    assert args.files == ["First/Resource.TXT", "Second/Resource.TXT"]
    assert args.tree is True
    assert args.all_formats is True
    assert args.include == ["Pattern/Case"]


    captured = _capture_batch(monkeypatch)

    assert (
        hammerdown.cli.main(
            [
                "-T",
                "-I",
                "Include/CaseSensitive.TXT",
                "-E",
                "Exclude/CaseSensitive.LOG",
                "-M",
                "Merge/CaseSensitive.MD",
                "Mixed/Resource.TXT",
            ]
        )
        == 0
    )

    args = captured["args"]
    assert args.tree is True
    assert args.include == ["Include/CaseSensitive.TXT"]
    assert args.exclude == ["Exclude/CaseSensitive.LOG"]
    assert args.merge == "Merge/CaseSensitive.MD"
    assert args.files == ["Mixed/Resource.TXT"]


def test_optional_merge_value_is_preserved_when_followed_by_another_option(monkeypatch):
    captured = _capture_batch(monkeypatch)

    assert hammerdown.cli.main(["-M", "Merge/CaseSensitive.MD", "-T", "Input/CaseSensitive.TXT"]) == 0

    args = captured["args"]
    assert args.merge == "Merge/CaseSensitive.MD"
    assert args.tree is True
    assert args.files == ["Input/CaseSensitive.TXT"]


@pytest.mark.parametrize("output_option", ["-O", "--OuTpUt-DiR"])
def test_mixed_case_output_option_preserves_output_value(monkeypatch, output_option: str):
    captured = _capture_batch(monkeypatch)

    assert hammerdown.cli.main([output_option, "Output/CaseSensitive", "Input/CaseSensitive.TXT"]) == 0

    args = captured["args"]
    assert args.output_dir == "Output/CaseSensitive"
    assert args.files == ["Input/CaseSensitive.TXT"]


@pytest.mark.parametrize(
    ("option", "attribute", "expected"),
    [
        ("-IPattern/CaseSensitive.TXT", "include", ["Pattern/CaseSensitive.TXT"]),
        ("-EExclude/CaseSensitive.LOG", "exclude", ["Exclude/CaseSensitive.LOG"]),
        ("-OOutput/CaseSensitive", "output_dir", "Output/CaseSensitive"),
        ("-MMerge/CaseSensitive.MD", "merge", "Merge/CaseSensitive.MD"),
        ("-I=Include/Equals.Case", "include", ["Include/Equals.Case"]),
    ],
)
def test_uppercase_compact_short_options_preserve_attached_values(
    monkeypatch, option: str, attribute: str, expected
):
    captured = _capture_batch(monkeypatch)

    assert hammerdown.cli.main([option, "Input/Resource.TXT"]) == 0

    args = captured["args"]
    assert getattr(args, attribute) == expected
    assert args.files == ["Input/Resource.TXT"]


@pytest.mark.parametrize("option", ["-I-pattern", "-I=-pattern"])
def test_compact_short_option_preserves_hyphen_leading_value(monkeypatch, option: str):
    captured = _capture_batch(monkeypatch)

    assert hammerdown.cli.main([option, "Input/Resource.TXT"]) == 0

    assert captured["args"].include == ["-pattern"]


def test_tokens_after_separator_are_not_normalized(monkeypatch):
    captured = _capture_batch(monkeypatch)

    assert hammerdown.cli.main(["--", "--TrEe", "Mixed/Resource.TXT"]) == 0

    assert captured["args"].files == ["--TrEe", "Mixed/Resource.TXT"]
    assert captured["args"].tree is False


@pytest.mark.parametrize(
    ("option", "suggestion"),
    [
        ("-VeRsIoN", "--version"),
        ("-TrEe", "--tree"),
        ("-AlL-FoRmAtS", "--all-formats"),
    ],
)
def test_mixed_case_single_dash_long_options_are_rejected(option: str, suggestion: str, capsys):
    with pytest.raises(SystemExit) as exc:
        hammerdown.cli.main([option, "resource.txt"])

    assert exc.value.code == 2
    assert f"did you mean '{suggestion}'" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("option", "message"),
    [
        ("--TrE", "did you mean '--tree'?"),
        ("--V", "did you mean '--version'?"),
        (
            "--In",
            "possible matches: '--include', '--include-gitignored', '--install'",
        ),
    ],
)
def test_mixed_case_abbreviated_long_options_are_rejected(option: str, message: str, capsys):
    with pytest.raises(SystemExit) as exc:
        hammerdown.cli.main([option, "resource.txt"])

    assert exc.value.code == 2
    assert message in capsys.readouterr().err
