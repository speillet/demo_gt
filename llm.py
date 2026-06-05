"""Sélection et construction du modèle de chat (fournisseur configurable).

Le fournisseur est choisi via la variable d'environnement ``LLM_PROVIDER``. S'il
n'est pas défini, on auto-détecte le premier fournisseur dont la configuration est
présente (ex. une clé d'API), sinon on retombe sur ``anthropic``.

**Ajouter un fournisseur** = ajouter un appel ``register(Provider(...))`` ci-dessous.
La plupart des fournisseurs sont des endpoints *compatibles OpenAI* : il suffit de
fournir ``base_url`` + ``api_key`` + ``model`` (helper ``_openai_compatible``).
Le fournisseur ``custom`` permet même d'en brancher un **sans toucher au code**,
uniquement via le ``.env`` (``LLM_BASE_URL`` / ``LLM_API_KEY`` / ``LLM_MODEL_NAME``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from langchain_core.language_models import BaseChatModel

# Paramètres d'échantillonnage communs à tous les fournisseurs.
TEMPERATURE = 0
MAX_TOKENS = 8192


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"La variable d'environnement {name} est requise pour ce fournisseur LLM.")
    return value


def _openai_compatible(*, base_url: str, api_key: str, model: str, headers: dict | None = None) -> BaseChatModel:
    """Construit un modèle pour n'importe quel endpoint compatible OpenAI."""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        default_headers=headers or {},
    )


def _anthropic(*, model: str) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(model=model, temperature=TEMPERATURE, max_tokens=MAX_TOKENS)


@dataclass(frozen=True)
class Provider:
    """Description d'un fournisseur de modèle.

    - ``build`` : construit le ``BaseChatModel`` (lecture des variables d'env au
      moment de l'appel, pas à l'import).
    - ``detect`` : vrai si ce fournisseur est utilisable en l'état (auto-détection
      quand ``LLM_PROVIDER`` n'est pas défini).
    """

    name: str
    build: Callable[[], BaseChatModel]
    detect: Callable[[], bool] = lambda: False


PROVIDERS: dict[str, Provider] = {}

# Catalogue des modèles proposés par fournisseur (ceux affichés dans le sélecteur).
# Chaque entrée : (identifiant affiché, nom technique envoyé à l'API).
# Le 1er de chaque liste sert de défaut. Tous compatibles « tool calling ».
MODELS_CATALOG: dict[str, list[tuple[str, str]]] = {
    # Vérifiés sur https://openrouter.ai/models (juin 2026).
    "openrouter": [
        # — Performants —
        ("DeepSeek V4 Pro", "deepseek/deepseek-v4-pro"),
        ("Claude Opus 4.8", "anthropic/claude-opus-4.8"),
        ("GPT-5.5", "openai/gpt-5.5"),
        ("GPT-5.5 Pro", "openai/gpt-5.5-pro"),
        ("Grok 4.3", "x-ai/grok-4.3"),
        ("Qwen3.7 Max", "qwen/qwen3.7-max"),
        ("Mistral Medium 3.5", "mistralai/mistral-medium-3.5"),
        # — Rapides / économiques —
        ("DeepSeek V4 Flash", "deepseek/deepseek-v4-flash"),
        ("GPT-5.4 Mini", "openai/gpt-5.4-mini"),
        ("Gemini 3.5 Flash", "google/gemini-3.5-flash"),
        ("Claude Opus 4.8 (Fast)", "anthropic/claude-opus-4.8-fast"),
        ("Qwen3.7 Plus", "qwen/qwen3.7-plus"),
    ],
    # Identifiants de l'API native Anthropic.
    "anthropic": [
        ("Claude Sonnet 4.6", "claude-sonnet-4-6"),
        ("Claude Opus 4.8", "claude-opus-4-8"),
        ("Claude Haiku 4.5", "claude-haiku-4-5-20251001"),
    ],
    # Identifiants de l'API native OpenAI.
    "openai": [
        ("GPT-5.5", "gpt-5.5"),
        ("GPT-5.5 Pro", "gpt-5.5-pro"),
        ("GPT-5.4 Mini", "gpt-5.4-mini"),
        ("GPT-4o", "gpt-4o"),
    ],
    "github_copilot": [
        ("GPT-4o", "gpt-4o"),
        ("Claude Sonnet 4", "claude-sonnet-4"),
    ],
}


def register(provider: Provider) -> None:
    PROVIDERS[provider.name] = provider


# ── Fournisseurs livrés ─────────────────────────────────────────────────────────
register(Provider(
    "openrouter",
    build=lambda: _openai_compatible(
        base_url=_env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key=_require("OPENROUTER_API_KEY"),
        model=_env("OPENROUTER_MODEL", "deepseek/deepseek-v4-pro"),
        headers={"X-Title": "demo_gt"},  # classement OpenRouter (optionnel)
    ),
    detect=lambda: bool(_env("OPENROUTER_API_KEY")),
))

register(Provider(
    "anthropic",
    build=lambda: _anthropic(model=_env("LLM_MODEL", "claude-sonnet-4-6")),
    detect=lambda: bool(_env("ANTHROPIC_API_KEY")),
))

register(Provider(
    "openai",
    build=lambda: _openai_compatible(
        base_url=_env("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key=_require("OPENAI_API_KEY"),
        model=_env("OPENAI_MODEL", "gpt-4o"),
    ),
    detect=lambda: bool(_env("OPENAI_API_KEY")),
))

register(Provider(
    # GitHub Copilot via le proxy local copilot-api (cf. README). Le proxy gère
    # l'authentification GitHub ; la clé client est factice par défaut.
    "github_copilot",
    build=lambda: _openai_compatible(
        base_url=_env("COPILOT_BASE_URL", "http://localhost:4141/v1"),
        api_key=_env("COPILOT_API_KEY", "copilot"),
        model=_env("COPILOT_MODEL", "gpt-4o"),
    ),
))

register(Provider(
    # Catch-all : n'importe quel endpoint compatible OpenAI (opencode, vLLM,
    # Ollama, etc.) configuré entièrement via le .env, sans modifier le code.
    "custom",
    build=lambda: _openai_compatible(
        base_url=_require("LLM_BASE_URL"),
        api_key=_env("LLM_API_KEY", "none"),
        model=_require("LLM_MODEL_NAME"),
    ),
))


def _auto_detect() -> str | None:
    for provider in PROVIDERS.values():
        if provider.detect():
            return provider.name
    return None


def resolve_provider_name() -> str:
    """Nom du fournisseur actif (variable explicite, sinon auto-détection)."""
    return _env("LLM_PROVIDER") or _auto_detect() or "anthropic"


def build_model() -> BaseChatModel:
    """Instancie le modèle de chat du fournisseur configuré."""
    name = resolve_provider_name()
    provider = PROVIDERS.get(name)
    if provider is None:
        raise ValueError(
            f"Fournisseur LLM inconnu : '{name}'. Disponibles : {', '.join(PROVIDERS)}."
        )
    return provider.build()


# ── Sélection dynamique du modèle ──────────────────────────────────────────────

# Modèle choisi dans l'UI (None = défaut du fournisseur).
_active_model: str | None = None


def get_active_model() -> str:
    """Renvoie le nom technique du modèle actif."""
    if _active_model:
        return _active_model
    # Tombe sur le défaut du fournisseur.
    provider = resolve_provider_name()
    catalog = MODELS_CATALOG.get(provider, [])
    return catalog[0][1] if catalog else ""


def set_active_model(model_id: str) -> None:
    global _active_model
    _active_model = model_id


def list_available_models() -> list[dict]:
    """Renvoie la liste des modèles proposés pour le fournisseur actif."""
    provider = resolve_provider_name()
    catalog = MODELS_CATALOG.get(provider, [])
    active = get_active_model()
    return [
        {"label": label, "id": mid, "active": mid == active}
        for label, mid in catalog
    ]


def build_model_by_id(model_id: str) -> BaseChatModel:
    """Construit un modèle à partir d'un identifiant technique du catalogue."""
    provider_name = resolve_provider_name()
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        raise ValueError(f"Fournisseur inconnu : {provider_name}")

    # On reconstruit le modèle en surchargeant le nom.
    if provider_name == "openrouter":
        return _openai_compatible(
            base_url=_env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            api_key=_require("OPENROUTER_API_KEY"),
            model=model_id,
            headers={"X-Title": "demo_gt"},
        )
    elif provider_name == "anthropic":
        return _anthropic(model=model_id)
    elif provider_name == "openai":
        return _openai_compatible(
            base_url=_env("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            api_key=_require("OPENAI_API_KEY"),
            model=model_id,
        )
    elif provider_name == "github_copilot":
        return _openai_compatible(
            base_url=_env("COPILOT_BASE_URL", "http://localhost:4141/v1"),
            api_key=_env("COPILOT_API_KEY", "copilot"),
            model=model_id,
        )
    else:
        return _openai_compatible(
            base_url=_require("LLM_BASE_URL"),
            api_key=_env("LLM_API_KEY", "none"),
            model=model_id,
        )
