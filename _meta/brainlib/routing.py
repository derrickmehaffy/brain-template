"""The routing map: parse the Mermaid in `_meta/ROUTING-META.md` and `docs/ROUTING.md` as one graph,
lint it, show it and (in `routing_sync`) write each skill's block from it (spec §7.7)."""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set, Tuple

from . import config, paths
from .config import Config
from .report import BLOCK, BROKEN, GAP, OK, Finding, emit, exit_code
from .skills import Skill, owned_skills

CLASSES = ("entry", "gate", "work", "optional", "decision", "state", "human")
MAP_FILES = (("_meta", "ROUTING-META.md"), ("docs", "ROUTING.md"))  # read in this order, as one graph
CALL = "**Call it directly when:**"


@dataclass
class Node:
    id: str
    cls: str  # "" until some appearance gives the node a class
    label: str  # the text inside its shape, else the id
    file: str
    line: int  # where the node first appears


@dataclass
class Edge:
    src: str
    dst: str
    sometimes: bool  # `-.->`: a call that happens only sometimes
    label: str
    file: str
    line: int


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: List[Edge] = field(default_factory=list)
    not_drawn: dict[str, str] = field(default_factory=dict)  # skill -> why it is deliberately not drawn
    problems: List[Finding] = field(default_factory=list)  # what `parse` could not accept
    declared: Set[str] = field(default_factory=set)  # ids that some appearance gave a shape or a class


# -- the scanner -------------------------------------------------------------------
#
# One line of a fence holds one statement. It is read by hand, not by one pattern, so that a
# bracket inside a quoted label, `a-->b` with no spaces and a stray token each behave.

_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_NAME_CHARS = _LETTERS + "0123456789_-"
_ARROWS = (("-.->", True), ("-->", False))  # (text, sometimes)
# Longest opener first, so `[(x)]` is a cylinder and not a `[` around `(x)`.
_SHAPES = (("[(", ")]"), ("((", "))"), ("{{", "}}"), ("[[", "]]"), ("[", "]"), ("(", ")"), ("{", "}"))
_RESERVED = frozenset(("end", "subgraph", "style", "class", "classDef", "click", "linkStyle", "direction",
                       "flowchart", "graph"))  # words Mermaid reads before it reads an id
_LABEL_BARRED = "[](){}\""  # not allowed in an unquoted label
_HEADER = re.compile(r"(?:flowchart|graph)[ \t]+(?:TB|TD|BT|RL|LR)")
_CLASSDEF = re.compile(r"classDef[ \t]+[A-Za-z][A-Za-z0-9_,-]*[ \t]+\S")
_FENCE_OPEN = re.compile(r"[ \t]*(`{3,})[ \t]*([^`\s]*)[^`]*")
_FENCE_CLOSE = re.compile(r"[ \t]*(`{3,})[ \t]*")
_HEADING = re.compile(r"#{1,6}[ \t]+(.*?)[ \t#]*")


class _Unsupported(Exception):
    """A line outside the dialect; the text says what was expected."""


@dataclass
class _Ref:
    id: str
    label: Optional[str]  # None when the reference has no shape
    cls: Optional[str]


def _skip(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t":
        i += 1
    return i


def _scan_name(s: str, i: int, what: str) -> Tuple[str, int]:
    """An id or a class name at `s[i]`. Dashes belong to a name, so the dashes of an arrow stuck to
    its end (`a-->b`, `a-.->b`) are given back."""
    if i >= len(s) or s[i] not in _LETTERS:
        raise _Unsupported(f"expected {what}")
    end = i + 1
    while end < len(s) and s[end] in _NAME_CHARS:
        end += 1
    dashes = end
    while dashes > i + 1 and s[dashes - 1] == "-":
        dashes -= 1
    for at in range(dashes, end):
        if any(s.startswith(arrow, at) for arrow, _ in _ARROWS):
            end = at
            break
    return s[i:end], end


def _scan_shape(s: str, i: int) -> Tuple[Optional[str], int]:
    """The label of the shape at `s[i]` and where it ends; (None, i) when there is no shape."""
    for opener, closer in _SHAPES:
        if not s.startswith(opener, i):
            continue
        start = _skip(s, i + len(opener))
        if s.startswith('"', start):  # a quoted label may hold brackets
            quote_end = s.find('"', start + 1)
            if quote_end < 0:
                continue
            label = s[start + 1:quote_end]
            close_at = _skip(s, quote_end + 1)
            if not s.startswith(closer, close_at):
                continue
        else:
            close_at = s.find(closer, start)
            if close_at < 0:
                continue
            label = s[start:close_at].strip()
            if any(c in label for c in _LABEL_BARRED):  # brackets and quotes mean quoting, or a malformed shape
                continue
        if label.strip():
            return label.strip(), close_at + len(closer)
    if i < len(s) and s[i] in "[({":
        raise _Unsupported("a node shape that is not closed, has no label, or has brackets or quotes in an "
                           "unquoted label (quote the label)")
    return None, i


def _scan_ref(s: str, i: int) -> Tuple[_Ref, int]:
    name, i = _scan_name(s, i, "a node id")
    if name in _RESERVED:
        raise _Unsupported(f"'{name}' is a Mermaid keyword, not a node id")
    label, i = _scan_shape(s, i)
    cls = None
    if s.startswith(":::", i):
        cls, i = _scan_name(s, i + 3, "a class name after ':::'")
    return _Ref(name, label, cls), i


def _scan_statement(s: str) -> Tuple[List[_Ref], List[Tuple[bool, str]]]:
    """`ref (ARROW [|label|] ref)*`: the references, and the (sometimes, label) of each arrow between them."""
    ref, i = _scan_ref(s, 0)
    refs, links = [ref], []
    i = _skip(s, i)
    while i < len(s):
        arrow = next((a for a in _ARROWS if s.startswith(a[0], i)), None)
        if arrow is None:
            raise _Unsupported("expected '-->' or '-.->' between nodes")
        i = _skip(s, i + len(arrow[0]))
        label = ""
        if s.startswith("|", i):
            end = s.find("|", i + 1)
            if end < 0:
                raise _Unsupported("an arrow label that is not closed")
            label = s[i + 1:end].strip().strip('"').strip()
            i = _skip(s, end + 1)
        ref, i = _scan_ref(s, i)
        refs.append(ref)
        links.append((arrow[1], label))
        i = _skip(s, i)
    return refs, links


# -- parse -------------------------------------------------------------------------


def _add_ref(graph: Graph, ref: _Ref, file: str, line: int) -> None:
    node = graph.nodes.get(ref.id)
    if node is None:
        node = graph.nodes[ref.id] = Node(ref.id, "", ref.id, file, line)
    if ref.label is not None:
        node.label = ref.label
        graph.declared.add(ref.id)
    if ref.cls is None:
        return
    graph.declared.add(ref.id)
    where = f"{file}:{line}"
    if ref.cls not in CLASSES:
        graph.problems.append(Finding(BROKEN, where, f"unknown class '{ref.cls}' on {ref.id} "
                                                     f"(use one of {', '.join(CLASSES)})"))
    if not node.cls:
        node.cls = ref.cls
    elif node.cls != ref.cls:
        graph.problems.append(Finding(BROKEN, where, f"conflicting class on {ref.id}: '{ref.cls}' here, "
                                                     f"'{node.cls}' elsewhere (it first appears at "
                                                     f"{node.file}:{node.line}); a node has one class"))


def _read_diagram_line(graph: Graph, file: str, number: int, raw: str) -> None:
    line = raw.strip()
    if not line or line.startswith("%%") or _HEADER.fullmatch(line) or _CLASSDEF.match(line):
        return
    try:
        refs, links = _scan_statement(line)
    except _Unsupported as why:  # the line's text is not echoed: findings name a place, not content
        graph.problems.append(Finding(BROKEN, f"{file}:{number}", f"unsupported line: {why}"))
        return
    for ref in refs:
        _add_ref(graph, ref, file, number)
    for src, dst, (sometimes, label) in zip(refs, refs[1:], links):
        graph.edges.append(Edge(src.id, dst.id, sometimes, label, file, number))


def _strip_comments(line: str, in_comment: bool) -> Tuple[str, bool, bool]:
    """`line` without its `<!-- … -->` text, whether a comment is still open at its end, and whether the
    open one began on this line."""
    visible, i, opened = [], 0, False
    while i < len(line):
        if in_comment:
            end = line.find("-->", i)
            if end < 0:
                break
            i, in_comment, opened = end + 3, False, False
        else:
            start = line.find("<!--", i)
            if start < 0:
                visible.append(line[i:])
                break
            visible.append(line[i:start])
            i, in_comment, opened = start + 4, True, True
    return "".join(visible), in_comment, opened and in_comment


def _read_not_drawn_row(graph: Graph, line: str) -> None:
    if not line.lstrip().startswith("|"):
        return
    cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
    named = re.search(r"`([^`]+)`", cells[0])
    if named:  # the header and `---` rows name no skill
        graph.not_drawn[named.group(1)] = "|".join(cells[1:]).replace("\\|", "|").strip()


def parse(text: str, file: str, graph: Graph) -> None:
    """Add what `text` (the Markdown of `file`) draws to `graph`: the nodes and edges of its
    ```mermaid fences, and the table under `## Not drawn`. A line the dialect does not allow becomes a
    BROKEN finding in `graph.problems` and adds nothing, so one slip is one finding."""
    fence: Optional[Tuple[int, bool]] = None  # (backticks that opened it, whether it is mermaid)
    in_comment, comment_line = False, 0
    section = ""
    text = text[1:] if text.startswith("\ufeff") else text
    for number, raw in enumerate(text.split("\n"), 1):  # not splitlines(): numbers must match an editor's
        raw = raw.rstrip("\r")
        if fence is not None:
            closing = _FENCE_CLOSE.fullmatch(raw)
            if closing and len(closing.group(1)) >= fence[0]:
                fence = None
            elif fence[1]:
                _read_diagram_line(graph, file, number, raw)
            continue
        line, in_comment, opened = _strip_comments(raw, in_comment)
        if opened:
            comment_line = number
        opening = _FENCE_OPEN.fullmatch(line)
        if opening:
            fence = (len(opening.group(1)), opening.group(2) == "mermaid")
            continue
        heading = _HEADING.fullmatch(line.strip())
        if heading:
            section = heading.group(1).strip().lower()
        elif section == "not drawn":
            _read_not_drawn_row(graph, line)
    if in_comment:  # everything after the opener was swallowed, so say where it began
        graph.problems.append(Finding(BROKEN, f"{file}:{comment_line}", "unclosed '<!--' comment"))


def load_graph(root: Path) -> Graph:
    """The graph of `_meta/ROUTING-META.md` then `docs/ROUTING.md`. A missing file is an empty map; a file
    that exists but cannot be read is a BROKEN problem, not an empty map."""
    graph = Graph()
    for parts in MAP_FILES:
        name = "/".join(parts)
        try:
            text = Path(root).joinpath(*parts).read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            continue
        except OSError as why:
            graph.problems.append(Finding(BROKEN, name, f"cannot read the routing map ({why.strerror or why})"))
            continue
        parse(text, name, graph)
    return graph


# -- the graph ---------------------------------------------------------------------


def is_skill_id(node_id: str) -> bool:
    """A node whose id starts lowercase is a skill, and its id is the skill's name."""
    return node_id[:1].islower()


def _successors(graph: Graph) -> dict[str, List[str]]:
    found: dict[str, List[str]] = {}
    for edge in graph.edges:
        found.setdefault(edge.src, []).append(edge.dst)
    return found


def _skills_after(start: str, successors: dict[str, List[str]]) -> Set[str]:
    """The skills a call from `start` lands on, walking through nodes that are not skills."""
    found: Set[str] = set()
    seen, todo = {start}, [start]
    while todo:
        for dst in successors.get(todo.pop(), ()):
            if is_skill_id(dst):
                found.add(dst)
            elif dst not in seen:
                seen.add(dst)
                todo.append(dst)
    return found


def contract(graph: Graph) -> Tuple[dict[str, Set[str]], dict[str, Set[str]]]:
    """(up, down): for each skill the skills that hand to it and the skills it hands to, walking through
    decisions, entries and every other node that is not a skill. Every skill node has an entry. A skill
    never appears in its own sets: a call that loops back to the caller is a retry, not a hand-on."""
    successors = _successors(graph)
    down = {n: _skills_after(n, successors) - {n} for n in graph.nodes if is_skill_id(n)}  # a retry is no hand-on
    up: dict[str, Set[str]] = {n: set() for n in down}
    for skill, below in down.items():
        for target in below:
            up[target].add(skill)
    return up, down


def reachable(graph: Graph) -> Set[str]:
    """Every node id an `entry` node leads to, the entry nodes included."""
    successors = _successors(graph)
    seen = {n.id for n in graph.nodes.values() if n.cls == "entry"}
    todo = list(seen)
    while todo:
        for dst in successors.get(todo.pop(), ()):
            if dst not in seen:
                seen.add(dst)
                todo.append(dst)
    return seen


def _entry_skills(graph: Graph) -> Set[str]:
    """The skills an entry node hands to directly (through nodes that are not skills)."""
    successors = _successors(graph)
    found: Set[str] = set()
    for node in graph.nodes.values():
        if node.cls == "entry":
            found |= _skills_after(node.id, successors) | ({node.id} if is_skill_id(node.id) else set())
    return found


# -- lint --------------------------------------------------------------------------

_CALL_LINE = re.compile(r"^[ \t>]*" + re.escape(CALL) + r"[ \t]*(.*)$", re.MULTILINE)
_TODO = re.compile(r"\W*TODO\b")


def _call_line(body: str) -> str:
    """`missing`, `todo` (empty, or still reading TODO) or `ok` for a skill's call-directly line."""
    found = _CALL_LINE.search(body)
    if not found:
        return "missing"
    text = found.group(1).strip()
    if not text:  # the sentence may start on the next line
        following = [ln.strip() for ln in body[found.end():].split("\n") if ln.strip()][:1]
        text = following[0] if following and not following[0].startswith("#") else ""
    return "todo" if not text or _TODO.match(text) else "ok"


def _node_findings(graph: Graph, names: Set[str]) -> List[Finding]:
    in_an_edge = {e.src for e in graph.edges} | {e.dst for e in graph.edges}
    found = []
    for node in graph.nodes.values():
        where = f"{node.file}:{node.line}"
        if is_skill_id(node.id) and node.id not in names:
            found.append(Finding(BROKEN, where, f"lowercase node '{node.id}' is not a skill; a skill's node id "
                                                f"is its name, and anything else starts with a capital letter"))
        if node.cls:
            continue
        if node.id not in graph.declared and node.id in in_an_edge:
            found.append(Finding(BROKEN, where, f"edge to '{node.id}', which is never declared; give it a "
                                                f"label and a class where it first appears"))
        else:
            found.append(Finding(BROKEN, where, f"node '{node.id}' has no class; add one of "
                                                f"{', '.join(CLASSES)} (for example ':::work')"))
    return found


def _skill_findings(graph: Graph, cfg: Config, skills: List[Skill]) -> List[Finding]:
    reach = reachable(graph)
    found = []
    for skill in owned_skills(cfg, skills):
        if skill.name not in graph.not_drawn:  # listed there on purpose: neither undrawn nor unreachable
            if skill.name not in graph.nodes:
                found.append(Finding(GAP, skill.name, "is not in the routing map; draw it, or list it under "
                                                      "'## Not drawn' with the reason"))
            elif skill.name not in reach:
                found.append(Finding(GAP, skill.name, "is in the routing map but no entry node reaches it"))
        state = _call_line(skill.body)
        if state == "missing":
            found.append(Finding(GAP, skill.name, f"has no '{CALL}' line"))
        elif state == "todo":
            found.append(Finding(GAP, skill.name, f"'{CALL}' line still reads TODO"))
    return found


def lint_routing(root: Path, cfg: Config, skills: List[Skill]) -> List[Finding]:
    """The routing-map checks of spec §7.7. BROKEN: a line outside the dialect, a lowercase node that is
    not a skill, a node with no class, an unknown class, two classes, an edge to a node never declared.
    GAP, for the skills this brain owns: not drawn and not under `## Not drawn`, no entry node reaches
    it, no call-directly line or one still reading TODO."""
    graph = load_graph(root)
    names = {s.name for s in skills}
    return graph.problems + _node_findings(graph, names) + _skill_findings(graph, cfg, skills)


# -- show --------------------------------------------------------------------------


def _list(names) -> str:
    return ", ".join(sorted(names)) or "(none)"


def _overview(graph: Graph) -> str:
    successors = _successors(graph)
    up, down = contract(graph)
    entry_skills = _entry_skills(graph)
    entries = []
    for node in graph.nodes.values():
        if node.cls == "entry":
            what = node.id if node.label == node.id else f"{node.id}: {node.label}"
            entries.append(f"  {what} -> {_list(_skills_after(node.id, successors))}")
    isolated = [s for s in down if not up[s] and not down[s] and s not in entry_skills]
    return "\n".join(["entry points:", *(entries or ["  (none)"]),
                      "isolated skills:", *(["  " + s for s in isolated] or ["  (none)"])])


def _describe(graph: Graph, skill: Optional[str]) -> Tuple[str, bool]:
    """(the text `show` prints, whether `skill` was found)."""
    if skill is None:
        return _overview(graph), True
    node = graph.nodes.get(skill)
    if node is None and skill in graph.not_drawn:
        return f"{skill} is not drawn: {graph.not_drawn[skill] or 'no reason given'}", True
    if node is None:
        return f"{skill} is not in the routing map", False
    if not is_skill_id(skill):
        return f"{skill} is not a skill (it is a '{node.cls}' node)", False
    up, down = contract(graph)
    before = (["(entry)"] if skill in _entry_skills(graph) else []) + sorted(up[skill])
    return "\n".join([f"{skill} ({node.cls or 'no class'})", f"up: {', '.join(before) or '(none)'}",
                      f"down: {_list(down[skill])}"]), True


def show(root: Path, skill: Optional[str]) -> str:
    """Without `skill`: the entry points and the isolated skills. With one: what hands to it (`up`, with
    `(entry)` when an entry node does) and what it hands to (`down`), both resolved through non-skill nodes."""
    return _describe(load_graph(root), skill)[0]


# -- the command -------------------------------------------------------------------


def _show_arguments(parser) -> None:
    parser.add_argument("skill", nargs="?", help="a skill to print the neighbours of "
                                                 "(without one: the entry points and isolated skills)")


def _run_show(args) -> int:
    text, found = _describe(load_graph(paths.harness_root()), args.skill)
    if found:
        print(text)
        return 0
    print(f"routing: {text}", file=sys.stderr)
    return 1


def _sync_arguments(parser) -> None:
    parser.add_argument("--check", action="store_true",
                        help="write nothing; exit 1 when a block or a style line is out of date")


def _run_sync(args) -> int:
    from . import routing_sync  # imported here: it imports this module

    root = paths.harness_root()
    try:
        cfg = config.load(root)
    except config.ConfigError as exc:
        print(f"routing: {exc}", file=sys.stderr)
        return 1
    refused: List[Finding] = []
    returned = routing_sync.sync(root, cfg, args.check, refused)
    # with --check the result also names the files that could not be confirmed current; those are reported
    # once, as the BROKEN findings in `refused`, not again as out of date
    not_current = set(routing_sync.refused_paths(refused))
    changed = [rel for rel in returned if rel not in not_current]
    if args.check:
        findings = [Finding(BLOCK, rel, "is out of date; run '_meta/brain routing sync'") for rel in changed]
    else:
        findings = [Finding(OK, rel, "updated") for rel in changed]
    emit(findings + refused)
    counts = ([f"{len(changed)} {'out of date' if args.check else 'updated'}"] if changed else []) + \
             ([f"{len(refused)} problem{'' if len(refused) == 1 else 's'}"] if refused else [])
    print("routing sync: " + (", ".join(counts) or ("everything is up to date" if args.check else "nothing to update")))
    return exit_code(findings + refused)


# name -> (help, add_arguments(parser), run(args) -> int). A new subcommand is one more entry.
SUBCOMMANDS = {
    "show": ("print entry points and isolated skills, or one skill's neighbours", _show_arguments, _run_show),
    "sync": ("write each skill's 'Where this sits' block and the map's style lines", _sync_arguments, _run_sync),
}


def add_arguments(parser) -> None:
    sub = parser.add_subparsers(dest="routing_command", metavar="<subcommand>", required=True)
    for name, (help_text, add, _run) in SUBCOMMANDS.items():
        add(sub.add_parser(name, help=help_text, description=help_text))


def run(args) -> int:
    return int(SUBCOMMANDS[args.routing_command][2](args))
