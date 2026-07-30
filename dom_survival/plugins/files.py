"""File operations plugin — browse, read, move, delete files.

SANDBOXED: All file operations are restricted to /home/ardis/dom_data/.
Any path containing ".." or resolving outside the sandbox is rejected.
"""

import os
import shutil

# ============================================================================
# SANDBOX CONFIGURATION
# ============================================================================
SANDBOX_ROOT = "/home/ardis/dom_data/"


def _validate_sandbox(path: str) -> str:
    """Resolve the path and verify it falls strictly inside the sandbox.

    Returns the resolved absolute path if valid.
    Raises PermissionError if the path escapes the sandbox or contains '..'.
    """
    if ".." in path:
        raise PermissionError(f"Directory traversal rejected: path contains '..': {path}")

    resolved = os.path.realpath(os.path.join(SANDBOX_ROOT, path))
    sandbox_real = os.path.realpath(SANDBOX_ROOT)

    if not resolved.startswith(sandbox_real + os.sep) and resolved != sandbox_real:
        raise PermissionError(
            f"Path escapes sandbox: {path} -> {resolved} "
            f"(must be inside {sandbox_real})"
        )
    return resolved


def handle_file(tag_args: str) -> str:
    """Handle [FILE: op, path, args] tags.

    Operations: list, read, write, move, copy, delete, mkdir, exists, size

    All paths are sandboxed to /home/ardis/dom_data/.
    """
    parts = [p.strip() for p in tag_args.split(",", 2)]
    if len(parts) < 2:
        return "[FILE] Usage: [FILE: operation, path, args]"

    op = parts[0].lower()
    raw_path = parts[1]
    extra = parts[2] if len(parts) > 2 else ""

    # --- Validate and resolve path inside sandbox ---
    try:
        resolved_path = _validate_sandbox(raw_path)
    except PermissionError as e:
        return f"[FILE] ACCESS DENIED: {e}"

    try:
        if op == "list":
            if not os.path.isdir(resolved_path):
                return f"[FILE] Not a directory: {raw_path}"
            entries = os.listdir(resolved_path)
            result = []
            for e in sorted(entries):
                full = os.path.join(resolved_path, e)
                prefix = "d " if os.path.isdir(full) else "f "
                size = os.path.getsize(full) if os.path.isfile(full) else 0
                result.append(
                    f"{prefix}{e} ({size} bytes)" if os.path.isfile(full) else f"{prefix}{e}/"
                )
            return "\n".join(result) if result else "(empty directory)"

        elif op == "read":
            if not os.path.isfile(resolved_path):
                return f"[FILE] Not a file: {raw_path}"
            with open(resolved_path, "r") as f:
                content = f.read(10000)  # Limit to 10KB
            return content

        elif op == "write":
            # Validate extra (content) path if provided for parent dir
            parent_dir = os.path.dirname(resolved_path)
            if not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)
            with open(resolved_path, "w") as f:
                f.write(extra)
            return f"[FILE] Written to {raw_path}"

        elif op == "move":
            if not extra:
                return "[FILE] Usage: [FILE: move, source, destination]"
            try:
                resolved_dest = _validate_sandbox(extra)
            except PermissionError as e:
                return f"[FILE] ACCESS DENIED (destination): {e}"
            shutil.move(resolved_path, resolved_dest)
            return f"[FILE] Moved {raw_path} -> {extra}"

        elif op == "copy":
            if not extra:
                return "[FILE] Usage: [FILE: copy, source, destination]"
            try:
                resolved_dest = _validate_sandbox(extra)
            except PermissionError as e:
                return f"[FILE] ACCESS DENIED (destination): {e}"
            if os.path.isdir(resolved_path):
                shutil.copytree(resolved_path, resolved_dest)
            else:
                shutil.copy2(resolved_path, resolved_dest)
            return f"[FILE] Copied {raw_path} -> {extra}"

        elif op == "delete":
            if os.path.isdir(resolved_path):
                shutil.rmtree(resolved_path)
            else:
                os.remove(resolved_path)
            return f"[FILE] Deleted {raw_path}"

        elif op == "mkdir":
            os.makedirs(resolved_path, exist_ok=True)
            return f"[FILE] Created directory: {raw_path}"

        elif op == "exists":
            if os.path.exists(resolved_path):
                ftype = "directory" if os.path.isdir(resolved_path) else "file"
                return f"[FILE] {raw_path} exists ({ftype})"
            return f"[FILE] {raw_path} does not exist"

        elif op == "size":
            if os.path.isfile(resolved_path):
                size = os.path.getsize(resolved_path)
                return f"[FILE] {raw_path}: {size} bytes ({size / 1024:.1f} KB)"
            elif os.path.isdir(resolved_path):
                total = sum(
                    os.path.getsize(os.path.join(dp, f))
                    for dp, _, fn in os.walk(resolved_path)
                    for f in fn
                )
                return f"[FILE] {raw_path}: {total} bytes ({total / 1024:.1f} KB)"
            return f"[FILE] {raw_path} not found"

        else:
            return (
                f"[FILE] Unknown operation: {op}. "
                "Available: list, read, write, move, copy, delete, mkdir, exists, size"
            )

    except Exception as e:
        return f"[FILE] Error: {str(e)}"


def register(registry):
    """Register file handlers with the tag registry."""
    from core.tags import TagRegistry
    registry.register("[FILE:", handle_file)
