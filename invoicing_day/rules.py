"""Business rules of the Invoicing Day — every threshold and mapping in one place.

Sources: BS › "How to - Invoice your project" (Confluence page 902594711) and Didier's choices.
Values marked TO CONFIRM were inferred from Odoo data on 2026-11-10 and still need Didier's OK.
Each one can be overridden by an environment variable of the same name prefixed with INVOICING_.
"""
import os
import re


def _env_float(name, default):
    return float(os.environ.get(f"INVOICING_{name}", default))


def _env_int(name, default):
    return int(os.environ.get(f"INVOICING_{name}", default))


# ---------------------------------------------------------------- scope
DEPARTMENT_ID = _env_int("DEPARTMENT_ID", 23)          # hr.department "3.1 - Grammont"

# ---------------------------------------------------------------- Odoo › Dashboards › Invoicing Dashboards
# Their domains are read LIVE from these window actions, so a change in Odoo is followed.
DASHBOARD_ACTIONS = {
    "01": 4417,     # 01 - Garbage Collectors (account.analytic.line) — team-level: our employees' lines
    "02": 4419,     # 02 - Projects not linked with Jira (project.project)
    "03": 4420,     # 03 - Tasks not linked to a SO line (project.task)
    "04": 4418,     # 04 - TS lines without tasks (account.analytic.line)
}
CRM_ACTIONS = {"leads": 4100, "opportunities": 4101}    # 01 - My leads / My opportunities to clean

# ---------------------------------------------------------------- Step 6: hours report attached
REPORT_ATTACHMENT = re.compile(r"rapport|heures|stunden|hours|timesheet|feuille", re.I)

# ---------------------------------------------------------------- Steps 2–3: functional vs technical items
# SO item role, from the product internal reference (e.g. "P_01-bs-ts_ba").
PRODUCT_ROLE = re.compile(r"ts_(ba|pm|fsc|pdir|am|dev|arch)\b", re.I)
FUNCTIONAL_ROLES = {"ba", "pm", "fsc", "pdir", "am"}    # AM, BA, PM (How-to) + FSC, PDIR
TECHNICAL_ROLES = {"dev", "arch"}                       # DEV / ARCH (How-to)
# Employee side, from hr.employee.job_id — TO CONFIRM. Team leader, Department manager and
# Subcontractor are deliberately left unclassified (no flag rather than a false one).
FUNCTIONAL_JOBS = {"ICT Consultant", "ICT Consultant (SC)", "ICT Application Manager", "ICT Project manager"}
TECHNICAL_JOBS = {"ICT Application Engineer", "ICT Architect", "ICT DevOps Engineer"}

# ---------------------------------------------------------------- tolerances and thresholds
HOURS_TOLERANCE = _env_float("HOURS_TOLERANCE", 0.25)     # Jira vs Odoo, project vs SO line (h)
BLOCK_WARN_PCT = _env_float("BLOCK_WARN_PCT", 90)         # hours block consumed ≥ this → yellow
DETAIL_LIMIT = _env_int("DETAIL_LIMIT", 15)               # offending lines listed per control
ACTIVE_MONTHS = _env_int("ACTIVE_MONTHS", 3)              # an SO is "active" with hours in these last months

# ---------------------------------------------------------------- Jira "Check Epic" filter (How-to, step 1A)
CHECK_EPIC_JQL = ("timespent > 0 AND type NOT IN (Epic) AND updatedDate >= startOfMonth(-3M) "
                  "AND parent = empty")

# ---------------------------------------------------------------- Step 5: invoice fields
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"]


def product_role(default_code):
    m = PRODUCT_ROLE.search(default_code or "")
    return m.group(1).lower() if m else None


def role_family(role):
    if role in FUNCTIONAL_ROLES:
        return "functional"
    if role in TECHNICAL_ROLES:
        return "technical"
    return None


def job_family(job_name):
    if job_name in FUNCTIONAL_JOBS:
        return "functional"
    if job_name in TECHNICAL_JOBS:
        return "technical"
    return None
