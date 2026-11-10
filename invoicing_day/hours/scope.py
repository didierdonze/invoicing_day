"""Hours report scope, built FROM THE PROJECT (replaces Compass's registry/projects.yaml).

Didier's rule: always work from the project, not directly from the SO — starting from an SO
risks leaving hours out. The orders of the report are therefore the confirmed orders that the
project's tasks and timesheet lines point to; `--so` can only narrow that list, never widen it.
Hours booked on the project outside these orders keep being reported by the fetcher
(UNLINKED_HOURS / OTHER_SO_HOURS).

Returns the `entry` dict the fetcher expects:
  {"slug", "odoo_project_id", "client", "language", "scopes": [{"sale_orders": [...]}]}
"""
from ..constants import _u
from .fetch import HoursRefusal

LANGS = {"fr": "fr", "de": "de", "en": "en"}


def find_project(client, ref):
    """A project by id ("2894") or by exact name ("fmel_odoo"); archived ones included."""
    ref = str(ref).strip()
    dom = [("id", "=", int(ref))] if ref.isdigit() else [("name", "=", ref)]
    rows = client.search_read("project.project", dom, ["id", "name", "partner_id", "active"],
                              context={"active_test": False})
    if not rows:
        raise HoursRefusal(f"project {ref!r} not found in Odoo (use its code, e.g. fmel_odoo, or its id).")
    if len(rows) > 1:
        raise HoursRefusal(f"project {ref!r} is ambiguous (ids {', '.join(str(r['id']) for r in rows)}) — pass the id.")
    return rows[0]


def project_orders(client, project_id):
    """Ids of the sale orders the project's tasks and timesheet lines point to."""
    line_ids = set()
    for t in client.search_read("project.task", [("project_id", "=", project_id), ("sale_line_id", "!=", False)],
                                ["sale_line_id"], context={"active_test": False}):
        line_ids.add(t["sale_line_id"][0])
    for g in client.read_group("account.analytic.line", [("project_id", "=", project_id), ("so_line", "!=", False)],
                               ["unit_amount"], ["so_line"]):
        if g.get("so_line"):
            line_ids.add(g["so_line"][0])
    if not line_ids:
        return []
    order_ids = {r["order_id"][0] for r in client.search_read("sale.order.line", [("id", "in", sorted(line_ids))],
                                                              ["order_id"]) if r.get("order_id")}
    return sorted(order_ids)


def project_entry(client, ref, sale_orders=None):
    pr = find_project(client, ref)
    order_ids = project_orders(client, pr["id"])
    orders = client.search_read("sale.order", [("id", "in", order_ids)], ["id", "name", "partner_id"],
                                order="date_order asc, id asc") if order_ids else []
    names = [o["name"] for o in orders]
    if sale_orders:
        wanted = [s.strip() for s in sale_orders if s and s.strip()]
        foreign = [s for s in wanted if s not in names]
        if foreign:
            raise HoursRefusal(f"{', '.join(foreign)} is not linked to project {pr['name']} "
                               f"(its orders: {', '.join(names) or 'none'}) — --so can only narrow the project's orders.")
        names = [n for n in names if n in wanted]
    partner_id = (pr.get("partner_id") or [None])[0] or (orders[0]["partner_id"][0] if orders and orders[0].get("partner_id") else None)
    client_name, lang = None, "en"
    if partner_id:
        p = client.read("res.partner", [partner_id], ["commercial_partner_id", "lang"])[0]
        cp_id = p["commercial_partner_id"][0] if p.get("commercial_partner_id") else partner_id
        cp = client.read("res.partner", [cp_id], ["name", "lang"])[0]
        client_name = _u(cp.get("name"))
        lang = LANGS.get(str(cp.get("lang") or p.get("lang") or "")[:2], "en")
    return {"slug": pr["name"], "odoo_project_id": pr["id"], "client": client_name, "language": lang,
            "scopes": [{"name": "project", "sale_orders": names}]}
