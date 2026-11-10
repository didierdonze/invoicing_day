---
name: hours-report
description: Build a client-facing hours report (PDF, Camptocamp charter) for ONE project, for ONE invoice or ONE date period — sale-order lines ordered / delivered / invoiced / this invoice-or-period, and rounded hours per Odoo task. Asks which invoice or which period first. Ported from Compass. Trigger: "rapport d'heures", "Stundenrapport", "hours report", "rapport à joindre à la facture", step 6 of the Invoicing Day, or any request for an hours / timesheet report to send to a client.
allowed-tools:
  - Bash(python3 -m invoicing_day hours:*)
  - Bash(python3 -m invoicing_day projects:*)
---

# Hours Report (ported from Compass, commit 506671a)

Prepare the hours report a PM sends to the client WITH the PM, never FOR the client. You frame the request,
run one deterministic command, explain what it found, and hand the PDF to the PM. All commands run from the
repo root: `cd ~/nobackup/invoicing_day`.

Differences with Compass: the orders come **from the project** (its tasks and timesheet lines), not from a
registry — `--so` can only narrow them; files go to `runs/AAAA-MM/hours/<project>/`.

## Hard rules (non-negotiable)
- **Fresh run every time.** Never reuse a PDF, a figure or an invoice list from an earlier turn — the report
  is regenerated from live Odoo each time it is asked for.
- **Quantities only.** The report carries hours and order quantities. No money, no employee names, no
  timesheet descriptions — not in the PDF, not in your chat message about it. The command never reads them;
  do not add them from anywhere else.
- **Warnings are for the PM.** Every `⚠` the command prints is something the PM must know BEFORE forwarding;
  none of it is in the PDF. Explain each one; never drop one because the report "looks fine".
- **A refusal is an answer.** `REFUSED:` (exit 2) means the command would rather produce nothing than a wrong
  client document. Say why in one sentence and propose the alternative it names (usually the other mode).
  **Never switch mode without the PM's GO.**
- **Never edit the HTML or the PDF by hand**, and never re-type the figures into a message as if they were the
  report. If something is wrong, it is wrong in Odoo — say where.
- **Nothing is sent to the client and nothing is attached in Odoo.** The PM reads the PDF, attaches it to the
  invoice and forwards it. Odoo needs the c2c VPN: if it is unreachable (exit 3), say so and stop. In a cloud
  session there is no VPN and no Chrome: only `--html-only` on code changes, never a client document.

## STEP 1 — Frame (ask, then PAUSE)
1. **Which project?** The project code (e.g. `fmel_odoo`) or its id. If the PM did not name one, or the name is
   ambiguous, run `python3 -m invoicing_day projects` and ask.
2. **Ask: for which invoice, or for which period?** One question, both options:
   - **Invoice** → run `python3 -m invoicing_day hours invoices <project>` and show the list (number, date,
     state, linked hours). The PM picks one. A draft has no number yet — it is picked by its id. An invoice
     with **0 linked hours** will be refused in invoice mode: say so now and offer the period instead.
   - **Period** → get explicit, inclusive start and end dates. Turn "septembre" into
     `2026-09-01 → 2026-09-30` (dd.mm.yyyy when you show them) and confirm them. A period ending today or later
     is accepted, but hours may still be booked — mention it.
   - If the project has several orders and the PM wants one report per order, add `--so SO-…`.
3. **PAUSE** until the mode and the reference (invoice number/id, or both dates) are explicit and confirmed.

## STEP 2 — Generate
- Invoice: `python3 -m invoicing_day hours report <project> --invoice <number or id>`
- Period: `python3 -m invoicing_day hours report <project> --from YYYY-MM-DD --to YYYY-MM-DD`

The command prints a summary, writes the PDF (plus its `.html` and `.json` trace) under
`runs/AAAA-MM/hours/<project>/`, and prints the PDF path. Exit 2 = `REFUSED`, exit 1 = failure.

## STEP 3 — Read the summary to the PM (conclusion first)
1. **One line**: total rounded hours, number of tasks and orders, pages, language — and which invoice or
   period. E.g. "Rapport prêt : 59.53 h sur 4 tâches, facture CI-CH26-1258 du 11.08.2026, 1 page, en français."
2. **Every `⚠`, in plain words, with what it means for the client**:
   - `CONSISTENCY` — the invoice's quantities and the hours behind it disagree; the client WILL see two
     different totals. Do not forward before the PM has looked.
   - `DELIVERED_MISMATCH` — Odoo's "Livré" figure is not the sum of the rounded hours on that line; the order
     table would contradict itself.
   - `DRAFTS_IN_INVOICED` (ℹ, not ⚠) — "Facturé" counts draft invoices, exactly as the order line does in Odoo;
     the client has not received those yet. Mention it, no action needed.
   - `UNLINKED_HOURS` / `OTHER_SO_HOURS` — hours booked in the period or on the invoice that sit outside these
     orders, therefore NOT in the report. Fine if they are internal (or excluded on purpose with `--so`); a
     question if they should have been billed.
   - `ODOO_TERM` — a task or line name in Odoo contains a word never shown to a client (e.g. "marge"). The
     name is printed as Odoo holds it: the PM decides.
   - `PERIOD_OPEN`, `DRAFT_INVOICE`, `INVOICE_UNLINKED_LINE`, `FONT_FALLBACK`, `LONG_REPORT` — say what the
     message says, briefly.
   Infos (`ℹ`) only when they matter for the PM's decision.
3. On `REFUSED:` — explain, propose the alternative, wait for the GO.

## STEP 4 — Deliver
Say that the PM should **read the report before forwarding it**, give the PDF path exactly as printed by the
command, and remind that it is to be attached to the invoice in Odoo (How-to step 6) — the next Invoicing Day
run ticks "6 Report" when it finds it there.
