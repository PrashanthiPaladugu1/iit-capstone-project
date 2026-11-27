"""chat_store: conversations and their messages in SQLite, so the sidebar history survives a refresh and a restart.

    store = ChatStore()                       # file from config/paths.json (chats_db)
    cid = store.new_conversation()
    store.add_message(cid, "user", "RSI of TCS?")
    store.list_conversations(query="rsi")     # newest first; empty conversations are not listed

Nothing is ever deleted here (no-delete rule): the sidebar has no delete button.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

import config

TITLE_LENGTH = 48
DEFAULT_TITLE = "New chat"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations(
    id TEXT PRIMARY KEY, title TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS messages(
    id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL, text TEXT NOT NULL, trace TEXT NOT NULL DEFAULT '[]', budget TEXT NOT NULL DEFAULT '{}',
    route TEXT NOT NULL DEFAULT '', stopped TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated);
"""


def group_label(timestamp: float, now: float | None = None) -> str:
    """Sidebar heading for a conversation: Today, Yesterday, Previous 7 days or Older (calendar days, local time)."""
    now = time.time() if now is None else now
    days = (time.localtime(now).tm_yday + 366 * time.localtime(now).tm_year
            - time.localtime(timestamp).tm_yday - 366 * time.localtime(timestamp).tm_year)
    if days <= 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if days <= 7:
        return "Previous 7 days"
    return "Older"


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= TITLE_LENGTH else text[:TITLE_LENGTH - 3].rstrip() + "..."


def _like(text: str) -> str:
    """A LIKE pattern that matches the text literally: % and _ are not wildcards."""
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class ChatStore:
    def __init__(self, db: Path | str | None = None):
        self.db = Path(db) if db else config.chats_db()
        self.db.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as con, con:
            con.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        return con

    def new_conversation(self) -> str:
        cid, now = uuid.uuid4().hex[:12], time.time()
        with closing(self._connect()) as con, con:
            con.execute("INSERT INTO conversations(id, title, created, updated) VALUES(?,?,?,?)",
                        (cid, DEFAULT_TITLE, now, now))
        return cid

    def get(self, cid: str) -> dict | None:
        with closing(self._connect()) as con:
            row = con.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
        return dict(row) if row else None

    def add_message(self, cid: str, role: str, text: str, *, trace: list | None = None, budget: dict | None = None,
                    route: str = "", stopped: str = "") -> None:
        now = time.time()
        with closing(self._connect()) as con, con:
            conv = con.execute("SELECT title FROM conversations WHERE id=?", (cid,)).fetchone()
            if conv is None:
                raise KeyError(f"unknown conversation: {cid}")
            first = con.execute("SELECT COUNT(*) FROM messages WHERE conversation_id=? AND role='user'",
                                (cid,)).fetchone()[0] == 0
            con.execute("INSERT INTO messages(conversation_id, role, text, trace, budget, route, stopped, created) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (cid, role, text, json.dumps(trace or []), json.dumps(budget or {}), route, stopped, now))
            if role == "user" and first and conv["title"] == DEFAULT_TITLE:
                con.execute("UPDATE conversations SET title=?, updated=? WHERE id=?", (_short(text), now, cid))
            else:
                con.execute("UPDATE conversations SET updated=? WHERE id=?", (now, cid))

    def messages(self, cid: str) -> list[dict]:
        with closing(self._connect()) as con:
            rows = con.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (cid,)).fetchall()
        return [{"role": r["role"], "text": r["text"], "trace": json.loads(r["trace"]), "budget": json.loads(r["budget"]),
                 "route": r["route"], "stopped": r["stopped"], "created": r["created"]} for r in rows]

    def list_conversations(self, query: str = "", limit: int = 200) -> list[dict]:
        """Newest first. Conversations with no message are left out. `query` matches titles and message text."""
        sql = ("SELECT c.* FROM conversations c WHERE EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id=c.id)")
        args: list = []
        if query.strip():
            sql += (" AND (c.title LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id=c.id "
                    "AND m.text LIKE ? ESCAPE '\\'))")
            args += [_like(query.strip())] * 2
        sql += " ORDER BY c.updated DESC LIMIT ?"
        with closing(self._connect()) as con:
            return [dict(r) for r in con.execute(sql, args + [limit]).fetchall()]
