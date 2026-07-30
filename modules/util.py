"""Shared utilities for all modules.

Import from here instead of from dom to avoid circular imports.
"""

import os
import subprocess
import sys
import threading
import time
from datetime import datetime

# ── ANSI Colors ──────────────────────────────────────────────────────────────

GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
DIM = "\033[2m"
RESET = "\033[0m"
BOLD = "\033[1m"

# ── Paths ────────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


# ── Logging ──────────────────────────────────────────────────────────────────

def _timestamp():
    return datetime.now().strftime("%H:%M:%S")

def log_info(msg):
    print(f"  {DIM}{_timestamp()}{RESET}  {BLUE}i{RESET}  {msg}")

def log_ok(msg):
    print(f"  {DIM}{_timestamp()}{RESET}  {GREEN}✓{RESET}  {msg}")

def log_warn(msg):
    print(f"  {DIM}{_timestamp()}{RESET}  {YELLOW}!{RESET}  {msg}")

def log_err(msg):
    print(f"  {DIM}{_timestamp()}{RESET}  {RED}✗{RESET}  {msg}")


# ── Shell Runner ─────────────────────────────────────────────────────────────

def run_cmd(cmd, timeout=5):
    """Run a shell command safely, return stdout or empty string."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


# ── Spinner ──────────────────────────────────────────────────────────────────

def show_spinner(stop_event, message="Working"):
    spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    i = 0
    while not stop_event.is_set():
        sys.stdout.write(f"\r  {GREEN}{spinner_chars[i % len(spinner_chars)]}{RESET} {DIM}{message}...{RESET}")
        sys.stdout.flush()
        time.sleep(0.08)
        i += 1
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()


def run_with_spinner(message, func, *args, **kwargs):
    """Run func in foreground while showing spinner. Returns func's result."""
    stop = threading.Event()
    t = threading.Thread(target=show_spinner, args=(stop, message))
    t.start()
    try:
        result = func(*args, **kwargs)
    finally:
        stop.set()
        t.join()
    return result


# ── Bordered Box ─────────────────────────────────────────────────────────────

def print_box(title, body, color=CYAN):
    width = max(len(line) for line in body.splitlines()) if body else 0
    width = max(width, len(title)) + 2
    border = "─" * (width + 2)
    print(f"\n  {color}┌{border}┐{RESET}")
    print(f"  {color}│{RESET} {BOLD}{title}{RESET}{' ' * max(0, width - len(title))} {color}│{RESET}")
    print(f"  {color}├{border}┤{RESET}")
    for line in body.splitlines():
        pad = width - len(line)
        print(f"  {color}│{RESET} {line}{' ' * max(0, pad)} {color}│{RESET}")
    print(f"  {color}└{border}┘{RESET}\n")
