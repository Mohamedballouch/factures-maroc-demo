# Contexte de Factures Maroc

Une equipe administrative de l'agence Maroc souhaite centraliser les factures recues sous forme de PDF, photo ou scan. Le responsable doit pouvoir retrouver une facture, verifier ce que l'IA a lu, corriger les champs, puis suivre les factures a payer et celles dont le paiement a ete renseigne.

Le parcours est importer → extraire → relire → valider → suivre. L'extraction du LLM propose fournisseur, ICE s'il figure dans la source, reference, dates, devise, HT, taxe, TTC, categorie et description. Une proposition de categorie enrichit la fiche sans constituer une preuve comptable. Les fournisseurs sont normalises dans une table dediee apres validation humaine. Les valeurs manquantes restent absentes.

Le premier produit est volontairement local et mono-utilisateur. Il ne realise pas de paiement et ne se connecte pas a une banque, un ERP ou un fournisseur externe. Le statut paye signifie seulement qu'une personne a renseigne ce suivi. Les factures d'exemple et leurs societes sont fictives, les montants et taxes servent a illustrer les controles, sans affirmer un taux reglementaire.

Le backend enregistre des brouillons SQLite et les documents sur disque. La validation controle les champs requis et l'egalite HT + taxe = TTC. Une correction significative d'une facture validee demande une nouvelle validation. Une facture payee reste en lecture seule dans ce prototype. Les totaux du tableau de bord additionnent uniquement MAD; d'autres devises restent distinctes.

Ces fichiers de contexte ont ete rediges pour la demo. Leur presence ne prouve pas l'execution d'un skill PDSF. PDO peut lire ces regles lors d'une implementation dans son worktree isole.
