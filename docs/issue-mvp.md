# MVP : importer et suivre les factures de l’agence Maroc

## Problème métier

L’équipe reçoit des factures par PDF, photo ou scan. Les informations sont ensuite recopiées dans un tableau, le document est stocké ailleurs et il devient difficile de savoir ce qui reste à relire ou à payer.

Nous voulons une petite application web française où l’assistante importe une facture, vérifie les informations proposées et retrouve ensuite le document avec son statut. Le responsable doit pouvoir consulter les dépenses de l’agence et exporter les données.

## Exemple à montrer au manager

Une facture fictive d’Atlas Services est importée. L’application propose **4 800,00 MAD HT**, **960,00 MAD de taxes** et **5 760,00 MAD TTC**, ainsi que le fournisseur, le numéro et les dates. L’assistante compare ces champs avec le PDF, valide la fiche et retrouve le fournisseur dans la liste. Le responsable enregistre ensuite que la facture a été payée.

Le bénéfice attendu est de réduire la ressaisie et de centraliser le suivi. Le MVP ne prétend pas mesurer un gain de productivité avant un essai avec l’équipe.

## Utilisateurs et parcours

### Assistante de l’agence

1. Importer un PDF ou une photo PNG/JPEG.
2. Voir le document et les informations extraites dans un panneau de relecture.
3. Comprendre les champs absents et les points à vérifier.
4. Corriger une valeur, compléter une note et enregistrer.
5. Valider lorsque les informations ont été contrôlées.

### Responsable

1. Consulter le nombre de factures, le TTC recensé en MAD et le montant des factures validées non payées.
2. Rechercher une facture par fournisseur ou numéro et filtrer par statut ou catégorie.
3. Ouvrir le document source.
4. Marquer une facture validée comme payée.
5. Exporter les données au format CSV.

## Périmètre du MVP

- Interface française responsive avec tableau de bord, recherche, filtres et détail de facture.
- Import de PDF, PNG ou JPEG, jusqu’à 10 MiB ; maximum 10 pages pour les PDF.
- Extraction backend de fournisseur, ICE si présent, numéro, dates, devise, HT, taxes, TTC et description.
- Proposition de catégorie éditable et éléments de preuve pour les champs essentiels.
- Champs absents conservés vides ; aucun taux ni délai de paiement déduit.
- Relecture humaine avant validation.
- Conservation locale de la fiche et du document dans SQLite et le dossier de données.
- Détection du même fichier pour éviter les doublons exacts.
- Référentiel fournisseur créé ou actualisé après validation.
- États « à relire », « validée » et « payée ».
- Export CSV ; aucune conversion automatique entre devises.
- Mode de démonstration sans clé et fournisseurs Anthropic/Ollama configurables côté serveur.

## Critères d’acceptation

- [ ] Sur une base neuve, importer `atlas-services.pdf` en mode Démo crée une facture à relire avec le TTC **5 760,00 MAD**.
- [ ] Le PDF original est visible pendant la relecture ; les champs peuvent être corrigés et sauvegardés.
- [ ] HT **4 800,00** + taxes **960,00** permet la validation de TTC **5 760,00** ; un TTC incohérent bloque la validation avec une explication lisible.
- [ ] L’échéance absente de `connexion-maroc.png` reste vide, avec un avertissement ; aucune date n’est inventée.
- [ ] Une facture ne peut être validée sans fournisseur, numéro, date, devise ou l’un des trois montants requis.
- [ ] Un second import du même fichier ne crée pas de doublon et indique la facture déjà existante.
- [ ] Le chargement des trois exemples peut être relancé sans doublons ; leur total vaut **9 300,00 MAD**.
- [ ] Le fournisseur apparaît dans le référentiel après approbation humaine.
- [ ] Une facture validée peut être marquée payée ; la même action répétée conserve un résultat cohérent.
- [ ] Après validation des trois exemples puis paiement d’Atlas Services seulement, le TTC recensé reste **9 300,00 MAD** et le montant à payer est **3 540,00 MAD**.
- [ ] Le TTC recensé inclut les factures à vérifier ; le montant à payer et les échéances dépassées portent uniquement sur les factures validées et non réglées.
- [ ] Une modification substantielle d’une facture validée impose une nouvelle relecture ; une facture payée ne peut pas être modifiée dans ce parcours.
- [ ] Les filtres modifient la liste sans masquer le fait que les indicateurs couvrent toutes les factures.
- [ ] Une facture dans une autre devise n’est pas ajoutée au total MAD.
- [ ] L’export produit un CSV exploitable avec un tableur et neutralise les valeurs pouvant être interprétées comme des formules.
- [ ] En mode Démo, un document inconnu est refusé explicitement ; aucune extraction fictive n’est fabriquée.
- [ ] Avec un fournisseur LLM configuré, l’import appelle ce fournisseur côté backend ; aucune clé ne circule dans l’interface.
- [ ] Une clé absente, un modèle inaccessible ou un fichier invalide produit un message utile et aucune facture inventée.

## Démonstration et données

Fournir trois documents entièrement fictifs : Atlas Services, Bureau Casa et Connexion Maroc. Chaque document doit indiquer **DEMONSTRATION DONNEES FICTIVES**. Les deux premiers sont complets ; le troisième n’indique pas d’échéance. Utiliser le [conducteur de six minutes](demo.md) pour présenter le besoin et le parcours.

## Configuration attendue

Le mode par défaut est `demo`, sans clé. Le serveur lit `.env` et accepte `INVOICE_PROVIDER=anthropic` avec `ANTHROPIC_API_KEY` et `ANTHROPIC_MODEL`, ou `INVOICE_PROVIDER=ollama` avec `OLLAMA_BASE_URL` et `OLLAMA_MODEL`. Documenter la mise en route sous Ubuntu WSL et le rôle distinct de Claude Code pour le développement. Voir [configuration](configuration.md).

## Découpage proposé pour un pipeline PDO

1. **Cadrage :** comprendre cette issue, confirmer les champs et le parcours de relecture.
2. **Backend :** implémenter import, fournisseurs d’extraction, données, contrôles et export.
3. **Interface :** rendre les actions visibles et simples, avec aperçu du document et messages d’erreur.
4. **Vérification :** tester les montants, champs absents, doublons, états, export et import de formats invalides.
5. **Revue :** inspecter le parcours dans le navigateur et vérifier que le mode Démo est annoncé honnêtement.

Les agents travaillent sur le dépôt approuvé ; une personne inspecte les changements et la PR avant toute intégration. L’application finale n’appelle pas PDO pour chaque facture.

## Hors du périmètre

Le MVP ne réalise pas de paiement bancaire, ne synchronise pas un ERP et ne certifie pas la conformité comptable. Il n’inclut pas encore de comptes d’équipe, de rôles, de traitement des avoirs ou de règles fiscales. Ces sujets peuvent faire l’objet d’issues suivantes après une première démonstration.
