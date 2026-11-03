from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from tests.helpers import TempDirCase  # first: puts <template>/_meta on sys.path
from brainlib import config, lint, route
from brainlib.report import BROKEN
from brainlib.skills import list_skills

SKILLS = {"lab-build-block", "lab-write-script", "lab-check-api", "lab-plain-script", "lab-fallback", "brain-retro"}


def rules_file() -> dict:
    """Three rules whose conditions overlap, a default and two cases; every skill it names is in SKILLS."""
    return {
        "default": "lab-fallback",
        "rules": [
            {"when": {"kind": ["block", "model"]}, "skill": "lab-build-block", "why": "blocks are built"},
            {"when": {"kind": ["script"], "title~": ["api"]}, "skill": "lab-write-script",
             "also": ["lab-check-api"], "why": "api scripts want the docs check"},
            {"when": {"kind": ["script"]}, "skill": "lab-plain-script", "why": "any other script"},
        ],
        "cases": [
            {"input": {"kind": "block"}, "expect": "lab-build-block"},
            {"input": {"kind": "script", "title": "Add an API call"}, "expect": "lab-write-script"},
        ],
    }


class BareBrainCase(TempDirCase):
    def bare_brain(self) -> Path:
        """A fake brain holding no `brain-*` skill and no router: `fake_brain` copies the shipped ones, which
        would make a test depend on what the template ships (a `brain-retro`, a router with a `rules.json`)."""
        root = self.fake_brain()
        for folder in (root / ".claude" / "skills").glob("brain-*"):
            shutil.rmtree(str(folder), ignore_errors=True)
        return root


def fields(**kwargs) -> dict:
    """`fields(kind="a")` -> {"kind": ["a"]}; a list value stays a list."""
    return {k: v if isinstance(v, list) else [v] for k, v in kwargs.items()}


class RouteTest(unittest.TestCase):
    def test_first_match_wins(self):
        rules = {"rules": [
            {"when": {"kind": ["script"]}, "skill": "lab-first", "why": "first"},
            {"when": {"kind": ["script"], "title~": ["api"]}, "skill": "lab-second", "why": "second"},
        ]}
        got = route.route(rules, fields(kind="script", title="api"))
        self.assertEqual((got["skill"], got["rule"], got["why"]), ("lab-first", 1, "first"))
        # Rule numbers are 1-based positions in the list, not counts of matches.
        got = route.route(rules, fields(kind="other", title="x"))
        self.assertEqual(got["rule"], "default")
        later = {"rules": [{"when": {"kind": ["a"]}, "skill": "s1", "why": "w"},
                           {"when": {"kind": ["b"]}, "skill": "s2", "why": "w"}]}
        self.assertEqual(route.route(later, fields(kind="b"))["rule"], 2)

    def test_all_conditions_must_hold(self):
        rules = rules_file()
        self.assertEqual(route.route(rules, fields(kind="script", title="Add an API call"))["skill"],
                         "lab-write-script")
        # kind holds but the title condition of rule 2 does not: rule 3 answers.
        got = route.route(rules, fields(kind="script", title="Tidy the cache"))
        self.assertEqual((got["skill"], got["rule"]), ("lab-plain-script", 3))
        # The title would hold but the kind does not: nothing matches.
        got = route.route(rules, fields(kind="note", title="Add an API call"))
        self.assertEqual((got["skill"], got["rule"]), ("lab-fallback", "default"))

    def test_case_insensitive_exact(self):
        rules = {"rules": [{"when": {"kind": ["Block"]}, "skill": "lab-build-block", "why": "w"}]}
        for value in ("block", "BLOCK", "  Block \t"):
            self.assertEqual(route.route(rules, fields(kind=value))["rule"], 1, repr(value))
        padded = {"rules": [{"when": {"kind": [" BLOCK  "]}, "skill": "lab-build-block", "why": "w"}]}
        self.assertEqual(route.route(padded, fields(kind="block"))["rule"], 1)
        # Exact means exact: a longer or shorter word is a different value.
        for value in ("blocks", "bloc", "a block", ""):
            self.assertEqual(route.route(rules, fields(kind=value))["rule"], "default", repr(value))

    def test_tilde_substring(self):
        rules = {"rules": [{"when": {"title~": ["API", "Rate Limit"]}, "skill": "lab-check-api", "why": "w"}]}
        for title in ("add an api call", "Fix the RATE LIMIT bug", "rapid", "API"):
            self.assertEqual(route.route(rules, fields(title=title))["rule"], 1, title)
        self.assertEqual(route.route(rules, fields(title="Tidy the cache"))["rule"], "default")
        # `title~` reads the input field `title`; an exact `title` condition still means the whole value.
        exact = {"rules": [{"when": {"title": ["api"]}, "skill": "lab-check-api", "why": "w"}]}
        self.assertEqual(route.route(exact, fields(title="add an api call"))["rule"], "default")

    def test_repeated_set_any_match(self):
        # Several values for one field: any of them may satisfy the condition.
        rules = {"rules": [{"when": {"kind": ["b"]}, "skill": "lab-build-block", "why": "w"}]}
        self.assertEqual(route.route(rules, {"kind": ["a", "b"]})["rule"], 1)
        self.assertEqual(route.route(rules, {"kind": ["a", "c"]})["rule"], "default")
        tilde = {"rules": [{"when": {"title~": ["api"]}, "skill": "lab-check-api", "why": "w"}]}
        self.assertEqual(route.route(tilde, {"title": ["x", "an API"]})["rule"], 1)

    def test_missing_field_fails(self):
        rules = {"rules": [
            {"when": {"repo": ["core"]}, "skill": "s1", "why": "w"},
            {"when": {"note~": ["x"]}, "skill": "s2", "why": "w"},
            {"when": {"kind": ["a"], "repo": ["core"]}, "skill": "s3", "why": "w"},
        ]}
        self.assertEqual(route.route(rules, fields(kind="a"))["rule"], "default")
        self.assertEqual(route.route(rules, {})["rule"], "default")
        self.assertEqual(route.route(rules, {"repo": []})["rule"], "default")

    def test_default_and_fallback_to_brain_retro(self):
        got = route.route(rules_file(), fields(kind="note"))
        self.assertEqual((got["skill"], got["rule"], got["also"]), ("lab-fallback", "default", []))
        self.assertTrue(got["why"])
        got = route.route({"rules": []}, fields(kind="note"))
        self.assertEqual((got["skill"], got["rule"]), ("brain-retro", "default"))
        self.assertEqual(route.DEFAULT_SKILL, "brain-retro")

    def test_result_carries_also_and_why(self):
        got = route.route(rules_file(), fields(kind="script", title="api"))
        self.assertEqual(got, {"skill": "lab-write-script", "rule": 2, "also": ["lab-check-api"],
                               "why": "api scripts want the docs check"})
        # `also` is optional and the answer never aliases the rules' own list.
        self.assertEqual(route.route(rules_file(), fields(kind="block"))["also"], [])
        rules = rules_file()
        got = route.route(rules, fields(kind="script", title="api"))
        got["also"].append("x")
        self.assertEqual(rules["rules"][1]["also"], ["lab-check-api"])

    def test_a_rule_it_cannot_read_is_an_error_not_a_skip(self):
        for bad in ("not an object", {"skill": "s", "why": "w"}, {"when": [], "skill": "s", "why": "w"},
                    {"when": {"kind": ["a"]}, "why": "w"}):
            with self.assertRaises(route.RulesError, msg=repr(bad)):
                route.route({"rules": [bad]}, fields(kind="a"))
        with self.assertRaises(route.RulesError):
            route.route([], {})
        with self.assertRaises(route.RulesError):
            route.route({"rules": "x"}, {})
        with self.assertRaises(route.RulesError):
            route.route({"default": 3, "rules": []}, {})
        # A broken rule after the match is never reached.
        late = {"rules": [{"when": {"kind": ["a"]}, "skill": "s", "why": "w"}, "junk"]}
        self.assertEqual(route.route(late, fields(kind="a"))["rule"], 1)

    def test_a_bare_string_is_one_value_not_a_list_of_letters(self):
        rules = {"rules": [{"when": {"title~": "api"}, "skill": "s", "why": "w"}]}
        self.assertEqual(route.route(rules, fields(title="x a y"))["rule"], "default")
        self.assertEqual(route.route(rules, fields(title="an api"))["rule"], 1)


class LoadRulesTest(BareBrainCase):
    def test_load_rules_reads_json_and_names_a_bad_file(self):
        good = self.tmp / "good.json"
        good.write_text(json.dumps(rules_file()), encoding="utf-8")
        self.assertEqual(route.load_rules(good), rules_file())
        bad = self.tmp / "bad.json"
        bad.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(route.RulesError) as caught:
            route.load_rules(bad)
        self.assertIn("bad.json", str(caught.exception))
        with self.assertRaises(route.RulesError):
            route.load_rules(self.tmp / "absent.json")
        latin = self.tmp / "latin.json"
        latin.write_bytes(b'{"default": "caf\xe9"}')
        with self.assertRaises(route.RulesError) as caught:
            route.load_rules(latin)
        self.assertIn("latin.json", str(caught.exception))
        bom = self.tmp / "bom.json"
        bom.write_bytes(b"\xef\xbb\xbf" + json.dumps({"rules": []}).encode("utf-8"))
        self.assertEqual(route.load_rules(bom), {"rules": []})

    def test_router_files_lists_each_routers_rules_json(self):
        root = self.bare_brain()
        for name in ("lab-b", "lab-a"):
            path = root / ".claude" / "skills" / name / "rules.json"
            path.parent.mkdir(parents=True)
            path.write_text("{}", encoding="utf-8")
        (root / ".claude" / "skills" / "lab-c").mkdir()
        (root / ".claude" / "skills" / "lab-d" / "references").mkdir(parents=True)
        (root / ".claude" / "skills" / "lab-d" / "references" / "rules.json").write_text("{}", encoding="utf-8")
        self.assertEqual([p.parent.name for p in route.router_files(root)], ["lab-a", "lab-b"])
        self.assertEqual(route.router_files(self.tmp / "nowhere"), [])


class CheckRulesTest(unittest.TestCase):
    def errors(self, rules, names=SKILLS):
        return route.check_rules(rules, set(names))

    def assert_one(self, errors, *fragments):
        self.assertEqual(len(errors), 1, errors)
        for fragment in fragments:
            self.assertIn(fragment, errors[0])

    def test_clean_file_has_no_errors(self):
        self.assertEqual(self.errors(rules_file()), [])

    def test_not_an_object_and_rules_not_a_list(self):
        for junk in ([], "x", 3, None):
            self.assert_one(self.errors(junk), "not a JSON object")
        self.assert_one(self.errors({"default": "lab-fallback"}), "'rules' must be a list")
        self.assert_one(self.errors({"rules": {"a": 1}}), "'rules' must be a list")

    def test_rule_without_when_skill_or_why(self):
        rules = rules_file()
        del rules["rules"][0]["when"]
        self.assert_one(self.errors(rules), "rule 1", "'when'")
        rules = rules_file()
        rules["rules"][0]["when"] = ["kind"]
        self.assert_one(self.errors(rules), "rule 1", "'when'")
        rules = rules_file()
        del rules["rules"][1]["skill"]
        self.assert_one(self.errors(rules), "rule 2", "'skill'")
        rules = rules_file()
        del rules["rules"][2]["why"]
        self.assert_one(self.errors(rules), "rule 3", "'why'")
        rules = rules_file()
        rules["rules"][2]["why"] = "  "
        self.assert_one(self.errors(rules), "rule 3", "'why'")
        rules = rules_file()
        rules["rules"].append("junk")
        self.assert_one(self.errors(rules), "rule 4", "not an object")

    def test_also_must_be_a_list_of_skill_names(self):
        rules = rules_file()
        rules["rules"][1]["also"] = "lab-check-api"
        self.assert_one(self.errors(rules), "rule 2", "'also' must be a list")
        rules["rules"][1]["also"] = ["lab-check-api", 4]
        self.assert_one(self.errors(rules), "rule 2", "'also'")

    def test_conditions_are_non_empty_lists_of_strings(self):
        for bad in ("script", [], [""], ["a", 3], None):
            rules = rules_file()
            rules["rules"][2]["when"]["kind"] = bad  # rule 3: no case reaches it, so only the shape is wrong
            self.assert_one(self.errors(rules), "rule 3", "'kind'")

    def test_missing_skills_are_named_wherever_they_occur(self):
        rules = rules_file()
        rules["rules"][0]["skill"] = "lab-ghost1"
        rules["rules"][1]["also"] = ["lab-check-api", "lab-ghost2"]
        rules["default"] = "lab-ghost3"
        rules["cases"][0]["expect"] = "lab-ghost4"
        errors = self.errors(rules)
        for ghost, where in (("lab-ghost1", "rule 1"), ("lab-ghost2", "rule 2"), ("lab-ghost3", "default"),
                             ("lab-ghost4", "case 1")):
            self.assertTrue(any(ghost in e and where in e and "does not exist" in e for e in errors),
                            (ghost, errors))

    def test_absent_default_needs_brain_retro(self):
        rules = rules_file()
        del rules["default"]
        self.assert_one(self.errors(rules, SKILLS - {"brain-retro"}), "default", "brain-retro", "does not exist")
        self.assertEqual(self.errors(rules), [])

    def test_failing_case_names_its_index_got_and_expected(self):
        rules = rules_file()
        rules["cases"][1]["expect"] = "lab-plain-script"
        self.assert_one(self.errors(rules), "case 2", "lab-write-script", "lab-plain-script")
        # An input value may be a string or a list of them, as --set repeated gives.
        rules = rules_file()
        rules["cases"] = [{"input": {"kind": ["note", "block"]}, "expect": "lab-build-block"}]
        self.assertEqual(self.errors(rules), [])

    def test_malformed_cases(self):
        rules = rules_file()
        rules["cases"] = {"input": {}}
        self.assert_one(self.errors(rules), "'cases' must be a list")
        for bad in ("x", {"input": {"kind": "block"}}, {"expect": "lab-build-block"},
                    {"input": [], "expect": "lab-build-block"}, {"input": {"kind": "block"}, "expect": 4}):
            rules = rules_file()
            rules["cases"] = [bad]
            self.assert_one(self.errors(rules), "case 1")

    def test_several_problems_are_all_reported(self):
        rules = rules_file()
        rules["rules"][2]["skill"] = "lab-ghost"
        del rules["rules"][1]["why"]
        rules["cases"][1]["expect"] = "lab-plain-script"
        errors = self.errors(rules)
        self.assertEqual(len(errors), 3, errors)
        self.assertTrue(any("rule 3" in e and "lab-ghost" in e for e in errors))
        self.assertTrue(any("rule 2" in e and "'why'" in e for e in errors))
        self.assertTrue(any("case 2" in e for e in errors))

    def test_a_case_that_reaches_a_missing_skill_fails_too(self):
        # Rule 1 now routes to a skill that is not there, so the case expecting the real one fails as well.
        rules = rules_file()
        rules["rules"][0]["skill"] = "lab-ghost"
        errors = self.errors(rules)
        self.assertEqual(len(errors), 2, errors)
        self.assertTrue(any("rule 1" in e and "lab-ghost" in e and "does not exist" in e for e in errors))
        self.assertTrue(any("case 1" in e and "lab-ghost" in e and "lab-build-block" in e for e in errors))


class RouteCommandTest(BareBrainCase):
    def brain_with_skills(self, names=("lab-build-block", "lab-write-script", "lab-check-api",
                                       "lab-plain-script", "lab-fallback", "brain-retro")) -> Path:
        root = self.bare_brain()  # the only skills are the ones named here, so `brain-retro` is there only if listed
        for name in names:
            self.make_skill(root, name, "Does X. Does NOT do Y, which is lab-fallback.", "body")
        return root

    def write_rules(self, where: Path, rules) -> Path:
        where.parent.mkdir(parents=True, exist_ok=True)
        where.write_text(json.dumps(rules, indent=2) + "\n", encoding="utf-8")
        return where

    def test_cli_prints_json(self):
        root = self.brain_with_skills()
        path = self.write_rules(self.tmp / "my rules" / "rules.json", rules_file())
        r = self.run_brain(root, "route", str(path), "--set", "kind=script", "--set", "title=Add an API call")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 1, r.stdout)
        got = json.loads(lines[0])
        self.assertEqual(list(got), ["skill", "rule", "also", "why"])
        self.assertEqual(got, {"skill": "lab-write-script", "rule": 2, "also": ["lab-check-api"],
                               "why": "api scripts want the docs check"})
        # Nothing matched: still exit 0, rule is the word "default".
        r = self.run_brain(root, "route", str(path), "--set", "kind=note")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual((got["skill"], got["rule"], got["also"]), ("lab-fallback", "default", []))
        # With no --set at all the input is empty and the default answers.
        r = self.run_brain(root, "route", str(path))
        self.assertEqual((r.returncode, json.loads(r.stdout)["rule"]), (0, "default"))

    def test_cli_repeated_set_gives_a_field_two_values(self):
        root = self.brain_with_skills()
        path = self.write_rules(self.tmp / "rules.json", rules_file())
        r = self.run_brain(root, "route", str(path), "--set", "kind=note", "--set", "kind=Block")
        self.assertEqual((r.returncode, json.loads(r.stdout)["rule"]), (0, 1), r.stderr)
        # The value is everything after the first '='.
        r = self.run_brain(root, "route", str(path), "--set", "kind=script", "--set", "title=a=b api")
        self.assertEqual((r.returncode, json.loads(r.stdout)["rule"]), (0, 2), r.stderr)

    def test_cli_set_usage_errors_exit_2(self):
        root = self.brain_with_skills()
        path = self.write_rules(self.tmp / "rules.json", rules_file())
        for bad in ("kind", "=block", "title~=api"):
            r = self.run_brain(root, "route", str(path), "--set", bad)
            self.assertEqual(r.returncode, 2, (bad, r.stderr))
            self.assertIn("--set", r.stderr)
        self.assertEqual(self.run_brain(root, "route").returncode, 2)

    def test_cli_refuses_an_unreadable_or_unusable_file(self):
        root = self.brain_with_skills()
        r = self.run_brain(root, "route", str(self.tmp / "absent.json"))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")
        self.assertIn("absent.json", r.stderr)
        bad = self.tmp / "bad.json"
        bad.write_text("{ nope", encoding="utf-8")
        r = self.run_brain(root, "route", str(bad))
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertIn("route:", r.stderr)
        self.assertIn("bad.json", r.stderr)
        for junk in ([], {"rules": [{"skill": "lab-build-block", "why": "w"}]}):
            path = self.write_rules(self.tmp / "junk.json", junk)
            r = self.run_brain(root, "route", str(path), "--set", "kind=block")
            self.assertEqual((r.returncode, r.stdout), (1, ""), junk)
            self.assertIn("route:", r.stderr)

    def test_router_name_resolves(self):
        root = self.brain_with_skills()
        self.make_skill(root, "lab-router", "Does X. Does NOT do Y, which is lab-fallback.", "body")
        self.write_rules(root / ".claude" / "skills" / "lab-router" / "rules.json", rules_file())
        # From a directory that is not the brain: the name is resolved under the brain holding _meta/.
        for argument in ("lab-router", "lab-router/rules.json"):
            r = self.run_brain(root, "route", argument, "--set", "kind=model", cwd=self.tmp)
            self.assertEqual(r.returncode, 0, (argument, r.stderr))
            got = json.loads(r.stdout)
            self.assertEqual((got["skill"], got["rule"]), ("lab-build-block", 1), argument)
        # A file that exists at the path given wins over a router of the same name.
        other = rules_file()
        other["default"] = "lab-plain-script"
        elsewhere = self.write_rules(self.tmp / "lab-router", other)
        r = self.run_brain(root, "route", "lab-router", "--set", "kind=note", cwd=self.tmp)
        self.assertEqual(json.loads(r.stdout)["skill"], "lab-plain-script", elsewhere)
        r = self.run_brain(root, "route", "no-such-router", "--set", "kind=note", cwd=self.tmp)
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertIn("no-such-router", r.stderr)

    def test_check_reports_missing_skill_failing_case_and_missing_why(self):
        root = self.brain_with_skills()
        rules = rules_file()
        rules["rules"][2]["skill"] = "lab-ghost"
        del rules["rules"][1]["why"]
        rules["cases"][1]["expect"] = "lab-plain-script"
        path = self.write_rules(self.tmp / "rules.json", rules)
        r = self.run_brain(root, "route", str(path), "--check")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        lines = r.stdout.splitlines()
        self.assertTrue(all(l.startswith("BROKEN ") for l in lines), r.stdout)
        self.assertEqual(len(lines), 3, r.stdout)
        self.assertTrue(any("rule 3" in l and "lab-ghost" in l and "does not exist" in l for l in lines))
        self.assertTrue(any("rule 2" in l and "'why'" in l for l in lines))
        self.assertTrue(any("case 2" in l and "lab-write-script" in l and "lab-plain-script" in l for l in lines))
        # --set is not used by --check.
        r = self.run_brain(root, "route", str(path), "--check", "--set", "kind=block")
        self.assertEqual(r.returncode, 1)

    def test_check_passes_a_clean_file_and_needs_the_default_skill(self):
        root = self.brain_with_skills()
        path = self.write_rules(self.tmp / "rules.json", rules_file())
        r = self.run_brain(root, "route", str(path), "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("ok"), r.stdout)
        # Without a default the answer is brain-retro, which must exist.
        bare = rules_file()
        del bare["default"]
        path = self.write_rules(self.tmp / "bare.json", bare)
        self.assertEqual(self.run_brain(root, "route", str(path), "--check").returncode, 0)
        lonely = self.bare_brain()  # no brain-retro, whatever the template ships
        for name in ("lab-build-block", "lab-write-script", "lab-check-api", "lab-plain-script"):
            self.make_skill(lonely, name, "Does X.", "body")
        r = self.run_brain(lonely, "route", str(path), "--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("brain-retro", r.stdout)

    def test_check_by_router_name_uses_the_router_as_subject(self):
        root = self.brain_with_skills()
        rules = rules_file()
        rules["default"] = "lab-ghost"
        self.write_rules(root / ".claude" / "skills" / "lab-router" / "rules.json", rules)
        r = self.run_brain(root, "route", "lab-router", "--check", cwd=self.tmp)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stdout.startswith("BROKEN lab-router: "), r.stdout)

    def test_check_on_invalid_json_exits_1(self):
        root = self.brain_with_skills()
        bad = self.tmp / "bad.json"
        bad.write_text("[1,", encoding="utf-8")
        r = self.run_brain(root, "route", str(bad), "--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("bad.json", r.stdout + r.stderr)


class LintRulesTest(BareBrainCase):
    def brain_with_router(self, rules) -> Path:
        root = self.bare_brain()
        for name in ("lab-build-block", "lab-write-script", "lab-check-api", "lab-plain-script", "lab-fallback"):
            self.make_skill(root, name, "Does X.", "body")
        self.make_skill(root, "lab-router", "Does X.", "body")
        path = root / ".claude" / "skills" / "lab-router" / "rules.json"
        path.write_text(rules if isinstance(rules, str) else json.dumps(rules), encoding="utf-8")
        return root

    def test_lint_rules_is_registered_with_lint(self):
        self.assertIn(route.lint_rules, lint.EXTRA_CHECKS)

    def test_lint_includes_rules_errors(self):
        rules = rules_file()
        rules["rules"][2]["skill"] = "lab-ghost"
        del rules["rules"][1]["why"]
        root = self.brain_with_router(rules)
        cfg = config.load(root)
        # Other checks may add findings under the same subject; this module's are the `rule N` / `case N` ones.
        found = lint.all_findings(root, cfg)
        mine = [f for f in found if f.subject == "lab-router" and f.severity == BROKEN
                and f.message.startswith(("rule ", "case "))]
        self.assertEqual(len(mine), 2, found)
        self.assertEqual(sorted(mine, key=lambda f: f.message),
                         sorted(route.lint_rules(root, cfg, list_skills(root)), key=lambda f: f.message))
        self.assertTrue(any("rule 3" in f.message and "lab-ghost" in f.message for f in mine))
        self.assertTrue(any("rule 2" in f.message and "'why'" in f.message for f in mine))
        # `lint_skills` stays the skill checks alone.
        self.assertEqual([f for f in lint.lint_skills(root, cfg) if f.message.startswith(("rule ", "case "))], [])
        r = self.run_brain(root, "lint")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertTrue(any(l.startswith("BROKEN lab-router: rule 3") for l in r.stdout.splitlines()), r.stdout)

    def test_lint_rules_direct_call_uses_the_given_skills(self):
        root = self.brain_with_router(rules_file())
        cfg = config.load(root)
        skills = list_skills(root)
        self.assertEqual(route.lint_rules(root, cfg, skills), [])  # brain-retro is not needed: default is set
        found = route.lint_rules(root, cfg, [s for s in skills if s.name != "lab-fallback"])
        self.assertEqual([(f.severity, f.subject) for f in found], [(BROKEN, "lab-router")] * len(found))
        self.assertTrue(any("lab-fallback" in f.message for f in found))

    def test_lint_rules_reports_invalid_json_without_crashing(self):
        root = self.brain_with_router("{ not json")
        found = route.lint_rules(root, config.load(root), [])
        self.assertEqual(len(found), 1, found)
        self.assertEqual((found[0].severity, found[0].subject), (BROKEN, "lab-router"))
        self.assertIn("rules.json", found[0].message)

    def test_a_brain_without_routers_has_no_rules_findings(self):
        root = self.bare_brain()
        self.assertEqual(route.lint_rules(root, config.load(root), []), [])


if __name__ == "__main__":
    unittest.main()
