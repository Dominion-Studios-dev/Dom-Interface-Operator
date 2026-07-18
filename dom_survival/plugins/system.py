"""System control plugin — execute commands, monitor processes."""

import subprocess
import os
import json


def load_commands():
    """Load dom_commands.json."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dom_commands.json")
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def run_command(cmd: str) -> str:
    """Execute a shell command and return output."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30
        )
        output = result.stdout.strip()
        if result.stderr.strip():
            output += "\n" + result.stderr.strip() if output else result.stderr.strip()
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 30 seconds"
    except Exception as e:
        return f"Error: {str(e)}"


def handle_run(cmd_key: str) -> str:
    """Handle [RUN: key] tags."""
    commands = load_commands()
    if cmd_key in commands:
        actual_cmd = commands[cmd_key]
        print(f"[EXEC] {actual_cmd}")
        run_command(actual_cmd)
        return ""
    return f"[RUN] Unknown command: {cmd_key}"


def handle_probe(probe_key: str) -> str:
    """Handle [PROBE: key] tags — run command, return output."""
    commands = load_commands()
    if probe_key in commands:
        actual_cmd = commands[probe_key]
        print(f"[PROBE] {probe_key} -> {actual_cmd}")
        return run_command(actual_cmd)
    return ""


def register(registry):
    """Register system handlers with the tag registry."""
    from core.tags import TagRegistry
    registry.register("[RUN:", handle_run)
    registry.register("[PROBE:", handle_probe)
