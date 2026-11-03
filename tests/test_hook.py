from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from datetime import date
from pathlib import Path

from tests.helpers import TEMPLATE_ROOT, TempDirCase  # first: puts <template>/_meta on sys.path
from brainlib import config, hook, practices, routing_sync
from brainlib.report import BLOCK

# Planted secrets are assembled at run time: no source file may hold a literal credential shape,
# because the template's own pre-commit guard scans every file it commits.
PLANTED = {
    "private-key": "-----BEGIN " + "RSA PRIVATE KEY" + "-----",
    "github-token": "gh" + "p_" + "a" * 36,
    "aws-key": "AK" + "IA" + "B" * 16,
    "slack-token": "xo" + "xb-" + "1234567890" + "abcdef",
    "anthropic-key": "sk-" + "ant-" + "c" * 24,
    "openai-key": "sk-" + "d" * 24,
    "assignment": "pass" + "word=" + '"' + "hunter2" + "hunter2" + '"',  # a quoted literal
}
DOTENV = "API_" + "TOKEN=" + "abcdefgh" + "12345678"  # the other `assignment` shape: a dotenv line

GITHUB = "github-token"  # kept apart from the text after it: "<that word>: <8 characters>" is itself a finding

SHIM_TEXT = (
    "#!/bin/sh\n"
    "# brain-template pre-commit shim\n"
    'exec "$(git rev-parse --show-toplevel)/_meta/brain" hook pre-commit\n'
)

FENCE = "`" * 3
MAP = f"{FENCE}mermaid\nflowchart LR\nIN(a request):::entry --> lab-a:::work\n{FENCE}\n"
SKILL_BODY = "Does the thing.\n\n**Call it directly when:** the person names it.\n\n## Done when\n\n- it is done\n"
ENTRY = (
    "---\nid: sample-fact\ntags: [demo]\ndurability: durable\nevidence: researched\n"
    f"verified: {date.today().isoformat()}\nsource: a note\nreviewed-against: []\n---\nA short fact.\n"
)


class HookCase(TempDirCase):
    def brain_repo(self, extra=None, private=None, skills=False) -> Path:
        """A git repository holding a brain: the harness, a minimal brain.json and the managed allowlist."""
        root = self.fake_brain(extra=extra)
        if not skills:  # shipped brain-* skills are not under test here
            shutil.rmtree(str(root / ".claude" / "skills"), ignore_errors=True)
        shipped_map = root / "_meta" / "ROUTING-META.md"
        if shipped_map.exists():
            shipped_map.unlink()
        allowlist = (TEMPLATE_ROOT / "_meta" / "managed" / "gitignore.block").read_text(encoding="utf-8")
        (root / ".gitignore").write_text(allowlist, encoding="utf-8")
        if private is not None:
            (root / ".brain-private").write_text("\n".join(private) + "\n", encoding="utf-8")
        self.git(root, "init", "-q")
        self.git(root, "symbolic-ref", "HEAD", "refs/heads/main")
        return root

    def stage(self, root: Path, rel: str, data="x\n") -> None:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            data = data.encode("utf-8")
        target.write_bytes(data)
        self.git(root, "add", "-f", "--", rel)

    def pre_commit(self, root: Path) -> subprocess.CompletedProcess:
        return self.run_brain(root, "hook", "pre-commit")

    def blocked(self, root: Path, rule: str, location: str) -> subprocess.CompletedProcess:
        r = self.pre_commit(root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(f"BLOCK  {rule}: {location}", r.stdout)
        return r

    def passes(self, root: Path) -> subprocess.CompletedProcess:
        r = self.pre_commit(root)
        self.assertEqual((r.returncode, "BLOCK" in r.stdout), (0, False), r.stdout + r.stderr)
        return r

    def commit_attempt(self, root: Path, message: str = "change") -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "commit", "-q", "-m", message], cwd=str(root), env=self.env,
            capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
        )

    def synced_skill_brain(self) -> Path:
        """A brain with one skill and a map that names it, the skill's Where block written."""
        root = self.brain_repo()
        self.make_skill(root, "lab-a", "Does X. Use when Y.", SKILL_BODY)
        (root / "docs").mkdir()
        (root / "docs" / "ROUTING.md").write_text(MAP, encoding="utf-8")
        routing_sync.sync(root, config.load(root), check=False)
        return root


class BlocksEachRuleTest(HookCase):
    def test_blocks_each_rule(self):
        doc = "docs/notes.md"
        cases = [
            # (rule, files to stage, brain.json extra, .brain-private lines, expected location)
            ("env-file", {".env": "A=1\n"}, None, None, ".env"),
            ("env-file", {"config/.env.local": "A=1\n"}, None, None, "config/.env.local"),
            ("private-key", {doc: "a\nb\n" + PLANTED["private-key"] + "\n"}, None, None, doc + ":3"),
            ("github-token", {doc: "ref " + PLANTED["github-token"] + "\n"}, None, None, doc + ":1"),
            ("github-token", {doc: "pat " + "github" + "_pat_" + "E" * 50 + "\n"}, None, None, doc + ":1"),
            ("aws-key", {doc: "\n" + PLANTED["aws-key"] + "\n"}, None, None, doc + ":2"),
            ("slack-token", {doc: PLANTED["slack-token"] + "\n"}, None, None, doc + ":1"),
            ("anthropic-key", {doc: "k " + PLANTED["anthropic-key"] + "\n"}, None, None, doc + ":1"),
            ("openai-key", {doc: "k " + PLANTED["openai-key"] + "\n"}, None, None, doc + ":1"),
            ("assignment", {doc: "x\n" + PLANTED["assignment"] + "\n"}, None, None, doc + ":2"),
            ("assignment", {doc: "x\ny\n" + DOTENV + "\n"}, None, None, doc + ":3"),
            ("assignment", {doc: "export DB_" + "PASSWORD=" + "abcdefgh1234\n"}, None, None, doc + ":1"),
            ("deny-pattern", {doc: "the host 10.13.4.5 is up\n"},
             {"privacy": {"deny_patterns": [r"10\.13\.\d+\.\d+"]}}, None, doc + ":1"),
            ("private-pattern", {doc: "x\nthe castle-black host\n"}, None, [r"\bcastle-black\b"], doc + ":2"),
            ("large-file", {"docs/big.md": "a" * 2000}, {"privacy": {"max_file_kb": 1}}, None, "docs/big.md"),
        ]
        for rule, files, extra, private, location in cases:
            with self.subTest(rule=rule, location=location):
                root = self.brain_repo(extra=extra, private=private)
                for rel, text in files.items():
                    self.stage(root, rel, text)
                self.blocked(root, rule, location)

    def test_private_patterns_ignore_case(self):
        root = self.brain_repo(private=[r"\bcastle-black\b"])
        self.stage(root, "docs/notes.md", "Visit Castle-Black on Monday.\n")
        self.blocked(root, "private-pattern", "docs/notes.md:1")

    def test_deny_patterns_are_exactly_as_written(self):
        root = self.brain_repo(extra={"privacy": {"deny_patterns": ["internal-host", "(?i)SHOUTING"]}})
        self.stage(root, "docs/notes.md", "Internal-Host is fine; shouting is not.\n")
        self.blocked(root, "deny-pattern", "docs/notes.md:1")
        quiet = self.brain_repo(extra={"privacy": {"deny_patterns": ["internal-host"]}})
        self.stage(quiet, "docs/notes.md", "Internal-Host is not matched by a case-sensitive pattern.\n")
        self.passes(quiet)

    def test_a_staged_nested_repo_is_blocked(self):
        root = self.brain_repo()
        inner = root / "docs" / "inner"
        inner.mkdir(parents=True)
        self.git(inner, "init", "-q")
        self.git(inner, "commit", "-q", "--allow-empty", "-m", "i")
        subprocess.run(["git", "add", "-f", "docs/inner"], cwd=str(root), env=self.env, capture_output=True, check=True)
        self.blocked(root, "nested-repo", "docs/inner")

    def test_a_nested_repo_is_blocked_even_when_git_is_told_to_ignore_submodules(self):
        root = self.brain_repo()
        self.git(root, "config", "diff.ignoreSubmodules", "all")  # hides a staged gitlink from a plain `git diff`
        inner = root / "docs" / "inner"
        inner.mkdir(parents=True)
        self.git(inner, "init", "-q")
        self.git(inner, "commit", "-q", "--allow-empty", "-m", "i")
        subprocess.run(["git", "add", "-f", "docs/inner"], cwd=str(root), env=self.env, capture_output=True, check=True)
        self.blocked(root, "nested-repo", "docs/inner")

    def test_a_file_inside_a_nested_repo_is_blocked(self):
        root = self.brain_repo()
        inner = root / "docs" / "inner"
        inner.mkdir(parents=True)
        self.git(inner, "init", "-q")
        (inner / "page.md").write_text("hello\n", encoding="utf-8")
        # git itself may refuse to add a file below an unindexed repository; the guard must hold either way.
        self.git(root, "update-index", "--add", "--cacheinfo",
                 "100644," + self.git(root, "hash-object", "-w", "docs/inner/page.md").strip() + ",docs/inner/page.md")
        self.blocked(root, "nested-repo", "docs/inner/page.md")

    def test_every_rule_has_a_case_in_the_self_test_and_here(self):
        self.assertEqual(len(hook.RULES), len(set(hook.RULES)))
        names = [name for name, _pattern in hook.CREDENTIAL_PATTERNS]
        self.assertEqual(  # `assignment` is two patterns under one name
            names,
            ["private-key", "github-token", "aws-key", "slack-token", "anthropic-key", "openai-key",
             "assignment", "assignment"],
        )
        for name in names:
            self.assertIn(name, hook.RULES)

    def test_an_invalid_pattern_blocks_without_echoing_it(self):
        root = self.brain_repo(extra={"privacy": {"deny_patterns": ["(unclosed-castle"]}}, private=["(unclosed-keep"])
        self.stage(root, "docs/notes.md", "fine\n")
        r = self.pre_commit(root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("BLOCK  deny-pattern:", r.stdout)
        self.assertIn("BLOCK  private-pattern:", r.stdout)
        self.assertNotIn("castle", r.stdout + r.stderr)
        self.assertNotIn("keep", r.stdout + r.stderr)

    def test_an_unreadable_brain_json_blocks(self):
        root = self.brain_repo()
        self.stage(root, "docs/notes.md", "fine\n")
        (root / "brain.json").write_text("{not json", encoding="utf-8")
        r = self.pre_commit(root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("BLOCK  config:", r.stdout)

    def test_outside_a_repository_blocks(self):
        root = self.fake_brain()  # no git init
        r = self.pre_commit(root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("BLOCK  git:", r.stdout)


class CleanCommitsTest(HookCase):
    def test_clean_commit_and_env_example_pass(self):
        root = self.brain_repo()
        self.stage(root, "docs/notes.md", "Plain notes about the homelab.\n")
        self.stage(root, ".env.example", "# names only\nAPI_KEY=\nDB_PASSWORD=\n")
        self.stage(root, "config/.env.example", "TOKEN=\n")
        r = self.passes(root)
        self.assertIn("ok     pre-commit: 3 staged file(s) checked", r.stdout)

    def test_deleting_a_file_is_not_a_finding(self):
        root = self.brain_repo()
        self.stage(root, "docs/old.md", "old\n")
        self.git(root, "commit", "-q", "-m", "base")
        self.git(root, "rm", "-q", "docs/old.md")
        r = self.passes(root)
        self.assertIn("ok     pre-commit: 0 staged file(s) checked", r.stdout)

    def test_nothing_staged_passes(self):
        self.passes(self.brain_repo())

    def test_placeholders_not_flagged(self):
        root = self.brain_repo()
        lines = [
            'token = os.environ["TOKEN"]',
            "api_key=$API_KEY",
            "password=<your password>",
            "password: ${PASSWORD}",
            'token = response.json()["token"]',
            'token = env.secret("FORGE_TOKEN")',
            "tokens = fetch_tokens(command)",
            'secret = "short"',
            "TOKEN=$FROM_THE_SHELL",
        ]
        self.stage(root, "docs/setup.md", "\n".join(lines) + "\n")
        self.passes(root)

    def test_bare_begin_marker_is_not_a_private_key(self):
        root = self.brain_repo()
        self.stage(root, "docs/notes.md", 'pattern = re.compile(r"-----BEGIN")\n-----BEGIN CERTIFICATE-----\n')
        self.passes(root)

    def test_brain_json_skipped_for_deny_patterns_only(self):
        root = self.brain_repo(
            extra={"description": "talks to internal-host", "privacy": {"deny_patterns": ["internal-host"]}},
            private=[r"\bcastle-black\b"],
        )
        self.git(root, "add", "brain.json")
        self.passes(root)  # its own deny list does not match itself
        self.stage(root, "docs/notes.md", "uses internal-host\n")
        self.blocked(root, "deny-pattern", "docs/notes.md:1")

        private = self.brain_repo(extra={"description": "the castle-black box"}, private=[r"\bcastle-black\b"])
        self.git(private, "add", "brain.json")
        self.blocked(private, "private-pattern", "brain.json:")

        credential = self.brain_repo(extra={"note": "key " + PLANTED["github-token"]})
        self.git(credential, "add", "brain.json")
        self.blocked(credential, "github-token", "brain.json:")

    def test_large_file_allow_glob(self):
        root = self.brain_repo(extra={"privacy": {"max_file_kb": 1, "large_file_allow": ["assets/**", "*.pdf"]}})
        self.stage(root, "assets/big.txt", "a" * 3000)
        self.stage(root, "manual.pdf", "b" * 3000)
        self.stage(root, "docs/exact.md", "c" * 1024)  # at the limit, not over it
        self.passes(root)
        self.stage(root, "docs/big.md", "a" * 1025)
        r = self.blocked(root, "large-file", "docs/big.md")
        self.assertNotIn("assets/big.txt", r.stdout)
        self.assertNotIn("manual.pdf", r.stdout)
        self.assertNotIn("exact.md", r.stdout)


class SafetyTest(HookCase):
    def test_findings_never_echo_secret(self):
        root = self.brain_repo(
            extra={"privacy": {"deny_patterns": [r"10\.13\.\d+\.\d+"]}}, private=[r"\bcastle-black\b"],
        )
        lines = list(PLANTED.values()) + [DOTENV, "host 10.13.4.5", "the castle-black box"]
        self.stage(root, "docs/notes.md", "\n".join(lines) + "\n")
        self.stage(root, "docs/other.md", "ref " + PLANTED["github-token"] + "\n")
        r = self.pre_commit(root)
        self.assertEqual(r.returncode, 1)
        out = r.stdout + r.stderr
        for rule in PLANTED:
            self.assertIn(f"BLOCK  {rule}: docs/notes.md:", r.stdout)
        for value in list(PLANTED.values()) + [DOTENV, "abcdefgh12345678", "10.13.4.5", "castle-black", "hunter2"]:
            self.assertNotIn(value, out)
        for fragment in ("p_" + "a" * 8, "ant-" + "c" * 8, "A" * 8, "1234567890", "RSA PRIVATE"):
            self.assertNotIn(fragment, out)

    def test_binary_and_latin1_files_do_not_crash(self):
        root = self.brain_repo()
        png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(256)) * 8
        self.stage(root, "docs/logo.png", png)
        self.stage(root, "docs/cafe.txt", "café résumé naïve\n".encode("latin-1"))
        self.stage(root, "docs/mixed.txt", b"ok \xff\xfe\xfd still text\n")
        r = self.passes(root)
        self.assertNotIn("Traceback", r.stderr)

    def test_latin1_text_is_still_scanned(self):
        root = self.brain_repo()
        data = "café\n".encode("latin-1") + PLANTED["github-token"].encode("ascii") + b"\n"
        self.stage(root, "docs/cafe.txt", data)
        self.blocked(root, "github-token", "docs/cafe.txt:2")

    def test_a_non_utf8_file_name_is_reported_without_crashing(self):
        root = self.brain_repo()
        name = os.fsdecode(b"docs/caf\xe9.md")
        try:
            self.stage(root, name, "ref " + PLANTED["github-token"] + "\n")
        except (OSError, AssertionError, ValueError):
            self.skipTest("this file system does not allow a non-UTF-8 file name")
        r = self.pre_commit(root)
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"BLOCK  {GITHUB}: docs/caf", r.stdout)
        self.assertNotIn("Traceback", r.stderr)

    def test_the_credential_patterns_have_the_pinned_boundaries(self):
        def hits(text: str):
            return [rule for rule, line in hook.credential_hits(text.encode("utf-8"))]

        self.assertEqual(hits("gh" + "p_" + "a" * 36), ["github-token"])
        self.assertEqual(hits("gh" + "p_" + "a" * 35), [])
        self.assertEqual(hits("AK" + "IA" + "A" * 15), [])
        self.assertEqual(hits("sk-" + "a" * 19), [])
        self.assertEqual(hits("sk-" + "a" * 20), ["openai-key"])
        self.assertEqual(sorted(hits("sk-" + "ant-" + "a" * 20)), ["anthropic-key", "openai-key"])
        self.assertEqual(hits("xo" + "xb-" + "1" * 9), [])
        self.assertEqual(hits("xo" + "xs-" + "1" * 10), ["slack-token"])
        self.assertEqual(hits("-----BEGIN " + "PRIVATE KEY" + "-----"), ["private-key"])
        self.assertEqual(hits("Token: " + '"' + "abcdefgh" + '"'), ["assignment"])  # quoted literal, any case
        self.assertEqual(hits("secret = " + "'" + "abcdefgh" + "'"), ["assignment"])
        self.assertEqual(hits("api" + "_key=" + '"' + "x" * 8 + '"'), ["assignment"])
        self.assertEqual(hits("secret = 'short'"), [])  # under 8 characters
        self.assertEqual(hits("secret = " + '"' + "abcdefgh" + "'"), [])  # the quotes must match
        self.assertEqual(hits("secret = " + '"' + "$" + "abcdefgh" + '"'), [])  # a variable reference
        self.assertEqual(hits("Token: " + "abcdefgh"), [])  # unquoted, and not a dotenv line
        self.assertEqual(hits("API_" + "KEY=" + "x" * 8), ["assignment"])  # a dotenv line
        self.assertEqual(hits("  export MY_" + "SECRET=" + "x" * 8 + "  "), ["assignment"])
        self.assertEqual(hits("API_" + "KEY=" + "x" * 7), [])
        self.assertEqual(hits("API_" + "KEY=" + "x" * 8 + " # note"), [])  # not the whole line
        self.assertEqual(hits("api" + "_key=" + "x" * 8), [])  # a dotenv NAME is upper case
        self.assertEqual(hits("DB_PASSWORD=${DB_PASSWORD}"), [])
        self.assertEqual(hits("OTHER=" + "x" * 20), [])
        self.assertEqual(hits("pass" + "word=" + '"' + "hunter2" * 2 + '"'), ["assignment"])

    def test_binary_content_has_no_hits(self):
        self.assertEqual(hook.credential_hits(b"\x00" + PLANTED["github-token"].encode("ascii")), [])

    def test_the_harness_and_its_tests_pass_their_own_scan(self):
        # The guard will scan every file the template commits, itself included.
        offenders = []
        for folder in ("_meta", "tests"):
            for path in sorted((TEMPLATE_ROOT / folder).rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    hits = hook.credential_hits(path.read_bytes())
                    if hits:
                        offenders.append(f"{path.relative_to(TEMPLATE_ROOT).as_posix()}:{hits[0][1]} ({hits[0][0]})")
        self.assertEqual(offenders, [])


class StagedChecksTest(HookCase):
    def test_staged_checks(self):
        with self.subTest(check="a BROKEN skill"):
            root = self.brain_repo()
            self.stage(root, ".claude/skills/lab-bad/SKILL.md", "---\nname: lab-bad\ndescription:\n---\nBody.\n")
            r = self.pre_commit(root)
            self.assertEqual(r.returncode, 1)
            self.assertRegex(r.stdout, r"BLOCK  lint: lab-bad: .*description")

        with self.subTest(check="a stale Where block"):
            root = self.synced_skill_brain()
            self.git(root, "add", "-f", ".claude", "docs")
            self.passes(root)  # control: a freshly synced skill and map are clean
            path = root / ".claude" / "skills" / "lab-a" / "SKILL.md"
            text = path.read_text(encoding="utf-8")
            at = text.index("<!-- where:begin")
            at = text.index("\n", at) + 1
            path.write_text(text[:at] + "Words that sync did not write.\n" + text[at:], encoding="utf-8")
            self.git(root, "add", "-f", ".claude")
            r = self.pre_commit(root)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("BLOCK  routing-sync: .claude/skills/lab-a/SKILL.md", r.stdout)

        with self.subTest(check="a map edit and a new skill leave blocks stale"):
            root = self.synced_skill_brain()
            self.git(root, "add", "-f", ".claude", "docs")
            (root / "docs" / "ROUTING.md").write_text(
                MAP.replace("IN(a request):::entry --> lab-a:::work",
                            "IN(a request):::entry --> lab-b:::work\nlab-b --> lab-a:::work"), encoding="utf-8")
            self.make_skill(root, "lab-b", "Does X. Use when Y.", SKILL_BODY)
            self.git(root, "add", "-f", ".claude", "docs")
            r = self.pre_commit(root)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("BLOCK  routing-sync:", r.stdout)

        with self.subTest(check="a bad rules.json"):
            root = self.synced_skill_brain()
            self.git(root, "add", "-f", ".claude", "docs")
            self.stage(root, ".claude/skills/lab-a/rules.json", "{not json")
            r = self.pre_commit(root)
            self.assertEqual(r.returncode, 1)
            self.assertRegex(r.stdout, r"BLOCK  lint: lab-a: rules\.json")

        with self.subTest(check="a practice error"):
            root = self.brain_repo()
            self.stage(root, "docs/practices/bad-entry.md", "no frontmatter at all\n")
            r = self.pre_commit(root)
            self.assertEqual(r.returncode, 1)
            self.assertIn("BLOCK  practices-lint: docs/practices/bad-entry.md:", r.stdout)

    def test_clean_staged_skill_and_map_pass(self):
        root = self.synced_skill_brain()
        self.git(root, "add", "-f", ".claude", "docs")
        r = self.passes(root)
        self.assertIn("ok     pre-commit:", r.stdout)

    def test_skill_checks_run_only_when_skills_are_staged(self):
        root = self.brain_repo()
        self.make_skill(root, "lab-bad", "", "Body.")  # broken, but not staged
        self.stage(root, "docs/notes.md", "fine\n")
        self.passes(root)

    def test_a_deleted_skill_still_triggers_the_checks(self):
        root = self.synced_skill_brain()
        self.git(root, "add", "-f", ".claude", "docs")
        self.git(root, "commit", "-q", "-m", "base")
        self.make_skill(root, "lab-b", "Does X. Use when Y.", SKILL_BODY)  # unmapped, so the map is now wrong
        shutil.rmtree(str(root / ".claude" / "skills" / "lab-a"))
        self.git(root, "rm", "-q", "-r", "--cached", ".claude/skills/lab-a")
        r = self.pre_commit(root)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("BLOCK  lint:", r.stdout)  # the map still draws lab-a

    def test_practice_index_must_be_staged_and_current(self):
        root = self.brain_repo()
        self.stage(root, "docs/practices/sample-fact.md", ENTRY)
        self.assertEqual([f for f in practices.lint(root, config.load(root), date.today()) if f.severity == BLOCK], [])
        self.blocked(root, "practices-index", "docs/practices/INDEX.md")  # entry staged, no index at all

        r = self.run_brain(root, "practices", "index")  # regenerated in the working tree, not staged
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((root / "docs" / "practices" / "INDEX.md").is_file())
        self.blocked(root, "practices-index", "docs/practices/INDEX.md")

        self.git(root, "add", "-f", "docs/practices/INDEX.md")
        self.passes(root)

        self.stage(root, "docs/practices/sample-fact.md", ENTRY.replace("A short fact.", "A different short fact."))
        self.blocked(root, "practices-index", "docs/practices/INDEX.md")  # entry changed, staged index is old

    def test_practice_index_with_no_entries_needs_no_file(self):
        root = self.brain_repo()
        self.stage(root, "docs/practices/README.md", "# Practices\n")
        self.passes(root)

    def test_deleting_the_last_entry_makes_the_staged_index_stale(self):
        root = self.brain_repo()
        self.stage(root, "docs/practices/sample-fact.md", ENTRY)
        self.run_brain(root, "practices", "index")
        self.git(root, "add", "-f", "docs/practices/INDEX.md")
        self.git(root, "commit", "-q", "-m", "base")
        self.git(root, "rm", "-q", "docs/practices/sample-fact.md")
        self.blocked(root, "practices-index", "docs/practices/INDEX.md")


class InstallTest(HookCase):
    def hook_path(self, root: Path) -> Path:
        return root / ".git" / "hooks" / "pre-commit"

    def test_install_and_refusals(self):
        root = self.brain_repo()
        r = self.run_brain(root, "hook", "install")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        installed = self.hook_path(root)
        self.assertEqual(installed.read_text(encoding="utf-8"), SHIM_TEXT)
        self.assertEqual(installed.stat().st_mode & 0o777, 0o755)
        self.assertEqual(hook.SHIM_MARKER, "# brain-template pre-commit shim")
        self.assertIn(str(installed), r.stdout)

        again = self.run_brain(root, "hook", "install")
        self.assertEqual(again.returncode, 0, "installing over our own shim is allowed")
        self.assertEqual(installed.read_text(encoding="utf-8"), SHIM_TEXT)

        with self.subTest(refusal="a foreign hook"):
            other = self.brain_repo()
            foreign = "#!/bin/sh\necho mine\n"
            self.hook_path(other).parent.mkdir(parents=True, exist_ok=True)
            self.hook_path(other).write_text(foreign, encoding="utf-8")
            r = self.run_brain(other, "hook", "install")
            self.assertEqual(r.returncode, 1)
            self.assertIn("not the brain template's", r.stderr)
            self.assertEqual(self.hook_path(other).read_text(encoding="utf-8"), foreign)

        with self.subTest(refusal="core.hooksPath"):
            other = self.brain_repo()
            self.git(other, "config", "core.hooksPath", "elsewhere")
            r = self.run_brain(other, "hook", "install")
            self.assertEqual(r.returncode, 1)
            self.assertIn("core.hooksPath", r.stderr)
            self.assertFalse(self.hook_path(other).exists())

        with self.subTest(refusal="not a repository"):
            r = self.run_brain(self.fake_brain(), "hook", "install")
            self.assertEqual(r.returncode, 1)
            self.assertIn("not a git repository", r.stderr)

    def test_install_raises_hook_error(self):
        root = self.brain_repo()
        self.git(root, "config", "core.hooksPath", "elsewhere")
        with self.assertRaises(hook.HookError):
            hook.install(root)

    def test_install_returns_the_hook_path(self):
        root = self.brain_repo()
        self.assertEqual(Path(hook.install(root)), self.hook_path(root))

    def test_install_from_worktree_uses_common_dir(self):
        main = self.brain_repo()
        self.git(main, "add", "-f", "_meta", "brain.json", ".gitignore")
        self.git(main, "commit", "-q", "-m", "base")
        wt = main.parent / "linked worktree"
        self.git(main, "worktree", "add", "-q", "-b", "linked", str(wt))
        r = self.run_brain(wt, "hook", "install")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.hook_path(main).read_text(encoding="utf-8"), SHIM_TEXT)
        self.assertTrue((wt / ".git").is_file())  # a worktree has no hooks directory of its own

        # the shim runs from the worktree, where git sets GIT_DIR and a worktree index
        self.stage(wt, "docs/leak.md", "ref " + PLANTED["github-token"] + "\n")
        refused = self.commit_attempt(wt)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("github-token", refused.stdout + refused.stderr)

    def test_shim_works_in_path_with_space(self):
        root = self.brain_repo()
        self.assertIn(" ", str(root.parent))
        r = self.run_brain(root, "hook", "install")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

        self.stage(root, "docs/leak.md", "ref " + PLANTED["github-token"] + "\n")
        refused = self.commit_attempt(root, "leak")
        self.assertNotEqual(refused.returncode, 0)
        combined = refused.stdout + refused.stderr
        self.assertIn(f"BLOCK  {GITHUB}: docs/leak.md:1", combined)
        self.assertNotIn(PLANTED["github-token"], combined)
        self.assertEqual(self.git(root, "rev-list", "--all", "--count").strip(), "0")

        self.git(root, "rm", "-q", "-f", "--cached", "docs/leak.md")
        self.stage(root, "docs/clean.md", "Nothing secret here.\n")
        accepted = self.commit_attempt(root, "clean")
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        self.assertEqual(self.git(root, "rev-list", "--all", "--count").strip(), "1")

    def test_commit_dash_a_is_checked_too(self):
        root = self.brain_repo()
        self.stage(root, "docs/notes.md", "clean\n")
        self.run_brain(root, "hook", "install")
        self.assertEqual(self.commit_attempt(root, "base").returncode, 0)
        (root / "docs" / "notes.md").write_text("ref " + PLANTED["github-token"] + "\n", encoding="utf-8")
        refused = subprocess.run(
            ["git", "commit", "-q", "-a", "-m", "leak"], cwd=str(root), env=self.env,
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("github-token", refused.stdout + refused.stderr)


class SelfTestTest(HookCase):
    def test_self_test_passes(self):
        r = self.run_brain(self.fake_brain(), "hook", "self-test")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.strip(), f"self-test: {len(hook.RULES)} rules, all blocked")
        self.assertRegex(r.stdout, r"^self-test: \d+ rules, all blocked$")

    def test_self_test_returns_no_failures(self):
        self.assertEqual(hook.self_test(), [])

    def test_self_test_leaves_nothing_behind(self):
        before = set(os.listdir(self.env["TMPDIR"]))
        r = self.run_brain(self.fake_brain(), "hook", "self-test")  # TMPDIR is the isolated os-tmp
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(set(os.listdir(self.env["TMPDIR"])), before)

    def test_self_test_ignores_the_callers_git_location_variables(self):
        env = dict(self.env, GIT_DIR=str(self.tmp / "nowhere"), GIT_INDEX_FILE=str(self.tmp / "nowhere" / "index"))
        r = subprocess.run(
            ["python3", str(TEMPLATE_ROOT / "_meta" / "brain"), "hook", "self-test"],
            cwd=str(self.tmp), env=env, capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"^self-test: \d+ rules, all blocked$")


class UsageTest(HookCase):
    def test_hook_needs_a_subcommand(self):
        r = self.run_brain(self.fake_brain(), "hook")
        self.assertEqual(r.returncode, 2)

    def test_hook_is_registered(self):
        from brainlib import cli

        self.assertEqual(cli.COMMANDS["hook"][0], "hook")
        self.assertEqual(list(cli.COMMANDS), sorted(cli.COMMANDS))


if __name__ == "__main__":
    unittest.main()
