from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

WORD = re.compile(r"[a-z0-9']+")
PROFILE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: str, *, max_turns: int = 24, max_memories: int = 100) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.max_turns = max_turns
        self.max_memories = max_memories
        with self.connection:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                    user_text TEXT NOT NULL,
                    assistant_text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_turns_profile ON turns(profile_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                    content TEXT NOT NULL,
                    normalized TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(profile_id, normalized)
                );
                CREATE INDEX IF NOT EXISTS idx_memories_profile ON memories(profile_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                    name TEXT,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    last_seen TEXT,
                    revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_devices_profile ON devices(profile_id, created_at DESC);
                """
            )

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def ensure_profile(self, profile_id: str) -> None:
        if not PROFILE.fullmatch(profile_id):
            raise ValueError("profile_id must be 1-64 letters, numbers, dots, dashes, or underscores")
        now = _now()
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO profiles(id, created_at, updated_at) VALUES(?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at",
                (profile_id, now, now),
            )

    def create_device(self, *, name: str | None = None, profile_id: str | None = None) -> dict[str, str]:
        profile_id = profile_id or f"profile-{uuid.uuid4().hex[:12]}"
        self.ensure_profile(profile_id)
        device_id = f"device_{uuid.uuid4().hex[:16]}"
        token = "pa_" + secrets.token_urlsafe(32)
        now = _now()
        safe_name = " ".join((name or "Windows PC").split()).strip()[:120] or "Windows PC"
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO devices(id, profile_id, name, token_hash, created_at, last_seen, revoked) "
                "VALUES(?, ?, ?, ?, ?, NULL, 0)",
                (device_id, profile_id, safe_name, self.hash_token(token), now),
            )
        return {
            "device_id": device_id,
            "profile_id": profile_id,
            "device_name": safe_name,
            "device_token": token,
        }

    def authenticate_device(self, token: str) -> dict[str, str] | None:
        if not token:
            return None
        token_hash = self.hash_token(token)
        now = _now()
        with self.lock, self.connection:
            row = self.connection.execute(
                "SELECT id, profile_id, name FROM devices WHERE token_hash=? AND revoked=0",
                (token_hash,),
            ).fetchone()
            if not row:
                return None
            self.connection.execute("UPDATE devices SET last_seen=? WHERE id=?", (now, row["id"]))
        return {"device_id": row["id"], "profile_id": row["profile_id"], "device_name": row["name"] or ""}

    def revoke_device_token(self, token: str) -> bool:
        with self.lock, self.connection:
            changed = self.connection.execute(
                "UPDATE devices SET revoked=1 WHERE token_hash=? AND revoked=0",
                (self.hash_token(token),),
            ).rowcount
        return bool(changed)

    def device_count(self) -> int:
        with self.lock:
            row = self.connection.execute(
                "SELECT COUNT(*) AS count FROM devices WHERE revoked=0"
            ).fetchone()
        return int(row["count"]) if row else 0

    def add_turn(self, profile_id: str, user_text: str, assistant_text: str) -> str:
        self.ensure_profile(profile_id)
        turn_id = uuid.uuid4().hex
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO turns VALUES(?, ?, ?, ?, ?)",
                (turn_id, profile_id, user_text.strip(), assistant_text.strip(), _now()),
            )
            self.connection.execute(
                "DELETE FROM turns WHERE profile_id=? AND id NOT IN "
                "(SELECT id FROM turns WHERE profile_id=? ORDER BY created_at DESC LIMIT ?)",
                (profile_id, profile_id, self.max_turns),
            )
        return turn_id

    def recent_turns(self, profile_id: str) -> list[dict[str, str]]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT user_text, assistant_text FROM turns WHERE profile_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (profile_id, self.max_turns),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def add_memory(self, profile_id: str, content: str) -> dict[str, str] | None:
        content = " ".join(content.split()).strip()[:500]
        normalized = content.casefold()
        if not content:
            return None
        self.ensure_profile(profile_id)
        now = _now()
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO memories(id, profile_id, content, normalized, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?) ON CONFLICT(profile_id, normalized) "
                "DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at",
                (uuid.uuid4().hex, profile_id, content, normalized, now, now),
            )
            self.connection.execute(
                "DELETE FROM memories WHERE profile_id=? AND id NOT IN "
                "(SELECT id FROM memories WHERE profile_id=? ORDER BY updated_at DESC LIMIT ?)",
                (profile_id, profile_id, self.max_memories),
            )
            row = self.connection.execute(
                "SELECT id, content FROM memories WHERE profile_id=? AND normalized=?",
                (profile_id, normalized),
            ).fetchone()
        return dict(row) if row else None

    def memories(self, profile_id: str, *, query: str = "", limit: int = 12) -> list[dict[str, str]]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT id, content, updated_at FROM memories WHERE profile_id=? ORDER BY updated_at DESC",
                (profile_id,),
            ).fetchall()
        query_words = set(WORD.findall(query.casefold()))
        ranked = sorted(
            rows,
            key=lambda row: len(query_words & set(WORD.findall(row["content"].casefold()))),
            reverse=True,
        )
        return [{"id": row["id"], "content": row["content"]} for row in ranked[:limit]]

    def delete_memory(self, profile_id: str, memory_id: str) -> bool:
        with self.lock, self.connection:
            changed = self.connection.execute(
                "DELETE FROM memories WHERE profile_id=? AND id=?", (profile_id, memory_id)
            ).rowcount
        return bool(changed)

    def clear_memories(self, profile_id: str) -> None:
        with self.lock, self.connection:
            self.connection.execute("DELETE FROM memories WHERE profile_id=?", (profile_id,))

    def clear_turns(self, profile_id: str) -> None:
        with self.lock, self.connection:
            self.connection.execute("DELETE FROM turns WHERE profile_id=?", (profile_id,))

    def close(self) -> None:
        with self.lock:
            self.connection.close()
