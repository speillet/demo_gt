"""Construction de l'agent LangGraph connecté aux serveurs MCP.

L'agent est un ReAct (`create_react_agent`) qui reçoit la totalité des outils
exposés par les deux serveurs MCP (Géoportail IGN + QGIS) via
``MultiServerMCPClient``. Tout est asynchrone : le client MCP ouvre des sessions
``stdio`` persistantes, donc l'agent doit être construit puis utilisé sur la
**même** boucle asyncio (voir ``app.py`` pour l'intégration Streamlit).
"""

from __future__ import annotations

import json
import os

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool, StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent

from mcp_servers import SERVERS
from prompts import build_system_prompt

# Modèles par défaut selon le fournisseur.
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v4-pro"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def build_model() -> BaseChatModel:
    """Instancie le modèle de chat selon le fournisseur configuré.

    Sélection (variable ``LLM_PROVIDER`` : "openrouter" | "anthropic" | absente) :
    - OpenRouter si ``LLM_PROVIDER=openrouter`` ou, en auto, dès que
      ``OPENROUTER_API_KEY`` est défini (modèle via ``OPENROUTER_MODEL``) ;
    - Anthropic sinon (modèle via ``LLM_MODEL``).

    Les imports des SDK sont paresseux pour ne pas exiger les deux à la fois.
    """
    provider = os.environ.get("LLM_PROVIDER")
    use_openrouter = provider == "openrouter" or (
        provider is None and os.environ.get("OPENROUTER_API_KEY")
    )

    if use_openrouter:
        from langchain_openai import ChatOpenAI

        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError(
                "La clé OPENROUTER_API_KEY est manquante "
                "alors que le fournisseur configuré/détecté est OpenRouter."
            )

        return ChatOpenAI(
            model=os.environ.get("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL),
            base_url=OPENROUTER_BASE_URL,
            api_key=api_key,
            temperature=0,
            max_tokens=8192,
            default_headers={"X-Title": "demo_gt"},  # classement OpenRouter (optionnel)
        )

    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model=os.environ.get("LLM_MODEL", DEFAULT_ANTHROPIC_MODEL),
        temperature=0,
        max_tokens=8192,
    )


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
    client = MultiServerMCPClient(SERVERS)
    tools = [_text_only_tool(t) for t in await client.get_tools()]
    agent = create_react_agent(
        build_model(),
        tools,
        prompt=build_system_prompt(),
    )
    # On garde une référence au client sur l'agent pour éviter qu'il soit
    # garbage-collecté (ce qui fermerait les sous-processus MCP).
    agent._mcp_client = client  # type: ignore[attr-defined]
    return agent, tools
