# 🌍 Agent géospatial Géoportail (IGN) × QGIS

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> **Une interface conversationnelle qui pilote les données de la Géoplateforme IGN et QGIS en langage naturel.**

Saisissez vos demandes dans une boîte de dialogue web (Flask), et un agent **LangGraph** orchestre **deux serveurs MCP** pour :

1. 📥 **Télécharger** la donnée de référence française depuis la **Géoplateforme IGN** — serveur MCP [geocontext](https://github.com/ignfab/geocontext) *(géocodage, altitude, cadastre, urbanisme, requêtes WFS)*
2. 🗺️ **Manipuler** cette donnée dans **QGIS** — serveur MCP [nkarasiak/qgis-mcp](https://github.com/nkarasiak/qgis-mcp) *(couches, styles, algorithmes de traitement, rendu)*

---

### 📐 Architecture

```
Flask (app.py) ──▶ Agent LangGraph (agent.py) ──┬─▶ geoportail  (HTTP IGN : geollm.beta.ign.fr/geocontext/mcp)
   chat web          create_react_agent + LLM    └─▶ qgis        (qgis-mcp-server ─▶ QGIS:9876)
```

---

## 📋 Prérequis

| Outil | Version | Pourquoi |
|---|---|---|
| 🐍 **Python** | ≥ 3.10 | Exécution de l'application |
| 📦 **uv / uvx** | Récent | Gestion de l'env Python et lancement du serveur `qgis-mcp` |
| 🌐 **QGIS Desktop** | 3.28 – 4.x | Cible de la manipulation cartographique |
| 🔌 Plugin **QGIS MCP** | — | Expose QGIS en MCP (socket TCP `localhost:9876`) |
| 🔑 **Clé LLM** | — | `OPENROUTER_API_KEY` (défaut) ou `ANTHROPIC_API_KEY` (repli) |

> 💡 Le serveur **Géoportail** utilise l'**instance HTTP hébergée par l'IGN** (`https://geollm.beta.ign.fr/geocontext/mcp`) — **aucun Node/npm requis**. Pour un fonctionnement 100 % local, repassez au transport `stdio` (`npx @ignfab/geocontext`, Node ≥ 22) dans [`mcp_servers.py`](mcp_servers.py).

> ⚠️ Vérifiez votre environnement : `python3 --version` et `uvx --version`.

---

## 🚀 Installation

### 1️⃣ Dépendances Python

```bash
uv sync
```

### 2️⃣ Serveur MCP QGIS

Installé une fois comme outil persistant — évite que `uvx` ne re-résolve les dépendances réseau à chaque démarrage. L'application détecte et lance ce binaire automatiquement (sinon repli sur `uvx`).

```bash
uv tool install "git+https://github.com/nkarasiak/qgis-mcp@599de023a60f6ff0d477d8b75806259a29d7e88c"
```

### 3️⃣ Variables d'environnement

```bash
cp .env.example .env
```

Renseignez ensuite `OPENROUTER_API_KEY` (et optionnellement `OPENROUTER_MODEL`) — voir la section [🤖 Fournisseur LLM](#-fournisseur-llm) ci-dessous.

---

## 🤖 Fournisseur LLM

Le fournisseur est choisi par la variable `LLM_PROVIDER`. S'il n'est pas défini, l'agent **auto-détecte** le premier fournisseur configuré (clé présente). Toute la logique est dans [`llm.py`](llm.py) — un **registre de fournisseurs** facilement extensible.

| `LLM_PROVIDER` | Type | Variables principales |
|---|---|---|
| `openrouter` *(défaut)* | OpenAI-compatible | `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL` |
| `anthropic` | API native | `ANTHROPIC_API_KEY`, `LLM_MODEL` |
| `openai` | API native | `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL` |
| `github_copilot` | proxy local `copilot-api` | `COPILOT_BASE_URL`, `COPILOT_API_KEY`, `COPILOT_MODEL` |
| `custom` | **tout endpoint OpenAI-compatible** (opencode, vLLM, Ollama…) | `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL_NAME` |

> ⚠️ Choisissez un modèle **fort en tool calling** — l'agent expose ~61 outils. Voir [`.env.example`](.env.example) pour toutes les variables.

**Changer de fournisseur** : il suffit de définir `LLM_PROVIDER` (+ ses variables) dans `.env`, puis relancer l'app. Exemples :

```bash
LLM_PROVIDER=anthropic              # API Claude native
LLM_PROVIDER=github_copilot         # via le proxy local copilot-api
LLM_PROVIDER=custom                 # n'importe quel endpoint OpenAI-compatible
```

**Ajouter un fournisseur** : pour un endpoint OpenAI-compatible, le mode `custom` suffit (zéro code). Sinon, ajouter un `register(Provider(...))` dans [`llm.py`](llm.py).

---

## 🗺️ Configuration QGIS (à faire une fois)

1. Ouvrez **QGIS**.
2. Allez dans **Extensions ▸ Installer/Gérer les extensions** → cherchez **« QGIS MCP »** → installez.
3. Dans le dock du plugin, cliquez sur **« Start Server »** (écoute sur `localhost:9876`).

> 🔔 QGIS doit rester ouvert pendant toute l'utilisation de l'application.

---

## ▶️ Lancement

```bash
uv run python app.py
```

Ouvrez ensuite **<http://127.0.0.1:5000>** dans votre navigateur.

Au premier message, les serveurs MCP sont initialisés : **Géoportail** est joint en HTTP (instance IGN) et **`qgis-mcp-server`** (installé à l'étape 2) est lancé localement, sans accès réseau.

---

## 💬 Exemples de prompts

> 🏠 « Géocode l'adresse *1 rue de la République, Lyon*, télécharge les parcelles cadastrales dans un rayon de 200 m, charge-les dans QGIS, applique un style de contour rouge et fais un rendu. »

> ⛰️ « Quelle est l'altitude au point lat 45.76, lon 4.83 ? »

> 🏗️ « Liste les couches WFS disponibles contenant "bati", puis charge le bâti de la commune de Villeurbanne dans QGIS. »

---

## 📁 Structure du projet

| Fichier | Rôle |
|---|---|
| 🖥️ `app.py` | Serveur Flask (chat + streaming + routes conversations) + boucle asyncio dédiée |
| 💬 `conversations.py` | Persistance des conversations sur disque (messages + fichiers par conversation) |
| 🌐 `templates/index.html` | UI web : panneau latéral (historique + fichiers), chat, arrêt, thème clair/sombre |
| 🎨 `static/` | Fonds carto IGN : `mode_clair.jpg` et `mode_sombre.jpg` |
| 🤖 `agent.py` | Construction du `MultiServerMCPClient` et de l'agent LangGraph (LLM) |
| 🔌 `mcp_servers.py` | Configuration des 2 serveurs MCP (Géoportail HTTP IGN, QGIS stdio) |
| 📝 `prompts.py` | System prompt (workflow IGN → QGIS, CRS, bonnes pratiques) |
| 📂 `data/conversations/<id>/` | Une conversation = `conversation.json` + fichiers téléchargés/produits |

---

## ⚖️ Licences

Le code de `demo_gt` est sous licence **MIT**.

Le serveur `qgis-mcp` (GPL v2+) est **exécuté** via `uvx --from git+…` et **non embarqué** dans ce dépôt ; les deux projets restent donc découplés. `geocontext` est sous licence MIT.

---

## 🔧 Dépannage

| Problème | Solution |
|---|---|
| 🚫 **Un outil QGIS échoue / timeout** | QGIS n'est pas ouvert ou le serveur du plugin n'est pas démarré → cliquez sur **« Start Server »**. |
| 🌐 **`uvx` : « Git operation failed » au démarrage** | Échec réseau transitoire (proxy) pendant le clone. Le commit est épinglé dans [`mcp_servers.py`](mcp_servers.py) et mis en cache → relancer suffit en général. |
| 📦 **`uvx` introuvable** | Installez `uv` : <https://astral.sh/uv> |
| 🛰️ **Géoportail (HTTP IGN) injoignable** | Service beta `geollm.beta.ign.fr` — vérifiez l'accès réseau/proxy, réessayez plus tard. |
