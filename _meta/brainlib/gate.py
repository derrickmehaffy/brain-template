"""The skill gate (spec §7.9): hook commands that refuse a write until the skill that owns it has run.

`gate record` (PostToolUse on `Skill`) notes the skill against the session id in the OS temp
directory; `gate check` (PreToolUse on `Write`, `Edit` and `Bash`) refuses a write to a ruled path
unless an owning skill ran this session or the person armed a one-shot waiver. It is friction and
visibility, not a security boundary, and it never says "allow": the person's own permission prompt
stays in charge. If the gate itself errors it lets the write through with a visible warning.

Runs on every tool call, so imports stay lazy: a call that names no path inside the brain returns
before the config, the rules or any of the heavier modules are loaded.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, NamedTuple, Optional, Tuple

from . import globs, paths

if TYPE_CHECKING:  # annotations only; importing these at run time would slow every tool call
    from .config import Config
    from .report import Finding
    from .skills import Skill

GATES_FILE = "gates.json"  # under _meta/
WAIVER_FILE = Path(".brain") / "gate-waiver.json"
WAIVER_LOG = Path(".brain") / "gate-waivers.log"
NO_SESSION = "nosession"
# Written by `gate waive` and the gate itself only: no tool call may touch them, whatever has run.
RESERVED = (WAIVER_FILE.as_posix(), WAIVER_LOG.as_posix())


class Rule(NamedTuple):
    path: str
    skills: List[str]
    spend_on_revision: bool = False
    why: str = ""
    shipped: bool = False


# -- rules ---------------------------------------------------------------------------------------


def _parse_rule(entry: Dict[str, Any], shipped: bool) -> Tuple[Optional[Rule], str]:
    """(rule, "") for a well-formed entry, else (None, what is wrong with it)."""
    path = entry.get("path")
    if not isinstance(path, str) or not path.strip():
        return None, "has no 'path'"
    skills = entry.get("skills")
    if not isinstance(skills, list) or not skills or not all(isinstance(s, str) and s for s in skills):
        return None, "needs 'skills': a non-empty list of skill names"
    spend = entry.get("spend_on_revision", False)
    if not isinstance(spend, bool):
        return None, "has 'spend_on_revision' that is not true or false"
    why = entry.get("why", "")
    if not isinstance(why, str):
        return None, "has a 'why' that is not text"
    return Rule(path, list(skills), spend, why, shipped), ""


def _read_shipped(root: Path) -> Tuple[List[Any], List[Any], str]:
    """The shipped file's (rules, exempt, problem). A file that is not there is no rules and no problem."""
    path = Path(root) / "_meta" / GATES_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], [], ""
    except (OSError, UnicodeDecodeError) as exc:
        return [], [], f"cannot read {path.name}: {exc}"
    try:
        data = json.loads(text)
    except ValueError as exc:
        return [], [], f"{path.name} is not valid JSON: {exc}"
    rules = data.get("rules", []) if isinstance(data, dict) else None
    exempt = data.get("exempt", []) if isinstance(data, dict) else None
    if not isinstance(rules, list) or not isinstance(exempt, list) or not all(isinstance(g, str) for g in exempt):
        return [], [], f"{path.name} must hold 'rules' (a list of objects) and 'exempt' (a list of globs)"
    return rules, exempt, ""


def _load(root: Path, cfg: "Config") -> Tuple[List[Rule], List[str], str, List[str]]:
    """(rules, exempt globs, shipped-file problem, problems with the brain's own entries). Never raises."""
    shipped_entries, shipped_exempt, file_problem = _read_shipped(root)
    off = set()
    for entry in cfg.gates_off:
        if isinstance(entry.get("path"), str):
            off.add(entry["path"])
    rules: List[Rule] = []
    for entry in shipped_entries:
        if not isinstance(entry, dict):
            continue
        rule, _problem = _parse_rule(entry, True)
        if rule is None:
            continue
        only_in = entry.get("only_in")
        if only_in is not None and only_in != cfg.role:
            continue
        expanded = rule.path
        if "{prefix}" in rule.path:
            if not cfg.prefix:
                continue  # a brain without a prefix has no skills of its own to guard
            expanded = rule.path.replace("{prefix}", cfg.prefix)
        if rule.path in off or expanded in off:
            continue
        rules.append(rule._replace(path=expanded))
    problems: List[str] = []
    for number, entry in enumerate(cfg.gates, 1):
        rule, problem = _parse_rule(entry, False)
        if rule is None:
            problems.append(f"entry {number} {problem}")
        else:
            rules.append(rule)
    return rules, list(shipped_exempt) + list(cfg.gate_exempt), file_problem, problems


def load_rules(root: Path, cfg: "Config") -> Tuple[List[Rule], List[str]]:
    """(rules, exempt globs): the shipped rules for this role, minus `gates_off`, then the brain's own.

    A malformed entry in `brain.json` is skipped (`lint` reports it); an unreadable shipped file raises
    ValueError, so `check` warns on every call instead of quietly guarding nothing.
    """
    rules, exempt, file_problem, _problems = _load(root, cfg)
    if file_problem:
        raise ValueError(file_problem)
    return rules, exempt


def lint_rules(root: Path, cfg: "Config", skills: "List[Skill]") -> "List[Finding]":
    """BROKEN findings for the brain's own gate setup: a rule naming a skill that does not exist, a
    `gates_off` entry without a `why`, a malformed entry, an unreadable shipped file.

    The skills the *shipped* rules name are not checked here: they are the `brain-*` skills every
    brain holds, and a template-level test covers them.
    """
    from .report import BROKEN, Finding

    rules, _exempt, file_problem, problems = _load(root, cfg)
    found: List[Finding] = []
    if file_problem:
        found.append(Finding(BROKEN, f"_meta/{GATES_FILE}", file_problem))
    found += [Finding(BROKEN, "gates", problem) for problem in problems]
    known = {skill.name for skill in skills}
    for rule in rules:
        if rule.shipped:
            continue
        for name in rule.skills:
            if name not in known:
                found.append(Finding(BROKEN, "gates", f"rule for {rule.path} names {name}, which does not exist"))
    for number, entry in enumerate(cfg.gates_off, 1):
        path = entry.get("path")
        if not isinstance(path, str) or not path.strip():
            found.append(Finding(BROKEN, "gates_off", f"entry {number} has no 'path'"))
            continue
        why = entry.get("why")
        if not isinstance(why, str) or not why.strip():
            found.append(Finding(BROKEN, "gates_off", f"entry for {path} has no 'why'"))
    return found


# -- what a tool call writes ---------------------------------------------------------------------

_WRAPPERS = {"sudo", "env", "command", "nohup", "time", "exec"}
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


# `<<EOF`, `<<-EOF`, `<<'EOF'`: not `<<<` (a here-string), whose word is an argument, not a delimiter.
_HEREDOC = re.compile(r"(?<!<)<<(-?)[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")


def _without_heredoc_bodies(command: str) -> str:
    """`command` minus the text of its here-documents, which is data, not commands. A body is only
    dropped when its closing line is there, so a stray `<<` in a quoted string hides nothing."""
    lines = command.split("\n")
    kept: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i += 1
        for match in _HEREDOC.finditer(line):
            strip_tabs, delimiter = bool(match.group(1)), match.group(3)
            for j in range(i, len(lines)):
                closing = (lines[j].lstrip("\t") if strip_tabs else lines[j]).rstrip("\r")
                if closing == delimiter:
                    i = j + 1
                    break
    return "\n".join(kept)


_OPERATOR = re.compile(r"&>>|&>|>>|>\||>&|<<<|<<|<&|<>|&&|\|\||\|&|;;|[;|&()<>`]")


def _tokens(command: str) -> List[Tuple[str, bool]]:
    """(text, is_operator) for each shell word and operator of `command`.

    Quotes and backslashes are resolved, so a quoted `>` is a word and not a redirection; a newline
    ends a command; a quote left open runs to the end of the text (the shell would refuse to run it).
    """
    tokens: List[Tuple[str, bool]] = []
    word: List[str] = []
    in_word = False
    i, n = 0, len(command)
    while i < n:
        char = command[i]
        if char in " \t\r\n();<>|&`":  # a word ends here
            if in_word:
                tokens.append(("".join(word), False))
                word, in_word = [], False
            if char == "\n":
                tokens.append((";", True))
                i += 1
            elif char in " \t\r":
                i += 1
            else:
                operator = _OPERATOR.match(command, i).group()
                tokens.append((operator, True))
                i += len(operator)
        elif char == "\\":
            if i + 1 < n and command[i + 1] != "\n":  # a backslash before a newline joins the lines
                word.append(command[i + 1])
                in_word = True
            i += 2
        elif char == "'":
            end = command.find("'", i + 1)
            end = n if end < 0 else end
            word.append(command[i + 1:end])
            in_word = True
            i = end + 1
        elif char == '"':
            in_word = True
            i += 1
            while i < n and command[i] != '"':
                if command[i] == "\\" and i + 1 < n and command[i + 1] in '"\\$`\n':
                    if command[i + 1] != "\n":
                        word.append(command[i + 1])
                    i += 2
                else:
                    word.append(command[i])
                    i += 1
            i += 1
        else:
            word.append(char)
            in_word = True
            i += 1
    if in_word:
        tokens.append(("".join(word), False))
    return tokens


def _split_options(args: List[str]) -> Tuple[List[str], List[str]]:
    """(options, operands) of `args`; everything after `--` is an operand."""
    if "--" in args:
        at = args.index("--")
        return args[:at], args[at + 1:]
    return [a for a in args if a.startswith("-") and a != "-"], [a for a in args if not (a.startswith("-") and a != "-")]


def _sed_targets(args: List[str]) -> List[str]:
    in_place = script_given = False
    operands: List[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        i += 1
        if arg == "--":
            operands += args[i:]
            break
        if arg.startswith("--"):
            if arg.startswith("--in-place"):
                in_place = True
            elif arg in ("--expression", "--file"):
                script_given = True
                i += 1  # its value is the next word
            elif arg.startswith(("--expression=", "--file=")):
                script_given = True
        elif arg.startswith("-") and arg != "-":
            for position, flag in enumerate(arg[1:], 1):
                if flag == "i":
                    in_place = True
                    if position == len(arg) - 1 and i < len(args) and args[i] == "":
                        i += 1  # macOS: `-i ''`, an empty backup suffix
                    break
                if flag in "ef":  # takes a value: the rest of this word, else the next one
                    script_given = True
                    if position == len(arg) - 1:
                        i += 1
                    break
        else:
            operands.append(arg)
    if not in_place:
        return []
    return [o for o in (operands if script_given else operands[1:]) if o]


def _command_targets(words: List[str]) -> List[Tuple[str, bool]]:
    """(file, may_be_a_folder) for what one simple command writes: `tee` files, the destination of `cp`
    and `mv` (which may be a folder, existing or about to be made), and the files of `sed -i`."""
    i = 0
    wrapped = False
    while i < len(words):
        word = words[i]
        name = word.rsplit("/", 1)[-1]
        if _ASSIGNMENT.match(word) or name in _WRAPPERS:
            wrapped = wrapped or name in _WRAPPERS
        elif not (wrapped and word.startswith("-")):
            break
        i += 1
    if i >= len(words):
        return []
    name, args = words[i].rsplit("/", 1)[-1], words[i + 1:]
    if name == "tee":
        return [(operand, False) for operand in _split_options(args)[1]]
    if name in ("cp", "mv"):
        for position, arg in enumerate(args):  # GNU: the destination folder comes first with -t
            if arg == "--":
                break
            if arg in ("-t", "--target-directory") and position + 1 < len(args):
                return [(args[position + 1], True)]
            if arg.startswith("--target-directory="):
                return [(arg.split("=", 1)[1], True)]
        operands = _split_options(args)[1]
        return [(operands[-1], True)] if len(operands) >= 2 else []
    if name == "sed":
        return [(target, False) for target in _sed_targets(args)]
    return []


def _bash_targets(command: str) -> List[Tuple[str, bool]]:
    found: List[Tuple[str, bool]] = []

    def add(target: str, folder: bool) -> None:
        if not target:
            return
        for position, (known, was_folder) in enumerate(found):
            if known == target:
                found[position] = (known, was_folder or folder)
                return
        found.append((target, folder))

    words: List[str] = []
    tokens = _tokens(_without_heredoc_bodies(command))
    i = 0
    while i < len(tokens):
        text, operator = tokens[i]
        i += 1
        if not operator:
            words.append(text)
            continue
        following = tokens[i] if i < len(tokens) and not tokens[i][1] else None  # the next word, if there is one
        if text.startswith((">", "&>")):  # an output redirection takes the next word
            if following is not None:
                i += 1
                if not (text.startswith(">&") and (following[0].isdigit() or following[0] == "-")):
                    add(following[0], False)  # (`2>&1` copies a descriptor; it writes no file)
        elif text.startswith("<"):
            if following is not None:
                i += 1  # an input redirection or a here-document marker, not a word of the command
        else:  # ; && || | & ( ) `: the command ends here
            for target, folder in _command_targets(words):
                add(target, folder)
            words = []
    for target, folder in _command_targets(words):
        add(target, folder)
    return found


def bash_targets(command: str) -> List[str]:
    """Files a shell command writes, as written: the targets of `>`, `>>`, `tee [-a]`, and the last
    argument of `cp`, `mv` and `sed -i`. A quoted `>` is text, not a redirection. A heuristic on
    purpose: it catches the tools one reaches for."""
    return [target for target, _folder in _bash_targets(command)]


def _inside(path: str, base: str) -> Optional[str]:
    """`path` relative to `base` (slash-separated), or None when it is `base` itself or outside it."""
    prefix = base.rstrip(os.sep) + os.sep
    if path.startswith(prefix) and len(path) > len(prefix):
        return path[len(prefix):].replace(os.sep, "/")
    return None


def targets(payload: Any, root: Path) -> List[Tuple[str, bool]]:
    """(relpath inside the brain, exists) for each file the tool call writes, in order.

    Reads `file_path`, `notebook_path` and the targets of a Bash `command`, resolves them against the
    payload's `cwd`, normalises `..` and symlinks, and drops what lies outside the brain. A folder
    comes back with a trailing `/` (so `cp a scripts/` meets the rule for `scripts/**`), and so does
    a destination of `cp` or `mv` that is not there yet, besides the plain name: it may be a folder
    the command is about to make (`cp -r draft .claude/skills/new`).
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("tool_input"), dict):
        return []
    tool_input = payload["tool_input"]
    named = [tool_input.get(key) for key in ("file_path", "notebook_path")]
    raw = [(value, False) for value in named if isinstance(value, str) and value]
    command = tool_input.get("command")
    if isinstance(command, str) and command:
        raw += _bash_targets(command)
    if not raw:
        return []
    cwd = payload.get("cwd")
    base = cwd if isinstance(cwd, str) and cwd else os.getcwd()
    roots = [os.path.normpath(os.path.abspath(str(root)))]
    if os.path.realpath(roots[0]) != roots[0]:
        roots.append(os.path.realpath(roots[0]))
    found: List[Tuple[str, bool]] = []
    for item, may_be_folder in raw:
        written_as_folder = item.endswith("/")
        item = os.path.expanduser(item)
        absolute = os.path.normpath(item if os.path.isabs(item) else os.path.join(base, item))
        candidates = [absolute]
        real = os.path.realpath(absolute)
        if real != absolute:
            candidates.append(real)
        for candidate in candidates:
            for top in roots:
                relative = _inside(candidate, top)
                if relative is None:
                    continue
                if os.path.isdir(candidate):
                    entries = [(relative + "/", True)]
                elif written_as_folder:
                    entries = [(relative + "/", False)]
                else:
                    exists = os.path.exists(candidate)
                    entries = [(relative, exists)]
                    if may_be_folder and not exists:
                        entries.append((relative + "/", False))
                for entry in entries:
                    if entry not in found:
                        found.append(entry)
    return found


# -- session state, waivers --------------------------------------------------------------------------


def _now() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")


def _session_id(payload: Any) -> str:
    raw = payload.get("session_id") if isinstance(payload, dict) else None
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", str(raw))[:128] if raw is not None else ""
    return cleaned or NO_SESSION


def _state_dir(root: Path) -> Path:
    import hashlib
    import tempfile

    digest = hashlib.sha1(str(root).encode("utf-8", "surrogateescape"), usedforsecurity=False).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / "brain-gate" / digest


def _state_path(root: Path, session_id: str) -> Path:
    return _state_dir(root) / f"{session_id or NO_SESSION}.json"


def _read_state(path: Path) -> Dict[str, Any]:
    state: Dict[str, Any] = {"ran": {}, "last_refusal": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return state
    if isinstance(data, dict):
        ran = data.get("ran")
        if isinstance(ran, dict):
            state["ran"] = {k: v for k, v in ran.items()
                            if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool)}
        if isinstance(data.get("last_refusal"), dict):
            state["last_refusal"] = data["last_refusal"]
    return state


def _make_dir(path: Path, mode: int) -> None:
    """Create `path` with exactly `mode` (the umask would narrow it); an existing folder is left alone."""
    try:
        os.mkdir(str(path), mode)
    except FileExistsError:
        if not path.is_dir():  # something else is in the way
            raise
        return
    os.chmod(str(path), mode)


def _ensure_state_dir(path: Path) -> None:
    """The shared `brain-gate` folder is sticky and world-writable, like /tmp itself, so a second user on
    the machine can still make their own folder in it; each brain's folder is private to its user."""
    _make_dir(path.parent.parent, 0o1777)
    _make_dir(path.parent, 0o700)


def _write_state(path: Path, state: Dict[str, Any]) -> None:
    _ensure_state_dir(path)
    scratch = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    scratch.write_text(json.dumps(state), encoding="utf-8")
    os.replace(str(scratch), str(path))


def _read_waiver(root: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads((Path(root) / WAIVER_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("skill"), str) and data["skill"]:
        return data
    return None


def _log_waiver(root: Path, event: str, skill: str, reason: str, path: str) -> None:
    """One tab-separated line: ISO time, armed|used, skill, reason, path (empty when armed)."""
    fields = [_now(), event, skill, reason, path]
    line = "\t".join(re.sub(r"[\t\r\n]+", " ", field) for field in fields)
    target = Path(root) / WAIVER_LOG
    os.makedirs(str(target.parent), exist_ok=True)
    with open(str(target), "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")


def record(root: Path, payload: Any) -> None:
    """Note one run of the skill a `Skill` tool call invoked, against the call's session."""
    if not isinstance(payload, dict):
        raise ValueError("the hook payload is not a JSON object")
    if payload.get("tool_name") not in (None, "Skill"):
        return
    tool_input = payload.get("tool_input")
    skill = tool_input.get("skill") if isinstance(tool_input, dict) else None
    skill = skill.strip().lstrip("/") if isinstance(skill, str) else ""
    if not skill:
        return
    path = _state_path(root, _session_id(payload))
    state = _read_state(path)
    state["ran"][skill] = state["ran"].get(skill, 0) + 1
    _write_state(path, state)


def _deny(reason: str) -> Dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def _needs(rule: Rule) -> str:
    needs = rule.skills[0]
    if len(rule.skills) > 1:
        needs += f" (or {' or '.join(rule.skills[1:])})"
    return needs


def _refusal(blocking: List[Tuple[str, Rule]]) -> Dict[str, Any]:
    """The refusal for the first blocked target, naming every owner set that is still unsatisfied."""
    first_rel, first_rule = blocking[0]
    reason = f"skill gate: writing {first_rel} needs {_needs(first_rule)} to run first in this session."
    if first_rule.why:
        reason += f" {first_rule.why}"
    for rel, rule in blocking[1:]:
        lead = "It also needs" if rel == first_rel else f"Writing {rel} needs"
        reason += f" {lead} {_needs(rule)} to run first."
        if rule.why:
            reason += f" {rule.why}"
    reason += (f" Invoke the skill{'s' if len(blocking) > 1 else ''}; a one-time waiver needs the person's "
               f"express say-so: _meta/brain gate waive {first_rule.skills[0]} \"<reason, and who said so>\"")
    return _deny(reason)


def _reserved_refusal(rel: str) -> Dict[str, Any]:
    return _deny(f"skill gate: writing {rel} is refused: the waiver and its log are written only by "
                 f"_meta/brain gate waive, and only on the person's express say-so. No skill run opens this path.")


def _remember_refusal(state_path: Path, state: Dict[str, Any], rel: str, skills: List[str], why: str) -> None:
    state["last_refusal"] = {"time": _now(), "path": rel, "skills": list(skills), "why": why}
    try:
        _write_state(state_path, state)
    except OSError:
        pass  # the refusal stands even when it cannot be remembered


def _state_problem(state_path: Path) -> str:
    """Why this session's runs could not be kept, or "" when they can."""
    try:
        _ensure_state_dir(state_path)
    except OSError as exc:
        return f"{state_path.parent}: {exc.strerror or type(exc).__name__}"
    if not os.access(str(state_path.parent), os.W_OK | os.X_OK):
        return f"{state_path.parent}: not writable"
    return ""


def _use_waiver(root: Path, waiver: Dict[str, Any], rels: List[str]) -> Optional[str]:
    """Spend the armed waiver on `rels`; the notice, or None when someone else spent it first."""
    try:
        os.unlink(str(Path(root) / WAIVER_FILE))
    except FileNotFoundError:
        return None
    reason = str(waiver.get("reason", ""))
    written = list(dict.fromkeys(rels))
    for rel in written:
        _log_waiver(root, "used", waiver["skill"], reason, rel)
    return (f"skill gate: the one-time waiver for {waiver['skill']} was used to write {', '.join(written)} "
            f"(reason: {reason}). It is spent and logged to {WAIVER_LOG.as_posix()}.")


Obligation = Tuple[str, bool, List[Rule]]  # a target, whether it exists, and every rule that matches it


def _decide(root: Path, payload: Any, obligations: List[Obligation]) -> Optional[Dict[str, Any]]:
    """Judge every (target, rule) pair first, without side effects; act only when none is blocked.

    A pair is satisfied by a run of one of the rule's skills. A revision of an existing file under a
    `spend_on_revision` rule uses up one run, so several revisions need several runs. An armed waiver
    covers the pairs whose rule names its skill. If any pair is left, nothing is spent or consumed.
    """
    state_path = _state_path(root, _session_id(payload))
    state = _read_state(state_path)
    remaining = dict(state["ran"])
    spends: List[Tuple[str, str]] = []
    unsatisfied: List[Tuple[str, Rule]] = []
    for rel, exists, matching in obligations:
        for rule in matching:
            owner = next((skill for skill in rule.skills if remaining.get(skill, 0) > 0), None)
            if owner is None:
                unsatisfied.append((rel, rule))
            elif rule.spend_on_revision and exists:
                remaining[owner] -= 1
                spends.append((rel, owner))
    notices: List[str] = []
    blocking = unsatisfied
    if unsatisfied:
        waiver = _read_waiver(root)
        if waiver is not None:
            blocking = [(rel, rule) for rel, rule in unsatisfied if waiver["skill"] not in rule.skills]
            if not blocking:
                used = _use_waiver(root, waiver, [rel for rel, _rule in unsatisfied])
                if used is None:
                    blocking = unsatisfied
                else:
                    notices.append(used)
    if blocking:
        rel, rule = blocking[0]
        problem = _state_problem(state_path)
        if problem:  # a refusal that no skill run could ever lift is not a refusal
            return {"systemMessage": f"skill gate: cannot keep session state ({problem}), so a run of "
                                     f"{rule.skills[0]} could never be recorded and {rel} was not checked "
                                     f"(write allowed)."}
        _remember_refusal(state_path, state, rel, rule.skills, rule.why)
        return _refusal(blocking)
    for rel, owner in spends:
        state["ran"][owner] -= 1
        notices.append(f"skill gate: editing {rel} spent the run of {owner} (every revision of this file goes "
                       f"back through it). Invoke {owner} again before the next edit.")
    if spends:
        _write_state(state_path, state)
    return {"systemMessage": " ".join(notices)} if notices else None


def check(root: Path, payload: Any) -> Optional[Dict[str, Any]]:
    """The hook answer for one tool call: a refusal, a notice, or None for an ordinary pass.

    Every target of the call that no exempt glob covers, and every rule that matches it, must be
    satisfied; the waiver files are refused unconditionally.
    """
    root = Path(root)
    found = targets(payload, root)
    if not found:
        return None
    for rel, _exists in found:
        if rel in RESERVED:
            state_path = _state_path(root, _session_id(payload))
            _remember_refusal(state_path, _read_state(state_path), rel, [], "reserved for gate waive")
            return _reserved_refusal(rel)
    from . import config

    rules, exempt = load_rules(root, config.load(root))
    obligations: List[Obligation] = []
    matched: Dict[str, List[Rule]] = {}
    for rel, exists in found:
        if any(globs.match(pattern, rel) for pattern in exempt):
            continue
        matching = [rule for rule in rules if globs.match(rule.path, rel)]
        matched[rel] = matching
        if rel.endswith("/"):  # the folder form of a name tried before: only its extra rules are new
            matching = [rule for rule in matching if rule not in matched.get(rel[:-1], [])]
        if matching:
            obligations.append((rel, exists, matching))
    return _decide(root, payload, obligations) if obligations else None


def waive(root: Path, skill: str, reason: str) -> str:
    """Arm a one-shot waiver for `skill`; the next write the gate would refuse for lack of it goes through."""
    skill, reason = skill.strip(), reason.strip()
    if not skill or not reason:
        raise ValueError("a waiver needs a skill and a reason, and who said so")
    previous = _read_waiver(root)
    target = Path(root) / WAIVER_FILE
    os.makedirs(str(target.parent), exist_ok=True)
    target.write_text(json.dumps({"skill": skill, "reason": reason, "armed": _now()}) + "\n", encoding="utf-8")
    _log_waiver(root, "armed", skill, reason, "")
    message = (f"waiver armed for {skill}: the next write that needs it goes through once, and is announced "
               f"and logged to {WAIVER_LOG.as_posix()}.")
    if previous is not None:
        message += f" It replaces the unused waiver for {previous['skill']}."
    return message


def _latest_session(root: Path) -> str:
    newest, best = "", -1.0
    try:
        for entry in os.scandir(str(_state_dir(root))):
            if entry.name.endswith(".json") and entry.stat().st_mtime > best:
                newest, best = entry.name[:-len(".json")], entry.stat().st_mtime
    except OSError:
        pass
    return newest


def status(root: Path, session_id: Optional[str] = None) -> Dict[str, Any]:
    """What ran in the session (the latest one for this brain when none is named), the armed waiver
    and the last refusal."""
    session = _session_id({"session_id": session_id}) if session_id else _latest_session(root)
    state = _read_state(_state_path(root, session)) if session else {"ran": {}, "last_refusal": None}
    return {"session": session, "ran": state["ran"], "waiver": _read_waiver(root),
            "last_refusal": state["last_refusal"]}


# -- the command ---------------------------------------------------------------------------------------


def add_arguments(parser) -> None:
    actions = parser.add_subparsers(dest="action", metavar="<action>", required=True)
    actions.add_parser("record", help="note the skill a Skill tool call ran (hook payload on stdin)",
                       description="PostToolUse hook: note the skill that ran against this session.")
    actions.add_parser("check", help="refuse a write to a ruled path until its skill ran (hook payload on stdin)",
                       description="PreToolUse hook: refuse a write to a ruled path until its skill ran.")
    waiver = actions.add_parser("waive", help="let the next refused write through once, with a reason",
                                description="One-shot waiver, only on the person's express say-so.")
    waiver.add_argument("skill", help="the skill whose rule is waived")
    waiver.add_argument("reason", help="why, and who said so")
    report = actions.add_parser("status", help="show what ran, any armed waiver and the last refusal",
                                description="Show what ran this session, any armed waiver and the last refusal.")
    report.add_argument("--session", default=None, help="session id (default: the latest session of this brain)")


def _hook(action: str, root: Path) -> int:
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            raise ValueError("the hook payload is not a JSON object")
        answer = record(root, payload) if action == "record" else check(root, payload)
    except Exception as exc:  # the gate must never fail a tool call
        outcome = "write allowed" if action == "check" else "run not recorded"
        answer = {"systemMessage": f"skill gate error ({outcome}): {str(exc) or type(exc).__name__}"}
    if answer:
        sys.stdout.write(json.dumps(answer) + "\n")
    return 0


def _format_status(info: Dict[str, Any]) -> List[str]:
    ran = ", ".join(f"{skill} x{count}" for skill, count in sorted(info["ran"].items())) or "nothing"
    waiver = info["waiver"]
    refusal = info["last_refusal"]
    lines = [f"session: {info['session'] or 'none'}", f"ran: {ran}"]
    if waiver:
        lines.append(f"waiver: {waiver['skill']} armed {waiver.get('armed', '?')} (reason: {waiver.get('reason', '')})")
    else:
        lines.append("waiver: none")
    if refusal and not refusal.get("skills"):
        lines.append(f"last refusal: {refusal.get('path', '?')} is reserved for gate waive ({refusal.get('time', '?')})")
    elif refusal:
        needs = " or ".join(refusal["skills"])
        lines.append(f"last refusal: {refusal.get('path', '?')} needs {needs} ({refusal.get('time', '?')})")
    else:
        lines.append("last refusal: none")
    return lines


def run(args) -> int:
    root = paths.harness_root()
    if args.action in ("record", "check"):
        return _hook(args.action, root)
    if args.action == "waive":
        try:
            print(waive(root, args.skill, args.reason))
        except ValueError as exc:
            print(f"gate: {exc}", file=sys.stderr)
            return 2
        return 0
    print("\n".join(_format_status(status(root, args.session))))
    return 0
