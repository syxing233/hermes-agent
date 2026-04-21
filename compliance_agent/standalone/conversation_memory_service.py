from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Protocol
from uuid import uuid4

from compliance_agent.models.schemas import ChatMessage, ChatRole


def _utcnow() -> datetime:
    return datetime.utcnow()


def _to_iso(value: datetime) -> str:
    return value.isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass(frozen=True)
class ConversationRecord:
    conversation_id: str
    user: str
    title: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime


@dataclass(frozen=True)
class ConversationMessageRecord:
    message_id: str
    conversation_id: str
    role: ChatRole
    content: str
    attachments: list[dict[str, Any]]
    created_at: datetime


class ConversationRepository(Protocol):
    def create_conversation(self, *, user: str, title: str | None = None) -> ConversationRecord: ...

    def list_conversations(
        self,
        *,
        user: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationRecord]: ...

    def get_conversation(
        self,
        *,
        conversation_id: str,
        user: str,
    ) -> ConversationRecord | None: ...

    def soft_delete_conversation(self, *, conversation_id: str, user: str) -> bool: ...


class MessageRepository(Protocol):
    def add_message(
        self,
        *,
        conversation_id: str,
        user: str,
        role: ChatRole,
        content: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> ConversationMessageRecord: ...

    def list_messages(
        self,
        *,
        conversation_id: str,
        user: str,
        limit: int = 200,
    ) -> list[ConversationMessageRecord]: ...

    def list_recent_chat_messages(
        self,
        *,
        conversation_id: str,
        user: str,
        max_messages: int,
        max_chars: int,
    ) -> list[ChatMessage]: ...


class ConversationStore(ConversationRepository, MessageRepository, Protocol):
    """Marker protocol for a combined conversation + message store."""


class SqliteConversationStore(ConversationStore):
    def __init__(self, db_path: str):
        self.db_path = Path(db_path).expanduser()
        if not self.db_path.is_absolute():
            self.db_path = (Path.cwd() / self.db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def create_conversation(self, *, user: str, title: str | None = None) -> ConversationRecord:
        normalized_user = (user or "anonymous").strip() or "anonymous"
        normalized_title = (title or "").strip() or "新会话"
        now = _utcnow()
        conversation_id = str(uuid4())

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversations (id, user, title, created_at, updated_at, last_message_at, deleted_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (conversation_id, normalized_user, normalized_title, _to_iso(now), _to_iso(now), _to_iso(now)),
            )
            conn.commit()

        return ConversationRecord(
            conversation_id=conversation_id,
            user=normalized_user,
            title=normalized_title,
            created_at=now,
            updated_at=now,
            last_message_at=now,
        )

    def list_conversations(
        self,
        *,
        user: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationRecord]:
        normalized_user = (user or "anonymous").strip() or "anonymous"
        safe_limit = max(1, min(int(limit), 200))
        safe_offset = max(0, int(offset))

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user, title, created_at, updated_at, last_message_at
                FROM conversations
                WHERE user = ? AND deleted_at IS NULL
                ORDER BY last_message_at DESC, updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (normalized_user, safe_limit, safe_offset),
            ).fetchall()

        return [self._to_conversation_record(row) for row in rows]

    def get_conversation(
        self,
        *,
        conversation_id: str,
        user: str,
    ) -> ConversationRecord | None:
        normalized_user = (user or "anonymous").strip() or "anonymous"
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, user, title, created_at, updated_at, last_message_at
                FROM conversations
                WHERE id = ? AND user = ? AND deleted_at IS NULL
                """,
                (conversation_id, normalized_user),
            ).fetchone()
        if row is None:
            return None
        return self._to_conversation_record(row)

    def soft_delete_conversation(self, *, conversation_id: str, user: str) -> bool:
        normalized_user = (user or "anonymous").strip() or "anonymous"
        now = _to_iso(_utcnow())
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE conversations
                SET deleted_at = ?, updated_at = ?
                WHERE id = ? AND user = ? AND deleted_at IS NULL
                """,
                (now, now, conversation_id, normalized_user),
            )
            conn.commit()
            return cur.rowcount > 0

    def add_message(
        self,
        *,
        conversation_id: str,
        user: str,
        role: ChatRole,
        content: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> ConversationMessageRecord:
        normalized_user = (user or "anonymous").strip() or "anonymous"
        normalized_content = (content or "").strip()
        if not normalized_content:
            raise ValueError("message content 不能为空")
        message_id = str(uuid4())
        now = _utcnow()
        safe_attachments = attachments or []
        attachments_json = json.dumps(safe_attachments, ensure_ascii=False)

        with self._lock, self._connect() as conn:
            row = self._ensure_conversation_row(
                conn=conn,
                conversation_id=conversation_id,
                user=normalized_user,
            )
            if row is None:
                raise ValueError("conversation 不存在或无权限")

            conn.execute(
                """
                INSERT INTO conversation_messages (id, conversation_id, role, content, attachments_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (message_id, conversation_id, role.value, normalized_content, attachments_json, _to_iso(now)),
            )

            conn.execute(
                """
                UPDATE conversations
                SET updated_at = ?, last_message_at = ?
                WHERE id = ? AND user = ? AND deleted_at IS NULL
                """,
                (_to_iso(now), _to_iso(now), conversation_id, normalized_user),
            )

            # Auto-title the conversation from first user message.
            if role == ChatRole.USER and (row["title"] or "").strip() in {"", "新会话"}:
                total_row = conn.execute(
                    "SELECT COUNT(1) AS total FROM conversation_messages WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()
                total = int(total_row["total"] if total_row else 0)
                if total == 1:
                    conn.execute(
                        "UPDATE conversations SET title = ? WHERE id = ?",
                        (_derive_title_from_content(normalized_content), conversation_id),
                    )
            conn.commit()

        return ConversationMessageRecord(
            message_id=message_id,
            conversation_id=conversation_id,
            role=role,
            content=normalized_content,
            attachments=safe_attachments,
            created_at=now,
        )

    def list_messages(
        self,
        *,
        conversation_id: str,
        user: str,
        limit: int = 200,
    ) -> list[ConversationMessageRecord]:
        normalized_user = (user or "anonymous").strip() or "anonymous"
        safe_limit = max(1, min(int(limit), 500))
        with self._connect() as conn:
            row = self._ensure_conversation_row(conn=conn, conversation_id=conversation_id, user=normalized_user)
            if row is None:
                raise ValueError("conversation 不存在或无权限")

            rows = conn.execute(
                """
                SELECT id, conversation_id, role, content, attachments_json, created_at
                FROM conversation_messages
                WHERE conversation_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (conversation_id, safe_limit),
            ).fetchall()
        # Return chronological order.
        return [self._to_message_record(row) for row in reversed(rows)]

    def list_recent_chat_messages(
        self,
        *,
        conversation_id: str,
        user: str,
        max_messages: int,
        max_chars: int,
    ) -> list[ChatMessage]:
        safe_max_messages = max(1, min(int(max_messages), 100))
        safe_max_chars = max(1000, int(max_chars))
        records = self.list_messages(
            conversation_id=conversation_id,
            user=user,
            limit=max(safe_max_messages * 3, safe_max_messages),
        )
        recent_records = records[-safe_max_messages:]

        total_chars = sum(len(item.content) for item in recent_records)
        while len(recent_records) > 1 and total_chars > safe_max_chars:
            removed = recent_records.pop(0)
            total_chars -= len(removed.content)

        output: list[ChatMessage] = []
        for item in recent_records:
            output.append(ChatMessage(role=item.role, content=item.content))
        return output

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    user TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '新会话',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_message_at TEXT NOT NULL,
                    deleted_at TEXT NULL
                );

                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    attachments_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_conversations_user_last_message
                    ON conversations (user, last_message_at DESC);

                CREATE INDEX IF NOT EXISTS idx_conversation_messages_conversation_created
                    ON conversation_messages (conversation_id, created_at ASC);
                """
            )
            conn.commit()

    def _ensure_conversation_row(
        self,
        *,
        conn: sqlite3.Connection,
        conversation_id: str,
        user: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT id, user, title, created_at, updated_at, last_message_at
            FROM conversations
            WHERE id = ? AND user = ? AND deleted_at IS NULL
            """,
            (conversation_id, user),
        ).fetchone()

    @staticmethod
    def _to_conversation_record(row: sqlite3.Row) -> ConversationRecord:
        return ConversationRecord(
            conversation_id=row["id"],
            user=row["user"],
            title=row["title"] or "新会话",
            created_at=_from_iso(row["created_at"]),
            updated_at=_from_iso(row["updated_at"]),
            last_message_at=_from_iso(row["last_message_at"]),
        )

    @staticmethod
    def _to_message_record(row: sqlite3.Row) -> ConversationMessageRecord:
        raw_role = str(row["role"] or "").strip().lower()
        role = ChatRole(raw_role) if raw_role in {item.value for item in ChatRole} else ChatRole.USER
        attachments_raw = row["attachments_json"] or "[]"
        try:
            attachments = json.loads(attachments_raw)
            if not isinstance(attachments, list):
                attachments = []
        except json.JSONDecodeError:
            attachments = []
        return ConversationMessageRecord(
            message_id=row["id"],
            conversation_id=row["conversation_id"],
            role=role,
            content=row["content"] or "",
            attachments=attachments,
            created_at=_from_iso(row["created_at"]),
        )


class ConversationMemoryService:
    def __init__(
        self,
        store: ConversationStore,
        *,
        default_context_messages: int = 16,
        default_context_chars: int = 12000,
    ):
        self.store = store
        self.default_context_messages = max(1, int(default_context_messages))
        self.default_context_chars = max(1000, int(default_context_chars))

    def create_conversation(self, *, user: str, title: str | None = None) -> ConversationRecord:
        return self.store.create_conversation(user=user, title=title)

    def list_conversations(self, *, user: str, limit: int = 50, offset: int = 0) -> list[ConversationRecord]:
        return self.store.list_conversations(user=user, limit=limit, offset=offset)

    def list_messages(
        self,
        *,
        conversation_id: str,
        user: str,
        limit: int = 200,
    ) -> list[ConversationMessageRecord]:
        return self.store.list_messages(conversation_id=conversation_id, user=user, limit=limit)

    def delete_conversation(self, *, conversation_id: str, user: str) -> bool:
        return self.store.soft_delete_conversation(conversation_id=conversation_id, user=user)

    def ensure_conversation(self, *, conversation_id: str, user: str) -> ConversationRecord:
        record = self.store.get_conversation(conversation_id=conversation_id, user=user)
        if record is None:
            raise ValueError("conversation 不存在或无权限")
        return record

    def load_chat_context(
        self,
        *,
        conversation_id: str,
        user: str,
        max_messages: int | None = None,
        max_chars: int | None = None,
    ) -> list[ChatMessage]:
        self.ensure_conversation(conversation_id=conversation_id, user=user)
        return self.store.list_recent_chat_messages(
            conversation_id=conversation_id,
            user=user,
            max_messages=max_messages or self.default_context_messages,
            max_chars=max_chars or self.default_context_chars,
        )

    def append_message(
        self,
        *,
        conversation_id: str,
        user: str,
        role: ChatRole,
        content: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> ConversationMessageRecord:
        return self.store.add_message(
            conversation_id=conversation_id,
            user=user,
            role=role,
            content=content,
            attachments=attachments,
        )

    def append_turn(
        self,
        *,
        conversation_id: str,
        user: str,
        user_content: str,
        assistant_content: str,
        user_attachments: list[dict[str, Any]] | None = None,
        assistant_attachments: list[dict[str, Any]] | None = None,
    ) -> None:
        normalized_user_content = (user_content or "").strip()
        normalized_assistant_content = (assistant_content or "").strip()
        if normalized_user_content:
            self.append_message(
                conversation_id=conversation_id,
                user=user,
                role=ChatRole.USER,
                content=normalized_user_content,
                attachments=user_attachments,
            )
        if normalized_assistant_content:
            self.append_message(
                conversation_id=conversation_id,
                user=user,
                role=ChatRole.ASSISTANT,
                content=normalized_assistant_content,
                attachments=assistant_attachments,
            )


def _derive_title_from_content(content: str, max_len: int = 24) -> str:
    text = " ".join((content or "").split())
    if not text:
        return "新会话"
    return text[:max_len]
