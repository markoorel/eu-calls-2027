"""Fetch grant topics from the Funding & Tenders Portal search API (SEDIA).

This is the only file that talks to the API. The API is undocumented and can
change without notice; if the nightly job breaks, start looking here.

Writes data/raw_topics.json. If anything goes wrong (network error, odd
response, fewer results than the API says it has) the script exits with an
error and leaves the existing file untouched.

Usage:  python scripts/fetch.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_FILE = ROOT / "data" / "raw_topics.json"

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
    return 0


if __name__ == "__main__":
    sys.exit(main())
