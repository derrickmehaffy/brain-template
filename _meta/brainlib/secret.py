"""`brain secret run KEY[,KEY...] COMMAND [ARG...]`: run a command with secrets in its environment, never
printing a value.

This is how anything that is not one of the brain's Python scripts gets a secret: an MCP server in `.mcp.json`,
a CLI tool, a one-off command. Each KEY is looked up the way the scripts' `.env` loader does it: the environment
first, then `.env` at the brain root. A value written as a 1Password reference (`op://vault/item/field`) is read
with `op read` at that moment, so `.env` can hold references instead of values. The command then replaces this
process, with the keys added to its environment.

Messages name a key, never a value. What the command prints is its own business: never run one that echoes its
environment.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

from . import envsync, paths

OP_PREFIX = "op://"
OP_TIMEOUT = 120  # seconds `op read` gets, a 1Password unlock prompt included
_KEY = re.compile(envsync.KEY_RE)
_COMMENT = re.compile(r"\s+#")


class SecretError(Exception):
    """A key that cannot be given a value. The message names the key, never a value."""


def read_env_file(path: Path) -> Dict[str, str]:
    """The KEY=value pairs of `path`; {} when it is not there. The scripts' loader's rules: `export ` allowed, a
    quoted value taken as written, an unquoted one ending at whitespace followed by `#`. Other lines are skipped."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")  # -sig: a byte order mark is not part of a key
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as exc:
        raise SecretError(f"cannot read {Path(path).name} ({type(exc).__name__})") from None
    values: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("export") and line[6:7] in (" ", "\t"):
            line = line[6:].lstrip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not _KEY.fullmatch(key):
            continue  # blank, a comment, or not an assignment
        if value[:1] in ("'", '"'):
            end = value.find(value[0], 1)
            value = value[1:end] if end > 0 else value[1:]
        else:
            value = _COMMENT.split(value, 1)[0]
        values[key] = value
    return values


def _op_read(name: str, reference: str) -> str:
    """The value a 1Password reference points at, read with `op read`. Its own messages (not signed in, no such
    item) go to stderr as they are; they never hold the value."""
    op = shutil.which("op")
    if op is None:
        raise SecretError(f"{name} is a 1Password reference, but the `op` command is not installed")
    try:
        done = subprocess.run([op, "read", "--no-newline", reference], stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, timeout=OP_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise SecretError(f"{name}: `op read` did not answer within {OP_TIMEOUT}s") from None
    except OSError as exc:
        raise SecretError(f"{name}: `op` could not be run ({exc.strerror or type(exc).__name__})") from None
    if done.returncode != 0:
        raise SecretError(f"{name}: `op read` failed (exit {done.returncode}); is 1Password unlocked and the "
                          "reference right?")
    value = os.fsdecode(done.stdout)
    if not value:
        raise SecretError(f"{name}: its 1Password reference holds an empty value")
    return value


def resolve(root: Path, names: List[str]) -> Dict[str, str]:
    """name -> value for each of `names`: the environment first, then `.env` at `root`, with an `op://` reference
    read from 1Password. Raises SecretError for the first name that has no value."""
    from_file = None
    found: Dict[str, str] = {}
    for name in names:
        value = os.environ.get(name, "")
        if not value:
            if from_file is None:
                from_file = read_env_file(Path(root) / envsync.ENV)
            value = from_file.get(name, "")
        if not value:
            raise SecretError(f"{name} is not set: add the name with `_meta/brain env-sync --add {name}` and ask the "
                              "person to fill in its value, or an op:// reference, in .env")
        if value.startswith(OP_PREFIX):
            value = _op_read(name, value)
        found[name] = value
    return found


# -- the command ----------------------------------------------------------------------------------


def add_arguments(parser) -> None:
    import argparse

    actions = parser.add_subparsers(dest="action", metavar="<action>", required=True)
    runner = actions.add_parser(
        "run", help="run COMMAND with KEY (comma-separated for several) in its environment; never prints a value",
        description="Run COMMAND with each KEY in its environment, taken from the environment or .env, an op:// "
                    "reference read from 1Password. Example: _meta/brain secret run FORGE_TOKEN gh api user")
    runner.add_argument("keys", metavar="KEY[,KEY...]", help="the secret names, comma-separated")
    runner.add_argument("to_run", nargs=argparse.REMAINDER, metavar="COMMAND [ARG...]", help="what to run")


def run(args) -> int:
    names = [name.strip() for name in args.keys.split(",") if name.strip()]
    bad = [name for name in names if not _KEY.fullmatch(name)]
    command = args.to_run[1:] if args.to_run[:1] == ["--"] else args.to_run
    if not names or bad:
        # The text is not repeated: someone may have typed NAME=value, and no value is ever printed.
        print("secret: give key names such as FORGE_TOKEN (letters, digits and '_'), comma-separated, never a value",
              file=sys.stderr)
        return 2
    if not command:
        print("secret: name the command to run after the keys", file=sys.stderr)
        return 2
    try:
        values = resolve(paths.harness_root(), names)
    except SecretError as exc:
        print(f"secret: {exc}", file=sys.stderr)
        return 1
    try:
        os.execvpe(command[0], command, {**os.environ, **values})
    except OSError as exc:
        print(f"secret: cannot run {command[0]} ({exc.strerror or type(exc).__name__})", file=sys.stderr)
        return 127
    return 0  # not reached: exec replaced this process
