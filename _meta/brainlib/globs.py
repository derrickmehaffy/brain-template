"""Anchored glob matching for brain-relative paths (the skill gate's rules).

`*` and `?` stay inside one path segment; `**` crosses segments (`a/**` is everything below `a/`,
`a/**/b` matches `a/b` and `a/x/y/b`, `**/b` matches `b` anywhere). Every other character is
literal, so `[x]` and `+` mean themselves. Standard library only, and cheap to import: the gate
runs on every tool call.
"""
from __future__ import annotations

import re
from functools import lru_cache


@lru_cache(maxsize=512)
def _compile(pattern: str):
    while pattern.startswith("./"):
        pattern = pattern[2:]
    pattern = pattern.lstrip("/")  # rules are relative to the brain root
    out = []
    i, n = 0, len(pattern)
    while i < n:
        char = pattern[i]
        if char == "*":
            if pattern.startswith("**", i):
                end = i + 2
                at_segment_start = i == 0 or pattern[i - 1] == "/"
                if at_segment_start and pattern.startswith("/", end):
                    out.append("(?:.*/)?")  # `**/`: zero or more whole folders
                    i = end + 1
                else:
                    out.append(".*")
                    i = end
                continue
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        i += 1
    return re.compile("".join(out), re.DOTALL)


def match(pattern: str, relpath: str) -> bool:
    """True when the whole of `relpath` (slash-separated, relative to the root) fits `pattern`."""
    return _compile(pattern).fullmatch(relpath) is not None
