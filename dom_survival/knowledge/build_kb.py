"""Build the FTS5 knowledge base from text packs.

Usage: python3 build_kb.py

Reads all .txt files from knowledge/packs/ and populates the unified
libsql database (shared/db.py). Syncs to Turso when credentials are set.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from shared import db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PACKS_DIR = os.path.join(BASE_DIR, "packs")


def parse_pack(filepath: str) -> list:
    entries = []
    category = "general"
    current_title = None
    current_content = []

    with open(filepath, "r") as f:
        for line in f:
            line = line.rstrip()
            if line.startswith("# ") and not line.startswith("## "):
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

    if current_title and current_content:
        entries.append({
            "category": category,
            "title": current_title,
            "content": "\n".join(current_content).strip()
        })

    return entries


def build_database():
    if not os.path.exists(PACKS_DIR):
        print(f"Error: No packs directory found at {PACKS_DIR}")
        return

    db.knowledge_clear()

    total_entries = 0
    for filename in sorted(os.listdir(PACKS_DIR)):
        if not filename.endswith(".txt"):
            continue
        filepath = os.path.join(PACKS_DIR, filename)
        entries = parse_pack(filepath)
        for entry in entries:
            db.knowledge_insert(entry["category"], entry["title"], entry["content"])
            total_entries += 1

    count = db.knowledge_count()
    print(f"Knowledge base built: {count} entries")
    print(f"Database: {db._resolve_path()}")


if __name__ == "__main__":
    build_database()
