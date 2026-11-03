"""The skill gate (spec §7.9): hook commands that refuse a write until the skill that owns it has run.

`gate record` (PostToolUse on `Skill`) notes the skill against the session id in a private folder
(under `$XDG_RUNTIME_DIR` when set, else in the OS temp directory); `gate check` (PreToolUse on `Write`, `Edit` and `Bash`) refuses a write to a ruled path
unless an owning skill ran this session or the person armed a one-shot waiver. It is friction and
visibility, not a security boundary, and it never says "allow": the person's own permission prompt
stays in charge. If the gate itself errors it lets the write through with a visible warning.

Runs on every tool call, so imports stay lazy: a call that names no path inside the brain returns
before the config, the rules or any of the heavier modules are loaded.
"""
from __future__ import annotations

import errno
import json
import os
import re
import stat
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
# Words that open or close a compound command; a command follows them, so they must not hide it.
_RESERVED = {"if", "then", "else", "elif", "fi", "while", "until", "do", "done", "esac", "!", "{", "}"}
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


_OPERATOR = re.compile(r"&>>|&>|>>|>\||>&|<<<|<<-|<<|<&|<>|&&|\|\||\|&|;;&|;;|;&|[;|&()<>`]")
_BRACKETS = re.compile(r"[\[\](){}]")
_OPENER = {")": "(", "]": "[", "}": "{"}
_ANSI_ESCAPES = {"a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n", "r": "\r", "t": "\t",
                 "v": "\v", "\\": "\\", "'": "'", '"': '"', "?": "?"}
_ANSI_WIDTH = {"x": 2, "u": 4, "U": 8}
MAX_EXPANSIONS = 128  # alternatives one word may brace-expand to
MAX_BRACE_WORD = 4096  # a longer word, or one with more than MAX_BRACE_GROUPS braces, is taken literally
MAX_BRACE_GROUPS = 64
MAX_NESTING = 32  # `$(` inside `$(`: a command nested deeper than this is refused, since it cannot be checked
TOO_DEEP = f"a command nested more than {MAX_NESTING} levels deep"
# A skill the person starts by typing `/<skill>` may load without a Skill tool call, which the gate never sees.
SLASH_HINT = ("If the person started the skill by typing /<skill>, invoke it once with the Skill tool so the gate "
              "can see the run.")
_RESERVED_WHY = "reserved for gate waive"
MAX_HEREDOCS = 64  # here-documents opened on one line
MAX_MATCHES = 256  # names one glob may expand to
GLOB_SECONDS = 0.25  # how long one glob may spend looking


class _Word(str):
    """A shell word with quotes resolved. `mask` has one character per letter: "1" where the letter was
    quoted, escaped or decoded (so no brace or glob meaning), "0" where bash would read it as syntax."""

    mask: str = ""
    subs: Tuple = ()  # the commands inside the `$(...)` and `<(...)` the word holds, as token lists


def _word(chars: List[str], flags: List[str], subs: Optional[List[Any]] = None) -> _Word:
    word = _Word("".join(chars))
    word.mask = "".join(flags)
    word.subs = tuple(subs or ())
    return word


def _ansi_c(command: str, i: int) -> Tuple[str, int, bool]:
    """The text of the `$'...'` string whose opening quote is `command[i]`, the index after its end, and
    whether it was closed at all. Bash cuts the text at the first NUL it decodes."""
    out: List[str] = []
    n = len(command)
    i += 1
    while i < n and command[i] != "'":
        char = command[i]
        following = command[i + 1] if i + 1 < n else ""
        if char != "\\" or not following:
            out.append(char)
            i += 1
        elif following in _ANSI_ESCAPES:
            out.append(_ANSI_ESCAPES[following])
            i += 2
        elif following in _ANSI_WIDTH:
            digits = re.match(r"[0-9A-Fa-f]{1,%d}" % _ANSI_WIDTH[following], command[i + 2:i + 2 + _ANSI_WIDTH[following]])
            if digits:
                try:
                    out.append(chr(int(digits.group(), 16)))
                except (ValueError, OverflowError):
                    pass
                i += 2 + len(digits.group())
            else:
                out.append(char + following)
                i += 2
        elif following in "01234567":
            octal = re.match(r"[0-7]*", command[i + 1:i + 4]).group()  # 1 to 3 digits: `following` is one
            out.append(chr(int(octal, 8)))
            i += 1 + len(octal)
        else:
            out.append(char + following)
            i += 2
    return "".join(out).split("\0", 1)[0], i + 1, i < n


Token = Tuple[str, bool, bool]  # (text, is_operator, attached)


class _Source:
    """One command being read, and what every nested part of it shares: where each bracket closes and
    where each line starts (each found once, and only when first needed), the substitutions already read,
    and whether any part is nested too deep to read."""

    def __init__(self, command: str) -> None:
        self.command = command
        self.too_deep = False
        self._inner: Dict[Tuple[int, int], Tuple[List[Token], int, bool]] = {}
        self._closes: Optional[Dict[int, int]] = None
        self._lines: Optional[Tuple[Dict[str, List[Tuple[int, int]]], ...]] = None
        self._closers: Tuple[List[Tuple[str, int, int]], ...] = ()
        self._spots: Dict[Tuple[str, bool], List[Tuple[int, int]]] = {}

    def nested(self, start: int, depth: int) -> Tuple[List[Token], int]:
        """`_scan` of the substitution whose text starts at `start`. Each is read once: a double quote left
        open is read a second time as plain text, and must not read everything inside it again."""
        key = (start, depth)
        if key not in self._inner:
            outside, self.too_deep = self.too_deep, False
            tokens, end = _scan(self, start, depth)
            self._inner[key] = (tokens, end, self.too_deep)
            self.too_deep = outside
        tokens, end, too_deep = self._inner[key]
        self.too_deep = self.too_deep or too_deep
        return tokens, end

    def close(self, start: int) -> int:
        """Where the bracket at `start` closes, counting brackets as plain characters; -1 when it never does."""
        if self._closes is None:
            closes: Dict[int, int] = {}
            open_at: Dict[str, List[int]] = {"(": [], "[": [], "{": []}
            for match in _BRACKETS.finditer(self.command):
                char = match.group()
                if char in open_at:
                    open_at[char].append(match.start())
                elif open_at[_OPENER[char]]:
                    closes[open_at[_OPENER[char]].pop()] = match.start()
            self._closes = closes
        return self._closes.get(start, -1)

    def arithmetic_end(self, inner: int) -> int:
        """The index after the `))` of the `((` whose second parenthesis is at `inner`, or -1 when bash reads
        it as subshells: the parenthesis that closes `inner` must be followed straight away by another."""
        close = self.close(inner)
        return close + 2 if close >= 0 and self.command.startswith(")", close + 1) else -1

    def _index(self) -> Tuple[Dict[str, List[Tuple[int, int]]], ...]:
        """(lines by text, lines by text without leading tabs): each a list of (start, index after the line),
        a trailing `\\r` ignored. Lines holding a `)` also go into `_closers`, sorted by the text before it."""
        if self._lines is None:
            exact: Dict[str, List[Tuple[int, int]]] = {}
            tabbed: Dict[str, List[Tuple[int, int]]] = {}
            plain: List[Tuple[str, int, int]] = []
            stripped: List[Tuple[str, int, int]] = []
            start, n = 0, len(self.command)
            for line in self.command.split("\n"):
                after = min(start + len(line) + 1, n)
                text = line[:-1] if line.endswith("\r") else line
                exact.setdefault(text, []).append((start, after))
                tabbed.setdefault(text.lstrip("\t"), []).append((start, after))
                cut = line.find(")")
                if cut >= 0:
                    head = line[:cut]
                    bare = head.lstrip("\t")
                    plain.append((head, start, 0))
                    stripped.append((bare, start, cut - len(bare)))  # with how many tabs it starts
                start += len(line) + 1
            plain.sort()
            stripped.sort()
            self._lines, self._closers = (exact, tabbed), (plain, stripped)
        return self._lines

    def heredoc_end(self, start: int, delimiter: str, strip_tabs: bool, nested: bool) -> Tuple[int, bool]:
        """(where reading goes on, whether that is in the middle of a line) after the body of a here-document
        whose first line starts at `start`. The body ends at a line that is the delimiter (after tabs, for
        `<<-`); inside a substitution also at one that starts with it and goes on to a `)`, where bash reads
        on right after the delimiter (`EOF)"`). With no such line nothing is skipped: a stray `<<` hides
        nothing."""
        from bisect import bisect_left

        rows = self._index()[1 if strip_tabs else 0].get(delimiter, [])
        found = bisect_left(rows, (start,))
        best = rows[found] if found < len(rows) else None
        mid_line = False
        if nested:
            spots = self._spots.get((delimiter, strip_tabs))
            if spots is None:  # lines whose text before the first `)` starts with the delimiter
                table = self._closers[1 if strip_tabs else 0]
                spots = []
                at = bisect_left(table, (delimiter,))  # they sort together, right from here
                while at < len(table) and table[at][0].startswith(delimiter):
                    _head, line_start, lead = table[at]
                    spots.append((line_start, line_start + lead + len(delimiter)))
                    at += 1
                spots.sort()
                self._spots[(delimiter, strip_tabs)] = spots
            found = bisect_left(spots, (start,))
            if found < len(spots) and (best is None or spots[found][0] < best[0]):
                best, mid_line = spots[found], True
        return (start, False) if best is None else (best[1], mid_line)


def _follow_case(cases: List[str], text: "_Word", at_command: bool) -> None:
    """Move the open `case` commands on past one word: `case WORD in`, then patterns up to their `)`, a
    body up to `;;` (or `;&`, `;;&`), more patterns, and `esac`. A quoted word is never a reserved word."""
    keyword = str(text) if "1" not in getattr(text, "mask", "1") else ""
    state = cases[-1] if cases else ""
    if state == "subject":
        cases[-1] = "in"
    elif state == "in":
        if keyword == "in":
            cases[-1] = "pattern"
    elif state == "pattern":
        if keyword == "esac":
            cases.pop()
    elif keyword == "case" and at_command:
        cases.append("subject")
    elif keyword == "esac" and state == "body" and at_command:
        cases.pop()


def _scan(source: _Source, i: int, depth: int = 0) -> Tuple[List[Token], int]:
    """(tokens, index after them) for the shell text from `source.command[i]`.

    A call with `depth` above 0 reads the inside of a `$(...)` or `<(...)` and stops after its closing
    parenthesis; each substitution is scanned by such a call, with its own quotes, comments, here-documents
    and `case` patterns (whose `)` closes nothing), whether it stands in a command or inside double quotes,
    and hangs on the word it belongs to (`_Word.subs`). Deeper than MAX_NESTING, `source.too_deep` is set.

    Quotes and backslashes are resolved, so a quoted `>` is a word and not a redirection; `$'...'` is
    decoded and `$"..."` is a double-quoted string; a comment (a `#` that starts a word, outside `${...}`;
    inside backticks it ends at the closing backtick) runs to the end of its line; the body of a
    here-document is skipped; arithmetic (`$((...))`, `((...))`, `$[...]`) is skipped, so a `<<` in it is a
    shift, but a `((` or `$((` that does not close with `))` opens subshells, as in bash; a newline ends a
    command. Nothing left open swallows what follows it: a quote, `$[`, `$((` or `${` that never closes is
    read as plain characters and the text after it as usual. Words are `_Word`s that remember which letters
    were quoted. `attached` is true for an operator that touches the word before it (`2>&1`).
    """
    command = source.command
    nested = depth > 0
    tokens: List[Token] = []
    word: List[str] = []
    flags: List[str] = []
    subs: List[Any] = []
    in_word = False
    ticks = param = paren = 0  # open backticks (0 or 1), `${` depth, plain `(` depth
    cases: List[str] = []  # each open `case`: "subject", "in", "pattern" or "body"
    heredoc: Optional[bool] = None  # a `<<` is waiting for its delimiter; True when it is `<<-`
    waiting: List[Tuple[str, bool]] = []  # here-documents whose bodies start after this line
    n = len(command)

    def command_position() -> bool:
        """True where a command may start: after an operator, a reserved word, or `for`."""
        return not tokens or tokens[-1][1] or str(tokens[-1][0]) in _RESERVED or str(tokens[-1][0]) == "for"

    def end_word() -> None:
        nonlocal word, flags, subs, in_word, heredoc
        text = _word(word, flags, subs)
        if heredoc is not None:
            if len(waiting) < MAX_HEREDOCS:
                waiting.append((str(text), heredoc))
            heredoc = None
        else:  # the word after a redirection is a file name (`echo > case`), never a reserved word
            redirected = bool(tokens) and tokens[-1][1] and any(c in tokens[-1][0] for c in "<>")
            _follow_case(cases, text, command_position() and not redirected)
        tokens.append((text, False, False))
        word, flags, subs, in_word = [], [], [], False

    def substitution(start: int) -> int:
        """Read the substitution whose text starts at `start` onto this word; the index after it, or -1 when
        it is nested too deep to read (the command is then refused)."""
        if depth >= MAX_NESTING:
            source.too_deep = True
            return -1
        inner, after = source.nested(start, depth + 1)
        subs.append(inner)
        return after

    while i < n:
        char = command[i]
        if char in " \t\r\n();<>|&`":  # a word ends here
            attached = in_word
            if in_word:
                end_word()
            if char == "\n":
                tokens.append((";", True, False))
                i += 1
                for delimiter, strip_tabs in waiting:
                    i, mid_line = source.heredoc_end(i, delimiter, strip_tabs, nested)
                    if mid_line:  # `EOF)`: what follows the delimiter is read on, and ends any other body
                        break
                waiting = []
                continue
            if char in " \t\r":
                i += 1
                continue
            operator = _OPERATOR.match(command, i).group()
            heredoc = (operator == "<<-") if operator in ("<<", "<<-") else None
            if operator in (">", "<") and command.startswith("(", i + 1):
                after = substitution(i + 2)  # `>(cmd)`: a word standing for a pipe
                if after >= 0:
                    word, flags, in_word, i = list(operator + "()"), ["1"] * 3, True, after
                    continue
            state = cases[-1] if cases else ""
            pattern = state == "pattern" and operator in ("(", ")")
            if pattern:  # `(a)` or `a)` in a case: a pattern, not a group
                if operator == ")":
                    cases[-1] = "body"
            elif operator == "`":
                ticks ^= 1
            elif operator == "(":
                if command.startswith("((", i) and command_position():
                    after = source.arithmetic_end(i + 1)
                    if after >= 0:  # `(( a << 1 ))`: arithmetic
                        tokens.append((_word(list("(())"), ["1"] * 4), False, False))
                        i = after
                        continue
                paren += 1  # a subshell; `((cd a && cp x y) && echo ok)` opens two
            elif operator == ")":
                if paren:
                    paren -= 1
                elif nested:
                    return tokens, i + 1
            elif operator in (";;", ";&", ";;&") and state == "body":
                cases[-1] = "pattern"
            tokens.append((";" if pattern else operator, True, attached))  # a pattern's parens group nothing
            i += len(operator)
        elif char == "#" and not in_word and not param:
            stop = "\n`" if ticks else "\n"
            while i < n and command[i] not in stop:  # the newline (or backtick) itself still counts
                i += 1
        elif char == "\\":
            if i + 1 < n and command[i + 1] != "\n":  # a backslash before a newline joins the lines
                word.append(command[i + 1])
                flags.append("1")
                in_word = True
            i += 2
        elif char == "$" and command.startswith('$"', i):
            i += 1  # `$"..."` is a double-quoted string, translated if there is a catalogue
        elif char == "$" and command.startswith("$((", i) and source.arithmetic_end(i + 2) >= 0:
            i = source.arithmetic_end(i + 2)
            word.extend("$(())")
            flags.extend("11111")
            in_word = True
        elif char == "$" and command.startswith("$[", i) and source.close(i + 1) >= 0:
            i = source.close(i + 1) + 1
            word.extend("$(())")
            flags.extend("11111")
            in_word = True
        elif char == "$" and command[i + 1:i + 2] in ("'", "("):
            # `$'...'`, decoded; `$(...)`, also a `$((cmd) )` that is no arithmetic. Left open, or nested too
            # deep to read (refused then), the `$` is a plain character.
            if command[i + 1] == "'":
                text, after, closed = _ansi_c(command, i + 1)
            else:
                text, after = "$()", substitution(i + 2)
                closed = after >= 0
            if closed:
                word.extend(text)
                flags.extend("1" * len(text))
                i = after
            else:
                word.append(char)
                flags.append("0")
                i += 1
            in_word = True
        elif char == "'":
            end = command.find("'", i + 1)
            if end < 0:  # never closed: a plain character, and what follows is read as usual
                word.append(char)
                flags.append("1")
                i += 1
            else:
                word.extend(command[i + 1:end])
                flags.extend("1" * (end - i - 1))
                i = end + 1
            in_word = True
        elif char == '"':
            start, kept, too_deep = i, (len(word), len(subs)), source.too_deep
            i += 1
            while i < n and command[i] != '"':
                if command[i] == "\\" and i + 1 < n and command[i + 1] in '"\\$`\n':
                    if command[i + 1] != "\n":
                        word.append(command[i + 1])
                        flags.append("1")
                    i += 2
                elif command.startswith("$((", i) and source.arithmetic_end(i + 2) >= 0:
                    i = source.arithmetic_end(i + 2)
                    word.extend("$(())")
                    flags.extend("11111")
                elif command.startswith("$(", i):
                    after = substitution(i + 2)  # its own quotes, comments, here-documents
                    text = "$()" if after >= 0 else "$"
                    word.extend(text)
                    flags.extend("1" * len(text))
                    i = after if after >= 0 else i + 1
                else:
                    word.append(command[i])
                    flags.append("1")
                    i += 1
            if i >= n:  # never closed: the quote is a plain character, and what follows is read as usual
                del word[kept[0]:], flags[kept[0]:], subs[kept[1]:]
                source.too_deep = too_deep
                word.append(char)
                flags.append("1")
                i = start
            in_word = True
            i += 1
        else:
            if char == "{" and command[i - 1:i] == "$" and source.close(i) >= 0:
                param += 1  # a `${` that never closes is plain text, so a later `#` is still a comment
            elif char == "}" and param:
                param -= 1
            word.append(char)
            flags.append("0")
            in_word = True
            i += 1
    if in_word:
        end_word()
    return tokens, n


def _tokens(command: str) -> Tuple[List[Token], bool]:
    """The tokens of `command`, and whether some part of it is nested too deep to read."""
    source = _Source(command)
    return _scan(source, 0)[0], source.too_deep


def _brace_expand(word: str) -> List[str]:
    """`word` with its simple `{a,b}` groups expanded, as bash does before it opens a file. Quoted or
    escaped braces and `${` are left alone; the number of results is capped."""
    if len(word) > MAX_BRACE_WORD or word.count("{") > MAX_BRACE_GROUPS:
        return [word]
    mask = getattr(word, "mask", "0" * len(word))
    for start, char in enumerate(word):
        if char != "{" or mask[start] != "0" or (start and word[start - 1] == "$"):
            continue
        depth, commas = 0, []
        for end in range(start, len(word)):
            if mask[end] != "0":
                continue
            if word[end] == "{":
                depth += 1
            elif word[end] == "," and depth == 1:
                commas.append(end)
            elif word[end] == "}":
                depth -= 1
                if depth == 0:
                    break
        else:
            continue  # never closed
        if not commas:
            continue  # `{a}` is just text
        edges = [start] + commas + [end]
        expanded: List[str] = []
        for left, right in zip(edges, edges[1:]):
            joined = _Word(word[:start] + word[left + 1:right] + word[end + 1:])
            joined.mask = mask[:start] + mask[left + 1:right] + mask[end + 1:]
            expanded += _brace_expand(joined)
            if len(expanded) >= MAX_EXPANSIONS:
                return expanded[:MAX_EXPANSIONS]
        return expanded
    return [word]


def _has_glob(word: str) -> bool:
    mask = getattr(word, "mask", "")  # only words out of a command have one: a tool's own path is literal
    return len(mask) == len(word) and any(char in "*?[" and mask[k] == "0" for k, char in enumerate(word))


def _expand_glob(word: str, base: str) -> List[str]:
    """The existing paths `word` matches when it is read as a glob in the folder `base`, or [] when it
    has no unquoted glob character or matches nothing. Bounded in matches and in time."""
    if not _has_glob(word):
        return []
    import fnmatch
    import time

    mask = getattr(word, "mask")
    segments: List[Tuple[str, str, bool]] = []  # (text, fnmatch pattern, has glob characters)
    start = 0
    for end in range(len(word) + 1):
        if end < len(word) and word[end] != "/":
            continue
        text, flags = word[start:end], mask[start:end]
        start = end + 1
        if text:
            pattern = "".join(f"[{c}]" if f == "1" and c in "*?[" else c for c, f in zip(text, flags))
            segments.append((text, pattern, any(c in "*?[" and f == "0" for c, f in zip(text, flags))))
    found: List[str] = []
    deadline = time.monotonic() + GLOB_SECONDS

    def walk(prefix: str, index: int) -> None:
        if len(found) >= MAX_MATCHES or time.monotonic() > deadline:
            return
        if index == len(segments):
            found.append(prefix)
            return
        text, pattern, magic = segments[index]
        if not magic:
            following = os.path.join(prefix, text)
            if os.path.lexists(following):
                walk(following, index + 1)
            return
        try:
            names = sorted(os.listdir(prefix))
        except OSError:
            return
        for name in names:
            if name.startswith(".") and not pattern.startswith("."):
                continue
            if fnmatch.fnmatchcase(name, pattern):
                walk(os.path.join(prefix, name), index + 1)

    walk("/" if word.startswith("/") else base, 0)
    return found


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


class _Target(NamedTuple):
    """A file a command writes: as written, whether it may be a folder (the destination of `cp`, `mv`,
    `ln`), the sources that land in it when it is an existing folder, and the folder a relative name is
    read against: "" for the one the call runs in, the path a literal `cd` before it moved to, or None
    after a `cd` the gate cannot read (a relative name then means a folder it does not know)."""

    word: str
    folder: bool = False
    sources: Tuple[str, ...] = ()
    at: Optional[str] = ""


_CHDIR = {"cd", "pushd", "popd"}
_CD_OPTIONS = {"-L", "-P", "-e", "-@"}


def _after_chdir(words: List[str], here: Optional[str]) -> Optional[str]:
    """The folder a shell is in after the simple command `words`, given that it was in `here` before ("" is
    the folder the call runs in, None one the gate does not know). A `cd <path>` (or `pushd`) with a plain
    literal path, absolute, relative or `~`-prefixed, moves to it, a relative one from `here`; a bare `cd`
    goes home. A `cd` it cannot read (`cd "$X"`, `cd -`, `cd $(...)`, `cd *`, `popd`) leaves it unknown, and
    that stays so until a `cd` to an absolute path. Any other command leaves it where it was."""
    i = 0
    while i < len(words) and (words[i] in _RESERVED or words[i] in ("builtin", "command")
                              or _ASSIGNMENT.match(words[i])):
        i += 1
    if i >= len(words) or words[i] not in _CHDIR:
        return here
    name, args = words[i], list(words[i + 1:])
    while args and args[0] in _CD_OPTIONS:
        args.pop(0)
    if args[:1] == ["--"]:
        args.pop(0)
    elif args and args[0].startswith("-"):
        return None  # `cd -` is the previous folder; an option such as `pushd -n` is not read
    if name == "popd" or (name == "pushd" and not args) or len(args) > 1:
        return None
    path = args[0] if args else "~"  # a bare `cd` goes home
    if "$" in path or _has_glob(path) or path[:2] in ("~+", "~-"):
        return None
    if not path:
        return here  # `cd ""` stays where it is
    if path.startswith(("/", "~")):
        return path
    return None if here is None else os.path.join(here, path)


def _command_targets(words: List[str]) -> List[_Target]:
    """What one simple command writes: `tee` files, the destination of `cp`, `mv` and `ln` (which may be a
    folder, existing or about to be made, so the sources count too) and the files of `sed -i`."""
    i = 0
    wrapped = False
    while i < len(words):
        word = words[i]
        name = word.rsplit("/", 1)[-1]
        if word in _RESERVED:
            pass  # `then cp a b`, `{ cp a b`, `! cp a b`: the command is what follows
        elif _ASSIGNMENT.match(word) or name in _WRAPPERS:
            wrapped = wrapped or name in _WRAPPERS
        elif not (wrapped and word.startswith("-")):
            break
        i += 1
    if i >= len(words):
        return []
    name, args = words[i].rsplit("/", 1)[-1], words[i + 1:]
    if name == "tee":
        return [_Target(operand) for operand in _split_options(args)[1]]
    if name in ("cp", "mv", "ln"):
        for position, arg in enumerate(args):  # GNU: the destination folder comes first with -t
            if arg == "--":
                break
            if arg in ("-t", "--target-directory") and position + 1 < len(args):
                rest = args[:position] + args[position + 2:]
                return [_Target(args[position + 1], True, tuple(_split_options(rest)[1]))]
            if arg.startswith("--target-directory="):
                rest = args[:position] + args[position + 1:]
                return [_Target(arg.split("=", 1)[1], True, tuple(_split_options(rest)[1]))]
        operands = _split_options(args)[1]
        return [_Target(operands[-1], True, tuple(operands[:-1]))] if len(operands) >= 2 else []
    if name == "sed":
        return [_Target(target) for target in _sed_targets(args)]
    return []


def _bash_targets(command: str) -> Tuple[List[_Target], bool]:
    """What `command` writes, and whether some part of it is nested too deep to read."""
    found: List[_Target] = []
    here: List[Optional[str]] = [""]  # where the command is now: see `_after_chdir`

    def add(target: _Target) -> None:
        if not target.word or target.word in ("<()", ">()"):  # a process substitution is an argument, not a file
            return
        target = target._replace(at=here[0])
        for position, known in enumerate(found):
            if known.word == target.word and known.at == target.at:
                found[position] = _Target(known.word, known.folder or target.folder,
                                          known.sources + tuple(s for s in target.sources if s not in known.sources),
                                          known.at)
                return
        found.append(target)

    def end_command(words: List[str], alone: bool = True) -> None:
        for target in _command_targets(words):
            add(target)
        if alone:  # in a pipeline or in the background a `cd` moves a subshell, not this one
            here[0] = _after_chdir(words, here[0])

    def scoped(tokens: List[Token]) -> None:
        """A `$(...)` or `<(...)` runs in a subshell: a `cd` in it does not carry out."""
        kept = here[0]
        collect(tokens)
        here[0] = kept

    def collect(tokens: List[Token]) -> None:
        words: List[str] = []
        groups: List[Optional[str]] = []  # where each open `( ... )` was entered: a `cd` in it ends with it
        piped = False  # the command before was piped into this one
        i = 0
        while i < len(tokens):
            text, operator, attached = tokens[i]
            i += 1
            if not operator:
                for inner in getattr(text, "subs", ()):  # what runs to make this word comes first
                    scoped(inner)
                words.extend(_brace_expand(text))  # before cp and mv pick their operands: `cp a{,.bak}`
                continue
            if attached and text[0] in "<>" and words and words[-1].isdigit():
                words.pop()  # `2>&1`, `2>/dev/null`: the digits name a file descriptor, not an operand
            following = tokens[i][0] if i < len(tokens) and not tokens[i][1] else None  # the next word, if any
            if text.startswith((">", "&>")):  # an output redirection takes the next word
                if following is not None:
                    i += 1
                    for inner in getattr(following, "subs", ()):
                        scoped(inner)
                    if not (text.startswith(">&") and (following.isdigit() or following == "-")):
                        for alternative in _brace_expand(following):  # (`2>&1` copies a descriptor)
                            add(_Target(alternative))
            elif text.startswith("<"):
                if following is not None:
                    i += 1  # an input redirection or a here-document marker, not a word of the command
                    for inner in getattr(following, "subs", ()):
                        scoped(inner)
            else:  # ; && || | & ( ) `: the command ends here
                end_command(words, not piped and text not in ("|", "|&", "&"))
                words = []
                piped = text in ("|", "|&")
                if text == "(":
                    groups.append(here[0])
                elif text == ")" and groups:
                    here[0] = groups.pop()
        end_command(words, not piped)

    tokens, too_deep = _tokens(command)
    collect(tokens)
    return found, too_deep


def bash_targets(command: str) -> List[str]:
    """Files a shell command writes, as written: the targets of `>`, `>>`, `tee [-a]`, and the last
    argument of `cp`, `mv`, `ln` and `sed -i`, after quotes and `{a,b}` groups are resolved. A quoted `>` is
    text, not a redirection, and a comment hides the rest of its line. A heuristic on purpose: it catches
    the tools one reaches for."""
    return list(dict.fromkeys(str(target.word) for target in _bash_targets(command)[0]))


def _inside(path: str, base: str) -> Optional[str]:
    """`path` relative to `base` (slash-separated), or None when it is `base` itself or outside it."""
    prefix = base.rstrip(os.sep) + os.sep
    if path.startswith(prefix) and len(path) > len(prefix):
        return path[len(prefix):].replace(os.sep, "/")
    return None


def targets(payload: Any, root: Path) -> List[Tuple[str, bool]]:
    """(relpath inside the brain, exists) for each file the tool call writes, in order.

    Reads `file_path`, `notebook_path` and the targets of a Bash `command`, resolves them against the
    payload's `cwd`, normalises `..` and symlinks, and drops what lies outside the brain. A relative target
    after a literal `cd <path>` in the command is read against that folder; after a `cd` the gate cannot
    read (`cd "$X"`, `cd -`) it is dropped. Globs in a command's targets are matched against the folder it
    runs in (no match leaves the name as written).
    A folder comes back with a trailing `/` (so `cp a scripts/` meets the rule for `scripts/**`), and so
    does a destination of `cp` or `mv` that is not there yet, besides the plain name: it may be a folder
    the command is about to make (`cp -r draft .claude/skills/new`). A destination that is a folder also
    brings the name each source gets in it.
    """
    return _targets(payload, root)[0]


def _targets(payload: Any, root: Path) -> Tuple[List[Tuple[str, bool]], bool]:
    """`targets(payload, root)`, and whether the call's command is nested too deep to read."""
    if not isinstance(payload, dict) or not isinstance(payload.get("tool_input"), dict):
        return [], False
    tool_input = payload["tool_input"]
    named = [tool_input.get(key) for key in ("file_path", "notebook_path")]
    raw = [_Target(value) for value in named if isinstance(value, str) and value]
    command = tool_input.get("command")
    too_deep = False
    if isinstance(command, str) and command:
        written, too_deep = _bash_targets(command)
        raw += written
    if not raw:
        return [], too_deep
    cwd = payload.get("cwd")
    base = os.path.abspath(cwd if isinstance(cwd, str) and cwd else os.getcwd())
    roots = [os.path.normpath(os.path.abspath(str(root)))]
    if os.path.realpath(roots[0]) != roots[0]:
        roots.append(os.path.realpath(roots[0]))
    found: List[Tuple[str, bool]] = []

    def keep(entry: Tuple[str, bool]) -> None:
        if entry not in found:
            found.append(entry)

    def keep_names(candidate: str, relative: str, written_as_folder: bool, may_be_folder: bool) -> None:
        if os.path.isdir(candidate):
            keep((relative + "/", True))
        elif written_as_folder:
            keep((relative + "/", False))
        else:
            exists = os.path.exists(candidate)
            keep((relative, exists))
            if may_be_folder and not exists:
                keep((relative + "/", False))

    for target in raw:
        try:  # a relative name is read against the folder a literal `cd` before it moved to
            here = base if not target.at else os.path.normpath(os.path.join(base, os.path.expanduser(target.at)))
        except (ValueError, OSError):
            continue
        if target.at is None and not os.path.isabs(os.path.expanduser(str(target.word))):
            continue  # after a `cd` it cannot read a relative name means a folder the gate does not know
        # One name that cannot be looked at (a lone surrogate, say) is skipped, never allowed to
        # fail the whole call open: every other name of the call is still checked.
        try:
            names = _expand_glob(target.word, here) or [str(target.word)]
        except (ValueError, OSError):
            names = [str(target.word)]
        arrivals: List[Tuple[str, bool]] = []  # (name a source gets in the folder, may be a folder itself)
        for source in target.sources:
            try:
                for path in _expand_glob(source, here) or [str(source)]:
                    name = os.path.basename(path.rstrip("/"))
                    if name and name not in (".", ".."):
                        arrivals.append((name, not os.path.isfile(os.path.join(here, os.path.expanduser(path)))))
            except (ValueError, OSError):
                continue
        for item in names:
            try:
                item = os.path.expanduser(item.split("\0", 1)[0])
                if not item:
                    continue
                written_as_folder = item.endswith("/")
                absolute = os.path.normpath(item if os.path.isabs(item) else os.path.join(here, item))
                candidates = [absolute]
                real = os.path.realpath(absolute)
                if real != absolute:
                    candidates.append(real)
                for candidate in candidates:
                    for top in roots:
                        relative = _inside(candidate, top)
                        if relative is None:
                            continue
                        keep_names(candidate, relative, written_as_folder, target.folder)
                        if os.path.isdir(candidate):
                            for name, may_be_folder in arrivals:
                                keep_names(os.path.join(candidate, name), f"{relative}/{name}", False, may_be_folder)
            except (ValueError, OSError):
                continue
    return found, too_deep


# -- session state, waivers --------------------------------------------------------------------------


def _now() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")


def _session_id(payload: Any) -> str:
    raw = payload.get("session_id") if isinstance(payload, dict) else None
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", str(raw))[:128] if raw is not None else ""
    return cleaned or NO_SESSION


def _state_base() -> Tuple[Path, int]:
    """The shared state folder and the mode it is made with: `$XDG_RUNTIME_DIR/brain-gate` (private to the
    user) when that variable names a folder the user owns, else `brain-gate` in the OS temp folder, which
    every user shares, so sticky and world-writable like /tmp itself."""
    run = os.environ.get("XDG_RUNTIME_DIR")
    if run:
        try:
            info = os.stat(run)
        except OSError:
            info = None
        if info is not None and stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid():
            return Path(run) / "brain-gate", 0o700
    import tempfile

    return Path(tempfile.gettempdir()) / "brain-gate", 0o1777


def _state_dir(root: Path) -> Path:
    import hashlib

    digest = hashlib.sha1(str(root).encode("utf-8", "surrogateescape"), usedforsecurity=False).hexdigest()[:12]
    return _state_base()[0] / digest


def _state_path(root: Path, session_id: str) -> Path:
    return _state_dir(root) / f"{session_id or NO_SESSION}.json"


def _verify_state_dir(folder: Path) -> None:
    """Raise unless `folder` is a real folder (not a link) of this user that nobody else can use: anything
    else could hold state someone forged, or lead a write somewhere else."""
    info = os.lstat(str(folder))
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise PermissionError(errno.EPERM, "not a private folder of this user")


def _read_state(path: Path) -> Dict[str, Any]:
    state: Dict[str, Any] = {"ran": {}, "last_refusal": None}
    try:
        _verify_state_dir(path.parent)
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
    """Make the shared `brain-gate` folder (a second user on the machine must still be able to make their
    own folder in it) and this brain's private one, and insist that the latter is what it should be."""
    _make_dir(path.parent.parent, _state_base()[1])
    _make_dir(path.parent, 0o700)
    _verify_state_dir(path.parent)


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
    listed = [first_rule]
    for rel, rule in blocking[1:]:
        if rule in listed:  # the same rule blocking a second name (cp into a folder) is said once
            continue
        listed.append(rule)
        lead = "It also needs" if rel == first_rel else f"Writing {rel} needs"
        reason += f" {lead} {_needs(rule)} to run first."
        if rule.why:
            reason += f" {rule.why}"
    reason += (f" Invoke the skill{'s' if len(listed) > 1 else ''}. {SLASH_HINT} A one-time waiver needs the "
               f"person's express say-so: _meta/brain gate waive {first_rule.skills[0]} \"<reason, and who said so>\"")
    return _deny(reason)


def _reserved_refusal(rel: str) -> Dict[str, Any]:
    return _deny(f"skill gate: writing {rel} is refused: the waiver and its log are written only by "
                 f"_meta/brain gate waive, and only on the person's express say-so. No skill run opens this path.")


def _too_deep_refusal() -> Dict[str, Any]:
    return _deny(f"skill gate: this is {TOO_DEEP} ($(...) or <(...) inside one another), too deep for the gate "
                 f"to see what it writes, so it is refused. Split it into smaller commands, keeping intermediate "
                 f"results in variables or files; no real command nests that deep.")


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
    found, too_deep = _targets(payload, root)
    if too_deep:  # fail closed: what it writes cannot be seen, and no skill run or waiver changes that
        state_path = _state_path(root, _session_id(payload))
        _remember_refusal(state_path, _read_state(state_path), "", [], TOO_DEEP)
        return _too_deep_refusal()
    if not found:
        return None
    for rel, _exists in found:
        if rel in RESERVED:
            state_path = _state_path(root, _session_id(payload))
            _remember_refusal(state_path, _read_state(state_path), rel, [], _RESERVED_WHY)
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
        _verify_state_dir(_state_dir(root))
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
    if refusal and not refusal.get("skills") and refusal.get("why") not in (None, _RESERVED_WHY):
        lines.append(f"last refusal: {refusal['why']} ({refusal.get('time', '?')})")  # a command nested too deep
    elif refusal and not refusal.get("skills"):
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
