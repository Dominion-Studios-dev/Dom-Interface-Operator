"""Email Cleaner — scan inbox, delete spam, report important messages."""

import os
import subprocess

from modules.base import BasePlugin
from modules.util import (
    SCRIPT_DIR, GREEN, DIM, RESET,
    log_info, log_err, log_ok, run_with_spinner, print_box,
)


class Plugin(BasePlugin):
    name = "email_cleaner"
    triggers = ["email", "emails", "inbox", "mail"]

    def execute(self, user_input: str) -> dict:
        script = os.path.join(SCRIPT_DIR, "dom_cloud", "plugins", "emails.py")
        if not os.path.exists(script):
            return {"status": "error", "output": f"Email plugin not found: {script}"}

        log_info("Launching email engine...")
        result = run_with_spinner("Processing emails", subprocess.run,
                                  ["python3", "-u", script], stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True)

        if result.stdout.strip():
            print(f"\n  {DIM}{result.stdout.strip()}{RESET}")

        if result.returncode != 0:
            stderr = result.stderr.strip()
            return {"status": "error", "output": f"Exit code {result.returncode}: {stderr}"}

        report_path = os.path.join(SCRIPT_DIR, "dom_sandbox", "important_emails.txt")
        if os.path.exists(report_path):
            with open(report_path, "r") as f:
                report = f.read().strip()
            if report:
                print_box("Email Report", report, GREEN)
                return {"status": "success", "output": report}

        log_ok("Email scan complete — no issues found.")
        return {"status": "success", "output": "No issues found."}
