#!/usr/bin/env python3
"""Database bridge for C++ servers (main.cpp, dom_cloud/main.cpp).

Replaces direct JSON file I/O with libsql database operations.
All output is JSON to stdout; errors to stderr.

Usage:
  python3 dom_db_bridge.py init
  python3 dom_db_bridge.py ram:push <role> <content> [session]
  python3 dom_db_bridge.py ram:load [session]
  python3 dom_db_bridge.py ram:clear [session]
  python3 dom_db_bridge.py ram:count [session]
  python3 dom_db_bridge.py hdd:set <key> <value>
  python3 dom_db_bridge.py hdd:get <key>
  python3 dom_db_bridge.py hdd:load
  python3 dom_db_bridge.py hdd:delete <key>
  python3 dom_db_bridge.py email:add <type> <sender>
  python3 dom_db_bridge.py email:is_known <sender>
  python3 dom_db_bridge.py email:load
  python3 dom_db_bridge.py migrate <hdd_json> [ram_json] [session]
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shared import db


def out(data):
    print(json.dumps(data))
    sys.stdout.flush()


def err(msg):
    print(msg, file=sys.stderr)
    sys.stderr.flush()


def main():
    if len(sys.argv) < 2:
        out({"status": "error", "message": "Usage: dom_db_bridge.py <command> [args...]"})
        sys.exit(1)

    cmd = sys.argv[1]

    try:
        if cmd == "init":
            db.init_schema()
            out({"status": "ok"})

        # ── RAM Operations ─────────────────────────────────────────────────
        elif cmd == "ram:push":
            if len(sys.argv) < 4:
                out({"status": "error", "message": "Usage: ram:push <role> <content> [session]"})
                sys.exit(1)
            role = sys.argv[2]
            content = sys.argv[3]
            session = sys.argv[4] if len(sys.argv) > 4 else "default"
            db.ram_push(role, content, session)
            out({"status": "ok"})

        elif cmd == "ram:load":
            session = sys.argv[2] if len(sys.argv) > 2 else "default"
            messages = db.ram_load(session)
            out(messages)

        elif cmd == "ram:clear":
            session = sys.argv[2] if len(sys.argv) > 2 else "default"
            db.ram_clear(session)
            out({"status": "ok"})

        elif cmd == "ram:count":
            session = sys.argv[2] if len(sys.argv) > 2 else "default"
            count = db.ram_count(session)
            out({"status": "ok", "count": count})

        # ── HDD Operations ─────────────────────────────────────────────────
        elif cmd == "hdd:set":
            if len(sys.argv) < 4:
                out({"status": "error", "message": "Usage: hdd:set <key> <value>"})
                sys.exit(1)
            db.hdd_set(sys.argv[2], sys.argv[3])
            out({"status": "ok"})

        elif cmd == "hdd:get":
            if len(sys.argv) < 3:
                out({"status": "error", "message": "Usage: hdd:get <key>"})
                sys.exit(1)
            value = db.hdd_get(sys.argv[2])
            out({"status": "ok", "value": value})

        elif cmd == "hdd:load":
            data = db.hdd_get_all()
            out(data)

        elif cmd == "hdd:delete":
            if len(sys.argv) < 3:
                out({"status": "error", "message": "Usage: hdd:delete <key>"})
                sys.exit(1)
            db.hdd_delete(sys.argv[2])
            out({"status": "ok"})

        # ── Email Filter Operations ────────────────────────────────────────
        elif cmd == "email:add":
            if len(sys.argv) < 4:
                out({"status": "error", "message": "Usage: email:add <type> <sender>"})
                sys.exit(1)
            db.email_filter_add(sys.argv[2], sys.argv[3])
            out({"status": "ok"})

        elif cmd == "email:is_known":
            if len(sys.argv) < 3:
                out({"status": "error", "message": "Usage: email:is_known <sender>"})
                sys.exit(1)
            result = db.email_filter_is_known(sys.argv[2])
            out({"status": "ok", "type": result})

        elif cmd == "email:load":
            data = db.email_filter_load_all()
            out(data)

        # ── Migration ──────────────────────────────────────────────────────
        elif cmd == "migrate":
            hdd_path = sys.argv[2] if len(sys.argv) > 2 else None
            ram_path = sys.argv[3] if len(sys.argv) > 3 else None
            session = sys.argv[4] if len(sys.argv) > 4 else "default"
            db.migrate_from_json(hdd_path, ram_path, session)
            out({"status": "ok"})

        elif cmd == "set_db_path":
            if len(sys.argv) < 3:
                out({"status": "error", "message": "Usage: set_db_path <path>"})
                sys.exit(1)
            db.set_db_path(sys.argv[2])
            out({"status": "ok"})

        else:
            out({"status": "error", "message": f"Unknown command: {cmd}"})
            sys.exit(1)

    except Exception as e:
        out({"status": "error", "message": str(e)})
        sys.exit(1)


if __name__ == "__main__":
    main()
