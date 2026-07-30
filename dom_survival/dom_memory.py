"""Long-term memory — unified libsql database.

Delegates to shared.db for all storage operations.
Automatically syncs to Turso when TURSO_DATABASE_URL is set.
Falls back to local-only mode when Turso is not configured.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared import db


def init_memory():
    pass


def save_memory(category: str, content: str):
    db.memory_save(category, content)


def search_memory(query: str, limit: int = 3):
    return db.memory_search(query, limit)
