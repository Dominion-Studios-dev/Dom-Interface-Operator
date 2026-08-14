"""Unified database layer for Dom Interface.

Replaces: dom_ram.json, dom_hdd.json, email_filters_memory.json, survival.db
Uses libsql with optional Turso edge sync via sync_url + auth_token.

All operations work fully offline (local libsql replica).
When TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are set, writes sync to
the cloud Turso primary in the background — zero-latency local reads.

LIBSQL FALLBACK:
If the native `libsql` package is not importable in the active interpreter
(common in minimal containers, fresh machines, or very new Python versions
without a pip wheel), this module transparently falls back to the standard
library `sqlite3` with an API-compatible connection wrapper. Every feature
works identically; the ONLY difference is that Turso cloud sync is disabled
until `libsql` is installed (pip install libsql-client). A single warning
is printed to stderr so it never pollutes the C++ bridge stdout.
"""

import os
import json
import sys
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

try:
    import libsql
    HAS_LIBSQL = True
except ImportError:
    HAS_LIBSQL = False

    import sqlite3

    class _CompatConn:
        """Wraps stdlib sqlite3.Connection to match the libsql client API used here.

        Exposes execute/commit/close plus a no-op sync() so callers (and the
        C++ bridge) never need to know libsql is unavailable.
        """

        def __init__(self, path: str):
            self._conn = sqlite3.connect(path)
            self._conn.row_factory = sqlite3.Row

        def execute(self, sql, params=()):
            return self._conn.execute(sql, params)

        def commit(self):
            self._conn.commit()

        def close(self):
            self._conn.close()

        def sync(self):
            return None

    def _connect(path: str, **kwargs):
        return _CompatConn(path)

    def _warn_libsql_missing():
        global _SYNC_WARNED
        if not _SYNC_WARNED:
            _SYNC_WARNED = True
            print(
                "[db] libsql package not found — running on stdlib SQLite3. "
                "Turso cloud sync disabled until 'libsql-client' is installed.",
                file=sys.stderr,
            )

else:

    def _connect(path: str, **kwargs):
        return libsql.connect(path, **kwargs)

# ── Local .env loader (fallback if env vars not already set) ──────────
def _load_dotenv():
    """Load .env file from project root into os.environ without python-dotenv dependency."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(base, ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("\"'").strip()
            if key and key not in os.environ:
                os.environ[key] = val

_load_dotenv()

def _clean_env(val: str) -> str:
    """Strip whitespace, surrounding quotes, and trailing newlines."""
    return val.strip().strip("\"'").strip()

TURSO_URL = _clean_env(os.environ.get("TURSO_DATABASE_URL", ""))
TURSO_TOKEN = _clean_env(os.environ.get("TURSO_AUTH_TOKEN", ""))
MAX_RAM = 12

_DB_PATH: Optional[str] = None

def set_db_path(path: str):
    global _DB_PATH
    _DB_PATH = path

def _resolve_path() -> str:
    if _DB_PATH is not None:
        return _DB_PATH
    env_path = os.environ.get("DOM_DB_PATH", "")
    if env_path:
        return env_path
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "dom.db")

_SYNC_WARNED: bool = False

def get_conn():
    global _SYNC_WARNED
    db_path = _resolve_path()
    if TURSO_URL and TURSO_TOKEN:
        if not HAS_LIBSQL:
            _warn_libsql_missing()
            return _connect(db_path)
        try:
            conn = _connect(db_path, sync_url=TURSO_URL, auth_token=TURSO_TOKEN)
            conn.sync()
            return conn
        except Exception as e:
            if not _SYNC_WARNED:
                _SYNC_WARNED = True
                msg = str(e).strip()
                if "401" in msg or "Unauthorized" in msg or "auth" in msg.lower():
                    print("[db] Turso credentials invalid or expired. Running local-only.", file=sys.stderr)
                else:
                    print(f"[db] Turso sync unavailable: {msg}. Running local-only.", file=sys.stderr)
    return _connect(db_path)

def _sync(conn):
    if not HAS_LIBSQL:
        return
    if TURSO_URL and TURSO_TOKEN:
        try:
            conn.sync()
        except Exception:
            pass

def init_schema():
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session TEXT NOT NULL DEFAULT 'default',
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session)")
    conn.execute("""CREATE TABLE IF NOT EXISTS kv_store (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS email_filters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        sender TEXT NOT NULL UNIQUE,
        created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ef_type ON email_filters(type)")
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL
    )""")
    try:
        conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
            title, content, category, content='knowledge', content_rowid='id', tokenize='porter unicode61'
        )""")
    except Exception:
        pass
    conn.execute("""CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        category TEXT NOT NULL,
        content TEXT NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_cat ON memories(category)")
    conn.execute("""CREATE TABLE IF NOT EXISTS snippets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        tag TEXT NOT NULL DEFAULT '',
        content TEXT NOT NULL,
        created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snippets_tag ON snippets(tag)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snippets_name ON snippets(name)")
    conn.commit()
    _sync(conn)
    conn.close()

# ── RAM (conversation buffer) ────────────────────────────────────────────────

def ram_push(role: str, content: str, session: str = "default"):
    conn = get_conn()
    now = int(datetime.now(timezone.utc).timestamp())
    conn.execute(
        "INSERT INTO conversations (session, role, content, created_at) VALUES (?, ?, ?, ?)",
        (session, role, content, now)
    )
    conn.execute("""DELETE FROM conversations WHERE id IN (
        SELECT id FROM conversations WHERE session = ? ORDER BY id DESC LIMIT -1 OFFSET ?
    )""", (session, MAX_RAM))
    conn.commit()
    _sync(conn)
    conn.close()

def ram_load(session: str = "default") -> List[Dict[str, str]]:
    conn = get_conn()
    cursor = conn.execute(
        "SELECT role, content FROM conversations WHERE session = ? ORDER BY id ASC", (session,)
    )
    rows = [{"role": row[0], "content": row[1]} for row in cursor.fetchall()]
    conn.close()
    return rows

def ram_clear(session: str = "default"):
    conn = get_conn()
    conn.execute("DELETE FROM conversations WHERE session = ?", (session,))
    conn.commit()
    _sync(conn)
    conn.close()

def ram_count(session: str = "default") -> int:
    conn = get_conn()
    cursor = conn.execute("SELECT COUNT(*) FROM conversations WHERE session = ?", (session,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

# ── HDD (key-value store) ────────────────────────────────────────────────────

def hdd_set(key: str, value: str):
    conn = get_conn()
    now = int(datetime.now(timezone.utc).timestamp())
    conn.execute(
        "INSERT OR REPLACE INTO kv_store (key, value, updated_at) VALUES (?, ?, ?)",
        (key, value, now)
    )
    conn.commit()
    _sync(conn)
    conn.close()

def hdd_get(key: str) -> Optional[str]:
    conn = get_conn()
    cursor = conn.execute("SELECT value FROM kv_store WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def hdd_get_all() -> Dict[str, str]:
    conn = get_conn()
    cursor = conn.execute("SELECT key, value FROM kv_store")
    result = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return result

def hdd_delete(key: str):
    conn = get_conn()
    conn.execute("DELETE FROM kv_store WHERE key = ?", (key,))
    conn.commit()
    _sync(conn)
    conn.close()

# ── Email Filters ────────────────────────────────────────────────────────────

def email_filter_add(type_: str, sender: str):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO email_filters (type, sender) VALUES (?, ?)",
            (type_, sender.lower())
        )
        conn.commit()
        _sync(conn)
    except Exception:
        pass
    conn.close()

def email_filter_is_known(sender: str) -> Optional[str]:
    conn = get_conn()
    cursor = conn.execute(
        "SELECT type FROM email_filters WHERE sender = ?", (sender.lower(),)
    )
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def email_filter_load_all() -> Dict[str, List[str]]:
    conn = get_conn()
    cursor = conn.execute("SELECT type, sender FROM email_filters ORDER BY id")
    result: Dict[str, List[str]] = {"scam_senders": [], "promo_senders": []}
    for row in cursor.fetchall():
        key = "scam_senders" if row[0] == "scam" else "promo_senders"
        result[key].append(row[1])
    conn.close()
    return result

# ── Knowledge Base (FTS5) ────────────────────────────────────────────────────

def knowledge_insert(category: str, title: str, content: str) -> int:
    conn = get_conn()
    conn.execute(
        "INSERT INTO knowledge (category, title, content) VALUES (?, ?, ?)",
        (category, title, content)
    )
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO knowledge_fts (rowid, title, content, category) VALUES (?, ?, ?, ?)",
        (row_id, title, content, category)
    )
    conn.commit()
    _sync(conn)
    conn.close()
    return row_id

def knowledge_search(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    conn = get_conn()
    try:
        cursor = conn.execute(
            "SELECT title, content, rank FROM knowledge_fts "
            "WHERE knowledge_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit)
        )
        results = [{"title": row[0], "content": row[1], "rank": row[2]} for row in cursor.fetchall()]
    except Exception:
        results = []
    conn.close()
    return results

def knowledge_get_entry(title: str) -> Optional[Dict[str, str]]:
    conn = get_conn()
    cursor = conn.execute("SELECT title, content FROM knowledge WHERE title = ?", (title,))
    row = cursor.fetchone()
    conn.close()
    return {"title": row[0], "content": row[1]} if row else None

def knowledge_list_categories() -> List[str]:
    conn = get_conn()
    cursor = conn.execute("SELECT DISTINCT category FROM knowledge ORDER BY category")
    result = [row[0] for row in cursor.fetchall()]
    conn.close()
    return result

def knowledge_count() -> int:
    conn = get_conn()
    cursor = conn.execute("SELECT COUNT(*) FROM knowledge")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def knowledge_rebuild_fts():
    conn = get_conn()
    conn.execute("DELETE FROM knowledge_fts")
    conn.execute("""INSERT INTO knowledge_fts (rowid, title, content, category)
        SELECT id, title, content, category FROM knowledge""")
    conn.commit()
    _sync(conn)
    conn.close()

def knowledge_clear():
    conn = get_conn()
    conn.execute("DELETE FROM knowledge")
    conn.execute("DELETE FROM knowledge_fts")
    conn.commit()
    _sync(conn)
    conn.close()

# ── Long-term Memories ───────────────────────────────────────────────────────

def memory_save(category: str, content: str):
    timestamp = datetime.now(timezone.utc).isoformat()
    conn = get_conn()
    conn.execute(
        "INSERT INTO memories (timestamp, category, content) VALUES (?, ?, ?)",
        (timestamp, category, content)
    )
    conn.commit()
    _sync(conn)
    conn.close()

def memory_search(query: str, limit: int = 3) -> List[Dict[str, str]]:
    conn = get_conn()
    cursor = conn.execute(
        "SELECT timestamp, category, content FROM memories "
        "WHERE content LIKE ? OR category LIKE ? ORDER BY id DESC LIMIT ?",
        (f"%{query}%", f"%{query}%", limit)
    )
    results = [
        {"timestamp": row[0], "category": row[1], "content": row[2]}
        for row in cursor.fetchall()
    ]
    conn.close()
    return results

# ── Code Vault (code snippets) ───────────────────────────────────────────────

def snippet_save(name: str, content: str, tag: str = "") -> Optional[int]:
    """Save a code snippet. Returns row id, or None if name already exists."""
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO snippets (name, tag, content) VALUES (?, ?, ?)",
            (name.strip(), tag.strip(), content)
        )
        row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        _sync(conn)
        conn.close()
        return row_id
    except Exception:
        conn.close()
        return None

def snippet_get(name: str) -> Optional[Dict[str, Any]]:
    """Fetch a snippet by exact name."""
    conn = get_conn()
    cursor = conn.execute(
        "SELECT name, tag, content, created_at FROM snippets WHERE name = ?",
        (name.strip(),)
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {"name": row[0], "tag": row[1], "content": row[2], "created_at": row[3]}

def snippet_search(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Keyword search across name, tag, and content (LIKE)."""
    conn = get_conn()
    like = f"%{query.strip()}%"
    cursor = conn.execute(
        "SELECT name, tag, content, created_at FROM snippets "
        "WHERE name LIKE ? OR tag LIKE ? OR content LIKE ? "
        "ORDER BY id DESC LIMIT ?",
        (like, like, like, limit)
    )
    results = [
        {"name": row[0], "tag": row[1], "content": row[2], "created_at": row[3]}
        for row in cursor.fetchall()
    ]
    conn.close()
    return results

def snippet_list(limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_conn()
    cursor = conn.execute(
        "SELECT name, tag, created_at FROM snippets ORDER BY id DESC LIMIT ?",
        (limit,)
    )
    results = [
        {"name": row[0], "tag": row[1], "created_at": row[2]}
        for row in cursor.fetchall()
    ]
    conn.close()
    return results

def snippet_tags() -> List[str]:
    conn = get_conn()
    cursor = conn.execute(
        "SELECT DISTINCT tag FROM snippets WHERE tag != '' ORDER BY tag"
    )
    results = [row[0] for row in cursor.fetchall()]
    conn.close()
    return results

def snippet_delete(name: str) -> bool:
    conn = get_conn()
    cursor = conn.execute("DELETE FROM snippets WHERE name = ?", (name.strip(),))
    conn.commit()
    _sync(conn)
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted

def snippet_count() -> int:
    conn = get_conn()
    cursor = conn.execute("SELECT COUNT(*) FROM snippets")
    count = cursor.fetchone()[0]
    conn.close()
    return count

# ── Migration Helpers ────────────────────────────────────────────────────────

def migrate_from_json(hdd_path: str = None, ram_path: str = None, session: str = "default"):
    if hdd_path and os.path.exists(hdd_path):
        try:
            with open(hdd_path) as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    hdd_set(k, str(v) if not isinstance(v, str) else v)
        except Exception:
            pass
    if ram_path and os.path.exists(ram_path):
        try:
            with open(ram_path) as f:
                data = json.load(f)
            if isinstance(data, list):
                for msg in data:
                    if isinstance(msg, dict) and "role" in msg and "content" in msg:
                        ram_push(msg["role"], msg["content"], session)
        except Exception:
            pass

try:
    init_schema()
except Exception:
    pass
