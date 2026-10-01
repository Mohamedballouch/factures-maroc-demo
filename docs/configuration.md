# Configuration - Ubuntu dans Windows, puis choix de l’extraction

## 1. Ouvrir Ubuntu et récupérer le projet

Les commandes suivantes s’exécutent dans Ubuntu WSL, comme pour PDO. L’application de factures est un serveur distinct, sur le port **5180**.

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
```

Cloner le [dépôt public de démonstration](https://github.com/Mohamedballouch/factures-maroc-demo), puis se placer dans le dossier cloné. Depuis une copie déjà disponible, se placer directement dans `factures-maroc-demo`.

```bash
cd ~
git clone https://github.com/Mohamedballouch/factures-maroc-demo.git
cd ~/factures-maroc-demo
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

La commande `cp` s’utilise pour la première configuration. Si `.env` existe déjà, conserver ses valeurs et le modifier directement.

## 2. Démarrer une première démonstration sans clé

Dans `.env` :

```dotenv
INVOICE_PROVIDER=demo
INVOICE_DATA_DIR=./data
```

Lancer le serveur depuis la racine du projet :

```bash
python -m uvicorn backend.app:app --host 127.0.0.1 --port 5180
```

Ouvrir **http://localhost:5180** dans le navigateur Windows. Garder le terminal ouvert pendant la démonstration. Pour arrêter, utiliser `Ctrl+C`. Les données sont conservées dans le dossier local configuré.

Le mode `demo` n’appelle aucun LLM, ne demande aucune clé et reconnaît les trois documents de `examples/`. Un document quelconque n’est pas extrait dans ce mode. Le bouton de démonstration charge les mêmes exemples de manière idempotente.

## 3. Activer une extraction réelle avec l’API Anthropic

Créer une clé sur la [console Anthropic](https://platform.claude.com/) avec un accès API et un modèle disponible pour son compte. La placer uniquement dans le fichier `.env` local du serveur :

```dotenv
INVOICE_PROVIDER=anthropic
ANTHROPIC_API_KEY=remplacer_par_la_cle_locale
ANTHROPIC_MODEL=claude-sonnet-5-5
INVOICE_DATA_DIR=./data
```

La valeur `ANTHROPIC_MODEL` correspond au modèle par défaut de ce projet. Si le compte n’y a pas accès, sélectionner un identifiant de modèle compatible avec les documents et les sorties structurées, disponible sur ce compte. Redémarrer le serveur après modification de `.env`.

Le backend transmet le document à l’API afin d’obtenir les champs prévus par le schéma d’extraction. Anthropic documente les [sorties JSON structurées](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), ainsi que la [prise en charge des PDF](https://platform.claude.com/docs/en/build-with-claude/pdf-support). Un schéma conforme facilite le traitement du résultat ; il ne garantit pas que chaque valeur a été correctement lue.

La clé n’est jamais à saisir dans le navigateur ou dans une issue GitHub. Les données du fichier importé sont envoyées au fournisseur API dans ce mode. Tester d’abord avec les exemples fictifs ou une nouvelle facture de démonstration.

### Claude Code et l’API Claude : deux usages

**Claude Code** est un outil de développement qui peut écrire, tester et modifier le projet, notamment lorsqu’il est orchestré par PDO. **L’API Anthropic** est appelée par cette application lorsqu’une personne importe une facture. L’installation et la connexion de Claude Code ne configurent pas automatiquement `ANTHROPIC_API_KEY` pour le backend. L’application peut tourner sans Claude Code installé.

## 4. Utiliser un modèle local avec Ollama

Installer Ollama selon ses [instructions officielles pour Linux](https://docs.ollama.com/linux), puis charger un modèle qui accepte les images. Le serveur Ollama doit fonctionner et le modèle choisi doit être téléchargé avant les imports.

La documentation [Vision Ollama](https://docs.ollama.com/capabilities/vision) décrit le passage d’images aux modèles compatibles. Ce projet utilise aussi un schéma pour les [sorties structurées Ollama](https://docs.ollama.com/capabilities/structured-outputs).

Exemple dans `.env` :

```dotenv
INVOICE_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=remplacer_par_un_modele_vision_installe
INVOICE_DATA_DIR=./data
```

Utiliser l’identifiant exact affiché par `ollama list`. Un modèle de texte seul ne suffit pas pour extraire les informations d’une photo ou d’une page rasterisée. Avec Ollama, le backend transforme chaque page PDF en image avant l’appel ; avec Anthropic, il transmet le PDF comme document. La qualité et le temps de traitement dépendent du modèle et de la machine. Redémarrer ensuite l’application.

Avec Ollama dans la **même instance Ubuntu**, `http://localhost:11434` est le point de départ. Avec Ollama installé **sur Windows**, vérifier l’adresse réellement accessible depuis WSL : `localhost` peut fonctionner selon la configuration réseau WSL, sinon `OLLAMA_BASE_URL` doit viser l’hôte Windows joignable. Ne pas supposer qu’un serveur accessible dans le navigateur Windows est automatiquement accessible depuis Ubuntu.

Pour vérifier l’API Ollama depuis Ubuntu :

```bash
curl http://localhost:11434/api/tags
```

Adapter l’adresse à celle configurée dans `OLLAMA_BASE_URL`. Cet appel doit retourner la liste des modèles. Il confirme la connexion, pas la qualité d’extraction.

## 5. Vérifier la configuration de l’application

```bash
curl http://localhost:5180/api/health
curl http://localhost:5180/api/config
```

`/api/health` vérifie que l’application répond. `/api/config` indique le fournisseur, le modèle et l’état de configuration sans afficher de clé. Une configuration déclarée prête ne remplace pas un import réussi : le modèle distant peut encore être indisponible ou la clé refusée par son fournisseur.

Les documents acceptés sont **PDF, PNG et JPEG**, jusqu’à **10 MiB**. Les PDF sont limités à **10 pages** dans cette application. Utiliser de préférence un scan lisible, cadré et sans mot de passe.

## Variables de configuration

| Variable | Utilité | Exemple |
|---|---|---|
| `INVOICE_PROVIDER` | Choix de l’extraction | `demo`, `anthropic` ou `ollama` |
| `ANTHROPIC_API_KEY` | Secret de l’API Anthropic | Valeur locale dans `.env` |
| `ANTHROPIC_MODEL` | Modèle Anthropic | `claude-sonnet-5-5` |
| `OLLAMA_BASE_URL` | Adresse de l’API locale | `http://localhost:11434` |
| `OLLAMA_MODEL` | Modèle vision téléchargé | Identifiant obtenu avec `ollama list` |
| `INVOICE_DATA_DIR` | Dossier des données et documents | `./data` |

## GitHub, PDO et cette application

Une authentification GitHub sert à cloner un dépôt privé, créer des issues ou publier des modifications. Le fonctionnement quotidien de Factures Maroc ne demande aucun jeton GitHub. Pour l’atelier, le dépôt public peut être cloné en lecture sans connexion GitHub.

Pour faire évoluer l’application avec PDO, approuver le dépôt local dans PDO, choisir une issue et lancer un pipeline de développement. Les accès de l’agent de développement et ceux du LLM d’extraction sont configurés séparément. Voir [l’issue proposée](issue-mvp.md) et [l’architecture](architecture.md).

## En cas de problème

| Symptôme | Vérification utile |
|---|---|
| Le navigateur ne répond pas | Vérifier que le serveur est lancé dans Ubuntu et que l’URL utilise bien le port 5180. |
| Le port 5180 est occupé | Arrêter l’instance déjà ouverte ou lancer avec `--port 5181` puis utiliser cette nouvelle URL. |
| Le mode Démo refuse un fichier | Importer un des fichiers originaux de `examples/` ; les autres documents demandent un fournisseur LLM. |
| Clé Anthropic manquante | Vérifier `INVOICE_PROVIDER`, la clé dans `.env` et le redémarrage du serveur. |
| Erreur de modèle Anthropic | Vérifier l’identifiant et l’accès API du compte. |
| Ollama ne répond pas | Vérifier le service, son adresse vue depuis WSL et `/api/tags`. |
| Facture reconnue comme doublon | Ouvrir la facture existante ; le même fichier ne doit pas créer une seconde ligne. |
| Validation refusée | Corriger les champs indiqués en les comparant au document, notamment HT + taxes = TTC. |

## Limites du prototype

Cette version est conçue pour une démonstration locale avec données fictives. Elle n’inclut pas d’authentification d’équipe, de rôles, de connexion bancaire ou ERP, ni de certification comptable. Le suivi « payé » est une information saisie dans l’application. La validation humaine et la conservation du document restent nécessaires pour le parcours présenté.
