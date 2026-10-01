# Afficher l historique des corrections et validations d une facture

## Besoin du responsable

Quand une facture change, le responsable de l'agence Maroc veut comprendre les corrections et les etapes franchies, sans ouvrir la base de donnees. Une chronologie lisible doit montrer l'importation, les champs corriges, la validation et le paiement renseigne.

Le prototype conserve deja ces evenements dans `invoice_events`. Cette evolution les rend visibles dans la fiche facture et expose une API en lecture seule. Il n'y a pas d'authentification dans le prototype : ne pas inventer un auteur ou un nom de collaborateur.

## Parcours attendu

1. Importer une facture fictive et ouvrir sa fiche.
2. Voir l'evenement Extraction, sa date et le mode utilise.
3. Corriger un champ puis enregistrer : une nouvelle ligne montre le champ, son ancienne valeur et sa nouvelle valeur.
4. Valider puis renseigner un paiement : la chronologie suit les deux changements de statut.
5. Fermer et rouvrir la fiche, puis redemarrer le serveur : l'historique demeure present et concerne uniquement cette facture.

## Criteres d acceptation

- [ ] Ajouter `GET /api/invoices/{id}/history`, en lecture seule. Retour : `{invoice_id, events:[{id,event_type,occurred_at,payload}]}`.
- [ ] Un identifiant inconnu retourne 404. Une facture connue sans evenement retourne une liste vide.
- [ ] Lire `invoice_events` existante, sans recreer un autre historique. Champs SQLite : `id`, `invoice_id`, `event_type`, `occurred_at`, `payload_json`. Types : extraction, correction, approval, payment. Ordre chronologique ascendant, stabilise par `id` en cas d'egalite.
- [ ] Une correction affiche `payload.changes[field].before` et `after` avec des labels metier francais. Une valeur absente s'affiche « Non renseigne ».
- [ ] Afficher une section « Historique de la facture » dans la fiche, avec date et heure a Casablanca, labels francais et indication explicite du mode demo pour les exemples.
- [ ] Rafraichir l'historique apres enregistrement, validation et paiement, sans recharger toute la page.
- [ ] Afficher les etats chargement, liste vide et erreur. Le panneau doit rester utilisable au clavier et sur mobile.
- [ ] Inserer les textes de factures et valeurs d'evenements comme texte, jamais comme HTML interprete.
- [ ] Tester l'isolation entre deux factures, l'ordre, les anciennes/nouvelles valeurs, les etapes extraction/validation/paiement, la persistance et le 404. Les tests ne doivent appeler aucun LLM externe.
- [ ] L'historique ne contient aucune cle API, aucune instruction de connexion et aucune identite supposee. « Paiement renseigne » signifie un suivi manuel, sans transaction bancaire.

## Hors perimetre

Connexion bancaire, authentification multi-utilisateur, modification/suppression d'evenements, export ERP, extraction reelle avec cle API. Cette issue concerne l'historique de faits deja enregistres.

## Schema des evenements deja enregistres

- extraction : `{provider, filename, warnings}`
- correction : `{changes:{field:{before,after}}}`
- approval : `{status_from,status_to,supplier_id}`
- payment : `{status_from,status_to}`

Lire AGENTS.md et CONTEXT.md avant modification. Conserver les fichiers uploades et la base dans `data/`, hors Git. Verification de base : `python -m pytest -q`.
