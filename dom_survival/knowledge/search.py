"""SQLite FTS5 knowledge base — offline search engine.

Build with: python3 knowledge/build_kb.py
Search with: from knowledge.search import search_kb
"""

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "survival.db")


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def search_kb(query: str, limit: int = 5) -> list:
    """Search the knowledge base using FTS5 full-text search."""
    if not os.path.exists(DB_PATH):
        return []

    conn = _get_conn()
    try:
        # FTS5 search with BM25 ranking
        cursor = conn.execute(
            "SELECT title, content, rank FROM knowledge_fts "
            "WHERE knowledge_fts MATCH ? "
            "ORDER BY rank "
            "LIMIT ?",
            (query, limit)
        )
        return [dict(row) for row in cursor.fetchall()]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def get_entry(title: str) -> dict:
    """Get a specific entry by title."""
    if not os.path.exists(DB_PATH):
        return {}

    conn = _get_conn()
    try:
        cursor = conn.execute(
            "SELECT title, content FROM knowledge WHERE title = ?",
            (title,)
        )
        row = cursor.fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def list_categories() -> list:
    """List all unique categories in the knowledge base."""
    if not os.path.exists(DB_PATH):
        return []

    conn = _get_conn()
    try:
        cursor = conn.execute("SELECT DISTINCT category FROM knowledge ORDER BY category")
        return [row["category"] for row in cursor.fetchall()]
    finally:
        conn.close()
