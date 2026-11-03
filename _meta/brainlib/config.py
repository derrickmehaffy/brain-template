"""Reading and writing `brain.json`, with every absent key filled from its default."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional

PREFIX_PATTERN = re.compile(r"^[a-z][a-z0-9]{1,15}$")
RESERVED_PREFIXES = ("brain", "template")
ROLES = ("brain", "template")
PACKAGE_POLICIES = ("stdlib-only", "allowed")

BRAIN_JSON = "brain.json"
LOCAL_JSON = "brain.local.json"
PRIVATE_FILE = ".brain-private"


class ConfigError(Exception):
    """brain.json (or brain.local.json) is missing, unreadable or malformed."""


@dataclass
class Config:
    root: Path
    name: str
    prefix: str
    role: str
    description: str
    template_source: Optional[str]
    template_version: Optional[str]
    python: str
    packages: str
    deny_patterns: List[str]
    private_patterns: List[str]
    private_file_expected: bool
    max_file_kb: int
    large_file_allow: List[str]
    stale_after_days: int
    gates: List[dict]
    gates_off: List[dict]
    gate_exempt: List[str]
    raw: dict


# -- reading and writing the raw file -----------------------------------------


def _read_json_object(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"{path.name} not found in {path.parent}")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ConfigError(f"{path.name} is not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} must hold a JSON object")
    return data


def read_raw(root: Path) -> dict:
    """The parsed `brain.json` exactly as written (key order kept)."""
    return _read_json_object(Path(root) / BRAIN_JSON)


def write_raw(root: Path, raw: dict) -> None:
    """Write `brain.json`: indent 2, key order kept, trailing newline."""
    text = json.dumps(raw, indent=2, ensure_ascii=False) + "\n"
    with open(Path(root) / BRAIN_JSON, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


# -- validation -----------------------------------------------------------------


def validate_prefix(p: str) -> Optional[str]:
    """None when `p` can be a brain's prefix, else the reason it cannot."""
    if p in RESERVED_PREFIXES:
        return f"prefix '{p}' is reserved; shipped skills use brain-* and the template uses template-*"
    if not PREFIX_PATTERN.fullmatch(p):
        suggestion = re.sub(r"^[^a-z]+", "", re.sub(r"[^a-z0-9]", "", p.lower()))[:16]
        hint = f"; '{suggestion}' would do" if PREFIX_PATTERN.fullmatch(suggestion) and \
            suggestion not in RESERVED_PREFIXES else ""
        return (f"prefix '{p}' must be 2 to 16 characters: a lowercase letter, then lowercase letters or digits"
                f"{hint}")
    return None


def _is_str(v: Any) -> bool:
    return isinstance(v, str)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_bool(v: Any) -> bool:
    return isinstance(v, bool)


def _is_dict(v: Any) -> bool:
    return isinstance(v, dict)


def _list_of(check: Callable[[Any], bool]) -> Callable[[Any], bool]:
    return lambda v: isinstance(v, list) and all(check(item) for item in v)


def _section(raw: dict, key: str) -> dict:
    value = raw.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"brain.json: '{key}' must be an object")
    return value


def _field(source: dict, where: str, key: str, check: Callable[[Any], bool], expected: str, default: Any) -> Any:
    """`source[key]` when present (and not null) and of the right type, else `default`."""
    value = source.get(key)
    if value is None:
        return default
    if not check(value):
        raise ConfigError(f"brain.json: '{where}{key}' must be {expected}")
    return list(value) if isinstance(value, list) else value


def _choice(value: str, options: tuple, where: str) -> str:
    if value not in options:
        raise ConfigError(f"brain.json: '{where}' must be one of {', '.join(options)}")
    return value


REGEX_PREFIX = "re:"  # a `.brain-private` line that starts with this is a regular expression, not a plain term
# What only a regular expression holds: a backslash, `.*`, `.+`, `|` or a `[...]` class. Before 0.2.0 every line was
# a regular expression, so a line holding one of these is still read as one: reading it as plain text would quietly
# stop it matching, and the guard must fail closed.
LOOKS_LIKE_REGEX = re.compile(r"\\|\.\*|\.\+|\||\[[^\]]+\]")


def term_pattern(line: str) -> str:
    """The regular expression one line of `.brain-private` stands for. A plain term (a name, a host, an address,
    as a person would write it) matches as a whole word: not inside a longer word, so `lab` leaves `label` alone,
    and `c++` or `my-server.local` mean exactly that; a straight and a curly apostrophe match each other. A line
    starting `re:`, or one that can only be a regular expression (`LOOKS_LIKE_REGEX`), is one as written."""
    if line.startswith(REGEX_PREFIX):
        return line[len(REGEX_PREFIX):].strip()
    if LOOKS_LIKE_REGEX.search(line):
        return line
    return r"(?<!\w)" + re.sub("['\u2019]", "['\u2019]", re.escape(line)) + r"(?!\w)"


def _private_patterns(root: Path) -> List[str]:
    """The pattern for each line of `.brain-private` (see `term_pattern`); blank lines and `#` comments are skipped.

    A missing file means no patterns; one that exists but cannot be read is an error,
    so a weaker privacy guard never goes unnoticed.
    """
    path = root / PRIVATE_FILE
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}")
    lines = (line.strip() for line in text.splitlines())
    return [term_pattern(line) for line in lines if line and not line.startswith("#")]


# -- the public loader ------------------------------------------------------------


def load(root: Path) -> Config:
    """Load `<root>/brain.json` with defaults for every absent key; raises ConfigError."""
    root = Path(root)
    raw = read_raw(root)
    template = _section(raw, "template")
    scripts = _section(raw, "scripts")
    privacy = _section(raw, "privacy")
    practices = _section(raw, "practices")
    strings = _list_of(_is_str)
    return Config(
        root=root,
        name=_field(raw, "", "name", _is_str, "a string", ""),
        prefix=_field(raw, "", "prefix", _is_str, "a string", ""),
        role=_choice(_field(raw, "", "role", _is_str, "a string", "brain"), ROLES, "role"),
        description=_field(raw, "", "description", _is_str, "a string", ""),
        template_source=_field(template, "template.", "source", _is_str, "a string or null", None),
        template_version=_field(template, "template.", "version", _is_str, "a string or null", None),
        python=_field(scripts, "scripts.", "python", _is_str, "a string", "python3"),
        packages=_choice(_field(scripts, "scripts.", "packages", _is_str, "a string", "stdlib-only"),
                         PACKAGE_POLICIES, "scripts.packages"),
        deny_patterns=_field(privacy, "privacy.", "deny_patterns", strings, "a list of strings", []),
        private_patterns=_private_patterns(root),
        private_file_expected=_field(privacy, "privacy.", "private_file_expected", _is_bool, "true or false", False),
        max_file_kb=_field(privacy, "privacy.", "max_file_kb", _is_int, "an integer", 1024),
        large_file_allow=_field(privacy, "privacy.", "large_file_allow", strings, "a list of strings", []),
        stale_after_days=_field(practices, "practices.", "stale_after_days", _is_int, "an integer", 180),
        gates=_field(raw, "", "gates", _list_of(_is_dict), "a list of objects", []),
        gates_off=_field(raw, "", "gates_off", _list_of(_is_dict), "a list of objects", []),
        gate_exempt=_field(raw, "", "gate_exempt", strings, "a list of strings", []),
        raw=raw,
    )


def effective_source(cfg: Config) -> Optional[str]:
    """The template's location on this machine: `brain.local.json` wins over `brain.json`."""
    local_path = cfg.root / LOCAL_JSON
    if local_path.exists():
        template = _read_json_object(local_path).get("template")
        source = template.get("source") if isinstance(template, dict) else None
        if isinstance(source, str) and source:
            return source
    return cfg.template_source
