"""Personality and behavior rules loader."""

import os

def _rules_path():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dom_rules.txt")

DEFAULT_RULES = "You are Dom Interface, a loyal desktop AI assistant for Master Ardis."

def load_rules():
    path = _rules_path()
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return DEFAULT_RULES
