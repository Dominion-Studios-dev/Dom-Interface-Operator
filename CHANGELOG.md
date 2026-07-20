# Changelog

## [2.0.0] — 2026-07-21

### Render.com Docker Deployment
- C++ Crow servers (`main.cpp`, `dom_cloud/main.cpp`) now bind to `0.0.0.0` for container-friendly networking.
- Default port `7860`, configurable via `PORT` environment variable (Render convention).
- Added `GET /ping` health check endpoint returning `{"status": "alive", "engine": "Dom C++ Core"}`.
- Dockerfiles use `ENV PORT=7860` and `EXPOSE ${PORT}` so Render can inject its own port.
- Removed `wget`, `python3`, `python3-pip` from Docker images — `curl` is the only runtime dependency.
- Added `-std=c++17` to g++ build flags for modern C++ support.
- Both `render.yaml` files declare `GROQ_API_KEY` as a required non-synced environment variable.

### Path Safety (Parentheses in Directory Names)
- All shell command paths in `fireGroqRequest()` are now wrapped in double quotes, preventing bash syntax errors when the working directory contains parentheses (e.g., `(a)Dominion-Studios`).
- `speakText()` voice output paths (`.voice.mp3`) are now double-quoted in shell commands.

### Environment & Security Clean-up
- Removed all plain-text API keys and credentials from `.env` (now contains only placeholders).
- Created `.env.example` as a safe reference template.
- C++ servers read `GROQ_API_KEY` exclusively via `std::getenv()` — no `.env` file parsing.
- Python scripts (`engine.py`, `emails.py`, `process_emails.py`) read all credentials via `os.getenv()` — no `.env` file parsing.
- Expanded `.gitignore` to cover `.env.*` (except `.env.example`), `*.log`, `logs/`, `build/`, `dist/`.
- Error messages no longer reference `.env` file fallback — credentials must come from environment variables.

### File Consolidation
- `shared/` is now the single source of truth for `dom_rules.txt` and `dom_commands.json`.
- Removed 6 duplicate copies: root, `dom_cloud/`, `dom_sandbox/`, and `dom_survival/`.
- C++ servers reference `shared/dom_rules.txt` and `shared/dom_commands.json`.
- Python survival mode (`core/rules.py`, `plugins/system.py`) reference `shared/` via relative paths.
