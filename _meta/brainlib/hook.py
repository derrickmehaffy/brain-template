"""`brain hook`: the pre-commit privacy guard, its installer and its self-test (spec §7.3).

The guard looks only at what is staged. A finding names the rule, the file and the line and never the
text that matched, so a refused commit does not copy a secret into a terminal or a log.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import config, gitutil, globs, paths
from .config import Config
from .report import BLOCK, BROKEN, OK, Finding, emit, exit_code

SHIM_MARKER = "# brain-template pre-commit shim"
SHIM = f'#!/bin/sh\n{SHIM_MARKER}\nexec "$(git rev-parse --show-toplevel)/_meta/brain" hook pre-commit\n'

# (rule, pattern), tried on every line of every staged text file.
CREDENTIAL_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{50,}\b")),
    ("aws-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    # A quoted literal of 8+ characters assigned to a secret-sounding name: a bare or compound name
    # (`db_password`, `client_secret`, `SECRET_KEY`), in code (`=`, `:`), a PHP array (`=>`) or with the name
    # itself quoted (JSON). A value that is a reference (`$`, `<`, `{`) or not quoted is not a literal.
    # The name may carry up to 64 characters on either side; the bound keeps a long line from costing time
    # in proportion to its square.
    (
        "assignment",
        re.compile(
            r'''(?i)(?<![A-Za-z0-9])[A-Za-z0-9_-]{0,64}(?:password|passwd|token|api[_-]?key|secret)'''
            r'''(?:[_-]?key)?["']?\s*(?:[:=]|=>)\s*(["'])(?![$<{])[^"'\s]{8,}\1'''
        ),
    ),
    # A dotenv-style line: an UPPER_CASE name and an unquoted (or quoted) value, optionally a compose list item
    # (`- NAME=value`), a Dockerfile `ENV NAME=value`, `export NAME=value` or a YAML `NAME: value`, and a
    # trailing comment. The name is upper case because lower case is ordinary code (`tokens = _tokens(x)`).
    (
        "assignment",
        re.compile(
            r'''(?m)^\s*(?:-\s+)?(?:export\s+|ENV\s+)?[A-Z0-9_]{0,64}(?:PASSWORD|PASSWD|TOKEN|API_KEY|SECRET)'''
            r'''[A-Z0-9_]{0,64}(?:=(["']?)(?![$<{])[^\s"'#]{8,}\1|\s*[=:]\s*(?![$<{"'])[^\s"'#]{8,})'''
            r'''\s*(?:#.*)?$'''
        ),
    ),
]

# Every rule the guard can block on. `self_test` plants one case for each.
RULES: Tuple[str, ...] = (
    "env-file",
    "private-file",
    *dict.fromkeys(name for name, _pattern in CREDENTIAL_PATTERNS),  # `assignment` has two patterns
    "deny-pattern",
    "private-pattern",
    "large-file",
    "nested-repo",
    "lint",
    "routing-sync",
    "practices-lint",
    "practices-index",
)

_SKILLS_PREFIX = ".claude/skills/"
_ROUTING_MAPS = ("docs/ROUTING.md", "_meta/ROUTING-META.md")
_PRACTICES_PREFIX = "docs/practices/"
_PRACTICES_INDEX = "docs/practices/INDEX.md"
_ENV_EXAMPLE = ".env.example"
_PRIVATE_FILES = (config.PRIVATE_FILE, config.LOCAL_JSON)  # this machine's settings: never committed, at any depth
_MASK = "***"


class HookError(Exception):
    """`hook install` cannot proceed; the message says why and what to do."""


def _shown(path: str) -> str:
    """A path safe to print: a name that is not UTF-8 would otherwise crash the output."""
    return path.encode("utf-8", errors="replace").decode("utf-8")


# -- content scanning -----------------------------------------------------------------


def _text_of(data: bytes) -> Optional[str]:
    """The text to scan, or None for a binary file (one holding a NUL byte). Bytes that are not UTF-8 are
    replaced, so a Latin-1 file is still read."""
    if b"\0" in data:
        return None
    return data.decode("utf-8", errors="replace")


def _hits(text: str, rules: Sequence[Tuple[str, "re.Pattern[str]"]]) -> List[Tuple[str, int]]:
    """(rule, 1-based line) once for each rule that matches a line, in line order."""
    found: List[Tuple[str, int]] = []
    for number, line in enumerate(text.split("\n"), 1):
        seen = set()  # two patterns of one rule (`assignment`) can both fit a line: one finding
        for name, pattern in rules:
            if name not in seen and pattern.search(line):
                seen.add(name)
                found.append((name, number))
    return found


def credential_hits(data: bytes) -> List[Tuple[str, int]]:
    """(rule, line) for each credential shape in `data`; nothing for a binary file."""
    text = _text_of(data)
    return [] if text is None else _hits(text, CREDENTIAL_PATTERNS)


def _compile(rule: str, source: str, patterns: List[str]) -> Tuple[List[Tuple[str, "re.Pattern[str]"]], List[Finding]]:
    """The patterns as (rule, regex) pairs; each one that is not a regex becomes a BLOCK (the guard would
    otherwise run weaker than its owner believes). The pattern itself is never printed."""
    compiled: List[Tuple[str, "re.Pattern[str]"]] = []
    problems: List[Finding] = []
    for number, pattern in enumerate(patterns, 1):
        try:
            # `.brain-private` names things that must not appear in any case; a deny pattern is exactly as written.
            compiled.append((rule, re.compile(pattern, re.IGNORECASE if rule == "private-pattern" else 0)))
        except re.error:
            problems.append(Finding(BLOCK, rule, f"{source} entry {number} is not a valid regular expression"))
    return compiled, problems


class _Scan:
    """One run over the staged files of `root`."""

    def __init__(self, root: Path, cfg: Config) -> None:
        self.root = root
        self.cfg = cfg
        self.findings: List[Finding] = []
        self.deny, bad_deny = _compile("deny-pattern", "privacy.deny_patterns", cfg.deny_patterns)
        self.private, bad_private = _compile("private-pattern", config.PRIVATE_FILE, cfg.private_patterns)
        self.findings += bad_deny + bad_private
        self._repo_dirs: Dict[str, bool] = {}

    def _repo_above(self, path: str) -> Optional[str]:
        """The folder above `path` that holds a `.git` (so `path` belongs to another repository), if any."""
        prefix = ""
        for part in path.split("/")[:-1]:
            prefix = f"{prefix}/{part}" if prefix else part
            if prefix not in self._repo_dirs:
                self._repo_dirs[prefix] = os.path.lexists(os.path.join(str(self.root), *prefix.split("/"), ".git"))
            if self._repo_dirs[prefix]:
                return prefix
        return None

    def _block(self, rule: str, message: str) -> None:
        self.findings.append(Finding(BLOCK, rule, message))

    def _display(self, path: str) -> str:
        """`path` as it is printed. A private or deny match inside a name is replaced, so a finding about a
        file never repeats the very term that makes its name private."""
        masked = path
        for _rule, pattern in self.private + self.deny:
            masked = pattern.sub(lambda match: _MASK if match.group(0) else "", masked)
        return _shown(masked)

    def _name_findings(self, path: str, shown: str) -> None:
        """A private or deny term in a file name is committed with the name, whatever the file holds."""
        for rule, patterns in (("private-pattern", self.private), ("deny-pattern", self.deny)):
            if any(pattern.search(path) for _rule, pattern in patterns):
                self._block(rule, f"{shown} (in the file name)")

    def _too_big(self, path: str, size: int) -> bool:
        limit = self.cfg.max_file_kb * 1024
        return size > limit and not any(globs.match(pattern, path) for pattern in self.cfg.large_file_allow)

    def file(self, entry: gitutil.StagedEntry) -> None:
        path = entry.path
        shown = self._display(path)
        self._name_findings(path, shown)
        if entry.mode == gitutil.GITLINK_MODE:
            self._block("nested-repo", f"{shown} (a repository inside this one)")
            return
        above = self._repo_above(path)
        if above is not None:
            self._block("nested-repo", f"{shown} (inside the repository at {self._display(above)})")
        name = path.rsplit("/", 1)[-1]
        if (name == ".env" or name.startswith(".env.")) and name != _ENV_EXAMPLE:
            self._block("env-file", f"{shown} (secrets belong in an ignored .env, never in a commit)")
        if name in _PRIVATE_FILES:
            self._block("private-file", f"{shown} (this machine's private settings are never committed)")
        try:
            size = gitutil.staged_size(self.root, path)
            if self._too_big(path, size):
                self._block("large-file", f"{shown} ({size} bytes; the limit is {self.cfg.max_file_kb} KB)")
                return
            text = _text_of(gitutil.staged_blob(self.root, path))
        except gitutil.GitError as exc:  # cannot look, so cannot vouch
            self._block("git", f"cannot read the staged {shown}: {_first_line(exc.stderr)}")
            return
        if text is None:
            return
        rules = CREDENTIAL_PATTERNS + self.private
        if path != config.BRAIN_JSON:  # brain.json holds the deny list, which would match itself
            rules = rules + self.deny
        for rule, number in _hits(text, rules):
            self._block(rule, f"{shown}:{number}")


def _first_line(text: str) -> str:
    return (text.strip().splitlines() or ["no message"])[0]


# -- checks that read the working tree when certain staged paths change --------------------


def _touches_skills(path: str) -> bool:
    return path.startswith(_SKILLS_PREFIX) or path in _ROUTING_MAPS


def _touches_practices(path: str) -> bool:
    return path.startswith(_PRACTICES_PREFIX)


def _guarded(rule: str, check: Callable[[], List[Finding]]) -> List[Finding]:
    """Run `check`; one that crashes blocks (a guard that cannot look must not wave a commit through) and says
    only what kind of failure it was."""
    try:
        return check()
    except Exception as exc:  # noqa: BLE001 - any failure is reported, never swallowed
        why = type(exc).__name__ + (f" ({exc.strerror})" if isinstance(exc, OSError) and exc.strerror else "")
        return [Finding(BLOCK, rule, f"the check could not run: {why}")]


# The modules below are imported by the check that needs them, inside `_guarded`: a commit that touches no
# skills or practices must not depend on them loading, and one that does gets a finding, not a traceback.


def _lint_findings(root: Path, cfg: Config) -> List[Finding]:
    from . import lint

    # `all_findings` includes the routing map, the gate rules and every router's rules.json.
    return [Finding(BLOCK, "lint", f"{f.subject}: {f.message}")
            for f in lint.all_findings(root, cfg) if f.severity == BROKEN]


def _sync_findings(root: Path, cfg: Config) -> List[Finding]:
    from . import routing_sync

    problems: List[Finding] = []
    stale = routing_sync.sync(root, cfg, True, problems)  # a non-empty result: out of date or not confirmed current
    refused = set(routing_sync.refused_paths(problems))
    found = [Finding(BLOCK, "routing-sync", f"{f.subject}: {f.message}") for f in problems]
    found += [Finding(BLOCK, "routing-sync", f"{_shown(path)}: out of date; run _meta/brain routing sync and stage it")
              for path in stale if path not in refused]
    return found


def _practices_lint_findings(root: Path, cfg: Config, today: date) -> List[Finding]:
    from . import practices

    return [Finding(BLOCK, "practices-lint", f"{f.subject}: {f.message}")
            for f in practices.lint(root, cfg, today) if f.severity == BLOCK]


def _practices_index_findings(root: Path, cfg: Config, today: date) -> List[Finding]:
    """The index must be what `practices index` writes, and the staged copy is the one that counts: an
    index regenerated in the working tree but never staged is still not what would be committed."""
    from . import practices

    entries = practices.load_entries(root)
    try:
        staged = gitutil.staged_blob(root, _PRACTICES_INDEX).decode("utf-8", errors="replace")
        staged = staged.replace("\r\n", "\n").replace("\r", "\n")  # as `practices index --check` reads it
    except gitutil.GitError:
        staged = None
    if staged is None:
        if not entries:
            return []
        state = "has no staged copy"
    elif staged == practices.render_index(entries, cfg, today):
        return []
    else:
        state = "is out of date in the index"
    return [Finding(BLOCK, "practices-index",
                    f"{_PRACTICES_INDEX} {state}; run _meta/brain practices index, then stage it")]


def _staged_checks(root: Path, cfg: Config, changed: List[str]) -> List[Finding]:
    found: List[Finding] = []
    if any(_touches_skills(path) for path in changed):
        found += _guarded("lint", lambda: _lint_findings(root, cfg))
        found += _guarded("routing-sync", lambda: _sync_findings(root, cfg))
    if any(_touches_practices(path) for path in changed):
        today = date.today()
        found += _guarded("practices-lint", lambda: _practices_lint_findings(root, cfg, today))
        found += _guarded("practices-index", lambda: _practices_index_findings(root, cfg, today))
    return found


# -- the pre-commit guard -----------------------------------------------------------------


def _check(root: Path) -> Tuple[List[Finding], int]:
    """(the findings, how many staged files were looked at)."""
    try:
        cfg = config.load(root)
    except config.ConfigError as exc:
        return [Finding(BLOCK, "config", str(exc))], 0
    try:
        entries = gitutil.staged_entries(root)
    except gitutil.GitError as exc:
        return [Finding(BLOCK, "git", f"cannot read the staged files: {_first_line(exc.stderr)}")], 0
    scan = _Scan(root, cfg)
    present = [entry for entry in entries if entry.status != "D"]
    for entry in present:
        scan.file(entry)
    return scan.findings + _staged_checks(root, cfg, [entry.path for entry in entries]), len(present)


def pre_commit(root) -> List[Finding]:
    """BLOCK findings for everything staged in the repository at `root` that must not be committed (empty when
    the commit may go ahead)."""
    return _check(Path(root))[0]


# -- the installer ------------------------------------------------------------------------


def install(root) -> str:
    """Write the shim to `<git common dir>/hooks/pre-commit` (mode 0755) and return that path.

    The common dir is shared by every worktree of the repository. Only an exact copy of the shim is replaced.
    Any other hook (even one carrying the marker), or a `core.hooksPath` (git would then never look in the hooks
    folder), is a refusal.
    """
    root = Path(root)
    if not gitutil.is_repo(root):
        raise HookError(f"{root} is not a git repository; run git init first")
    configured = str(gitutil.git(root, "config", "--get", "core.hooksPath", check=False)).rstrip("\n")
    if configured:
        raise HookError(f"core.hooksPath is set ({configured}), so git ignores the repository's hooks folder; "
                        "unset it, or call `_meta/brain hook pre-commit` from the hook that path holds")
    common = str(gitutil.git(root, "rev-parse", "--git-common-dir")).rstrip("\n")
    target = (root / common).resolve() / "hooks" / "pre-commit"
    if os.path.lexists(str(target)):
        try:
            existing = target.read_bytes()
        except OSError as exc:
            raise HookError(f"cannot read the existing {target}: {exc.strerror or exc}")
        if existing != SHIM.encode("utf-8"):  # a changed copy, or any other hook that mentions the marker
            raise HookError(f"{target} is not the brain template's shim (an exact copy of it); move it aside and "
                            "run this again, or keep it and have it run `_meta/brain hook pre-commit` "
                            "(this command is then not needed)")
    staging = target.with_name("pre-commit.brain-new")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(str(staging), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(SHIM)
        os.chmod(str(staging), 0o755)
        os.replace(str(staging), str(target))
    except OSError as exc:
        try:
            os.unlink(str(staging))
        except OSError:
            pass
        raise HookError(f"cannot write {target}: {exc.strerror or exc}")
    return str(target)


# -- the self-test ------------------------------------------------------------------------

# Planted values are put together here, not written out, so this file never holds a credential shape.
_PLANTED = {
    "private-key": "-----BEGIN " + "RSA PRIVATE KEY" + "-----",
    "github-token": "gh" + "p_" + "a" * 36,
    "aws-key": "AK" + "IA" + "B" * 16,
    "slack-token": "xo" + "xb-" + "1234567890" + "abcdef",
    "anthropic-key": "sk-" + "ant-" + "c" * 24,
    "openai-key": "sk-" + "d" * 24,
    "assignment": "pass" + "word=" + '"' + "hunter2" + "hunter2" + '"',
}
_PLANTED_DOTENV = "API_" + "TOKEN=" + "abcdefgh" + "12345678"
_GIT_LOCATION_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX",
                      "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE")
_SELF_TEST_MAP = "```mermaid\nflowchart LR\nIN(a request):::entry --> lab-a:::work\n```\n"
_SELF_TEST_SKILL = ("---\nname: lab-a\ndescription: Does X. Use when Y.\n---\nDoes the thing.\n\n"
                    "**Call it directly when:** asked.\n\n## Done when\n\n- done\n")


class _Lab:
    """A throwaway repository the self-test plants one case in."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, rel: str, text: str) -> None:
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def stage(self, rel: str, text: str) -> None:
        self.write(rel, text)
        gitutil.git(self.root, "add", "-f", "--", rel)

    def brain_json(self, **privacy) -> None:
        raw = {"name": "self-test", "prefix": "lab", "description": "the hook self-test"}
        if privacy:
            raw["privacy"] = privacy
        self.write("brain.json", json.dumps(raw, indent=2) + "\n")

    def nested_repo(self, rel: str) -> None:
        inner = self.root / rel
        inner.mkdir(parents=True)
        gitutil.git(inner, "init", "-q")
        gitutil.git(inner, "-c", "user.name=self-test", "-c", "user.email=self-test@invalid",
                    "-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "--allow-empty", "-m", "self-test")
        gitutil.git(self.root, "add", "-f", "--", rel)


def _credential_case(rule: str) -> Callable[[_Lab], None]:
    return lambda lab: lab.stage("docs/note.md", f"a line\n{_PLANTED[rule]}\n")


def _dotenv_case(lab: _Lab) -> None:
    lab.stage("docs/note.md", f"a line\n{_PLANTED_DOTENV}\n")


def _deny_case(lab: _Lab) -> None:
    lab.brain_json(deny_patterns=["self-test-denied-term"])
    lab.stage("docs/note.md", "mentions self-test-denied-term here\n")


def _private_case(lab: _Lab) -> None:
    lab.write(config.PRIVATE_FILE, "\\bself-test-private-term\\b\n")
    lab.stage("docs/note.md", "mentions self-test-private-term here\n")


def _large_case(lab: _Lab) -> None:
    lab.brain_json(max_file_kb=1)
    lab.stage("docs/big.md", "x" * 2048)


def _skill_case(lab: _Lab) -> None:
    lab.stage(".claude/skills/lab-bad/SKILL.md", "---\nname: lab-bad\ndescription:\n---\nBody.\n")


def _routing_case(lab: _Lab) -> None:
    lab.stage("docs/ROUTING.md", _SELF_TEST_MAP)
    lab.stage(".claude/skills/lab-a/SKILL.md", _SELF_TEST_SKILL)  # no `Where this sits` block yet


def _practices_lint_case(lab: _Lab) -> None:
    lab.stage("docs/practices/bad.md", "no frontmatter\n")


def _practices_index_case(lab: _Lab) -> None:
    entry = ("---\nid: sample-fact\ntags: [demo]\ndurability: durable\nevidence: researched\n"
             f"verified: {date.today().isoformat()}\nsource: a note\nreviewed-against: []\n---\nA short fact.\n")
    lab.stage("docs/practices/sample-fact.md", entry)  # and no INDEX.md


def _cases() -> List[Tuple[str, Callable[[_Lab], None]]]:
    return [
        ("env-file", lambda lab: lab.stage("config/.env.local", "A=1\n")),
        ("private-file", lambda lab: lab.stage("brain.local.json", "{}\n")),
        *((rule, _credential_case(rule)) for rule in _PLANTED),
        ("assignment", _dotenv_case),
        ("deny-pattern", _deny_case),
        ("private-pattern", _private_case),
        ("large-file", _large_case),
        ("nested-repo", lambda lab: lab.nested_repo("docs/inner")),
        ("lint", _skill_case),
        ("routing-sync", _routing_case),
        ("practices-lint", _practices_lint_case),
        ("practices-index", _practices_index_case),
    ]


def _seed(repo: Path) -> _Lab:
    repo.mkdir(parents=True)
    shutil.copytree(str(paths.harness_root() / "_meta"), str(repo / "_meta"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    gitutil.git(repo, "init", "-q")
    lab = _Lab(repo)
    lab.brain_json()
    return lab


def self_test() -> List[str]:
    """Plant one case per rule in a temporary repository and return a line for each that was not blocked.

    A clean commit is tried as well, so a guard that blocks everything cannot pass. Empty means every rule held.
    """
    failures: List[str] = []
    cases = _cases()
    if list(dict.fromkeys(name for name, _build in cases)) != list(RULES):
        failures.append("the self-test cases do not match hook.RULES")
    saved = {name: os.environ.pop(name) for name in _GIT_LOCATION_VARS if name in os.environ}
    base: Optional[Path] = None
    try:
        base = Path(tempfile.mkdtemp(prefix="brain-hook-self-test-")).resolve()
        for index, (rule, build) in enumerate([("control", None), *cases]):
            try:
                lab = _seed(base / f"case {index} {rule}")  # the space is deliberate
                if build is None:
                    lab.stage("docs/note.md", "Plain notes, nothing private.\n")
                else:
                    build(lab)
                blocking = [f for f in pre_commit(lab.root) if f.severity == BLOCK]
            except (gitutil.GitError, OSError) as exc:
                failures.append(f"{rule}: the case could not be set up ({exc})")
                continue
            if build is None and blocking:
                failures.append("control: a clean commit was blocked")
            elif build is not None and not any(f.subject == rule for f in blocking):
                failures.append(f"{rule}: not blocked")
    finally:
        os.environ.update(saved)
        if base is not None:
            shutil.rmtree(str(base), ignore_errors=True)
    return failures


# -- the command ---------------------------------------------------------------------------


def add_arguments(parser) -> None:
    sub = parser.add_subparsers(dest="hook_command", metavar="<subcommand>", required=True)
    sub.add_parser("pre-commit", help="check the staged files (what the git hook runs)",
                   description="Block a commit that would carry a secret, a private term, a stray .env, a "
                               "large file or a nested repo, or break the skills, routing map or practices.")
    sub.add_parser("install", help="install the pre-commit shim in this repository's git directory",
                   description="Write the shim to the common git directory (shared by worktrees). Refuses to "
                               "replace a hook that is not its own, or when core.hooksPath is set.")
    sub.add_parser("self-test", help="plant one case per rule in a temporary repository and prove each blocks")


def _run_pre_commit(root: Path) -> int:
    findings, checked = _check(root)
    if findings:
        emit(findings)
        print(f"hook pre-commit: {len(findings)} finding(s) block this commit", file=sys.stderr)
    else:
        emit([Finding(OK, "pre-commit", f"{checked} staged file(s) checked")])
    return exit_code(findings)


def run(args) -> int:
    root = paths.harness_root()
    name = args.hook_command
    if name == "pre-commit":
        return _run_pre_commit(root)
    if name == "install":
        try:
            installed = install(root)
        except HookError as exc:
            print(f"hook install: {exc}", file=sys.stderr)
            return 1
        print(f"installed: {installed}")
        return 0
    failures = self_test()
    for failure in failures:
        print(f"self-test: FAIL {failure}", file=sys.stderr)
    if failures:
        return 1
    print(f"self-test: {len(RULES)} rules, all blocked")
    return 0
