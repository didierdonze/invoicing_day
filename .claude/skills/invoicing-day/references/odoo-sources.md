# Sources Odoo et Jira — relevé du 2026-11-10 (Odoo 17.0+e, lecture seule)

## Projets du département
- `x_bi_sql_view.c2c_project_list` : `x_department_id = 23` (« 3 - Business Solutions / 3.1 - Grammont »),
  `x_active = True` → 39 projets, tous en CHF. `x_id` = `project.project`.
- `project.project.jira_key` : clé Jira du projet (vide pour les projets Odoo seulement).

## Odoo › Dashboards › Invoicing Dashboards (domaines relus à chaque run)
| Action | Nom | Modèle | Domaine (2026-11-10) |
|---|---|---|---|
| 4417 | 01 - Garbage Collectors | account.analytic.line | `project_id.name ilike "to dispatch"` — filtré sur les employés du département |
| 4100 | 01 - My leads => should be empty | crm.lead | utilise `uid` |
| 4101 | 01 - My opportunities to clean | crm.lead | utilise `uid`, `context_today()` |
| 4419 | 02 - Projects not linked with Jira | project.project | `jira_bind_ids = False, active, allow_timesheets` |
| 4420 | 03 - Tasks not linked to a SO line | project.task | `sale_line_id = False, project_id.analytic_plan_id = 1, active` |
| 4418 | 04 - TS lines without tasks | account.analytic.line | `task_id = False, account_plan_id in [1,2], timesheet_invoice_id = False, project actif` |

Dashboard tableur du groupe « Invoicing day » : « SO with negative remaining amounts » (id 51) → vue
`x_bi_sql_view.c2c_so_remaining_amount` (`x_remaining_amount_invoiced`, `x_remaining_amount_delivered`).

## Lignes de timesheet (`account.analytic.line`)
- Filtre *To invoice* de la vue de recherche : `timesheet_invoice_id = False`.
- `unit_amount_rounded` = base facturée (les write-offs manuels y sont) ; `unit_amount` = temps passé.
- `timesheet_invoice_type` : billable_time, billable_fixed, billable_milestones, billable_manual,
  non_billable, timesheet_revenues, service_revenues, other_revenues, other_costs.
- `jira_tempo_status` : approved, in_review, waiting_for_approval, ready_to_submit, open.
- `jira_issue_key` : carte Jira d'origine (connecteur Jira, `jira.account.analytic.line`).

## Postes de SO (`sale.order.line`)
- `qty_delivered_method` : timesheet, milestones, manual, analytic…; `product_id.invoice_policy` : order /
  delivery. timesheet + order = blocs prépayés, maintenance, forfaits ; timesheet + delivery = régie (T&M).
- Rôle du poste dans la référence interne du produit : `P_01-bs-ts_ba`, `ts_pm`, `ts_fsc`, `ts_pdir`
  (fonctionnels), `ts_dev`, `ts_arch` (techniques) ; `P_01-ts_project`, support, maintenance, voyage : sans rôle.
- Unités : beaucoup de postes en `Days (8h)`, d'autres en `Hours`, la maintenance annuelle en `Units`.
- Commande verrouillée : `sale.order.locked` (booléen ; Odoo 17 n'a plus d'état `done`, `state` ∈ draft, sent,
  sale, cancel). Relevé 2026-11-10 : ~3 770 h « To invoice » (sans facture liée) dorment sur des commandes
  verrouillées des projets Grammont, contre 5 h saisies en octobre 2026 → elles sont hors contrôles.
- Abonnements : `sale.order.is_subscription`, `next_invoice_date`, `subscription_state` (`3_progress`),
  `recurring_monthly`.

## Profils des employés (`hr.employee.job_id`) — À CONFIRMER par Didier
Fonctionnels : ICT Consultant, ICT Consultant (SC), ICT Application Manager, ICT Project manager.
Techniques : ICT Application Engineer, ICT Architect, ICT DevOps Engineer.
Non classés (aucun signal) : ICT Team leader, ICT Department Manager, OUT Subcontractor.

## Étapes 6–7
- Rapport d'heures joint : `ir.attachment` PDF sur la facture dont le nom contient
  rapport / heures / stunden / hours / timesheet / feuille.
- Étape 7 : **n'importe quelle activité ouverte** (`mail.activity`) sur la facture brouillon, quel que soit son type ;
  la page affiche à qui elle est assignée (règle de Didier, 2026-11-10). Une facture postée compte comme faite :
  Odoo supprime l'activité quand elle est marquée faite. Le How-to demande « Validate/Send Invoice »
  (`mail.activity.type` 5) assignée à Leila Muminovic (`res.users` 272) — non vérifié par le script.

## Jira (REST v3, lecture seule)
- Check Epic (How-to) : `timespent > 0 AND type NOT IN (Epic) AND updatedDate >= startOfMonth(-3M) AND parent = empty`,
  restreint aux clés des projets Grammont.
- Jira vs Odoo : `worklogDate` dans le mois, puis `/issue/{key}/worklog` filtré par `started` (Europe/Zurich),
  comparé aux lignes Odoo du mois par `jira_issue_key`. Tolérance 0.25 h.
- **Pas encore vérifié en réel** (pas de token au 2026-11-10) : la synchronisation Tempo → worklogs Jira.
