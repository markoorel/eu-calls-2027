"""Score how well each call fits a department or area of interest.

Used by build_calls.py. The score only orders results; the page never shows
it. What the page shows is the evidence: the matched terms and, once
tags.csv has panels, the matched ERC panels.

Scoring for one call and one department or topic:
  - each search term found in the title: TITLE_POINTS
  - otherwise, found in the portal's tags or keywords: TAG_POINTS
  - otherwise, found at least DESCRIPTION_MIN_MENTIONS times in the
    description: DESCRIPTION_POINTS (a single passing mention is ignored)
  - the department's main ERC panel in the call's erc_panels: MAIN_PANEL_POINTS
  - any other of its panels in the call's erc_panels: OTHER_PANEL_POINTS
A term counts once per call, at the best place it was found.

Usage (prints the top matches for checking):
  python scripts/match.py arts-management entrepreneurship management
"""

from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

TITLE_POINTS = 3
TAG_POINTS = 2
DESCRIPTION_POINTS = 1
DESCRIPTION_MIN_MENTIONS = 2
MAIN_PANEL_POINTS = 3
OTHER_PANEL_POINTS = 1


def load_profiles(path: Path = DATA / "departments.json") -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    profiles = {}
    for kind in ("departments", "topics"):
        for entry in data.get(kind, []):
            if entry["id"] in profiles:
                raise ValueError(f"departments.json: duplicate id {entry['id']}")
            profiles[entry["id"]] = {**entry, "kind": kind[:-1]}
    rules = [(re.compile(r["pattern"], re.I), r["label"])
             for r in data.get("open_to_all_fields", {}).get("rules", [])]
    return {"profiles": profiles, "open_rules": rules}


@lru_cache(maxsize=None)
def term_pattern(term: str) -> re.Pattern:
    """Whole-word pattern that tolerates common spelling variants.

    'start-ups' also matches 'start ups' and 'startups'; 'organisations'
    matches 'organizations'; 'behaviour' matches 'behavior'; a final 's'
    is optional and one may be added ('SME' / 'SMEs').
    """
    words = re.split(r"[\s\-]+", term.strip())
    parts = []
    for word in words:
        w = re.escape(word)
        w = re.sub(r"is(e|ation|ing|ed)", r"i[sz]\1", w)
        w = w.replace("our", "ou?r")
        parts.append(w)
    body = r"[\s\-]?".join(parts)
    if body.endswith("s") and not body.endswith("ss"):
        body = body[:-1] + "s?"
    else:
        body += "s?"
    return re.compile(rf"(?<![\w-]){body}(?![\w-])", re.I)


def open_to_all_label(identifier: str, rules) -> str | None:
    for pattern, label in rules:
        if pattern.search(identifier):
            return label
    return None


def score_call(call: dict, profile: dict, description: dict | None) -> dict | None:
    """Return {'score', 'terms', 'panels'} or None when nothing matched."""
    title = call.get("title") or ""
    tags = " | ".join((description or {}).get("tags", []) + (description or {}).get("keywords", []))
    text = (description or {}).get("text", "")
    score, terms = 0, []
    for term in profile["search_terms"]:
        pattern = term_pattern(term)
        if pattern.search(title):
            score += TITLE_POINTS
        elif tags and pattern.search(tags):
            score += TAG_POINTS
        elif text and len(pattern.findall(text)) >= DESCRIPTION_MIN_MENTIONS:
            score += DESCRIPTION_POINTS
        else:
            continue
        terms.append(term)
    panels = []
    call_panels = set(call.get("erc_panels") or [])
    for n, panel in enumerate(profile.get("erc_panels", [])):
        if panel in call_panels:
            score += MAIN_PANEL_POINTS if n == 0 else OTHER_PANEL_POINTS
            panels.append(panel)
    if not score:
        return None
    return {"score": score, "terms": terms, "panels": panels}


def match_calls(calls: list[dict], descriptions: dict, config: dict) -> None:
    """Add 'open_to_all_fields' and 'fits' to each call, in place."""
    for call in calls:
        call["open_to_all_fields"] = open_to_all_label(call["identifier"], config["open_rules"])
        description = descriptions.get(call["identifier"].upper())
        fits = {}
        for pid, profile in config["profiles"].items():
            result = score_call(call, profile, description)
            if result:
                fits[pid] = result
        call["fits"] = fits


def load_descriptions(path: Path = DATA / "descriptions.json") -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k.upper(): v for k, v in data.get("topics", {}).items()}


def ranked(calls: list[dict], profile_id: str) -> list[dict]:
    """Calls that match the profile, best fit first, then soonest deadline."""
    hits = [c for c in calls if profile_id in c.get("fits", {})]
    return sorted(hits, key=lambda c: (-c["fits"][profile_id]["score"], c["deadlines"][0], c["identifier"]))


def main(argv: list[str]) -> int:
    data = json.loads((DATA / "calls.json").read_text(encoding="utf-8"))
    calls = data["calls"]
    config = load_profiles()
    ids = argv or ["arts-management", "entrepreneurship", "management"]
    open_all = [c for c in calls if c.get("open_to_all_fields")]
    print(f"Open to all fields ({len(open_all)}): " +
          ", ".join(f"{c['identifier']} [{c['open_to_all_fields']}]" for c in open_all))
    for pid in ids:
        profile = config["profiles"][pid]
        hits = ranked(calls, pid)
        print(f"\n=== {profile['name']}: {len(hits)} matching calls; top 10 ===")
        for n, call in enumerate(hits[:10], 1):
            fit = call["fits"][pid]
            print(f"{n:2}. [{fit['score']:2}] {call['title']}")
            print(f"      {call['identifier']} | {call['pillar_or_cluster'] or call['programme']} | deadline {call['deadlines'][0]}")
            print(f"      matched: {', '.join(fit['terms'])}" + (f" | panels: {', '.join(fit['panels'])}" if fit["panels"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
