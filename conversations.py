"""Persistance des conversations sur disque.

Chaque conversation est un dossier ``data/conversations/<id>/`` contenant :
- ``conversation.json`` : métadonnées (id, titre, dates) + liste des messages ;
- tous les autres fichiers = fichiers téléchargés/produits par l'agent
  (GeoJSON, projets ``.qgs``, rendus…). Ce dossier est aussi le **dossier de
  travail** communiqué à l'agent, ce qui associe naturellement les fichiers à la
  conversation.

Usage local mono-utilisateur : un simple verrou protège les écritures.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from datetime import datetime, timezone

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "conversations")
META_FILE = "conversation.json"
_lock = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conv_dir(conv_id: str) -> str:
    return os.path.join(BASE_DIR, conv_id)


def _meta_path(conv_id: str) -> str:
    return os.path.join(_conv_dir(conv_id), META_FILE)


def _is_valid_id(conv_id: str) -> bool:
    # uuid4 hex (pas de séparateur de chemin) — empêche toute traversée.
    return bool(conv_id) and conv_id.isalnum()


def _read(conv_id: str) -> dict:
    with open(_meta_path(conv_id), encoding="utf-8") as f:
        return json.load(f)


def _write(conv_id: str, data: dict) -> None:
    path = _meta_path(conv_id)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # écriture atomique


def conv_dir(conv_id: str) -> str:
    """Dossier de travail absolu de la conversation (à communiquer à l'agent)."""
    if not _is_valid_id(conv_id) or not os.path.isdir(_conv_dir(conv_id)):
        raise KeyError(conv_id)
    return _conv_dir(conv_id)


def new_conversation() -> str:
    """Crée une conversation vide et renvoie son id."""
    conv_id = uuid.uuid4().hex
    with _lock:
        os.makedirs(_conv_dir(conv_id), exist_ok=True)
        now = _now()
        _write(conv_id, {
            "id": conv_id,
            "title": "Nouvelle conversation",
            "created_at": now,
            "updated_at": now,
            "messages": [],
        })
    return conv_id


def exists(conv_id: str) -> bool:
    return _is_valid_id(conv_id) and os.path.isfile(_meta_path(conv_id))


def load(conv_id: str) -> dict:
    """Renvoie ``{meta, messages, files}`` pour une conversation."""
    with _lock:
        data = _read(conv_id)
    return {"meta": _meta(data), "messages": data.get("messages", []), "files": list_files(conv_id)}


def messages(conv_id: str) -> list[tuple[str, str]]:
    """Messages sous forme de tuples ``(role, content)`` pour l'agent."""
    with _lock:
        data = _read(conv_id)
    return [(m["role"], m["content"]) for m in data.get("messages", [])]


def append_message(conv_id: str, role: str, content: str) -> None:
    with _lock:
        data = _read(conv_id)
        data.setdefault("messages", []).append({"role": role, "content": content})
        data["updated_at"] = _now()
        # Titre = premier message utilisateur tronqué.
        if role == "user" and data.get("title") in (None, "", "Nouvelle conversation"):
            data["title"] = (content[:60] + "…") if len(content) > 60 else content
        _write(conv_id, data)


def _meta(data: dict) -> dict:
    msgs = data.get("messages", [])
    return {
        "id": data["id"],
        "title": data.get("title") or "Nouvelle conversation",
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "message_count": len(msgs),
    }


def list_conversations() -> list[dict]:
    """Liste des conversations triées par date de mise à jour décroissante."""
    if not os.path.isdir(BASE_DIR):
        return []
    out = []
    with _lock:
        for conv_id in os.listdir(BASE_DIR):
            if not os.path.isfile(_meta_path(conv_id)):
                continue
            try:
                meta = _meta(_read(conv_id))
            except (OSError, json.JSONDecodeError, KeyError):
                continue
            meta["file_count"] = len(list_files(conv_id))
            out.append(meta)
    out.sort(key=lambda m: m.get("updated_at") or "", reverse=True)
    return out


def list_files(conv_id: str) -> list[dict]:
    """Fichiers du dossier de la conversation (hors métadonnées)."""
    d = _conv_dir(conv_id)
    if not os.path.isdir(d):
        return []
    files = []
    for name in sorted(os.listdir(d)):
        if name == META_FILE or name.endswith(".tmp"):
            continue
        full = os.path.join(d, name)
        if os.path.isfile(full):
            st = os.stat(full)
            files.append({
                "name": name,
                "size": st.st_size,
                "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
            })
    return files


def safe_file_path(conv_id: str, name: str) -> str | None:
    """Chemin absolu d'un fichier de la conversation, ou None si hors dossier."""
    if not _is_valid_id(conv_id):
        return None
    base = os.path.realpath(_conv_dir(conv_id))
    full = os.path.realpath(os.path.join(base, name))
    if (full == base) or (os.path.commonpath([base, full]) != base):
        return None  # tentative de traversée
    if os.path.basename(full) == META_FILE or not os.path.isfile(full):
        return None
    return full


def delete(conv_id: str) -> bool:
    if not _is_valid_id(conv_id):
        return False
    with _lock:
        d = _conv_dir(conv_id)
        if os.path.isdir(d):
            shutil.rmtree(d)
            return True
    return False
