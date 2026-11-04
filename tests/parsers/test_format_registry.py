from __future__ import annotations

from hammerdown import core
from hammerdown.parsers import CONVERTERS
from hammerdown.parsers.format_registry import FORMAT_SPECS, FormatSpec


def test_registry_preserves_converter_order_and_projection() -> None:
    expected_extensions = (
        ".pdf",
        ".epub",
        ".mobi",
        ".fb2",
        ".xps",
        ".docx",
        ".doc",
        ".odt",
        ".xlsx",
        ".xls",
        ".pptx",
        ".ppt",
        ".csv",
        ".txt",
        ".md",
        ".log",
        ".html",
        ".htm",
        ".gdoc",
        ".gsheets",
        ".gslides",
        ".gfile",
        ".zip",
    )

    assert tuple(spec.extension for spec in FORMAT_SPECS) == expected_extensions
    assert tuple(CONVERTERS) == expected_extensions
    assert {spec.extension: spec.converter for spec in FORMAT_SPECS} == CONVERTERS
    assert core.CONVERTERS is CONVERTERS


def test_registry_metadata_matches_existing_classifications() -> None:
    specs = {spec.extension: spec for spec in FORMAT_SPECS}

    assert all(isinstance(spec, FormatSpec) for spec in FORMAT_SPECS)
    assert {ext for ext, spec in specs.items() if spec.kind == "pdf"} == {
        ".pdf", ".epub", ".mobi", ".fb2", ".xps"
    }
    assert {ext for ext, spec in specs.items() if spec.kind == "office"} == {
        ".docx", ".doc", ".odt", ".xlsx", ".xls", ".pptx", ".ppt"
    }
    assert {ext for ext, spec in specs.items() if spec.kind == "text"} == {
        ".csv", ".txt", ".md", ".log"
    }
    assert {ext for ext, spec in specs.items() if spec.tree_policy == "text_convertible"} == {
        ".csv", ".txt", ".md", ".html", ".htm"
    }
    assert {ext for ext, spec in specs.items() if spec.tree_policy == "source_code"} == {".log"}
    assert {ext for ext, spec in specs.items() if spec.estimate_kind == "pdf_pages"} == {
        ".pdf", ".epub", ".mobi", ".fb2", ".xps"
    }
    assert {ext for ext, spec in specs.items() if spec.estimate_kind == "fast_text"} == {
        ".csv", ".txt", ".md", ".log"
    }
    assert {ext for ext, spec in specs.items() if spec.overwrite_source} == {
        ".csv", ".txt", ".md", ".log"
    }


def test_core_converter_mapping_remains_mutable_compatibility_surface() -> None:
    original = core.CONVERTERS[".md"]
    replacement = lambda *_args, **_kwargs: ("patched", 0)
    try:
        core.CONVERTERS[".md"] = replacement
        assert CONVERTERS[".md"] is replacement
    finally:
        core.CONVERTERS[".md"] = original


def test_registry_import_does_not_break_archive_core_path_utils_cycle() -> None:
    from hammerdown.parsers.archive import convert_zip
    from hammerdown.core.path_utils import get_images_dir_name

    assert CONVERTERS[".zip"] is convert_zip
    assert callable(get_images_dir_name)
