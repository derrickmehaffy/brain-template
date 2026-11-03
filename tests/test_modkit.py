"""The mod kit (`_meta/modkit/`) and `brain mods`, once each end to end: a mod started from the starter and linked,
its copy of the kit kept in step, a broken mod caught by `lint`, and the kit's own mods well formed.

The kit's TypeScript has its own tests, run by hand with `claude plugin test` (see `_meta/modkit/README.md`):
this suite never needs the `claude` CLI.
"""
from __future__ import annotations

import json
import os
import shutil

from tests.helpers import TEMPLATE_ROOT, TempDirCase  # first: puts <template>/_meta on sys.path

from brainlib import config, mods  # noqa: E402
from brainlib.report import BROKEN, GAP  # noqa: E402

MODKIT = TEMPLATE_ROOT / "_meta" / "modkit"


class ModsCase(TempDirCase):
    """A brain with the prefix `lab`, holding the template's mod kit and nothing else."""

    def setUp(self) -> None:
        super().setUp()
        self.root = self.tmp / "brain"
        (self.root / "_meta").mkdir(parents=True)
        shutil.copytree(str(MODKIT), str(self.root / "_meta" / "modkit"))
        (self.root / ".claude" / "skills").mkdir(parents=True)
        (self.root / "brain.json").write_text(json.dumps({"name": "lab", "prefix": "lab", "role": "brain"}),
                                             encoding="utf-8")
        self.cfg = config.load(self.root)

    def new(self, name: str = "health"):
        lines, status = mods.new(self.root, self.cfg, name)
        self.assertEqual(status, 0, "\n".join(lines))
        return self.root / "mods" / f"lab-{name}"


class ModsTest(ModsCase):
    def test_new_starts_a_linked_mod_from_the_starter_that_lint_accepts(self):
        gitignore = self.root / ".gitignore"
        gitignore.write_text("/*\n!/.gitignore\n!/scripts/\n", encoding="utf-8")
        mod = self.new()
        manifest = json.loads((mod / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "lab-health")
        self.assertFalse(mods.differs(mods.kit_dir(self.root), mod / "hooks" / "kit"))
        link = self.root / ".claude" / "skills" / "lab-health"
        self.assertEqual(os.readlink(str(link)), os.path.join("..", "..", "mods", "lab-health"))
        self.assertTrue(gitignore.read_text(encoding="utf-8").endswith("!/mods/\n"))  # an allowlist now saves mods/
        self.assertEqual(mods.lint_mods(self.root, self.cfg, []), [])

    def test_sync_puts_back_a_kit_copy_edited_in_place(self):
        mod = self.new()
        (mod / "hooks" / "kit" / "tokens.ts").write_text("// edited in place\n", encoding="utf-8")
        self.assertEqual(mods.sync(self.root, check=True), (["differs lab-health"], 1))
        self.assertIn(GAP, [f.severity for f in mods.lint_mods(self.root, self.cfg, [])])
        self.assertEqual(mods.sync(self.root), (["copied  lab-health"], 0))
        self.assertEqual(mods.sync(self.root, check=True), (["ok      lab-health"], 0))

        # a mod whose hooks/ is a link to somewhere else is refused, and that place is left untouched
        outside = self.tmp / "outside"
        shutil.copytree(str(mod / "hooks"), str(outside))
        (outside / "kit" / "tokens.ts").write_text("// not the brain's\n", encoding="utf-8")
        shutil.rmtree(str(mod / "hooks"))
        os.symlink(str(outside), str(mod / "hooks"))
        lines, status = mods.sync(self.root)
        self.assertEqual(status, 1)
        self.assertIn("mods/lab-health/hooks is a link", lines[0])
        self.assertEqual((outside / "kit" / "tokens.ts").read_text(encoding="utf-8"), "// not the brain's\n")

    def test_lint_reports_a_broken_mod_and_a_dangling_link(self):
        mod = self.new()
        (mod / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "something-else"}), encoding="utf-8")
        os.symlink(os.path.join("..", "..", "mods", "lab-gone"), str(self.root / ".claude" / "skills" / "lab-gone"))
        broken = {f.subject for f in mods.lint_mods(self.root, self.cfg, []) if f.severity == BROKEN}
        self.assertEqual(broken, {"lab-health", "lab-gone"})

    def test_the_kits_starter_and_gallery_are_well_formed_mods(self):
        for folder in (MODKIT / "gallery", MODKIT / "starter"):
            manifest = json.loads((folder / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
            hooks = json.loads((folder / "hooks" / "hooks.json").read_text(encoding="utf-8"))
            self.assertEqual(hooks["modules"], ["./register.tsx"])
            self.assertTrue((folder / manifest["types"]).is_file())
        self.assertFalse((MODKIT / "starter" / "hooks" / "kit").exists(), "the starter gets its kit from `mods new`")
