# EU Calls 2027 Finder

A static page listing EU research calls with a deadline in 2027, for academics at the
Prague University of Economics and Business. Project rules are in `CLAUDE.md`.

## How the data flows

1. `scripts/fetch.py` asks the Funding & Tenders Portal search API for forthcoming and open
   grant topics and saves them to `data/raw_topics.json`.
2. `scripts/build_calls.py` keeps topics a new applicant can still apply to with a 2027
   deadline, maps them using `data/programmes.json`, adds `data/manual_calls.json`, applies
   `data/tags.csv`, and writes `data/calls.json`.
   It also scores each call against the departments and areas of interest in
   `data/departments.json` (via `scripts/match.py`) and stores the matched terms.
3. `site/` reads `calls.json` in the browser.

`fetch.py` also keeps `data/descriptions.json`: plain-text descriptions, tags and
keywords for topics with a 2027 deadline, used only for matching. It fetches a topic's
description when the topic is new or its metadata changed, and refreshes all of them
once a week. A failed fetch keeps the old text.

To check department matches: `python scripts/match.py arts-management marketing`

ERC panel codes come from Annex 1 of the ERC Work Programme 2027, saved as
`data/ERC_Work_Programme_2027.pdf`.

Either script stops with an error, leaving the old file in place, if the data looks wrong:
an empty result, a partial download, or a fall of more than half in the number of calls.

## Running locally (Python 3.11, no packages needed)

    python scripts/fetch.py
    python scripts/build_calls.py
    python -m http.server 8000

Then open http://localhost:8000/site/

Tests use invented sample topics and need no network:

    python -m unittest discover -s tests -v

## Editing tags and manual calls

See `data/MANUAL_AND_TAGS.md`. Pushing a change to `tags.csv` or `manual_calls.json` to
`main` rebuilds and redeploys the page without fetching from the API again.

## Deployment

`.github/workflows/refresh.yml` runs nightly at 02:17 UTC, commits changed data and deploys
to GitHub Pages. In the repository settings, set Pages → Source to "GitHub Actions".
