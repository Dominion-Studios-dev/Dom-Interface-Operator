#!/usr/bin/env python3
"""Dom Interface — Survival Mode

Offline-first AI assistant. Works with or without internet.
When online: uses Groq API. When offline: uses local LLM or embedded rules.

Usage:
    python3 dom.py              # Interactive mode
    python3 dom.py "message"    # Single message mode
    python3 dom.py --build-kb   # Rebuild knowledge base
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.memory import update_ram, load_ram, load_hdd, hdd_set
from core.rules import load_rules
from core.tags import TagRegistry, clean_output
from core.engine import infer, get_api_key
from dom_memory import save_memory, search_memory


# ANSI Colors
GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"


def process_message(user_input: str, tags: TagRegistry) -> str:
    """Process a user message through the full pipeline."""
    # --- Long-term memory: "Remember that" command ---
    lower_input = user_input.strip()
    remember_prefixes = ["remember that ", "remember "]
    for prefix in remember_prefixes:
        if lower_input.lower().startswith(prefix):
            fact = user_input.strip()[len(prefix):].strip()
            if fact:
                save_memory("user_fact", fact)
                update_ram("user", user_input)
                reply = f"Understood, Master. I will remember: {fact}"
                update_ram("assistant", reply)
                return reply

    # --- Search long-term memories for relevant context ---
    memory_context = None
    try:
        memories = search_memory(user_input, limit=3)
        if memories:
            memory_context = "\n".join(
                f"- [{m['category']}] {m['content']}" for m in memories
            )
    except Exception:
        pass  # Memory search is best-effort; never block inference

    # Save to memory
    update_ram("user", user_input)

    # Get AI response (with memory context injected into system prompt)
    dom_reply = infer(user_input, memory_context)
    if dom_reply == "ERROR_SIGNAL":
        return "Connection failed. Running in offline mode."

    # Process tags
    tag_results = tags.process_all(dom_reply)

    # If probe returned data, inject it back for summary
    if tag_results and "[RECALLED" not in tag_results:
        # Send probe results back to LLM for summary
        from core.engine import fire_groq, fire_ollama, _groq_available, _ollama_available

        api_key = get_api_key()
        summary = None

        if api_key and _groq_available():
            messages = [{"role": "system", "content": load_rules()}]
            for msg in load_ram():
                messages.append(msg)
            messages.append({"role": "user", "content":
                f"[INTERNAL SYSTEM METRICS INJECTED]:\n{tag_results}\n\n"
                "Master is waiting. Read the metrics data and provide a concise summary."})
            summary = fire_groq(messages[-1]["content"], api_key)

        if not summary and _ollama_available():
            summary = fire_ollama(
                f"[SYSTEM METRICS]:\n{tag_results}\n\nSummarize this for Master.")

        if summary:
            dom_reply = summary

    # Save assistant response
    update_ram("assistant", dom_reply)

    return clean_output(dom_reply)


def register_plugins(tags: TagRegistry):
    """Load and register all available plugins."""
    import importlib

    plugin_modules = [
        "plugins.system",
        "plugins.files",
        "plugins.search",
        "plugins.notifications",
    ]

    for module_name in plugin_modules:
        try:
            mod = importlib.import_module(module_name)
            if hasattr(mod, "register"):
                mod.register(tags)
        except Exception as e:
            print(f"{YELLOW}[WARN] Could not load {module_name}: {e}{RESET}")


def interactive_mode():
    """Run Dom in interactive terminal mode."""
    tags = TagRegistry()
    register_plugins(tags)

    api_key = get_api_key()
    mode = "cloud" if api_key else "offline"

    print(f"\n{BOLD}{CYAN}=== Dom Interface — Survival Mode ({mode}) ==={RESET}")
    print(f"Type 'exit' to close, 'help' for commands.\n")

    while True:
        try:
            user_input = input(f"{BOLD}You:{RESET} ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit"]:
                print("Disconnecting...")
                break
            if user_input.lower() == "help":
                print(f"\n{CYAN}Available commands:{RESET}")
                print("  exit       — Close Dom")
                print("  help       — Show this help")
                print("  memory     — Show conversation memory")
                print("  memories   — Search long-term memories")
                print("  remember <fact> — Save a fact to long-term memory")
                print("  status     — Show system status")
                print("  kb         — Search knowledge base")
                print("  kb rebuild — Rebuild knowledge base")
                print()

            elif user_input.lower() == "memory":
                ram = load_ram()
                for msg in ram:
                    role = msg["role"]
                    color = GREEN if role == "assistant" else BOLD
                    print(f"{color}{role}:{RESET} {msg['content'][:100]}...")
                continue

            elif user_input.lower().startswith("remember "):
                fact = user_input[len("remember "):].strip()
                if fact:
                    save_memory("user_fact", fact)
                    print(f"{GREEN}Remembered: {fact}{RESET}")
                else:
                    print("Usage: remember <fact>")
                continue

            elif user_input.lower() == "memories":
                query = input(f"{BOLD}Search query: {RESET} ").strip()
                if query:
                    results = search_memory(query, limit=5)
                    if results:
                        for m in results:
                            print(f"\n{CYAN}[{m['category']}]{RESET} {m['content']}")
                            print(f"  {YELLOW}{m['timestamp']}{RESET}")
                    else:
                        print("No matching memories found.")
                continue

            elif user_input.lower() == "status":
                hdd = load_hdd()
                print(f"\n{CYAN}Dom Status:{RESET}")
                print(f"  Mode: {mode}")
                print(f"  RAM messages: {len(load_ram())}")
                print(f"  HDD keys: {len(hdd)}")
                print(f"  API key: {'loaded' if api_key else 'not found'}")
                print()

            elif user_input.lower().startswith("kb"):
                query = user_input[2:].strip()
                if query == "rebuild":
                    from knowledge.build_kb import build_database
                    build_database()
                elif query:
                    try:
                        from knowledge.search import search_kb
                        results = search_kb(query)
                        if results:
                            for r in results:
                                print(f"\n{GREEN}{r['title']}{RESET}")
                                print(f"{r['content'][:200]}...")
                        else:
                            print("No results found.")
                    except Exception as e:
                        print(f"KB search error: {e}")
                else:
                    print("Usage: kb <search query> or kb rebuild")
                continue

            reply = process_message(user_input, tags)
            print(f"{BOLD}{GREEN}Dom Interface:{RESET} {reply}\n")

        except (KeyboardInterrupt, EOFError):
            print(f"\n{YELLOW}Disconnected.{RESET}")
            break
        except Exception as e:
            print(f"\n{RED}[Error]: {e}{RESET}\n")


def single_message(message: str):
    """Process a single message and print the response."""
    tags = TagRegistry()
    register_plugins(tags)
    reply = process_message(message, tags)
    print(reply)


def main():
    # Handle command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "--build-kb":
            from knowledge.build_kb import build_database
            build_database()
            return
        elif sys.argv[1] == "--status":
            api_key = get_api_key()
            print(f"Mode: {'cloud' if api_key else 'offline'}")
            print(f"API key: {'loaded' if api_key else 'not found'}")
            return
        else:
            single_message(" ".join(sys.argv[1:]))
            return

    interactive_mode()


if __name__ == "__main__":
    main()
