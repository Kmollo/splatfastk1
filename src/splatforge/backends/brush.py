from __future__ import annotations

from pathlib import Path

from splatforge.tools import command_for_tool

from .base import BackendPlan, SplatBackend


# Map the user-facing quality preset to a Brush training step count.
# These match the cloud worker so cloud and local produce the same-quality
# result at the same setting.
_STEPS_FOR_QUALITY = {
    "fast":     5000,
    "balanced": 15000,
    "high":     30000,
}


class BrushBackend(SplatBackend):
    name = "brush"
    required_tools = ("brush",)

    def build_plan(self, layout: dict[str, Path], quality: str = "balanced") -> BackendPlan:
        total_steps = _STEPS_FOR_QUALITY.get(quality, _STEPS_FOR_QUALITY["balanced"])
        # Setting --export-every == --total-steps means Brush exports the .ply
        # ONCE at the very end (instead of every 5000 steps, which is the
        # default and was making "fast" silently run all 30,000 steps).
        command = [
            command_for_tool("brush"),
            str(layout["root"]),
            "--total-steps", str(total_steps),
            "--export-every", str(total_steps),
            "--export-path", str(layout["splat"]),
            "--export-name", "scene.ply",
        ]

        return BackendPlan(
            label="Brush Gaussian splat training",
            command=command,
            expected_output=layout["splat"] / "scene.ply",
        )
