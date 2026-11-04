"""Check WCAG 2.1 contrast for the colour pairs the site uses.

Reads the colour tokens from site/style.css, so a changed token is checked
automatically. Text pairs need 4.5:1 (AA, normal text); outlines of
controls, focus rings and chart bars need 3:1 (WCAG 1.4.11).

Usage:  python scripts/check_contrast.py      (exit code 1 if any pair fails)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "site" / "style.css"

# (foreground token, background token, minimum ratio, where it is used)
PAIRS = [
    ("text", "white", 4.5, "body text, hints, secondary labels"),
    ("heading", "white", 4.5, "headings, legends, labels"),
    ("blue", "white", 4.5, "links, secondary buttons, credit line, star button"),
    ("blue-dark", "white", 4.5, "link hover"),
    ("white", "blue", 4.5, "header band text, primary button, selected month"),
    ("white", "blue-dark", 4.5, "primary button hover"),
    ("text", "tint", 4.5, "independence notice, career-stage note"),
    ("heading", "tint", 4.5, "bold text on tinted panels and selected cards"),
    ("blue", "tint", 4.5, "tick on selected cards, pressed star, secondary button hover"),
    ("blue-dark", "tint", 4.5, "badges and links in badges"),
    ("control", "white", 3.0, "outlines of answer cards, chips, fields, months, star"),
    ("blue", "white", 3.0, "selected card border"),
    ("blue-dark", "white", 3.0, "focus ring"),
    ("blue", "tint", 3.0, "month bars"),
    ("white", "blue-dark", 3.0, "month bar when its month is selected"),
]


def tokens(css: str) -> dict[str, str]:
    root = re.search(r":root\s*\{(.*?)\}", css, re.S).group(1)
    return {m.group(1): m.group(2) for m in re.finditer(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})", root)}


def luminance(hex_colour: str) -> float:
    def channel(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def ratio(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def check(css_text: str | None = None) -> list[tuple]:
    colours = tokens(css_text if css_text is not None else CSS.read_text(encoding="utf-8"))
    results = []
    for fg, bg, minimum, use in PAIRS:
        r = ratio(colours[fg], colours[bg])
        results.append((fg, colours[fg], bg, colours[bg], r, minimum, use))
    return results


def main() -> int:
    failed = 0
    for fg, fgc, bg, bgc, r, minimum, use in check():
        ok = r >= minimum
        failed += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {r:5.2f}:1 (needs {minimum}) {fg} {fgc} on {bg} {bgc} — {use}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
