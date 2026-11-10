import unittest
from datetime import date

from invoicing_day import rules
from invoicing_day.invoicing import _months_back, action_domain, jira_keys, month_bounds
from invoicing_day.odoo import READ_ONLY, Odoo, OdooError
from tests.fakes import FakeOdoo


class RulesTest(unittest.TestCase):
    def test_product_role(self):
        self.assertEqual(rules.product_role("P_01-bs-ts_ba"), "ba")
        self.assertEqual(rules.product_role("P_01-bs-ts_dev"), "dev")
        self.assertIsNone(rules.product_role("P_01-ts_project"))
        self.assertIsNone(rules.product_role(False))

    def test_families(self):
        self.assertEqual(rules.role_family("pm"), "functional")
        self.assertEqual(rules.role_family("arch"), "technical")
        self.assertEqual(rules.job_family("ICT Application Engineer"), "technical")
        self.assertIsNone(rules.job_family("ICT Team leader"))           # deliberately unclassified


class HelpersTest(unittest.TestCase):
    def test_activity_assignees_any_type(self):
        from invoicing_day.invoicing import activity_assignees
        acts = [{"activity_type_id": [5, "Validate/Send Invoice"], "user_id": [272, "Admin One"]},
                {"activity_type_id": [1, "Email"], "user_id": [7, "PM Two"]},
                {"activity_type_id": [4, "To Do"], "user_id": False}]
        self.assertEqual(activity_assignees(acts), ["Admin One", "PM Two", "unassigned"])
        self.assertEqual(activity_assignees([]), [])

    def test_d04_cards_grouped_biggest_first(self):
        from invoicing_day.invoicing import d04_cards
        lines = [{"jira": "A-1", "hours": 0.5}, {"jira": "A-2", "hours": 2.0}, {"jira": "A-1", "hours": 0.25},
                 {"jira": None, "hours": 0.1}]
        self.assertEqual(d04_cards(lines), [{"key": "A-2", "lines": 1, "hours": 2.0},
                                            {"key": "A-1", "lines": 2, "hours": 0.75},
                                            {"key": None, "lines": 1, "hours": 0.1}])

    def test_month_bounds(self):
        self.assertEqual(month_bounds("2026-10"), (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(month_bounds("2026-12"), (date(2026, 12, 1), date(2026, 12, 31)))
        self.assertEqual(month_bounds("2028-02")[1], date(2028, 2, 29))

    def test_jira_keys(self):
        self.assertEqual(jira_keys("FMEL, BIZ"), ["FMEL", "BIZ"])
        self.assertEqual(jira_keys("BSIDM"), ["BSIDM"])
        self.assertEqual(jira_keys(False), [])

    def test_months_back(self):
        self.assertEqual(_months_back(date(2026, 2, 1), 2), date(2025, 12, 1))
        self.assertEqual(_months_back(date(2026, 10, 1), 0), date(2026, 10, 1))

    def test_action_domain_evaluates_uid_and_today(self):
        fake = FakeOdoo({4101: {"name": "01 - My opportunities", "res_model": "crm.lead",
                                "domain": "['&',['user_id.id','=',uid],['date_deadline','<=',context_today()]]"}})
        d = action_domain(fake, 4101, date(2026, 11, 10))
        self.assertEqual(d["domain"], ["&", ["user_id.id", "=", 42], ["date_deadline", "<=", "2026-11-10"]])

    def test_action_domain_tuples(self):
        fake = FakeOdoo({4418: {"name": "04", "res_model": "account.analytic.line",
                                "domain": "[('task_id', '=', False), ('account_plan_id', 'in', [1, 2])]"}})
        self.assertEqual(action_domain(fake, 4418, date(2026, 11, 10))["domain"],
                         [["task_id", "=", False], ["account_plan_id", "in", [1, 2]]])


class ReadOnlyGuardTest(unittest.TestCase):
    def test_write_methods_refused_before_network(self):
        o = object.__new__(Odoo)              # no __init__: no network, no credentials
        for m in ("create", "write", "unlink", "action_post", "message_post"):
            with self.assertRaises(OdooError):
                o.execute_kw("account.move", m, [[1]])

    def test_whitelist_is_reads_only(self):
        self.assertEqual(READ_ONLY, frozenset({"search_read", "read", "read_group", "search", "search_count",
                                                "fields_get", "name_search"}))


if __name__ == "__main__":
    unittest.main()
