from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


FilterKind = Literal["include", "exclude"]


@dataclass(frozen=True)
class FilterOperation:
    kind: FilterKind
    pattern: str


@dataclass(frozen=True)
class RunConfig:
    inputs: tuple[str, ...] = ()
    filters: tuple[FilterOperation, ...] = ()
    tree: bool = False
    all_formats: bool = False
    overwrite: bool = False
    skip_existing: bool = False
    output_dir: str | None = None
    merge_target: str | None = None
    merge_auto: bool = False
    stdout: bool = False
    confirm: bool = False
    include_gitignored: bool = False


@dataclass(frozen=True)
class ResolvedInput:
    """Keep a requested input's identity and original locator beside its local path."""

    identity: str
    original: str
    path: Path

    def __post_init__(self) -> None:
        if not self.identity:
            raise ValueError("resolved input identity must not be empty")


@dataclass(frozen=True)
class ResolvedInputs:
    """An ordered set of input identities; equal paths need not mean equal inputs."""

    items: tuple[ResolvedInput, ...] = ()

    def __post_init__(self) -> None:
        identities = tuple(item.identity for item in self.items)
        if len(identities) != len(set(identities)):
            raise ValueError("resolved input identities must be unique")


@dataclass(frozen=True)
class PlannedOutput:
    input_index: int
    input_identity: str
    path: Path | None

    def __post_init__(self) -> None:
        if not self.input_identity:
            raise ValueError("planned output input identity must not be empty")


@dataclass(frozen=True)
class OutputPlan:
    """Per-input destinations indexed in the same order as the resolved inputs."""

    outputs: tuple[PlannedOutput, ...] = ()

    def __post_init__(self) -> None:
        expected_indexes = tuple(range(len(self.outputs)))
        actual_indexes = tuple(output.input_index for output in self.outputs)
        if actual_indexes != expected_indexes:
            raise ValueError("planned output indexes must match their ordered positions")

        identities = tuple(output.input_identity for output in self.outputs)
        if len(identities) != len(set(identities)):
            raise ValueError("planned output input identities must be unique")
