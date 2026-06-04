"""Interface web Flask de l'agent géospatial Géoportail × QGIS.

Flask est synchrone alors que le client MCP (sessions stdio) est asynchrone. On
maintient donc **une boucle asyncio dédiée dans un thread d'arrière-plan**
(`AgentRuntime`), créée une seule fois ; l'agent et ses sessions MCP y sont
construits une fois et restent vivants entre les tours. Les coroutines de l'agent
y sont soumises via `run_coroutine_threadsafe`, et les événements remontent par
une file thread-safe consommée en streaming par la route `/chat`.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import threading

from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from langchain_core.messages import AIMessage, ToolMessage

import conversations
from agent import build_agent

load_dotenv()


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


app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/stop")
def stop():
    # Annule le tour en cours sans toucher à l'historique ni aux serveurs MCP.
    if _runtime is not None:
        _runtime.cancel_current()
    return ("", 204)


# ── Conversations ──────────────────────────────────────────────────────────────
@app.get("/conversations")
def conversations_list():
    return jsonify(conversations.list_conversations())


@app.post("/conversations")
def conversations_create():
    conv_id = conversations.new_conversation()
    return jsonify(conversations.load(conv_id)["meta"]), 201


@app.get("/conversations/<conv_id>")
def conversations_get(conv_id):
    if not conversations.exists(conv_id):
        abort(404)
    return jsonify(conversations.load(conv_id))


@app.delete("/conversations/<conv_id>")
def conversations_delete(conv_id):
    if not conversations.delete(conv_id):
        abort(404)
    return ("", 204)


@app.get("/conversations/<conv_id>/files/<path:name>")
def conversations_file(conv_id, name):
    path = conversations.safe_file_path(conv_id, name)
    if path is None:
        abort(404)
    directory, filename = os.path.split(path)
    return send_from_directory(directory, filename, as_attachment=True)


# ── Chat ───────────────────────────────────────────────────────────────────────
def _folder_note(conv_dir: str) -> tuple[str, str]:
    return (
        "system",
        "Dossier de travail de CETTE conversation (écris-y TOUS les fichiers téléchargés "
        f"ou produits — GeoJSON, projets QGIS .qgs, rendus) : {conv_dir}",
    )


@app.post("/chat")
def chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    conv_id = data.get("conversation_id") or ""
    if not message:
        return jsonify({"error": "message vide"}), 400
    if not conversations.exists(conv_id):
        return jsonify({"error": "conversation inconnue"}), 404

    # Persiste le message utilisateur et prépare le contexte du tour.
    conversations.append_message(conv_id, "user", message)
    conv_dir = conversations.conv_dir(conv_id)
    turn_messages = [_folder_note(conv_dir)] + conversations.messages(conv_id)

    def generate():
        def sse(evt: dict) -> str:
            return json.dumps(evt, ensure_ascii=False) + "\n"

        final_text = ""
        stopped = False
        try:
            runtime = get_runtime()
            for kind, payload in runtime.stream_turn(turn_messages):
                if kind == "error":
                    yield sse({"type": "error", "message": str(payload)})
                    final_text = final_text or f"❌ Erreur : {payload}"
                    break
                if kind == "stopped":
                    stopped = True
                    yield sse({"type": "stopped"})
                    break
                events, text = updates_to_events(payload)
                for evt in events:
                    yield sse(evt)
                final_text += text
            if not stopped:
                yield sse({"type": "final", "text": final_text or "(aucune réponse texte)"})
        except Exception as exc:  # pragma: no cover - garde-fou
            yield sse({"type": "error", "message": str(exc)})
            final_text = final_text or f"❌ Erreur : {exc}"
        finally:
            # On conserve l'historique : réponse partielle ou marqueur d'interruption.
            if stopped and not final_text:
                conversations.append_message(conv_id, "assistant", "(réponse interrompue par l'utilisateur)")
            else:
                conversations.append_message(conv_id, "assistant", final_text or "(aucune réponse texte)")

    return Response(
        generate(),
        mimetype="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, threaded=True)
