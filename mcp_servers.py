"""Configuration des serveurs MCP utilisés par l'agent.

Deux serveurs sont lancés en sous-processus via le transport ``stdio`` :

- ``geoportail`` : serveur geocontext de l'IGN (Node, via ``npx``). Donne accès
  aux services de la Géoplateforme (géocodage, altitude, cadastre, urbanisme,
  requêtes WFS).
- ``qgis`` : serveur qgis-mcp (Python, via ``uvx``). Pilote une instance QGIS
  Desktop ouverte, dont le plugin « QGIS MCP » écoute en local (TCP 9876).

Le dictionnaire ``SERVERS`` est consommé tel quel par
``langchain_mcp_adapters.client.MultiServerMCPClient``.
"""

from __future__ import annotations

import os
import shutil

from config import QGIS_MCP_REF, GEOPORTAIL_URL

def _qgis_command() -> tuple[str, list[str]]:
    """Détermine comment lancer le serveur MCP QGIS.

    On privilégie le binaire **déjà installé** (`uv tool install
    git+https://github.com/nkarasiak/qgis-mcp@<ref>`) : son lancement ne
    nécessite **aucun accès réseau**, ce qui évite les échecs transitoires du
    proxy IGN (uvx re-résout sinon les dépendances depuis PyPI à chaque
    démarrage). Repli sur `uvx` si le binaire n'est pas trouvé.
    """
    candidates = [
        shutil.which("qgis-mcp-server"),
        os.path.expanduser("~/.local/bin/qgis-mcp-server"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path, []
    return "uvx", [
        "--from",
        f"git+https://github.com/nkarasiak/qgis-mcp@{QGIS_MCP_REF}",
        "qgis-mcp-server",
    ]


def get_mcp_servers_config() -> dict[str, dict]:
    """Retourne la configuration des serveurs MCP formatée pour MultiServerMCPClient.

    On calcule les chemins (ex: `_qgis_command`) au moment de l'appel, et non
    à l'import du module, pour plus de fiabilité et flexibilité.
    """
    _qgis_cmd, _qgis_args = _qgis_command()

    # Config au format attendu par MultiServerMCPClient.
    return {
        # Instance HTTP hébergée par l'IGN (transport streamable_http) : aucun Node/npm
        # requis, jointe via le proxy IGN. Alternative locale : command "npx",
        # args ["-y", "@ignfab/geocontext"], transport "stdio" (nécessite Node ≥ 22).
        "geoportail": {
            "url": GEOPORTAIL_URL,
            "transport": "streamable_http",
        },
        "qgis": {
            "command": _qgis_cmd,
            "args": _qgis_args,
            "transport": "stdio",
        },
    }
