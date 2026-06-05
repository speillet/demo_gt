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
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import CONVERSATIONS_DIR

class ConversationStore:
    def __init__(self):
        self.base_dir = Path(CONVERSATIONS_DIR)
        self.meta_file = "conversation.json"
        self._lock = threading.RLock()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _conv_dir(self, conv_id: str) -> Path:
        return self.base_dir / conv_id

    def _meta_path(self, conv_id: str) -> Path:
        return self._conv_dir(conv_id) / self.meta_file

    def _is_valid_id(self, conv_id: str) -> bool:
        # uuid4 hex (pas de séparateur de chemin) — empêche toute traversée.
        return bool(conv_id) and conv_id.isalnum()

    def _read(self, conv_id: str) -> dict:
        with open(self._meta_path(conv_id), encoding="utf-8") as f:
            return json.load(f)

    def _write(self, conv_id: str, data: dict) -> None:
        path = self._meta_path(conv_id)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(path)  # écriture atomique

    def conv_dir(self, conv_id: str) -> str:
        """Dossier de travail absolu de la conversation (à communiquer à l'agent)."""
        if not self._is_valid_id(conv_id) or not self._conv_dir(conv_id).is_dir():
            raise KeyError(conv_id)
        return str(self._conv_dir(conv_id))

    def new_conversation(self) -> str:
        """Crée une conversation vide et renvoie son id."""
        conv_id = uuid.uuid4().hex
        with self._lock:
            self._conv_dir(conv_id).mkdir(parents=True, exist_ok=True)
            now = self._now()
            self._write(conv_id, {
                "id": conv_id,
                "title": "Nouvelle conversation",
                "created_at": now,
                "updated_at": now,
                "messages": [],
            })
        return conv_id

    def exists(self, conv_id: str) -> bool:
        return self._is_valid_id(conv_id) and self._meta_path(conv_id).is_file()

    def load(self, conv_id: str) -> dict:
        """Renvoie ``{meta, messages, files}`` pour une conversation."""
        with self._lock:
            data = self._read(conv_id)
        return {"meta": self._meta(data), "messages": data.get("messages", []), "files": self.list_files(conv_id)}

    def messages(self, conv_id: str) -> list[tuple[str, str]]:
        """Messages sous forme de tuples ``(role, content)`` pour l'agent."""
        with self._lock:
            data = self._read(conv_id)
        return [(m["role"], m["content"]) for m in data.get("messages", [])]

    def append_message(self, conv_id: str, role: str, content: str) -> None:
        with self._lock:
            data = self._read(conv_id)
            data.setdefault("messages", []).append({"role": role, "content": content})
            data["updated_at"] = self._now()
            # Titre = premier message utilisateur tronqué.
            if role == "user" and data.get("title") in (None, "", "Nouvelle conversation"):
                data["title"] = (content[:60] + "…") if len(content) > 60 else content
            self._write(conv_id, data)

    def _meta(self, data: dict) -> dict:
        msgs = data.get("messages", [])
        return {
            "id": data["id"],
            "title": data.get("title") or "Nouvelle conversation",
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "message_count": len(msgs),
        }

    def list_conversations(self) -> list[dict]:
        """Liste des conversations triées par date de mise à jour décroissante."""
        if not self.base_dir.is_dir():
            return []
        out = []
        with self._lock:
            for item in self.base_dir.iterdir():
                conv_id = item.name
                if not self._meta_path(conv_id).is_file():
                    continue
                try:
                    meta = self._meta(self._read(conv_id))
                except (OSError, json.JSONDecodeError, KeyError):
                    continue
                meta["file_count"] = len(self.list_files(conv_id))
                out.append(meta)
        out.sort(key=lambda m: m.get("updated_at") or "", reverse=True)
        return out

    def list_files(self, conv_id: str) -> list[dict]:
        """Fichiers du dossier de la conversation (hors métadonnées)."""
        d = self._conv_dir(conv_id)
        if not d.is_dir():
            return []
        files = []
        for p in sorted(d.iterdir(), key=lambda x: x.name):
            if p.name == self.meta_file or p.name.endswith(".tmp"):
                continue
            if p.is_file():
                st = p.stat()
                files.append({
                    "name": p.name,
                    "size": st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
                })
        return files

    def safe_file_path(self, conv_id: str, name: str) -> str | None:
        """Chemin absolu d'un fichier de la conversation, ou None si hors dossier."""
        if not self._is_valid_id(conv_id):
            return None
        base = self._conv_dir(conv_id).resolve()
        full = (base / name).resolve()
        
        # empêcher la traversée
        if not str(full).startswith(str(base)):
            return None
            
        if str(full) == str(base) or full.name == self.meta_file or not full.is_file():
            return None
        return str(full)

    def delete(self, conv_id: str) -> bool:
        if not self._is_valid_id(conv_id):
            return False
        with self._lock:
            d = self._conv_dir(conv_id)
            if d.is_dir():
                shutil.rmtree(d)
                return True
        return False
