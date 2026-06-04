# demo_gt — Agent géospatial Géoportail (IGN) × QGIS

Application à agent : vous tapez vos demandes en langage naturel dans une boîte
de dialogue web (Flask), et un agent LangGraph orchestre **deux serveurs
MCP** pour :

1. **Télécharger** la donnée de référence française depuis la **Géoplateforme
   IGN** — serveur MCP [geocontext](https://github.com/ignfab/geocontext)
   (géocodage, altitude, cadastre, urbanisme, requêtes WFS) ;
2. **Manipuler** cette donnée dans **QGIS** — serveur MCP
   [nkarasiak/qgis-mcp](https://github.com/nkarasiak/qgis-mcp) (couches, styles,
   algorithmes de traitement, rendu).

```
Flask (app.py) ──▶ Agent LangGraph (agent.py) ──┬─▶ geoportail  (HTTP IGN : geollm.beta.ign.fr/geocontext/mcp)
   chat web          create_react_agent + LLM    └─▶ qgis        (qgis-mcp-server ─▶ QGIS:9876)
```

## Prérequis

| Outil | Version | Pourquoi |
|---|---|---|
| **Python** | ≥ 3.10 | l'application |
| **uv / uvx** | récent | gère l'env Python et lance le serveur `qgis-mcp` |
| **QGIS Desktop** | 3.28 – 4.x | cible de la manipulation |
| Plugin **QGIS MCP** | — | expose QGIS en MCP (socket TCP `localhost:9876`) |
| **Clé LLM** | — | `OPENROUTER_API_KEY` (par défaut) ou `ANTHROPIC_API_KEY` (repli) |

> Le serveur **Géoportail** utilise l'**instance HTTP hébergée par l'IGN**
> (`https://geollm.beta.ign.fr/geocontext/mcp`) — **aucun Node/npm requis**. Pour
> un fonctionnement 100 % local, on peut repasser au transport `stdio`
> (`npx @ignfab/geocontext`, Node ≥ 22) dans [mcp_servers.py](mcp_servers.py).
>
> ⚠️ Vérifiez : `python3 --version`, `uvx --version`.

## Installation

```bash
# 1. Dépendances Python
uv sync

# 2. Serveur MCP QGIS — installé une fois comme outil persistant.
#    Évite que uvx re-résolve les dépendances (réseau) à chaque démarrage ;
#    l'app détecte et lance ce binaire automatiquement (sinon repli sur uvx).
uv tool install "git+https://github.com/nkarasiak/qgis-mcp@599de023a60f6ff0d477d8b75806259a29d7e88c"

# 3. Variables d'environnement
cp .env.example .env
# puis renseignez OPENROUTER_API_KEY (et OPENROUTER_MODEL) — voir « Fournisseur LLM »
```

### Fournisseur LLM

L'agent détecte automatiquement le fournisseur :

- **OpenRouter (par défaut)** — utilisé dès que `OPENROUTER_API_KEY` est défini. Choisissez un
  modèle **fort en tool calling** via `OPENROUTER_MODEL` (l'agent expose ~61 outils) ; défaut
  `deepseek/deepseek-v4-pro`. Slugs sur [openrouter.ai/models](https://openrouter.ai/models).
  Nécessite des **crédits OpenRouter**.
- **Anthropic (repli)** — utilisé si aucune clé OpenRouter n'est présente ; clé `ANTHROPIC_API_KEY`,
  modèle via `LLM_MODEL` (défaut `claude-sonnet-4-6`). Nécessite des crédits API Anthropic.

Forçage explicite possible : `LLM_PROVIDER=openrouter` ou `LLM_PROVIDER=anthropic`.

### Côté QGIS (à faire une fois)

1. Ouvrez **QGIS**.
2. *Extensions ▸ Installer/Gérer les extensions* → cherchez **« QGIS MCP »** → installez.
3. Dans le dock du plugin, cliquez sur **« Start Server »** (écoute sur
   `localhost:9876`). QGIS doit rester ouvert pendant l'utilisation.

## Lancement

```bash
uv run python app.py
```

Ouvrez ensuite <http://127.0.0.1:5000> dans le navigateur. Au premier message,
les serveurs MCP sont initialisés : Géoportail est joint en HTTP (instance IGN) et
`qgis-mcp-server` (installé à l'étape 2) est lancé localement, sans accès réseau.

## Exemples de prompts

- « Géocode l'adresse *1 rue de la République, Lyon*, télécharge les parcelles
  cadastrales dans un rayon de 200 m, charge-les dans QGIS, applique un style de
  contour rouge et fais un rendu. »
- « Quelle est l'altitude au point lat 45.76, lon 4.83 ? »
- « Liste les couches WFS disponibles contenant "bati", puis charge le bâti de la
  commune de Villeurbanne dans QGIS. »

## Structure

| Fichier | Rôle |
|---|---|
| `app.py` | Serveur Flask (chat + streaming + routes conversations) + boucle asyncio dédiée |
| `conversations.py` | Persistance des conversations sur disque (messages + fichiers par conversation) |
| `templates/index.html` | UI web : panneau latéral (historique + fichiers), chat, arrêt, thème clair/sombre |
| `static/` | Fonds carto IGN : `mode_clair.jpg` (thème clair) et `mode_sombre.jpg` (thème sombre) |
| `agent.py` | Construit le `MultiServerMCPClient` et l'agent LangGraph (LLM) |
| `mcp_servers.py` | Config des 2 serveurs MCP (Géoportail HTTP IGN, QGIS stdio via uvx) |
| `prompts.py` | System prompt (workflow IGN → QGIS, CRS, bonnes pratiques) |
| `data/conversations/<id>/` | Une conversation = `conversation.json` (messages) + ses fichiers téléchargés/produits |

## Licences

Code de `demo_gt` : **MIT**. Le serveur `qgis-mcp` (GPL v2+) est **exécuté**
via `uvx --from git+…` et **non embarqué** dans ce dépôt ; les deux restent donc
découplés. `geocontext` est MIT.

## Dépannage

- **Un outil QGIS échoue / timeout** : QGIS n'est pas ouvert ou le serveur du
  plugin n'est pas démarré → cliquez sur « Start Server ».
- **`uvx` : « Git operation failed » au démarrage de qgis** : échec réseau
  transitoire (proxy) pendant le clone. Le commit est épinglé dans
  [mcp_servers.py](mcp_servers.py) et mis en cache → relancer suffit en général.
- **`uvx` introuvable** : installez `uv` (https://astral.sh/uv).
- **Géoportail (HTTP IGN) injoignable** : service beta `geollm.beta.ign.fr` en
  ligne ; vérifier l'accès réseau/proxy, réessayer plus tard.
  (certains en beta) ; réessayez plus tard.
