# EU Calls 2027 Finder

A static page listing EU research calls with a deadline in 2027, for researchers at the
Faculty of Business Administration (FPH), VŠE. Live at
https://mapkoloco.github.io/eu-calls-2027/. Project rules are in `CLAUDE.md`.

It is an independent staff tool, not an official VŠE service. The EU Funding & Tenders
Portal stays the authoritative source for every call.

## What the page does

- **Guided start.** Three skippable questions: where you work (nine FPH departments,
  "Another faculty or unit", or one of ten areas of interest), what you are looking for
  (own project, consortium, doctoral training or staff exchanges, everything), and when you
  defended your PhD.
- **Results in two groups.** Calls open to all fields (ERC frontier grants, MSCA, EIC
  Pathfinder Open) come first; then calls that match the chosen department or topic, best
  match first. Each card says who applies, how many days are left, whether the call is
  two-stage, the budget per project when known, and why it may fit ("Matches your
  department's terms: …").
- **Career stage.** Only labels ERC Consolidator and MSCA calls ("Likely fits your career
  stage", "Check eligibility" or a neutral note) with the rule and a link to the work
  programme. It never hides a call and never decides eligibility.
- **Month strip**, **glossary** of EU terms, **advanced filters** (the original filters),
  and a **shortlist** saved only in the visitor's browser (`localStorage`), with "Copy list"
  and "Download as CSV".
- **Shareable links.** Every choice is kept in the address, for example
  `?dept=arts-management&want=own-project&stage=2012-2021` or `?topic=esg&month=9`.
  Parameters: `dept` (department id or `other`), `topic`, `want` (`own-project`,
  `consortium`, `training`, `all`), `stage` (`phd`, `2022-plus`, `2012-2021`,
  `before-2012`), plus `q`, `programme`, `cluster`, `discipline`, `scheme`, `month`, `open`.

No cookies, accounts, tracking or analytics.

## How the data flows

1. `scripts/fetch.py` asks the Funding & Tenders Portal search API for forthcoming and open
   grant topics and saves them to `data/raw_topics.json`. It also keeps
   `data/descriptions.json`: plain-text descriptions, tags and keywords for topics with a
   2027 deadline, used only for matching. A description is fetched when the topic is new or
   its metadata changed, and all of them once a week. A failed fetch keeps the old text.
2. `scripts/build_calls.py` keeps topics a new applicant can still apply to with a 2027
   deadline, maps them using `data/programmes.json`, adds `data/manual_calls.json`, applies
   `data/tags.csv`, scores each call against `data/departments.json` (via
   `scripts/match.py`), and writes `data/calls.json`. It also copies the department names
   and the career-stage rules from `data/career_stages.json` into `calls.json`, so the page
   loads one file.
3. `site/` (plain HTML, CSS and JavaScript) reads `calls.json` in the browser.

Either script stops with an error, leaving the old file in place, if the data looks wrong:
an empty result, a partial or unstable download, or a fall of more than half in the number
of calls.

## Files people are expected to edit

| File | What it holds | Who should check it |
|---|---|---|
| `data/departments.json` | search terms and ERC panels per department and area of interest | heads of department |
| `data/career_stages.json` | career-stage wording per scheme, with the rule and its source | whoever owns the site, each new work programme |
| `data/tags.csv`, `data/manual_calls.json` | reviewed discipline tags and calls the API misses; see `data/MANUAL_AND_TAGS.md` | project office |
| `data/programmes.json` | programme and cluster names, "who applies" rules, purpose rules | developer |

To see how a department's terms perform:

    python scripts/match.py arts-management marketing

ERC panel codes come from Annex 1 of the ERC Work Programme 2027, saved as
`data/ERC_Work_Programme_2027.pdf`. Panel matches count in the scoring but are not shown on
the page until `tags.csv` gives calls their panels.

## Design

Colours and type follow the FPH graphic manual (tokens in `CLAUDE.md` and at the top of
`site/style.css`). No logo is used. `scripts/check_contrast.py` checks every colour pair
against WCAG AA and runs as part of the tests.

## Running locally (Python 3.11, no packages needed)

    python scripts/fetch.py
    python scripts/build_calls.py
    python -m http.server 8000

Then open http://localhost:8000/site/

Tests use invented sample topics and need no network:

    python -m unittest discover -s tests -v

## Deployment

`.github/workflows/refresh.yml` runs nightly at 02:17 UTC: fetch, build, test, commit changed
data, deploy to GitHub Pages. A push to `main` that changes the site, scripts or edited data
files rebuilds and redeploys without fetching again. In the repository settings, Pages →
Source must be "GitHub Actions".
