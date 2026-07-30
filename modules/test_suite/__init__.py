"""Test Suite — runs a safe health check on all registered plugins."""

import inspect

from modules import load_modules
from modules.base import BasePlugin

CHECK = "\033[92m\u2713\033[0m"
CROSS = "\033[91m\u2717\033[0m"


class Plugin(BasePlugin):
    name = "test_suite"
    triggers = ["/test", "test plugins", "run diagnostics"]

    def execute(self, user_input: str) -> dict:
        rows = []
        passed = 0
        failed = 0

        for modname, mod in load_modules():
            if modname == "test_suite":
                continue

            name_col = modname.replace("_", " ").title()

            if not mod.TRIGGERS:
                rows.append(f"  {CROSS} {name_col:<16}  \033[2mno triggers\033[0m")
                failed += 1
                continue

            if not all(isinstance(t, str) for t in mod.TRIGGERS):
                rows.append(f"  {CROSS} {name_col:<16}  \033[2mnon-string trigger\033[0m")
                failed += 1
                continue

            if not callable(mod.execute):
                rows.append(f"  {CROSS} {name_col:<16}  \033[2mexecute not callable\033[0m")
                failed += 1
                continue

            sig = inspect.signature(mod.execute)
            if len(sig.parameters) < 1:
                rows.append(f"  {CROSS} {name_col:<16}  \033[2mexecute expects 0 args\033[0m")
                failed += 1
                continue

            rows.append(f"  {CHECK} {name_col:<16}  loaded, healthy")
            passed += 1

        total = passed + failed
        if failed == 0:
            status = f"  {CHECK} All {total} plugins: PASS"
            status_code = "success"
        else:
            status = f"  {CROSS} {failed}/{total} plugins FAILED"
            status_code = "error"

        left = "\u2502"
        w = 48

        def line(text=""):
            return f"  {left} {text:<{w}}{left}"

        report = "\n".join([
            f"  \u250c{'─' * (w + 2)}\u2510",
            line("Test Suite Report"),
            f"  \u251c{'─' * (w + 2)}\u2524",
        ] + [line(r) for r in rows] + [
            f"  \u251c{'─' * (w + 2)}\u2524",
            line(status),
            f"  \u2514{'─' * (w + 2)}\u2518",
        ])

        return {"status": status_code, "output": report}
