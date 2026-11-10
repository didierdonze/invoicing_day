---
name: invoicing-day
description: Prépare l'Invoicing Day mensuel du département Grammont (Camptocamp) — contrôles du « How to - Invoice your project » (dashboards Odoo 01–04, cartes Jira sans epic, heures à facturer par poste de SO, Jira vs Odoo, arrondis, blocs d'heures, SO en dépassement, impayés), proposition de facturation construite à partir des projets, et page Confluence « AAAA.MM - Invoicing Day Grammont » dans BS › Invoicing Day. Utiliser dès qu'il est question d'invoicing day, de facturation mensuelle, de préparer ou contrôler les factures du mois, de vérifier les timesheets avant facturation, ou de mettre à jour la page Invoicing Day.
allowed-tools:
  - Bash(python3 -m invoicing_day:*)
  - mcp__claude_ai_Atlassian__searchConfluenceUsingCql
  - mcp__claude_ai_Atlassian__getConfluencePage
  - mcp__claude_ai_Atlassian__getContentFormatGuide
  - mcp__claude_ai_Atlassian__createConfluencePage
  - mcp__claude_ai_Atlassian__updateConfluencePage
---

# Invoicing Day Grammont — contrôles, proposition, page du mois

Chaque mois, la comptabilité donne le feu vert et la date limite ; chaque chef de projet facture ses
projets selon BS › **How to - Invoice your project** (page `902594711`). Ce skill fait pour Didier la partie
contrôle et préparation sur **tous les projets actifs du département Grammont**, puis crée ou met à jour la page
du mois. **La création des factures reste manuelle** : l'outil est en lecture seule sur Odoo et Jira.

Règle de Didier : **toujours partir du projet, jamais directement du SO** (risque d'oublier des heures). Le
script le fait : la proposition part des lignes *To invoice* de chaque projet, groupées par poste de SO.

| Repère | Valeur |
|---|---|
| Dépôt / dossier de travail | `~/nobackup/invoicing_day` — toutes les commandes se lancent **depuis la racine du dépôt** |
| Mois facturé | par défaut le mois civil précédent (facturation de novembre → `2026-10`) |
| Dossier du run | `runs/AAAA-MM/` (jamais commité : données clients) |
| Site / espace / dossier parent | `camptocamp.atlassian.net` / `BS` / dossier « Invoicing Day » `1747615753` |
| Titre | `AAAA.MM - Invoicing Day Grammont` (AAAA.MM = mois facturé) |
| Format de la page | `references/page-format.md` · sources Odoo : `references/odoo-sources.md` |

## 0. Préalables

- **VPN Camptocamp** : Odoo n'est joignable que par le VPN. Dans une session cloud (claude.ai/code), Odoo est
  injoignable : le dire et s'arrêter — on peut y modifier le code et lancer les tests, pas un run.
- Jira : `~/.config/invoicing_day/jira.env` (voir `config/jira.env.example`). Sans ce fichier, les contrôles
  Jira sont **sautés et signalés** sur la page et dans le rapport — ne jamais les présenter comme passés.

## 1. Mode

- **Interactif** (Didier lance le skill) : confirmer le mois facturé. Pas d'autre question avant le run. La page
  du mois est une **live doc** (décision de Didier, 2026-11-10) : visible par l'équipe dès sa création, sans
  brouillon. Pour relire avant que l'équipe la voie : l'essai à blanc.
- **Essai à blanc** (la consigne contient « dry-run ») : tout se déroule, mais on s'arrête après l'étape 4 avec
  `runs/AAAA-MM/body.html` ; rien n'est écrit dans Confluence.

## 2. Chiffres

```
python3 -m invoicing_day run --month AAAA-MM --out runs/AAAA-MM/figures.json
```

Codes de sortie : 3 = Odoo injoignable (VPN ?) · 4 = appel refusé par Odoo · 5 = configuration manquante →
s'arrêter et le dire. **Ne jamais calculer un chiffre soi-même** : tout vient de `figures.json`.
Les **commandes verrouillées** (`locked`) sont hors proposition et hors contrôles de SO (décision de Didier,
2026-11-10) : seules leurs heures du mois sont signalées (info `LOCKED_SO_HOURS`, sous Details). Les impayés et
les factures du cycle couvrent toujours toutes les commandes. Un run
précédent du même mois est conservé automatiquement dans `figures.prev.json`.

## 3. La page du mois existe-t-elle ?

1. `runs/AAAA-MM/page.json` présent → la page a été créée par un run précédent (il retrouve aussi un ancien
   brouillon de page classique, que la recherche Confluence ne trouve pas).
2. Sinon `searchConfluenceUsingCql` :
   `ancestor = 1747615753 AND type = page AND title = "AAAA.MM - Invoicing Day Grammont"`.

**Elle existe → mise à jour** (c'est le cas normal : contrôler, corriger dans Odoo/Jira, relancer) :
- montrer ce qui a changé : `python3 -m invoicing_day diff --old runs/AAAA-MM/figures.prev.json --new runs/AAAA-MM/figures.json`
  (si `figures.prev.json` manque, le dire et résumer `report.md`) ;
- **demander l'accord** de Didier avant de mettre la page à jour ;
- `getConfluencePage` (`contentFormat: "html"`) sur la page, écrire son corps **tel quel** dans
  `runs/AAAA-MM/current.html`, puis
  `python3 -m invoicing_day page --figures runs/AAAA-MM/figures.json --previous runs/AAAA-MM/current.html --same-page --out runs/AAAA-MM/body.html` ;
- passer à l'étape 5 avec `updateConfluencePage` (même statut qu'avant ; une ancienne page classique en brouillon
  reste brouillon).

**Page « live doc »** (`subtype: "live"` dans la réponse de `getConfluencePage` ; toutes les pages depuis
octobre 2026 — mise à jour testée le 2026-11-10) : chaque frappe de l'équipe y est enregistrée aussitôt, et la mise à jour
remplace tout le corps. Donc :
- toujours `run` **avant** de lire la page (jamais l'inverse), et enchaîner lecture → `page` → écriture sans pause ;
- **juste avant** `updateConfluencePage`, relire la page et comparer son corps à `current.html` (`cmp`) : s'il a
  changé, réécrire `current.html` et relancer `page` avant d'écrire ;
- `status: "current"` (une live doc n'a pas de brouillon) ;
- l'API retire les `data-local-id` des commentaires recopiés : le texte reste identique, ce n'est pas une erreur.

**Elle n'existe pas → nouvelle édition** :
- édition précédente : `searchConfluenceUsingCql`
  `ancestor = 1747615753 AND type = page AND title ~ "Invoicing Day Grammont" ORDER BY created DESC`,
  prendre la plus récente dont le mois est **antérieur** ; `getConfluencePage` en `html`, écrire son corps tel
  quel dans `runs/AAAA-MM/previous.html` (aucune édition précédente : pas de `--previous`) ;
- `python3 -m invoicing_day page --figures runs/AAAA-MM/figures.json --previous runs/AAAA-MM/previous.html --out runs/AAAA-MM/body.html`.

La commande `page` recopie la colonne **Comments** projet par projet, **mot pour mot** ; c'est le travail de
Didier : ne jamais l'écrire ni la réécrire. Elle signale les commentaires de projets devenus inactifs (non
recopiés) : le dire dans la réponse.

## 4. Relire avant d'envoyer

Lire `runs/AAAA-MM/report.md` (écrit par `page`) : conclusion, projets à corriger, contrôles sautés.
**Ne jamais modifier `body.html` à la main** : une erreur se corrige dans Odoo/Jira ou dans le code, puis on
relance.

## 5. Créer ou mettre à jour

`getContentFormatGuide` (`toolName` = l'outil utilisé) une fois, puis :
- **création** : `createConfluencePage` — `cloudId: "camptocamp.atlassian.net"`, `spaceId: "BS"`,
  `parentId: "1747615753"`, `title`, `contentFormat: "html"`, `contentType: "page"`, **`subtype: "live"`**,
  `status: "current"`, `body` = le contenu de `body.html` **inchangé** ;
  aussitôt après, écrire `runs/AAAA-MM/page.json` : `{"id", "url", "status", "created_at"}` ;
- **mise à jour** : `updateConfluencePage` — `pageId`, `title` inchangé, `contentFormat: "html"`, même
  `status`, `versionMessage: "invoicing_day run <date>"`, `body` = `body.html` inchangé.

Si l'appel échoue ou reste muet, **ne pas le relancer** (risque de doublon) : le dire, Didier vérifie le
dossier Invoicing Day.

## 6. Vérifier sur la page réelle

Relire la page (`getConfluencePage`) : le nombre de lignes du tableau = projets non « idle » de `figures.json`
(+ ceux qui ont un commentaire), l'ordre rouge → jaune → vert, les montants et les statuts. Un écart se
signale, il ne se corrige pas à la main.

## 7. Rapports d'heures (étape 6 du How-to)

Pour les projets dont un brouillon de facture existe déjà (`progress.invoices`), proposer le rapport
d'heures client avec le skill **hours-report** (mode facture sur l'id du brouillon). Didier le joint
lui-même à la facture dans Odoo ; le run suivant le détecte et coche « 6 Report ».

## 8. Réponse finale

Trois lignes au plus : statut (rouges / jaunes / verts, montant à facturer), lien de la page, chemin de
`report.md`. Puis, s'il y en a, les contrôles sautés (Jira…) et les commentaires non recopiés.

## Interdits

Écrire dans Odoo ou Jira ; publier une page sans l'accord de Didier ; recalculer ou arrondir un chiffre ;
réécrire un commentaire ; modifier `body.html` ; relancer une création qui a échoué ; commiter `runs/`.
