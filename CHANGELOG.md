# Changelog

## [3.1.0] — 2026-08-20

### Hierarchical Memory System (memory_tier.h / memory_tier.cpp)
- New three-tier memory architecture replacing the Python-bridge RAM calls
  in `/chat`:
  - **L1 Working Memory** — thread-safe `std::deque` window (default 12
    turns) serialized directly into the LLM context. On overflow, the
    evicted turn is promoted to L2.
  - **L2 Episodic Memory** — in-RAM vector store with cosine-similarity
    retrieval. Dot product is AVX2-accelerated (`_mm256` intrinsics,
    runtime-checked via `__builtin_cpu_supports`) with a scalar fallback.
    Dependency-free embeddings use FNV-1a feature hashing (no ML model).
  - **L3 Semantic / Cold Storage** — native SQLite (`dom_memory.db`, WAL,
    prepared statements, RAII statement wrapper) persisting decayed
    memories across restarts.
- Formal Ebbinghaus decay: `R = M0 * exp(-lambda * t) + S`. Every L2 item
  carries initial strength (M0, novelty-weighted), a `std::chrono`
  timestamp, and a semantic relevance floor (S, from context similarity).
- `MemoryManager` background GC worker (`std::thread` + `std::shared_mutex`
  + `std::condition_variable`): periodically scores L2 items, evicts
  `R < threshold` to L3, and trims L2 beyond capacity by weakest R.
  Defaults `lambda=0.001/s`, threshold `0.35`, 60 s cadence — all
  overridable via `DOM_MEM_*` env vars.
- `/chat` now records turns into L1 in-process (no more `ram:push` /
  `ram:load` bridge round-trips); assistant replies are stored cleaned.
- `/status` now reports memory tier occupancy (`l1_working_turns`,
  `l2_episodic`, `l3_cold_stored`, decay config).
- The Python bridge keeps its `ram:*` commands for `dom_cloud` and
  survival mode, which still use the `conversations` table.

## [3.0.0] — 2026-08-14

### Security Hardening
- Removed every `std::system()` / shell-string path from `main.cpp`.
  All process execution now uses `fork`/`execvp` with explicit argv arrays
  (`execAndWait`, `execDetached`, `execAndCapture`), so user or LLM-derived
  data can never be interpolated through a shell.
- `runShellCommandSync()` is the only shell path left and is restricted to
  trusted static whitelist strings from `shared/dom_commands.json`.
- GROQ requests moved from `curl` + shared temp files to in-process libcurl
  with a per-request in-memory response buffer (no `.request.json` /
  `.response.json` race conditions between concurrent `/chat` threads).
- TTS output uses unique per-request temp files (`.voice.<pid>.<seq>.mp3`);
  stale files are swept at startup and shutdown.
- HTTP server now binds to `127.0.0.1` by default. Cloud deployments
  opt in with `DOM_BIND=0.0.0.0` (added to `render.yaml`).
- Dockerfile: added `libcurl4-openssl-dev` and `-lcurl`.

### Operational QoL
- Timestamped `[INFO]` / `[WARN]` / `[ERROR]` logging replaces raw console output.
- New `GET /status` endpoint: uptime, request counter, connected WebSocket
  clients, bind address/port, GROQ model.
- `/chat` requests are logged with remote IP and payload size.
- Graceful shutdown on SIGINT/SIGTERM: Crow stops accepting traffic, stale
  voice files are cleaned, libcurl is de-initialized, clean exit message.

### Housekeeping
- Removed dead legacy artifacts from the repo: `.request.json`,
  `.response.json`, `.voice.mp3`, `test.mp3`, `dom_interface`, `dom_server`.

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
