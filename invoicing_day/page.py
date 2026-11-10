"""Confluence page body (Atlassian HTML format) from figures.json — deterministic.

The page is "AAAA.MM - Invoicing Day Grammont" in BS › folder Invoicing Day (1747615753).
Everything on it comes from figures.json; the only thing carried over is the Comments column,
copied verbatim per project from the previous edition (or from the page being updated).

HTML format: see the Atlassian MCP `getContentFormatGuide` (createConfluencePage) — panels,
status lozenges, task lists in table cells, <details> expands, data-background on cells.
"""
import html
import re
from html.parser import HTMLParser

PARENT_FOLDER_ID = "1747615753"
SPACE_KEY = "BS"
STATUS = {"red": ("red", "TO FIX", "#FFEBE6"), "yellow": ("yellow", "TO CHECK", "#FFFAE6"),
          "green": ("green", "READY", "#E3FCEF"), "idle": ("neutral", "NOTHING", None)}
KIND_LABEL = {"tm": "Time & materials", "block": "Prepaid / ordered qty", "milestone": "Milestones",
              "manual": "Manual", "subscription": "Subscription"}
LEVEL_ICON = {"red": "🔴", "yellow": "🟡", "info": "ℹ️"}
COLWIDTHS = (230, 110, 220, 300, 200, 400)
HOWTO = "https://camptocamp.atlassian.net/wiki/spaces/BS/pages/902594711/How+to+-+Invoice+your+project"


def title(fig):
    return f"{fig['month'].replace('-', '.')} - Invoicing Day Grammont"


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def money(x, cur=""):
    if x is None:
        return "—"
    s = f"{x:,.2f}".replace(",", "'")
    return f"{cur} {s}".strip()


def hrs(x):
    return "—" if x is None else f"{x:,.2f} h".replace(",", "'")


def a(url, text):
    return f'<a href="{esc(url)}">{esc(text)}</a>'


def status(st):
    color, label, _ = STATUS[st]
    return f'<span data-type="status" data-color="{color}">{label}</span>'


def date_tag(d):
    return f'<time datetime="{esc(d)}">{esc(d)}</time>' if d else "—"


# ---------------------------------------------------------------- comments carry-over

class _CommentsParser(HTMLParser):
    """Map project name → inner HTML of the last cell of its row, in the table whose header
    row contains 'Comments'. The project name is the first <strong> text of the first cell."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out = {}
        self.table_depth = 0
        self.in_target = False
        self.header = []
        self.row = None            # list of cells (each: {"html": [...], "strong": str|None})
        self.cell = None
        self.cell_depth = 0
        self.in_strong = False
        self.th_text = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table_depth += 1
            if self.table_depth == 1:
                self.in_target, self.header = False, []
        if self.cell is not None:
            if tag in ("td", "th"):
                self.cell_depth += 1
            self.cell["html"].append(self.get_starttag_text())
            if tag == "strong" and self.cell["strong"] is None:
                self.in_strong, self.cell["strong"] = True, ""
            return
        if self.table_depth != 1:
            return
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell, self.cell_depth = {"html": [], "strong": None, "tag": tag, "text": ""}, 0

    def handle_startendtag(self, tag, attrs):
        if self.cell is not None:
            self.cell["html"].append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if self.cell is not None:
            if tag in ("td", "th") and self.cell_depth == 0:
                self.row.append(self.cell)
                self.cell = None
                return
            if tag in ("td", "th"):
                self.cell_depth -= 1
            if tag == "strong":
                self.in_strong = False
            self.cell["html"].append(f"</{tag}>")
            return
        if tag == "tr" and self.row is not None and self.table_depth == 1:
            if self.row and all(c["tag"] == "th" for c in self.row):
                self.header = [c["text"].strip() for c in self.row]
                self.in_target = any(h.lower().startswith("comment") for h in self.header)
            elif self.in_target and self.row:
                name = (self.row[0]["strong"] or "").strip()
                if name:
                    self.out[name] = "".join(self.row[-1]["html"]).strip()
            self.row = None
        if tag == "table":
            self.table_depth -= 1

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["html"].append(data)
            self.cell["text"] += data
            if self.in_strong:
                self.cell["strong"] += data

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")


def extract_comments(page_html, same_page=False):
    """Comments per project. For a NEW edition (same_page=False) the Confluence local ids and the
    inline-comment anchors of the old page are stripped (they belong to the old page); when the
    same page is updated they are kept, as the format guide requires."""
    p = _CommentsParser()
    p.feed(page_html or "")
    p.close()
    out = {k: v for k, v in p.out.items() if _has_text(v)}
    if not same_page:
        out = {k: _strip_page_ids(v) for k, v in out.items()}
    return out


def _strip_page_ids(fragment):
    fragment = re.sub(r'\s+data-local-id="[^"]*"', "", fragment)
    return re.sub(r'<span class="annotation"[^>]*>(.*?)</span>', r"\1", fragment, flags=re.S)


def _has_text(fragment):
    class T(HTMLParser):
        def __init__(self):
            super().__init__()
            self.t = ""

        def handle_data(self, d):
            self.t += d
    t = T()
    t.feed(fragment)
    return bool(t.t.strip())


# ---------------------------------------------------------------- blocks

# The checklist = the steps of "How to - Invoice your project". Each tick is COMPUTED from Odoo/Jira
# at every run (invoicing.py, progress): (key, label, ✅ when, if ⬜ what to do).
STEPS = [
    ("step1_clean", "1 Data clean",
     "No line for the project in Odoo › Invoicing Dashboards 03 / 04, and no Jira card with time but no Epic. "
     "A project without Jira link (Connector tab empty) is Odoo-only: dashboard 02 does not apply to it.",
     "Fix in Jira / Odoo — see “How to fix” under Details (How-to step 1)."),
    ("step23_hours", "2–3 Hours checked",
     "The month's hours are all on an SO item, on the right kind of item (functional AM/BA/PM vs technical DEV/ARCH), "
     "and Odoo can invoice all the hours that are not yet invoiced.",
     "Project › Timesheet › filter To invoice › group by Sales Order Item › Mass edit (How-to steps 2–3)."),
    ("step45_draft", "4–5 Draft invoice",
     "An invoice (draft or posted) exists on the project's orders, created since the start of the invoicing cycle.",
     "On each SO: create the invoice, period year to date, fields as in “Invoice fields” above (How-to steps 4–5)."),
    ("step6_report", "6 Hours report attached",
     "Every invoice of the cycle has an hours report PDF attached in Odoo.",
     "Print Timesheet Entries - External / Hours Block report (or ask Claude for the hours report) and attach it "
     "to the invoice (How-to step 6)."),
    ("step7_activity", "7 Admin notified",
     "Every draft invoice has an activity “Validate/Send Invoice” assigned to Leila (or the invoice is already posted).",
     "On the invoice: Schedule activity › Validate/Send Invoice › assigned to Leila (How-to step 7)."),
]


def _checklist(pr):
    return "<p>" + "<br>".join(f"{'✅' if pr.get(k) else '⬜'} {esc(t)}" for k, t, _, _ in STEPS) + "</p>"


def _legend():
    head = "".join(f"<th><p><strong>{h}</strong></p></th>" for h in ("Checklist step", "✅ means (checked automatically)",
                                                                    "⬜ → what to do"))
    rows = "".join(f"<tr><td><p><strong>{esc(t)}</strong></p></td><td><p>{esc(ok)}</p></td><td><p>{esc(todo)}</p></td></tr>"
                   for _, t, ok, todo in STEPS)
    status_line = ("<p><strong>Status</strong>: "
                   f"{status('red')} something to correct in Odoo / Jira before invoicing · "
                   f"{status('yellow')} a point to verify, invoicing possible · "
                   f"{status('green')} nothing to fix, amount ready to invoice · "
                   f"{status('idle')} nothing to invoice.</p>")
    note = ("<p style=\"font-size: 14px\">The ticks and statuses are recomputed from Odoo and Jira at every run of "
            "<code>invoicing_day</code>: a tick added by hand is overwritten. Write remarks in the "
            "<strong>Comments</strong> column — it is kept from run to run and month to month.</p>")
    return "\n".join(["<h3>How to read this table</h3>", status_line,
                      f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>", note])


def _to_invoice_cell(r):
    if not r["proposal"]:
        return "<p>—</p>"
    amounts = " · ".join(money(v, c) for c, v in sorted(r["to_invoice"].items())) or "—"
    by_so = {}
    for it in r["proposal"]:
        d = by_so.setdefault(it["so"], {"link": it["link"], "amount": 0.0, "hours": 0.0, "cur": it["currency"], "kinds": set()})
        d["amount"] += it["amount"] or 0.0
        d["hours"] += it["hours"] or 0.0
        if it["kind"] != "tm":
            d["kinds"].add(KIND_LABEL[it["kind"]])
    lines = "".join(
        f'<p style="font-size: 14px">{a(d["link"], so)} {esc(money(d["amount"], d["cur"]))}'
        + (f" · {esc(hrs(d['hours']))}" if d["hours"] else "")
        + (f" · {esc(', '.join(sorted(d['kinds'])))}" if d["kinds"] else "") + "</p>"
        for so, d in sorted(by_so.items()))
    return f"<p><strong>{esc(amounts)}</strong></p>{lines}"


def _unpaid_cell(r):
    if not r["unpaid"]:
        return "<p>—</p>"
    out = []
    for u in sorted(r["unpaid"], key=lambda u: -u["days_late"]):
        late = f" · <strong>{u['days_late']} d late</strong>" if u["days_late"] else ""
        out.append(f'<p style="font-size: 14px">{a(u["link"], u["name"])} {esc(money(u["residual"], u["currency"]))}{late}</p>')
    return "".join(out)


def _row(r, comment):
    _, _, bg = STATUS[r["status"]]
    bga = f' data-background="{bg}"' if bg else ""
    sub = " · ".join(x for x in (r.get("client"), r.get("manager")) if x)
    cells = [
        f'<p><strong>{esc(r["project"])}</strong></p><p style="font-size: 14px">{esc(sub)}</p>',
        f"<p>{status(r['status'])}</p>",
        _to_invoice_cell(r),
        _checklist(r["progress"]),
        _unpaid_cell(r),
        comment or "<p></p>",
    ]
    tds = "".join(f'<td data-colwidth="{w}"{bga if i < 2 else ""}>{c}</td>' for i, (w, c) in enumerate(zip(COLWIDTHS, cells)))
    return f"<tr>{tds}</tr>"


def _table(rows, comments):
    head = "".join(f'<th data-colwidth="{w}"><p><strong>{h}</strong></p></th>'
                   for w, h in zip(COLWIDTHS, ("Project", "Status", "To invoice (excl. VAT)", "Checklist (How-to steps)",
                                               "Unpaid &amp; late", "Comments")))
    body = "\n".join(_row(r, comments.get(r["project"])) for r in rows)
    return (f'<table data-layout="full-width" data-display-mode="fixed"><thead><tr>{head}</tr></thead>'
            f"<tbody>\n{body}\n</tbody></table>")


def _small_table(headers, rows):
    if not rows:
        return ""
    h = "".join(f"<th><p><strong>{esc(x)}</strong></p></th>" for x in headers)
    b = "".join("<tr>" + "".join(f"<td><p>{c}</p></td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>"


EXAMPLES = 5


def _examples(items, fmt):
    shown = "; ".join(fmt(x) for x in items[:EXAMPLES])
    more = f" … (+{len(items) - EXAMPLES})" if len(items) > EXAMPLES else ""
    return shown + more


def _details(r, odoo_url, dashboards):
    c = r["controls"]
    parts = []
    if r["flags"]:
        shown = [f for f in r["flags"] if f["level"] != "info" or f["code"] in ("STALE_TO_INVOICE", "ODOO_ONLY")]
        if shown:
            parts.append("<ul>" + "".join(f"<li>{LEVEL_ICON[f['level']]} {esc(f['msg'])}</li>" for f in shown) + "</ul>")
    noted = [it for it in r["proposal"] if it.get("note") and it["kind"] == "tm"]
    if noted:
        parts.append("<p><strong>Items to check</strong>: " + esc(_examples(
            noted, lambda it: f"{it['so']} {it['line']} {hrs(it['hours'])} ({it['note']})")) + "</p>")

    def dash_link(k):
        d = dashboards.get(k)
        if not d:
            return ""
        return " — " + a(f"{odoo_url}/web#action={d['action_id']}", "open dashboard " + k)
    if c.get("d04_ts_no_task"):
        parts.append(f"<p><strong>04 - TS lines without tasks</strong>: {c['d04_count']} line(s), {esc(hrs(c['d04_hours']))} — "
                     + esc(_examples(c["d04_ts_no_task"], lambda l: f"{l['jira'] or 'no card'} {l['date']} {l['employee']} {hrs(l['hours'])}"))
                     + dash_link("04") + "</p>")
    if c.get("d03_tasks_no_so"):
        parts.append(f"<p><strong>03 - Tasks not linked to a SO line</strong>: {c['d03_count']} — "
                     + esc(_examples(c["d03_tasks_no_so"], lambda t: t["name"])) + dash_link("03") + "</p>")
    if c.get("check_epic"):
        ce = c["check_epic"]
        parts.append(f"<p><strong>Jira cards with time and no Epic</strong>: {len(ce)} — "
                     + ", ".join(a(i["link"], i["key"]) for i in ce[:10]) + (f" … (+{len(ce) - 10})" if len(ce) > 10 else "") + "</p>")
    jv = c.get("jira_vs_odoo")
    if jv and jv.get("diffs"):
        parts.append(f"<p><strong>Jira vs Odoo, month</strong> (Jira {esc(hrs(jv['jira_h']))}, Odoo {esc(hrs(jv['odoo_h']))}): "
                     + ", ".join(f"{a(d['link'], d['key'])} {d['jira_h']}/{d['odoo_h']} h" for d in jv["diffs"][:10])
                     + (f" … (+{len(jv['diffs']) - 10})" if len(jv["diffs"]) > 10 else "") + "</p>")
    if c.get("item_category"):
        parts.append("<p><strong>Functional vs technical items</strong>: "
                     + esc(_examples(c["item_category"], lambda x: f"{x['employee']} ({x['job']}) on {x['item_role']} item "
                                                                 f"“{x['so_line']}” {hrs(x['hours'])}")) + "</p>")
    flagged_blocks = [b for b in c.get("hours_blocks") or [] if b["pct"] is not None and b["pct"] >= 90]
    if flagged_blocks:
        parts.append("<p><strong>Hours blocks</strong>: " + esc(_examples(
            flagged_blocks, lambda b: f"{b['so']} {b['line']} {b['delivered']}/{b['ordered']} {b['uom'] or ''} ({b['pct']} %)")) + "</p>")
    rd = c.get("rounding") or {}
    if rd.get("leak_h"):
        parts.append(f"<p style=\"font-size: 14px\">Month: {esc(hrs(rd['month_hours']))} spent, {esc(hrs(rd['month_rounded']))} "
                     f"rounded (write-off {esc(hrs(rd['leak_h']))}, {rd['leak_pct']} %)</p>")
    inv = r["progress"]["invoices"]
    if inv:
        parts.append("<p><strong>This cycle's invoices</strong>: " + "; ".join(
            f"{a(i['link'], i['name'])} {esc(i['state'])} {esc(money(i['amount_untaxed'], i['currency']))}"
            f" · report {'✅' if i['report_attached'] else '—'} · activity {'✅' if i['admin_activity'] else '—'}" for i in inv) + "</p>")
    body = "\n".join(p for p in parts if p) or "<p>Nothing to report.</p>"
    return f"<details><summary>{esc(r['project'])} — {STATUS[r['status']][1]}</summary>{body}</details>"


def build_body(fig, comments=None):
    comments = comments or {}
    rows = fig["rows"]
    s = fig["summary"]
    table_rows = [r for r in rows if r["status"] != "idle" or r["project"] in comments]
    idle = [r["project"] for r in rows if r not in table_rows]
    out = []
    out.append(f'<div data-type="panel-info"><p>Invoicing of <strong>{esc(fig["month_label"])}</strong> for the Grammont '
               f'department ({s["projects"]} active projects). Figures read from Odoo on {date_tag(fig["today"])} '
               f'({esc(fig["generated_at"][11:16])}) by <code>invoicing_day</code> — read-only, regenerate before '
               f'invoicing. Process: {a(HOWTO, "How to - Invoice your project")}.</p></div>')
    warn = list(fig["meta"].get("skipped") or [])
    if warn:
        out.append('<div data-type="panel-warning"><p><strong>Not checked in this run</strong></p><ul>'
                   + "".join(f"<li>{esc(w)}</li>" for w in warn) + "</ul></div>")
    # summary
    ti = s.get("to_invoice") or {}
    lines = []
    for cur, d in sorted(ti.items()):
        lines.append(f"<p><strong>{esc(money(d.get('total'), cur))}</strong></p>")
        lines.append("<ul>" + "".join(f"<li>{esc(KIND_LABEL[k])}: {esc(money(v, cur))}</li>"
                                      for k, v in sorted(d.items()) if k != "total") + "</ul>")
    col1 = "<h3>To invoice</h3>" + ("".join(lines) or "<p>—</p>")
    col2 = ("<h3>Projects</h3><ul>"
            + "".join(f"<li>{status(k)} {s.get(k, 0)}</li>" for k in ("red", "yellow", "green", "idle")) + "</ul>")
    up = s.get("unpaid") or {}
    team = fig.get("team") or {}
    gc = team.get("garbage_collectors")
    crm = team.get("crm") or {}
    col3 = "<h3>Unpaid &amp; team checks</h3><ul>"
    for cur, d in sorted(up.items()):
        col3 += (f"<li>Unpaid: {esc(money(d['amount'], cur))} ({d['count']}), of which late "
                 f"{esc(money(d['late_amount'], cur))} ({d['late_count']})</li>")
    if not up:
        col3 += "<li>Unpaid: none</li>"
    if gc is not None:
        col3 += f"<li>01 - Garbage Collectors (team): {gc['count']} line(s), {esc(hrs(gc['hours']))}</li>"
    for k, v in sorted(crm.items()):
        col3 += f"<li>{esc(v['name'].split('=>')[0].strip())}: {v['count']}</li>"
    col3 += "</ul>"
    out.append(f'<section data-type="layout-three-equal"><div data-type="column">{col1}</div>'
               f'<div data-type="column">{col2}</div><div data-type="column">{col3}</div></section>')
    d = fig["invoice_defaults"]
    out.append("<h2>Invoice fields (How-to steps 4–7)</h2><ul>"
               f"<li>Period: <strong>{esc(d['period'])}</strong> — always year to date</li>"
               f"<li>Invoice date: {date_tag(d['invoice_date'])} (date of creation) · Date: {date_tag(d['accounting_date'])} "
               "(1st day of the current month)</li>"
               f"<li>Payment reference: {esc(d['payment_reference'])} · Customer reference: <code>{esc(d['customer_reference'])}</code></li>"
               "<li>Attach the hours report (Timesheet Entries - External, Hours Block report, or "
               "<code>python3 -m invoicing_day hours report</code>)</li>"
               "<li>Activity <em>Validate/Send Invoice</em> assigned to Leila: “Hello, The invoice is ready to be sent "
               "with the hour details attached. Thank you!”</li></ul>")
    out.append("<h2>Projects</h2>")
    out.append(_legend())
    out.append(_table(table_rows, comments))
    if idle:
        out.append(f"<p style=\"font-size: 14px\">Nothing to invoice and nothing to fix: {esc(', '.join(idle))}.</p>")
    if gc and gc["lines"]:
        out.append("<p><strong>Team — 01 - Garbage Collectors</strong>: " + esc(_examples(
            gc["lines"], lambda l: f"{l['jira'] or 'no card'} {l['date']} {l['employee']} {hrs(l['hours'])}")) + "</p>")
    out.append("<h2>Details per project</h2>")
    out.append('<div data-type="panel-note"><p><strong>How to fix</strong> (How-to step 1–3)</p><ul>'
               "<li>04 - TS lines without tasks: add the Epic in the Jira card, then select the lines › Action › "
               "<em>Refresh workload from Jira</em>; or Action › <em>Mass edit (Timesheets)</em> › Task + Sales Order Item "
               "(or Maintenance project + Task).</li>"
               "<li>03: link the task to an SO line. (02, project without Jira link: fine for an Odoo-only project.)</li>"
               "<li>Hours without SO item or on the wrong item (functional AM/BA/PM vs technical DEV/ARCH): "
               "project › Timesheet › filter To invoice › group by Sales Order Item › <em>Mass edit</em>.</li>"
               "<li>Rounded hours: round down on the TS (internal); a commercial gesture is a rebate line on the invoice.</li>"
               "</ul><p>Per-item breakdown of each proposal: <code>runs/AAAA-MM/report.md</code> and "
               "<code>figures.json</code> on Didier's machine.</p></div>")
    out += [_details(r, fig['links']['odoo'], fig['meta'].get('dashboards') or {}) for r in table_rows
            if any(f['level'] != 'info' or f['code'] in ('STALE_TO_INVOICE', 'ODOO_ONLY') for f in r['flags'])
            or r['progress']['invoices']]
    return "\n".join(out) + "\n"          # one block per line: readable in chunks, < 2 k chars per line
