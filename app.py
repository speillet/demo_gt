"""Interface web Flask de l'agent géospatial Géoportail × QGIS.

Flask est synchrone alors que le client MCP (sessions stdio) est asynchrone. On
maintient donc **une boucle asyncio dédiée dans un thread d'arrière-plan**
(`AgentRuntime`), créée une seule fois ; l'agent et ses sessions MCP y sont
construits une fois et restent vivants entre les tours. Les coroutines de l'agent
y sont soumises via `run_coroutine_threadsafe`, et les événements remontent par
une file thread-safe consommée en streaming par la route `/chat`.
"""

from __future__ import annotations

import json
import os

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    make_response,
    render_template,
    request,
    send_from_directory,
)

from conversations import ConversationStore
from services import agent_service
from services.agent_service import get_runtime, updates_to_events
from llm import resolve_provider_name, get_active_model, set_active_model, list_available_models

# ── Grille tarifaire par modèle ($ / million de tokens) ────────────────────────
# Clé = début du nom de modèle (préfixe). Valeurs = (input, output) en $/Mtok.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4":      (3.0,  15.0),
    "claude-opus-4":        (15.0, 75.0),
    "claude-3-5-sonnet":    (3.0,  15.0),
    "claude-3-5-haiku":     (0.80, 4.0),
    "gpt-4o":               (2.50, 10.0),
    "gpt-4.1":              (2.0,  8.0),
    "o4-mini":              (1.10, 4.40),
    "deepseek/deepseek-v4": (0.50, 1.50),
    "deepseek/deepseek-chat": (0.27, 1.10),
}


def _estimate_cost(input_tokens: int, output_tokens: int) -> float | None:
    """Estime le coût en dollars à partir du modèle actif."""
    model = get_active_model()
    for prefix, (inp_price, out_price) in MODEL_PRICING.items():
        if model.startswith(prefix):
            return (input_tokens * inp_price + output_tokens * out_price) / 1_000_000
    return None

conversation_store = ConversationStore()

app = Flask(__name__)


@app.get("/")
def index():
    # Pas de cache sur la page HTML : chaque chargement sert la version courante
    # du template (sinon le navigateur réaffiche une ancienne page après relance).
    resp = make_response(render_template("index.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.post("/stop")
def stop():
    # Annule le tour en cours sans toucher à l'historique ni aux serveurs MCP.
    agent_service.cancel_current()
    return ("", 204)


# ── Modèles ────────────────────────────────────────────────────────────────────
@app.get("/models")
def models_list():
    return jsonify(list_available_models())


@app.post("/model")
def model_switch():
    data = request.get_json(silent=True) or {}
    model_id = (data.get("model") or "").strip()
    if not model_id:
        return jsonify({"error": "model manquant"}), 400
    try:
        runtime = get_runtime()
        runtime.switch_model(model_id)
        set_active_model(model_id)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"model": model_id})


# ── Conversations ──────────────────────────────────────────────────────────────
@app.get("/conversations")
def conversations_list():
    return jsonify(conversation_store.list_conversations())


@app.post("/conversations")
def conversations_create():
    conv_id = conversation_store.new_conversation()
    return jsonify(conversation_store.load(conv_id)["meta"]), 201


@app.get("/conversations/<conv_id>")
def conversations_get(conv_id):
    if not conversation_store.exists(conv_id):
        abort(404)
    return jsonify(conversation_store.load(conv_id))


@app.delete("/conversations/<conv_id>")
def conversations_delete(conv_id):
    if not conversation_store.delete(conv_id):
        abort(404)
    return ("", 204)


@app.get("/conversations/<conv_id>/files/<path:name>")
def conversations_file(conv_id, name):
    path = conversation_store.safe_file_path(conv_id, name)
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
    if not conversation_store.exists(conv_id):
        return jsonify({"error": "conversation inconnue"}), 404

    # Persiste le message utilisateur et prépare le contexte du tour.
    conversation_store.append_message(conv_id, "user", message)
    conv_dir = conversation_store.conv_dir(conv_id)
    turn_messages = [_folder_note(conv_dir)] + conversation_store.messages(conv_id)

    def generate():
        def sse(evt: dict) -> str:
            return json.dumps(evt, ensure_ascii=False) + "\n"

        final_text = ""
        stopped = False
        total_input = 0
        total_output = 0
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
                events, text, usage = updates_to_events(payload)
                total_input += usage["input"]
                total_output += usage["output"]
                for evt in events:
                    yield sse(evt)
                final_text += text
            if not stopped:
                cost = _estimate_cost(total_input, total_output)
                yield sse({
                    "type": "final",
                    "text": final_text or "(aucune réponse texte)",
                    "usage": {"input_tokens": total_input, "output_tokens": total_output, "cost": cost},
                })
        except Exception as exc:  # pragma: no cover - garde-fou
            yield sse({"type": "error", "message": str(exc)})
            final_text = final_text or f"❌ Erreur : {exc}"
        finally:
            # On conserve l'historique : réponse partielle ou marqueur d'interruption.
            if stopped and not final_text:
                conversation_store.append_message(conv_id, "assistant", "(réponse interrompue par l'utilisateur)")
            else:
                conversation_store.append_message(conv_id, "assistant", final_text or "(aucune réponse texte)")

    return Response(
        generate(),
        mimetype="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, threaded=True)
