"""Durable app state: SQLite locally, Postgres when DATABASE_URL is set."""

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
_lock = threading.RLock()
_ready = False


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex


@contextmanager
def connection():
    if DATABASE_URL:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as con:
            yield con
    else:
        con = sqlite3.connect(ROOT / "app_state.sqlite3", timeout=30)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()


def sql(con, query, params=()):
    if DATABASE_URL:
        query = query.replace("?", "%s")
    return con.execute(query, params)


def rows(cursor):
    return [dict(row) for row in cursor.fetchall()]


def init():
    global _ready
    if _ready:
        return
    with _lock:
        if _ready:
            return
        blob = "BYTEA" if DATABASE_URL else "BLOB"
        with connection() as con:
            sql(con, "CREATE TABLE IF NOT EXISTS chats (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
            sql(con, "CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, activity_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL, usage_json TEXT NOT NULL DEFAULT '{}')")
            if DATABASE_URL:
                columns = {row["column_name"] for row in rows(sql(con, "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='messages'"))}
            else:
                columns = {row["name"] for row in rows(sql(con, "PRAGMA table_info(messages)"))}
            if "usage_json" not in columns:
                sql(con, "ALTER TABLE messages ADD COLUMN usage_json TEXT NOT NULL DEFAULT '{}'")
            sql(con, "CREATE INDEX IF NOT EXISTS messages_chat_idx ON messages(chat_id, created_at)")
            sql(con, "CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, category TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, scope TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
            sql(con, "CREATE UNIQUE INDEX IF NOT EXISTS memories_key_idx ON memories(category, key, scope)")
            sql(con, f"CREATE TABLE IF NOT EXISTS datasets (id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, filename TEXT NOT NULL, content {blob} NOT NULL, created_at TEXT NOT NULL)")
            sql(con, f"CREATE TABLE IF NOT EXISTS charts (id TEXT PRIMARY KEY, content {blob} NOT NULL, created_at TEXT NOT NULL)")
            sql(con, "CREATE TABLE IF NOT EXISTS upload_sessions (id TEXT PRIMARY KEY, filename TEXT NOT NULL, size_bytes INTEGER NOT NULL, created_at TEXT NOT NULL)")
            sql(con, f"CREATE TABLE IF NOT EXISTS upload_chunks (upload_id TEXT NOT NULL, seq INTEGER NOT NULL, content {blob} NOT NULL, PRIMARY KEY (upload_id, seq))")
            sql(con, "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        _ready = True
        with connection() as con:
            imported = sql(con, "SELECT value FROM meta WHERE key='legacy_memory_imported'").fetchone()
        if not imported:
            _import_legacy_memory()
            with connection() as con:
                sql(con, "INSERT INTO meta VALUES ('legacy_memory_imported', '1') ON CONFLICT (key) DO NOTHING")


def _import_legacy_memory():
    legacy = ROOT / "agent_memory.json"
    if not legacy.exists():
        return
    try:
        data = json.loads(legacy.read_text(encoding="utf-8"))
        for category in ("definitions", "preferences"):
            for key, value in data.get(category, {}).items():
                upsert_memory(category[:-1] if category == "preferences" else "definition", key, str(value))
    except (OSError, ValueError, TypeError):
        pass


def list_chats():
    init()
    with connection() as con:
        return rows(sql(con, "SELECT * FROM chats ORDER BY updated_at DESC"))


def create_chat(title="New analysis"):
    init()
    item = {"id": uid(), "title": title[:100], "created_at": now(), "updated_at": now()}
    with connection() as con:
        sql(con, "INSERT INTO chats VALUES (?, ?, ?, ?)", tuple(item.values()))
    return item


def get_chat(chat_id):
    init()
    with connection() as con:
        chat = sql(con, "SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not chat:
            return None
        messages = rows(sql(con, "SELECT * FROM messages WHERE chat_id=? ORDER BY created_at, id", (chat_id,)))
    for message in messages:
        message["activity"] = json.loads(message.pop("activity_json"))
        message["usage"] = json.loads(message.pop("usage_json"))
    return {**dict(chat), "messages": messages}


def rename_chat(chat_id, title):
    init()
    with connection() as con:
        return sql(con, "UPDATE chats SET title=?, updated_at=? WHERE id=?", (title[:100], now(), chat_id)).rowcount > 0


def delete_chat(chat_id):
    init()
    with connection() as con:
        sql(con, "DELETE FROM messages WHERE chat_id=?", (chat_id,))
        return sql(con, "DELETE FROM chats WHERE id=?", (chat_id,)).rowcount > 0


def add_message(chat_id, role, content, activity=None, usage=None):
    init()
    item = {"id": uid(), "chat_id": chat_id, "role": role, "content": content,
            "activity_json": json.dumps(activity or []), "created_at": now(), "usage_json": json.dumps(usage or {})}
    with connection() as con:
        sql(con, "INSERT INTO messages (id, chat_id, role, content, activity_json, created_at, usage_json) VALUES (?, ?, ?, ?, ?, ?, ?)", tuple(item.values()))
        sql(con, "UPDATE chats SET updated_at=? WHERE id=?", (now(), chat_id))
    item["activity"] = activity or []
    item["usage"] = usage or {}
    item.pop("activity_json")
    item.pop("usage_json")
    return item


def update_message_usage(message_id, usage):
    init()
    with connection() as con:
        sql(con, "UPDATE messages SET usage_json=? WHERE id=?", (json.dumps(usage), message_id))


def list_memories():
    init()
    with connection() as con:
        return rows(sql(con, "SELECT * FROM memories ORDER BY updated_at DESC"))


def upsert_memory(category, key, value, scope=""):
    init()
    category, key, value, scope = category.strip().lower(), key.strip().lower(), value.strip(), scope.strip().lower()
    if not key or not value:
        raise ValueError("Memory key and value are required")
    with connection() as con:
        existing = sql(con, "SELECT id, created_at FROM memories WHERE category=? AND key=? AND scope=?", (category, key, scope)).fetchone()
        item = {"id": existing["id"] if existing else uid(), "category": category, "key": key,
                "value": value, "scope": scope, "created_at": existing["created_at"] if existing else now(), "updated_at": now()}
        sql(con, "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (category, key, scope) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", tuple(item.values()))
    return item


def update_memory(memory_id, category, key, value, scope=""):
    init()
    with connection() as con:
        return sql(con, "UPDATE memories SET category=?, key=?, value=?, scope=?, updated_at=? WHERE id=?",
                   (category.strip().lower(), key.strip().lower(), value.strip(), scope.strip().lower(), now(), memory_id)).rowcount > 0


def delete_memory(memory_id):
    init()
    with connection() as con:
        return sql(con, "DELETE FROM memories WHERE id=?", (memory_id,)).rowcount > 0


def list_uploads():
    init()
    with connection() as con:
        return rows(sql(con, "SELECT id, name, filename, created_at FROM datasets ORDER BY created_at DESC"))


def save_upload(name, filename, content):
    init()
    item = {"id": uid(), "name": name, "filename": filename, "created_at": now()}
    with connection() as con:
        sql(con, "INSERT INTO datasets VALUES (?, ?, ?, ?, ?)", (item["id"], name, filename, content, item["created_at"]))
    return item


def get_upload(upload_id):
    init()
    with connection() as con:
        row = sql(con, "SELECT * FROM datasets WHERE id=?", (upload_id,)).fetchone()
        return dict(row) if row else None


def delete_upload(upload_id):
    init()
    with connection() as con:
        return sql(con, "DELETE FROM datasets WHERE id=?", (upload_id,)).rowcount > 0


def create_upload_session(filename, size_bytes):
    init()
    item = {"id": uid(), "filename": filename, "size_bytes": size_bytes, "created_at": now()}
    with connection() as con:
        sql(con, "INSERT INTO upload_sessions VALUES (?, ?, ?, ?)", tuple(item.values()))
    return item


def save_upload_chunk(upload_id, seq, content):
    init()
    with connection() as con:
        session = sql(con, "SELECT id FROM upload_sessions WHERE id=?", (upload_id,)).fetchone()
        if not session:
            return False
        sql(con, "INSERT INTO upload_chunks VALUES (?, ?, ?) ON CONFLICT (upload_id, seq) DO UPDATE SET content=excluded.content", (upload_id, seq, content))
    return True


def get_upload_session(upload_id):
    init()
    with connection() as con:
        session = sql(con, "SELECT * FROM upload_sessions WHERE id=?", (upload_id,)).fetchone()
        if not session:
            return None
        chunks = rows(sql(con, "SELECT seq, content FROM upload_chunks WHERE upload_id=? ORDER BY seq", (upload_id,)))
    return {**dict(session), "chunks": chunks}


def delete_upload_session(upload_id):
    init()
    with connection() as con:
        sql(con, "DELETE FROM upload_chunks WHERE upload_id=?", (upload_id,))
        sql(con, "DELETE FROM upload_sessions WHERE id=?", (upload_id,))


def save_chart(content):
    init()
    chart_id = uid()
    with connection() as con:
        sql(con, "INSERT INTO charts VALUES (?, ?, ?)", (chart_id, content, now()))
    return chart_id


def get_chart(chart_id):
    init()
    with connection() as con:
        row = sql(con, "SELECT content FROM charts WHERE id=?", (chart_id,)).fetchone()
        return bytes(row["content"]) if row else None
