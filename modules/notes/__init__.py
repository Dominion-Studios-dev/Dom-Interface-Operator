"""Notes — save, view, and clear timestamped notes stored locally."""

import os
from datetime import datetime
from typing import Optional

from modules.base import BasePlugin
from modules.util import log_info, log_err, GREEN, CYAN, RESET


NOTES_DIR = os.path.expanduser("~/.config/dom")
NOTES_FILE = os.path.join(NOTES_DIR, "notes.md")


def _ensure_file():
    os.makedirs(NOTES_DIR, exist_ok=True)
    if not os.path.exists(NOTES_FILE):
        with open(NOTES_FILE, "w") as f:
            f.write("# Dom Notes\n\n")


def _add_note(text: str) -> dict:
    _ensure_file()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(NOTES_FILE, "a") as f:
        f.write(f"**[{timestamp}]** {text}\n\n")
    log_info(f"Note saved at {timestamp}")
    return {"status": "success", "output": f"Note saved at {timestamp}:\n{text}"}


def _view_notes() -> dict:
    _ensure_file()
    with open(NOTES_FILE, "r") as f:
        content = f.read().strip()
    lines = [l for l in content.splitlines() if l.startswith("**[")]
    if not lines:
        return {"status": "success", "output": "No notes saved yet."}
    return {"status": "success", "output": "\n".join(lines)}


def _clear_notes() -> dict:
    _ensure_file()
    with open(NOTES_FILE, "w") as f:
        f.write("# Dom Notes\n\n")
    log_info("Notes cleared.")
    return {"status": "success", "output": "All notes cleared."}


class Plugin(BasePlugin):
    name = "notes"
    triggers = ["note", "notes"]

    def execute(self, user_input: str) -> Optional[dict]:
        lower = user_input.lower().strip()

        if any(phrase in lower for phrase in ["clear notes", "delete notes", "wipe notes"]):
            return _clear_notes()

        if any(phrase in lower for phrase in ["show notes", "read notes", "view notes", "list notes"]):
            return _view_notes()

        save_prefixes = ["take note", "save note", "add note", "new note"]
        for prefix in save_prefixes:
            if prefix in lower:
                text = user_input[lower.index(prefix) + len(prefix):].strip()
                if text:
                    return _add_note(text)
                return {"status": "error", "output": "No text provided. Usage: take note <text>"}

        if lower.startswith("note "):
            text = user_input[5:].strip()
            if text:
                return _add_note(text)

        return None
