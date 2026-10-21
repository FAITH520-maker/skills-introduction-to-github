"""会话 JSON 文件存储：每个会话一个 JSON 文件，原子写入。"""
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from config import SESSION_DIR


class SessionStore:
    def __init__(self, root: Path = SESSION_DIR) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def new_id(self) -> str:
        return f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"

    def path(self, session_id: str) -> Path:
        safe = "".join(ch for ch in session_id if ch.isalnum() or ch in "-_")
        return self.root / f"{safe}.json"

    def save(self, session: dict) -> None:
        target = self.path(session["id"])
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)

    def load(self, session_id: str) -> dict:
        target = self.path(session_id)
        if not target.exists():
            raise FileNotFoundError(session_id)
        return json.loads(target.read_text(encoding="utf-8"))

    def list_all(self) -> list[dict]:
        sessions = []
        for file_path in self.root.glob("*.json"):
            try:
                sessions.append(json.loads(file_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        sessions.sort(key=lambda s: s.get("created_at", ""), reverse=True)
        return sessions

    def delete(self, session_id: str) -> bool:
        target = self.path(session_id)
        if target.exists():
            target.unlink()
            return True
        return False
