"""Turn data/raw_topics.json into data/calls.json for the site.

Steps:
  1. Read the raw topics saved by fetch.py.
  2. Keep topics that a new applicant can still apply to with a 2027 deadline
     (decided from the deadline dates, not the portal's status label).
  3. Map each topic to the fields in CLAUDE.md, using data/programmes.json.
  4. Add calls from data/manual_calls.json and apply reviewed tags from
     data/tags.csv.
  5. Check the result and only then replace calls.json.

Missing values stay empty (null or []); the page shows "check portal".
Nothing here guesses a deadline, budget or eligibility rule.

Usage:  python scripts/build_calls.py [--today YYYY-MM-DD] [--allow-drop]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import match

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TARGET_YEAR = 2027
PORTAL_TOPIC_URL = (
    "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/"
    "opportunities/topic-details/{identifier}"
)
# Refuse to publish if the number of calls falls below this share of the
# previous file (a sign of a broken fetch rather than real change).
MIN_SHARE_OF_PREVIOUS = 0.5

SCHEMES = {"individual", "consortium", "either"}
ERC_DOMAINS = {"LS", "PE", "SH"}
ERC_PANEL_RE = re.compile(r"^(LS[1-9]|PE(1[01]|[1-9])|SH[1-8])$")


class BuildError(Exception):
    pass


# ---------------------------------------------------------------- helpers

def first(value):
    """Metadata values arrive as lists, even single values."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def clean_text(value) -> str | None:
    value = first(value)
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def iso_date(value) -> str | None:
    """'2027-02-17T00:00:00.000+0000' -> '2027-02-17'. Returns None if unparseable."""
    if not value:
        return None
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", str(value))
    if not match:
        return None
    try:
        date.fromisoformat(match.group(1))
    except ValueError:
        return None
    return match.group(1)


def load_json(path: Path, default=None):
    if not path.exists():
        if default is not None:
            return default
        raise BuildError(f"missing file: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BuildError(f"{path.name} is not valid JSON: {exc}") from exc


# ---------------------------------------------------------------- mapping

def match_division(identifier: str, divisions: list[dict]) -> dict | None:
    best = None
    for division in divisions:
        if identifier.upper().startswith(division["prefix"].upper()):
            if best is None or len(division["prefix"]) > len(best["prefix"]):
                best = division
    return best


def field_text(field: str, identifier: str, type_of_action: str | None, meta: dict) -> str:
    if field == "identifier":
        return identifier
    if field == "type_of_action":
        return type_of_action or ""
    if field == "cross_cutting":
        return " | ".join(str(v) for v in as_list(meta.get("crossCuttingPriorities")))
    raise BuildError(f"unknown rule field: {field}")


def apply_scheme_rules(identifier, type_of_action, meta, rules) -> tuple[str | None, str | None]:
    for rule in rules:
        if re.search(rule["pattern"], field_text(rule["field"], identifier, type_of_action, meta)):
            return rule["scheme"], rule["basis"]
    return None, None


def apply_tag_rules(identifier, type_of_action, meta, rules) -> dict | None:
    """Return the first matching suggestion, or None."""
    for rule in rules:
        if re.search(rule["pattern"], field_text(rule["field"], identifier, type_of_action, meta), re.I):
            return {
                "ssh_flag": rule["ssh_flag"],
                "erc_domains": list(rule["erc_domains"]),
                "reason": rule["reason"],
            }
    return None


def parse_budget(meta: dict, identifier: str) -> dict | None:
    """Read min and max EU contribution per project from budgetOverview.

    Returns None unless the portal states both values for this topic.
    """
    raw = first(meta.get("budgetOverview"))
    if not raw:
        return None
    try:
        overview = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return None
    action_map = (overview or {}).get("budgetTopicActionMap") or {}
    mins, maxs = [], []
    for entries in action_map.values():
        for entry in as_list(entries):
            if not isinstance(entry, dict):
                continue
            # Entries look like "IDENTIFIER - TYPE OF ACTION". Match the whole
            # identifier so "...-01" does not pick up "...-01-two-stage".
            action = str(entry.get("action", ""))
            if not action.upper().startswith(identifier.upper() + " - "):
                continue
            lo, hi = entry.get("minContribution"), entry.get("maxContribution")
            # The portal stores 0/0 when it states no per-project amount
            # (e.g. ERC and MSCA), so zero means "not given".
            if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and hi > 0:
                mins.append(lo)
                maxs.append(hi)
    if not mins:
        return None
    return {"min": int(min(mins)), "max": int(max(maxs))}


def parse_stages(meta: dict) -> int | None:
    model = (clean_text(meta.get("deadlineModel")) or "").lower()
    if "two" in model or "2-stage" in model:
        return 2
    if "single" in model or "one" in model or "multiple cut-off" in model:
        return 1
    return None


def applicable_in_target_year(deadlines: list[str], stages: int | None, today: date) -> bool:
    """Can a new applicant still apply, with a deadline in TARGET_YEAR?

    Two-stage topics: the first-stage deadline is the one an applicant must
    meet, so it has to be in the target year and not yet passed.
    Single-stage and cut-off topics: any future deadline in the target year.
    """
    if not deadlines:
        return False
    parsed = sorted(date.fromisoformat(d) for d in deadlines)
    if stages == 2:
        stage_one = parsed[0]
        return stage_one.year == TARGET_YEAR and stage_one >= today
    return any(d.year == TARGET_YEAR and d >= today for d in parsed)


def topic_to_call(topic: dict, lookups: dict, today: date, checked: str) -> tuple[dict | None, str]:
    """Return (call, '') or (None, reason it was skipped)."""
    meta = topic.get("metadata") or {}
    identifier = clean_text(meta.get("identifier"))
    if not identifier:
        return None, "no identifier"

    if identifier.upper().endswith("-CANCELLED"):
        return None, "topic cancelled"

    division = match_division(identifier, lookups["divisions"])
    if division is None:
        return None, "programme not listed in programmes.json"

    deadlines = sorted({d for d in (iso_date(v) for v in as_list(meta.get("deadlineDate"))) if d})
    stages = parse_stages(meta)
    if not applicable_in_target_year(deadlines, stages, today):
        return None, f"no applicable {TARGET_YEAR} deadline"

    opening = iso_date(first(meta.get("startDate")))
    status = "forthcoming" if opening and date.fromisoformat(opening) > today else "open"
    if not opening:
        # Without an opening date, fall back to the portal label, but only
        # to choose between the two states we publish.
        status = "forthcoming" if "31094501" in [str(s) for s in as_list(meta.get("status"))] else "open"

    type_of_action = clean_text(" ".join(str(v) for v in as_list(meta.get("typesOfAction"))))
    scheme, scheme_basis = apply_scheme_rules(
        identifier, type_of_action, meta, lookups["scheme_rules"]
    )
    suggestion = apply_tag_rules(identifier, type_of_action, meta, lookups["tag_rules"])

    # Cross-check the prefix mapping against the API's programme code, for
    # programmes whose code is listed in programmes.json.
    fp_codes = [str(v) for v in as_list(meta.get("frameworkProgramme"))]
    code_names = lookups["fp_codes"]
    expected = {c for c, name in code_names.items() if name == division["programme"]}
    if expected and fp_codes and not expected & set(fp_codes):
        lookups["warnings"].add(
            f"{identifier} is mapped to {division['programme']} but has "
            f"frameworkProgramme {fp_codes} ({', '.join(code_names.get(c, 'unknown') for c in fp_codes)})"
        )

    call = {
        "identifier": identifier,
        "title": clean_text(meta.get("title")),
        "programme": division["programme"],
        "pillar_or_cluster": division["pillar_or_cluster"],
        "call_identifier": clean_text(meta.get("callIdentifier")),
        "type_of_action": type_of_action,
        "scheme": scheme,
        "scheme_basis": scheme_basis,
        "stages": stages,
        "deadlines": deadlines,
        "opening_date": opening,
        "budget_per_project_eur": parse_budget(meta, identifier),
        "status": status,
        "ssh_flag": suggestion["ssh_flag"] if suggestion else "unknown",
        "erc_domains": suggestion["erc_domains"] if suggestion else [],
        "erc_panels": [],
        "tag_status": "suggested" if suggestion else "untagged",
        "tag_note": suggestion["reason"] if suggestion else None,
        "portal_url": PORTAL_TOPIC_URL.format(identifier=identifier.lower()),
        "last_checked": checked,
        "source": "api",
    }
    return call, ""


# ---------------------------------------------------------------- manual + tags

REQUIRED_MANUAL = ("identifier", "title", "programme", "portal_url", "deadlines", "last_checked")


def load_manual(path: Path, today: date) -> list[dict]:
    entries = load_json(path, default=[])
    if not isinstance(entries, list):
        raise BuildError("manual_calls.json must contain a JSON list")
    calls = []
    for n, entry in enumerate(entries, 1):
        missing = [k for k in REQUIRED_MANUAL if not entry.get(k)]
        if missing:
            raise BuildError(f"manual_calls.json entry {n}: missing {', '.join(missing)}")
        if not str(entry["portal_url"]).startswith("https://ec.europa.eu/"):
            raise BuildError(f"manual_calls.json entry {n}: portal_url must be an ec.europa.eu link")
        deadlines = sorted({d for d in (iso_date(v) for v in as_list(entry["deadlines"])) if d})
        if len(deadlines) != len(as_list(entry["deadlines"])):
            raise BuildError(f"manual_calls.json entry {n}: deadlines must be YYYY-MM-DD dates")
        if not applicable_in_target_year(deadlines, entry.get("stages"), today):
            continue
        call = {
            "identifier": entry["identifier"],
            "title": entry["title"],
            "programme": entry["programme"],
            "pillar_or_cluster": entry.get("pillar_or_cluster"),
            "call_identifier": entry.get("call_identifier"),
            "type_of_action": entry.get("type_of_action"),
            "scheme": entry.get("scheme") if entry.get("scheme") in SCHEMES else None,
            "scheme_basis": entry.get("scheme_basis"),
            "stages": entry.get("stages") if entry.get("stages") in (1, 2) else None,
            "deadlines": deadlines,
            "opening_date": iso_date(entry.get("opening_date")),
            "budget_per_project_eur": entry.get("budget_per_project_eur"),
            "status": None,
            "ssh_flag": entry.get("ssh_flag", "unknown"),
            "erc_domains": [d for d in as_list(entry.get("erc_domains")) if d in ERC_DOMAINS],
            "erc_panels": [p for p in as_list(entry.get("erc_panels")) if ERC_PANEL_RE.match(p)],
            "tag_status": entry.get("tag_status") or "untagged",
            "tag_note": entry.get("tag_note"),
            "portal_url": entry["portal_url"],
            "last_checked": entry["last_checked"],
            "source": "manual",
        }
        opening = call["opening_date"]
        call["status"] = "forthcoming" if opening and date.fromisoformat(opening) > today else "open"
        calls.append(call)
    return calls


def parse_flag(value: str):
    value = value.strip().lower()
    if value in ("true", "yes", "1"):
        return True
    if value in ("false", "no", "0"):
        return False
    if value == "unknown":
        return "unknown"
    return None  # blank: leave the existing value


def split_list(value: str) -> list[str]:
    return [v.strip().upper() for v in re.split(r"[;,]", value or "") if v.strip()]


def load_tags(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    tags = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for n, row in enumerate(csv.DictReader(handle), 2):
            identifier = (row.get("identifier") or "").strip()
            if not identifier or identifier.startswith("#"):
                continue
            domains = split_list(row.get("erc_domains", ""))
            panels = split_list(row.get("erc_panels", ""))
            bad = [d for d in domains if d not in ERC_DOMAINS] + [p for p in panels if not ERC_PANEL_RE.match(p)]
            if bad:
                raise BuildError(f"tags.csv line {n}: unknown ERC code(s) {bad}")
            scheme = (row.get("scheme") or "").strip().lower()
            if scheme and scheme not in SCHEMES:
                raise BuildError(f"tags.csv line {n}: scheme must be individual, consortium or either")
            status = (row.get("tag_status") or "reviewed").strip().lower()
            if status not in ("reviewed", "suggested"):
                raise BuildError(f"tags.csv line {n}: tag_status must be reviewed or suggested")
            tags[identifier.upper()] = {
                "ssh_flag": parse_flag(row.get("ssh_flag", "")),
                "erc_domains": domains,
                "erc_panels": panels,
                "scheme": scheme or None,
                "tag_status": status,
                "note": (row.get("note") or "").strip() or None,
                "reviewed_by": (row.get("reviewed_by") or "").strip() or None,
            }
    return tags


def apply_tags(call: dict, tag: dict) -> None:
    if tag["ssh_flag"] is not None:
        call["ssh_flag"] = tag["ssh_flag"]
    # Panels imply their domain (SH3 -> SH).
    domains = set(tag["erc_domains"]) | {p[:2] for p in tag["erc_panels"]}
    if domains:
        call["erc_domains"] = sorted(domains)
    if tag["erc_panels"]:
        call["erc_panels"] = sorted(tag["erc_panels"])
    if tag["scheme"]:
        call["scheme"] = tag["scheme"]
        call["scheme_basis"] = "Checked against the topic conditions" + (
            f" by {tag['reviewed_by']}" if tag["reviewed_by"] else ""
        )
    call["tag_status"] = tag["tag_status"]
    call["tag_note"] = tag["note"]


# ---------------------------------------------------------------- main

def build(today: date, allow_drop: bool, data_dir: Path = DATA) -> dict:
    raw = load_json(data_dir / "raw_topics.json")
    topics = raw.get("topics")
    if not isinstance(topics, list) or not topics:
        raise BuildError("raw_topics.json has no topics")
    fetched_at = raw.get("fetched_at")
    if not fetched_at:
        raise BuildError("raw_topics.json has no fetched_at date")
    checked = fetched_at[:10]

    config = load_json(data_dir / "programmes.json")
    lookups = {
        "divisions": config["divisions"],
        "scheme_rules": config["scheme_rules"]["rules"],
        "tag_rules": config["tag_rules"]["rules"],
        "fp_codes": {k: v for k, v in config.get("framework_programme_codes", {}).items() if not k.startswith("_")},
        "warnings": set(),
    }

    calls: dict[str, dict] = {}
    skipped: dict[str, int] = {}
    unlisted_prefixes: dict[str, int] = {}
    for topic in topics:
        call, reason = topic_to_call(topic, lookups, today, checked)
        if call is None:
            skipped[reason] = skipped.get(reason, 0) + 1
            if reason.startswith("programme not listed"):
                ident = clean_text((topic.get("metadata") or {}).get("identifier")) or ""
                prefix = ident.split("-")[0]
                unlisted_prefixes[prefix] = unlisted_prefixes.get(prefix, 0) + 1
            continue
        calls[call["identifier"].upper()] = call

    for call in load_manual(data_dir / "manual_calls.json", today):
        key = call["identifier"].upper()
        if key in calls:
            print(f"build_calls.py: manual entry {call['identifier']} is also in the API data; using the API record")
            continue
        calls[key] = call

    tags = load_tags(data_dir / "tags.csv")
    for key, tag in tags.items():
        if key in calls:
            apply_tags(calls[key], tag)

    result = sorted(calls.values(), key=lambda c: (c["deadlines"][0], c["identifier"]))

    # Department and topic fit, for the guided start on the page.
    if (data_dir / "departments.json").exists():
        profiles = match.load_profiles(data_dir / "departments.json")
        descriptions = match.load_descriptions(data_dir / "descriptions.json")
        match.match_calls(result, descriptions, profiles)
        missing = sum(1 for c in result if c["identifier"].upper() not in descriptions)
        if missing:
            print(f"build_calls.py: {missing} call(s) have no cached description; matched on title only")
    if not result:
        raise BuildError(f"no calls with a {TARGET_YEAR} deadline; refusing to publish an empty file")

    previous_path = data_dir / "calls.json"
    if previous_path.exists() and not allow_drop:
        previous = load_json(previous_path)
        old_count = len(previous.get("calls", []))
        if old_count and len(result) < old_count * MIN_SHARE_OF_PREVIOUS:
            raise BuildError(
                f"call count fell from {old_count} to {len(result)}; this looks like a broken "
                "fetch. Re-run with --allow-drop if the drop is real."
            )

    for reason, count in sorted(skipped.items()):
        print(f"build_calls.py: skipped {count} topic(s): {reason}")
    if unlisted_prefixes:
        listing = ", ".join(f"{p} ({n})" for p, n in sorted(unlisted_prefixes.items(), key=lambda x: -x[1]))
        print(f"build_calls.py: identifier prefixes not in programmes.json: {listing}")
    for warning in sorted(lookups["warnings"])[:10]:
        print(f"build_calls.py: warning: {warning}")
    unused = [k for k in tags if k not in calls]
    if unused:
        print(f"build_calls.py: {len(unused)} row(s) in tags.csv match no current call")

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_refreshed": fetched_at,
        "target_year": TARGET_YEAR,
        "source": "EU Funding & Tenders Portal search API",
        "programmes": sorted({c["programme"] for c in result}),
        "call_count": len(result),
        "calls": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--today", type=date.fromisoformat, default=datetime.now(timezone.utc).date(),
                        help="treat this date as today (for testing)")
    parser.add_argument("--allow-drop", action="store_true",
                        help="publish even if the number of calls fell sharply")
    args = parser.parse_args()
    try:
        data = build(args.today, args.allow_drop)
    except BuildError as exc:
        print(f"build_calls.py: {exc}", file=sys.stderr)
        print("build_calls.py: kept the previous calls.json", file=sys.stderr)
        return 1
    out = DATA / "calls.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    print(f"build_calls.py: wrote {data['call_count']} calls to {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
