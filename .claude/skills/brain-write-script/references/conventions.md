# Script conventions

Paths here are from the brain root. Every block below is a whole file or a whole snippet that runs as
written; copy it and change the names, rather than writing your own version from memory.

## Layout

```text
scripts/
  README.md
  common/                     code two or more systems share
    __init__.py
    env.py                    the .env loader every script that needs a secret uses
  <system>/                   one folder per system, named as a Python identifier
    __init__.py
    list_repos.py             read-only: the default
    apply_repo_labels.py      changes something: the name starts apply_, write_ or delete_
  tests/
    __init__.py
    test_common_env.py
    test_<system>_<name>.py   one file per script
```

- Each folder has an `__init__.py` (one docstring line is enough). Without it, a package of the same
  name installed for `scripts.python` can win the import.
- Never name a system folder or a script after a module you import (`http`, `email`, `json`,
  `logging`, `test`, or a third-party package): it would shadow that module for every script and test.
- A script in a skill's own `scripts/` folder (the skill is its only caller) still has its test in
  `scripts/tests/`, so the one test run finds it. Load it by path; see "Testing a script that lives in a
  skill".

## The docstring

The first statement of every script. The first line is what the next session reads to decide whether
to reuse the script or write another, so make it say what question the script answers or what fact
about the system it encodes, not what it calls.

```python
"""WHY THIS EXISTS: <the question it answers or the fact it encodes, in one or two lines; why a file
and not an inline command>.

Usage:   python3 scripts/<system>/<name>.py [ARGS]
Reads:   <the system, and what of it: endpoints, folders, tables>.
Writes:  nothing.  (apply_/write_/delete_: exactly what it changes, and how to undo it)
Env:     <names it takes from the environment or .env, e.g. FORGE_TOKEN>, or none.
Needs:   <third-party packages, only when brain.json scripts.packages is "allowed">, or nothing.
Probed:  docs/CAPABILITIES.md, <system>, <YYYY-MM-DD>
"""
```

## Finding the brain root

A script needs the root only to import from `scripts/common/` or to read a file in the brain. Walk up
from the script's own file to the folder holding `brain.json`; never write a home or absolute path,
which breaks on the next machine and leaks a username into git.

```python
from __future__ import annotations

import sys
from pathlib import Path


def brain_root() -> Path:
    """The nearest folder above this file that holds brain.json."""
    for folder in Path(__file__).resolve().parents:
        if (folder / "brain.json").is_file():
            return folder
    sys.exit(f"{Path(__file__).name}: not inside a brain (no brain.json above it)")


sys.path.insert(0, str(brain_root() / "scripts"))  # `from common import env`, however it is run
from common import env  # noqa: E402
```

## The `.env` loader

Create `scripts/common/__init__.py`, this file and its test (below) before the first script that needs
a secret. Values come from the environment first, then from `.env` at the brain root, which the loader
reads itself: the agent is denied reading `.env`, and that is deliberate. Every message names a key or
a line number, never a value.

```python
# scripts/common/env.py
"""WHY THIS EXISTS: scripts take secrets and private settings from the environment, never from their
arguments, and the values live in the brain's .env, which the agent is denied reading. This reads
.env for them and never shows a value: its errors name a key or a line number, nothing else.

Usage:   from common import env; forge_token = env.secret("FORGE_TOKEN")
Reads:   the environment, then .env at the brain root.
Writes:  nothing.
Env:     whichever names the caller asks for.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Iterable, Optional, Set

MASK = "***"
_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_COMMENT = re.compile(r"\s+#")
_seen: Set[str] = set()  # every value secret() has returned, so redact() can hide them all


class EnvError(Exception):
    """A value is missing or .env cannot be read. The message never holds a value."""


def brain_root(start: Optional[Path] = None) -> Path:
    """The nearest folder at or above `start` (default: this file) that holds brain.json."""
    here = Path(start if start is not None else __file__).resolve()
    for folder in (here, *here.parents):
        if (folder / "brain.json").is_file():
            return folder
    raise EnvError(f"no brain.json at or above {here}")


def read_env_file(path: Path) -> Dict[str, str]:
    """The KEY=value pairs of a .env file; {} when there is none.

    Blank lines and # comments are skipped and `export ` is allowed. A value in matching quotes is
    taken as written (no escapes); an unquoted value ends at whitespace followed by #.
    """
    name = Path(path).name
    try:
        text = Path(path).read_text(encoding="utf-8-sig")  # -sig: a byte order mark is not part of a key
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as exc:
        raise EnvError(f"cannot read {name} ({type(exc).__name__})") from None
    values: Dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not _KEY.fullmatch(key):
            raise EnvError(f"{name} line {number} is not KEY=value")
        if value[:1] in ("'", '"'):
            end = value.find(value[0], 1)
            if end < 0:
                raise EnvError(f"{name} line {number} opens a quote it never closes")
            value = value[1:end]
        else:
            value = _COMMENT.split(value, 1)[0]
        values[key] = value
    return values


def secret(name: str, env_file: Optional[Path] = None) -> str:
    """The value of `name`: the environment first, then the brain's .env (or `env_file`).

    Raises EnvError, naming the key and never a value, when it is unset or empty.
    """
    value = os.environ.get(name, "")
    if not value:
        value = read_env_file(env_file or brain_root() / ".env").get(name, "")
    if not value:
        raise EnvError(f"{name} is not set: add the name with `_meta/brain env-sync --add {name}` "
                       f"and ask the person to fill in its value in .env")
    _seen.add(value)
    return value


def redact(text: str, values: Optional[Iterable[str]] = None) -> str:
    """`text` with each value replaced by ***; by default every value secret() has returned.

    Pass anything that could echo a secret (an error body, a URL, an exception) through this before
    printing it.
    """
    hidden = _seen if values is None else set(values)
    for value in sorted((v for v in hidden if v), key=len, reverse=True):
        text = text.replace(value, MASK)
    return text
```

- Take private settings (a hostname, an internal address) through `env.secret` as well: the script
  then commits clean past the pre-commit guard's deny patterns, and `redact` hides them too.
- Name the variable after what it holds (`forge_token = env.secret("FORGE_TOKEN")`), not a bare
  `token`: the name then says which system the value opens. Never write a value out, even a stand-in
  in a test; build it at runtime (`"t" * 24`). The pre-commit guard refuses a quoted literal of eight
  or more characters assigned to a bare `token`, `secret`, `password` or `api_key`, and a whole
  `NAME_TOKEN=value` line with an unquoted value, wherever either appears.
- A new name: `_meta/brain env-sync --add FORGE_TOKEN` writes `FORGE_TOKEN=` into `.env.example` and
  `.env`; the person fills in the value. `_meta/brain env-sync --list` says which names are `set`,
  `empty` or `missing`, never a value.

## Read-only, in one place

A script that talks to a system over HTTP sends every request through one function that refuses
anything but a read, before anything is sent. A test calls it with each writing method (below). A
read-only script that works on files has no code path that writes; its test snapshots the tree.

```python
# scripts/forge/list_repos.py
"""WHY THIS EXISTS: lists every repo on the forge; its API returns at most 50 per page and gives no
total, so a single request silently misses the rest.

Usage:   python3 scripts/forge/list_repos.py
Reads:   the forge API (GET /api/v1/repos/search).
Writes:  nothing.
Env:     FORGE_URL, FORGE_TOKEN
Needs:   nothing.
Probed:  docs/CAPABILITIES.md, forge API, 2026-11-02
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Dict, Iterator, List, Optional


def brain_root() -> Path:
    """The nearest folder above this file that holds brain.json."""
    for folder in Path(__file__).resolve().parents:
        if (folder / "brain.json").is_file():
            return folder
    sys.exit(f"{Path(__file__).name}: not inside a brain (no brain.json above it)")


sys.path.insert(0, str(brain_root() / "scripts"))  # `from common import env`, however it is run
from common import env  # noqa: E402

READS = ("GET", "HEAD")
PAGE = 50


class ReadOnlyError(RuntimeError):
    """This script only reads: a request that could change something is refused before it is sent."""


def request(method: str, url: str, headers: Optional[Dict[str, str]] = None) -> bytes:
    """The one way this script talks to the forge, so the read-only rule lives in one place."""
    if method.upper() not in READS:
        raise ReadOnlyError(f"{method.upper()} refused: {Path(__file__).name} only reads")
    req = urllib.request.Request(url, headers=headers or {}, method=method.upper())
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def repos(base: str, headers: Dict[str, str]) -> Iterator[dict]:
    """Every repo, page by page, until a page comes back short."""
    page = 1
    while True:
        reply = request("GET", f"{base}/api/v1/repos/search?page={page}&limit={PAGE}", headers)
        batch = json.loads(reply)["data"]
        yield from batch
        if len(batch) < PAGE:
            return
        page += 1


def main(argv: Optional[List[str]] = None) -> int:
    try:
        base = env.secret("FORGE_URL").rstrip("/")
        headers = {"Authorization": "Bearer " + env.secret("FORGE_TOKEN")}
        for repo in repos(base, headers):
            print(repo["full_name"])
    except Exception as exc:  # any error can carry the URL or the header: redact before printing
        print(f"list_repos: {env.redact(str(exc))}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

A script that changes something is named `apply_`, `write_` or `delete_`, prints what it would change,
and changes nothing unless it is given `--apply`. Run it with `--apply` only when the person asked
for that run.

## `docs/CAPABILITIES.md` rows

The table's columns are fixed by the skeleton:

```markdown
| System | Can | Cannot | Verified | How checked |
| --- | --- | --- | --- | --- |
| forge API (v1, read-only token) | list repos, 50 a page with no total; read releases and open issues | filter repos by topic (the `topic` parameter is ignored: the same 50 come back); create or change anything: not tried, it would write | 2026-11-02 | `python3 scripts/forge/probe_api.py`: GET /api/v1/version, GET /api/v1/repos/search?topic=x |
| mod loader (1.4) | load mods from its folder in name order, case-sensitive; read one config file per mod | reload a mod without a restart; report load errors anywhere but its log | 2026-11-02 | started the game with two dummy mods, `a-test` and `B-test`, and read the load log |
| local files (this machine) | walk a tree and read sizes without following symlinks | read folders this user may not (skipped and counted, not an error) | 2026-11-02 | `python3 scripts/files/count_large_files.py --min-gb 1 .` |
```

- **System**: the system, its version and the access the probe had (which token, which account).
  One row per system and access level; a re-probe edits that row and its date, and git keeps the old.
- **Can**: what worked, as verbs and objects someone can rely on.
- **Cannot**: what failed, was refused or is not offered, with the evidence (a status code, an
  ignored parameter). This is the column that saves the most time. Never leave it empty: write what
  you tried that worked, or `not tried: <why>` when finding out would have needed a write.
- **Verified**: the day the probe ran, `YYYY-MM-DD`.
- **How checked**: the command or the requests, so anyone can repeat it.
- Write a literal `|` inside a cell as `\|`. Never put a secret, a hostname or an internal address in
  a row: the file is committed.

## Tests

One test file per script in `scripts/tests/`, named `test_<system>_<name>.py`. Test the logic (parsing,
paging, the decision the script makes) and the refusal paths (a missing value, a write refused, a
secret kept out of output). Never touch the network or a live system: fake the reply. Run every test
from the brain root, with the interpreter `brain.json` `scripts.python` names (`python3` below):

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/tests -t scripts
```

`-t scripts` puts `scripts/` on the import path, so tests import `from common import env` and
`from forge import list_repos`.

### The loader's test

```python
# scripts/tests/test_common_env.py
"""common/env.py: where values come from, and that no message ever shows one."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common import env

VALUE = "v" * 20  # a stand-in, never a real value


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="env test "))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.file = self.tmp / ".env"

    def write(self, text):
        self.file.write_text(text, encoding="utf-8")

    def test_reads_pairs_comments_quotes_and_export(self):
        self.write(f"# a comment\n\nexport LAB_A={VALUE}\nLAB_B='{VALUE} #kept'\nLAB_C={VALUE} # note\nLAB_D=\n")
        self.assertEqual(env.read_env_file(self.file),
                         {"LAB_A": VALUE, "LAB_B": VALUE + " #kept", "LAB_C": VALUE, "LAB_D": ""})

    def test_a_byte_order_mark_is_not_part_of_the_first_key(self):
        self.file.write_bytes(b"\xef\xbb\xbf" + f"LAB_A={VALUE}\n".encode("utf-8"))
        self.assertEqual(env.read_env_file(self.file), {"LAB_A": VALUE})

    def test_no_file_is_no_values(self):
        self.assertEqual(env.read_env_file(self.tmp / "absent"), {})

    def test_environment_wins_over_the_file(self):
        self.write("LAB_A=from-file\n")
        with mock.patch.dict(os.environ, {"LAB_A": VALUE}):
            self.assertEqual(env.secret("LAB_A", self.file), VALUE)

    def test_missing_or_empty_names_the_key_only(self):
        self.write(f"LAB_EMPTY=\nLAB_OTHER={VALUE}\n")
        with mock.patch.dict(os.environ):
            for key in ("LAB_EMPTY", "LAB_ABSENT"):
                os.environ.pop(key, None)
                with self.assertRaises(env.EnvError) as caught:
                    env.secret(key, self.file)
                self.assertIn(key, str(caught.exception))
                self.assertNotIn(VALUE, str(caught.exception))

    def test_a_bad_line_is_named_by_number_not_shown(self):
        self.write(f"LAB_A={VALUE}\n{VALUE}\n")
        with self.assertRaises(env.EnvError) as caught:
            env.read_env_file(self.file)
        self.assertIn("line 2", str(caught.exception))
        self.assertNotIn(VALUE, str(caught.exception))

    def test_redact_hides_every_value_read(self):
        with mock.patch.dict(os.environ, {"LAB_A": VALUE}):
            env.secret("LAB_A", self.file)
        self.assertEqual(env.redact(f"failed with {VALUE}"), "failed with ***")
        self.assertEqual(env.redact("abc", ["b"]), "a***c")

    def test_finds_the_root_from_below(self):
        (self.tmp / "brain.json").write_text("{}", encoding="utf-8")
        (self.tmp / "scripts" / "common").mkdir(parents=True)
        self.assertEqual(env.brain_root(self.tmp / "scripts" / "common"), self.tmp.resolve())
```

### An HTTP script's test

```python
# scripts/tests/test_forge_list_repos.py
"""forge/list_repos.py: paging, the read-only guard and redaction, with the network faked."""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from forge import list_repos

FAKE = {"FORGE_URL": "https://forge.invalid", "FORGE_TOKEN": "t" * 24}  # stand-ins, never real values


def serve(*sizes):
    """A fake urlopen serving pages of the given sizes, and the list of methods it was called with."""
    methods, replies = [], iter(sizes)

    def urlopen(req, timeout=None):
        methods.append(req.get_method())
        data = [{"full_name": f"me/repo{i}"} for i in range(next(replies))]
        return io.BytesIO(json.dumps({"data": data}).encode())

    return urlopen, methods


class ListRepos(unittest.TestCase):
    def test_follows_pages_until_a_short_one_and_only_reads(self):
        urlopen, methods = serve(list_repos.PAGE, 3)
        with mock.patch.dict(os.environ, FAKE), mock.patch("urllib.request.urlopen", urlopen), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(list_repos.main([]), 0)
        self.assertEqual(len(out.getvalue().splitlines()), list_repos.PAGE + 3)
        self.assertEqual(methods, ["GET", "GET"])

    def test_refuses_every_method_that_writes(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "post"):
            with self.assertRaises(list_repos.ReadOnlyError):
                list_repos.request(method, "https://forge.invalid/api/v1/repos")

    def test_an_error_that_echoes_the_header_is_redacted(self):
        def fails(req, timeout=None):
            raise OSError("refused: " + req.get_header("Authorization"))

        with mock.patch.dict(os.environ, FAKE), mock.patch("urllib.request.urlopen", fails), \
                redirect_stderr(io.StringIO()) as err:
            self.assertEqual(list_repos.main([]), 1)
        self.assertNotIn(FAKE["FORGE_TOKEN"], err.getvalue())
        self.assertIn("***", err.getvalue())

    def test_a_missing_value_names_the_key(self):
        empty = Path(tempfile.mkdtemp(prefix="no env "))  # a root with no .env in it
        self.addCleanup(shutil.rmtree, empty)
        with mock.patch.dict(os.environ, {"FORGE_URL": FAKE["FORGE_URL"]}), \
                mock.patch.object(list_repos.env, "brain_root", return_value=empty), \
                redirect_stderr(io.StringIO()) as err:
            os.environ.pop("FORGE_TOKEN", None)
            self.assertEqual(list_repos.main([]), 1)
        self.assertIn("FORGE_TOKEN is not set", err.getvalue())
```

### A file script's test

For a script that reads files, prove it wrote nothing by comparing every path's size and modification
time before and after a run, on a temporary tree. The script:

```python
# scripts/files/count_large_files.py
"""WHY THIS EXISTS: counts the files at or over a size in a folder tree, without following symlinks
into other trees and without stopping at the first folder below it that it may not read; a folder
it cannot read at all is an error (exit 1), never a count of zero.

Usage:   python3 scripts/files/count_large_files.py FOLDER [--min-gb 1]
Reads:   sizes under FOLDER, never contents.
Writes:  nothing.
Env:     none.
Needs:   nothing.
Probed:  docs/CAPABILITIES.md, local files, 2026-11-02
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional, Tuple

GB = 1024 ** 3


def count_large(folder: str, min_bytes: int) -> Tuple[int, int, int]:
    """(files at or over `min_bytes`, their total size, folders below it that could not be read).

    Raises OSError when `folder` itself cannot be read, so that is never reported as no files.
    """
    count = total = unreadable = 0

    def skip(error: OSError) -> None:
        nonlocal unreadable
        if error.filename == folder:  # the root itself: an error, not a skipped folder
            raise error
        unreadable += 1

    for dirpath, _dirs, files in os.walk(folder, onerror=skip):  # never follows symlinked folders
        for name in files:
            try:
                size = os.lstat(os.path.join(dirpath, name)).st_size  # a link's own size, not its target's
            except OSError:
                continue
            if size >= min_bytes:
                count, total = count + 1, total + size
    return count, total, unreadable


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Count files at or over a size in a folder tree.")
    parser.add_argument("folder")
    parser.add_argument("--min-gb", type=float, default=1.0)
    args = parser.parse_args(argv)
    try:
        count, total, unreadable = count_large(args.folder, int(args.min_gb * GB))
    except OSError as exc:
        print(f"count_large_files: cannot read {args.folder}: {exc.strerror or exc}", file=sys.stderr)
        return 1
    print(f"{count} files at or over {args.min_gb:g} GB, {total / GB:.1f} GB in all")
    if unreadable:
        print(f"{unreadable} folders could not be read and were skipped", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

Its test:

```python
# scripts/tests/test_files_count_large_files.py
"""files/count_large_files.py: the counting, unreadable folders and roots, and that it only reads."""
from __future__ import annotations

import io
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from files import count_large_files


def snapshot(root: Path) -> dict:
    """Every path under `root`, with its size and modification time."""
    return {p.as_posix(): (p.lstat().st_size, p.lstat().st_mtime_ns) for p in [root, *root.rglob("*")]}


class CountLargeFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="count large "))
        self.addCleanup(shutil.rmtree, self.tmp)
        (self.tmp / "big.bin").write_bytes(b"x" * 2048)
        (self.tmp / "small.txt").write_bytes(b"x" * 10)
        (self.tmp / "sub").mkdir()
        (self.tmp / "sub" / "bigger.bin").write_bytes(b"x" * 4096)

    def test_counts_files_at_or_over_the_size(self):
        self.assertEqual(count_large_files.count_large(str(self.tmp), 2048), (2, 6144, 0))

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can read every folder")
    def test_an_unreadable_folder_is_counted_not_fatal(self):
        locked = self.tmp / "locked"
        locked.mkdir()
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o700)
        self.assertEqual(count_large_files.count_large(str(self.tmp), 2048), (2, 6144, 1))
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(count_large_files.main([str(locked)]), 1)  # the root itself: an error

    def test_a_root_that_is_not_there_is_an_error(self):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            self.assertEqual(count_large_files.main([str(self.tmp / "absent")]), 1)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("cannot read", err.getvalue())

    def test_only_reads(self):
        before = snapshot(self.tmp)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(count_large_files.main([str(self.tmp), "--min-gb", "0"]), 0)
        self.assertEqual(snapshot(self.tmp), before)
```

### Testing a script that lives in a skill

When the only caller is one skill, the script sits in that skill's `scripts/` folder, and its test
in `scripts/tests/` loads it by path (here, for a homelab brain with prefix `lab`):

```python
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "brain.json").is_file())
_spec = importlib.util.spec_from_file_location(
    "check_backups_age", ROOT / ".claude" / "skills" / "lab-check-backups" / "scripts" / "check_age.py")
check_age = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_age)
```

## Portability

Brains run on Linux and macOS. Do file work in Python rather than shelling out; when a script must
run another program, pass an argument list (`subprocess.run(["git", "log", "-1"], check=True)`), never
a shell string, and use no GNU-only flags.
