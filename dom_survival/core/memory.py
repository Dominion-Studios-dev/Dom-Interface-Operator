"""Memory management — delegates to shared/libsql database.

Replaces JSON file I/O with unified libsql database (Turso-synced).
Preserves all existing function signatures for backward compatibility.
Uses 'survival' session for conversation isolation.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from shared import db

SESSION = "survival"

def _init():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base, "memory", "dom.db")
    db.set_db_path(db_path)

_init()

def load_ram():
    return db.ram_load(SESSION)

def update_ram(role, content):
    db.ram_push(role, content, SESSION)

def load_hdd():
    return db.hdd_get_all()

def save_hdd(data):
    if isinstance(data, dict):
        for k, v in data.items():
            db.hdd_set(k, str(v) if not isinstance(v, str) else v)

def hdd_get(key):
    return db.hdd_get(key)

def hdd_set(key, value):
    db.hdd_set(key, value)
