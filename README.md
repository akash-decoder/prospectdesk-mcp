# ProspectDesk MCP

A free, local-first prospecting workspace for finding businesses, qualifying leads and planning follow-ups in Codex. A browser interface and a stdio MCP server share one SQLite database. No ProspectDesk subscription, API key or Apollo account is required.

## Install on Windows and connect Codex

Install Python 3.11+ and Codex CLI. Open PowerShell in the project folder (after extracting the source archive or cloning the repository).

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
$prospectPython = (Resolve-Path .\.venv\Scripts\python.exe).Path
codex mcp add prospectdesk -- "$prospectPython" -m prospectdesk mcp
codex mcp get prospectdesk
```

On Linux or macOS, use:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
codex mcp add prospectdesk -- "$PWD/.venv/bin/python" -m prospectdesk mcp
codex mcp get prospectdesk
```

Start a new local Codex session and type `/mcp` to see the tools. Keep the virtual environment in place. The command registers an absolute interpreter path that works from other project directories. [Official OpenAI documentation](https://developers.openai.com/codex/mcp/)

## Try it in two minutes

On Windows, load the three fictional sample leads and launch the local workspace:

```powershell
.\.venv\Scripts\python.exe -m prospectdesk demo
.\.venv\Scripts\python.exe -m prospectdesk web
```

On macOS/Linux replace `.\.venv\Scripts\python.exe` with `.venv/bin/python`. Open **http://127.0.0.1:8840**. You can also start with an empty database and import a UTF-8 CSV or run a map search. Codex can launch the MCP server independently of the browser workspace.

Try this in Codex after loading the sample:

> Use ProspectDesk to find leads in Hull with an email and no website listed. Add those leads to a shortlist named Hull web design. Show me each company and draft an introduction for the photography studio offering a free portfolio-site preview.

## Data and workflows

| Workflow | What happens |
| --- | --- |
| Discover | Search ten business categories within 100–5,000 metres of a chosen latitude/longitude. The public Overpass API returns up to 100 named OpenStreetMap listings per request. Existing map object IDs are matched on subsequent searches. |
| Import | Paste CSV text or select a UTF-8 file. Only the `company` column is required. Import validates the full batch before committing. Up to 5,000 rows and 2 MB per batch. |
| Qualify | Filter by company or person, job title, industry, location, available email/phone, website listing, stage or shortlist. |
| Organize | Save selected records to named lists, record the next follow-up date, add notes and move a lead through the pipeline. |
| Prepare outreach | Ask Codex to draft an editable introduction using a saved lead and your own offer. Sending is manual. |
| Export | Download all matching records in the browser or request a page of CSV text from Codex. Map records include attribution and a source link. |

CSV headers:

```csv
company,person,title,industry,location,email,phone,website,source_url
Example Studio,Alex Example,Owner,Photography,Hull,studio@example.com,,,
```

CSV deduplication uses company, person, location and email together, ignoring case and surrounding whitespace. Changing an identity field creates a new record. Blank fields on a repeated import preserve previously supplied information. CSV and map records have separate identities. Export is designed for spreadsheets and quotes formula-like values with an apostrophe.

## MCP tools

| Tools | Purpose |
| --- | --- |
| `discovery_categories`, `discover_businesses` | Find and save businesses from a bounded map area |
| `import_leads`, `search_leads`, `get_lead` | Import and query the local database |
| `add_to_list`, `list_shortlists` | Group leads and inspect memberships |
| `update_lead`, `draft_outreach` | Maintain pipeline notes, schedule a follow-up date and prepare copy |
| `export_leads` | Return a filtered CSV page with pagination metadata |

### Scope of the Apollo review

The supplied sign-up page describes data access, lead filtering and multichannel engagement. ProspectDesk independently implements discovery, filtering, lists and outreach preparation from that public description. This review covered published product behavior. Apollo's private backend and contact database were not inspected. [Apollo sign-up page](https://www.apollo.io/lp/sign-up) · [Apollo prospecting overview](https://www.apollo.io/product/prospect)

OpenStreetMap discovery returns business-level records. Coverage depends on the category and area. An empty website field means the source has no website listed. Location is populated from available address tags. Named contacts and titles come from your own CSV. ProspectDesk has no verified-contact database, email verification, automated campaign sending or dialer.

The software is MIT-licensed. Map data is © OpenStreetMap contributors and licensed separately under the ODbL. Public Overpass availability and rate limits can affect live searches. CSV import and local search work offline after installation. [OpenStreetMap attribution and license](https://www.openstreetmap.org/copyright) · [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API)

### Storage and tests

The browser app binds to loopback and is intended for one trusted local user. The default database is `~/.prospectdesk/leads.sqlite3`. To choose a different file, set `PROSPECTDESK_DB` to the same absolute path for the web command and the MCP server. For MCP registration, pass `--env PROSPECTDESK_DB=...` before the command separator. The repository contains only code and fictional examples.

Run `python -m unittest -v` with the installed dependencies. Tests cover imports, duplicate handling, retries, filters, shortlist transactions, exports, the local web interface, a simulated Overpass provider and a real MCP stdio session.
