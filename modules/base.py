"""Abstract base class for all Dom modules/plugins."""

from abc import ABC, abstractmethod
from typing import Optional


class BasePlugin(ABC):
    """Every module must inherit this class and implement execute()."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short human-readable plugin name."""

    @property
    @abstractmethod
    def triggers(self) -> list:
        """List of trigger phrases that activate this plugin."""

    @abstractmethod
    def execute(self, user_input: str) -> Optional[dict]:
        """Process user input.

        Return a dict with keys 'status' and 'output' on match,
        or None to signal pass-through to the main AI backend.
        """
