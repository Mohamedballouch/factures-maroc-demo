# Démonstration Factures Maroc - 6 minutes

## Ce que l’équipe va voir

Une assistante importe une facture PDF ou une photo. Le backend en extrait les informations, les propose à la relecture et les conserve dans une base locale. Le responsable peut retrouver une facture, vérifier le document, suivre sa validation et enregistrer qu’elle a été payée.

Le mode **Démo** utilise des extractions préparées pour les trois documents fictifs fournis. Il permet une présentation reproductible sans clé ni appel LLM. L’extraction de nouveaux documents par un LLM demande le mode **Anthropic** ou **Ollama** ; voir [configuration](configuration.md).

## Préparer la présentation

1. Démarrer l’application selon le [guide de configuration](configuration.md).
2. Ouvrir `http://localhost:5180` dans le navigateur Windows.
3. Vérifier que le mode affiché est **Démo**. Aucune facture réelle n’est nécessaire.
4. Repérer les trois fichiers dans `examples/`. Tous portent la mention **DEMONSTRATION DONNEES FICTIVES**.
5. Pour un premier passage, partir d’un dossier de données neuf. Pour rejouer sans toucher à l’historique existant, arrêter le serveur puis le relancer avec un autre dossier :

```bash
INVOICE_DATA_DIR=./data-atelier-2 python -m uvicorn backend.app:app --host 127.0.0.1 --port 5180
```

Ne pas charger les trois exemples avant de montrer l’import individuel : la détection des doublons retrouverait les documents déjà présents.

## Parcours à présenter

| Temps | Action à l’écran | Ce que l’on explique |
|---|---|---|
| 0:00-0:40 | Afficher le tableau de bord vide. | « Nous voulons retrouver les dépenses de l’agence sans ressaisir chaque facture. » |
| 0:40-1:40 | Importer `examples/atlas-services.pdf`, attendre l’extraction, ouvrir la relecture. | « L’application propose le fournisseur, le numéro, les dates et les montants. Nous gardons le document sous les yeux. » |
| 1:40-2:20 | Comparer les montants avec le PDF : HT **4 800,00**, taxes **960,00**, TTC **5 760,00 MAD**. Valider la facture. | « Une réponse bien structurée ne suffit pas : la personne vérifie le document, puis l’application contrôle les montants. » |
| 2:20-3:20 | Importer `examples/connexion-maroc.png`. Montrer l’échéance vide et son avertissement. | « La date absente reste vide. Le système n’invente pas une échéance. Elle est facultative. » |
| 3:20-4:00 | Compléter une note, par exemple « Échéance à confirmer auprès du fournisseur », enregistrer puis valider. | « Nous ajoutons notre contexte de gestion sans le présenter comme une donnée extraite du scan. » |
| 4:00-4:40 | Charger les exemples de démonstration pour ajouter Bureau Casa ; vérifier et valider Bureau Casa, puis montrer les filtres. | « Les trois factures totalisent **9 300,00 MAD**. L’import des exemples peut être relancé sans les dupliquer. » |
| 4:40-5:20 | Ouvrir Atlas Services validée, la marquer payée. | « Nous enregistrons un statut de suivi. Ce bouton ne réalise aucun virement. » |
| 5:20-6:00 | Exporter le CSV et revenir à la liste. | « Les données sont réutilisables pour un suivi. Ce prototype reste une application de démonstration locale. » |

Après validation des trois factures puis paiement d’Atlas Services seulement, le TTC recensé reste **9 300,00 MAD** et le montant à payer vaut **3 540,00 MAD**. Le TTC recensé inclut les factures à vérifier ; le montant à payer et les échéances dépassées concernent les factures validées et non réglées. Les filtres agissent sur la liste affichée, tandis que les indicateurs restent globaux. Au 1er octobre 2026, aucune de ces factures n’est en retard.

### Montrer une correction en direct

Pour une démonstration facultative de 30 secondes, ouvrir une facture encore à relire, remplacer volontairement son TTC par `5000`, puis tenter de la valider. L’application doit signaler que le total ne correspond pas à HT + taxes. Rétablir le TTC lu sur le document, enregistrer et valider. Présenter cette manipulation comme une erreur de saisie volontaire, pas comme le résultat réel de l’extraction.

### Montrer le vrai mode LLM

Dans une session séparée, configurer Anthropic ou Ollama, redémarrer le serveur et importer une nouvelle facture fictive. Le mode choisi s’applique aux imports individuels. Le bouton de chargement des exemples reste déterministe et ne teste pas le LLM. Comparer les champs avec le document ; ne pas promettre une extraction parfaite. Une clé absente, un modèle indisponible ou un document illisible doit produire une erreur visible, sans créer une facture inventée.

## Les appels derrière la démonstration

| Étape | Appel | Résultat attendu |
|---|---|---|
| Vérifier l’application | `GET /api/health` | `{"status":"ok"}` |
| Voir le mode actif | `GET /api/config` | Fournisseur, modèle et état de configuration, sans secret |
| Importer un document | `POST /api/invoices/upload` multipart, champ `file` | Facture `pending_review` |
| Charger les trois exemples | `POST /api/demo` | Import idempotent des documents fictifs |
| Retrouver une facture | `GET /api/invoices?search=Atlas&status=validated` | Liste filtrée et indicateurs globaux |
| Voir le document | `GET /api/invoices/{id}/document` | PDF ou image original |
| Enregistrer une correction | `PATCH /api/invoices/{id}` | Facture actualisée |
| Valider | `POST /api/invoices/{id}/approve` | Facture `validated`, fournisseur ajouté au référentiel |
| Suivre un paiement | `POST /api/invoices/{id}/payment` | Facture `paid` |
| Exporter | `GET /api/export.csv` | CSV UTF-8, séparateur point-virgule |

## Questions courantes pendant la présentation

**Le mode Démo lit-il vraiment les nouveaux scans ?** Non. Il reconnaît uniquement les trois fichiers fournis par leurs octets et restitue leurs données préparées. Un autre document est refusé dans ce mode.

**Peut-on utiliser une photo depuis un téléphone ?** L’import accepte PNG et JPEG et propose une entrée compatible avec la capture mobile. Un téléphone doit toutefois pouvoir joindre le serveur : `localhost` sur le téléphone désigne le téléphone lui-même. La configuration fournie sert à présenter l’application sur la machine locale.

**Que signifie enrichir la base ?** Créer la fiche facture avec ses champs, proposer une catégorie, conserver les éléments de preuve et, après validation humaine, créer ou actualiser le fournisseur. Aucune donnée externe ni recherche commerciale n’est ajoutée automatiquement.

**Le scan remplace-t-il la validation humaine ?** Non. La relecture permet de comparer la proposition avec le document. Les contrôles techniques vérifient les champs requis et l’arithmétique ; ils ne certifient pas l’authenticité d’une facture.

**Où interviennent PDO et PDSF ?** Ils peuvent structurer et orchestrer le travail de construction de ce projet depuis son issue GitHub. L’application livrée s’exécute ensuite avec son propre backend ; elle ne dépend pas d’un run PDO pour traiter chaque facture.
