"""Inference engine — routes between cloud, local LLM, and embedded rules."""

import json
import os
import urllib.request
import urllib.error
import subprocess
from typing import Optional

from .memory import load_ram, update_ram, load_hdd, save_hdd
from .rules import load_rules


def _groq_available() -> bool:
    """Quick check if Groq API is reachable."""
    try:
        urllib.request.urlopen("https://api.groq.com", timeout=2)
        return True
    except Exception:
        return False


def _ollama_available() -> bool:
    """Check if local Ollama is running."""
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        return True
    except Exception:
        return False


def fire_groq(message: str, api_key: str) -> Optional[str]:
    """Call Groq API for inference."""
    if not api_key:
        return None

    messages = [{"role": "system", "content": load_rules()}]
    for msg in load_ram():
        messages.append(msg)
    messages.append({"role": "user", "content": message})

    body = json.dumps({
        "model": "llama-3.1-8b-instant",
        "messages": messages
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data["choices"][0]["message"]["content"]
    except Exception:
        return None


def fire_ollama(message: str) -> Optional[str]:
    """Call local Ollama for inference."""
    messages = [{"role": "system", "content": load_rules()}]
    for msg in load_ram():
        messages.append(msg)
    messages.append({"role": "user", "content": message})

    body = json.dumps({
        "model": "llama3.2:3b",
        "messages": messages,
        "stream": False
    }).encode("utf-8")

    req = urllib.request.Request(
        "http://localhost:11434/api/chat",
        data=body,
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            return data["message"]["content"]
    except Exception:
        return None


def embedded_rules_response(message: str) -> str:
    """Last-resort rule-based response when no LLM is available."""
    msg = message.lower().strip()

    # System info
    if any(w in msg for w in ["who are you", "what are you", "your name"]):
        return "I am Dom Interface, your AI assistant. Running in offline mode with embedded knowledge."

    if any(w in msg for w in ["time", "what time", "clock"]):
        from datetime import datetime
        return f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    if any(w in msg for w in ["date", "what date", "today"]):
        from datetime import datetime
        return f"Today is {datetime.now().strftime('%A, %B %d, %Y')}"

    if any(w in msg for w in ["hostname", "computer name", "system"]):
        import platform
        return f"System: {platform.node()} — {platform.system()} {platform.release()}"

    if any(w in msg for w in ["help", "what can you do"]):
        return (
            "Offline mode active. I can help with:\n"
            "- System commands and file operations\n"
            "- Knowledge lookup from embedded database\n"
            "- Reminders and scheduling\n"
            "- Basic conversation\n\n"
            "Type [RUN: key] to execute commands from dom_commands.json.\n"
            "I'll search my knowledge base for any questions you have."
        )

    # Default: search knowledge base
    return None


def get_api_key() -> str:
    """Get Groq API key from environment variables only."""
    return os.environ.get("GROQ_API_KEY", "").strip()


def infer(message: str) -> str:
    """Main inference function — tries cloud, then local, then rules."""
    api_key = get_api_key()

    # Tier 1: Cloud (Groq)
    if api_key and _groq_available():
        result = fire_groq(message, api_key)
        if result:
            return result

    # Tier 2: Local LLM (Ollama)
    if _ollama_available():
        result = fire_ollama(message)
        if result:
            return result

    # Tier 3: Embedded rules + knowledge base
    result = embedded_rules_response(message)
    if result:
        return result

    # Tier 4: Knowledge base search (if available)
    try:
        from ..knowledge.search import search_kb
        results = search_kb(message, limit=3)
        if results:
            return "Here's what I found in my knowledge base:\n\n" + "\n\n".join(
                f"**{r['title']}**\n{r['content']}" for r in results
            )
    except ImportError:
        pass

    return "I'm running in offline mode with no LLM available. I can still execute commands and search my knowledge base. Try asking about a specific topic or type 'help' for what I can do."
