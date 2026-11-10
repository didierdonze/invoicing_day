"""Synthetic data for offline tests — no real customer data, no network."""


def figures(**over):
    row_green = {
        "project": "alpha_odoo", "project_id": 1, "client": "Alpha SA", "manager": "PM One", "jira_key": "ALP",
        "last_activity": "2026-10-30", "status": "green", "flags": [],
        "orders": ["SO-T0001"],
        "proposal": [{"kind": "tm", "so": "SO-T0001", "so_id": 10, "line": "Gestion de projet", "line_id": 100,
                      "currency": "CHF", "uom": "Hours", "customer_reference": "Support 2026 - October 2026",
                      "link": "https://odoo.example/web#id=10&model=sale.order&view_type=form",
                      "hours": 2.0, "qty": 2.0, "amount": 400.0, "odoo_qty_to_invoice_today": 2.5, "note": None}],
        "to_invoice": {"CHF": 400.0},
        "controls": {"d02_not_in_jira": False, "d03_tasks_no_so": [], "d03_count": 0, "d04_ts_no_task": [],
                     "d04_count": 0, "d04_hours": 0.0, "check_epic": [], "no_so_item": {}, "item_category": [],
                     "jira_vs_odoo": None, "tempo_not_approved_h": 0.0,
                     "rounding": {"month_hours": 2.0, "month_rounded": 2.0, "leak_h": 0.0, "leak_pct": 0.0},
                     "hours_blocks": [], "negative_remaining": [], "stale_to_invoice": []},
        "unpaid": [],
        "progress": {"step1_clean": True, "step23_hours": True, "step45_draft": False, "step6_report": False,
                     "step7_activity": False, "invoices": []},
        "links": {"project": "https://odoo.example/web#id=1&model=project.project&view_type=form"},
    }
    row_red = {**row_green, "project": "beta_odoo", "project_id": 2, "client": "Beta AG", "status": "red",
               "flags": [{"level": "red", "code": "D04_TS_NO_TASK", "msg": "3 TS line(s) without task, 1.5 h (dashboard 04)"},
                         {"level": "info", "code": "JIRA_SKIPPED", "msg": "Jira controls not run"}],
               "controls": {**row_green["controls"], "d04_count": 3, "d04_hours": 1.5,
                            "d04_ts_no_task": [{"id": 5, "date": "2026-10-02", "employee": "Dev Two", "jira": "BET-1",
                                                "hours": 0.5, "link": "https://odoo.example/x"}] * 3},
               "unpaid": [{"name": "CI-T-1", "due": "2026-09-01", "days_late": 70, "residual": 1000.0,
                           "currency": "CHF", "payment_state": "not_paid", "link": "https://odoo.example/m"}]}
    row_idle = {**row_green, "project": "gamma_odoo", "project_id": 3, "status": "idle", "proposal": [],
                "to_invoice": {}}
    fig = {
        "kind": "invoicing_day", "version": 1, "month": "2026-10", "month_label": "October 2026",
        "period": {"from": "2026-10-01", "to": "2026-10-31"}, "ytd_from": "2026-01-01",
        "generated_at": "2026-11-10T09:30:00+01:00", "today": "2026-11-10", "department_id": 23,
        "invoice_defaults": {"invoice_date": "2026-11-10", "accounting_date": "2026-11-01",
                             "period": "2026-01-01 → 2026-10-31 (year to date)",
                             "payment_reference": "leave blank (QR reference)",
                             "customer_reference": "<SO name> - October 2026"},
        "summary": {"projects": 3, "red": 1, "yellow": 0, "green": 1, "idle": 1,
                    "to_invoice": {"CHF": {"tm": 800.0, "total": 800.0}},
                    "unpaid": {"CHF": {"amount": 1000.0, "count": 1, "late_amount": 1000.0, "late_count": 1}}},
        "team": {"garbage_collectors": {"count": 0, "hours": 0.0, "lines": []},
                 "crm": {"leads": {"name": "My leads => should be empty", "count": 0}}},
        "jira": {"available": False, "reason": "disabled (--no-jira)"},
        "meta": {"skipped": ["Jira controls skipped: disabled (--no-jira)"],
                 "dashboards": {"04": {"action_id": 4418, "name": "04 - TS lines without tasks"}}},
        "rows": [row_red, row_green, row_idle],
        "links": {"odoo": "https://odoo.example"},
    }
    fig.update(over)
    return fig


class FakeOdoo:
    """Answers the few calls the unit-tested helpers make."""
    uid = 42
    url = "https://odoo.example"

    def __init__(self, actions=None):
        self.actions = actions or {}

    def read(self, model, ids, fields=None, **kw):
        assert model == "ir.actions.act_window"
        return [self.actions[i] for i in ids]

    def link(self, model, rec_id):
        return f"{self.url}/web#id={rec_id}&model={model}&view_type=form"
