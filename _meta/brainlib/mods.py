"""`brain mods`: the brain's mods in `mods/<prefix>-<name>/`, and the kit they are drawn with.

A mod is a Claude Code plugin whose hooks module changes Claude's own interface or behaviour (a
pane, a band above the prompt, a command, a hook on tool calls). A brain keeps each one in
`mods/<prefix>-<name>/` and loads it through a relative link,
`.claude/skills/<prefix>-<name>` -> `../../mods/<prefix>-<name>`: Claude Code loads a plugin folder
it finds in the project's `.claude/skills/` (as `<name>@skills-dir`), in sessions started at the
brain's root once the folder is trusted, and reloads it when a file in it is saved. The link is
committed, so every clone loads the same mods; a mod whose manifest says `"defaultEnabled": false`
loads only for someone who turns it on.

A mod may import only files inside its own folder, so each one carries a copy of the kit in
`hooks/kit/`. The kit's home is `_meta/modkit/gallery/hooks/kit/`; `sync` refreshes the copies and
`lint` reports one that differs.

Read-only except `new`, `link` and `sync`, which write only under `mods/` and `.claude/skills/`, and
each of those has `--dry-run`.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import config, paths
from .config import Config
from .report import BROKEN, GAP, Finding

MODS_DIR = "mods"
KIT = ("_meta", "modkit", "gallery", "hooks", "kit")
STARTER = ("_meta", "modkit", "starter")
STARTER_NAME = "modkit-starter"
LINKS = (".claude", "skills")
MANIFEST = (".claude-plugin", "plugin.json")
NAME = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
NAME_LIMIT = 64  # Claude Code's limit on command and pane names, which a mod's own name becomes
RESERVED = ("claude-", "anthropic-", "anthropics-", "cc-plugin-")
TEXT_SUFFIXES = (".ts", ".tsx", ".js", ".json", ".md")
SKIP = {".claude-plugin/types", "node_modules", ".mcpb-cache"}
MIN_CLI = (2, 1, 287)  # the first terminal Claude Code that runs mods
MIN_VSCODE_DRAW = (2, 1, 299)  # the first VS Code extension that draws what a mod draws
CHECK_TIMEOUT = 300


# -- where things are ---------------------------------------------------------------


def kit_dir(root: Path) -> Path:
    return Path(root).joinpath(*KIT)


def mods_dir(root: Path) -> Path:
    return Path(root) / MODS_DIR


def link_path(root: Path, name: str) -> Path:
    return Path(root).joinpath(*LINKS, name)


def link_target(name: str) -> str:
    return os.path.join("..", "..", MODS_DIR, name)


def mod_folders(root: Path) -> List[Path]:
    """Every real folder in `mods/` that is a mod, by name: one named `<prefix>-…` or holding `.claude-plugin/`.
    A link or a dotted name is not a mod, and neither is any other folder, so a folder that held other work in
    `mods/` before the brain (an adopted game mod, say) is left alone."""
    base = mods_dir(root)
    try:
        prefix = str(config.read_raw(root).get("prefix") or "")
    except config.ConfigError:
        prefix = ""

    def is_mod(p: Path) -> bool:
        if not p.is_dir() or p.is_symlink() or p.name.startswith("."):
            return False
        return bool(prefix and p.name.startswith(prefix + "-")) or p.joinpath(MANIFEST[0]).is_dir()

    try:
        return sorted(p for p in base.iterdir() if is_mod(p))
    except OSError:
        return []


def manifest(folder: Path) -> Optional[dict]:
    """The mod's plugin.json as a dict, or None when it is missing or not a JSON object."""
    try:
        data = json.loads(folder.joinpath(*MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _files(folder: Path) -> Dict[str, bytes]:
    """Relative path -> bytes for every file under `folder`, skipping what the engine writes."""
    found: Dict[str, bytes] = {}
    for dirpath, dirnames, filenames in os.walk(str(folder)):
        rel_dir = os.path.relpath(dirpath, str(folder)).replace(os.sep, "/")
        dirnames[:] = [d for d in dirnames if (d if rel_dir == "." else f"{rel_dir}/{d}") not in SKIP
                       and d not in SKIP and d != "__pycache__"]
        for name in filenames:
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            found[rel] = Path(dirpath, name).read_bytes()
    return found


def differs(a: Path, b: Path) -> bool:
    """Whether two folders hold different files (names or bytes). A link counts as a difference."""
    if b.is_symlink() or not b.is_dir():
        return True
    return _files(a) != _files(b)


def ignores_mods(root: Path) -> bool:
    """Whether the brain's allowlist `.gitignore` (`/*` then `!/<path>` lines) leaves `mods/` out."""
    try:
        lines = [l.strip() for l in (Path(root) / ".gitignore").read_text(encoding="utf-8").splitlines()]
    except OSError:
        return False
    return "/*" in lines and not any(l in ("!/mods/", "!/mods", "!mods/") for l in lines)


def allow_mods(root: Path) -> None:
    """Add `!/mods/` to the end of the brain's own `.gitignore` lines, so mods are committed."""
    path = Path(root) / ".gitignore"
    text = path.read_text(encoding="utf-8")
    path.write_text(text + ("" if text.endswith("\n") else "\n") + "!/mods/\n", encoding="utf-8")


def _is_ours(path: Path, name: str) -> bool:
    return path.is_symlink() and os.readlink(str(path)) == link_target(name)


# -- sync, link, new ----------------------------------------------------------------


def _link_on_the_way(root: Path, path: Path) -> Optional[str]:
    """The first folder or file from the brain's root down to `path` that is a link, as a `/` path, or None.
    Writing or deleting through one would act wherever it leads, which may be outside the brain."""
    current = Path(root)
    for part in Path(path).relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            return current.relative_to(root).as_posix()
    return None


def sync(root: Path, check: bool = False, dry_run: bool = False) -> Tuple[List[str], int]:
    """Copy the kit into every mod that has `hooks/kit/`. (lines, exit status)."""
    kit = kit_dir(root)
    if not kit.is_dir():
        return [f"mods sync: no kit at {'/'.join(KIT)}"], 2
    lines, status = [], 0
    for folder in mod_folders(root):
        dest = folder / "hooks" / "kit"
        if not (dest.exists() or dest.is_symlink()):
            continue
        if not differs(kit, dest):
            lines.append(f"ok      {folder.name}")
        elif check or dry_run:
            lines.append(f"differs {folder.name}" + ("" if check else " (would copy)"))
            status = 1 if check else status
        else:
            # Copy beside it, then swap, so a session reloading the mod never finds half a kit. `hooks/kit` itself
            # may be a link (only the link is removed); nothing above it, nor the swap folder, may be one.
            tmp = dest.parent / ".kit.sync"
            linked = _link_on_the_way(root, dest.parent) or _link_on_the_way(root, tmp)
            if linked:
                lines.append(f"BROKEN  {folder.name}: {linked} is a link; sync writes only inside the brain")
                status = 1
                continue
            shutil.rmtree(str(tmp), ignore_errors=True)
            shutil.copytree(str(kit), str(tmp))
            if dest.is_symlink() or dest.is_file():
                dest.unlink()
            else:
                shutil.rmtree(str(dest))
            tmp.rename(dest)
            lines.append(f"copied  {folder.name}")
    if not lines:
        lines.append("mods sync: no mod asks for the kit (a mod does by having hooks/kit/)")
    return lines, status


def link(root: Path, names: List[str], dry_run: bool = False) -> Tuple[List[str], int]:
    """Make the `.claude/skills/<name>` link for each mod named (every mod when none are)."""
    wanted = names or [f.name for f in mod_folders(root)]
    lines, status = [], 0
    for name in wanted:
        if not (mods_dir(root) / name).is_dir():
            lines.append(f"BROKEN  {name}: no mods/{name}/")
            status = 1
            continue
        path = link_path(root, name)
        if _is_ours(path, name):
            lines.append(f"ok      {name}: linked")
        elif path.exists() or path.is_symlink():
            lines.append(f"BROKEN  {name}: {'/'.join(LINKS)}/{name} exists and is not this mod's link; left alone")
            status = 1
        elif _link_on_the_way(root, path.parent):
            lines.append(f"BROKEN  {name}: {_link_on_the_way(root, path.parent)} is a link; mods are linked only "
                         "inside the brain")
            status = 1
        elif dry_run:
            lines.append(f"would   link {'/'.join(LINKS)}/{name} -> {link_target(name)}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(link_target(name), str(path))
            lines.append(f"linked  {name}: {'/'.join(LINKS)}/{name} -> {link_target(name)}")
    return lines, status


def full_name(cfg: Config, name: str) -> str:
    return name if name.startswith(cfg.prefix + "-") else f"{cfg.prefix}-{name}"


def name_problem(root: Path, cfg: Config, name: str) -> Optional[str]:
    """Why `name` cannot be a new mod here, or None."""
    if not NAME.match(name) or len(name) > NAME_LIMIT:
        return f"{name}: a mod's name is lowercase letters, digits and single hyphens, {NAME_LIMIT} at most"
    if name.startswith(RESERVED) or name in ("claude", "anthropic", "claude-code", "claude-mods"):
        return f"{name}: Claude Code reserves that name"
    if (mods_dir(root) / name).exists():
        return f"{name}: mods/{name}/ exists already"
    if link_path(root, name).exists() or link_path(root, name).is_symlink():
        return f"{name}: {'/'.join(LINKS)}/{name} exists already (a skill or another link has that name)"
    return None


def new(root: Path, cfg: Config, name: str, dry_run: bool = False) -> Tuple[List[str], int]:
    """Start `mods/<prefix>-<name>/` from the starter, with the kit and the link."""
    if cfg.role == "template":
        return ["mods new: the template keeps no mods; run this in a brain"], 2
    name = full_name(cfg, name)
    problem = name_problem(root, cfg, name)
    if problem:
        return [f"BROKEN  {problem}"], 1
    starter, kit = Path(root).joinpath(*STARTER), kit_dir(root)
    if not starter.is_dir() or not kit.is_dir():
        return [f"mods new: the starter or the kit is missing under _meta/modkit/; run _meta/brain update"], 2
    dest = mods_dir(root) / name
    linked = _link_on_the_way(root, mods_dir(root))
    if linked:
        return [f"BROKEN  {linked} is a link; mods new writes only inside the brain"], 1
    files = _files(starter)
    lines = [f"{'would write' if dry_run else 'wrote'} mods/{name}/ from the starter ({len(files)} files) "
             f"and its kit copy, and link {'/'.join(LINKS)}/{name}"]
    if dry_run:
        return lines, 0
    for rel, data in files.items():
        rel = rel.replace("tests/starter.test.", f"tests/{name}.test.")
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith(TEXT_SUFFIXES):
            data = data.decode("utf-8").replace(STARTER_NAME, name).encode("utf-8")
        target.write_bytes(data)
    shutil.copytree(str(kit), str(dest / "hooks" / "kit"))
    if ignores_mods(root):
        allow_mods(root)
        lines.append("added   !/mods/ to .gitignore, so mods are committed")
    linked, status = link(root, [name])
    return lines + linked, status


# -- checks -------------------------------------------------------------------------


def _version(text: str) -> Optional[Tuple[int, ...]]:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    return tuple(int(x) for x in m.groups()) if m else None


def _dotted(v: Tuple[int, ...]) -> str:
    return ".".join(str(x) for x in v)


def check(root: Path, names: List[str]) -> Tuple[List[str], int]:
    """`claude plugin validate` and `claude plugin test` on each mod named (every mod when none are)."""
    exe = shutil.which("claude")
    folders = [f for f in mod_folders(root) if not names or f.name in names]
    if not folders:
        return ["mods check: no mod to check"], 0
    if not exe:
        return [f"skipped {f.name}: claude is not on PATH, so the plugin checks cannot run" for f in folders], 0
    lines, status = [], 0
    for folder in folders:
        for step in ("validate", "test"):
            try:
                ran = subprocess.run([exe, "plugin", step, str(folder)], capture_output=True, text=True,
                                     timeout=CHECK_TIMEOUT, stdin=subprocess.DEVNULL)
                ok, tail = ran.returncode == 0, (ran.stdout + ran.stderr).strip().splitlines()[-3:]
            except (OSError, subprocess.SubprocessError) as exc:
                ok, tail = False, [type(exc).__name__]
            lines.append(f"{'ok     ' if ok else 'BROKEN '} {folder.name}: claude plugin {step}"
                         + ("" if ok else " failed: " + " | ".join(tail)))
            status = status if ok else 1
    return lines, status


def _names(folder: Path) -> List[str]:
    try:
        return [p.name for p in folder.iterdir()]
    except OSError:
        return []


def readiness(home: Path) -> List[Tuple[str, str]]:
    """(level, text) for each Claude Code on this machine: whether it runs mods. Never fails."""
    out: List[Tuple[str, str]] = []
    exe = shutil.which("claude")
    if exe:
        try:
            v = _version(subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20,
                                        stdin=subprocess.DEVNULL).stdout)
        except (OSError, subprocess.SubprocessError):
            v = None
        if v is None:
            out.append(("note", "claude CLI: could not read its version"))
        elif v >= MIN_CLI:
            out.append(("ok", f"claude CLI {_dotted(v)} runs mods"))
        else:
            out.append(("note", f"claude CLI {_dotted(v)} is older than {_dotted(MIN_CLI)}: no mods there"))
    else:
        out.append(("note", "claude CLI not on PATH"))
    # The desktop app keeps its own Claude Code, one folder per version.
    for folder in (home / ".config" / "Claude" / "claude-code",
                   home / "Library" / "Application Support" / "Claude" / "claude-code"):
        versions = [v for v in (_version(name) for name in _names(folder)) if v]
        if versions:
            newest = max(versions)
            out.append(("ok" if newest >= MIN_CLI else "note", f"desktop app's Claude Code {_dotted(newest)}"
                        + (" runs mods" if newest >= MIN_CLI else f" is older than {_dotted(MIN_CLI)}")))
    for ext in (home / ".vscode" / "extensions", home / ".vscode-server" / "extensions"):
        found = [v for v in (_version(n) for n in _names(ext) if n.startswith("anthropic.claude-code-")) if v]
        if found:
            newest = max(found)
            out.append(("ok" if newest >= MIN_VSCODE_DRAW else "note", f"VS Code extension {_dotted(newest)}"
                        + (" runs mods and draws them" if newest >= MIN_VSCODE_DRAW
                           else f" runs mods but draws nothing before {_dotted(MIN_VSCODE_DRAW)}")))
    if "microsoft" in platform.release().lower():
        out.append(("note", "WSL: the desktop app loads no plugins in a WSL session, so mods run only in "
                            "`claude` started in the WSL terminal"))
    return out


def lint_mods(root: Path, cfg: Config, skills: list) -> List[Finding]:
    """What `lint` (and so `doctor`) reports about the brain's mods and their links."""
    root = Path(root)
    found: List[Finding] = []
    kit = kit_dir(root)
    names = set()
    for folder in mod_folders(root):
        name = folder.name
        names.add(name)
        data = manifest(folder)
        if data is None:
            found.append(Finding(BROKEN, name, f"mods/{name}/{'/'.join(MANIFEST)} is missing or not a JSON object"))
            continue
        if data.get("name") != name:
            found.append(Finding(BROKEN, name, f"plugin.json names it {data.get('name')!r}; the folder is {name!r}"))
        if not (folder / "hooks" / "hooks.json").is_file():
            found.append(Finding(BROKEN, name, "no hooks/hooks.json naming its hooks module"))
        if cfg.prefix and not name.startswith(cfg.prefix + "-"):
            found.append(Finding(GAP, name, f"a mod's name starts with the brain's prefix ({cfg.prefix}-)"))
        if not _is_ours(link_path(root, name), name):
            found.append(Finding(GAP, name, f"not linked into {'/'.join(LINKS)}/, so no session loads it: "
                                            f"_meta/brain mods link {name}"))
        dest = folder / "hooks" / "kit"
        if (dest.exists() or dest.is_symlink()) and kit.is_dir() and differs(kit, dest):
            found.append(Finding(GAP, name, "its copy of the kit differs from _meta/modkit: _meta/brain mods sync"))
        if not any(p.name.endswith((".test.ts", ".test.tsx")) for p in folder.rglob("*.test.*")):
            found.append(Finding(GAP, name, "no *.test.ts: a mod is tested with claude plugin test"))
        if not (folder / "README.md").is_file():
            found.append(Finding(GAP, name, "no README.md saying what it does, what it reads and how to turn it off"))
    if names and ignores_mods(root):
        found.append(Finding(GAP, "mods", ".gitignore leaves mods/ out, so no mod is committed: add !/mods/ "
                                          "below the managed block"))
    base = root.joinpath(*LINKS)
    try:
        links = [p for p in base.iterdir() if p.is_symlink()]
    except OSError:
        links = []
    for path in links:
        target = os.readlink(str(path))
        if target.startswith(os.path.join("..", "..", MODS_DIR) + os.sep) and not path.exists():
            found.append(Finding(BROKEN, path.name, f"{'/'.join(LINKS)}/{path.name} points at a mod that is not there"))
    return found


# -- the command --------------------------------------------------------------------


def add_arguments(parser) -> None:
    sub = parser.add_subparsers(dest="action", metavar="<action>")
    sub.add_parser("list", help="each mod, whether it is linked and whether its kit is current")
    p = sub.add_parser("new", help="start mods/<prefix>-<name>/ from the starter, with the kit and the link")
    p.add_argument("name")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("sync", help="copy the kit into every mod that has hooks/kit/")
    p.add_argument("--check", action="store_true", help="change nothing; exit 1 when a copy differs")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("link", help="link mods into .claude/skills/ so sessions load them")
    p.add_argument("names", nargs="*")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("check", help="run claude plugin validate and test on each mod")
    p.add_argument("names", nargs="*")
    sub.add_parser("ready", help="which Claude Code on this machine runs mods")


def _list(root: Path, cfg: Config) -> List[str]:
    folders = mod_folders(root)
    if not folders:
        return ["no mods yet (mods/ holds none): _meta/brain mods new <name>"]
    kit = kit_dir(root)
    lines = []
    for folder in folders:
        data = manifest(folder) or {}
        bits = ["linked" if _is_ours(link_path(root, folder.name), folder.name) else "NOT linked"]
        dest = folder / "hooks" / "kit"
        if dest.exists():
            bits.append("kit stale" if kit.is_dir() and differs(kit, dest) else "kit current")
        if data.get("defaultEnabled") is False:
            bits.append("opt-in")
        lines.append(f"{folder.name:<24} {', '.join(bits)}  {str(data.get('description', ''))[:70]}")
    return lines


def run(args) -> int:
    root = paths.harness_root()
    action = getattr(args, "action", None) or "list"
    if action == "ready":
        for level, text in readiness(Path(os.path.expanduser("~"))):
            print(f"{level:<6} {text}")
        return 0
    cfg = config.load(root)
    if action == "list":
        print("\n".join(_list(root, cfg)))
        return 0
    if action == "new":
        lines, status = new(root, cfg, args.name, args.dry_run)
    elif action == "sync":
        lines, status = sync(root, args.check, args.dry_run)
    elif action == "link":
        lines, status = link(root, args.names, args.dry_run)
    else:
        lines, status = check(root, args.names)
    print("\n".join(lines))
    return status
