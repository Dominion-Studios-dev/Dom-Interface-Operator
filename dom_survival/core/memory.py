"""Memory management — RAM (rolling conversation) and HDD (permanent key-value)."""

import json
import os

MAX_RAM = 12

def _base_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def ram_path():
    return os.path.join(_base_dir(), "memory", "ram.json")

def hdd_path():
    return os.path.join(_base_dir(), "memory", "hdd.json")

def _ensure_dir(path):
    d = os.path.dirname(path)
    if not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def load_json(path, fallback=None):
    if fallback is None:
        fallback = []
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback

def save_json(path, data):
    _ensure_dir(path)
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

def load_ram():
    return load_json(ram_path(), [])

def save_ram(data):
    save_json(ram_path(), data)

def update_ram(role, content):
    ram = load_ram()
    ram.append({"role": role, "content": content})
    while len(ram) > MAX_RAM:
        ram.pop(0)
    save_ram(ram)

def load_hdd():
    return load_json(hdd_path(), {})

def save_hdd(data):
    save_json(hdd_path(), data)

def hdd_get(key):
    hdd = load_hdd()
    return hdd.get(key)

def hdd_set(key, value):
    hdd = load_hdd()
    hdd[key] = value
    save_hdd(hdd)
