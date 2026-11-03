"""The shipped set and `_meta/MANIFEST.sha256`: which files in a brain the template owns, the hash each had
when it was installed, and which of them the person has since edited."""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Dict, List

MANIFEST_PATH = "_meta/MANIFEST.sha256"
_SHA256 = re.compile(r"[0-9a-f]{64}")


def is_shipped(relpath: str) -> bool:
    """Whether `relpath` (a slash-separated path from the brain root) is a file the template owns:
    anything under `_meta/` or `.claude/skills/brain-*/`, except bytecode and the manifest itself."""
    if "\n" in relpath or "\r" in relpath:  # a manifest line holds one path
        return False
    parts = relpath.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    if "__pycache__" in parts or parts[-1].endswith(".pyc") or relpath == MANIFEST_PATH:
        return False
    if parts[0] == "_meta":
        return len(parts) >= 2
    return parts[:2] == [".claude", "skills"] and len(parts) >= 4 and parts[2].startswith("brain-")


def _digest(path: Path) -> str:
    """The SHA-256 of the file's bytes. Raises OSError when it cannot be read."""
    sha = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            sha.update(chunk)
    return sha.hexdigest()


def write(root, relpaths: List[str]) -> None:
    """Write `_meta/MANIFEST.sha256` for `relpaths` under `root`: one `<sha256>  <relpath>` line each,
    sorted by path. A path that is not shipped is left out, so the manifest never lists a file `local_edits`
    would not look at. A shipped path that cannot be read raises OSError."""
    root = Path(root)
    entries = {rel: _digest(root / rel) for rel in relpaths if is_shipped(rel)}
    text = "".join(f"{entries[rel]}  {rel}\n" for rel in sorted(entries))
    target = root / MANIFEST_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = target.with_name(target.name + ".tmp")
    try:
        scratch.write_text(text, encoding="utf-8")
        os.replace(str(scratch), str(target))
    finally:
        if scratch.exists():
            scratch.unlink()


def read(root) -> Dict[str, str]:
    """The manifest as {relpath: sha256}. A missing manifest is empty, and a blank or malformed line is
    skipped (the file it would have named then shows up in `local_edits`)."""
    try:
        text = (Path(root) / MANIFEST_PATH).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    found: Dict[str, str] = {}
    for line in text.split("\n"):
        digest, separator, relpath = line.rstrip("\r").partition("  ")
        if separator and relpath and _SHA256.fullmatch(digest):
            found[relpath] = digest
    return found


def _shipped_on_disk(root: Path) -> List[str]:
    """Every shipped file that exists under `root`."""
    folders = [root / "_meta", *sorted(p for p in (root / ".claude" / "skills").glob("brain-*") if p.is_dir())]
    found: List[str] = []
    for folder in folders:
        for dirpath, dirnames, filenames in os.walk(str(folder)):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                relpath = os.path.relpath(os.path.join(dirpath, name), str(root)).replace(os.sep, "/")
                if is_shipped(relpath):
                    found.append(relpath)
    return found


def local_edits(root) -> List[str]:
    """The shipped files under `root` that differ from the manifest, sorted: modified, missing and extra
    (on disk but not in the manifest). Reads files only; it does not ask git. Without a manifest every
    shipped file is extra."""
    root = Path(root)
    recorded = {rel: digest for rel, digest in read(root).items() if is_shipped(rel)}
    edited = set(_shipped_on_disk(root)) - set(recorded)
    for relpath, digest in recorded.items():
        try:
            if _digest(root / relpath) != digest:
                edited.add(relpath)
        except OSError:  # gone, or no longer a readable file
            edited.add(relpath)
    return sorted(edited)
