"""Monthly Invoicing Day — controls, invoicing proposal and progress. READ-ONLY on Odoo and Jira.

Follows BS › "How to - Invoice your project" (Confluence 902594711) and Didier's rule:
ALWAYS WORK FROM THE PROJECT, NOT FROM THE SO — the proposal starts from each project's
"To invoice" timesheet lines (timesheet_invoice_id = False) grouped by SO item; SO figures are
only a cross-check. Hours are the ROUNDED hours (unit_amount_rounded = the invoiced basis).

build_figures() returns the dict written to runs/AAAA-MM/figures.json. Every figure on the
Confluence page comes from it; Claude never computes one.
"""
import ast
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import rules
from .constants import CONFIRMED_STATES, TIME_UOM_NAMES, _u

TS = "account.analytic.line"
PL = "x_bi_sql_view.c2c_project_list"
REMAINING = "x_bi_sql_view.c2c_so_remaining_amount"
TZ = ZoneInfo("Europe/Zurich")
EPS = 1e-6
HOUR_NAMES = {"h", "hour", "hours", "heure", "heures", "hrs", "stunde", "stunden"}

SOL_FIELDS = ["id", "order_id", "name", "product_id", "product_uom", "product_uom_qty", "qty_delivered",
              "qty_invoiced", "qty_to_invoice", "untaxed_amount_to_invoice", "price_unit", "discount",
              "qty_delivered_method", "display_type", "is_downpayment", "currency_id", "state"]
SO_FIELDS = ["id", "name", "state", "date_order", "client_order_ref", "partner_id", "currency_id", "is_subscription",
             "next_invoice_date", "subscription_state", "recurring_monthly", "invoice_status"]


# ---------------------------------------------------------------- helpers

def jira_keys(raw):
    """'FMEL, BIZ' → ['FMEL', 'BIZ']."""
    return [k.strip().upper() for k in re.split(r"[,;\s]+", raw or "") if k.strip()]


def month_bounds(month):
    y, m = map(int, month.split("-"))
    first = date(y, m, 1)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return first, nxt - timedelta(days=1)


def _id(v):
    if isinstance(v, (list, tuple)):
        return v[0] if v else None
    return v or None


def _name(v):
    return _u(v[1]) if isinstance(v, (list, tuple)) and len(v) > 1 else None


def activity_assignees(activities):
    """Step 7: any open activity on the invoice counts, whatever its type; returns who it is assigned to."""
    return sorted({_name(a.get("user_id")) or "unassigned" for a in activities})


def d04_cards(lines):
    """Dashboard 04 lines grouped by Jira card (None = no card): what to fix, biggest first."""
    by = defaultdict(lambda: {"lines": 0, "hours": 0.0})
    for l in lines:
        d = by[l.get("jira")]
        d["lines"] += 1
        d["hours"] += l.get("hours") or 0.0
    return sorted(({"key": k, "lines": v["lines"], "hours": r2(v["hours"])} for k, v in by.items()),
                  key=lambda c: (-c["hours"], c["key"] or ""))


def r2(x):
    return None if x is None else round(float(x) + 0.0, 2)


def flag(level, code, msg):
    return {"level": level, "code": code, "msg": msg}


def action_domain(client, action_id, today):
    """Domain of a window action, evaluated like Odoo would for the current user."""
    a = client.read("ir.actions.act_window", [action_id], ["name", "res_model", "domain"])[0]
    s = a.get("domain") or "[]"
    s = re.sub(r"\buid\b", str(client.uid), s)
    s = s.replace("context_today()", repr(today.isoformat()))
    return {"action_id": action_id, "name": a["name"], "model": a["res_model"],
            "domain": [list(x) if isinstance(x, tuple) else x for x in ast.literal_eval(s)]}


def grammont_projects(client, department_id=rules.DEPARTMENT_ID):
    rows = client.search_read(PL, [["x_department_id", "=", department_id], ["x_active", "=", True]],
                              ["x_id", "x_name", "x_proj_manager_id", "x_last_activity_date",
                               "x_commercial_partner_id", "x_analytic_account_id"])
    out = []
    for r in rows:
        if not r.get("x_id"):
            continue
        out.append({"id": r["x_id"][0], "name": r["x_name"], "manager": _name(r.get("x_proj_manager_id")),
                    "last_activity": r.get("x_last_activity_date") or None,
                    "client": _name(r.get("x_commercial_partner_id")),
                    "analytic_account_id": _id(r.get("x_analytic_account_id"))})
    return sorted(out, key=lambda p: p["name"].lower())


def _hour_ratio_factory(client, uom_ids):
    """uom id → hours per unit (None when not a time unit)."""
    uoms = {u["id"]: u for u in client.search_read("uom.uom", [("id", "in", sorted(uom_ids))],
                                                   ["id", "name", "factor_inv", "category_id"],
                                                   context={"active_test": False})} if uom_ids else {}
    hour = client.search_read("uom.uom", [("name", "in", ["Hours", "Hour", "Heures", "h"])],
                              ["id", "name", "factor_inv", "category_id"], context={"active_test": False})
    hour = hour[0] if hour else None

    def hpu(uid_):
        u = uoms.get(uid_)
        if not u:
            return None
        if (u["name"] or "").strip().lower() in HOUR_NAMES:
            return 1.0
        if hour and _id(u["category_id"]) == _id(hour["category_id"]):
            return u["factor_inv"] / hour["factor_inv"]
        return None
    return hpu, uoms


# ---------------------------------------------------------------- the run

def build_figures(client, month, department_id=rules.DEPARTMENT_ID, projects=None, with_jira=True,
                  jira=None, today=None):
    first, last = month_bounds(month)
    today = today or date.today()
    year = first.year
    projs = grammont_projects(client, department_id)
    if projects:
        wanted = set(projects)
        unknown = wanted - {p["name"] for p in projs}
        if unknown:
            raise ValueError(f"not an active Grammont project: {', '.join(sorted(unknown))}")
        projs = [p for p in projs if p["name"] in wanted]
    pids = [p["id"] for p in projs]
    meta = {"skipped": [], "dashboards": {}}

    # project.project details (Jira key, customer)
    pdet = {p["id"]: p for p in client.search_read("project.project", [("id", "in", pids)],
                                                   ["id", "name", "jira_key", "partner_id", "user_id"],
                                                   context={"active_test": False})}

    # ---- Odoo › Invoicing Dashboards (domains read live)
    dash = {}
    for k, aid in rules.DASHBOARD_ACTIONS.items():
        try:
            dash[k] = action_domain(client, aid, today)
            meta["dashboards"][k] = {"action_id": aid, "name": dash[k]["name"]}
        except Exception as e:                                  # noqa: BLE001 — reported, never fatal
            meta["skipped"].append(f"dashboard {k} (action {aid}) unreadable: {e}")
    team = {"garbage_collectors": None, "crm": {}}
    if "01" in dash:
        gc = client.search_read(TS, dash["01"]["domain"] + [["employee_id.department_id", "=", department_id]],
                                ["id", "date", "employee_id", "project_id", "unit_amount", "jira_issue_key"],
                                order="date desc", limit=200)
        team["garbage_collectors"] = {
            "count": len(gc), "hours": r2(sum(l["unit_amount"] or 0 for l in gc)),
            "lines": [{"id": l["id"], "date": l["date"], "employee": _name(l["employee_id"]),
                       "project": _name(l["project_id"]), "jira": l.get("jira_issue_key") or None,
                       "hours": r2(l["unit_amount"]), "link": client.link(TS, l["id"])}
                      for l in gc[:rules.DETAIL_LIMIT]]}
    for k, aid in rules.CRM_ACTIONS.items():
        try:
            d = action_domain(client, aid, today)
            team["crm"][k] = {"name": d["name"], "count": client.search_count(d["model"], d["domain"])}
        except Exception as e:                                  # noqa: BLE001
            meta["skipped"].append(f"CRM {k} (action {aid}) unreadable: {e}")

    d02 = set()
    if "02" in dash:
        d02 = {r["id"] for r in client.search_read("project.project", dash["02"]["domain"] + [["id", "in", pids]], ["id"])}
    d03 = defaultdict(list)
    if "03" in dash:
        for t in client.search_read("project.task", dash["03"]["domain"] + [["project_id", "in", pids]],
                                    ["id", "name", "project_id"], limit=2000):
            d03[_id(t["project_id"])].append({"id": t["id"], "name": _u(t["name"]),
                                              "link": client.link("project.task", t["id"])})
    d04 = defaultdict(list)
    if "04" in dash:
        for l in client.search_read(TS, dash["04"]["domain"] + [["project_id", "in", pids]],
                                    ["id", "date", "project_id", "employee_id", "unit_amount", "jira_issue_key"],
                                    order="date desc", limit=5000):
            d04[_id(l["project_id"])].append({"id": l["id"], "date": l["date"], "employee": _name(l["employee_id"]),
                                              "jira": l.get("jira_issue_key") or None, "hours": r2(l["unit_amount"]),
                                              "link": client.link(TS, l["id"])})

    # ---- "To invoice" timesheet lines, FROM THE PROJECT (filter of project › Timesheet), up to month end
    ti = client.read_group(TS, [["project_id", "in", pids], ["timesheet_invoice_id", "=", False],
                                ["date", "<=", last.isoformat()]],
                           ["unit_amount:sum", "unit_amount_rounded:sum"],
                           ["project_id", "so_line", "timesheet_invoice_type", "employee_id"])
    # month lines without SO item (Steps 2–3) — month only: non-billable lines never leave "To invoice"
    no_so_month = defaultdict(dict)
    for g in client.read_group(TS, [["project_id", "in", pids], ["so_line", "=", False],
                                    ["date", ">=", first.isoformat()], ["date", "<=", last.isoformat()]],
                               ["unit_amount_rounded:sum"], ["project_id", "timesheet_invoice_type"]):
        no_so_month[_id(g["project_id"])][g.get("timesheet_invoice_type") or "none"] = g.get("unit_amount_rounded") or 0.0
    # month activity (rounding)
    act = {_id(g["project_id"]): g for g in client.read_group(
        TS, [["project_id", "in", pids], ["date", ">=", first.isoformat()], ["date", "<=", last.isoformat()]],
        ["unit_amount:sum", "unit_amount_rounded:sum"], ["project_id"])}
    # month lines with a Tempo status other than approved
    tempo = defaultdict(float)
    for g in client.read_group(TS, [["project_id", "in", pids], ["date", ">=", first.isoformat()],
                                    ["date", "<=", last.isoformat()], ["jira_tempo_status", "not in", [False, "approved"]]],
                               ["unit_amount:sum"], ["project_id"]):
        tempo[_id(g["project_id"])] += g["unit_amount"] or 0.0

    # ---- the project's orders: through its tasks and its timesheet lines (all time)
    proj_lines = defaultdict(set)
    for t in client.search_read("project.task", [["project_id", "in", pids], ["sale_line_id", "!=", False]],
                                ["project_id", "sale_line_id"], context={"active_test": False}):
        proj_lines[_id(t["project_id"])].add(_id(t["sale_line_id"]))
    for g in client.read_group(TS, [["project_id", "in", pids], ["so_line", "!=", False]], ["unit_amount:sum"],
                               ["project_id", "so_line"]):
        proj_lines[_id(g["project_id"])].add(_id(g["so_line"]))
    all_line_ids = sorted({l for s in proj_lines.values() for l in s if l})
    seed = {l["id"]: _id(l["order_id"]) for l in client.search_read("sale.order.line", [["id", "in", all_line_ids]],
                                                                     ["id", "order_id"])} if all_line_ids else {}
    proj_orders = {pid: sorted({seed[l] for l in ls if l in seed}) for pid, ls in proj_lines.items()}
    order_ids = sorted({o for os_ in proj_orders.values() for o in os_})
    orders = {o["id"]: o for o in client.search_read("sale.order", [["id", "in", order_ids]], SO_FIELDS)} if order_ids else {}
    # ACTIVE orders: hours booked on one of their lines in the last ACTIVE_MONTHS months, or confirmed
    # since the start of the invoiced month. SO-level checks and non-T&M amounts only consider them:
    # older orders often stay "to invoice" in Odoo forever (invoiced through down payments, closed blocks).
    win = _months_back(first, rules.ACTIVE_MONTHS - 1)
    recent_lines, month_lines = set(), set()
    for g in client.read_group(TS, [["project_id", "in", pids], ["so_line", "!=", False],
                                    ["date", ">=", win.isoformat()], ["date", "<=", last.isoformat()]],
                               ["unit_amount:sum"], ["so_line", "date:month"]):
        recent_lines.add(_id(g["so_line"]))
    for g in client.read_group(TS, [["project_id", "in", pids], ["so_line", "!=", False],
                                    ["date", ">=", first.isoformat()], ["date", "<=", last.isoformat()]],
                               ["unit_amount:sum"], ["so_line"]):
        month_lines.add(_id(g["so_line"]))
    sols = {l["id"]: l for l in client.search_read("sale.order.line", [["order_id", "in", order_ids]], SOL_FIELDS)} if order_ids else {}
    active_orders = {_id(sols[l]["order_id"]) for l in recent_lines if l in sols}
    active_orders |= {o for o, r in orders.items() if (r.get("date_order") or "")[:10] >= first.isoformat()}
    prod_ids = sorted({_id(l["product_id"]) for l in sols.values() if l.get("product_id")})
    prods = {p["id"]: p for p in client.search_read("product.product", [["id", "in", prod_ids]],
                                                    ["id", "default_code", "invoice_policy"],
                                                    context={"active_test": False})} if prod_ids else {}
    hpu, _uoms = _hour_ratio_factory(client, {_id(l["product_uom"]) for l in sols.values() if l.get("product_uom")})
    remaining = {_id(r["x_order_id"]): r for r in client.search_read(
        REMAINING, [["x_order_id", "in", order_ids]],
        ["x_order_id", "x_remaining_amount_invoiced", "x_remaining_amount_delivered"])} if order_ids else {}

    # employees' jobs (functional / technical check)
    emp_ids = sorted({_id(g["employee_id"]) for g in ti if g.get("employee_id")})
    jobs = {e["id"]: _name(e.get("job_id")) for e in client.read("hr.employee", emp_ids, ["job_id"],
                                                                  context={"active_test": False})} if emp_ids else {}

    # ---- unpaid & late, and this cycle's invoices (progress)
    moves = client.search_read("account.move", [["move_type", "=", "out_invoice"], ["state", "=", "posted"],
                                                ["payment_state", "in", ["not_paid", "partial"]],
                                                ["line_ids.sale_line_ids.order_id", "in", order_ids]],
                               ["id", "name", "invoice_date", "invoice_date_due", "amount_residual", "currency_id",
                                "payment_state", "invoice_origin"]) if order_ids else []
    cycle_start = last + timedelta(days=1)
    cyc = client.search_read("account.move", [["move_type", "in", ["out_invoice", "out_refund"]],
                                              ["state", "!=", "cancel"],
                                              ["create_date", ">=", cycle_start.isoformat() + " 00:00:00"],
                                              ["line_ids.sale_line_ids.order_id", "in", order_ids]],
                             ["id", "name", "move_type", "state", "invoice_date", "date", "ref", "amount_untaxed",
                              "currency_id", "invoice_origin"]) if order_ids else []
    cyc_ids = [m["id"] for m in cyc]
    atts = defaultdict(list)
    for a in (client.search_read("ir.attachment", [["res_model", "=", "account.move"], ["res_id", "in", cyc_ids]],
                                 ["res_id", "name", "mimetype"]) if cyc_ids else []):
        atts[a["res_id"]].append(a)
    acts = defaultdict(list)
    for a in (client.search_read("mail.activity", [["res_model", "=", "account.move"], ["res_id", "in", cyc_ids]],
                                 ["res_id", "activity_type_id", "user_id"]) if cyc_ids else []):
        acts[a["res_id"]].append(a)
    cyc_lines = defaultdict(set)          # move → its orders
    if cyc_ids:
        for ml in client.search_read("account.move.line", [["move_id", "in", cyc_ids], ["sale_line_ids", "!=", False]],
                                     ["move_id", "sale_line_ids"]):
            for sl in ml["sale_line_ids"]:
                if sl in sols:
                    cyc_lines[_id(ml["move_id"])].add(_id(sols[sl]["order_id"]))

    # ---- Jira
    jira_state = {"available": False, "reason": None}
    if with_jira:
        if jira is None:
            from . import jira as jira_mod
            jira = jira_mod.load()
        if jira is None:
            jira_state["reason"] = "no Jira configuration (~/.config/invoicing_day/jira.env)"
        else:
            jira_state["available"] = True
            jira_state["url"] = jira.url
    else:
        jira_state["reason"] = "disabled (--no-jira)"
    if not jira_state["available"]:
        meta["skipped"].append(f"Jira controls skipped: {jira_state['reason']}")
    # project.project.jira_key may hold several keys ("FMEL, BIZ"). A key used by several Grammont
    # projects (e.g. BIZ) cannot be attributed to one of them: it is left out and reported.
    all_keys = {pid: jira_keys(pdet.get(pid, {}).get("jira_key")) for pid in pids}
    usage = defaultdict(list)
    for pid, ks in all_keys.items():
        for k in ks:
            usage[k].append(pid)
    shared = sorted(k for k, ps in usage.items() if len(ps) > 1)
    keys = {pid: [k for k in ks if k not in shared] for pid, ks in all_keys.items()}
    if shared and jira_state["available"]:
        meta["skipped"].append("Jira key(s) shared by several projects, not checked: "
                               + ", ".join(f"{k} ({len(usage[k])} projects)" for k in shared))
    check_epic, jira_month = {}, {}
    if jira_state["available"]:
        try:
            check_epic, jira_month = _jira_controls(client, jira, keys, first, last)
        except Exception as e:                                  # noqa: BLE001 — reported, never fatal
            jira_state.update(available=False, reason=str(e))
            meta["skipped"].append(f"Jira controls failed: {e}")

    # ---- rows
    ti_by_p = defaultdict(list)
    for g in ti:
        ti_by_p[_id(g["project_id"])].append(g)
    rows = []
    for p in projs:
        pid = p["id"]
        rows.append(_row(client, p, pdet.get(pid, {}), ti_by_p[pid], act.get(pid), tempo.get(pid, 0.0),
                         proj_orders.get(pid, []), orders, sols, prods, hpu, remaining, jobs, moves, cyc,
                         cyc_lines, atts, acts, pid in d02, d03.get(pid, []), d04.get(pid, []),
                         ", ".join(all_keys.get(pid) or []) or None, check_epic.get(pid) if keys.get(pid) else None,
                         jira_month.get(pid), jira_state if keys.get(pid) or not all_keys.get(pid) else
                         {"available": False, "reason": "shared key only"}, first, last, today,
                         active_orders, month_lines, no_so_month.get(pid, {})))
    order = {"red": 0, "yellow": 1, "green": 2, "idle": 3}
    rows.sort(key=lambda r: (order[r["status"]], r["project"].lower()))

    totals = defaultdict(lambda: defaultdict(float))
    unpaid_tot = defaultdict(lambda: {"amount": 0.0, "count": 0, "late_amount": 0.0, "late_count": 0})
    for r in rows:
        for it in r["proposal"]:
            if it["amount"] is not None:
                totals[it["currency"]][it["kind"]] += it["amount"]
                totals[it["currency"]]["total"] += it["amount"]
        for u in r["unpaid"]:
            t = unpaid_tot[u["currency"]]
            t["amount"] += u["residual"]
            t["count"] += 1
            if u["days_late"] > 0:
                t["late_amount"] += u["residual"]
                t["late_count"] += 1
    month_name = f"{rules.MONTHS_EN[first.month - 1]} {first.year}"
    return {
        "kind": "invoicing_day", "version": 1, "month": month, "month_label": month_name,
        "period": {"from": first.isoformat(), "to": last.isoformat()}, "ytd_from": f"{year}-01-01",
        "generated_at": datetime.now(timezone.utc).astimezone(TZ).isoformat(timespec="seconds"),
        "today": today.isoformat(), "department_id": department_id,
        "invoice_defaults": {"invoice_date": today.isoformat(),
                             "accounting_date": today.replace(day=1).isoformat(),
                             "period": f"{year}-01-01 → {last.isoformat()} (year to date)",
                             "payment_reference": "leave blank (QR reference)",
                             "customer_reference": f"<SO name> - {month_name}"},
        "summary": {"projects": len(rows), **{s: sum(1 for r in rows if r["status"] == s) for s in order},
                    "to_invoice": {c: {k: r2(v) for k, v in d.items()} for c, d in totals.items()},
                    "unpaid": {c: {k: (r2(v) if isinstance(v, float) else v) for k, v in d.items()}
                               for c, d in unpaid_tot.items()}},
        "team": team, "jira": jira_state, "meta": meta, "rows": rows,
        "links": {"odoo": client.url},
    }


def _jira_controls(client, jira, keys, first, last):
    """Check Epic (How-to step 1A) + Jira vs Odoo hours of the month, per project."""
    by_key = {k: pid for pid, ks in keys.items() for k in ks}
    if not by_key:
        return {}, {}
    check = defaultdict(list)
    jql = f"project in ({', '.join(sorted(by_key))}) AND {rules.CHECK_EPIC_JQL} ORDER BY project ASC, key ASC"
    for i in jira.search(jql, fields=("summary", "timespent", "project")):
        k = i["key"].split("-")[0]
        f = i.get("fields") or {}
        check[by_key.get(k)].append({"key": i["key"], "summary": f.get("summary"),
                                     "hours": r2((f.get("timespent") or 0) / 3600), "link": jira.browse(i["key"])})
    a = int(datetime(first.year, first.month, first.day, tzinfo=TZ).timestamp() * 1000)
    b = int(datetime.combine(last + timedelta(days=1), datetime.min.time(), TZ).timestamp() * 1000)
    month = {}
    for pid, ks in keys.items():
        if not ks:
            continue
        jh, oh = {}, defaultdict(float)
        for k in ks:
            jql = (f'project = "{k}" AND worklogDate >= "{first.isoformat()}" AND worklogDate <= "{last.isoformat()}"')
            for i in jira.search(jql, fields=("summary",)):
                jh[i["key"]] = jira.worklog_seconds(i["key"], a, b) / 3600
            for l in client.search_read(TS, [["jira_issue_key", "=like", f"{k}-%"], ["date", ">=", first.isoformat()],
                                             ["date", "<=", last.isoformat()]], ["jira_issue_key", "unit_amount"]):
                oh[l["jira_issue_key"]] += l["unit_amount"] or 0.0
        diffs = []
        for issue in sorted(set(jh) | set(oh), key=lambda s: (len(s), s)):
            j, o = jh.get(issue, 0.0), oh.get(issue, 0.0)
            if abs(j - o) > rules.HOURS_TOLERANCE:
                diffs.append({"key": issue, "jira_h": r2(j), "odoo_h": r2(o), "link": jira.browse(issue)})
        month[pid] = {"jira_h": r2(sum(jh.values())), "odoo_h": r2(sum(oh.values())), "diffs": diffs}
    return dict(check), month


def _row(client, p, pd, ti, act, tempo_h, order_ids, orders, sols, prods, hpu, remaining, jobs, moves, cyc,
         cyc_lines, atts, acts, not_in_jira, d03, d04, jira_key, check_epic, jira_month, jira_state,
         first, last, today, active_orders, month_lines, no_so_month):
    flags = []
    pid = p["id"]
    month_name = f"{rules.MONTHS_EN[first.month - 1]} {first.year}"

    # Step 1 — Invoicing Dashboards 02/03/04 + Jira Check Epic
    if not_in_jira:
        # Didier 2026-11-10: a project with no Jira link (Connector tab empty = dashboard 02) is an
        # Odoo-only project by design — not an error, and it does not uncheck "1 Data clean".
        flags.append(flag("info", "ODOO_ONLY", "no Jira link (Connector tab empty): Odoo-only project, "
                                               "dashboard 02 and the Jira checks do not apply"))
    if d03:
        flags.append(flag("red", "D03_TASK_NO_SO", f"{len(d03)} task(s) not linked to an SO line (dashboard 03)"))
    if d04:
        flags.append(flag("red", "D04_TS_NO_TASK", f"{len(d04)} TS line(s) without task, "
                                                   f"{r2(sum(l['hours'] or 0 for l in d04))} h (dashboard 04)"))
    if check_epic:
        flags.append(flag("red", "JIRA_NO_EPIC", f"{len(check_epic)} Jira card(s) with time and no Epic (Check Epic filter)"))

    # Steps 2–3 — To invoice, grouped by SO item
    by_line = defaultdict(lambda: {"hours": 0.0, "rounded": 0.0})
    no_so = dict(no_so_month)
    category = defaultdict(float)
    for g in ti:
        sl = _id(g.get("so_line"))
        h, hr = g.get("unit_amount") or 0.0, g.get("unit_amount_rounded") or 0.0
        if not sl:
            continue
        by_line[sl]["hours"] += h
        by_line[sl]["rounded"] += hr
        line = sols.get(sl)
        if line:
            role = rules.product_role((prods.get(_id(line.get("product_id"))) or {}).get("default_code"))
            fam = rules.role_family(role)
            job = jobs.get(_id(g.get("employee_id")))
            jf = rules.job_family(job)
            if fam and jf and fam != jf:
                category[(sl, _name(g.get("employee_id")), job, role)] += hr
    no_so_h = sum(no_so.values())
    if no_so_h > EPS:
        flags.append(flag("yellow", "TS_NO_SO_ITEM", f"{r2(no_so_h)} h of {month_name} without SO item "
                                                    f"({', '.join(f'{k}: {r2(v)} h' for k, v in sorted(no_so.items()))})"
                                                    ""))
    cat_list = [{"so_line": ((_u(sols[sl]["name"]) or "").strip().splitlines() or [""])[0].strip()[:80], "employee": e, "job": j, "item_role": r.upper(),
                 "hours": r2(h)} for (sl, e, j, r), h in sorted(category.items(), key=lambda x: -x[1])]
    if cat_list:
        flags.append(flag("yellow", "ITEM_CATEGORY", f"{len(cat_list)} employee/item pair(s) where a functional profile "
                                                     "books on a technical item or the reverse"))

    # proposal + SO-level checks
    proposal, blocks, neg_remaining, stale = [], [], [], []
    for oid in order_ids:
        o = orders.get(oid)
        if not o or o["state"] not in CONFIRMED_STATES:
            continue
        active = oid in active_orders
        ref = _u(o.get("client_order_ref")) or o["name"]
        cur = _name(o.get("currency_id")) or "CHF"
        rem = remaining.get(oid)
        # "after delivered" is only meaningful when every timesheet-delivered line is sold in a time unit
        time_only = all(hpu(_id(l.get("product_uom"))) is not None for l in sols.values()
                        if _id(l["order_id"]) == oid and l.get("qty_delivered_method") == "timesheet"
                        and not l.get("display_type"))
        if active and rem and ((rem.get("x_remaining_amount_invoiced") or 0) < -0.005
                               or (time_only and (rem.get("x_remaining_amount_delivered") or 0) < -0.005)):
            neg_remaining.append({"so": o["name"], "remaining_invoiced": r2(rem.get("x_remaining_amount_invoiced")),
                                  "remaining_delivered": r2(rem.get("x_remaining_amount_delivered")),
                                  "link": client.link("sale.order", oid)})
        if o.get("is_subscription"):
            nid = o.get("next_invoice_date")
            if nid and nid <= _month_end(today).isoformat() and o.get("subscription_state") == "3_progress":
                proposal.append({"kind": "subscription", "so": o["name"], "so_id": oid, "line": "recurring",
                                 "hours": None, "qty": None, "uom": None, "currency": cur,
                                 "amount": r2(o.get("recurring_monthly")), "note": f"next invoice {nid}",
                                 "customer_reference": f"{ref} - {month_name}", "link": client.link("sale.order", oid)})
        for sl, l in sols.items():
            if _id(l["order_id"]) != oid or l.get("display_type") or l.get("is_downpayment"):
                continue
            prod = prods.get(_id(l.get("product_id"))) or {}
            method, policy = l.get("qty_delivered_method"), prod.get("invoice_policy")
            label = ((_u(l.get("name")) or "").strip().splitlines() or [""])[0].strip()[:90]
            ratio = hpu(_id(l.get("product_uom")))
            price = (l.get("price_unit") or 0.0) * (1 - (l.get("discount") or 0.0) / 100)
            base = {"so": o["name"], "so_id": oid, "line": label, "line_id": sl, "currency": cur,
                    "uom": _name(l.get("product_uom")), "customer_reference": f"{ref} - {month_name}",
                    "link": client.link("sale.order", oid)}
            if not active and (method != "timesheet" or policy == "order"):
                if (l.get("untaxed_amount_to_invoice") or 0) > 0.005:
                    stale.append({"so": o["name"], "line": label, "amount": r2(l.get("untaxed_amount_to_invoice")),
                                  "currency": cur, "link": base["link"]})
                continue
            if method == "timesheet" and policy == "order":
                # hours block / prepaid (incl. maintenance): invoiced on ordered qty; follow consumption
                ordered, delivered = l.get("product_uom_qty") or 0.0, l.get("qty_delivered") or 0.0
                # consumption only makes sense on lines sold in a time unit (a "1 year" maintenance
                # line sold in Units cannot be compared with booked hours)
                if ordered > EPS and sl in month_lines and ratio is not None:
                    pct = 100 * delivered / ordered
                    blocks.append({"so": o["name"], "line": label, "ordered": r2(ordered), "delivered": r2(delivered),
                                   "remaining": r2(ordered - delivered), "pct": r2(pct), "uom": base["uom"],
                                   "link": base["link"]})
                if (l.get("untaxed_amount_to_invoice") or 0) > 0.005:
                    proposal.append({**base, "kind": "block", "hours": None, "qty": r2(l.get("qty_to_invoice")),
                                     "amount": r2(l.get("untaxed_amount_to_invoice")), "note": "ordered, not yet invoiced"})
            elif method == "timesheet":
                # time & materials: FROM THE PROJECT's to-invoice hours on this item, up to month end
                h = by_line.get(sl, {}).get("rounded", 0.0)
                if abs(h) <= EPS:
                    continue
                qty = h / ratio if ratio else None
                amount = qty * price if qty is not None else None
                odoo_qty = l.get("qty_to_invoice") or 0.0
                note = None
                tol = rules.HOURS_TOLERANCE / (ratio or 1.0)
                if qty is not None and odoo_qty + tol < qty:
                    flags.append(flag("yellow", "HOURS_NOT_INVOICEABLE",
                                      f"{o['name']} / {label}: {r2(qty)} {base['uom']} not linked to any invoice on the "
                                      f"project, but Odoo has only {r2(odoo_qty)} left to invoice on the SO line "
                                      "(invoiced ≥ delivered) — invoiced without link, or to invoice?"))
                    note = f"Odoo to-invoice today: {r2(odoo_qty)}"
                proposal.append({**base, "kind": "tm", "hours": r2(h), "qty": r2(qty), "amount": r2(amount),
                                 "odoo_qty_to_invoice_today": r2(odoo_qty), "note": note})
            elif method == "milestones":
                if (l.get("untaxed_amount_to_invoice") or 0) > 0.005:
                    proposal.append({**base, "kind": "milestone", "hours": None, "qty": r2(l.get("qty_to_invoice")),
                                     "amount": r2(l.get("untaxed_amount_to_invoice")), "note": "milestone reached"})
            elif (l.get("untaxed_amount_to_invoice") or 0) > 0.005:
                proposal.append({**base, "kind": "manual", "hours": None, "qty": r2(l.get("qty_to_invoice")),
                                 "amount": r2(l.get("untaxed_amount_to_invoice")), "note": f"delivery: {method}"})
    if stale:
        flags.append(flag("info", "STALE_TO_INVOICE", f"{len(stale)} line(s) of inactive orders still 'to invoice' in "
                                                      f"Odoo ({r2(sum(x['amount'] or 0 for x in stale))} "
                                                      f"{stale[0]['currency']}) — ignored, not in the totals"))
    for b in blocks:
        if b["remaining"] is not None and b["remaining"] < -rules.HOURS_TOLERANCE:
            flags.append(flag("red", "BLOCK_NEGATIVE", f"{b['so']} / {b['line']}: {b['delivered']} of {b['ordered']} "
                                                       f"{b['uom']} consumed — beyond the ordered quantity (top-up or overrun)"))
        elif b["pct"] is not None and b["pct"] >= rules.BLOCK_WARN_PCT:
            flags.append(flag("yellow", "BLOCK_ALMOST_USED", f"{b['so']} / {b['line']}: {b['pct']} % consumed"))
    for n in neg_remaining:
        # Odoo › Dashboards "Invoicing day" › "SO with negative remaining amounts" (spreadsheet 51).
        # Invoiced beyond the order = red; delivered beyond it = the SO needs updating = yellow.
        lvl = "red" if (n["remaining_invoiced"] or 0) < -0.005 else "yellow"
        flags.append(flag(lvl, "SO_NEGATIVE_REMAINING", f"{n['so']}: remaining amount negative "
                                                        f"(after invoiced {n['remaining_invoiced']}, after delivered "
                                                        f"{n['remaining_delivered']}) — update the SO"))

    # Jira vs Odoo, Tempo status
    if jira_month and jira_month["diffs"]:
        flags.append(flag("red", "JIRA_ODOO_GAP", f"{len(jira_month['diffs'])} issue(s) where Jira and Odoo hours of "
                                                  f"{month_name} differ by more than {rules.HOURS_TOLERANCE} h"))
    if tempo_h > EPS:
        flags.append(flag("yellow", "TEMPO_NOT_APPROVED", f"{r2(tempo_h)} h of {month_name} not approved in Tempo"))
    if jira_key and not jira_state["available"]:
        flags.append(flag("info", "JIRA_SKIPPED", "Jira controls not run"))

    # unpaid & late
    my_orders = {orders[o]["name"] for o in order_ids if o in orders}
    unpaid = []
    for m in moves:
        origin = {s.strip() for s in (m.get("invoice_origin") or "").split(",")}
        if not origin & my_orders:
            continue
        due = m.get("invoice_date_due")
        late = (today - date.fromisoformat(due)).days if due else 0
        unpaid.append({"name": m["name"], "due": due, "days_late": max(0, late), "residual": r2(m["amount_residual"]),
                       "currency": _name(m.get("currency_id")) or "CHF", "payment_state": m["payment_state"],
                       "link": client.link("account.move", m["id"])})
    late = [u for u in unpaid if u["days_late"] > 0]
    if late:
        flags.append(flag("yellow", "UNPAID_LATE", f"{len(late)} invoice(s) overdue, "
                                                   f"{r2(sum(u['residual'] for u in late))} {late[0]['currency']}"))

    # progress (steps 4–7) on this cycle's invoices
    prog = []
    for m in cyc:
        if not cyc_lines.get(m["id"]) & set(order_ids):
            continue
        name = m["name"] if m.get("name") not in ("/", False, None) else f"draft #{m['id']}"
        pdfs = [a for a in atts.get(m["id"], []) if (a.get("mimetype") or "") == "application/pdf"]
        report = [a for a in pdfs if rules.REPORT_ATTACHMENT.search(a.get("name") or "")]
        assignees = activity_assignees(acts.get(m["id"], []))
        prog.append({"id": m["id"], "name": name, "kind": m["move_type"], "state": m["state"],
                     "invoice_date": m.get("invoice_date") or None, "accounting_date": m.get("date") or None,
                     "ref": m.get("ref") or None, "amount_untaxed": r2(m.get("amount_untaxed")),
                     "currency": _name(m.get("currency_id")) or "CHF",
                     "report_attached": bool(report), "admin_activity": bool(assignees), "activity_to": assignees,
                     "link": client.link("account.move", m["id"])})
    step1 = not any(f["code"] in ("D03_TASK_NO_SO", "D04_TS_NO_TASK", "JIRA_NO_EPIC") for f in flags)
    step23 = not any(f["code"] in ("TS_NO_SO_ITEM", "ITEM_CATEGORY", "HOURS_NOT_INVOICEABLE") for f in flags)
    invs = [x for x in prog if x["kind"] == "out_invoice"]
    progress = {"step1_clean": step1, "step23_hours": step23, "step45_draft": bool(invs),
                "step6_report": bool(invs) and all(x["report_attached"] for x in invs),
                "step7_activity": bool(invs) and all(x["admin_activity"] or x["state"] == "posted" for x in invs),
                "invoices": prog}

    levels = {f["level"] for f in flags}
    status = ("red" if "red" in levels else "yellow" if "yellow" in levels
              else "green" if proposal or prog else "idle")
    to_inv = defaultdict(float)
    for it in proposal:
        if it["amount"] is not None:
            to_inv[it["currency"]] += it["amount"]
    a_h, a_r = (act or {}).get("unit_amount") or 0.0, (act or {}).get("unit_amount_rounded") or 0.0
    return {
        "project": p["name"], "project_id": pid, "client": p.get("client") or _name(pd.get("partner_id")),
        "manager": p.get("manager"), "jira_key": jira_key, "last_activity": p.get("last_activity"),
        "status": status, "flags": flags,
        "orders": sorted({orders[o]["name"] for o in order_ids if o in orders and orders[o]["state"] in CONFIRMED_STATES}),
        "proposal": proposal, "to_invoice": {k: r2(v) for k, v in to_inv.items()},
        "controls": {
            "d02_not_in_jira": not_in_jira, "d03_tasks_no_so": d03[:rules.DETAIL_LIMIT], "d03_count": len(d03),
            "d04_ts_no_task": d04[:rules.DETAIL_LIMIT], "d04_count": len(d04),
            "d04_hours": r2(sum(l["hours"] or 0 for l in d04)), "d04_cards": d04_cards(d04)[:rules.DETAIL_LIMIT],
            "check_epic": None if check_epic is None and not jira_state["available"] else (check_epic or []),
            "no_so_item": {k: r2(v) for k, v in no_so.items()},
            "item_category": cat_list[:rules.DETAIL_LIMIT],
            "jira_vs_odoo": jira_month,
            "tempo_not_approved_h": r2(tempo_h),
            "rounding": {"month_hours": r2(a_h), "month_rounded": r2(a_r), "leak_h": r2(a_h - a_r),
                         "leak_pct": r2(100 * (a_h - a_r) / a_h) if a_h > EPS else None},
            "hours_blocks": blocks, "negative_remaining": neg_remaining, "stale_to_invoice": stale[:rules.DETAIL_LIMIT],
        },
        "unpaid": unpaid, "progress": progress,
        "links": {"project": client.link("project.project", pid)},
    }


def _months_back(first, n):
    y, m = first.year, first.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    return date(y, m, 1)


def _month_end(d):
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - timedelta(days=1)
