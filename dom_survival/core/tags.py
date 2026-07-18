"""Tag protocol — parser and registry.

Same tag protocol as dom_cloud. Tags in AI output like [RUN: spotify] are
extracted, dispatched to handlers, and results injected back.
"""

import re
from typing import Callable, Dict, List, Optional

TagHandler = Callable[[str], Optional[str]]

TAG_PREFIXES = [
    "[RUN:", "[SAVE:", "[PROBE:", "[RECALL:",
    "[FILE:", "[SEARCH:", "[REMIND:",
    "[SCREENSHOT]", "[NOTIFY:", "[MODE:"
]


def extract_tags(text: str, prefix: str) -> List[str]:
    """Extract all values for a given tag prefix from text."""
    pattern = re.escape(prefix) + r"([^\]]*)\]"
    return re.findall(pattern, text)


def extract_tag(text: str, prefix: str) -> Optional[str]:
    """Extract the first occurrence of a tag."""
    tags = extract_tags(text, prefix)
    return tags[0] if tags else None


def clean_output(text: str) -> str:
    """Strip all system tags from text, return clean user-facing output."""
    for prefix in TAG_PREFIXES:
        if prefix.endswith("]"):
            text = text.replace(prefix, "")
        else:
            pattern = re.escape(prefix) + r"[^\]]*\]"
            text = re.sub(pattern, "", text)
    return text.strip()


class TagRegistry:
    """Registry of tag prefix -> handler function mappings."""

    def __init__(self):
        self._handlers: Dict[str, TagHandler] = {}

    def register(self, prefix: str, handler: TagHandler):
        self._handlers[prefix] = handler

    def process_all(self, ai_response: str) -> str:
        """Process all tags in an AI response, return combined results."""
        results = []
        for prefix, handler in self._handlers.items():
            tags = extract_tags(ai_response, prefix)
            for tag in tags:
                result = handler(tag)
                if result:
                    results.append(result)
        return "\n".join(results)

    def has_tag(self, text: str) -> bool:
        """Check if any tags exist in the text."""
        for prefix in self._handlers:
            if extract_tag(text, prefix) is not None:
                return True
        return False
