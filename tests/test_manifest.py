from __future__ import annotations

import hashlib
import unittest

from tests.helpers import TempDirCase

from brainlib import manifest


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class IsShippedTest(unittest.TestCase):
    def test_is_shipped_cases(self):
        shipped = [
            "_meta/brain",
            "_meta/brainlib/cli.py",
            "_meta/skeleton/docs/README.md",
            "_meta/managed/CLAUDE.block.md",
            "_meta/.DS_Store.md",  # only a file named exactly .DS_Store is Finder litter
            ".claude/skills/brain-sync/SKILL.md",
            ".claude/skills/brain-sync/references/steps.md",
        ]
        not_shipped = [
            "_meta/MANIFEST.sha256",
            "_meta/brainlib/__pycache__/cli.cpython-312.pyc",
            "_meta/skeleton/scripts/__pycache__/x.py",
            "_meta/brainlib/stray.pyc",
            ".claude/skills/brain-sync/__pycache__/x.pyc",
            "_meta/.DS_Store",
            "_meta/skeleton/docs/.DS_Store",
            ".claude/skills/brain-sync/.DS_Store",
            ".claude/skills/brain-sync/references/.DS_Store",
            ".claude/skills/lab-own/SKILL.md",
            ".claude/skills/brainy/SKILL.md",
            ".claude/skills/brain-sync",  # the folder itself is not a file
            ".claude/settings.json",
            ".claude/commands/brain-x.md",
            "docs/README.md",
            "brain.json",
            "CLAUDE.md",
            "scripts/a.py",
            "tests/test_x.py",
            "_meta",
            "_meta/",
            "_meta/../brain.json",
            "x/_meta/brain",
        ]
        for rel in shipped:
            with self.subTest(shipped=rel):
                self.assertTrue(manifest.is_shipped(rel))
        for rel in not_shipped:
            with self.subTest(not_shipped=rel):
                self.assertFalse(manifest.is_shipped(rel))


class ManifestFilesTest(TempDirCase):
    def put(self, root, rel, text="x\n"):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_manifest_round_trip(self):
        root = self.tmp / "brain"
        self.put(root, "_meta/b.py", "bee\n")
        self.put(root, "_meta/a.py", "ay\n")
        self.put(root, ".claude/skills/brain-x/SKILL.md", "skill\n")
        manifest.write(root, ["_meta/b.py", ".claude/skills/brain-x/SKILL.md", "_meta/a.py"])
        text = (root / "_meta" / "MANIFEST.sha256").read_text(encoding="utf-8")
        self.assertEqual(text, (
            f"{digest('skill' + chr(10))}  .claude/skills/brain-x/SKILL.md\n"
            f"{digest('ay' + chr(10))}  _meta/a.py\n"
            f"{digest('bee' + chr(10))}  _meta/b.py\n"
        ))
        self.assertEqual(manifest.read(root), {
            ".claude/skills/brain-x/SKILL.md": digest("skill\n"),
            "_meta/a.py": digest("ay\n"),
            "_meta/b.py": digest("bee\n"),
        })

    def test_write_skips_paths_that_are_not_shipped(self):
        root = self.tmp / "brain"
        self.put(root, "_meta/a.py")
        self.put(root, "docs/a.md")
        self.put(root, "_meta/__pycache__/a.pyc")
        manifest.write(root, ["_meta/a.py", "docs/a.md", "_meta/__pycache__/a.pyc", "_meta/MANIFEST.sha256"])
        self.assertEqual(list(manifest.read(root)), ["_meta/a.py"])

    def test_write_hashes_bytes_exactly(self):
        root = self.tmp / "brain"
        path = root / "_meta" / "bin.dat"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"\xff\xfe\r\n\x00")
        manifest.write(root, ["_meta/bin.dat"])
        self.assertEqual(manifest.read(root), {"_meta/bin.dat": hashlib.sha256(b"\xff\xfe\r\n\x00").hexdigest()})

    def test_write_replaces_the_previous_manifest(self):
        root = self.tmp / "brain"
        self.put(root, "_meta/a.py")
        self.put(root, "_meta/b.py")
        manifest.write(root, ["_meta/a.py", "_meta/b.py"])
        manifest.write(root, ["_meta/a.py"])
        self.assertEqual(list(manifest.read(root)), ["_meta/a.py"])

    def test_read_without_a_manifest_is_empty(self):
        self.assertEqual(manifest.read(self.tmp), {})

    def test_read_skips_blank_and_malformed_lines(self):
        root = self.tmp / "brain"
        good = digest("x\n")
        self.put(root, "_meta/MANIFEST.sha256", f"\n{good}  _meta/a.py\nnot a line\nshort  _meta/b.py\n{good} _meta/c.py\n")
        self.assertEqual(manifest.read(root), {"_meta/a.py": good})

    def test_read_survives_invalid_utf8(self):
        root = self.tmp / "brain"
        good, other = digest("a\n"), digest("b\n")
        (root / "_meta").mkdir(parents=True)
        (root / manifest.MANIFEST_PATH).write_bytes(
            f"{good}  _meta/a.py\n".encode() + b"\xff\xfe not a manifest line \x80\n"
            + f"{other}  _meta/b.py\n".encode() + b"\xc3(\n")
        self.assertEqual(manifest.read(root), {"_meta/a.py": good, "_meta/b.py": other})

    def test_local_edits_survives_invalid_utf8_in_the_manifest(self):
        root = self.tmp / "brain"
        self.put(root, "_meta/a.py", "a\n")
        (root / manifest.MANIFEST_PATH).write_bytes(f"{digest('a' + chr(10))}  _meta/a.py\n".encode() + b"\xff\xfe\n")
        self.assertEqual(manifest.local_edits(root), [])

    def test_path_with_spaces_round_trips(self):
        root = self.tmp / "brain"
        self.put(root, "_meta/a b/c d.py", "s\n")
        manifest.write(root, ["_meta/a b/c d.py"])
        self.assertEqual(manifest.read(root), {"_meta/a b/c d.py": digest("s\n")})

    def test_local_edits_clean(self):
        root = self.tmp / "brain"
        self.put(root, "_meta/a.py")
        self.put(root, ".claude/skills/brain-x/SKILL.md")
        manifest.write(root, ["_meta/a.py", ".claude/skills/brain-x/SKILL.md"])
        self.assertEqual(manifest.local_edits(root), [])

    def test_local_edits_modified_missing_extra(self):
        root = self.tmp / "brain"
        for rel in ("_meta/a.py", "_meta/b.py", "_meta/c.py", ".claude/skills/brain-x/SKILL.md"):
            self.put(root, rel)
        manifest.write(root, ["_meta/a.py", "_meta/b.py", "_meta/c.py", ".claude/skills/brain-x/SKILL.md"])
        self.put(root, "_meta/a.py", "edited\n")  # modified
        (root / "_meta" / "b.py").unlink()  # missing
        self.put(root, "_meta/d.py")  # extra
        self.put(root, ".claude/skills/brain-x/references/r.md")  # extra, inside a shipped skill
        # None of these count: not shipped, or shipped-but-excluded.
        self.put(root, "_meta/__pycache__/a.pyc")
        self.put(root, "_meta/stray.pyc")
        self.put(root, "_meta/.DS_Store")
        self.put(root, "_meta/skeleton/docs/.DS_Store")
        self.put(root, ".claude/skills/brain-x/.DS_Store")
        self.put(root, ".claude/skills/lab-own/SKILL.md")
        self.put(root, ".claude/settings.json")
        self.put(root, "docs/README.md")
        self.put(root, "brain.json")
        self.assertEqual(manifest.local_edits(root), [
            ".claude/skills/brain-x/references/r.md",
            "_meta/a.py",
            "_meta/b.py",
            "_meta/d.py",
        ])

    def test_local_edits_does_not_read_the_manifest_as_a_shipped_file(self):
        root = self.tmp / "brain"
        self.put(root, "_meta/a.py")
        manifest.write(root, ["_meta/a.py"])
        self.assertNotIn("_meta/MANIFEST.sha256", manifest.local_edits(root))

    def test_local_edits_without_a_manifest_reports_every_shipped_file_as_extra(self):
        root = self.tmp / "brain"
        self.put(root, "_meta/a.py")
        self.put(root, "docs/README.md")
        self.assertEqual(manifest.local_edits(root), ["_meta/a.py"])

    def test_local_edits_with_no_shipped_folders(self):
        root = self.tmp / "empty"
        root.mkdir()
        self.assertEqual(manifest.local_edits(root), [])

    def test_manifest_entry_for_a_path_that_is_a_folder_counts_as_missing(self):
        root = self.tmp / "brain"
        (root / "_meta" / "a.py").mkdir(parents=True)
        (root / manifest.MANIFEST_PATH).write_text(f"{digest('x')}  _meta/a.py\n", encoding="utf-8")
        self.assertEqual(manifest.local_edits(root), ["_meta/a.py"])


if __name__ == "__main__":
    unittest.main()
