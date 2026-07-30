"""Module loader — discovers BasePlugin subclasses in subdirectory packages."""

import importlib
import os
import pkgutil
from typing import Optional

from modules.base import BasePlugin


SKIP = {"template", "__init__", "base", "util"}


class _ModuleProxy:
    """Backward-compatible wrapper: exposes .TRIGGERS and .execute()."""

    def __init__(self, plugin: BasePlugin):
        self._plugin = plugin
        self.name = plugin.name
        self.TRIGGERS = plugin.triggers

    def execute(self, user_input: str) -> Optional[dict]:
        try:
            return self._plugin.execute(user_input)
        except Exception as e:
            return {"status": "error", "output": f"{self.name} crashed: {e}"}


def load_modules():
    """Scan modules/ subdirectories and return list of (name, _ModuleProxy) tuples.

    Each discovered plugin is wrapped in try/except isolation so a single
    broken plugin never crashes the whole system.
    """
    package_dir = os.path.dirname(os.path.abspath(__file__))
    loaded = []

    for importer, modname, ispkg in pkgutil.iter_modules([package_dir]):
        if modname in SKIP or not ispkg:
            continue

        try:
            mod = importlib.import_module(f"modules.{modname}")
        except Exception as e:
            print(f"  \033[91m✗\033[0m  Failed to import package '{modname}': {e}")
            continue

        if not hasattr(mod, "Plugin"):
            continue

        try:
            instance = mod.Plugin()
        except Exception as e:
            print(f"  \033[91m✗\033[0m  Failed to instantiate plugin '{modname}': {e}")
            continue

        if not isinstance(instance, BasePlugin):
            print(f"  \033[91m✗\033[0m  '{modname}.Plugin' does not inherit BasePlugin")
            continue

        proxy = _ModuleProxy(instance)
        loaded.append((modname, proxy))

    return loaded
