# Page « AAAA.MM - Invoicing Day Grammont » — format

Généré entièrement par `invoicing_day/page.py` depuis `figures.json` (format HTML du connecteur Atlassian :
panels, status lozenges, `<details>`, `data-background` sur les cellules). Rien n'est ajouté à la main.

1. **Panel info** : mois facturé, nombre de projets actifs, date et heure de lecture d'Odoo, lien vers le How-to.
2. **Panel warning** « Not checked in this run » si un contrôle a été sauté (Jira sans token, dashboard illisible).
3. **Résumé en 3 colonnes** : à facturer (total HT par devise, puis par type) · projets par statut ·
   impayés (total, dont en retard) + contrôles d'équipe (01 Garbage Collectors, leads / opportunités à nettoyer).
4. **Invoice fields (How-to steps 4–7)** : période YTD, date de facture, date comptable, référence de paiement
   vide, référence client `<SO> - <Mois> <Année>`, rapport d'heures, activité à Leila.
5. **« How to read this table »** juste sous « Projects » : sens des 4 statuts, puis un tableau des 5 étapes de la
   checklist (✅ = ce que le script vérifie, ⬜ = quoi faire, avec l'étape du How-to) et le rappel que les coches
   sont recalculées à chaque run (les remarques vont dans Comments). Source unique : `STEPS` dans `page.py`.
6. **Tableau Projects**, une ligne par projet non « idle » (ou ayant un commentaire), trié rouge → jaune → vert :
   Project (code en gras, client · PM) | Status | To invoice (total, puis une ligne par SO : montant, heures,
   types non T&M) | Checklist (✅/⬜ une étape par ligne : 1 Data clean · 2–3 Hours checked · 4–5 Draft invoice · 6 Hours report attached · 7 Admin notified, calculée ; sous « 1 Data clean » non coché, des lignes ↳ renvoient aux cartes Jira, tâches et lignes de timesheet à corriger ; « 7 » affiche à qui l'activité est assignée) |
   Unpaid & late | **Comments (de Didier, recopiés tels quels)**.
   Les projets « idle » (rien à facturer, rien à corriger) tiennent en une ligne sous le tableau.
7. **Details per project** : panel « How to fix » une fois, puis un `<details>` par projet ayant un signal :
   messages, exemples (5 au plus) et lien vers le dashboard Odoo concerné, factures du cycle.

## Statuts

| Statut | Lozenge | Fond | Quand |
|---|---|---|---|
| red | TO FIX | `#FFEBE6` | dashboards 03/04 (02 = projet sans lien Jira = Odoo seulement, info), carte Jira sans epic, écart Jira ≠ Odoo, bloc d'heures dépassé, SO facturé au-delà du montant vendu |
| yellow | TO CHECK | `#FFFAE6` | heures du mois sans poste de SO, profil fonctionnel/technique sur le mauvais poste, heures non liées à une facture mais rien à facturer sur le SO, Tempo non approuvé, facture en retard, bloc ≥ 90 %, SO livré au-delà du montant (à mettre à jour) |
| green | READY | `#E3FCEF` | quelque chose à facturer, aucun signal |
| idle | NOTHING | — | rien à facturer, aucun signal |

Les seuils sont dans `invoicing_day/rules.py` (surchargeables par variables `INVOICING_*`).

## Taille

Le corps doit passer en un seul appel `createConfluencePage` : ~50 k caractères pour 39 projets. Le détail
complet (chaque poste, chaque ligne) reste dans `report.md` et `figures.json`.
