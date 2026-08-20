// ============================================================================
// memory_tier.h — D.I.O Hierarchical Memory System
//
// A zero-dependency (except SQLite) three-tier memory architecture inspired
// by CPU cache hierarchies and the Ebbinghaus Forgetting Curve:
//
//   L1 — Working Memory : std::deque of the last N (default 12) conversational
//        turns. Thread-safe, volatile, injected directly into the LLM context.
//   L2 — Episodic Memory : in-memory vector store with cosine-similarity
//        retrieval (AVX2-accelerated dot product). Each item carries an
//        initial strength M0, a creation timestamp, and a semantic relevance
//        score S used by the Ebbinghaus decay model:
//            R = M0 * exp(-lambda * t) + S
//   L3 — Semantic / Cold Storage : native SQLite persistence (dom_memory.db)
//        for memories evicted from L2 when R drops below a threshold.
//
// The MemoryManager orchestrates promotion (L1 -> L2 on deque overflow),
// background garbage collection (L2 -> L3 decay eviction) and recall queries
// spanning L2 + L3.
//
// CONCURRENCY MODEL (documented for maintainers):
//   - L1 and L2 each own a std::shared_mutex (concurrent reads, exclusive
//     writes). Callers never reach into the tiers directly with external
//     locks — every mutation is a small atomic public method.
//   - L3 guards its single sqlite3 connection with its own std::mutex
//     (opened with SQLITE_OPEN_FULLMUTEX as belt-and-braces).
//   - LOCK ORDER DISCIPLINE: no two tier locks are EVER held simultaneously;
//     operations acquire/release sequentially (L1 push -> release -> L2 add,
//     L2 snapshot -> release -> L3 persist -> L2 remove). Deadlock-free by
//     construction.
//
// Copyright (c) 2026 Dominion Studios. All Rights Reserved.
// ============================================================================

#ifndef DOM_MEMORY_TIER_H
#define DOM_MEMORY_TIER_H

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <memory>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <string>
#include <thread>
#include <vector>

// Opaque forward declaration: keeps this header free of any sqlite3 include.
// The full type is only needed in memory_tier.cpp (ColdStorage is fully
// implemented there, and its destructor is declared out-of-line).
struct sqlite3;

namespace dommem {

// ============================================================================
// TIMESTAMP CONVENTION
// ============================================================================
// All memory timestamps use std::chrono::system_clock (wall time), NOT
// steady_clock. Rationale: L3 items are persisted to SQLite as unix seconds;
// system_clock round-trips losslessly across process restarts, which the
// decay math (R = M0*exp(-lambda*t) + S) requires when cold memories are
// recalled after a reboot. NTP clock jumps are tolerable for decay
// arithmetic at these time scales.
using Clock = std::chrono::system_clock;

// ============================================================================
// TIER IDENTIFIER
// ============================================================================
enum class Tier {
    L1,  // working memory (hot, in the LLM context window)
    L2,  // episodic memory (warm, in RAM with embeddings)
    L3   // semantic / cold storage (cold, on disk in SQLite)
};

// ============================================================================
// L1 UNIT — a single conversational turn
// ============================================================================
struct MemoryTurn {
    std::string role;              // "user" | "assistant" | "system"
    std::string content;           // the raw text of the turn
    Clock::time_point created_at;  // when the turn was recorded
};

// ============================================================================
// L2 UNIT — an episodic memory with decay metadata
// ============================================================================
struct EpisodicMemory {
    int64_t id = -1;               // unique id (assigned by EpisodicStore)
    std::string role;              // originating role ("user"/"assistant")
    std::string content;           // the remembered text
    double m0 = 0.7;               // initial strength  (Ebbinghaus M0)
    double s = 0.0;                // semantic relevance (Ebbinghaus S)
    Clock::time_point created_at;  // birth time of this memory
    Clock::time_point last_access; // last read time (for recency weighting)
    std::vector<float> embedding;  // feature-hash vector (see embedText)
};

// A recall hit merged from any tier, with the similarity score used to rank.
struct RecallHit {
    EpisodicMemory memory;
    Tier tier = Tier::L2;
    double score = 0.0;
};

// ============================================================================
// RUNTIME CONFIGURATION (env-overridable, see Config::fromEnv)
// ============================================================================
struct Config {
    double lambda = 0.001;          // Ebbinghaus decay rate, units: 1/second
    double evictThreshold = 0.35;   // L2 -> L3 eviction floor for R
    std::chrono::milliseconds gcInterval{60000};  // GC worker cadence (60 s)
    size_t l1Capacity = 12;         // working-memory window size (LLM context)
    size_t l2Capacity = 512;        // max episodic items kept in RAM
    size_t embedDim = 256;          // embedding vector dimensionality
    std::string dbPath = "dom_memory.db";  // L3 SQLite file

    // Build a Config from environment variables (C++ core convention: env
    // vars only, no .env parsing). Invalid values silently fall back to the
    // defaults so a typo never takes the whole assistant down.
    static Config fromEnv();
};

// ============================================================================
// MATH PRIMITIVES (pure functions, no shared state)
// ============================================================================

// Ebbinghaus retention: R = M0 * exp(-lambda * t) + S.
//   t is the elapsed seconds since the memory was created.
//   S acts as a semantic floor: highly relevant memories never fully decay.
double retentionScore(const EpisodicMemory& m, double lambda);

// Cosine similarity between two embedding vectors in [0, 1].
// Uses an AVX2 kernel when the CPU supports it (runtime-checked), with a
// portable scalar fallback. See memory_tier.cpp for the SIMD details.
double cosineSimilarity(const std::vector<float>& a, const std::vector<float>& b);

// Deterministic, dependency-free text -> vector embedding.
// Tokenizes + lowercases, then feature-hashes tokens (FNV-1a) into a
// fixed-dimension signed bag-of-words vector, L2-normalized. Cosine
// similarity on these vectors approximates lexical overlap — enough for
// recall queries without shipping a neural embedding model.
std::vector<float> embedText(const std::string& text, size_t dim = 256);

// ============================================================================
// L1 — WORKING MEMORY (thread-safe rolling deque)
// ============================================================================
class WorkingMemory {
public:
    explicit WorkingMemory(size_t capacity = 12);

    // Append a turn. If the deque is at capacity, the OLDEST turn is
    // evicted and returned (caller promotes it to L2). Nullopt = no eviction.
    std::optional<MemoryTurn> push(const std::string& role, const std::string& content);

    // Snapshot of the current window, oldest -> newest. This is what gets
    // serialized into the LLM context window.
    std::vector<MemoryTurn> context() const;

    void clear();                      // wipe the window (fresh session)
    size_t size() const;
    size_t capacity() const;

private:
    size_t capacity_;
    std::deque<MemoryTurn> turns_;     // oldest at front, newest at back
    mutable std::shared_mutex mutex_;  // shared = readers, unique = writers
};

// ============================================================================
// L2 — EPISODIC MEMORY (in-memory vector store, cosine retrieval)
// ============================================================================
class EpisodicStore {
public:
    // Insert a memory (id is assigned internally). Returns the assigned id.
    int64_t add(EpisodicMemory memory);

    // Top-k memories most similar to the query embedding, ranked desc.
    std::vector<EpisodicMemory> queryTopK(const std::vector<float>& queryEmbedding,
                                          size_t k) const;

    // Full snapshot for the GC worker (decay scoring + eviction decision).
    std::vector<EpisodicMemory> snapshot() const;

    // Bulk remove (GC evictions). Unknown ids are silently ignored.
    void removeMany(const std::vector<int64_t>& ids);

    // Bump last_access to now (recall refreshes the item).
    void touch(int64_t id);

    void clear();
    size_t size() const;

private:
    int64_t nextId_ = 1;               // monotonically increasing id source
    std::vector<EpisodicMemory> items_;
    mutable std::shared_mutex mutex_;
};

// ============================================================================
// L3 — SEMANTIC / COLD STORAGE (native SQLite)
// ============================================================================
//
// RAII wrapper around sqlite3. The connection is opened with
// SQLITE_OPEN_FULLMUTEX, WAL journaling and a busy timeout; every statement
// is prepared once and reused (prepared-statement caching), every API call
// is checked, and failures surface as std::runtime_error with the real
// sqlite3 error message attached.
class ColdStorage {
public:
    explicit ColdStorage(std::string dbPath);
    ~ColdStorage();  // closes the connection (RAII)

    ColdStorage(const ColdStorage&) = delete;
    ColdStorage& operator=(const ColdStorage&) = delete;

    // Persist one episodic memory (embedding stored as a raw float blob).
    void persist(const EpisodicMemory& m);

    // Cold recall: scan all stored embeddings, cosine-rank against the query
    // vector, return the top-k as (score, memory) pairs, ranked desc.
    // A linear scan is intentional: cold storage is not latency-critical and
    // an exact scan beats ANN index complexity at this scale. FTS can be
    // layered on later if content grows beyond ~10k memories.
    std::vector<std::pair<double, EpisodicMemory>> search(
        const std::vector<float>& queryEmbedding, size_t k) const;

    size_t count() const;
    void clear();

private:
    void execSafe(const char* sql);  // run schema/pragma DDL, checked + RAII

    mutable std::mutex mutex_;         // guards the single connection
    sqlite3* db_ = nullptr;
};

// ============================================================================
// MEMORY MANAGER — orchestrates the tiers + background GC worker
// ============================================================================
class MemoryManager {
public:
    explicit MemoryManager(Config cfg = Config::fromEnv());
    ~MemoryManager();  // stops + joins the GC worker (RAII)

    MemoryManager(const MemoryManager&) = delete;
    MemoryManager& operator=(const MemoryManager&) = delete;

    // --- L1 (working memory) -----------------------------------------------
    // Record a turn in the window. On overflow the evicted turn is promoted
    // to L2 with significance scoring (novelty-weighted M0, context-relevance
    // S). This is the ONLY promotion path (L1 stays a strict 12-turn window).
    void addTurn(const std::string& role, const std::string& content);

    // LLM context: current window as role/content pairs, oldest -> newest.
    std::vector<MemoryTurn> context() const;

    // --- Recall (L2 + L3) ---------------------------------------------------
    // Semantic recall: embed the query, hit L2, fall through to L3 (cold
    // scan), merge and rank. Touches (refreshes) L2 hits, so it mutates
    // internal state — hence not const.
    std::vector<RecallHit> recall(const std::string& query, size_t k = 5);

    // --- GC ------------------------------------------------------------------
    // One pass of the decay eviction: score every L2 item with the Ebbinghaus
    // formula, evict R < threshold to L3, and trim L2 beyond capacity by
    // weakest R. Public so tests / diagnostics can drive it synchronously.
    void runGarbageCollection();

    // --- Introspection --------------------------------------------------------
    struct Stats {
        size_t l1_turns = 0;
        size_t l2_episodes = 0;
        size_t l3_stored = 0;
    };
    Stats stats() const;

    const Config& config() const { return cfg_; }

private:
    void gcWorkerLoop();  // background thread body

    Config cfg_;
    WorkingMemory l1_;
    EpisodicStore l2_;
    std::unique_ptr<ColdStorage> l3_;   // heap-allocated: movable-friendly RAII

    // GC worker plumbing: stop flag + condition variable so shutdown is
    // prompt (notify wakes the worker out of its sleep immediately).
    std::atomic<bool> stop_{false};
    mutable std::mutex gcWakeMutex_;
    std::condition_variable gcWakeCv_;
    std::thread gcThread_;
};

}  // namespace dommem

#endif  // DOM_MEMORY_TIER_H