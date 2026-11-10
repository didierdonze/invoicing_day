"""Local run report (French, Markdown) from figures.json — deterministic, conclusion first."""
from .page import KIND_LABEL, STATUS, hrs, money, title

LEVEL_FR = {"red": "🔴", "yellow": "🟡", "info": "ℹ️"}


def build_report(fig, page_url=None, carried=0):
    s = fig["summary"]
    ti = s.get("to_invoice") or {}
    total = " · ".join(money(d.get("total"), c) for c, d in sorted(ti.items())) or "rien"
    lines = [f"# {title(fig)} — rapport", ""]
    lines.append(f"**{s['red']} projet(s) à corriger, {s['yellow']} à vérifier, {s['green']} prêt(s) ; "
                 f"à facturer : {total} HT.**" + (f" Page : {page_url}" if page_url else ""))
    lines.append("")
    lines.append(f"Données Odoo lues le {fig['today']} à {fig['generated_at'][11:16]} · mois facturé : "
                 f"{fig['month_label']} · période des factures : {fig['invoice_defaults']['period']}.")
    if carried:
        lines.append(f"Commentaires repris de l'édition précédente : {carried}.")
    skipped = fig["meta"].get("skipped") or []
    if skipped:
        lines += ["", "## Non contrôlé", ""] + [f"- {x}" for x in skipped]
    for st in ("red", "yellow"):
        rows = [r for r in fig["rows"] if r["status"] == st]
        if not rows:
            continue
        lines += ["", f"## {STATUS[st][1]} ({len(rows)})", ""]
        for r in rows:
            lines.append(f"### {r['project']} — {r.get('client') or ''}")
            for f in r["flags"]:
                if f["level"] != "info":
                    lines.append(f"- {LEVEL_FR[f['level']]} `{f['code']}` {f['msg']}")
            lines.append("")
    green = [r for r in fig["rows"] if r["status"] == "green"]
    if green:
        lines += ["", f"## Prêts ({len(green)})", ""]
        for r in green:
            amt = " · ".join(money(v, c) for c, v in sorted(r["to_invoice"].items())) or "—"
            lines.append(f"- {r['project']} : {amt}")
    lines += ["", "## Proposition détaillée", "",
              "| Projet | SO | Poste | Type | Heures | Montant HT | Référence client |", "|---|---|---|---|---|---|---|"]
    for r in fig["rows"]:
        for it in r["proposal"]:
            lines.append(f"| {r['project']} | {it['so']} | {it['line']} | {KIND_LABEL[it['kind']]} | "
                         f"{hrs(it['hours']) if it['hours'] is not None else '—'} | {money(it['amount'], it['currency'])} | "
                         f"{it['customer_reference']} |")
    gc = (fig.get("team") or {}).get("garbage_collectors")
    if gc and gc["count"]:
        lines += ["", f"## Équipe — 01 Garbage Collectors : {gc['count']} ligne(s), {hrs(gc['hours'])}", ""]
        lines += [f"- {l['date']} {l['employee']} {l['jira'] or ''} {hrs(l['hours'])} — {l['link']}" for l in gc["lines"]]
    return "\n".join(lines) + "\n"
