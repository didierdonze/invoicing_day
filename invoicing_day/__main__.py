"""Command line: python3 -m invoicing_day <command> …

  projects                         active Grammont projects (department 23)
  run --month AAAA-MM [--out F]    controls + invoicing proposal → figures.json
  page --figures F --out B [--previous P] [--same-page]   figures.json → body.html + report.md (offline)
  diff --old F1 --new F2           what changed between two runs of the same month (offline)
  hours invoices <project>         invoices of the project's orders + linked hours
  hours report <project> (--invoice N|ID | --from D --to D) [--so SO …] [--html-only]

Exit codes: 0 ok · 1 failure · 2 hours report REFUSED · 3 Odoo unreachable (VPN?) ·
4 Odoo refused a call · 5 configuration missing.
Everything is READ-ONLY on Odoo and Jira; files are written under runs/ only.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .odoo import Odoo, OdooError

REPO_ROOT = Path(__file__).resolve().parent.parent


def _fmt_dmy(d):
    return f"{d[8:10]}.{d[5:7]}.{d[:4]}" if d else "—"


def _month(s):
    try:
        y, m = map(int, s.split("-"))
        date(y, m, 1)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid month {s!r}, expected AAAA-MM")
    return f"{y}-{m:02d}"


# ---------------------------------------------------------------- hours

def cmd_hours_invoices(args):
    from .hours import fetch as fh
    from .hours.scope import project_entry
    client = Odoo()
    try:
        entry = project_entry(client, args.project, args.so)
        invs = fh.list_invoices(client, entry, limit=args.limit)
    except fh.HoursRefusal as e:
        print(f"invoicing_day — invoices — {args.project} — REFUSED: {e}")
        return 2
    orders = entry["scopes"][0]["sale_orders"]
    print(f"invoicing_day — invoices — {entry['slug']} ({', '.join(orders)})")
    print(f"  {'id':<8} {'number':<16} {'date':<12} {'state':<8} {'kind':<12} {'linked h':>8}")
    for i in invs:
        number = i["name"] or f"(draft #{i['id']})"
        print(f"  {i['id']:<8} {number:<16} {_fmt_dmy(i['invoice_date']):<12} {i['state'] or '':<8} "
              f"{i['kind']:<12} {i['linked_hours']:>8.2f}")
    print(f"→ python3 -m invoicing_day hours report {entry['slug']} --invoice <number or id>   "
          "(0 linked h → invoice mode refuses: use --from/--to)")
    return 0


def cmd_hours_report(args):
    from . import pdf
    from .hours import fetch as fh, render
    from .hours.scope import project_entry
    client = Odoo()
    try:
        entry = project_entry(client, args.project, args.so)
        if args.lang:                      # default: the customer's language in Odoo (as the invoice)
            entry["language"] = args.lang
        facts = fh.fetch_hours(client, entry, invoice=args.invoice, date_from=args.date_from,
                               date_to=args.date_to, slug=entry["slug"])
    except fh.HoursRefusal as e:
        print(f"invoicing_day — hours report — {args.project} — REFUSED: {e}")
        return 2
    out_dir = args.out_dir or None
    try:
        result = render.render(facts, html_only=args.html_only, out_dir=out_dir)
    except pdf.PdfError as e:
        d = Path(out_dir or render.default_out_dir(facts))
        lines = [f"invoicing_day — hours report — {facts['project']}"]
        for key in ("html", "json"):
            p = d / (render.output_stem(facts) + "." + key)
            if p.exists():
                lines.append(f"{key}: {render.rel(p)}")
        lines.append(f"FAILED: {e}")
        print("\n".join(lines))
        return 1
    print(render.render_summary(facts, result))
    return 0


# ---------------------------------------------------------------- monthly run

def cmd_projects(args):
    from .invoicing import grammont_projects
    client = Odoo()
    for p in grammont_projects(client, args.department_id):
        print(f"  {p['name']:<32} {p['manager'] or '—':<24} last activity {p['last_activity'] or '—'}")
    return 0


def cmd_run(args):
    from .invoicing import build_figures
    client = Odoo()
    figures = build_figures(client, args.month, department_id=args.department_id,
                            projects=args.projects, with_jira=not args.no_jira)
    text = json.dumps(figures, indent=2, ensure_ascii=False)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():                       # keep the previous run for `diff`
            out.replace(out.with_name(out.stem + ".prev" + out.suffix))
        out.write_text(text, encoding="utf-8")
        s = figures["summary"]
        print(f"invoicing_day — {figures['month']} — {s['projects']} projects: "
              f"{s['red']} red · {s['yellow']} yellow · {s['green']} green · {s['idle']} idle → {out}")
    else:
        print(text)
    return 0


def cmd_page(args):
    """Offline: figures.json (+ previous page HTML for the Comments column) → body.html + report.md."""
    from .page import build_body, extract_comments, title
    from .report import build_report
    fig = json.loads(Path(args.figures).read_text(encoding="utf-8"))
    comments = {}
    if args.previous:
        comments = extract_comments(Path(args.previous).read_text(encoding="utf-8"), same_page=args.same_page)
    known = {r["project"] for r in fig["rows"]}
    dropped = sorted(set(comments) - known)
    body = build_body(fig, comments)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    rep = out.with_name("report.md")
    rep.write_text(build_report(fig, page_url=args.page_url, carried=len(set(comments) & known)), encoding="utf-8")
    print(f"title: {title(fig)}")
    print(f"body: {out} ({len(body)} chars) · report: {rep}")
    print(f"comments carried over: {len(set(comments) & known)}"
          + (f" · NOT carried (project no longer active): {', '.join(dropped)}" if dropped else ""))
    return 0


def cmd_diff(args):
    """Offline: what changed between two runs of the same month (status, amount, checklist)."""
    old = {r["project"]: r for r in json.loads(Path(args.old).read_text(encoding="utf-8"))["rows"]}
    new = {r["project"]: r for r in json.loads(Path(args.new).read_text(encoding="utf-8"))["rows"]}
    steps = ("step1_clean", "step23_hours", "step45_draft", "step6_report", "step7_activity")
    changed = 0
    for p in sorted(set(old) | set(new)):
        a, b = old.get(p), new.get(p)
        if not a or not b:
            print(f"  {p}: {'added' if b else 'removed'}")
            changed += 1
            continue
        bits = []
        if a["status"] != b["status"]:
            bits.append(f"status {a['status']} → {b['status']}")
        if a["to_invoice"] != b["to_invoice"]:
            bits.append(f"to invoice {a['to_invoice'] or '—'} → {b['to_invoice'] or '—'}")
        done = [s for s in steps if b["progress"].get(s) and not a["progress"].get(s)]
        undone = [s for s in steps if a["progress"].get(s) and not b["progress"].get(s)]
        if done:
            bits.append("done: " + ", ".join(done))
        if undone:
            bits.append("no longer done: " + ", ".join(undone))
        fixed = sorted({f["code"] for f in a["flags"]} - {f["code"] for f in b["flags"]})
        new_f = sorted({f["code"] for f in b["flags"]} - {f["code"] for f in a["flags"]})
        if fixed:
            bits.append("fixed: " + ", ".join(fixed))
        if new_f:
            bits.append("new: " + ", ".join(new_f))
        if bits:
            changed += 1
            print(f"  {p}: " + " · ".join(bits))
    print(f"{changed} project(s) changed")
    return 0


# ---------------------------------------------------------------- parser

class _Parser(argparse.ArgumentParser):
    def parse_known_args(self, args=None, namespace=None):
        ns, rest = super().parse_known_args(args, namespace)
        if hasattr(ns, "date_from") and getattr(ns, "cmd", None) == "report":
            if (ns.date_from is None) != (ns.date_to is None) or (ns.invoice is not None and ns.date_to is not None):
                self.error("--from and --to are required together, and exclusive with --invoice")
            if ns.invoice is None and ns.date_from is None:
                self.error("give --invoice, or --from and --to")
        return ns, rest


def build_parser():
    ap = _Parser(prog="python3 -m invoicing_day", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="group", required=True)

    pr = sub.add_parser("projects", help="READ-ONLY: active Grammont projects.")
    pr.add_argument("--department-id", type=int, default=23)
    pr.set_defaults(func=cmd_projects)

    run = sub.add_parser("run", help="READ-ONLY: controls + proposal for one month → figures.json.")
    run.add_argument("--month", type=_month, required=True, help="invoiced month AAAA-MM")
    run.add_argument("--out", help="figures.json path (default: stdout)")
    run.add_argument("--department-id", type=int, default=23)
    run.add_argument("--projects", nargs="*", help="limit to these project codes (default: all active Grammont)")
    run.add_argument("--no-jira", action="store_true", help="skip the Jira controls")
    run.set_defaults(func=cmd_run)

    pg = sub.add_parser("page", help="Offline: figures.json → Confluence body.html + report.md.")
    pg.add_argument("--figures", required=True, help="runs/AAAA-MM/figures.json")
    pg.add_argument("--previous", help="HTML of the previous edition (or of the page being updated): "
                                       "its Comments column is carried over verbatim")
    pg.add_argument("--out", required=True, help="runs/AAAA-MM/body.html (report.md is written next to it)")
    pg.add_argument("--page-url", help="URL of the Confluence page, for the report")
    pg.add_argument("--same-page", action="store_true",
                    help="--previous is the page being UPDATED: keep its local ids and inline-comment anchors")
    pg.set_defaults(func=cmd_page)

    df = sub.add_parser("diff", help="Offline: changes between two figures.json of the same month.")
    df.add_argument("--old", required=True)
    df.add_argument("--new", required=True)
    df.set_defaults(func=cmd_diff)

    hr = sub.add_parser("hours", help="Client hours report (ported from Compass).")
    hsub = hr.add_subparsers(dest="cmd", required=True)
    hi = hsub.add_parser("invoices", help="READ-ONLY: invoices of the project's orders + linked hours.")
    hi.add_argument("project", help="project code (e.g. fmel_odoo) or id")
    hi.add_argument("--so", nargs="*", help="narrow to these sale orders of the project")
    hi.add_argument("--limit", type=int, default=20)
    hi.set_defaults(func=cmd_hours_invoices)
    hrr = hsub.add_parser("report", help="READ-ONLY on Odoo; writes runs/AAAA-MM/hours/<project>/ only.")
    hrr.add_argument("project", help="project code (e.g. fmel_odoo) or id")
    g = hrr.add_mutually_exclusive_group()
    g.add_argument("--invoice", help="invoice number, or its id (drafts named '/' by id only)")
    g.add_argument("--from", dest="date_from", type=date.fromisoformat, metavar="YYYY-MM-DD")
    hrr.add_argument("--to", dest="date_to", type=date.fromisoformat, metavar="YYYY-MM-DD")
    hrr.add_argument("--so", nargs="*", help="narrow to these sale orders of the project")
    hrr.add_argument("--html-only", action="store_true", help="write HTML + JSON, skip the PDF")
    hrr.add_argument("--lang", choices=["fr", "de", "en"],
                     help="report language (default: the customer's language in Odoo, like the invoice)")
    hrr.add_argument("--out-dir", help="output folder (default: runs/AAAA-MM/hours/<project>/)")
    hrr.set_defaults(func=cmd_hours_report)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except OdooError as e:
        print(f"invoicing_day — ERROR: {e}", file=sys.stderr)
        return e.exit_code


if __name__ == "__main__":
    sys.exit(main())
