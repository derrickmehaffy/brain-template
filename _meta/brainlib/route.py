"""`brain route`: apply a router's `rules.json` to name the one skill that takes the work (spec §7.8)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from . import paths
from .config import Config
from .report import BROKEN, OK, Finding, emit
from .skills import Skill, list_skills, skills_dir

DEFAULT_SKILL = "brain-retro"  # unrouted work becomes an UNCLASSIFIED-LOG.md row
RULES_FILE = "rules.json"


class RulesError(Exception):
    """A rules file that cannot be read, or a rule `route` cannot evaluate."""


# -- reading --------------------------------------------------------------------------


def load_rules(path: Path) -> dict:
    """The JSON the file at `path` holds (`check_rules` confirms it is an object)."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise RulesError(f"{path.name} is not valid UTF-8")
    except OSError as exc:
        raise RulesError(f"cannot read {path.name}: {exc.strerror or exc}")
    try:
        return json.loads(text)
    except ValueError as exc:
        raise RulesError(f"{path.name} is not valid JSON: {exc}")


def router_files(root) -> List[Path]:
    """Every `.claude/skills/<name>/rules.json` under `root`, sorted by router name."""
    try:
        return sorted(p for p in skills_dir(root).glob(f"*/{RULES_FILE}") if p.is_file())
    except OSError:
        return []


# -- routing --------------------------------------------------------------------------


def _strings(value: Any) -> List[str]:
    """`value` as a list of strings: a lone value counts as one, so "api" is never read as letters."""
    items = value if isinstance(value, (list, tuple)) else [value]
    return [item if isinstance(item, str) else str(item) for item in items if item is not None]


def _holds(key: str, listed: Any, given: Dict[str, List[str]]) -> bool:
    """One condition: `field` is any listed value exactly, `field~` contains one; both ignore case."""
    substring = key.endswith("~")
    values = given.get(key[:-1] if substring else key)
    if not values:  # a field the input does not have
        return False
    wanted = _strings(listed)
    if substring:
        haystacks = [v.casefold() for v in values]
        return any(w.casefold() in h for w in wanted for h in haystacks)
    exact = {w.strip().casefold() for w in wanted}
    return any(v.strip().casefold() in exact for v in values)


def _is_name(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def route(rules: dict, inputs: Dict[str, List[str]]) -> dict:
    """The first rule whose conditions all hold, else the default.

    Returns `{"skill", "rule", "also", "why"}`; `rule` is the 1-based position of the matching rule,
    or "default". Raises `RulesError` for a rule it cannot evaluate (so a broken file never routes
    somewhere by accident).
    """
    if not isinstance(rules, dict):
        raise RulesError("the rules file is not a JSON object")
    listed = rules.get("rules")
    if not isinstance(listed, list):
        raise RulesError("'rules' must be a list")
    given = {field: _strings(values) for field, values in inputs.items()}
    for number, rule in enumerate(listed, start=1):
        if not isinstance(rule, dict) or not isinstance(rule.get("when"), dict) or not _is_name(rule.get("skill")):
            raise RulesError(f"rule {number} needs a 'when' object and a 'skill'")
        if all(_holds(key, values, given) for key, values in rule["when"].items()):
            also = rule.get("also")
            return {"skill": rule["skill"], "rule": number,
                    "also": _strings(also) if isinstance(also, list) else [],
                    "why": str(rule.get("why") or "")}
    default = rules.get("default", DEFAULT_SKILL)
    if not _is_name(default):
        raise RulesError("'default' must be a skill name")
    return {"skill": default, "rule": "default", "also": [], "why": "no rule matched, so the default applies"}


# -- checking -------------------------------------------------------------------------


def _condition_errors(label: str, when: dict) -> List[str]:
    return [f"{label}: condition '{key}' must be a non-empty list of non-empty strings"
            for key, values in when.items()
            if not (isinstance(values, list) and values and all(_is_name(v) for v in values))]


def _rule_errors(number: int, rule: Any) -> List[str]:
    label = f"rule {number}"
    if not isinstance(rule, dict):
        return [f"{label}: not an object"]
    errors = []
    if isinstance(rule.get("when"), dict):
        errors += _condition_errors(label, rule["when"])
    else:
        errors.append(f"{label}: missing 'when' (an object of field: [values])")
    if not _is_name(rule.get("skill")):
        errors.append(f"{label}: missing 'skill'")
    if not _is_name(rule.get("why")):
        errors.append(f"{label}: missing 'why'")
    if "also" in rule:
        also = rule["also"]
        if not isinstance(also, list):
            errors.append(f"{label}: 'also' must be a list")
        elif not all(_is_name(a) for a in also):
            errors.append(f"{label}: 'also' must hold skill names")
    return errors


def _case_inputs(case: Any) -> Optional[Dict[str, List[str]]]:
    """A case's input as `route` takes it, or None when the case is not shaped `{input, expect}`."""
    if not isinstance(case, dict) or not isinstance(case.get("input"), dict) or not _is_name(case.get("expect")):
        return None
    return {field: _strings(values) for field, values in case["input"].items()}


def _skill_errors(rules: dict, skill_names: Set[str]) -> List[str]:
    wanted: List[Tuple[str, Any]] = []
    for number, rule in enumerate(rules["rules"], start=1):
        if isinstance(rule, dict):
            wanted.append((f"rule {number}: skill", rule.get("skill")))
            also = rule.get("also")
            wanted += [(f"rule {number}: also", name) for name in (also if isinstance(also, list) else [])]
    wanted.append(("default", rules.get("default", DEFAULT_SKILL)))
    cases = rules.get("cases")
    for number, case in enumerate(cases if isinstance(cases, list) else [], start=1):
        if isinstance(case, dict):
            wanted.append((f"case {number}: expect", case.get("expect")))
    return [f"{label} '{name}' does not exist" for label, name in wanted
            if _is_name(name) and name not in skill_names]


def _case_errors(rules: dict) -> List[str]:
    errors = []
    cases = rules.get("cases")
    for number, case in enumerate(cases if isinstance(cases, list) else [], start=1):
        inputs = _case_inputs(case)
        if inputs is None:
            errors.append(f"case {number}: needs an 'input' object and an 'expect' skill name")
            continue
        try:
            got = route(rules, inputs)
        except RulesError:  # the rule it stumbled on is already reported
            continue
        if got["skill"] != case["expect"]:
            errors.append(f"case {number}: got '{got['skill']}' (rule {got['rule']}), expected '{case['expect']}'")
    return errors


def check_rules(rules: dict, skill_names: Set[str]) -> List[str]:
    """Every problem in a rules file (empty when it is sound): shape, missing skills, failing cases.

    Rules and cases are numbered from 1, as `route` numbers rules.
    """
    if not isinstance(rules, dict):
        return ["the rules file is not a JSON object"]
    if not isinstance(rules.get("rules"), list):
        return ["'rules' must be a list"]
    errors: List[str] = []
    for number, rule in enumerate(rules["rules"], start=1):
        errors += _rule_errors(number, rule)
    if "default" in rules and not _is_name(rules["default"]):
        errors.append("'default' must be a skill name")
    if "cases" in rules and not isinstance(rules["cases"], list):
        errors.append("'cases' must be a list")
    return errors + _skill_errors(rules, skill_names) + _case_errors(rules)


def lint_rules(root, cfg: Config, skills: List[Skill]) -> List[Finding]:
    """BROKEN for each problem in each router's `rules.json` (a `lint` extra check)."""
    names = {skill.name for skill in skills}
    found: List[Finding] = []
    for path in router_files(root):
        router = path.parent.name
        try:
            rules = load_rules(path)
        except RulesError as exc:
            found.append(Finding(BROKEN, router, str(exc)))
            continue
        found += [Finding(BROKEN, router, message) for message in check_rules(rules, names)]
    return found


# -- the command ----------------------------------------------------------------------


def _field_value(text: str) -> Tuple[str, str]:
    """`FIELD=VALUE` (split at the first '=') as an argparse type."""
    field, equals, value = text.partition("=")
    field = field.strip()
    if not equals or not field or field.endswith("~"):
        raise argparse.ArgumentTypeError(f"expected FIELD=VALUE with a plain field name, got '{text}'")
    return field, value


def add_arguments(parser) -> None:
    parser.add_argument("rules", metavar="RULES",
                        help="a rules.json path, or a router name (.claude/skills/<name>/rules.json in this brain)")
    parser.add_argument("--set", dest="fields", action="append", type=_field_value, metavar="FIELD=VALUE",
                        help="an input field; repeat it to give the field several values")
    parser.add_argument("--check", action="store_true",
                        help="validate the file and run its cases instead of routing (--set is not used)")


def _resolve(root: Path, argument: str) -> Optional[Path]:
    """The rules file `argument` names: a path, then `<router>/rules.json` or a router name under the skills."""
    candidates = [Path(argument)]
    relative = Path(argument)
    if not relative.is_absolute() and ".." not in relative.parts:
        candidates += [skills_dir(root) / relative, skills_dir(root) / relative / RULES_FILE]
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _check(root: Path, rules: Any, subject: str) -> int:
    names = {skill.name for skill in list_skills(root)}
    errors = check_rules(rules, names)
    if errors:
        emit(Finding(BROKEN, subject, message) for message in errors)
    else:
        cases = rules.get("cases") if isinstance(rules.get("cases"), list) else []
        emit([Finding(OK, subject, f"{len(rules['rules'])} rules, {len(cases)} cases")])
    return 1 if errors else 0


def run(args) -> int:
    root = paths.harness_root()
    path = _resolve(root, args.rules)
    if path is None:
        print(f"route: no rules file '{args.rules}' (not a path, nor a router with "
              f"{Path('.claude', 'skills', args.rules, RULES_FILE)})", file=sys.stderr)
        return 1
    try:
        rules = load_rules(path)
    except RulesError as exc:
        print(f"route: {exc}", file=sys.stderr)
        return 1
    if args.check:
        return _check(root, rules, args.rules)
    inputs: Dict[str, List[str]] = {}
    for field, value in args.fields or []:
        inputs.setdefault(field, []).append(value)
    try:
        print(json.dumps(route(rules, inputs)))
    except RulesError as exc:
        print(f"route: {path.name}: {exc}", file=sys.stderr)
        return 1
    return 0
