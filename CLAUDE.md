# EU Calls 2027 Finder

## Purpose
A free web page that helps academics at the Prague University of Economics and
Business find EU research calls with a deadline in 2027. Users filter by programme,
discipline, scheme type and deadline, then follow a link to the official
Funding & Tenders Portal topic page, which stays the authoritative source.

## Users
Academics across all disciplines, many in social sciences and humanities.
Most are not grant specialists. They want to know quickly: is there a call
for my field, can I apply alone or do I need a consortium, and when is it due.

Primary users: staff and doctoral candidates at the Faculty of Business
Administration (FPH), VŠE, from nine departments: Arts Management,
Entrepreneurship, Human Resource Management, Logistics, Management,
Marketing, Managerial Economics, Strategy, Managerial Psychology and
Sociology. Most do not know EU programme vocabulary (clusters, ERC panels,
types of action), so the page should start from their department.

## Design
- Colour tokens: FPH blue #00649C (header band, buttons, links, selected
  cards), hover and focus ring #004E7A, tint #E8F1F7 (selected cards,
  badges), body text #4A4A49, headings #000000, borders #D9DEE2.
- Font stack: "Gill Sans", "Gill Sans MT", "Myriad Pro", Calibri,
  system-ui, sans-serif. Do not bundle font files (Gill Sans Pro is
  licensed).
- Do not use the VŠE or FPH logo.
- Footer must always contain: "Coded with love by Marko Orel".

## Stack (keep it this simple)
- Python 3.11 scripts in /scripts for fetching and cleaning data
- Data files in /data (raw_topics.json, calls.json, manual_calls.json, tags.csv)
- A static site in /site: index.html, app.js, style.css; vanilla JavaScript,
  no framework, no build step
- GitHub Actions for a nightly data refresh; GitHub Pages for hosting
- No database, no user accounts, no tracking or analytics

## Data source
The public SEDIA search API used by the Funding & Tenders Portal:
POST https://api.tech.ec.europa.eu/search-api/prod/rest/search?apiKey=SEDIA&text=***
- It is undocumented and can change without notice. Keep request code in one
  place (scripts/fetch.py) so it is easy to fix.
- Send filters as multipart form fields ("query", "languages", "sort").
  A plain JSON body is silently ignored and returns the whole dataset.
- Grant topics: type 1. Status: 31094501 forthcoming, 31094502 open,
  31094503 closed. Horizon Europe frameworkProgramme: 43108390 (verify).
- Metadata values arrive as lists, even single values.
- Status labels are unreliable; decide what to keep from deadline dates.

## Fields for each call (calls.json)
identifier, title, programme, pillar_or_cluster, call_identifier,
type_of_action, scheme (individual | consortium | either), stages (1 or 2),
deadlines (list of ISO dates), opening_date, budget_per_project_eur (min, max),
status (forthcoming | open), ssh_flag (true | false | unknown),
erc_domains (list, e.g. SH, PE, LS), erc_panels (list, e.g. SH3),
tag_status (reviewed | suggested | untagged), portal_url, last_checked

## Rules
- Never invent or guess a deadline, budget or eligibility rule. If a value is
  missing, leave it empty and show "check portal" on the page.
- The site never decides eligibility. It marks likely fit and links to the
  official rules.
- Every call on the page links to its official portal topic page.
- Show the date the data was last refreshed at the top of the page.
- If a nightly fetch fails, keep the previous calls.json; never publish an
  empty or partial file.
- Programme names live in the data, not hard-coded in the page, so calls from
  the next framework programme can be added later.
- British spelling in all text on the page.
- Explain what you plan to change before editing more than one file.
