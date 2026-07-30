"""FTS5 knowledge base — offline search via unified libsql database.

Build with: python3 knowledge/build_kb.py
Search with: from knowledge.search import search_kb
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from shared import db


def search_kb(query: str, limit: int = 5) -> list:
    return db.knowledge_search(query, limit)


def get_entry(title: str) -> dict:
    result = db.knowledge_get_entry(title)
    return result if result else {}


def list_categories() -> list:
    return db.knowledge_list_categories()
