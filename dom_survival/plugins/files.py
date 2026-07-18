"""File operations plugin — browse, read, move, delete files."""

import os
import shutil


def handle_file(tag_args: str) -> str:
    """Handle [FILE: op, path, args] tags.
    
    Operations: list, read, write, move, copy, delete, mkdir, exists
    """
    parts = [p.strip() for p in tag_args.split(",", 2)]
    if len(parts) < 2:
        return "[FILE] Usage: [FILE: operation, path, args]"

    op = parts[0].lower()
    path = parts[1]
    extra = parts[2] if len(parts) > 2 else ""

    try:
        if op == "list":
            if not os.path.isdir(path):
                return f"[FILE] Not a directory: {path}"
            entries = os.listdir(path)
            result = []
            for e in sorted(entries):
                full = os.path.join(path, e)
                prefix = "d " if os.path.isdir(full) else "f "
                size = os.path.getsize(full) if os.path.isfile(full) else 0
                result.append(f"{prefix}{e} ({size} bytes)" if os.path.isfile(full) else f"{prefix}{e}/")
            return "\n".join(result) if result else "(empty directory)"

        elif op == "read":
            if not os.path.isfile(path):
                return f"[FILE] Not a file: {path}"
            with open(path, "r") as f:
                content = f.read(10000)  # Limit to 10KB
            return content

        elif op == "write":
            os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
            with open(path, "w") as f:
                f.write(extra)
            return f"[FILE] Written to {path}"

        elif op == "move":
            if not extra:
                return "[FILE] Usage: [FILE: move, source, destination]"
            shutil.move(path, extra)
            return f"[FILE] Moved {path} -> {extra}"

        elif op == "copy":
            if not extra:
                return "[FILE] Usage: [FILE: copy, source, destination]"
            if os.path.isdir(path):
                shutil.copytree(path, extra)
            else:
                shutil.copy2(path, extra)
            return f"[FILE] Copied {path} -> {extra}"

        elif op == "delete":
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            return f"[FILE] Deleted {path}"

        elif op == "mkdir":
            os.makedirs(path, exist_ok=True)
            return f"[FILE] Created directory: {path}"

        elif op == "exists":
            if os.path.exists(path):
                ftype = "directory" if os.path.isdir(path) else "file"
                return f"[FILE] {path} exists ({ftype})"
            return f"[FILE] {path} does not exist"

        elif op == "size":
            if os.path.isfile(path):
                size = os.path.getsize(path)
                return f"[FILE] {path}: {size} bytes ({size/1024:.1f} KB)"
            elif os.path.isdir(path):
                total = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fn in os.walk(path) for f in fn)
                return f"[FILE] {path}: {total} bytes ({total/1024:.1f} KB)"
            return f"[FILE] {path} not found"

        else:
            return f"[FILE] Unknown operation: {op}. Available: list, read, write, move, copy, delete, mkdir, exists, size"

    except Exception as e:
        return f"[FILE] Error: {str(e)}"


def register(registry):
    """Register file handlers with the tag registry."""
    from core.tags import TagRegistry
    registry.register("[FILE:", handle_file)
