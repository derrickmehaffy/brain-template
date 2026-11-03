"""The subcommand registry and dispatcher behind `_meta/brain`."""
from __future__ import annotations

import argparse
import importlib
from typing import List, Optional

from . import paths

# name -> (module under brainlib, one-line help). Each module exposes
# add_arguments(parser) and run(args) -> int; it is imported only when its command is chosen.
COMMANDS: dict[str, tuple[str, str]] = {
    "lint": ("lint", "check skills and the routing map"),
}


def _version() -> str:
    try:
        return (paths.harness_root() / "_meta" / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def _build_parser(chosen: Optional[str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brain", description="The brain template's harness.")
    parser.add_argument("--version", action="version", version="%(prog)s " + _version())
    sub = parser.add_subparsers(dest="command", metavar="<command>", required=True)
    for name, (module, help_text) in COMMANDS.items():
        command = sub.add_parser(name, help=help_text, description=help_text)
        if name == chosen:
            importlib.import_module(f".{module}", __package__).add_arguments(command)
    return parser


def main(argv: List[str]) -> int:
    # Commands come first (the only global options are --version and -h), so the first
    # token that names a command is the chosen one.
    chosen = next((a for a in argv if a in COMMANDS), None)
    parser = _build_parser(chosen)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:  # --version, --help and usage errors (2)
        return exit_.code if isinstance(exit_.code, int) else 0
    module = importlib.import_module(f".{COMMANDS[args.command][0]}", __package__)
    return int(module.run(args))
