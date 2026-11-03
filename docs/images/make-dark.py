#!/usr/bin/env python3
"""Write <name>-dark.svg beside each light <name>.svg in this folder, by swapping its palette.

Edit the light SVGs only, then run `python3 docs/images/make-dark.py`. Every colour an SVG uses must be in
DARK: an unknown one stops the run, so a new colour gets a dark partner rather than slipping through unchanged.
Paper and ink swap places, so a dark chat bubble with light text becomes a light bubble with dark text.
"""
import re
import sys
from pathlib import Path

DARK = {
    "#F6F1E6": "#1B1915",  # paper; also the text on dark bubbles
    "#FFFCF6": "#24211C",  # cards; also the text on coloured badges
    "#EFE7D7": "#2E2A24",  # stages, pills, the card's title bar
    "#F3ECDF": "#2A2620",  # sidebar
    "#DED3BD": "#2E2A23",  # dots
    "#E3D8C2": "#3A352D",  # borders
    "#D8CCB4": "#4A443A",  # inner borders, placeholder lines
    "#C9B79A": "#6B6152",  # doodles, soft arrows
    "#A89F8E": "#7D7567",  # tree branches, empty radio
    "#8A8274": "#A39A8B",  # muted text
    "#57524A": "#CFC6B7",  # body text
    "#1E1D1A": "#F0EAE0",  # ink; also dark bubbles and badges
    "#B5522B": "#E57D50",  # terracotta
    "#2B7A74": "#5BBDB2",  # teal
    "#C9962E": "#E2B653",  # mustard
    "#7A4E7E": "#BE90C2",  # plum
    "#D98466": "#D98466",  # window dots
    "#DDB45F": "#DDB45F",
    "#7FB0A6": "#7FB0A6",
    "#1F883D": "#238636",  # the green GitHub button
    "#FFFFFF": "#FFFFFF",
    "#5A4A2E": "#000000",  # shadow
}
HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")


def darken(svg: str, name: str) -> str:
    unknown = sorted({c.upper() for c in HEX.findall(svg)} - set(DARK))
    if unknown:
        sys.exit(f"{name}: no dark partner for {', '.join(unknown)}: add it to DARK")
    return HEX.sub(lambda m: DARK[m.group(0).upper()], svg)


def main() -> int:
    here = Path(__file__).resolve().parent
    for light in sorted(here.glob("*.svg")):
        if light.stem.endswith("-dark"):
            continue
        dark = light.with_name(light.stem + "-dark.svg")
        dark.write_text(darken(light.read_text(encoding="utf-8"), light.name), encoding="utf-8")
        print(f"wrote {dark.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
