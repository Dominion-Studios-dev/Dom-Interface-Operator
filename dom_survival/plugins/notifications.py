"""Notifications plugin — push notifications via ntfy."""

import urllib.request
import urllib.error
import json


NTFY_TOPIC = "dom-interface"
NTFY_SERVER = "https://ntfy.sh"


def handle_notify(message: str) -> str:
    """Handle [NOTIFY: message] tags — send push notification."""
    try:
        req = urllib.request.Request(
            f"{NTFY_SERVER}/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                "Title": "Dom Interface",
                "Tags": "robot_face"
            },
            method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
        return ""
    except Exception as e:
        return f"[NOTIFY] Failed to send notification: {str(e)}"


def register(registry):
    """Register notification handlers with the tag registry."""
    from core.tags import TagRegistry
    registry.register("[NOTIFY:", handle_notify)
