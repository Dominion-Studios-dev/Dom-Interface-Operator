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
# Run the interactive terminal (auto-detects cloud / local / survival mode)
./dom

# Run in local-only mode (no cloud server)
./dom --local

# Single message mode
./dom clean my emails

# Build the C++ API server (requires libasio-dev, libcurl, nlohmann-json)
g++ -O3 -std=c++17 main.cpp -lpthread -lcurl -o main
```

## Running the Server

```bash
export GROQ_API_KEY=your_key
export DOM_MASTER_SECRET=your_secret
export DOM_BIND=127.0.0.1   # optional; use 0.0.0.0 for cloud deployments
export PORT=7860            # optional; default 7860
./main
```

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Plain-text health check |
| `/ping` | GET | JSON `{"status": "alive"}` health check |
| `/status` | GET | Uptime, request counter, WebSocket clients, bind/port, model |
| `/telemetry` | WS | Live CPU / memory broadcast every 2s |
| `/chat` | POST | Chat with Dom; requires `Authorization: Bearer $DOM_MASTER_SECRET` |

## Security Model

- The server binds to loopback only by default; cloud deployments opt in with `DOM_BIND=0.0.0.0`.
- `/chat` requires the `DOM_MASTER_SECRET` bearer token.
- User/LLM data never passes through a shell: all process execution uses `fork`/`execvp` with explicit argv arrays.
- Shell commands (`/bin/sh -c`) run only trusted static whitelist entries from `shared/dom_commands.json`.
- GROQ calls use in-process libcurl — no temp files, no shared state between concurrent request threads.

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