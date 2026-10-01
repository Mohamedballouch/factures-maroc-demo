# Rejouer une demande avec PDO

Le produit de depart peut etre utilise sans PDO. Le pipeline `factures-maroc` sert a implementer une evolution sur son clone Git local : comprendre le ticket → developper → verifier → resumer pour le responsable. Une revue en echec retourne au developpement, avec trois passages au maximum.

Dans Ubuntu, avec le meme utilisateur que le daemon :

```bash
cd ~/factures-maroc-demo
mkdir -p ~/.pdo/pipelines
cp pdo/factures-maroc.yaml ~/.pdo/pipelines/
cp -r pdo/factures-maroc.prompts ~/.pdo/pipelines/
pdo daemon
```

Si le daemon tourne deja sur le port 5172, conserver cette instance. Dans l'interface http://localhost:5172 : ouvrir Pipelines, choisir `factures-maroc`, puis Runs → New Run. Choisir le chemin local `/home/mohamed_ballouch/factures-maroc-demo`, la branche `develop`, l'agent Claude Code configure, le pipeline et l'URL de l'issue voulue dans le prompt. Le chemin du clone definit le depot; le lien du ticket guide la lecture du besoin.

Apres lancement, relever l'ID du run. Pour chaque noeud ouvrir les entrees, sorties et terminal; lire le verdict et les commandes de verification. Examiner les changements dans Diff et l'application avant de demander une revue de PR. Ce pipeline ne pousse pas le code et ne cree pas automatiquement une PR.

PDSF peut aider a clarifier le besoin et a installer des skills dans le depot; PDO execute ce pipeline. Les fichiers AGENTS.md et CONTEXT.md de ce prototype ont ete rediges pour la demo : ils ne constituent pas la preuve d'une execution de `/build-factory`.

Une evolution de demonstration est prevue pour afficher l'historique de correction et validation d'une facture a partir des evenements deja conserves en SQLite. L'issue et les preuves du run seront references apres preparation.
