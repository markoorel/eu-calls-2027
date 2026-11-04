"""Fetch grant topics from the Funding & Tenders Portal search API (SEDIA).

This is the only file that talks to the API. The API is undocumented and can
change without notice; if the nightly job breaks, start looking here.

Writes data/raw_topics.json. If anything goes wrong (network error, odd
response, fewer results than the API says it has) the script exits with an
error and leaves the existing file untouched.

Usage:  python scripts/fetch.py
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_FILE = ROOT / "data" / "raw_topics.json"
DESCRIPTIONS_FILE = ROOT / "data" / "descriptions.json"

API_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
PAGE_SIZE = 100
MAX_PAGES = 200          # safety stop: 20,000 results is far more than expected
TIMEOUT_SECONDS = 60
RETRIES = 3
USER_AGENT = "eu-calls-2027-finder (static site; nightly refresh)"

TYPE_GRANT = "1"
STATUS_FORTHCOMING = "31094501"
STATUS_OPEN = "31094502"
STATUS_CLOSED = "31094503"   # not requested; kept here for reference

# Filters must go in multipart form fields. A JSON request body is silently
# ignored by the API, which then returns the whole dataset.
QUERY = {
    "bool": {
        "must": [
            {"terms": {"type": [TYPE_GRANT]}},
            {"terms": {"status": [STATUS_FORTHCOMING, STATUS_OPEN]}},
        ]
    }
}
LANGUAGES = ["en"]
# Sort by identifier: it is unique, so pages do not overlap. Sorting by
# startDate was unstable across pages (ties reshuffled), which duplicated some
# topics and silently dropped others (checked 2026-11-04).
SORT = {"field": "identifier", "order": "ASC"}
# The portal itself lists a few topics twice; more than this share of
# duplicates means paging went wrong and the data is incomplete.
MAX_DUPLICATE_SHARE = 0.01

# Metadata fields to keep. Long description fields are dropped to keep the
# committed file small. Add a name here if build_calls.py needs a new field.
KEEP_METADATA = {
    "identifier", "title", "callIdentifier", "callTitle", "type", "status",
    "deadlineDate", "deadlineModel", "startDate", "frameworkProgramme",
    "programmePeriod", "programmeDivision", "typesOfAction", "budgetOverview",
    "crossCuttingPriorities", "keywords", "tags", "language", "es_SortDate",
}


class FetchError(Exception):
    pass


def _multipart(fields: dict[str, object]) -> tuple[bytes, str]:
    """Encode fields as multipart/form-data, each part sent as JSON."""
    boundary = uuid.uuid4().hex
    lines: list[bytes] = []
    for name, value in fields.items():
        lines += [
            f"--{boundary}".encode(),
            f'Content-Disposition: form-data; name="{name}"; filename="blob"'.encode(),
            b"Content-Type: application/json",
            b"",
            json.dumps(value).encode(),
        ]
    lines += [f"--{boundary}--".encode(), b""]
    return b"\r\n".join(lines), f"multipart/form-data; boundary={boundary}"


def fetch_page(page_number: int) -> dict:
    params = {
        "apiKey": "SEDIA",
        "text": "***",
        "pageSize": str(PAGE_SIZE),
        "pageNumber": str(page_number),
    }
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    body, content_type = _multipart(
        {"query": QUERY, "languages": LANGUAGES, "sort": SORT}
    )
    last_error: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": content_type,
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as resp:
                payload = json.load(resp)
            if not isinstance(payload, dict) or "results" not in payload:
                raise FetchError(f"page {page_number}: response has no 'results' key")
            return payload
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, FetchError) as exc:
            last_error = exc
            if attempt < RETRIES:
                time.sleep(2 ** attempt)
    raise FetchError(f"page {page_number} failed after {RETRIES} attempts: {last_error}")


def slim(result: dict) -> dict:
    metadata = result.get("metadata") or {}
    return {
        "url": result.get("url"),
        "reference": result.get("reference"),
        "metadata": {k: v for k, v in metadata.items() if k in KEEP_METADATA},
    }


def first(value):
    """Metadata values arrive as lists, even single values."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def fetch_all() -> dict:
    first_page = fetch_page(1)
    total = first_page.get("totalResults")
    if not isinstance(total, int) or total <= 0:
        raise FetchError(f"unexpected totalResults: {total!r}")

    # Guard against the 'JSON body ignored' failure mode: the whole portal
    # dataset (all statuses, all types) runs to tens of thousands of records.
    if total > 20000:
        raise FetchError(
            f"API reports {total} results; the filters were probably ignored"
        )

    results = list(first_page["results"])
    pages = -(-total // PAGE_SIZE)
    if pages > MAX_PAGES:
        raise FetchError(f"{pages} pages exceeds the safety limit of {MAX_PAGES}")
    for page_number in range(2, pages + 1):
        results.extend(fetch_page(page_number)["results"])
        time.sleep(0.5)  # be polite

    if len(results) < total:
        raise FetchError(f"received {len(results)} of {total} results; refusing partial data")

    topics: dict[str, dict] = {}
    for result in results:
        item = slim(result)
        meta = item["metadata"]
        identifier = first(meta.get("identifier"))
        if not identifier:
            continue
        if first(meta.get("type")) not in (None, TYPE_GRANT):
            continue
        # Prefer the English record if the API returns more than one language.
        existing = topics.get(identifier)
        if existing is None or first(meta.get("language")) == "en":
            topics[identifier] = item

    if not topics:
        raise FetchError("no topics with an identifier in the response")
    duplicates = len(results) - len(topics)
    if duplicates > total * MAX_DUPLICATE_SHARE:
        raise FetchError(
            f"{duplicates} duplicate rows in {len(results)}; paging is unstable "
            "and some topics were probably missed"
        )

    return {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": API_URL,
        "query": QUERY,
        "total_results": total,
        "topic_count": len(topics),
        "topics": sorted(topics.values(), key=lambda t: first(t["metadata"]["identifier"])),
    }


# ---------------------------------------------------------------- descriptions
#
# The search API does not return full topic descriptions. Each topic has a
# JSON file on the portal with the description as HTML. The file name must be
# the identifier in lower case (upper case returns 404; checked 2026-11-04).

TOPIC_DETAILS_URL = (
    "https://ec.europa.eu/info/funding-tenders/opportunities/data/topicDetails/{id}.json"
)
DESCRIPTION_YEAR = "2027"          # only topics with a deadline in this year
FULL_REFRESH_DAYS = 7
DESCRIPTION_DELAY_SECONDS = 0.3


def metadata_hash(meta: dict) -> str:
    return hashlib.sha256(json.dumps(meta, sort_keys=True).encode()).hexdigest()[:16]


def html_to_text(raw: str) -> str:
    """Plain text from the portal's description HTML."""
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw or "")
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "\n- ", text)
    text = re.sub(r"(?i)</?(b|i|u|em|strong|span|a|sup|sub|abbr)\b[^>]*>", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def fetch_topic_details(identifier: str) -> dict:
    url = TOPIC_DETAILS_URL.format(id=urllib.parse.quote(identifier.lower()))
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as resp:
        details = json.load(resp)
    details = details.get("TopicDetails", details)
    if "description" not in details:
        raise FetchError(f"{identifier}: topic details have no description")
    return details


def update_descriptions(topics: list[dict], cache_path: Path = DESCRIPTIONS_FILE,
                        now: datetime | None = None, fetcher=fetch_topic_details) -> dict:
    """Refresh the description cache for topics with a DESCRIPTION_YEAR deadline.

    Fetches topics that are new or whose metadata changed, or all of them if
    the last full refresh is FULL_REFRESH_DAYS old. A failed fetch keeps the
    cached text. Topics no longer in scope are dropped from the cache.
    """
    now = now or datetime.now(timezone.utc)
    cache = {"last_full_refresh": None, "topics": {}}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("fetch.py: descriptions.json unreadable; rebuilding it", file=sys.stderr)
    old = cache.get("topics", {})
    last_full = cache.get("last_full_refresh")
    full = not last_full or now - datetime.fromisoformat(last_full.replace("Z", "+00:00")) >= timedelta(days=FULL_REFRESH_DAYS)

    in_scope = {}
    for topic in topics:
        meta = topic["metadata"]
        if any(str(d).startswith(DESCRIPTION_YEAR) for d in meta.get("deadlineDate") or []):
            in_scope[first(meta["identifier"])] = metadata_hash(meta)

    new_topics, fetched, failed = {}, 0, []
    for identifier, digest in sorted(in_scope.items()):
        entry = old.get(identifier)
        if entry and not full and entry.get("metadata_hash") == digest:
            new_topics[identifier] = entry
            continue
        try:
            details = fetcher(identifier)
            new_topics[identifier] = {
                "text": html_to_text(details.get("description", "")),
                "tags": [str(t) for t in details.get("tags") or []],
                "keywords": [str(k) for k in details.get("keywords") or []],
                "metadata_hash": digest,
                "fetched_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            fetched += 1
            time.sleep(DESCRIPTION_DELAY_SECONDS)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, FetchError, ValueError) as exc:
            failed.append(identifier)
            if entry:
                new_topics[identifier] = entry  # keep the old text, retry next run
            print(f"fetch.py: description for {identifier} failed ({exc}); "
                  f"{'kept the cached text' if entry else 'no cached text'}", file=sys.stderr)

    # Only record a full refresh if most fetches worked.
    if full and len(failed) <= len(in_scope) * 0.1:
        last_full = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    result = {"last_full_refresh": last_full, "topics": new_topics}
    write_atomic(cache_path, result)
    print(f"fetch.py: descriptions: {len(new_topics)} cached, {fetched} fetched"
          f"{' (full refresh)' if full else ''}, {len(failed)} failed")
    return result


def write_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    try:
        data = fetch_all()
    except FetchError as exc:
        print(f"fetch.py: {exc}", file=sys.stderr)
        print("fetch.py: kept the previous raw_topics.json", file=sys.stderr)
        return 1
    write_atomic(OUT_FILE, data)
    print(f"fetch.py: wrote {data['topic_count']} topics "
          f"({data['total_results']} results) to {OUT_FILE.relative_to(ROOT)}")
    # Descriptions are extra detail for matching. Problems here never block
    # the topic data; individual failures keep the cached text.
    try:
        update_descriptions(data["topics"])
    except Exception as exc:  # noqa: BLE001
        print(f"fetch.py: description update stopped ({exc}); kept descriptions.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
