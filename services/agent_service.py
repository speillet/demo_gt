from __future__ import annotations

import asyncio
import queue
import threading

from langchain_core.messages import AIMessage, ToolMessage

from agent import build_agent

class AgentRuntime:
    """Boucle asyncio en thread d'arrière-plan + agent MCP persistant."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        # Construit l'agent (et ouvre les sessions MCP) sur la boucle dédiée.
        self.agent, self.tools = self._submit(build_agent()).result()
        # Future du tour en cours (pour pouvoir l'annuler depuis /stop).
        self._current = None

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def stream_turn(self, history: list[tuple[str, str]]):
        """Exécute un tour et restitue, en synchrone, les chunks d'update de
        l'agent via une file thread-safe."""
        q: queue.Queue = queue.Queue()

        async def runner():
            try:
                async for chunk in self.agent.astream(
                    {"messages": history}, stream_mode="updates"
                ):
                    q.put(("update", chunk))
            except asyncio.CancelledError:  # annulation via /stop
                q.put(("stopped", None))
                raise
            except Exception as exc:  # remonte l'erreur au flux
                q.put(("error", exc))
            finally:
                q.put(("done", None))

        # On garde la Future pour pouvoir annuler la coroutine de l'agent :
        # cancel() sur la Future de run_coroutine_threadsafe propage l'annulation
        # à la tâche asyncio sous-jacente.
        self._current = self._submit(runner())
        try:
            while True:
                kind, payload = q.get()
                if kind == "done":
                    break
                yield kind, payload
        finally:
            self._current = None

    def cancel_current(self) -> bool:
        """Annule le tour de l'agent en cours, s'il y en a un."""
        fut = self._current
        return bool(fut and fut.cancel())

# ── Runtime partagé (singleton, construit à la 1re requête) ────────────────────
_runtime: AgentRuntime | None = None
_runtime_lock = threading.Lock()

def get_runtime() -> AgentRuntime:
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = AgentRuntime()
    return _runtime

def updates_to_events(chunk: dict):
    """Convertit un update LangGraph en événements pour le frontend.

    Renvoie une liste de dicts ``{"type": ...}`` et le texte assistant accumulé.
    """
    events = []
    text = ""
    for node_state in chunk.values():
        for msg in node_state.get("messages", []):
            if isinstance(msg, AIMessage):
                for call in getattr(msg, "tool_calls", []) or []:
                    events.append(
                        {"type": "tool_call", "name": call["name"], "args": call.get("args", {})}
                    )
                
                if isinstance(msg.content, str) and msg.content.strip():
                    text += msg.content
                elif isinstance(msg.content, list):
                    for block in msg.content:
                        if isinstance(block, str):
                            text += block
                        elif isinstance(block, dict) and block.get("type") == "text":
                            text += block.get("text", "")

            elif isinstance(msg, ToolMessage):
                preview = str(msg.content)
                if len(preview) > 800:
                    preview = preview[:800] + " …(tronqué)"
                events.append({"type": "tool_result", "name": msg.name, "preview": preview})
    return events, text
