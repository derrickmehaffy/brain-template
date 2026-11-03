from __future__ import annotations

import os
import shutil
import unittest
from pathlib import Path

from tests.helpers import TempDirCase  # first: puts <template>/_meta on sys.path
from brainlib import config, lint, routing, skills
from brainlib.report import BROKEN, GAP

FENCE = "`" * 3
CALL = "**Call it directly when:**"
DOCS = "docs/ROUTING.md"
META = "_meta/ROUTING-META.md"


def fenced(*lines: str) -> str:
    """A mermaid fence around `lines`: the fence opener is the text's first line, `lines[0]` its second."""
    return "\n".join([FENCE + "mermaid", *lines, FENCE]) + "\n"


def parsed(text: str, file: str = DOCS) -> routing.Graph:
    graph = routing.Graph({}, [], {}, [])
    routing.parse(text, file, graph)
    return graph


def edge_tuples(graph: routing.Graph) -> list:
    return [(e.src, e.dst, e.sometimes, e.label) for e in graph.edges]


class ParseTest(unittest.TestCase):
    def test_parse_nodes_classes_edges(self):
        text = "# Map\n\n" + fenced(
            "flowchart LR",                                                        # line 4
            "  %% a comment",
            "  classDef entry fill:#eee,stroke:#333;",
            '  IN(user asks):::entry --> lab-router["Router [v2]"]:::work',        # line 7
            "  lab-router -.->|only sometimes| lab-b:::optional",
            "  lab-router --> KIND{kind}:::decision --> lab-a:::work",
        )
        g = parsed(text)
        self.assertEqual(g.problems, [])
        self.assertEqual({k: n.cls for k, n in g.nodes.items()},
                         {"IN": "entry", "lab-router": "work", "lab-b": "optional", "KIND": "decision",
                          "lab-a": "work"})
        self.assertEqual(g.nodes["lab-router"].label, "Router [v2]")  # a quoted label may hold brackets
        self.assertEqual(g.nodes["IN"].label, "user asks")
        self.assertEqual(g.nodes["lab-b"].label, "lab-b")  # no shape: the id is the label
        self.assertEqual((g.nodes["IN"].file, g.nodes["IN"].line), (DOCS, 7))
        self.assertEqual(edge_tuples(g), [
            ("IN", "lab-router", False, ""),
            ("lab-router", "lab-b", True, "only sometimes"),  # -.-> is a sometimes call
            ("lab-router", "KIND", False, ""),
            ("KIND", "lab-a", False, ""),
        ])
        self.assertEqual([(e.file, e.line) for e in g.edges], [(DOCS, 7), (DOCS, 8), (DOCS, 9), (DOCS, 9)])
        self.assertEqual(g.not_drawn, {})

    def test_every_shape_and_quoted_brackets(self):
        cases = {
            "A[x]": "x", "B(x)": "x", "C{x}": "x", "D[(x)]": "x", "E((x))": "x", "F{{x}}": "x", "G[[x]]": "x",
            'H["a ] b"]': "a ] b", 'I(("a )) b"))': "a )) b", 'J[("q)] r")]': "q)] r", 'K{"{x}"}': "{x}",
            "L[ spaced ]": "spaced",
        }
        for ref, label in cases.items():
            with self.subTest(ref=ref):
                g = parsed(fenced("flowchart TD", ref + ":::work"))
                self.assertEqual(g.problems, [])
                self.assertEqual((g.nodes[ref[0]].label, g.nodes[ref[0]].cls), (label, "work"))

    def test_arrows_without_spaces_and_chains(self):
        g = parsed(fenced("flowchart TD", "lab-a-->lab-b", "lab-b-.->lab-c", "A-->|x|B", "C --> |y| D",
                          "E --> F -.-> G", 'H -->|"when x"| I'))
        self.assertEqual(g.problems, [])
        self.assertEqual(edge_tuples(g), [
            ("lab-a", "lab-b", False, ""), ("lab-b", "lab-c", True, ""), ("A", "B", False, "x"),
            ("C", "D", False, "y"), ("E", "F", False, ""), ("F", "G", True, ""), ("H", "I", False, "when x"),
        ])

    def test_ids_may_contain_dashes_and_digits(self):
        g = parsed(fenced("graph TB", "lab-step-2 --> Gate_1-b"))
        self.assertEqual((g.problems, edge_tuples(g)), ([], [("lab-step-2", "Gate_1-b", False, "")]))

    def test_one_node_across_statements_merges(self):
        g = parsed(fenced("flowchart TD", "A[First]", "A:::gate", "B --> A[Second]"))
        self.assertEqual(g.problems, [])
        self.assertEqual((g.nodes["A"].cls, g.nodes["A"].label, g.nodes["A"].line), ("gate", "Second", 3))

    def test_unsupported_lines(self):
        for bad in ("A -- text --> B", "A ==> B", "A --- B", "A --> B;", "A & B --> C", "A --> B C", "subgraph X",
                    "end", "style A fill:#fff", "click A callback", "A[unclosed --> B", "A[x]]", "A:::", "A --> ",
                    "--> B", "A -->|unclosed B", "flowchart", "graph XX", 'A["x" y]', "A[]", "A --> B -- x --> C",
                    "1A --> B",
                    # a longer opener that does not close must not fall back to a shorter one with brackets
                    # or quotes left in the label; such a label has to be quoted
                    "A([x])", "A((x)", "A[[x]", "A[Foo (bar)]", 'A[say "hi" now]'):
            with self.subTest(line=bad):
                g = parsed(fenced("flowchart TD", bad))
                self.assertEqual([(f.severity, f.subject) for f in g.problems], [(BROKEN, f"{DOCS}:3")])
                self.assertTrue(g.problems[0].message.startswith("unsupported line"), g.problems[0].message)
                self.assertEqual((g.nodes, g.edges), ({}, []))  # nothing from a rejected line is kept

    def test_a_rejected_line_does_not_echo_its_text(self):
        secret = "gh" + "p_" + "a" * 36
        g = parsed(fenced("flowchart TD", f"A -- {secret} --> B"))
        self.assertEqual(len(g.problems), 1)
        self.assertNotIn(secret, g.problems[0].message)

    def test_unknown_and_conflicting_classes_are_problems(self):
        g = parsed(fenced("flowchart TD", "A:::foo", "B:::work", "B:::gate"))
        self.assertEqual([(f.severity, f.subject) for f in g.problems], [(BROKEN, f"{DOCS}:3"), (BROKEN, f"{DOCS}:5")])
        self.assertIn("foo", g.problems[0].message)
        self.assertIn("B", g.problems[1].message)
        self.assertEqual((g.nodes["A"].cls, g.nodes["B"].cls), ("foo", "work"))  # the first class is kept

    def test_only_mermaid_fences_outside_comments_are_read(self):
        bad = "A ==> B"  # no `-->`: that would end a comment around it
        good = fenced("flowchart TD", "A --> B")
        ignored = {
            "fence inside a comment": f"<!--\n{fenced('flowchart TD', bad)}-->\n",
            "fence opened on the comment line": f"<!-- {FENCE}mermaid\n{bad}\n{FENCE} -->\n",
            "other language": f"{FENCE}text\n{bad}\n{FENCE}\n",
            "no language": f"{FENCE}\n{bad}\n{FENCE}\n",
            "plain prose": f"{bad}\n",
            "inside a longer fence": f"````text\n{FENCE}mermaid\n{bad}\n{FENCE}\n````\n",
        }
        for label, text in ignored.items():
            with self.subTest(label):
                g = parsed(text)
                self.assertEqual((g.problems, g.nodes), ([], {}), label)
        read = {
            "after a one-line comment": "<!-- note -->\n" + good,
            "after a multi-line comment": "<!--\nnote\n-->\n" + good,
            "after a code block that opens a comment": f"{FENCE}html\n<!--\n{FENCE}\n" + good,
            "indented": "  " + good.replace("\n", "\n  ").rstrip(" "),
            "CRLF": good.replace("\n", "\r\n"),
            "byte order mark": "\ufeff" + good,
        }
        for label, text in read.items():
            with self.subTest(label):
                g = parsed(text)
                self.assertEqual((g.problems, sorted(g.nodes)), ([], ["A", "B"]), label)
        with self.subTest("a comment marker inside a mermaid fence is not a comment"):
            g = parsed(fenced("flowchart TD", "<!-- hi -->"))
            self.assertEqual([f.subject for f in g.problems], [f"{DOCS}:3"])

    def test_an_unclosed_comment_is_a_problem_at_its_opener(self):
        diagram = fenced("flowchart TD", "A:::work")  # no `-->`: that would close the comment around it
        cases = {
            "never closed": ("intro\n<!-- never closed\n" + diagram, 2),
            "closed, then another opened": ("<!-- one -->\ntext\n  <!-- two\n" + diagram, 3),
            "closed and reopened on one line": ("<!-- one\ntwo --> <!-- three\n" + diagram, 2),
            "opened at the very end": ("text <!--", 1),
        }
        for label, (text, line) in cases.items():
            with self.subTest(label):
                g = parsed(text)
                self.assertEqual([(f.severity, f.subject) for f in g.problems], [(BROKEN, f"{DOCS}:{line}")])
                self.assertEqual(g.problems[0].message, "unclosed '<!--' comment")
                self.assertEqual(g.nodes, {})  # what the comment swallowed is not read
        for label, text in {"closed": "<!-- a\nb -->\n" + diagram, "closed on its line": "<!-- a -->" + diagram,
                            "none": diagram}.items():
            with self.subTest(label):
                self.assertEqual(parsed(text).problems, [])

    def test_line_numbers_run_across_fences(self):
        text = fenced("flowchart TD", "A --> B") + "\ntext\n\n" + fenced("flowchart TD", "B --> C", "oops here")
        g = parsed(text)
        self.assertEqual([f.subject for f in g.problems], [f"{DOCS}:11"])
        self.assertEqual([(e.src, e.line) for e in g.edges], [("A", 3), ("B", 10)])

    def test_not_drawn_table(self):
        text = "\n".join([
            "# Map", "", "## Not drawn", "", "| Skill | Why |", "|---|---|",
            "| `lab-old` | Retired; kept for history |", "| `lab-pipe` | has a \\| in the reason |",
            "| not a skill row | x |", "", "## Other", "", "| `lab-other` | not under the heading |",
            "", "<!--", "## Not drawn", "| `lab-commented` | inside a comment |", "-->",
        ])
        self.assertEqual(parsed(text).not_drawn,
                         {"lab-old": "Retired; kept for history", "lab-pipe": "has a | in the reason"})


class GraphTest(unittest.TestCase):
    def test_is_skill_id(self):
        self.assertEqual([routing.is_skill_id(x) for x in ("lab-a", "brain-sync", "KIND", "IN", "")],
                         [True, True, False, False, False])

    def test_contract_walks_through_decisions(self):
        g = parsed(fenced(
            "flowchart TD",
            "IN(x):::entry --> lab-router:::work",
            "lab-router --> KIND{kind}:::decision",
            "KIND -->|a| lab-a:::work",
            "KIND -->|b| lab-b:::work",
            "KIND -->|c| lab-c:::work",
        ))
        up, down = routing.contract(g)
        self.assertEqual(down["lab-router"], {"lab-a", "lab-b", "lab-c"})
        self.assertEqual(up["lab-a"], {"lab-router"})
        self.assertEqual(up["lab-router"], set())  # an entry node is not a skill
        self.assertEqual(down["lab-a"], set())

    def test_contract_stops_at_the_next_skill(self):
        up, down = routing.contract(parsed(fenced("flowchart TD", "lab-a:::work --> lab-b:::work --> lab-c:::work")))
        self.assertEqual((down["lab-a"], up["lab-c"], up["lab-b"]), ({"lab-b"}, {"lab-b"}, {"lab-a"}))

    def test_contract_survives_cycles_among_other_nodes(self):
        g = parsed(fenced("flowchart TD", "lab-a:::work --> X{x}:::decision", "X --> Y{y}:::decision",
                          "Y --> X", "Y -.-> lab-b:::work", "X --> STORE[(notes)]:::state"))
        up, down = routing.contract(g)
        self.assertEqual((down["lab-a"], down["lab-b"], up["lab-b"]), ({"lab-b"}, set(), {"lab-a"}))

    def test_contract_drops_a_skill_calling_itself(self):
        # A retry loop is not a hand-on: neither through a decision nor directly.
        g = parsed(fenced("flowchart TD", "lab-a:::work --> OK{ok}:::decision -.-> lab-a", "OK --> lab-b:::work",
                          "lab-b --> lab-b", "lab-b --> lab-c:::work"))
        up, down = routing.contract(g)
        self.assertEqual((down["lab-a"], up["lab-a"]), ({"lab-b"}, set()))
        self.assertEqual((down["lab-b"], up["lab-b"]), ({"lab-c"}, {"lab-a"}))
        self.assertEqual((down["lab-c"], up["lab-c"]), (set(), {"lab-b"}))

    def test_reachable_from_entry_nodes(self):
        g = parsed(fenced(
            "flowchart TD",
            "IN(x):::entry --> lab-a:::work -.-> KIND{k}:::decision --> lab-b:::work",
            "lab-c:::work --> lab-a",
            "OTHER(y):::human --> lab-d:::work",
        ))
        self.assertEqual(routing.reachable(g), {"IN", "lab-a", "KIND", "lab-b"})


class RoutingCase(TempDirCase):
    def brain(self, docs=None, meta=None, names=(), call=None, **kwargs) -> Path:
        """A brain whose skills and maps are exactly the ones given: `names` get a call line, `docs` and
        `meta` are the Markdown of `docs/ROUTING.md` and `_meta/ROUTING-META.md`. Whatever `fake_brain`
        copied from the working tree (shipped brain-* skills, the shipped meta map) is removed first, so no
        test here depends on, or counts, a skill it did not create."""
        root = self.fake_brain(**kwargs)
        shutil.rmtree(str(root / ".claude" / "skills"), ignore_errors=True)
        shipped_meta_map = root / "_meta" / "ROUTING-META.md"
        if shipped_meta_map.exists():
            shipped_meta_map.unlink()
        if docs is not None:
            (root / "docs").mkdir(exist_ok=True)
            (root / "docs" / "ROUTING.md").write_text(docs, encoding="utf-8")
        if meta is not None:
            (root / "_meta" / "ROUTING-META.md").write_text(meta, encoding="utf-8")
        for name in names:
            self.skill(root, name, f"{CALL} when someone asks for {name} by name." if call is None else call)
        return root

    @staticmethod
    def skill(root: Path, name: str, body: str) -> Path:
        return TempDirCase.make_skill(root, name, "Does X. Use when Y.", body)

    @staticmethod
    def lint_routing(root: Path) -> list:
        return routing.lint_routing(root, config.load(root), skills.list_skills(root))

    @staticmethod
    def shape(findings) -> list:
        return [(f.severity, f.subject) for f in findings]


class LoadGraphTest(RoutingCase):
    def test_missing_maps_are_an_empty_map(self):
        root = self.brain()
        g = routing.load_graph(root)
        self.assertEqual((g.nodes, g.edges, g.not_drawn, g.problems), ({}, [], {}, []))
        self.assertEqual(self.lint_routing(root), [])

    def test_same_id_across_diagrams_joins(self):
        # The entry is in the first diagram; lab-a is reached only through the second.
        docs = fenced("flowchart TD", "IN(x):::entry --> lab-router:::work") + "\n" + \
            fenced("flowchart TD", "lab-router --> lab-a:::work")
        root = self.brain(docs=docs, names=("lab-router", "lab-a"))
        g = routing.load_graph(root)
        self.assertEqual(g.problems, [])
        self.assertEqual(g.nodes["lab-router"].line, 3)  # first appearance
        self.assertIn("lab-a", routing.reachable(g))
        self.assertEqual(self.lint_routing(root), [])

    def test_meta_and_brain_files_share_ids(self):
        # The template's map declares brain-retro; the brain's map hands on to it by id alone.
        meta = fenced("flowchart LR", "WRONG(a skill went wrong):::entry --> brain-retro:::work")
        docs = fenced("flowchart LR", "IN(go):::entry --> lab-x:::work", "lab-x --> brain-retro")
        root = self.brain(docs=docs, meta=meta, names=("lab-x", "brain-retro"))
        g = routing.load_graph(root)
        self.assertEqual((g.nodes["brain-retro"].file, g.nodes["brain-retro"].cls), (META, "work"))
        self.assertEqual(g.nodes["lab-x"].file, DOCS)
        up, down = routing.contract(g)
        self.assertEqual((down["lab-x"], up["brain-retro"]), ({"brain-retro"}, {"lab-x"}))
        self.assertEqual(self.lint_routing(root), [])

    def test_a_problem_names_the_file_it_is_in(self):
        root = self.brain(docs=fenced("flowchart TD", "A -- x --> B"), meta=fenced("flowchart TD", "C ==> D"))
        self.assertEqual([f.subject for f in routing.load_graph(root).problems], [f"{META}:3", f"{DOCS}:3"])

    def test_a_map_that_cannot_be_read_is_broken_not_empty(self):
        root = self.brain()
        (root / "docs" / "ROUTING.md").mkdir(parents=True)  # a directory where the map should be
        g = routing.load_graph(root)
        self.assertEqual(g.nodes, {})
        self.assertEqual([(f.severity, f.subject) for f in g.problems], [(BROKEN, DOCS)])
        self.assertTrue(g.problems[0].message.startswith("cannot read the routing map ("), g.problems[0].message)
        self.assertEqual(self.shape(self.lint_routing(root)), [(BROKEN, DOCS)])

    def test_a_map_without_read_permission_is_broken_not_empty(self):
        root = self.brain(docs=fenced("flowchart TD", "IN(x):::entry --> lab-a:::work"), names=("lab-a",))
        path = root / "docs" / "ROUTING.md"
        path.chmod(0)
        self.addCleanup(path.chmod, 0o644)
        if os.access(str(path), os.R_OK):
            self.skipTest("this user can read a mode 0 file (root)")
        # lab-a is undrawn too, since nothing could be read, but the BROKEN is what fails the run.
        self.assertEqual(self.shape(self.lint_routing(root)), [(BROKEN, DOCS), (GAP, "lab-a")])
        r = self.run_brain(root, "lint")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue(any(l.startswith(f"BROKEN {DOCS}: cannot read the routing map") for l in r.stdout.splitlines()),
                        r.stdout)

    def test_a_missing_map_is_still_an_empty_map(self):
        root = self.brain(docs=fenced("flowchart TD", "IN(x):::entry --> lab-a:::work"))
        self.assertEqual(routing.load_graph(root).problems, [])  # no _meta/ROUTING-META.md


class LintBrokenTest(RoutingCase):
    def test_lint_broken(self):
        entry = "IN(x):::entry --> lab-a:::work"
        cases = {
            "ghost lowercase node": (fenced("flowchart TD", entry, "lab-a --> lab-ghost:::work"), "lab-ghost", 4),
            "node never given a class": (fenced("flowchart TD", entry, "lab-a --> KIND{kind}"), "KIND", 4),
            "edge to a node never declared": (fenced("flowchart TD", entry, "lab-a --> Missing"), "Missing", 4),
            "unknown class": (fenced("flowchart TD", "IN(x):::entry --> lab-a:::foo"), "foo", 3),
            "conflicting classes": (fenced("flowchart TD", entry, "lab-a:::gate"), "conflict", 4),
            "edge text the dialect does not have": (fenced("flowchart TD", entry, "lab-a -- text --> B"),
                                                   "unsupported line", 4),
        }
        for label, (docs, fragment, line) in cases.items():
            with self.subTest(label):
                root = self.brain(docs=docs, names=("lab-a",))
                found = self.lint_routing(root)
                self.assertEqual(self.shape(found), [(BROKEN, f"{DOCS}:{line}")], found)
                self.assertIn(fragment, found[0].message)

    def test_a_fence_inside_an_html_comment_is_ignored(self):
        bad = fenced("flowchart TD", "lab-ghost ==> Nowhere")
        root = self.brain(docs=f"<!--\n{bad}-->\n" + fenced("flowchart TD", "IN(x):::entry --> lab-a:::work"),
                          names=("lab-a",))
        self.assertEqual(self.lint_routing(root), [])

    def test_an_unclosed_comment_is_reported_by_lint(self):
        docs = fenced("flowchart TD", "IN(x):::entry --> lab-a:::work") + "\n<!-- notes\n"
        found = self.lint_routing(self.brain(docs=docs, names=("lab-a",)))
        self.assertEqual(self.shape(found), [(BROKEN, f"{DOCS}:6")])
        self.assertIn("unclosed", found[0].message)

    def test_a_class_given_on_a_later_appearance_counts(self):
        docs = fenced("flowchart TD", "IN(x):::entry --> lab-a", "lab-a:::work")
        self.assertEqual(self.lint_routing(self.brain(docs=docs, names=("lab-a",))), [])

    def test_lowercase_node_is_checked_against_every_skill_not_only_owned_ones(self):
        docs = fenced("flowchart TD", "IN(x):::entry --> brain-retro:::work", "IN --> lab-gone:::work")
        root = self.brain(docs=docs, names=("brain-retro",))
        self.assertEqual(self.shape(self.lint_routing(root)), [(BROKEN, f"{DOCS}:4")])


class LintGapTest(RoutingCase):
    def test_lint_gap(self):
        docs = fenced("flowchart TD", "IN(x):::entry --> lab-a:::work", "lab-c:::work --> lab-a") + "\n".join([
            "", "## Not drawn", "", "| Skill | Why |", "|---|---|", "| `lab-d` | a helper nobody calls |", ""])
        root = self.brain(docs=docs, names=("lab-a", "lab-b", "lab-c", "lab-d"))
        found = self.lint_routing(root)
        # lab-b is undrawn; lab-c is drawn but no entry reaches it; lab-d is listed under Not drawn.
        self.assertEqual(self.shape(found), [(GAP, "lab-b"), (GAP, "lab-c")])
        self.assertIn("Not drawn", found[0].message)
        self.assertIn("entry", found[1].message)

    def test_an_empty_map_leaves_every_owned_skill_a_gap(self):
        root = self.brain(names=("lab-a",))
        self.assertEqual(self.shape(self.lint_routing(root)), [(GAP, "lab-a")])

    def test_gaps_apply_to_owned_skills_only(self):
        brain = self.brain(names=("lab-a", "brain-x"))
        self.assertEqual(self.shape(self.lint_routing(brain)), [(GAP, "lab-a")])
        template = self.brain(names=("template-a", "brain-x"), prefix="template", role="template")
        self.assertEqual(self.shape(self.lint_routing(template)), [(GAP, "brain-x"), (GAP, "template-a")])

    def test_a_clean_router_map_has_no_findings(self):
        docs = fenced(
            "flowchart LR",
            "IN(a request):::entry --> lab-router:::work",
            "lab-router --> KIND{kind}:::decision",
            "KIND -->|a| lab-a:::work",
            "KIND -->|b| lab-b:::gate",
            "KIND -.->|c| lab-c:::optional",
            "lab-a --> DONE(the person reads it):::human",
        )
        root = self.brain(docs=docs, names=("lab-router", "lab-a", "lab-b", "lab-c"))
        self.assertEqual(self.lint_routing(root), [])

    def test_call_directly_line(self):
        docs = fenced("flowchart TD", "IN(x):::entry --> lab-ok:::work", "IN --> lab-missing:::work",
                      "IN --> lab-todo:::work", "IN --> lab-empty:::work", "IN --> lab-next:::work")
        root = self.brain(docs=docs)
        self.skill(root, "lab-ok", f"Intro.\n\n{CALL} when the person names it.\n")
        self.skill(root, "lab-missing", "Intro.\n\nCall it whenever.\n")
        self.skill(root, "lab-todo", f"{CALL} TODO — say when someone should call this directly, and which "
                                     "earlier steps still apply.\n")
        self.skill(root, "lab-empty", f"{CALL}\n\n## Done when\n")
        self.skill(root, "lab-next", f"{CALL}\nwhen the person names it\n")
        found = self.lint_routing(root)
        self.assertEqual(self.shape(found), [(GAP, "lab-empty"), (GAP, "lab-missing"), (GAP, "lab-todo")])
        self.assertIn(CALL, found[1].message)
        self.assertIn("TODO", found[2].message)

    def test_call_line_is_not_needed_for_template_owned_skills_in_a_brain(self):
        root = self.brain(docs=fenced("flowchart TD", "IN(x):::entry --> brain-x:::work"))
        self.skill(root, "brain-x", "No call line here.\n")
        self.assertEqual(self.lint_routing(root), [])


class ShowTest(RoutingCase):
    MAP = fenced(
        "flowchart LR",
        "IN(a retro is needed):::entry --> lab-router:::work",
        "lab-router --> KIND{kind}:::decision",
        "KIND -->|a| lab-a:::work",
        "KIND -->|b| lab-b:::work",
        "KIND -->|c| lab-c:::work",
        "lab-a --> lab-d:::work",
        "lab-lonely:::work",
    ) + "\n## Not drawn\n\n| Skill | Why |\n|---|---|\n| `lab-aside` | used by hand only |\n"

    def setUp(self):
        super().setUp()
        self.root = self.brain(docs=self.MAP)

    def test_show(self):
        lines = routing.show(self.root, "lab-router").splitlines()
        self.assertIn("up: (entry)", lines)
        self.assertIn("down: lab-a, lab-b, lab-c", lines)
        self.assertEqual(lines[0], "lab-router (work)")
        lines = routing.show(self.root, "lab-a").splitlines()
        self.assertIn("up: lab-router", lines)
        self.assertIn("down: lab-d", lines)
        self.assertIn("down: (none)", routing.show(self.root, "lab-d").splitlines())

    def test_show_ignores_a_skill_calling_itself(self):
        root = self.brain(docs=fenced("flowchart TD", "IN(x):::entry --> lab-a:::work", "lab-a --> lab-a"))
        lines = routing.show(root, "lab-a").splitlines()
        self.assertIn("up: (entry)", lines)
        self.assertIn("down: (none)", lines)

    def test_show_without_a_skill_lists_entry_points_and_isolated_skills(self):
        lines = routing.show(self.root, None).splitlines()
        self.assertEqual(lines[0], "entry points:")
        self.assertIn("  IN: a retro is needed -> lab-router", lines)
        self.assertEqual(lines[lines.index("isolated skills:") + 1], "  lab-lonely")
        self.assertNotIn("  lab-a", lines)

    def test_show_on_an_empty_map(self):
        lines = routing.show(self.brain(), None).splitlines()
        self.assertEqual(lines, ["entry points:", "  (none)", "isolated skills:", "  (none)"])

    def test_command_prints_the_same(self):
        r = self.run_brain(self.root, "routing", "show", "lab-router")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertIn("up: (entry)", lines)
        self.assertIn("down: lab-a, lab-b, lab-c", lines)
        r = self.run_brain(self.root, "routing", "show")
        self.assertEqual((r.returncode, r.stdout.splitlines()[0]), (0, "entry points:"))

    def test_command_refuses_what_is_not_in_the_map(self):
        for name in ("lab-nope", "KIND"):
            with self.subTest(name):
                r = self.run_brain(self.root, "routing", "show", name)
                self.assertEqual((r.returncode, r.stdout), (1, ""))
                self.assertIn(name, r.stderr)

    def test_command_says_why_a_skill_is_not_drawn(self):
        r = self.run_brain(self.root, "routing", "show", "lab-aside")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("used by hand only", r.stdout)

    def test_routing_needs_a_subcommand(self):
        r = self.run_brain(self.root, "routing")
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage: brain routing", r.stderr)
        r = self.run_brain(self.root, "routing", "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("show", r.stdout)

    def test_routing_is_listed_in_help(self):
        r = self.run_brain(self.root, "--help")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(any(l.split()[:1] == ["routing"] for l in r.stdout.splitlines()), r.stdout)


class RegistrationTest(RoutingCase):
    def test_registered_with_lint(self):
        self.assertIn(routing.lint_routing, lint.EXTRA_CHECKS)

    def test_lint_command_reports_routing_findings(self):
        root = self.brain(docs=fenced("flowchart TD", "IN(x):::entry --> lab-a:::work", "lab-a -- x --> B"),
                          names=("lab-a",))
        r = self.run_brain(root, "lint")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue(any(l.startswith(f"BROKEN {DOCS}:4: unsupported line") for l in r.stdout.splitlines()),
                        r.stdout)

    def test_gaps_alone_do_not_fail_lint(self):
        root = self.brain(names=("lab-a",))
        r = self.run_brain(root, "lint")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(any(l.startswith("GAP    lab-a: ") and "routing map" in l for l in r.stdout.splitlines()),
                        r.stdout)


if __name__ == "__main__":
    unittest.main()
