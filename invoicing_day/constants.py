"""Small constants and helpers shared across modules.

Origin (Compass, ~/.openclaw/workspace, commit 506671a): FORBIDDEN comes from compass/deck.py;
CONFIRMED_STATES, TIME_UOM_NAMES and _u from compass/fetchers/odoo.py.
"""
import html
import re

# Words Compass-authored text must never show a client (hours report). An Odoo label that
# contains one only raises an ODOO_TERM warning for the PM.
FORBIDDEN = re.compile(r"\b(marge|margin|co[ûu]t interne|internal cost|cost_eur|board_warning)\b", re.I)

# Confirmed sale orders (quotations are left out of every report).
CONFIRMED_STATES = ("sale", "done")

TIME_UOM_NAMES = {"h", "hour", "hours", "heure", "heures", "hrs", "stunde", "stunden",
                  "days (7h)", "days (8h)", "day (7h)", "day (8h)", "jours (7h)", "jours (8h)"}


def _u(s):
    """Un-escape Odoo Char fields on mail.thread models.

    c2c's instance returns these single- OR double-escaped (e.g. '&amp;amp;'), so unescape
    repeatedly until stable. Idempotent for clean strings; bounded against pathological input.
    """
    if not isinstance(s, str):
        return s
    prev, out = None, s
    for _ in range(5):
        if out == prev or "&" not in out:
            break
        prev, out = out, html.unescape(out)
    return out
