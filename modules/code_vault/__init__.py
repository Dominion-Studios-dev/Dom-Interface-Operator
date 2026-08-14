"""Code Vault — save, tag, and recall code snippets in the unified libsql DB.

Snippets live in the 'snippets' table of shared/db.py (dom.db), so they
survive across sessions and sync to Turso when configured.

Commands:
    save snippet <name> : <content>
    save snippet <name>#tag : <content>
    save snippet <name> <content>
    recall snippet <query>        search by name / tag / content (exact name first)
    show snippet <name>           exact lookup
    code vault list               all snippets
    code vault tags               all tags
    code vault delete <name>      remove a snippet
    code vault <query>            shorthand search

Examples:
    save snippet git_undo#git : git reset --soft HEAD~1
    save snippet ffmpeg gif : ffmpeg -i in.mp4 out.gif
    recall snippet git
"""

import os
import re
import sys

from modules.base import BasePlugin

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared import db  # noqa: E402


def _parse_save(rest: str):
    """Split 'rest' into (name, tag, content).

    Prefers the '<name> : <content>' / '<name> :: <content>' delimiter so
    names can be multi-word. Falls back to first-token-is-name. A trailing
    #tag or @tag on the name becomes the snippet tag.
    """
    rest = rest.strip()
    if not rest:
        return "", "", ""

    colon = re.search(r":\s*", rest)
    if colon:
        name_part = rest[:colon.start()].strip()
        content = rest[colon.end():].strip()
    else:
        parts = rest.split(None, 1)
        name_part = parts[0].strip()
        content = parts[1].strip() if len(parts) > 1 else ""

    tag = ""
    tag_m = re.search(r"[#@]([A-Za-z0-9_\-]+)\s*$", name_part)
    if tag_m:
        tag = tag_m.group(1)
        name_part = name_part[:tag_m.start()].strip()

    return name_part, tag, content


def _cmd_save(rest: str) -> dict:
    name, tag, content = _parse_save(rest)
    if not name:
        return {"status": "error", "output": "Usage: save snippet <name> : <content>"}
    if not content:
        return {"status": "error", "output": "No snippet content provided. Usage: save snippet <name> : <content>"}

    row_id = db.snippet_save(name, content, tag)
    if row_id is None:
        return {"status": "error", "output": f"Snippet '{name}' already exists. Use 'code vault delete {name}' first or pick a new name."}
    tag_str = f"  [#{tag}]" if tag else ""
    return {"status": "success", "output": f"Saved snippet '{name}'{tag_str} to the Code Vault."}


def _format_single(name: str, tag: str, content: str) -> str:
    header = f"[{name}]" + (f"  #{tag}" if tag else "")
    return f"{header}\n{content}"


def _cmd_show(q: str) -> dict:
    hit = db.snippet_get(q)
    if hit:
        return {"status": "success", "output": _format_single(hit["name"], hit["tag"], hit["content"])}
    return {"status": "error", "output": f"No snippet named '{q}'. Try: recall snippet {q}"}


def _cmd_recall(q: str) -> dict:
    q = q.strip()
    if not q:
        return {"status": "error", "output": "Usage: recall snippet <query>"}
    clean_q = re.sub(r"^[#@]+", "", q).strip()

    exact = db.snippet_get(clean_q)
    if exact:
        return {"status": "success", "output": _format_single(exact["name"], exact["tag"], exact["content"])}

    hits = db.snippet_search(clean_q)
    if not hits:
        return {"status": "success", "output": f"No snippets match '{q}'. Try: code vault list or code vault tags"}

    lines = [f"Found {len(hits)} snippet(s) matching '{q}':"]
    for i, h in enumerate(hits, 1):
        tag = f"  #{h['tag']}" if h["tag"] else ""
        lines.append(f"{i}. [{h['name']}]{tag}")
        lines.append(f"   {h['content'].splitlines()[0][:120] if h['content'] else ''}")
    return {"status": "success", "output": "\n".join(lines)}


def _cmd_list() -> dict:
    rows = db.snippet_list()
    if not rows:
        return {"status": "success", "output": "Code Vault is empty. Save your first snippet with: save snippet <name> : <content>"}
    lines = [f"Code Vault ({len(rows)} snippet(s)):"]
    for i, r in enumerate(rows, 1):
        tag = f"  #{r['tag']}" if r["tag"] else ""
        lines.append(f"{i}. {r['name']}{tag}")
    return {"status": "success", "output": "\n".join(lines)}


def _cmd_tags() -> dict:
    tags = db.snippet_tags()
    if not tags:
        return {"status": "success", "output": "No tags yet. Tag snippets with: save snippet <name>#tag : <content>"}
    return {"status": "success", "output": "Snippet tags:\n" + "\n".join(f"  #{t}" for t in tags)}


def _cmd_delete(q: str) -> dict:
    q = q.strip()
    if not q:
        return {"status": "error", "output": "Usage: code vault delete <name>"}
    if db.snippet_delete(q):
        return {"status": "success", "output": f"Deleted snippet '{q}'."}
    return {"status": "error", "output": f"No snippet named '{q}'."}


class Plugin(BasePlugin):
    name = "code_vault"
    triggers = ["save snippet", "recall snippet", "code vault", "snippet", "show snippet"]

    def execute(self, user_input: str) -> dict:
        lower = user_input.lower().strip()
        if not lower:
            return {"status": "error", "output": "Empty query."}

        # save snippet ...
        save_m = re.match(r"save snippet\s*(.*)", lower, re.DOTALL)
        if save_m:
            return _cmd_save(user_input[save_m.start(1):].strip())

        # show snippet <name>
        show_m = re.match(r"show snippet\s+(.+)", lower)
        if show_m:
            return _cmd_show(show_m.group(1).strip())

        # code vault list / tags / delete
        if re.search(r"(code vault|snippet)\s+list\b", lower):
            return _cmd_list()
        if re.search(r"(code vault|snippet)\s+tags\b", lower):
            return _cmd_tags()
        del_m = re.search(r"(?:code vault|delete snippet)\s+delete\s+(.+)|delete snippet\s+(.+)", lower)
        if "delete snippet" in lower or "delete" in lower and "code vault" in lower:
            m = re.search(r"delete\s+(?:snippet\s+)?(.+)", lower)
            if m:
                return _cmd_delete(m.group(1).strip())

        # recall snippet <q> / code vault <q>
        recall_m = re.match(r"recall snippet\s*(.*)", lower, re.DOTALL)
        if recall_m:
            return _cmd_recall(recall_m.group(1).strip())
        vault_m = re.match(r"code vault\s*(.*)", lower, re.DOTALL)
        if vault_m and vault_m.group(1).strip():
            return _cmd_recall(vault_m.group(1).strip())

        return {"status": "error", "output": "Unknown code vault command. Try: save snippet, recall snippet, code vault list, code vault tags, code vault delete"}
