# D.I.O (Dom Interface Operator)

A modular, terminal-native AI desktop assistant.

## Features

- **Modular CLI Architecture** — Drop Python scripts into `modules/` and they auto-load on startup. No config editing needed.
- **Smart Routing** — User input is matched against module triggers first; unmatched queries fall through to a local or cloud LLM.
- **Automation Scripts** — Email cleaning, system maintenance, and hardware monitoring built in.
- **Todo & Notes** — Lightweight task and note management stored locally.
- **Custom Integrations** — Extend with your own modules, plugins, and system scripts.

## Quickstart

```bash
# Run the interactive terminal
./dom

# Run in local-only mode (no cloud server)
./dom --local

# Single message mode
./dom clean my emails
```

## Adding a Module

1. Copy `modules/template.py` to `modules/my_module.py`.
2. Set `TRIGGERS` to a list of phrases that should activate your module.
3. Implement `execute(user_input)` returning `{"status": "success"|"error", "output": "..."}`.
4. Restart `./dom` — your module loads automatically.

```python
from modules.util import log_info

TRIGGERS = ["hello", "greet"]

def execute(user_input: str) -> dict:
    return {"status": "success", "output": "Hello, Master."}
```

## License
Copyright (c) 2026 Dominion Studios. All Rights Reserved.

This repository and its source code are made available solely for academic and educational review.

No permission is granted to copy, modify, distribute, sublicense, run, or reuse any part of this software for any purpose without explicit written consent from the copyright holder.

