"""Hours report (ported from Compass): customer-safety rules, offline."""
import re
from pathlib import Path
import unittest

from invoicing_day.hours import fetch
from invoicing_day.hours.render import build_html, check_customer_safe, output_stem


def facts(**over):
    f = {"kind": "hours_report", "version": 1, "project": "alpha_odoo", "client": "Alpha SA", "language": "fr",
         "as_of": "2026-11-10T08:00:00+00:00", "issued_on": "2026-11-10", "mode": "period", "invoice": None,
         "period": {"from": "2026-10-01", "to": "2026-10-31", "basis": "requested"},
         "delivered_as_of": "2026-10-31", "invoiced_upto": None,
         "orders": [{"id": 1, "name": "SO-T0001", "client_ref": "Support 2026", "lines": [
             {"kind": "section", "label": "Services"},
             {"kind": "line", "id": 11, "label": "Gestion de projet", "uom": "h", "time": True, "hours_per_unit": 1.0,
              "decimals": 2, "ordered": 10.0, "delivered": 4.5, "delivered_now": 5.0, "invoiced": 2.0,
              "invoiced_now": 2.0, "this": 2.5}]}],
         "tasks": [{"task_id": 7, "label": "SO-T0001 - Gestion de projet", "hours": 2.5}],
         "total_hours": 2.5, "excluded": {"unlinked_hours": 0.0, "other_so_hours": 0.0}, "checks": []}
    f.update(over)
    return f


class FieldAllowListTest(unittest.TestCase):
    """Quantities only: money, people and timesheet descriptions are never even read."""

    def test_no_money_people_or_descriptions(self):
        fields = fetch.SO_FIELDS + fetch.LINE_FIELDS + fetch.MOVE_FIELDS + fetch.MOVE_LINE_FIELDS + fetch.UOM_FIELDS
        for f in fields:
            self.assertFalse(re.match(r"(price|amount|employee|user_id)", f), f)
        self.assertIn("is_expense", fetch.LINE_FIELDS)        # expense lines are filtered out (employee names)
        src = Path(fetch.__file__).read_text(encoding="utf-8")
        self.assertNotIn('"employee_id"', src)
        self.assertNotIn('"price_unit"', src)


class RenderTest(unittest.TestCase):
    def test_html_is_self_contained_and_quantities_only(self):
        doc, ours, odoo = build_html(facts())
        self.assertIn("Rapport d'heures", doc)
        self.assertIn("Alpha SA", doc)
        self.assertNotIn("alpha_odoo", doc)                 # the project code never reaches the client
        self.assertNotIn("CHF", doc)
        self.assertNotIn("http://", doc.replace("http://www.w3.org", ""))   # images are data URIs
        self.assertIn("02:30", doc)                         # hours as HH:MM

    def test_forbidden_word_in_our_text_refuses(self):
        with self.assertRaises(RuntimeError):
            check_customer_safe(["Rapport de marge"], [])

    def test_forbidden_word_in_odoo_label_only_warns(self):
        out = check_customer_safe([], ["Calcul de la marge"])
        self.assertEqual(out[0]["code"], "ODOO_TERM")

    def test_output_stem(self):
        self.assertEqual(output_stem(facts()), "Rapport-heures_Alpha-SA_2026-10-01_2026-10-31")
        inv = facts(mode="invoice", invoice={"id": 9, "name": "CI-CH26-1", "draft": False})
        self.assertEqual(output_stem(inv), "Rapport-heures_Alpha-SA_CI-CH26-1")


if __name__ == "__main__":
    unittest.main()
