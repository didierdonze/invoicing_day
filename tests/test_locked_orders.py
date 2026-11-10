"""Locked sale orders are out of the proposal and of the SO-level checks (Didier 2026-11-10)."""
import unittest
from datetime import date

from invoicing_day.invoicing import _row
from tests.fakes import FakeOdoo


def so(oid, name, locked):
    return {"id": oid, "name": name, "state": "sale", "date_order": "2025-01-01 00:00:00", "client_order_ref": False,
            "currency_id": [1, "CHF"], "is_subscription": False, "locked": locked}


def tm_line(lid, oid):
    return {"id": lid, "order_id": [oid, "x"], "name": "Développement", "product_id": [1, "Dev"],
            "product_uom": [27, "Hours"], "product_uom_qty": 0.0, "qty_delivered": 3.0, "qty_invoiced": 0.0,
            "qty_to_invoice": 3.0, "untaxed_amount_to_invoice": 600.0, "price_unit": 200.0, "discount": 0.0,
            "qty_delivered_method": "timesheet", "display_type": False, "is_downpayment": False}


def row(month_hours):
    orders = {10: so(10, "SO-T0010", False), 20: so(20, "SO-T0020", True)}
    sols = {100: tm_line(100, 10), 200: tm_line(200, 20)}
    ti = [{"so_line": [100, "x"], "unit_amount": 3.0, "unit_amount_rounded": 3.0, "employee_id": [2, "Dev Two"]},
          {"so_line": [200, "x"], "unit_amount": 50.0, "unit_amount_rounded": 50.0, "employee_id": [1, "Dev One"]}]
    return _row(FakeOdoo(), {"id": 1, "name": "alpha_odoo"}, {}, ti, None, 0.0, [10, 20], orders, sols,
                {1: {"invoice_policy": "delivery", "default_code": "P_01-bs-ts_dev"}}, lambda u: 1.0, {},
                {1: "ICT Consultant", 2: "ICT Application Engineer"}, [], [], {}, {}, {}, False, [], [], None, None, None, {"available": False},
                date(2026, 10, 1), date(2026, 10, 31), date(2026, 11, 10), {10, 20}, {100, 200}, {}, month_hours)


class LockedOrdersTest(unittest.TestCase):
    def test_locked_order_left_out_of_proposal_and_checks(self):
        r = row({100: 1.0, 200: 1.5})
        self.assertEqual([it["so"] for it in r["proposal"]], ["SO-T0010"])
        self.assertEqual(r["orders"], ["SO-T0010"])
        self.assertEqual(r["locked_orders"], ["SO-T0020"])
        codes = [f["code"] for f in r["flags"]]
        self.assertNotIn("HOURS_NOT_INVOICEABLE", codes)
        self.assertNotIn("ITEM_CATEGORY", codes)      # a functional profile on a dev item, but on the locked order
        locked = [f for f in r["flags"] if f["code"] == "LOCKED_SO_HOURS"]
        self.assertEqual(len(locked), 1)
        self.assertEqual(locked[0]["level"], "info")
        self.assertIn("1.5 h of October 2026", locked[0]["msg"])
        self.assertIn("SO-T0020", locked[0]["msg"])

    def test_no_flag_without_hours_of_the_month_on_a_locked_order(self):
        r = row({100: 1.0})
        self.assertNotIn("LOCKED_SO_HOURS", [f["code"] for f in r["flags"]])


if __name__ == "__main__":
    unittest.main()
