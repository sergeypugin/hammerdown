from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from hammerdown.core.run_models import (
    FilterOperation,
    OutputPlan,
    PlannedOutput,
    ResolvedInput,
    ResolvedInputs,
    RunConfig,
)


def test_run_config_keeps_ordered_filter_operations_and_options() -> None:
    config = RunConfig(
        inputs=("first.txt", "second.txt"),
        filters=(
            FilterOperation("include", "*.txt"),
            FilterOperation("exclude", "private/**"),
            FilterOperation("include", "private/keep.txt"),
        ),
        tree=True,
        all_formats=True,
        overwrite=True,
        skip_existing=True,
        output_dir="Output/CaseSensitive",
        merge_target="Merge/CaseSensitive.MD",
        merge_auto=True,
        stdout=True,
        confirm=True,
        include_gitignored=True,
    )

    assert config.inputs == ("first.txt", "second.txt")
    assert [operation.kind for operation in config.filters] == ["include", "exclude", "include"]
    assert [operation.pattern for operation in config.filters] == [
        "*.txt",
        "private/**",
        "private/keep.txt",
    ]
    assert config.output_dir == "Output/CaseSensitive"
    assert config.merge_target == "Merge/CaseSensitive.MD"
    assert config.tree and config.all_formats and config.overwrite and config.skip_existing
    assert config.merge_auto and config.stdout and config.confirm and config.include_gitignored


def test_resolved_inputs_retain_identity_original_locator_and_order(tmp_path: Path) -> None:
    local_path = tmp_path / "same.txt"
    inputs = ResolvedInputs(
        (
            ResolvedInput("selection-1", "https://example.test/one", local_path),
            ResolvedInput("selection-2", "https://example.test/two", local_path),
        )
    )

    assert [item.identity for item in inputs.items] == ["selection-1", "selection-2"]
    assert [item.original for item in inputs.items] == [
        "https://example.test/one",
        "https://example.test/two",
    ]
    assert all(item.path == local_path for item in inputs.items)


def test_resolved_inputs_reject_duplicate_identities() -> None:
    first = ResolvedInput("same-id", "first.txt", Path("first.txt"))
    second = ResolvedInput("same-id", "second.txt", Path("second.txt"))

    with pytest.raises(ValueError, match="identities must be unique"):
        ResolvedInputs((first, second))


def test_resolved_input_requires_nonempty_identity() -> None:
    with pytest.raises(ValueError, match="identity must not be empty"):
        ResolvedInput("", "source.txt", Path("source.txt"))


def test_output_plan_is_contiguously_indexed_and_allows_shared_or_absent_paths() -> None:
    shared_target = Path("combined.md")
    plan = OutputPlan(
        (
            PlannedOutput(0, "first", shared_target),
            PlannedOutput(1, "second", shared_target),
            PlannedOutput(2, "third", None),
        )
    )

    assert [output.input_index for output in plan.outputs] == [0, 1, 2]
    assert [output.path for output in plan.outputs] == [shared_target, shared_target, None]


@pytest.mark.parametrize(
    "outputs",
    [
        (PlannedOutput(1, "first", Path("first.md")),),
        (
            PlannedOutput(0, "first", Path("first.md")),
            PlannedOutput(2, "second", Path("second.md")),
        ),
        (
            PlannedOutput(0, "first", Path("first.md")),
            PlannedOutput(0, "second", Path("second.md")),
        ),
    ],
)
def test_output_plan_rejects_noncontiguous_indexes(outputs: tuple[PlannedOutput, ...]) -> None:
    with pytest.raises(ValueError, match="indexes must match their ordered positions"):
        OutputPlan(outputs)


def test_output_plan_rejects_duplicate_input_identities() -> None:
    with pytest.raises(ValueError, match="identities must be unique"):
        OutputPlan(
            (
                PlannedOutput(0, "same", Path("first.md")),
                PlannedOutput(1, "same", Path("second.md")),
            )
        )


def test_contract_records_are_immutable() -> None:
    config = RunConfig(inputs=("source.txt",))
    resolved = ResolvedInput("source", "source.txt", Path("source.txt"))
    output = PlannedOutput(0, "source", Path("source.md"))

    with pytest.raises(FrozenInstanceError):
        config.tree = True  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        resolved.identity = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        output.path = None  # type: ignore[misc]
