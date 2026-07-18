"""Build the SQLite FTS5 knowledge base from text packs.

Usage: python3 build_kb.py

Reads all .txt files from knowledge/packs/ and builds survival.db
"""

import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PACKS_DIR = os.path.join(BASE_DIR, "packs")
DB_PATH = os.path.join(BASE_DIR, "survival.db")


def parse_pack(filepath: str) -> list:
    """Parse a text pack into entries. Format:
    
    # Category
    
    ## Title
    Content paragraph(s) until next ## or # or end of file.
    """
    entries = []
    category = "general"
    current_title = None
    current_content = []

    with open(filepath, "r") as f:
        for line in f:
            line = line.rstrip()
            if line.startswith("# ") and not line.startswith("## "):
                # New category
                if current_title and current_content:
                    entries.append({
                        "category": category,
                        "title": current_title,
                        "content": "\n".join(current_content).strip()
                    })
                category = line[2:].strip()
                current_title = None
                current_content = []
            elif line.startswith("## "):
                # New entry
                if current_title and current_content:
                    entries.append({
                        "category": category,
                        "title": current_title,
                        "content": "\n".join(current_content).strip()
                    })
                current_title = line[3:].strip()
                current_content = []
            elif current_title:
                current_content.append(line)

    # Don't forget the last entry
    if current_title and current_content:
        entries.append({
            "category": category,
            "title": current_title,
            "content": "\n".join(current_content).strip()
        })

    return entries


def build_database():
    """Build the SQLite FTS5 database from all text packs."""
    if not os.path.exists(PACKS_DIR):
        print(f"Error: No packs directory found at {PACKS_DIR}")
        return

    # Remove old database
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
            title, content, category,
            content=knowledge,
            content_rowid=id
        )
    """)

    total_entries = 0
    for filename in sorted(os.listdir(PACKS_DIR)):
        if not filename.endswith(".txt"):
            continue
        filepath = os.path.join(PACKS_DIR, filename)
        entries = parse_pack(filepath)
        for entry in entries:
            conn.execute(
                "INSERT INTO knowledge (category, title, content) VALUES (?, ?, ?)",
                (entry["category"], entry["title"], entry["content"])
            )
            total_entries += 1

    # Populate FTS index
    conn.execute("""
        INSERT INTO knowledge_fts(rowid, title, content, category)
        SELECT id, title, content, category FROM knowledge
    """)

    conn.commit()
    conn.close()

    size_kb = os.path.getsize(DB_PATH) / 1024
    print(f"Knowledge base built: {total_entries} entries, {size_kb:.1f} KB")
    print(f"Database: {DB_PATH}")


if __name__ == "__main__":
    build_database()
