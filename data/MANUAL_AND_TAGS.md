# Editing manual_calls.json and tags.csv

## tags.csv
One row per topic that someone has checked. Empty cells leave the automatic value alone.

| column | values |
|---|---|
| identifier | topic identifier exactly as on the portal, e.g. HORIZON-CL2-2027-01-DEMOCRACY-01 |
| tag_status | `reviewed` (default) or `suggested` |
| ssh_flag | `true`, `false` or `unknown` |
| erc_domains | `SH`, `PE`, `LS`, separated by `;` |
| erc_panels | e.g. `SH1;SH3`. Each panel also adds its domain |
| scheme | `individual`, `consortium` or `either`. Set this only after reading the topic conditions |
| reviewed_by | initials of the person who checked |
| note | short free text, shown on the page |

Example row:

    HORIZON-CL2-2027-01-DEMOCRACY-01,reviewed,true,SH,SH2;SH3,consortium,MO,Political science and sociology

## manual_calls.json
A JSON list for calls that the API does not return. Each entry needs `identifier`, `title`,
`programme`, `portal_url` (an ec.europa.eu link), `deadlines` (list of YYYY-MM-DD) and
`last_checked` (YYYY-MM-DD). Optional: `pillar_or_cluster`, `call_identifier`,
`type_of_action`, `scheme`, `stages`, `opening_date`, `budget_per_project_eur`
(`{"min": ..., "max": ...}`), `ssh_flag`, `erc_domains`, `erc_panels`, `tag_status`, `tag_note`.
Copy values from the portal. Leave anything you cannot confirm out.
