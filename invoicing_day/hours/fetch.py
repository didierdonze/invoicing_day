"""Client hours report — FETCHER piece. READ-ONLY.

Ported from Compass (~/.openclaw/workspace/compass/fetchers/hours.py, commit 506671a). Changes:
- the scope comes from the PROJECT (invoicing_day/hours/scope.py builds `entry`), not from
  Compass's registry/projects.yaml — Didier's rule "always work from the project, not the SO";
- the client is invoicing_day.odoo.Odoo (same search_read / read_group / fields_get interface);
- messages name the invoicing_day commands.

Reads, for ONE project: its confirmed sale orders + lines (ordered / delivered / invoiced), the
uoms they use, and the billable timesheets of an invoice or of a period, grouped by task.
Returns the facts dict that `invoicing_day/hours/render.py` renders. No ranking, no layout.

Field allow-list (the constants below; asserted by tests/test_hours.py): QUANTITIES ONLY.
Never `price_*`, `amount*`, `employee_id`, `user_id` nor the analytic line `name`: this
document goes to a client, so money, people and timesheet descriptions are never even read.

Probe facts behind the choices (design §2, live 2026-10-08):
- `unit_amount_rounded` carries the project's MANUAL write-offs (932.98 h raw vs 913.97 h
  rounded) — it IS the invoiced basis. This module never falls back to `unit_amount`.
- Timesheets use uom 27 "Hour", which is ARCHIVED (absent from the active listing): uom reads
  pass `active_test=False`. Conversions follow Odoo's own ratio, q * factor_inv(from) /
  factor_inv(to); units of different categories are not convertible.
- Task display names carry a "[KEY] " prefix: names come from `project.task.name`.

This fetcher does NOT degrade. A client document built from a partial read is worse than none:
any read failure raises; the expected, explainable ones raise `HoursRefusal`.
"""
import calendar
import math
import re
from datetime import date, datetime, timezone

from ..constants import CONFIRMED_STATES, TIME_UOM_NAMES, _u  # noqa: F401  (TIME_UOM_NAMES: see HOUR_NAMES)

CMD = "python3 -m invoicing_day hours"

SO_FIELDS = ["id", "name", "state", "date_order", "client_order_ref"]
LINE_FIELDS = ["id", "order_id", "sequence", "name", "display_type", "is_downpayment",
               "product_uom_qty", "qty_delivered", "qty_invoiced", "qty_delivered_method",
               "product_uom"]
MOVE_FIELDS = ["id", "name", "move_type", "state", "payment_state", "invoice_date", "reversed_entry_id"]
MOVE_LINE_FIELDS = ["id", "sale_line_ids", "quantity", "product_uom_id"]
UOM_FIELDS = ["id", "name", "factor_inv", "rounding", "category_id"]
HOUR_NAMES = {"h", "hour", "hours", "heure", "heures", "hrs", "stunde", "stunden"}   # subset of TIME_UOM_NAMES

TS = "account.analytic.line"
RES = "unit_amount_rounded"
EPS = 1e-9


class HoursRefusal(RuntimeError):
    """Expected, explainable refusal: the message is what to tell the PM and what to do instead."""


# ---------------------------------------------------------------- small helpers

def _id(v):
    """many2one value ([id, name] / id / False) -> id or None."""
    if isinstance(v, (list, tuple)):
        return v[0] if v else None
    return v or None


def _r(x):
    return None if x is None else round(float(x), 6)


def _natural_key(label):
    return [int(p) if i % 2 else p.casefold() for i, p in enumerate(re.split(r"(\d+)", label or ""))]


def _chk(level, code, msg):
    return {"level": level, "code": code, "msg": msg}


def _is_draft_name(n):
    return n in ("/", False, None, "")


def _names(seq):
    return ", ".join(seq)


def _group_hours(groups):
    return sum(g.get(RES) or 0.0 for g in groups)


# ---------------------------------------------------------------- common steps

def _scope_orders(client, entry):
    """Step 1 — confirmed sale orders of the project (refuses on every ambiguity).

    `entry` comes from invoicing_day.hours.scope.project_entry(): the orders are those the
    project's tasks and timesheet lines point to (optionally narrowed with --so)."""
    if not entry.get("client"):
        raise HoursRefusal("the project has no customer — the customer-facing name is missing. "
                           "Set the customer on the project in Odoo (the project code never goes on a client document).")
    names = []
    for sc in entry.get("scopes") or []:
        for n in sc.get("sale_orders") or []:
            if n not in names:
                names.append(n)
    if not names:
        raise HoursRefusal("no sale order is linked to this project (neither through its tasks nor its "
                           "timesheet lines) — nothing to report on.")
    rows = client.search_read("sale.order", [("name", "in", names)], SO_FIELDS, order="date_order asc, id asc")
    found = {r["name"]: r for r in rows}
    missing = [n for n in names if n not in found]
    if missing:
        raise HoursRefusal(f"sale order(s) not found in Odoo: {_names(missing)}.")
    kept, infos = [], []
    for n in names:
        r = found[n]
        if r["state"] in CONFIRMED_STATES:
            kept.append(r)
        else:
            infos.append(_chk("info", "QUOTATION_EXCLUDED", f"{n} is in state '{r['state']}' — not a confirmed order, left out"))
    if not kept:
        raise HoursRefusal("none of the project's sale orders is confirmed (" +
                           _names(f"{r['name']}={r['state']}" for r in found.values()) + ").")
    kept.sort(key=lambda r: (r.get("date_order") or "", r["id"]))
    return kept, infos


def _require_fields(client, invoice_mode):
    fg = client.fields_get(TS)
    need = [RES] + (["timesheet_invoice_id"] if invoice_mode else [])
    miss = [f for f in need if f not in fg]
    if miss:
        raise HoursRefusal(f"this Odoo has no sale_timesheet_rounded ({_names(miss)} missing on "
                           f"{TS}) — the hours report cannot be built here.")


def _fmt_h(x):
    return f"{x:.2f}"


# ---------------------------------------------------------------- invoices listing

def list_invoices(client, entry, limit=20):
    orders, _ = _scope_orders(client, entry)
    _require_fields(client, True)
    so_ids = [o["id"] for o in orders]
    moves = client.search_read(
        "account.move",
        [("line_ids.sale_line_ids.order_id", "in", so_ids), ("move_type", "in", ["out_invoice", "out_refund"])],
        MOVE_FIELDS, order="invoice_date desc, id desc", limit=limit)
    hours = {}
    if moves:
        gs = client.read_group(TS, [("timesheet_invoice_id", "in", [m["id"] for m in moves]),
                                    ("project_id", "!=", False)], [RES], ["timesheet_invoice_id"])
        for g in gs:
            k = _id(g.get("timesheet_invoice_id"))
            hours[k] = hours.get(k, 0.0) + (g.get(RES) or 0.0)
    return [{"id": m["id"], "name": None if _is_draft_name(m.get("name")) else m["name"],
             "kind": "credit_note" if m.get("move_type") == "out_refund" else "invoice",
             "state": m.get("state"), "payment_state": m.get("payment_state"),
             "invoice_date": m.get("invoice_date") or None,
             "linked_hours": _r(hours.get(m["id"], 0.0))} for m in moves]


# ---------------------------------------------------------------- the report

def fetch_hours(client, entry, invoice=None, date_from=None, date_to=None, today=None, slug=None):
    invoice_mode = invoice is not None
    if invoice_mode == (date_from is not None or date_to is not None):
        raise HoursRefusal("give exactly one of: an invoice, or a period (--from and --to).")
    if not invoice_mode:
        if date_from is None or date_to is None:
            raise HoursRefusal("a period needs both its first and its last day.")
        if date_from > date_to:
            raise HoursRefusal(f"the period is inverted ({date_from} is after {date_to}).")
    today = today or date.today()
    checks = []

    # 1-3. orders, fields, lines
    orders, infos = _scope_orders(client, entry)
    checks += infos
    so_ids = [o["id"] for o in orders]
    so_names = _names(o["name"] for o in orders)
    _require_fields(client, invoice_mode)
    lines = client.search_read("sale.order.line", [("order_id", "in", so_ids)], LINE_FIELDS,
                               order="order_id, sequence, id")
    scope = {l["id"]: l for l in lines if not l.get("display_type") and not l.get("is_downpayment")}
    all_line_ids = {l["id"] for l in lines}
    scope_ids = list(scope)
    if not scope_ids:
        raise HoursRefusal(f"the orders {so_names} have no product line.")

    inv_info = None
    inv_lines = []                    # (line_id, qty, uom_id) attributed to a scope line
    other_so_hours = 0.0
    unlinked_hours = 0.0
    other_lines = []
    unlinked_inv = []                 # (qty, uom_id)
    hist, hist_moves = [], {}         # every invoice / credit-note line on the scope's lines (invoice mode)
    draft = False

    # ---- mode specific reads
    if invoice_mode:
        s = str(invoice).strip()
        if s in ("", "/"):
            raise HoursRefusal("draft invoices have no number (Odoo names them '/') — pass the invoice id "
                               f"(see `{CMD} invoices <project>`).")
        dom = [("id", "=", int(s))] if s.isdigit() else [("name", "=", s)]
        moves = client.search_read("account.move", dom, MOVE_FIELDS)
        if not moves:
            raise HoursRefusal(f"invoice {s!r} not found (run `{CMD} invoices <project>` to list them).")
        if len(moves) > 1:
            raise HoursRefusal(f"invoice {s!r} is ambiguous (ids {', '.join(str(m['id']) for m in moves)}) — pass the id.")
        mv = moves[0]
        label = mv["name"] if not _is_draft_name(mv.get("name")) else f"draft #{mv['id']}"
        if mv.get("move_type") != "out_invoice":
            raise HoursRefusal(f"{label} is a {mv.get('move_type')}: a credit note is not an hours report — "
                               "pick the invoice it reverses.")
        if mv.get("state") == "cancel":
            raise HoursRefusal(f"{label} is cancelled — pick another invoice, or use --from/--to.")
        if mv.get("payment_state") == "reversed":
            raise HoursRefusal(f"{label} is reversed by a credit note: Odoo unlinked its timesheets — use --from/--to.")
        draft = mv.get("state") == "draft" or _is_draft_name(mv.get("name"))
        if draft:
            checks.append(_chk("warning", "DRAFT_INVOICE", f"{label} has no number until posted — "
                                                          "regenerate after posting if the client needs it."))
        inv_info = {"id": mv["id"], "name": None if draft and _is_draft_name(mv.get("name")) else mv["name"],
                    "state": mv.get("state"), "invoice_date": mv.get("invoice_date") or None, "draft": draft}
        if _is_draft_name(mv.get("name")):
            inv_info["name"] = None
        mls = client.search_read("account.move.line", [("move_id", "=", mv["id"]), ("display_type", "=", "product")],
                                 MOVE_LINE_FIELDS)
        others = []
        for ml in mls:
            sl = ml.get("sale_line_ids") or []
            uom = _id(ml.get("product_uom_id"))
            if not sl:
                unlinked_inv.append((ml.get("quantity") or 0.0, uom))
            elif len(sl) > 1:
                checks.append(_chk("warning", "INVOICE_MULTI_LINK",
                                   f"invoice line #{ml['id']} is linked to {len(sl)} sale lines — not attributed in the 4th column"))
            elif sl[0] in scope:
                inv_lines.append((sl[0], ml.get("quantity") or 0.0, uom))
            elif sl[0] not in all_line_ids:        # down-payment lines of the scope orders are in all_line_ids
                others.append(sl[0])
        if others:
            ors = client.search_read("sale.order.line", [("id", "in", others)], ["id", "order_id"])
            other_lines = sorted({(_id(r["order_id"]), r["order_id"][1] if isinstance(r["order_id"], (list, tuple)) else str(r["order_id"])) for r in ors})
            checks.append(_chk("warning", "INVOICE_OTHER_SOS",
                               f"invoice {label} also bills lines of other order(s): {_names(n for _, n in other_lines)} — not in the report"))
        # "Facturé" is rebuilt up to and including THIS invoice (Didier 2026-10-08) from every invoice
        # and credit-note line on the scope's sale lines — quantities and units only, no amount.
        hist = client.search_read("account.move.line", [("sale_line_ids", "in", scope_ids),
                                                        ("display_type", "=", "product")],
                                  MOVE_LINE_FIELDS + ["move_id"])
        if hist:
            hist_moves = {m["id"]: m for m in client.search_read(
                "account.move", [("id", "in", sorted({_id(h.get("move_id")) for h in hist}))], MOVE_FIELDS)}
        groups = client.read_group(TS, [("timesheet_invoice_id", "=", mv["id"]), ("project_id", "!=", False)],
                                   [RES], ["task_id", "so_line", "product_uom_id"])
        bill = [g for g in groups if _id(g.get("so_line")) in scope]
        other = [g for g in groups if _id(g.get("so_line")) not in scope]
        other_so_hours = _group_hours(other)
        if abs(other_so_hours) > EPS:
            checks.append(_chk("warning", "OTHER_SO_HOURS",
                               f"{_fmt_h(other_so_hours)} h linked to {label} sit on no line of {so_names} — not in the report"))
        if abs(_group_hours(bill)) < EPS:
            if not inv_lines:
                raise HoursRefusal(f"invoice {label} bills none of {so_names}.")
            raise HoursRefusal(f"no timesheet linked to invoice {label} on these orders (fixed-price lines, or "
                               "invoiced outside timesheets) — use --from/--to.")
    else:
        a, b = date_from.isoformat(), date_to.isoformat()
        pid = entry.get("odoo_project_id")
        groups = client.read_group(
            TS, [("project_id", "!=", False), ("date", ">=", a), ("date", "<=", b),
                 "|", ("so_line", "in", scope_ids), ("project_id", "=", pid)],
            [RES], ["task_id", "so_line", "product_uom_id"])
        bill = [g for g in groups if _id(g.get("so_line")) in scope]
        unl = [g for g in groups if _id(g.get("so_line")) not in scope]
        unlinked_hours = _group_hours(unl)
        if abs(unlinked_hours) > EPS:
            checks.append(_chk("warning", "UNLINKED_HOURS",
                               f"{_fmt_h(unlinked_hours)} h booked on the project between {a} and {b} are on no line of "
                               "these orders (internal, non-billable or another order) — not in the report"))
        if abs(_group_hours(bill)) < EPS:
            extra = f" ({_fmt_h(unlinked_hours)} h are booked on the project but on no line of these orders)" \
                if abs(unlinked_hours) > EPS else ""
            raise HoursRefusal(f"no billable hours between {a} and {b} on {so_names}{extra}.")
        if date_to >= today:
            checks.append(_chk("warning", "PERIOD_OPEN", f"the period ends on {b}, today or later — hours may still be booked"))

    # ---- services period, and the date "Livré" is cut at
    if invoice_mode:
        q = [("timesheet_invoice_id", "=", inv_info["id"]), ("project_id", "!=", False), ("so_line", "in", scope_ids)]
        first = client.search_read(TS, q, ["date"], order="date asc", limit=1)
        last = client.search_read(TS, q, ["date"], order="date desc", limit=1)
        period = {"from": first[0]["date"] if first else None, "to": last[0]["date"] if last else None,
                  "basis": "linked_timesheets"}
        # Didier 2026-10-08: "Livré" stops at the END OF THE INVOICED MONTH — the month of the last
        # service the invoice bills (CI-CH26-1301: services to 22.07 → 31.07), not the invoice date.
        cutoff = _month_end(period["to"])
    else:
        period = {"from": date_from.isoformat(), "to": date_to.isoformat(), "basis": "requested"}
        cutoff = date_to                           # same rule for a period: its last day

    # ---- delivered tripwire read (all time, scope lines) + the same sum up to the cut-off
    deliv = client.read_group(TS, [("so_line", "in", scope_ids), ("project_id", "!=", False)],
                              [RES], ["so_line", "product_uom_id"])
    deliv_cut = client.read_group(TS, [("so_line", "in", scope_ids), ("project_id", "!=", False),
                                       ("date", "<=", cutoff.isoformat())],
                                  [RES], ["so_line", "product_uom_id"])

    # 4. units
    # Unit strictness applies to the BILLABLE hours only: hours left out of the report (other order,
    # internal) must not block it. Their warning sums them as booked — the project's timesheets share
    # one encoding unit in practice (dransenergie: 828/828 in "Hour").
    ts_uoms = {_id(g.get("product_uom_id")) for g in bill}
    if None in ts_uoms:
        raise HoursRefusal("a billable timesheet has no unit — cannot build the report.")
    need = set(ts_uoms) | {_id(l.get("product_uom")) for l in scope.values()}
    need |= {_id(g.get("product_uom_id")) for g in deliv + deliv_cut} | {u for _, _, u in inv_lines} | {u for _, u in unlinked_inv}
    need |= {_id(h.get("product_uom_id")) for h in hist}
    need.discard(None)
    uoms = {u["id"]: u for u in client.search_read("uom.uom", [("id", "in", sorted(need))], UOM_FIELDS,
                                                   context={"active_test": False})}
    for i in sorted(need):
        if i not in uoms:
            raise HoursRefusal(f"cannot convert unit #{i}: not readable in uom.uom.")

    def cat(i):
        return _id(uoms[i].get("category_id"))

    def conv(q, f, t):
        if cat(f) != cat(t):
            return None
        return q * uoms[f]["factor_inv"] / uoms[t]["factor_inv"]

    main_uoms = {_id(g.get("product_uom_id")) for g in bill}
    if len(main_uoms) != 1:
        raise HoursRefusal("the timesheets are booked in several units (" +
                           _names(sorted(uoms[i]["name"] for i in main_uoms)) + ") — cannot build one hours report.")
    H = main_uoms.pop()
    if (uoms[H]["name"] or "").strip().lower() not in HOUR_NAMES:
        raise HoursRefusal(f"the timesheets are in '{uoms[H]['name']}', not in hours — cannot build an hours report.")

    meta = {}
    for lid, l in scope.items():
        lu = _id(l.get("product_uom"))
        time = lu is not None and cat(lu) == cat(H)
        rounding = uoms[lu].get("rounding") if lu else None
        dec = 2
        if rounding and rounding > 0:
            dec = max(2, -math.floor(math.log10(rounding) + 1e-9))
        meta[lid] = {"uom_id": lu, "time": time, "rounding": rounding or 0.0, "decimals": dec,
                     "uom": _u(uoms[lu]["name"]) if lu else "",
                     "hpu": (uoms[lu]["factor_inv"] / uoms[H]["factor_inv"]) if time else None}

    bill_by_line, bill_by_task = {}, {}
    for g in bill:
        h = g.get(RES) or 0.0
        sl, tk = _id(g.get("so_line")), _id(g.get("task_id"))
        bill_by_line[sl] = bill_by_line.get(sl, 0.0) + h
        bill_by_task[tk] = bill_by_task.get(tk, 0.0) + h
    total_hours = sum(bill_by_task.values())

    # 4th column
    this = {lid: (0.0 if meta[lid]["time"] else None) for lid in scope}
    if invoice_mode:
        for lid, q, u in inv_lines:
            v = conv(q, u or meta[lid]["uom_id"], meta[lid]["uom_id"]) if meta[lid]["uom_id"] else None
            if v is None:
                raise HoursRefusal(f"cannot convert the unit of an invoice line into the order line's unit "
                                   f"({uoms[u]['name'] if u else '?'} → {meta[lid]['uom']}).")
            this[lid] = (this[lid] or 0.0) + v
        for q, u in unlinked_inv:
            checks.append(_chk("warning", "INVOICE_UNLINKED_LINE",
                               f"an invoice line without a sale line ({q:g} {_u(uoms[u]['name']) if u else '?'}) "
                               "is not in the report"))
    else:
        for lid, h in bill_by_line.items():
            if meta[lid]["time"]:
                this[lid] = conv(h, H, meta[lid]["uom_id"])
    nth = [lid for lid in scope if not meta[lid]["time"] and abs(bill_by_line.get(lid, 0.0)) > EPS]
    if nth:
        checks.append(_chk("warning", "NON_TIME_HOURS",
                           "hours booked on line(s) not priced in time units — task summary only: " +
                           "; ".join(f"{_label(scope[l])} ({_fmt_h(bill_by_line[l])} h)" for l in nth)))

    # "Livré" at the cut-off. Odoo stores only TODAY's qty_delivered; on a timesheet-delivered line it
    # is Σ rounded timesheets (probe P4 — and DELIVERED_MISMATCH below keeps checking it on every
    # run), so the same sum up to the cut-off IS the delivered figure at that date. Rounded to the
    # line's unit precision, as Odoo rounds qty_delivered. Any other delivery method has no history
    # here: it keeps today's figure and the PM is warned (DELIVERED_UNDATED).
    delivered_at = {}
    for g in deliv_cut:
        sl, u = _id(g.get("so_line")), _id(g.get("product_uom_id"))
        if sl in scope and u and meta[sl]["uom_id"]:
            v = conv(g.get(RES) or 0.0, u, meta[sl]["uom_id"])
            if v is not None:
                delivered_at[sl] = delivered_at.get(sl, 0.0) + v
    for lid, l in scope.items():
        if l.get("qty_delivered_method") == "timesheet":
            delivered_at[lid] = round(delivered_at.get(lid, 0.0), meta[lid]["decimals"])
        else:
            delivered_at.pop(lid, None)
    undated = []

    # "Facturé" up to and including THIS invoice (invoice mode). Odoo's qty_invoiced is the signed sum
    # of the sale line's non-cancelled invoice lines (+) and credit-note lines (−), drafts included
    # (sale.order.line._compute_qty_invoiced). Dated, counting what the order line counts (Didier
    # 2026-10-12: drafts included, as on the SO line): this invoice itself plus every non-cancelled
    # move before it — invoices by (date, id), credit notes by date; an undated draft sorts last. The
    # undated sum is re-checked against Odoo's own qty_invoiced on every run (INVOICED_MISMATCH), as
    # DELIVERED_MISMATCH does.
    invoiced_at = {}
    drafts_counted = set()
    if invoice_mode:
        upto = (inv_info["invoice_date"] or "9999-12-31", inv_info["id"])

        def counts(m):
            if m["id"] == inv_info["id"]:
                return True
            d = m.get("invoice_date") or "9999-12-31"
            return d <= upto[0] if m.get("move_type") == "out_refund" else (d, m["id"]) <= upto

        invoiced_all = {}
        for h in hist:
            m = hist_moves.get(_id(h.get("move_id")))
            if not m or m.get("state") == "cancel" or m.get("move_type") not in ("out_invoice", "out_refund"):
                continue
            sign = -1.0 if m["move_type"] == "out_refund" else 1.0
            for sl in h.get("sale_line_ids") or []:
                lu = meta[sl]["uom_id"] if sl in scope else None
                v = conv(h.get("quantity") or 0.0, _id(h.get("product_uom_id")) or lu, lu) if lu else None
                if v is None:
                    continue
                invoiced_all[sl] = invoiced_all.get(sl, 0.0) + sign * v
                if counts(m):
                    invoiced_at[sl] = invoiced_at.get(sl, 0.0) + sign * v
                    if m.get("state") == "draft" and m["id"] != inv_info["id"]:
                        drafts_counted.add(m["id"])
        for lid in scope:
            invoiced_at[lid] = round(invoiced_at.get(lid, 0.0), meta[lid]["decimals"])
        bad_inv = [f"{_label(l)}: invoiced {l.get('qty_invoiced') or 0.0:g} vs {invoiced_all.get(lid, 0.0):.2f} "
                   "from the invoice lines" for lid, l in scope.items()
                   if abs(invoiced_all.get(lid, 0.0) - (l.get("qty_invoiced") or 0.0)) > meta[lid]["rounding"] + EPS]
        if bad_inv:
            checks.append(_chk("warning", "INVOICED_MISMATCH",
                               f"Invoiced cannot be rebuilt from the invoice lines on {len(bad_inv)} line(s) — the "
                               "dated figure may be wrong there: " + "; ".join(bad_inv[:5])
                               + (" …" if len(bad_inv) > 5 else "")))

    # rows
    def nonzero(v):
        return v is not None and abs(v) > EPS

    by_order = {}
    for l in lines:
        by_order.setdefault(_id(l["order_id"]), []).append(l)
    out_orders, omitted, dp_skipped = [], [], []
    for o in orders:
        ols = by_order.get(o["id"], [])
        if not any(nonzero(this.get(l["id"])) for l in ols if l["id"] in scope):
            omitted.append(o["name"])
            continue
        rows, pending = [], None
        for l in sorted(ols, key=lambda x: (x.get("sequence") or 0, x["id"])):
            dt = l.get("display_type")
            if dt == "line_section":
                pending = {"kind": "section", "label": _label(l)}
                continue
            if dt == "line_note":
                continue
            if l.get("is_downpayment"):
                dp_skipped.append(f"{o['name']}: {_label(l)}")
                continue
            if l["id"] not in scope:
                continue
            m = meta[l["id"]]
            dlv = delivered_at.get(l["id"], l.get("qty_delivered") or 0.0)
            inv = invoiced_at.get(l["id"], l.get("qty_invoiced") or 0.0)
            vals = [l.get("product_uom_qty"), dlv, inv, this[l["id"]]]
            if not any(nonzero(v) for v in vals):
                continue
            if l["id"] not in delivered_at:
                undated.append(_label(l))
            if pending:
                rows.append(pending)
                pending = None
            rows.append({"kind": "line", "id": l["id"], "label": _label(l), "uom": m["uom"], "time": m["time"],
                         "hours_per_unit": _r(m["hpu"]), "decimals": m["decimals"],
                         "ordered": _r(l.get("product_uom_qty") or 0.0), "delivered": _r(dlv),
                         "delivered_now": _r(l.get("qty_delivered") or 0.0),
                         "invoiced": _r(inv), "invoiced_now": _r(l.get("qty_invoiced") or 0.0),
                         "this": _r(this[l["id"]])})
        out_orders.append({"id": o["id"], "name": o["name"],
                           "client_ref": _u(o.get("client_order_ref")) or None, "lines": rows})
    if undated:
        checks.append(_chk("warning", "DELIVERED_UNDATED",
                           f"Delivered is not timesheet-based on {_names(undated)} — shown as of today, "
                           f"not as of {cutoff.isoformat()} like the other lines"))
    if omitted:
        checks.append(_chk("info", "ORDERS_OMITTED", f"no activity in this report on: {_names(omitted)} — left out"))
    if dp_skipped:
        checks.append(_chk("info", "DOWNPAYMENT_SKIPPED", "down-payment line(s) not shown: " + "; ".join(dp_skipped)))

    # tasks
    ids = [t for t in bill_by_task if t is not None]
    tnames = {}
    if ids:
        tnames = {t["id"]: _u(t["name"]) for t in client.search_read(
            "project.task", [("id", "in", ids)], ["id", "name"], context={"active_test": False})}
    tasks = [{"task_id": t, "label": tnames.get(t, f"(task #{t})"), "hours": _r(h)}
             for t, h in bill_by_task.items() if t is not None]
    tasks.sort(key=lambda t: _natural_key(t["label"]))
    if None in bill_by_task:
        tasks.append({"task_id": None, "label": None, "hours": _r(bill_by_task[None])})

    # checks: consistency
    tl = [lid for lid in scope if meta[lid]["time"]]
    s_this = sum((this[l] or 0.0) * meta[l]["hpu"] for l in tl)
    tol = max(0.01, sum(meta[l]["rounding"] * meta[l]["hpu"] for l in tl if nonzero(this[l])))
    if abs(s_this - total_hours) > tol + EPS:
        gaps = []
        for l in tl:
            a_ = (this[l] or 0.0) * meta[l]["hpu"]
            b_ = bill_by_line.get(l, 0.0)
            if abs(a_ - b_) > meta[l]["rounding"] * meta[l]["hpu"] + EPS:
                gaps.append(f"{_label(scope[l])}: {_fmt_h(a_)} h vs {_fmt_h(b_)} h")
        checks.append(_chk("warning", "CONSISTENCY",
                           f"the 4th column ({_fmt_h(s_this)} h) differs from the task total ({_fmt_h(total_hours)} h)"
                           + (" — " + "; ".join(gaps) if gaps else "")))

    # checks: delivered
    all_time = {}
    for g in deliv:
        sl, u = _id(g.get("so_line")), _id(g.get("product_uom_id"))
        if sl in scope and u and meta[sl]["uom_id"]:
            v = conv(g.get(RES) or 0.0, u, meta[sl]["uom_id"])
            if v is not None:
                all_time[sl] = all_time.get(sl, 0.0) + v
    bad = []
    for lid, l in scope.items():
        if l.get("qty_delivered_method") != "timesheet":
            continue
        got = all_time.get(lid, 0.0)
        if abs(got - (l.get("qty_delivered") or 0.0)) > meta[lid]["rounding"] + EPS:
            bad.append(f"{_label(l)}: delivered {l.get('qty_delivered') or 0.0:g} vs {got:.2f} timesheet")
    if bad:
        checks.append(_chk("warning", "DELIVERED_MISMATCH",
                           f"Delivered differs from the rounded timesheets on {len(bad)} line(s): " + "; ".join(bad[:5])
                           + (" …" if len(bad) > 5 else "")))

    # checks: drafts counted in Invoiced — by design, as the order line counts them (Didier
    # 2026-10-12); said so the PM knows which of them the client has not received yet.
    if invoice_mode:
        nd = len(drafts_counted)
    else:
        nd = client.search_count("account.move",
                                 [("line_ids.sale_line_ids.order_id", "in", so_ids),
                                  ("move_type", "in", ["out_invoice", "out_refund"]), ("state", "=", "draft")])
    if nd > 0:
        checks.append(_chk("info", "DRAFTS_IN_INVOICED",
                           f"Invoiced counts {nd} draft invoice(s) / credit note(s), as the order lines do — "
                           "not posted yet"))


    return {
        "kind": "hours_report", "version": 1, "project": slug or entry.get("slug") or "",
        "client": entry["client"], "language": entry.get("language") or "en",
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"), "issued_on": today.isoformat(),
        "mode": "invoice" if invoice_mode else "period", "invoice": inv_info, "period": period,
        "delivered_as_of": cutoff.isoformat(),
        "invoiced_upto": ({"invoice": inv_info["name"], "date": inv_info["invoice_date"]} if invoice_mode else None),
        "orders": out_orders, "tasks": tasks, "total_hours": _r(total_hours),
        "excluded": {"unlinked_hours": _r(unlinked_hours), "other_so_hours": _r(other_so_hours)},
        "checks": checks,
        "source_health": {"family": "odoo", "ok": True, "errors": {}},
        "source": {"family": "odoo",
                   "ref": "sale.order.line + account.move(.line) + account.analytic.line.unit_amount_rounded"},
    }


def _month_end(iso):
    y, m = int(iso[:4]), int(iso[5:7])
    return date(y, m, calendar.monthrange(y, m)[1])


def _label(line):
    txt = _u(line.get("name") or "")
    return (txt.strip().splitlines() or [""])[0].strip()
