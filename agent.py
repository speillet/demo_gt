"""Construction de l'agent LangGraph connecté aux serveurs MCP.

L'agent est un ReAct (`create_react_agent`) qui reçoit la totalité des outils
exposés par les deux serveurs MCP (Géoportail IGN + QGIS) via
``MultiServerMCPClient``. Tout est asynchrone : le client MCP ouvre des sessions
``stdio`` persistantes, donc l'agent doit être construit puis utilisé sur la
**même** boucle asyncio (voir ``app.py`` pour l'intégration Streamlit).
"""

from __future__ import annotations

import json

from langchain_core.tools import BaseTool, StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent

from llm import build_model, build_model_by_id
from mcp_servers import get_mcp_servers_config
from prompts import build_system_prompt


def _flatten_tool_result(result) -> str:
    """Aplatit un résultat d'outil MCP en texte simple.

    Les outils MCP renvoient une liste de blocs de contenu
    (``[{"type": "text", "text": ...}, ...]``). Les blocs **non textuels**
    (ressource, fichier, URL, image) produisent des « data blocks » que l'API
    OpenAI Chat Completions (donc OpenRouter) refuse
    (« does not support file URLs »). On concatène donc le texte et on remplace
    les blocs non textuels par un court marqueur — évite l'erreur et l'explosion
    de tokens (base64 d'images, etc.).
    """
    if isinstance(result, tuple):  # response_format="content_and_artifact"
        result = result[0]
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        parts: list[str] = []
        for block in result:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                else:
                    parts.append(f"[contenu non-textuel omis : {block.get('type', '?')}]")
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return json.dumps(result, ensure_ascii=False, default=str)


def _text_only_tool(tool: BaseTool) -> BaseTool:
    """Enveloppe un outil MCP pour que sa sortie soit du texte simple."""

    async def _coro(**kwargs):
        return _flatten_tool_result(await tool.ainvoke(kwargs))

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        coroutine=_coro,
    )


async def build_agent():
    """Crée le client MCP, récupère les outils des deux serveurs, et renvoie
    le couple ``(agent, tools)``.

    À appeler une seule fois, sur la boucle asyncio dédiée. Les sessions stdio
    restent ouvertes tant que la boucle vit.
    """
    client = MultiServerMCPClient(get_mcp_servers_config())
    tools = [_text_only_tool(t) for t in await client.get_tools()]
    agent = create_react_agent(
        build_model(),
        tools,
        prompt=build_system_prompt(),
    )
    # On garde une référence au client sur l'agent pour éviter qu'il soit
    # garbage-collecté (ce qui fermerait les sous-processus MCP).
    agent._mcp_client = client  # type: ignore[attr-defined]
    return agent, tools, client


def rebuild_agent_with_model(model_id: str, tools: list[BaseTool], client):
    """Reconstruit l'agent avec un modèle différent, en réutilisant les outils MCP existants."""
    agent = create_react_agent(
        build_model_by_id(model_id),
        tools,
        prompt=build_system_prompt(),
    )
    agent._mcp_client = client  # type: ignore[attr-defined]
    return agent
