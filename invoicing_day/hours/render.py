"""Client-facing hours report — RENDER piece.

Ported from Compass (~/.openclaw/workspace/compass/hours_report.py, commit 506671a). Changes:
imports point to invoicing_day; files go to the run folder given by the caller
(runs/AAAA-MM/hours/<project>/ by default); the summary header names invoicing_day.

facts dict (from invoicing_day/hours/fetch.py) -> self-contained HTML -> PDF via invoicing_day.pdf.

CUSTOMER-FACING rules: quantities only. No money, no employee names, no timesheet
descriptions (the fetcher never reads them), never the slug, never the word "Compass", no
compass icon in the HTML/PDF. `checks` (warnings) are for the PM and never reach the document.
Ranking/fetching live elsewhere; this module only lays out what it is handed.
"""
import base64
import html as _html
import json
import os
import re
import unicodedata
from pathlib import Path

from .. import pdf
from ..constants import FORBIDDEN

PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(PACKAGE_DIR)
ASSETS_DIR = os.path.join(PACKAGE_DIR, "assets")
LONG_REPORT_PAGES = 5

_T = {
    "fr": {
        "title": "Rapport d'heures",
        "invoice": "Facture {name} du {date}", "invoice_draft": "Facture en préparation",
        "period": "Période du {a} au {b}",
        "meta": "Prestations du {a} au {b} · Établi le {issued}", "meta_issued": "Établi le {issued}",
        "h1_orders": "Lignes de commande", "order": "Commande {name}",
        "ref": " — votre référence {ref}",
        "description": "Description", "unit": "Unité", "ordered": "Commandé",
        "delivered": "Livré", "invoiced": "Facturé",
        "this_invoice": "Cette facture", "this_period": "Cette période",
        "orders_note": "Commandé, livré et facturé : cumuls depuis l'ouverture de la commande, "
                       "au {issued}. {this}",
        "orders_note_cut": "Livré : cumul depuis l'ouverture de la commande jusqu'au {cut} ({why}). "
                           "Commandé et facturé : au {issued}. {this}",
        "cut_invoice": "fin du mois facturé", "cut_period": "fin de la période",
        "orders_note_inv": "Livré : cumul jusqu'au {cut} (fin du mois facturé). Facturé : cumul jusqu'à "
                           "la présente facture incluse. Commandé : au {issued}. {this}",
        "this_note_invoice": "Cette facture : quantités de la présente facture.",
        "this_note_period": "Cette période : prestations de la période.",
        "h1_tasks": "Résumé par tâche", "task": "Tâche", "hours": "Heures",
        "no_task": "(sans tâche)", "total": "Total",
        "unit_day": "j", "unit_h": "h", "unit_hours": "h",
    },
    "de": {
        "title": "Stundenrapport",
        "invoice": "Rechnung {name} vom {date}", "invoice_draft": "Rechnung in Vorbereitung",
        "period": "Zeitraum vom {a} bis {b}",
        "meta": "Leistungen vom {a} bis {b} · Erstellt am {issued}", "meta_issued": "Erstellt am {issued}",
        "h1_orders": "Auftragspositionen", "order": "Auftrag {name}",
        "ref": " — Ihre Referenz {ref}",
        "description": "Beschreibung", "unit": "Einheit", "ordered": "Bestellt",
        "delivered": "Geliefert", "invoiced": "Fakturiert",
        "this_invoice": "Diese Rechnung", "this_period": "Dieser Zeitraum",
        "orders_note": "Bestellt, geliefert und fakturiert: Kumulwerte seit Auftragseröffnung, "
                       "per {issued}. {this}",
        "orders_note_cut": "Geliefert: kumuliert seit Auftragseröffnung bis {cut} ({why}). "
                           "Bestellt und fakturiert: per {issued}. {this}",
        "cut_invoice": "Ende des fakturierten Monats", "cut_period": "Ende des Zeitraums",
        "orders_note_inv": "Geliefert: kumuliert bis {cut} (Ende des fakturierten Monats). Fakturiert: "
                           "kumuliert bis und mit dieser Rechnung. Bestellt: per {issued}. {this}",
        "this_note_invoice": "Diese Rechnung: Mengen der vorliegenden Rechnung.",
        "this_note_period": "Dieser Zeitraum: Leistungen des Zeitraums.",
        "h1_tasks": "Zusammenfassung nach Aufgabe", "task": "Aufgabe", "hours": "Stunden",
        "no_task": "(ohne Aufgabe)", "total": "Total",
        "unit_day": "T", "unit_h": "h", "unit_hours": "Std.",
    },
    "en": {
        "title": "Hours report",
        "invoice": "Invoice {name} of {date}", "invoice_draft": "Invoice in preparation",
        "period": "Period from {a} to {b}",
        "meta": "Services from {a} to {b} · Issued on {issued}", "meta_issued": "Issued on {issued}",
        "h1_orders": "Order lines", "order": "Order {name}",
        "ref": " — your reference {ref}",
        "description": "Description", "unit": "Unit", "ordered": "Ordered",
        "delivered": "Delivered", "invoiced": "Invoiced",
        "this_invoice": "This invoice", "this_period": "This period",
        "orders_note": "Ordered, delivered and invoiced: cumulative since the order was opened, "
                       "as of {issued}. {this}",
        "orders_note_cut": "Delivered: cumulative since the order was opened, up to {cut} ({why}). "
                           "Ordered and invoiced: as of {issued}. {this}",
        "cut_invoice": "end of the invoiced month", "cut_period": "end of the period",
        "orders_note_inv": "Delivered: cumulative up to {cut} (end of the invoiced month). Invoiced: "
                           "cumulative up to and including this invoice. Ordered: as of {issued}. {this}",
        "this_note_invoice": "This invoice: quantities of this invoice.",
        "this_note_period": "This period: services of the period.",
        "h1_tasks": "Summary by task", "task": "Task", "hours": "Hours",
        "no_task": "(no task)", "total": "Total",
        "unit_day": "d", "unit_h": "h", "unit_hours": "h",
    },
}
_PREFIX = {"fr": "Rapport-heures", "de": "Stundenrapport", "en": "Hours-report"}

# VISUAL POLICY = c2c's own Odoo documents (Didier 2026-10-12: "only the visual policy" of the
# "Hours Block Report" he supplied — content unchanged): letterhead wordmark + company block in grey
# + offices in orange on page 1, the bare icon on the following pages, orange uppercase section
# titles, white tables with bold centred headers and thin grey rules, hours as HH:MM, dates
# dd/mm/yyyy, a sober black footer. Company-wide, so not translated.
_COMPANY = (("Camptocamp SA", "Route de la Chaux 4A", "1030 Bussigny Switzerland"),
            ("+41 21 619 10 10", "info@camptocamp.com", "www.camptocamp.com"))
_OFFICES = "Lausanne / Olten / Chambéry / Paris / Munich"


def _lang(facts):
    lg = facts.get("language")
    return lg if lg in _T else "en"


def _t(lang, key):
    return _T[lang][key]


# ---------------------------------------------------------------- formatting

def fmt_qty(x, decimals=2):
    if x is None:
        return "—"
    return f"{x:,.{decimals}f}".replace(",", "'")


def fmt_date(d):
    if not d:
        return "—"
    y, m, day = str(d)[:10].split("-")
    return f"{day}/{m}/{y}"


def fmt_hm(h):
    """Hours as HH:MM, as c2c's Odoo reports print them (13.7833 → "13:47", 174.6 → "174:36")."""
    if h is None:
        return "—"
    m = round(abs(h) * 60)
    return f"{'-' if h < 0 and m else ''}{m // 60:02d}:{m % 60:02d}"


def _is_hours(line):
    return bool(line.get("time")) and line.get("hours_per_unit") is not None \
        and abs(line["hours_per_unit"] - 1) < 1e-6


def unit_label(line, lang):
    uom = line.get("uom") or ""
    if not line.get("time"):
        return uom
    hpu = line.get("hours_per_unit")
    if hpu is None:
        return uom
    if abs(hpu - 1) < 1e-6:
        return _t(lang, "unit_h")
    if hpu >= 4:
        return f"{_t(lang, 'unit_day')} ({hpu:g} {_t(lang, 'unit_hours')})"
    return uom


def _css_str(s):
    """Escape a string for a CSS double-quoted `content:`; `<` is hex-escaped so `</style>`
    can never close the block."""
    s = str(s).replace("\\", "\\\\").replace('"', '\\"').replace("<", "\\3C ")
    return re.sub(r"[\r\n]+", " ", s)


def _esc(s):
    return _html.escape(str(s), quote=True)


def _data_uri(path):
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode()


# ---------------------------------------------------------------- html

def _line3(facts, lang):
    if facts.get("mode") == "invoice":
        inv = facts.get("invoice") or {}
        if inv.get("draft") or not inv.get("name"):
            return _t(lang, "invoice_draft")
        return _t(lang, "invoice").format(name=inv["name"], date=fmt_date(inv.get("invoice_date")))
    p = facts.get("period") or {}
    return _t(lang, "period").format(a=fmt_date(p.get("from")), b=fmt_date(p.get("to")))


def build_html(facts, assets_dir=None):
    lang = _lang(facts)
    adir = assets_dir or ASSETS_DIR
    wordmark = _data_uri(os.path.join(adir, "c2c-letterhead.png"))
    icon = _data_uri(os.path.join(adir, "c2c-icon.png"))
    invoice_mode = facts.get("mode") == "invoice"
    client = facts.get("client") or ""
    title2 = _t(lang, "title")
    line3 = _line3(facts, lang)
    p = facts.get("period") or {}
    issued = fmt_date(facts.get("issued_on"))
    # In period mode line 3 already states the dates; the meta line would only repeat them.
    meta = (_t(lang, "meta").format(a=fmt_date(p.get("from")), b=fmt_date(p.get("to")), issued=issued)
            if invoice_mode else _t(lang, "meta_issued").format(issued=issued))
    year = str(facts.get("issued_on") or "")[:4]
    footer = f"© Camptocamp | {year} | {title2} — {client}"
    this_hdr = _t(lang, "this_invoice" if invoice_mode else "this_period")
    this_note = _t(lang, "this_note_invoice" if invoice_mode else "this_note_period")
    # "Livré" may be cut at the end of the invoiced month / of the period (fetcher `delivered_as_of`,
    # Didier 2026-10-08): the header carries the date, and the note says which date each column is at.
    cut = facts.get("delivered_as_of")
    upto = facts.get("invoiced_upto")                  # invoice mode: Facturé up to this invoice
    if cut and upto:
        orders_note = _t(lang, "orders_note_inv").format(cut=fmt_date(cut), issued=issued, this=this_note)
    elif cut:
        why = _t(lang, "cut_invoice" if invoice_mode else "cut_period")
        orders_note = _t(lang, "orders_note_cut").format(cut=fmt_date(cut), why=why, issued=issued,
                                                         this=this_note)
    else:
        orders_note = _t(lang, "orders_note").format(issued=issued, this=this_note)

    compass = [client, title2, line3, meta, footer, this_hdr, orders_note, _OFFICES,
               *[x for block in _COMPANY for x in block],
               _t(lang, "h1_orders"), _t(lang, "h1_tasks"),
               _t(lang, "total"), _t(lang, "no_task")]
    compass += [_t(lang, k) for k in ("description", "unit", "ordered", "delivered", "invoiced",
                                      "task", "hours")]
    odoo = []

    name, *address = _COMPANY[0]
    company = (f'<p class="co"><b>{_esc(name)}</b><br>{"<br>".join(_esc(x) for x in address)}</p>'
               f'<p class="co">{"<br>".join(_esc(x) for x in _COMPANY[1])}</p>')
    body = [f'<div class="lh"><img class="wordmark" src="{wordmark}" alt="Camptocamp">{company}'
            f'<p class="offices">{_esc(_OFFICES)}</p></div>',
            f'<h1 class="doc">{_esc(title2)}</h1><p class="client">{_esc(client)}</p>'
            f'<p class="ref">{_esc(line3)}</p><p class="meta">{_esc(meta)}</p>',
            f'<h1>{_esc(_t(lang, "h1_orders"))}</h1>']
    asof = f'<br><span class="asof">{_esc(fmt_date(cut))}</span>' if cut else ""
    asof_inv = (f'<br><span class="asof">{_esc(fmt_date(upto["date"]))}</span>'
                if upto and upto.get("date") else "")
    head = ("<thead><tr>"
            f'<th>{_esc(_t(lang, "description"))}</th><th>{_esc(_t(lang, "unit"))}</th>'
            f'<th class="num">{_esc(_t(lang, "ordered"))}</th>'
            f'<th class="num">{_esc(_t(lang, "delivered"))}{asof}</th>'
            f'<th class="num">{_esc(_t(lang, "invoiced"))}{asof_inv}</th>'
            f'<th class="num">{_esc(this_hdr)}</th></tr></thead>')
    for o in facts.get("orders") or []:
        h2 = _t(lang, "order").format(name=o.get("name") or "")
        odoo.append(o.get("name") or "")
        if o.get("client_ref"):
            odoo.append(o["client_ref"])
            h2 += _t(lang, "ref").format(ref=o["client_ref"])
        rows = []
        for ln in o.get("lines") or []:
            if ln.get("kind") == "section":
                odoo.append(ln.get("label") or "")
                rows.append(f'<tr class="section"><td colspan="6">{_esc(ln.get("label") or "")}</td></tr>')
                continue
            odoo.append(ln.get("label") or "")
            d = ln.get("decimals", 2)
            odoo.append(ln.get("uom") or "")
            fmt = fmt_hm if _is_hours(ln) else (lambda v: fmt_qty(v, d))
            cells = "".join(f'<td class="num">{fmt(ln.get(k))}</td>'
                            for k in ("ordered", "delivered", "invoiced", "this"))
            rows.append(f'<tr><td>{_esc(ln.get("label") or "")}</td>'
                        f'<td>{_esc(unit_label(ln, lang))}</td>{cells}</tr>')
        body.append(f'<h2>{_esc(h2)}</h2><table class="orders">{head}<tbody>{"".join(rows)}</tbody></table>')
    body.append(f'<p class="note">{_esc(orders_note)}</p>')

    body.append(f'<h1>{_esc(_t(lang, "h1_tasks"))}</h1>')
    trs = []
    for t in facts.get("tasks") or []:
        if t.get("label") is None:
            label = _t(lang, "no_task")
        else:
            label = t["label"]
            odoo.append(label)
        trs.append(f'<tr><td>{_esc(label)}</td><td class="num">{fmt_hm(t.get("hours"))}</td></tr>')
    trs.append(f'<tr class="total"><td>{_esc(_t(lang, "total"))}</td>'
               f'<td class="num">{fmt_hm(facts.get("total_hours"))}</td></tr>')
    body.append(f'<table class="tasks"><thead><tr><th>{_esc(_t(lang, "task"))}</th>'
                f'<th class="num">{_esc(_t(lang, "hours"))}</th></tr></thead>'
                f'<tbody>{"".join(trs)}</tbody></table>')
    # No note under the task table (Didier 2026-10-08): a discount is a dedicated line on the invoice,
    # shown to the client there — the report does not hint at an adjustment it does not show.

    font = '"Messina Sans","Helvetica Neue",Arial,sans-serif'
    css = f"""
@page {{ size: A4; margin: 32mm 10mm 18mm 10mm; font-family: {font};
  @top-left {{ content: ""; width: 8mm; background: url("{icon}") no-repeat left 0 top 8mm / 7mm auto; }}
  @bottom-left {{ content: "{_css_str(footer)}"; color: #1A1A1A; font-size: 7.5pt; }}
  @bottom-right {{ content: counter(page) "/" counter(pages); color: #1A1A1A; font-size: 7.5pt; }}
}}
@page :first {{ margin-top: 10mm; @top-left {{ content: none; background: none; }} }}
body {{ font-family: {font}; font-size: 9pt; color: #1A1A1A; }}
.lh {{ margin-bottom: 14mm; }}
.lh img.wordmark {{ width: 78mm; display: block; margin-bottom: 4mm; }}
.lh p.co {{ color: #6E7376; font-size: 8.5pt; line-height: 1.5; margin: 0 0 2.5mm; }}
.lh p.co b {{ color: #4E5356; font-weight: 700; }}
.lh p.offices {{ color: #FF680A; font-size: 7pt; margin: 0; }}
h1 {{ color: #FF680A; font-weight: 700; font-size: 13pt; text-transform: uppercase;
      margin: 7mm 0 2.5mm; break-after: avoid; }}
h1.doc {{ margin-top: 0; }}
p.client {{ font-weight: 700; font-size: 10.5pt; margin: 0 0 1mm; }}
p.ref, p.meta {{ color: #6E7376; font-size: 8.5pt; margin: 0 0 1mm; }}
h2 {{ font-weight: 700; font-size: 9.5pt; margin: 4mm 0 1.5mm; break-after: avoid; }}
table {{ width: 100%; border-collapse: collapse; font-size: 8.5pt; }}
thead {{ display: table-header-group; }}
th {{ background: #FFFFFF; color: #1A1A1A; font-weight: 700; text-align: center; vertical-align: bottom;
      border: 0.5pt solid #BDBDBD; border-bottom: 1.2pt solid #1A1A1A; padding: 3pt 4pt; }}
td {{ border: 0.5pt solid #BDBDBD; padding: 2.5pt 4pt; vertical-align: top; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
tr {{ break-inside: avoid; }}
tr.section td {{ font-weight: 700; }}
tr.total td {{ font-weight: 700; }}
table.tasks .num {{ width: 22mm; }}
.note {{ font-size: 7.5pt; color: #6E7376; margin: 1.5mm 0; }}
th .asof {{ font-weight: 400; font-size: 7.5pt; }}
"""
    doc = (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
           "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; "
           "img-src data:; style-src 'unsafe-inline'\">"
           f"<title>{_esc(title2 + ' — ' + client)}</title><style>{css}</style></head>"
           f'<body>{"".join(body)}</body></html>')
    return doc, compass, odoo


def check_customer_safe(compass_texts, odoo_texts):
    """Compass-authored text hitting FORBIDDEN blocks; an Odoo label only warns (ERP task names
    like "Calcul de la marge" are legitimate). Never run on raw HTML: CSS `margin` would trip."""
    for t in compass_texts:
        m = FORBIDDEN.search(t or "")
        if m:
            raise RuntimeError(f"refusing to render: customer-facing text contains {m.group(0)!r}")
    out = []
    for t in odoo_texts:
        m = FORBIDDEN.search(t or "")
        if m:
            out.append({"level": "warning", "code": "ODOO_TERM",
                        "msg": f"Odoo label contains {m.group(0)!r}: {t!r} — the client will read it; "
                               "check before forwarding"})
    return out


# ---------------------------------------------------------------- files

def output_stem(facts):
    lang = _lang(facts)
    client = (facts.get("client") or "").split(" — ")[0]
    client = unicodedata.normalize("NFKD", client).encode("ascii", "ignore").decode()
    client = re.sub(r"[^A-Za-z0-9]+", "-", client).strip("-") or "client"
    inv = facts.get("invoice") or {}
    if facts.get("mode") == "invoice" and inv.get("name") and not inv.get("draft"):
        ref = re.sub(r"[^A-Za-z0-9-]", "-", inv["name"])
    else:
        p = facts.get("period") or {}
        ref = f"{p.get('from')}_{p.get('to')}"
    return f"{_PREFIX[lang]}_{client}_{ref}"


def rel(path):
    root = os.path.abspath(REPO_ROOT)
    ap = os.path.abspath(path)
    if ap == root or ap.startswith(root + os.sep):
        return os.path.relpath(ap, root)
    return ap


def _write_json(facts, path):
    Path(path).write_text(json.dumps(facts, indent=2, ensure_ascii=False), encoding="utf-8")


def default_out_dir(facts):
    """runs/AAAA-MM/hours/<project>/ — AAAA-MM = the month of the last day reported."""
    p = facts.get("period") or {}
    month = str(p.get("to") or facts.get("issued_on") or "")[:7] or "undated"
    return os.path.join(REPO_ROOT, "runs", month, "hours", facts["project"])


def render(facts, html_only=False, out_dir=None):
    out_dir = out_dir or default_out_dir(facts)
    os.makedirs(out_dir, exist_ok=True)
    checks = facts.setdefault("checks", [])
    doc, compass_texts, odoo_texts = build_html(facts)
    checks.extend(check_customer_safe(compass_texts, odoo_texts))
    if pdf.brand_font_ok() is False:
        checks.append({"level": "warning", "code": "FONT_FALLBACK",
                       "msg": "Messina Sans not installed here — the PDF uses the fallback font, "
                              "not the charter"})
    stem = output_stem(facts)
    html_path = os.path.join(out_dir, stem + ".html")
    json_path = os.path.join(out_dir, stem + ".json")
    pdf_path = os.path.join(out_dir, stem + ".pdf")
    Path(html_path).write_text(doc, encoding="utf-8")
    _write_json(facts, json_path)
    result = {"html": html_path, "json": json_path, "pdf": None, "pages": None, "bytes": None}
    if not html_only:
        r = pdf.html_to_pdf(html_path, pdf_path)        # PdfError propagates; html+json on disk
        result.update(pdf=pdf_path, pages=r["pages"], bytes=r["bytes"])
        if r["pages"] and r["pages"] > LONG_REPORT_PAGES:
            checks.append({"level": "warning", "code": "LONG_REPORT",
                           "msg": f"{r['pages']} pages — check the report before forwarding"})
    _write_json(facts, json_path)
    return result


def render_summary(facts, result):
    inv = facts.get("invoice") or {}
    if facts.get("mode") == "invoice":
        if inv.get("draft") or not inv.get("name"):
            what = f"invoice draft #{inv.get('id')}"
        else:
            what = f"invoice {inv['name']} ({inv.get('state')}, {fmt_date(inv.get('invoice_date'))})"
    else:
        p = facts.get("period") or {}
        what = f"period {fmt_date(p.get('from'))} → {fmt_date(p.get('to'))}"
    checks = facts.get("checks") or []
    warns = [c for c in checks if c.get("level") == "warning"]
    infos = [c for c in checks if c.get("level") != "warning"]
    nt, no = len(facts.get("tasks") or []), len(facts.get("orders") or [])
    stats = [f"{fmt_qty(facts.get('total_hours'), 2)} h", f"{nt} task{'s' * (nt != 1)}",
             f"{no} order{'s' * (no != 1)}"]
    if result.get("pages"):
        stats.append(f"{result['pages']} page{'s' * (result['pages'] != 1)}")
    stats.append(_lang(facts))
    verdict = ("READY" if not warns else
               f"READY — {len(warns)} WARNING(S) TO READ BEFORE FORWARDING")
    if not warns:
        verdict += " FOR OPERATOR REVIEW"
    p = facts.get("period") or {}
    lines = [f"invoicing_day — hours report — {facts.get('project')} — {what}",
             f"→ {verdict}: " + " · ".join(stats),
             f"services: {fmt_date(p.get('from'))} → {fmt_date(p.get('to'))} ({p.get('basis')})"]
    if result.get("pdf"):
        lines.append(f"pdf : {rel(result['pdf'])}")
    else:
        lines.append(f"html: {rel(result['html'])} (--html-only, no PDF)")
    lines += [f"⚠ {c['code']}: {c['msg']}" for c in warns]
    lines += [f"ℹ {c['code']}: {c['msg']}" for c in infos]
    return "\n".join(lines)
