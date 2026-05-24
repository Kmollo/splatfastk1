from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .doctor import run_doctor
from .pipeline import CreateOptions, create_project
from .ui.server import run_ui


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="splatforge",
        description="Create Blender-ready Gaussian splat project folders from video or images.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check installed external tools.")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable diagnostics.")
    doctor.add_argument("--hardware", action="store_true", help="Include local hardware guidance.")

    ui = subparsers.add_parser("ui", help="Open the local SplatfastK1 web interface.")
    ui.add_argument("--host", default="127.0.0.1", help="Host for the local UI server.")
    ui.add_argument("--port", type=int, default=8765, help="Port for the local UI server.")
    ui.add_argument(
        "--open",
        action="store_true",
        help="Open the UI in the default browser after the server starts.",
    )

    create = subparsers.add_parser("create", help="Create a splat project from a video or image folder.")
    create.add_argument("source", type=Path, help="Video file or folder of images.")
    create.add_argument("--output", "-o", type=Path, help="Output project folder.")
    create.add_argument(
        "--quality",
        choices=["fast", "balanced", "high"],
        default="balanced",
        help="Frame extraction and reconstruction preset.",
    )
    create.add_argument(
        "--matcher",
        choices=["sequential", "exhaustive"],
        default="sequential",
        help="Feature matching strategy for reconstruction.",
    )
    create.add_argument(
        "--backend",
        choices=["brush", "none"],
        default="brush",
        help="Gaussian splat generation backend.",
    )
    create.add_argument("--dry-run", action="store_true", help="Print planned commands only.")
    create.add_argument(
        "--continue-on-missing-tools",
        action="store_true",
        help="Create the project folder even when external tools are unavailable.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        return run_doctor(as_json=args.json, include_hardware=args.hardware)

    if args.command == "ui":
        return run_ui(host=args.host, port=args.port, open_browser=args.open)

    if args.command == "create":
        options = CreateOptions(
            source=args.source,
            output=args.output,
            quality=args.quality,
            matcher=args.matcher,
            backend=args.backend,
            dry_run=args.dry_run,
            continue_on_missing_tools=args.continue_on_missing_tools,
        )
        try:
            return create_project(options)
        except RuntimeError as exc:
            print(f"Pipeline failed: {exc}")
            return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
