from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BackendPlan:
    label: str
    command: list[str]
    expected_output: Path


class SplatBackend:
    name = "base"
    required_tools: tuple[str, ...] = ()

    def build_plan(self, layout: dict[str, Path], quality: str = "balanced") -> BackendPlan:
        raise NotImplementedError
