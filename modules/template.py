"""Template Module — copy this directory to create new plugins.

Steps to add a new module:
  1. Copy this directory: cp -r modules/template modules/my_tool
  2. Edit modules/my_tool/__init__.py:
     - Change class name (optional) and name/triggers
     - Implement execute() with your logic
  3. That's it — dom auto-discovers it on startup

Module interface:
  class Plugin(BasePlugin):
    name: str                   — short unique identifier
    triggers: list[str]         — phrases/keywords that activate this module
    execute(user_input) -> dict | None  — dict with status/output, or None for pass-through
"""

from modules.base import BasePlugin


class Plugin(BasePlugin):
    name = "template"
    triggers = ["template trigger here"]

    def execute(self, user_input: str) -> dict:
        return {"status": "success", "output": "Template module ran successfully."}
