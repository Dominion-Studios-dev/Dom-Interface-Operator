"""Todo — manage a simple task list stored as JSON."""

import json
import os

from modules.base import BasePlugin
from modules.util import log_info, log_err, GREEN, CYAN, RESET


TODO_DIR = os.path.expanduser("~/.config/dom")
TODO_FILE = os.path.join(TODO_DIR, "todo.json")


def _ensure_file():
    os.makedirs(TODO_DIR, exist_ok=True)
    if not os.path.exists(TODO_FILE):
        with open(TODO_FILE, "w") as f:
            json.dump([], f)


def _load() -> list:
    _ensure_file()
    with open(TODO_FILE, "r") as f:
        return json.load(f)


def _save(tasks: list):
    with open(TODO_FILE, "w") as f:
        json.dump(tasks, f, indent=2)


def _add_task(text: str) -> dict:
    tasks = _load()
    tasks.append({"task": text, "done": False})
    _save(tasks)
    log_info(f"Added task #{len(tasks)}: {text}")
    return {"status": "success", "output": f"Added task #{len(tasks)}: {text}"}


def _list_tasks() -> dict:
    tasks = _load()
    if not tasks:
        return {"status": "success", "output": "No tasks."}
    lines = []
    for i, t in enumerate(tasks, 1):
        mark = "✓" if t["done"] else "○"
        lines.append(f"  {mark} {i}. {t['task']}")
    return {"status": "success", "output": "\n".join(lines)}


def _done_task(index_str: str) -> dict:
    try:
        idx = int(index_str) - 1
    except ValueError:
        return {"status": "error", "output": "Usage: done todo <number>"}
    tasks = _load()
    if idx < 0 or idx >= len(tasks):
        return {"status": "error", "output": f"Invalid task number. Valid range: 1-{len(tasks)}"}
    tasks[idx]["done"] = True
    _save(tasks)
    log_info(f"Completed task #{idx + 1}: {tasks[idx]['task']}")
    return {"status": "success", "output": f"Completed: {tasks[idx]['task']}"}


def _clear_tasks() -> dict:
    _save([])
    log_info("All tasks cleared.")
    return {"status": "success", "output": "All tasks cleared."}


class Plugin(BasePlugin):
    name = "todo"
    triggers = ["todo", "task"]

    def execute(self, user_input: str) -> dict:
        lower = user_input.lower()

        if any(phrase in lower for phrase in ["clear todo", "clear tasks"]):
            return _clear_tasks()
        elif any(phrase in lower for phrase in ["show todo", "list todo", "show tasks", "list tasks"]):
            return _list_tasks()
        elif any(phrase in lower for phrase in ["done todo", "complete todo", "finish todo"]):
            for prefix in ["done todo", "complete todo", "finish todo"]:
                if prefix in lower:
                    rest = user_input[lower.index(prefix) + len(prefix):].strip()
                    break
            else:
                rest = ""
            return _done_task(rest)
        elif any(phrase in lower for phrase in ["add todo", "add task", "new todo", "new task"]):
            for prefix in ["add todo", "add task", "new todo", "new task"]:
                if prefix in lower:
                    text = user_input[lower.index(prefix) + len(prefix):].strip()
                    break
            else:
                text = ""
            if not text:
                return {"status": "error", "output": "No task provided. Usage: add todo <task>"}
            return _add_task(text)

        return {"status": "error", "output": "Unknown todo command. Try: add todo, show todo, done todo, or clear todo"}
