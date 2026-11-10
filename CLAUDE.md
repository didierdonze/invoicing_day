# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Monthly **Invoicing Day** for the Grammont department (Camptocamp, Odoo integrator): controls from BS ›
"How to - Invoice your project" (Confluence page 902594711), an invoicing proposal, a Confluence page
"AAAA.MM - Invoicing Day Grammont" (BS › folder *Invoicing Day* 1747615753), and client hours reports (PDF,
ported from Compass). Two skills drive it: `.claude/skills/invoicing-day/` and `.claude/skills/hours-report/`.

## Commands (run from the repo root; Python 3 stdlib only, no install)

```bash
python3 -m unittest                                   # offline tests (synthetic data) — run before committing
python3 -m unittest tests.test_page.PageTest.test_comments_round_trip   # a single test

# need the Camptocamp VPN (Odoo) — not available in cloud sessions
python3 -m invoicing_day projects                     # active Grammont projects
python3 -m invoicing_day run --month 2026-10 --out runs/2026-10/figures.json [--projects fmel_odoo …] [--no-jira]
python3 -m invoicing_day hours invoices fmel_odoo
python3 -m invoicing_day hours report fmel_odoo --from 2026-09-01 --to 2026-09-30 [--so SO-…] [--html-only]
python3 -m invoicing_day hours report fmel_odoo --invoice CI-CH26-1638

# offline
python3 -m invoicing_day page --figures runs/2026-10/figures.json [--previous prev.html [--same-page]] --out runs/2026-10/body.html
python3 -m invoicing_day diff --old runs/2026-10/figures.prev.json --new runs/2026-10/figures.json
```

Exit codes: 1 failure · 2 hours report REFUSED · 3 Odoo unreachable (VPN) · 4 Odoo refused a call · 5 config missing.

## Architecture

- `invoicing_day/odoo.py`: the only door to Odoo. XML-RPC client with a method whitelist (`READ_ONLY`)
  checked before any network call. It retries on HTTP 429, because c2c's Odoo rate-limits. Its interface
  (`search_read` / `read_group` / `fields_get` / `search_count`) is the one the ported Compass code expects.
- `invoicing_day/invoicing.py`: `build_figures()` runs every control and the proposal in a few bulk queries
  across all projects, then builds one row per project (`_row`). Everything else consumes its output,
  `figures.json`.
  - **Project first** (Didier's rule): the proposal starts from each project's *To invoice* timesheet lines
    (`timesheet_invoice_id = False`, up to month end, rounded hours), grouped by SO item. SO fields are only
    a cross-check.
  - **Active orders:** an SO is *active* when hours were booked on it in the last `ACTIVE_MONTHS` months, or
    when it was confirmed during the cycle. SO-level checks and non-T&M amounts only consider active orders.
    Old orders often stay "to invoice" in Odoo forever; they are reported as `STALE_TO_INVOICE`, not counted.
  - **Dashboard domains** (Invoicing Dashboards 01–04, CRM) are read live from the Odoo window actions and
    evaluated with `uid` and `context_today()`, so the checks follow any change Odoo makes to them.
  - **Status per project:** red > yellow > green > idle, computed from the flags.
- `invoicing_day/rules.py`: every id, threshold and mapping, overridable with `INVOICING_*` env vars. This
  includes the dashboard action ids, the functional/technical product/job mapping and the tolerances.
- `invoicing_day/page.py` and `report.py`: deterministic rendering of `figures.json` into the Confluence
  body (Atlassian MCP HTML format: panels, status lozenges, `<details>`) and into the French `report.md`.
  - The **Comments** column is the only content carried over, extracted verbatim per project from the
    previous edition (`--previous`) or from the page being updated (`--same-page`, which keeps local ids).
  - Since October 2026 the monthly page is a Confluence **live doc** (`subtype: "live"`, no draft): the
    team types straight into it, so the skill re-reads the page just before each full-body update.
  - The body must fit in one MCP call (~50 k characters for 39 projects). The full detail lives in
    `figures.json` and `report.md`.
- `invoicing_day/jira.py`: read-only Jira Cloud REST (enhanced search + worklogs). It is optional: without
  `~/.config/invoicing_day/jira.env` the Jira controls are reported as skipped, never as passed.
- `invoicing_day/hours/` and `pdf.py`: the hours report ported from Compass
  (`~/.openclaw/workspace/compass`, commit 506671a). Changes from the Compass version:
  - The scope comes from the project (`hours/scope.py`: the orders its tasks and timesheet lines point to;
    `--so` can only narrow them), instead of Compass's registry.
  - Files go to `runs/AAAA-MM/hours/<project>/`.
  - It keeps Compass's rules: quantities only (no money, names or descriptions are ever read), `⚠`
    warnings for the PM only, refusal rather than a wrong document. The PDF is printed by headless Chrome.

## Rules

- **Read-only on Odoo and Jira.** Never widen `READ_ONLY`. Invoices, mass edits and activities stay manual.
- **`runs/` is git-ignored and must stay so:** it holds customer financial data.
- **Credentials live outside the repo:** `~/.config/timesheetMagician/odoo.env` (shared with Didier's other
  tools) and `~/.config/invoicing_day/jira.env` (template in `config/`).
- **Cloud sessions (claude.ai/code)** see only what is committed and have no VPN and no Chrome. Edit code and
  run `python3 -m unittest` there; actual runs and PDFs happen locally.
- **Figures come from the script:** never compute or patch a figure in a page, report or message.
- **Odoo facts and open points:** the Odoo facts behind the controls (models, fields, selection values, ids)
  are in `.claude/skills/invoicing-day/references/odoo-sources.md`; update it when Odoo changes. Still to
  confirm with Didier:
  - the 2RO/2UP rounding rule (rounding is reported only, without a flag);
  - the functional/technical job mapping;
  - the page title;
  - Jira worklogs vs Tempo, which has not been checked against live data yet (no token).
