"""`brain doctor [--quick]`: the read-only health check of a brain (spec §7.1).

Every line is `ok`, `WARN` or `BLOCK`; the exit status is 1 when anything blocks. The command changes nothing:
it never rewrites `_meta/MANIFEST.sha256` (the pre-commit guard trusts that file to tell a template file from an
edit), runs git only through `gitutil` (which passes `--no-optional-locks`, so even `git status` leaves the index
alone), and asks a nested repository only for its remotes and unpushed commits, never its status.

`--quick` leaves out what is slow or leaves the machine: the scripts' tests, the walk for nested repositories
and the `ls-remote` that asks a URL source for its latest commit. Findings name files, keys and rules; they never
carry a value from `.env`, a test's output or a URL's credentials.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import stat
import subprocess
from datetime import date
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from . import config, envsync, gitutil, globs, hook, lint, manifest, paths, practices
from .config import Config
from .report import BLOCK, BROKEN, GAP, OK, WARN, Finding, emit, exit_code
from .skills import skills_dir

LS_REMOTE_TIMEOUT = 10  # seconds a URL source gets to answer
SCRIPT_TESTS_TIMEOUT = 300  # seconds the brain's own tests get to finish
NO_TESTS_EXIT = 5  # what `unittest discover` exits with, on Python 3.12 and later, when it finds no tests
LISTED = 8  # names shown in one line before "and N more"
GUARD_CALL = re.compile(r"_meta/brain[\"']?\s+hook\s+pre-commit")
_URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_SCP = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._-]*@[A-Za-z0-9._-]+:")
_USERINFO = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*://)[^/\s]*@")  # to the last `@`: a password may hold one


# -- small helpers --------------------------------------------------------------------------------------


def _ok(subject: str, message: str) -> Finding:
    return Finding(OK, subject, message)


def _warn(subject: str, message: str) -> Finding:
    return Finding(WARN, subject, message)


def _block(subject: str, message: str) -> Finding:
    return Finding(BLOCK, subject, message)


def _plural(count: int, noun: str, many: Optional[str] = None) -> str:
    return f"{count} {noun if count == 1 else (many or noun + 's')}"


def _names(names: List[str], limit: int = LISTED) -> str:
    shown = ", ".join(names[:limit])
    return shown + (f" and {len(names) - limit} more" if len(names) > limit else "")


def _python_command(root: Path, cfg: Optional[Config]) -> str:
    """`scripts.python` as something to run: a relative path (`.venv/bin/python`) is the brain's own."""
    python = cfg.python if cfg is not None else "python3"
    if "/" in python or os.sep in python:
        return python if os.path.isabs(python) else str(root / python)
    return python


def _guarded(subject: str, check: Callable[[], List[Finding]]) -> List[Finding]:
    """Run `check`; one that crashes blocks (a health check that cannot look must not say all is well) and says
    only what kind of failure it was."""
    try:
        return check()
    except gitutil.GitError as exc:
        reason = (exc.stderr.strip().splitlines() or ["git failed"])[0]
        return [_block(subject, f"the check could not run: {reason}")]
    except Exception as exc:  # noqa: BLE001 - any failure is reported, never swallowed
        why = type(exc).__name__ + (f" ({exc.strerror})" if isinstance(exc, OSError) and exc.strerror else "")
        return [_block(subject, f"the check could not run: {why}")]


# -- the tools, brain.json, and what kind of folder this is -------------------------------------------------


def _tools(root: Path, cfg: Optional[Config]) -> List[Finding]:
    python = _python_command(root, cfg)
    wanted = [("git", "git"), ("python3", "python3")]
    if python != "python3":
        wanted.append((f"scripts.python '{cfg.python if cfg is not None else python}'", python))
    found: List[Finding] = []
    for label, command in wanted:
        if shutil.which(command) is None:
            hint = "fix scripts.python in brain.json or install it" if label.startswith("scripts.python") \
                else "install it"
            found.append(_block("tools", f"{label} not found; {hint}"))
    if found:
        return found
    return [_ok("tools", ", ".join(label for label, _ in wanted) + " found")]


def _config_findings(cfg: Config) -> List[Finding]:
    if cfg.role == "template":
        return [_ok("brain.json", "valid (role template)")]
    if not cfg.prefix:
        return [_block("brain.json", "prefix is not set: it names this brain's own skills (<prefix>-*)")]
    problem = config.validate_prefix(cfg.prefix)
    if problem:
        return [_block("brain.json", problem)]
    return [_ok("brain.json", f"valid, prefix {cfg.prefix}")]


def _template_files(root: Path, cfg: Config) -> List[Finding]:
    """The template itself is fine (with `local/`); a brain must hold nothing that only the template owns."""
    if cfg.role == "template":
        if (root / "local").is_dir():
            return [_ok("template", "this is the template")]
        return [_block("template", "this is a copy of the template that was never set up: run brain-setup "
                                   "(create local/ if you develop the template here)")]
    strays: List[str] = []
    base = skills_dir(root)
    try:
        strays += [f".claude/skills/{p.name}" for p in sorted(base.glob("template-*")) if p.is_dir()]
    except OSError:
        pass
    if (root / "tests" / ".brain-template").exists():
        strays.append("tests/.brain-template")
    if strays:
        return [_block("template files", f"{_names(strays)} belong to the template only, so this brain is a copy "
                                         "that was never fully set up: run brain-setup")]
    return [_ok("template files", "none of the template's own files here")]


def _manifest(root: Path, cfg: Config) -> List[Finding]:
    if cfg.role == "template":
        return []  # the template has no manifest: it is what the manifests are made from
    if not (root / manifest.MANIFEST_PATH).is_file():
        return [_warn("manifest", f"{manifest.MANIFEST_PATH} is missing, so edits to template files cannot be "
                                  "told apart; run update")]
    edits = manifest.local_edits(root)
    if not edits:
        return [_ok("manifest", "template-owned files match the manifest")]
    return [_warn("manifest", f"{_plural(len(edits), 'template-owned file')} differ from the manifest: "
                              f"{_names(edits)}; a change the template should have goes to brain-upstream, "
                              "which also restores the file")]


# -- the template this brain came from ------------------------------------------------------------------------


def _is_url(source: str) -> bool:
    return not source.startswith("-") and bool(_URL.match(source) or _SCP.match(source))


def _shown(source: str) -> str:
    """The source without credentials: `https://token@host/x` shows as `https://host/x`."""
    return _USERINFO.sub(r"\1", source)


@contextlib.contextmanager
def _never_prompt(root: Path) -> Iterator[None]:
    """For the length of one network call: git and ssh fail instead of asking a question nobody will answer
    (a password, or whether to trust a host). The person's own ssh command, if they set one, is kept."""
    changes = {"GIT_TERMINAL_PROMPT": "0"}
    if "GIT_SSH_COMMAND" not in os.environ and "GIT_SSH" not in os.environ:
        ssh = str(gitutil.git(root, "config", "--get", "core.sshCommand", check=False)).strip() or "ssh"
        changes["GIT_SSH_COMMAND"] = ssh + " -o BatchMode=yes"
    before: Dict[str, Optional[str]] = {key: os.environ.get(key) for key in changes}
    os.environ.update(changes)
    try:
        yield
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _moved_on(recorded: str, shown: str, latest: str, way: str) -> Finding:
    """`way` is "behind", "ahead of" or "differs from": only a brain behind its source is told to update."""
    advice = "; run update (brain-setup walks through it)" if way == "behind" else ""
    return _warn("source", f"this brain {'is ' if way != 'differs from' else ''}{way} {shown}: it was set up from "
                           f"{recorded}, and {shown} is at {latest}{advice}")


def _is_ancestor(repo: Path, older: str, newer: str) -> bool:
    """Whether commit `older` is `newer` or one of its ancestors in `repo`; False when either is unknown there."""
    if not re.fullmatch(r"[0-9a-f]{4,64}", older) or not re.fullmatch(r"[0-9a-f]{4,64}", newer):
        return False
    try:
        gitutil.git(repo, "merge-base", "--is-ancestor", older, newer)
    except gitutil.GitError:
        return False
    return True


def _path_source(path: Path, recorded: str, shown: str) -> Finding:
    if not gitutil.is_repo(path):
        return _ok("source", f"skipped: {shown} is not a template checkout on this machine")
    branch = gitutil.default_branch(path)
    head = gitutil.short_sha(path, branch)
    if not head:
        return _ok("source", f"skipped: {shown} has no commits to compare with")
    version, _plus, sha = recorded.partition("+")
    latest = str(gitutil.git(path, "show", f"{branch}:_meta/VERSION", check=False)).strip()
    if sha:
        same = head.startswith(sha) or sha.startswith(head)
    else:  # recorded from a template that was not a repository: only the version number can be compared
        same = not latest or latest == version
    if same:
        return _ok("source", f"up to date with {shown} ({branch} at {head})")
    way = ("behind" if _is_ancestor(path, sha, head) else "ahead of" if _is_ancestor(path, head, sha)
           else "differs from")
    return _moved_on(recorded, shown, f"{latest}+{head}" if latest else head, way)


def _url_source(root: Path, source: str, recorded: str, shown: str) -> Finding:
    sha = recorded.partition("+")[2]
    if not sha:
        return _ok("source", f"skipped: {recorded} has no commit id to compare with {shown}")
    try:
        with _never_prompt(root):
            answer = str(gitutil.git(root, "ls-remote", "--", source, "HEAD", timeout=LS_REMOTE_TIMEOUT))
    except gitutil.GitError:  # offline, unknown host, refused or too slow: not a problem with this brain
        return _ok("source", f"skipped: {shown} is not reachable")
    fields = answer.split()
    head = fields[0] if fields and re.fullmatch(r"[0-9a-f]{7,64}", fields[0]) else ""
    if not head:
        return _ok("source", f"skipped: {shown} did not name a latest commit")
    if head.startswith(sha) or sha.startswith(head):
        return _ok("source", f"up to date with {shown} (at {head[:max(7, len(sha))]})")
    # the source's history is not on this machine, so which of the two is newer cannot be told
    return _moved_on(recorded, shown, head[:max(7, len(sha))], "differs from")


def _source(root: Path, cfg: Config, quick: bool) -> List[Finding]:
    if cfg.role == "template":
        if cfg.template_source is None and gitutil.is_repo(root) and str(gitutil.git(root, "remote")).strip():
            return [_warn("source", "this template has a remote but brain.json template.source is null; set it to "
                                    "the published URL before publishing, so init in a clone starts a fresh history")]
        return []
    try:
        source = config.effective_source(cfg)
    except config.ConfigError:
        return [_ok("source", f"skipped: {config.LOCAL_JSON} cannot be read")]
    if not source:
        return [_ok("source", "skipped: no template source is recorded")]
    if not cfg.template_version:
        return [_ok("source", "skipped: no template version is recorded in brain.json")]
    shown = _shown(source)
    if _is_url(source):
        if quick:
            return [_ok("source", f"skipped (--quick): {shown} would be asked over the network")]
        return [_url_source(root, source, cfg.template_version, shown)]
    return [_path_source(Path(os.path.expanduser(source)), cfg.template_version, shown)]


# -- git hook and Claude settings -------------------------------------------------------------------------------


def _hook(root: Path, cfg: Config) -> List[Finding]:
    if not gitutil.is_repo(root):
        return [_block("hook", "not a git repository, so the pre-commit guard cannot be installed: run git init, "
                               "then _meta/brain hook install")]
    configured = str(gitutil.git(root, "config", "--get", "core.hooksPath", check=False)).strip()
    if configured:
        return [_block("hook", f"core.hooksPath is set ({configured}), so git never runs the guard in "
                               ".git/hooks: unset it (git config --unset core.hooksPath), then run "
                               "_meta/brain hook install")]
    common = str(gitutil.git(root, "rev-parse", "--git-common-dir")).rstrip("\n")
    target = (root / common).resolve() / "hooks" / "pre-commit"
    if not os.path.lexists(str(target)):
        return [_block("hook", "no pre-commit hook: run _meta/brain hook install")]
    data = target.read_bytes()
    text = data.decode("utf-8", errors="replace")
    ours = data == hook.SHIM.encode("utf-8")
    calls = any(GUARD_CALL.search(line) for line in text.splitlines() if not line.lstrip().startswith("#"))
    if not ours and not calls:
        return [_block("hook", "the pre-commit hook does not run the guard: have it call "
                               "`_meta/brain hook pre-commit`, or move it aside and run _meta/brain hook install")]
    if not os.access(str(target), os.X_OK):
        return [_block("hook", "the pre-commit hook is not executable, so git ignores it: chmod +x it")]
    return [_ok("hook", "pre-commit guard installed" if ours else "pre-commit hook calls the guard")]


def _wires(settings: dict, event: str, verb: str) -> bool:
    hooks = settings.get("hooks")
    groups = hooks.get(event) if isinstance(hooks, dict) else None
    for group in groups if isinstance(groups, list) else []:
        inner = group.get("hooks") if isinstance(group, dict) else None
        for entry in inner if isinstance(inner, list) else []:
            command = entry.get("command") if isinstance(entry, dict) else None
            if isinstance(command, str) and re.search(r"_meta/brain[\"']?\s+gate\s+" + verb + r"\b", command):
                return True
    return False


def _settings(root: Path, cfg: Config) -> List[Finding]:
    path = root / ".claude" / "settings.json"
    if not path.is_file():
        return [_warn("settings", ".claude/settings.json is missing: .env can be read and the skill gate is off, "
                                  "so skills can be imitated from memory; run brain-setup")]
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, ValueError):
        return [_warn("settings", ".claude/settings.json is not valid JSON, so neither the .env deny entries nor "
                                  "the skill gate are in force; fix it, then run brain-setup")]
    if not isinstance(settings, dict):
        return [_warn("settings", ".claude/settings.json is not a JSON object; fix it, then run brain-setup")]
    found: List[Finding] = []
    permissions = settings.get("permissions")
    deny = permissions.get("deny") if isinstance(permissions, dict) else None
    lost = [entry for entry in ("Read(./.env)", "Read(./.env.*)") if not isinstance(deny, list) or entry not in deny]
    if lost:
        found.append(_warn("settings", f"does not deny {_names(lost)}, so .env can be read; run brain-setup"))
    for event, verb in (("PreToolUse", "check"), ("PostToolUse", "record")):
        if not _wires(settings, event, verb):
            found.append(_warn("settings", f"{event} does not run `_meta/brain gate {verb}`, so skills can be "
                                           "imitated from memory; run brain-setup"))
    return found or [_ok("settings", "denies reading .env and wires both gate hooks")]


# -- lint, practices ------------------------------------------------------------------------------------------------


def _lint(root: Path, cfg: Config) -> List[Finding]:
    """BROKEN blocks and GAP warns with a count. The routing map, the gate rules and every router's
    `rules.json` are part of `lint`'s run, so they are checked here."""
    everything = lint.all_findings(root, cfg)
    found = [_block("lint", f"{f.subject}: {f.message}") for f in everything if f.severity == BROKEN]
    gaps = sum(1 for f in everything if f.severity == GAP)
    if gaps:
        found.append(_warn("lint", f"{_plural(gaps, 'gap')}: conventions not yet followed; "
                                   "run _meta/brain lint to list them"))
    return found or [_ok("lint", "no broken skill, routing map, router rules or gate rules")]


def _practices(root: Path, cfg: Config) -> List[Finding]:
    found = [f for f in practices.lint(root, cfg, date.today()) if f.severity in (BLOCK, WARN)]
    if found:
        return found
    count = len(practices.load_entries(root))
    return [_ok("practices", f"{_plural(count, 'entry', 'entries')}, valid and current" if count
                else "no entries yet")]


# -- .env ---------------------------------------------------------------------------------------------------------------


def _env(root: Path, cfg: Config) -> List[Finding]:
    found: List[Finding] = []
    env = root / envsync.ENV
    if env.exists():
        mode = stat.S_IMODE(os.stat(str(env)).st_mode)
        if mode != 0o600:
            found.append(_warn(".env", f"mode is {mode:o}, not 600: run chmod 600 .env"))
    try:
        missing = [name for name, state in envsync.statuses(root) if state == "missing"]
    except OSError as exc:
        return found + [_warn(".env", f"cannot be read ({exc.strerror or exc})")]
    if missing:
        found.append(_warn(".env", f"lacks {_plural(len(missing), 'key')} that .env.example lists: "
                                   f"{_names(missing)}; run _meta/brain env-sync"))
    if found:
        return found
    return [_ok(".env", "mode 600, every key of .env.example is present" if env.exists()
                else "none, and .env.example lists no keys")]


# -- the scripts' own tests -----------------------------------------------------------------------------------------


def _failed_tests(output: str) -> List[str]:
    names: List[str] = []
    for short, dotted in re.findall(r"^(?:FAIL|ERROR): (\S+)(?: \(([\w.]+)\))?", output, re.MULTILINE):
        name = dotted or short
        if name not in names:
            names.append(name)
    return names


def _script_tests(root: Path, cfg: Config, quick: bool) -> List[Finding]:
    if quick:
        return [_ok("script tests", "skipped (--quick)")]
    if not (root / "scripts" / "tests").is_dir():
        return [_ok("script tests", "no script tests yet")]
    python = _python_command(root, cfg)
    if shutil.which(python) is None:
        return []  # `tools` already blocked on it
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")  # running tests must not leave __pycache__ in the brain
    command = [python, "-m", "unittest", "discover", "-s", "scripts/tests", "-t", "scripts"]
    try:
        done = subprocess.run(command, cwd=str(root), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=SCRIPT_TESTS_TIMEOUT)
    except subprocess.TimeoutExpired:
        return [_block("script tests", f"did not finish within {SCRIPT_TESTS_TIMEOUT} seconds")]
    output = done.stdout.decode("utf-8", errors="replace")
    ran = re.search(r"^Ran (\d+) tests?\b", output, re.MULTILINE)
    count = int(ran.group(1)) if ran else 0
    if done.returncode == NO_TESTS_EXIT or (done.returncode == 0 and count == 0):
        return [_ok("script tests", "no script tests yet")]  # Python 3.12+ exits 5 for none; older ones exit 0
    if done.returncode == 0:
        return [_ok("script tests", f"{count} test passes" if count == 1 else f"{count} tests pass")]
    failed = _failed_tests(output)  # names only: a test's output could hold anything
    named = f": {_names(failed, 3)}" if failed else ""
    return [_block("script tests", f"failed (exit {done.returncode}){named}; run `{cfg.python} -m unittest "
                                   "discover -s scripts/tests -t scripts` to see why")]


# -- git: this repository, the nested ones, and what is tracked ---------------------------------------------------


def _brain_repo(root: Path, cfg: Config) -> List[Finding]:
    if not gitutil.is_repo(root):
        return []  # `hook` already blocked on it
    state = gitutil.repo_state(root)
    found: List[Finding] = []
    if not state.has_remote:
        found.append(_warn("git", "no remote: nothing here is backed up; add one with `git remote add origin <url>` "
                                  "and push"))
    elif state.unpushed:
        found.append(_warn("git", f"{_plural(state.unpushed, 'commit')} not pushed; brain-sync pushes when you ask"))
    changed = [line for line in str(gitutil.git(root, "status", "--porcelain")).splitlines() if line.strip()]
    if changed:
        found.append(_warn("git", f"{_plural(len(changed), 'uncommitted change')}; brain-sync commits them"))
    return found or [_ok("git", "has a remote, and nothing is uncommitted or unpushed")]


def _nested(root: Path, cfg: Config, quick: bool) -> List[Finding]:
    if quick:
        return [_ok("nested repos", "skipped (--quick)")]
    repos = gitutil.nested_repos(root)
    found: List[Finding] = []
    for repo in repos:
        shown = repo.relative_to(root).as_posix()
        state = gitutil.repo_state(repo)  # never `git status` here: that would refresh the repo's index
        if not state.has_remote:
            found.append(_warn(shown, "no remote: its work exists only on this disk"))
        elif state.unpushed:
            found.append(_warn(shown, f"{_plural(state.unpushed, 'commit')} not pushed"))
    if found:
        return found
    return [_ok("nested repos", f"{len(repos)} found, each with a remote and nothing unpushed" if repos
                else "none")]


def _docs(root: Path, cfg: Config) -> List[Finding]:
    docs = root / "docs"
    try:
        folders = sorted(p.name for p in docs.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return [_ok("docs", "no docs folder")]
    if not folders:
        return [_ok("docs", "no subfolders to index")]
    try:
        index = (docs / "README.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [_warn("docs", f"docs/README.md is missing; it should name {_names([f + '/' for f in folders])}")]
    lost = [f for f in folders if not re.search(rf"(?<![\w-]){re.escape(f)}(?![\w-])", index)]
    if lost:
        return [_warn("docs", f"docs/README.md does not mention {_names([f + '/' for f in lost])}; add a line for "
                              "each")]
    return [_ok("docs", "docs/README.md mentions every subfolder")]


def _large_files(root: Path, cfg: Config) -> List[Finding]:
    if not gitutil.is_repo(root):
        return []
    limit = cfg.max_file_kb * 1024
    listed = gitutil.git(root, "ls-files", "-z", binary=True)
    over: List[Tuple[str, int]] = []
    for raw in listed.split(b"\0"):  # type: ignore[union-attr]
        if not raw:
            continue
        rel = raw.decode("utf-8", errors="surrogateescape")
        try:
            info = os.lstat(str(root / rel))
        except OSError:
            continue  # tracked but gone from the working tree
        if stat.S_ISREG(info.st_mode) and info.st_size > limit \
                and not any(globs.match(pattern, rel) for pattern in cfg.large_file_allow):
            over.append((rel, info.st_size))
    if not over:
        return [_ok("files", f"no tracked file over {cfg.max_file_kb} KB")]
    found = [_warn("files", f"{rel} is {size // 1024} KB, over max_file_kb ({cfg.max_file_kb}); list it in "
                            "privacy.large_file_allow or take it out of git") for rel, size in over[:LISTED]]
    if len(over) > LISTED:
        found.append(_warn("files", f"and {len(over) - LISTED} more over max_file_kb"))
    return found


def _privacy(root: Path, cfg: Config) -> List[Finding]:
    if cfg.private_file_expected and not (root / config.PRIVATE_FILE).is_file():
        return [_warn("privacy", f"{config.PRIVATE_FILE} is missing on this machine although this brain expects "
                                 "one (privacy.private_file_expected), so the pre-commit guard is weaker here: "
                                 "restore the file")]
    return [_ok("privacy", f"{config.PRIVATE_FILE} present" if cfg.private_file_expected
                else f"no {config.PRIVATE_FILE} expected")]


# -- the checks, in the order they print ------------------------------------------------------------------------------


def checks(root, cfg: Config, quick: bool) -> List[Finding]:
    """Every finding for the brain at `root` (`cfg` is its loaded brain.json). Reads only; `quick` leaves out the
    scripts' tests, the nested repositories and the network."""
    root = Path(root)
    steps: List[Tuple[str, Callable[[], List[Finding]]]] = [
        ("tools", lambda: _tools(root, cfg)),
        ("brain.json", lambda: _config_findings(cfg)),
        ("template", lambda: _template_files(root, cfg)),
        ("manifest", lambda: _manifest(root, cfg)),
        ("source", lambda: _source(root, cfg, quick)),
        ("hook", lambda: _hook(root, cfg)),
        ("settings", lambda: _settings(root, cfg)),
        ("lint", lambda: _lint(root, cfg)),
        ("practices", lambda: _practices(root, cfg)),
        (".env", lambda: _env(root, cfg)),
        ("script tests", lambda: _script_tests(root, cfg, quick)),
        ("git", lambda: _brain_repo(root, cfg)),
        ("nested repos", lambda: _nested(root, cfg, quick)),
        ("docs", lambda: _docs(root, cfg)),
        ("files", lambda: _large_files(root, cfg)),
        ("privacy", lambda: _privacy(root, cfg)),
    ]
    found: List[Finding] = []
    for subject, step in steps:
        found += _guarded(subject, step)
    return found


def diagnose(root, quick: bool = False) -> List[Finding]:
    """`checks` for the brain at `root`, loading its brain.json first: one that cannot be loaded blocks, and only
    the tools are checked then (nothing else can be judged without it)."""
    root = Path(root)
    try:
        cfg = config.load(root)
    except config.ConfigError as exc:
        return _guarded("tools", lambda: _tools(root, None)) + [_block("brain.json", str(exc))]
    return checks(root, cfg, quick)


def summary(findings: List[Finding]) -> str:
    blocks = sum(1 for f in findings if f.severity == BLOCK)
    warns = sum(1 for f in findings if f.severity == WARN)
    return f"doctor: {blocks} block, {warns} warn"


# -- the command ------------------------------------------------------------------------------------------------------------

# Variables that point git at one particular repository. Set (a git hook exports them), they would make every
# question about a nested repository answer for this one instead.
_GIT_LOCATION_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX",
                      "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE")


def add_arguments(parser) -> None:
    parser.add_argument("--quick", action="store_true",
                        help="skip the scripts' tests, the nested repositories and the network (for before a commit)")


def run(args) -> int:
    for name in _GIT_LOCATION_VARS:
        os.environ.pop(name, None)
    found = diagnose(paths.harness_root(), args.quick)
    emit(found)
    print(summary(found))
    return exit_code(found, failing=(BLOCK,))
