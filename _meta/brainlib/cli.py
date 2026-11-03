"""The subcommand registry and dispatcher behind `_meta/brain`."""
from __future__ import annotations

import argparse
import importlib
from typing import List, Optional

from . import paths

# name -> (module under brainlib, one-line help). Each module exposes
# add_arguments(parser) and run(args) -> int; it is imported only when its command is chosen.
COMMANDS: dict[str, tuple[str, str]] = {
    "adopt": ("cmd_adopt", "turn an existing folder into a brain, touching none of its files (--dry-run to look)"),
    "doctor": ("doctor", "read-only health check of this brain (--quick skips tests, nested repos, the network)"),
    "env-sync": ("envsync", "add the key names .env.example lists to .env; never prints a value"),
    "gate": ("gate", "the skill gate: record, check, waive, status"),
    "hook": ("hook", "the pre-commit privacy guard: pre-commit, install, self-test"),
    "init": ("cmd_init", "turn a copy of the template into a brain (a dry run with --dry-run)"),
    "lint": ("lint", "check skills and the routing map"),
    "new": ("cmd_new", "make a brain from this template checkout (a dry run with --dry-run)"),
    "practices": ("practices", "check, index and search the practices store"),
    "rename-skill": ("rename", "rename a skill everywhere it is named (a dry run unless --apply)"),
    "route": ("route", "apply a router's rules file and name one skill"),
    "routing": ("routing", "routing map tools"),
    "update": ("cmd_update", "pull the template's committed changes into this brain (a dry run with --dry-run)"),
    "upstream": ("upstream", "upstream suggestions this brain has recorded for the template: list"),
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
