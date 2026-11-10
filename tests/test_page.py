import unittest

from invoicing_day.page import build_body, extract_comments, title
from invoicing_day.report import build_report
from tests.fakes import figures


class PageTest(unittest.TestCase):
    def test_title(self):
        self.assertEqual(title(figures()), "2026.10 - Invoicing Day Grammont")

    def test_body_orders_rows_and_hides_idle(self):
        body = build_body(figures())
        self.assertLess(body.index("<strong>beta_odoo</strong>"), body.index("<strong>alpha_odoo</strong>"))
        self.assertNotIn("<strong>gamma_odoo</strong>", body)          # idle → listed in one line
        self.assertIn("Nothing to invoice and nothing to fix: gamma_odoo", body)
        self.assertIn('data-type="status" data-color="red">TO FIX', body)
        self.assertIn("CHF 400.00", body)
        self.assertIn("Not checked in this run", body)                 # skipped controls are visible

    def test_idle_row_kept_when_it_has_a_comment(self):
        body = build_body(figures(), {"gamma_odoo": "<p>keep me</p>"})
        self.assertIn("<strong>gamma_odoo</strong>", body)
        self.assertIn("<p>keep me</p>", body)

    def test_comments_round_trip(self):
        comments = {"beta_odoo": '<p>Relance <strong>faite</strong> &amp; OK</p><ul><li>voir PM</li></ul>',
                    "alpha_odoo": "<p>Facture en attente</p>"}
        body = build_body(figures(), comments)
        self.assertEqual(extract_comments(body), comments)

    def test_comments_strip_old_page_ids_unless_same_page(self):
        html_ = ('<table><thead><tr><th><p>Project</p></th><th><p>Comments</p></th></tr></thead><tbody>'
                 '<tr><td><p><strong>x_odoo</strong></p></td><td><p data-local-id="abcdefabcdef">A '
                 '<span class="annotation" data-annotation-id="q" data-annotation-type="inlineComment">b</span></p>'
                 '</td></tr></tbody></table>')
        self.assertEqual(extract_comments(html_), {"x_odoo": "<p>A b</p>"})
        self.assertIn('data-local-id="abcdefabcdef"', extract_comments(html_, same_page=True)["x_odoo"])

    def test_empty_comments_ignored(self):
        self.assertEqual(extract_comments(build_body(figures())), {})

    def test_no_storage_xml(self):
        body = build_body(figures())
        self.assertNotIn("<ac:", body)                                  # format guide: never storage XML
        self.assertNotIn("<html", body)

    def test_report_conclusion_first(self):
        rep = build_report(figures())
        first = [l for l in rep.splitlines() if l.strip()][1]
        self.assertTrue(first.startswith("**1 projet(s) à corriger"))
        self.assertIn("D04_TS_NO_TASK", rep)
        self.assertNotIn("JIRA_SKIPPED", rep)                           # info flags stay out of the report


if __name__ == "__main__":
    unittest.main()
