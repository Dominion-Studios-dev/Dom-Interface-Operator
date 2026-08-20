// ============================================================================
// memory_tier.cpp — D.I.O Hierarchical Memory System (implementation)
//
// Implements the three tiers declared in memory_tier.h:
//   L1 WorkingMemory  — thread-safe rolling deque (the LLM context window)
//   L2 EpisodicStore  — vector store + AVX2 cosine similarity
//   L3 ColdStorage    — native SQLite persistence (dom_memory.db, WAL)
// plus the MemoryManager (promotion, Ebbinghaus decay GC, recall) and the
// dependency-free feature-hash embedding used for semantic matching.
//
// Copyright (c) 2026 Dominion Studios. All Rights Reserved.
// ============================================================================

#include "memory_tier.h"

#include <immintrin.h>   // AVX2 intrinsics (_mm256_*)
#include <sqlite3.h>     // native SQLite C API

#include <algorithm>
#include <cmath>
#include <cstdlib>        // std::getenv, std::strtod
#include <cstring>
#include <stdexcept>
#include <unordered_set>

namespace dommem {

// ============================================================================
// CONFIG
// ============================================================================

Config Config::fromEnv() {
    Config c;

    // Small helper: parse a positive double env var, else keep the default.
    auto envDouble = [](const char* name, double fallback) -> double {
        const char* raw = std::getenv(name);
        if (!raw || !*raw) return fallback;
        char* end = nullptr;
        const double v = std::strtod(raw, &end);
        return (end != raw && v > 0.0) ? v : fallback;
    };
    // Small helper: parse a positive size_t env var, else keep the default.
    auto envSize = [](const char* name, size_t fallback) -> size_t {
        const char* raw = std::getenv(name);
        if (!raw || !*raw) return fallback;
        char* end = nullptr;
        const long v = std::strtol(raw, &end, 10);
        return (end != raw && v > 0) ? static_cast<size_t>(v) : fallback;
    };

    const char* db = std::getenv("DOM_MEM_DB_PATH");
    if (db && *db) c.dbPath = db;

    c.lambda          = envDouble("DOM_MEM_LAMBDA", c.lambda);
    c.evictThreshold  = envDouble("DOM_MEM_EVICT_THRESHOLD", c.evictThreshold);
    c.gcInterval      = std::chrono::milliseconds(
        envSize("DOM_MEM_GC_INTERVAL_MS",
                static_cast<size_t>(c.gcInterval.count())));
    c.l1Capacity      = envSize("DOM_MEM_L1_CAPACITY", c.l1Capacity);
    c.l2Capacity      = envSize("DOM_MEM_L2_CAPACITY", c.l2Capacity);
    c.embedDim        = envSize("DOM_MEM_EMBED_DIM", c.embedDim);
    return c;
}

// ============================================================================
// MATH PRIMITIVES
// ============================================================================

// Ebbinghaus Forgetting Curve: R = M0 * exp(-lambda * t) + S.
//   - M0: initial strength of the memory at creation.
//   - t  : elapsed wall-clock seconds since creation.
//   - S  : semantic relevance floor — a memory that is semantically tied to
//          the conversation (S high) decays to S, never to zero. This models
//          "meaningful" memories resisting the curve, per the Ebbinghaus
//          "overlearning / relevance" refinements.
double retentionScore(const EpisodicMemory& m, double lambda) {
    const double elapsedSeconds =
        std::chrono::duration<double>(Clock::now() - m.created_at).count();
    if (elapsedSeconds < 0.0) return m.m0 + m.s;  // clock skew guard
    return m.m0 * std::exp(-lambda * elapsedSeconds) + m.s;
}

// ---------------------------------------------------------------------------
// AVX2 ACCELERATED DOT PRODUCT
// ---------------------------------------------------------------------------
// The AVX2 kernel is compiled with a function-specific target attribute, so
// the rest of the translation unit (and the whole project) never needs
// -mavx2. Runtime detection (__builtin_cpu_supports) decides which path to
// take per-process; the scalar path always remains as a portable fallback.
// ---------------------------------------------------------------------------

#if defined(__GNUC__) || defined(__clang__)
__attribute__((target("avx2")))
#endif
static double dotProductAvx2(const float* a, const float* b, size_t n) {
    __m256 acc = _mm256_setzero_ps();
    size_t i = 0;

    // Process 8 floats (one full YMM register) per iteration.
    for (; i + 8 <= n; i += 8) {
        const __m256 va = _mm256_loadu_ps(a + i);  // unaligned-safe loads
        const __m256 vb = _mm256_loadu_ps(b + i);
        acc = _mm256_add_ps(_mm256_mul_ps(va, vb), acc);  // FMA-free: wider
                                                          // CPU compatibility
    }

    // Horizontally reduce the 8 lanes and finish any tail elements.
    alignas(32) float lanes[8];
    _mm256_store_ps(lanes, acc);
    double dot = static_cast<double>(lanes[0]) + static_cast<double>(lanes[1]) +
                 static_cast<double>(lanes[2]) + static_cast<double>(lanes[3]) +
                 static_cast<double>(lanes[4]) + static_cast<double>(lanes[5]) +
                 static_cast<double>(lanes[6]) + static_cast<double>(lanes[7]);
    for (; i < n; ++i) dot += static_cast<double>(a[i]) * b[i];
    return dot;
}

// Portable scalar dot product (always available).
static double dotProductScalar(const float* a, const float* b, size_t n) {
    double dot = 0.0;
    for (size_t i = 0; i < n; ++i)
        dot += static_cast<double>(a[i]) * b[i];
    return dot;
}

// One-time CPU feature probe. __builtin_cpu_supports requires a prior
// __builtin_cpu_init() (glibc does this implicitly on modern systems, but
// we call it explicitly so the behavior is defined on every platform).
static bool cpuHasAvx2() {
    static const bool kAvx2 = []() {
        __builtin_cpu_init();
        return __builtin_cpu_supports("avx2");
    }();
    return kAvx2;
}

// ---------------------------------------------------------------------------
// COSINE SIMILARITY
// ---------------------------------------------------------------------------
// cos(a, b) = dot(a,b) / (|a| * |b|), clamped to [0,1]. Zero-norm vectors
// (empty embeddings) yield 0.0 similarity instead of NaN.
double cosineSimilarity(const std::vector<float>& a, const std::vector<float>& b) {
    const size_t n = std::min(a.size(), b.size());
    if (n == 0) return 0.0;

    const double dot = cpuHasAvx2() ? dotProductAvx2(a.data(), b.data(), n)
                                    : dotProductScalar(a.data(), b.data(), n);
    const double normA = std::sqrt(dotProductScalar(a.data(), a.data(), n));
    const double normB = std::sqrt(dotProductScalar(b.data(), b.data(), n));
    if (normA <= 0.0 || normB <= 0.0) return 0.0;

    const double cos = dot / (normA * normB);
    return std::clamp(cos, 0.0, 1.0);  // lexical overlap can't be negative
}

// ---------------------------------------------------------------------------
// DEPENDENCY-FREE EMBEDDING — feature hashing
// ---------------------------------------------------------------------------
// Classic "hashing trick" bag-of-words: each token is FNV-1a hashed; the hash
// selects a dimension (index = hash % dim) and a sign (bit 63), so token
// collisions average out across dimensions. The result is L2-normalized.
// Deterministic across processes — embeddings stored in L3 remain valid for
// recall after restarts, which is a hard requirement for this design.
// ---------------------------------------------------------------------------

static uint64_t fnv1a(const std::string& s) {
    uint64_t hash = 1469598103934665603ULL;  // FNV-1a 64-bit offset basis
    for (const unsigned char c : s) {
        hash ^= static_cast<uint64_t>(c);
        hash *= 1099511628211ULL;            // FNV-1a 64-bit prime
    }
    return hash;
}

std::vector<float> embedText(const std::string& text, size_t dim) {
    std::vector<float> vec(dim, 0.0f);
    if (dim == 0) return vec;

    // Tokenize: split on anything that is not alphanumeric, lowercased.
    std::string token;
    token.reserve(32);
    for (const unsigned char c : text) {
        if (std::isalnum(c)) {
            token.push_back(static_cast<char>(std::tolower(c)));
        } else if (!token.empty()) {
            const uint64_t h = fnv1a(token);
            const size_t idx = static_cast<size_t>(h % dim);
            vec[idx] += (h & (1ULL << 63)) ? -1.0f : 1.0f;
            token.clear();
        }
    }
    if (!token.empty()) {  // flush the final token
        const uint64_t h = fnv1a(token);
        const size_t idx = static_cast<size_t>(h % dim);
        vec[idx] += (h & (1ULL << 63)) ? -1.0f : 1.0f;
    }

    // L2-normalize so cosine similarity behaves as a pure angle metric.
    double norm = 0.0;
    for (const float v : vec) norm += static_cast<double>(v) * v;
    norm = std::sqrt(norm);
    if (norm > 0.0) {
        for (float& v : vec) v = static_cast<float>(static_cast<double>(v) / norm);
    }
    return vec;
}

// ============================================================================
// L1 — WORKING MEMORY
// ============================================================================

WorkingMemory::WorkingMemory(size_t capacity) : capacity_(capacity) {
    // Guard against a zero/absurd capacity: a window of < 1 makes no sense.
    if (capacity_ == 0) capacity_ = 1;
}

std::optional<MemoryTurn> WorkingMemory::push(const std::string& role,
                                              const std::string& content) {
    MemoryTurn turn{role, content, Clock::now()};
    std::optional<MemoryTurn> evicted;

    std::unique_lock<std::shared_mutex> lock(mutex_);
    if (turns_.size() >= capacity_) {
        evicted = std::move(turns_.front());  // oldest turn leaves the window
        turns_.pop_front();
    }
    turns_.push_back(std::move(turn));
    return evicted;  // caller (MemoryManager) promotes this to L2
}

std::vector<MemoryTurn> WorkingMemory::context() const {
    std::shared_lock<std::shared_mutex> lock(mutex_);
    return {turns_.begin(), turns_.end()};  // copy: snapshot for the LLM
}

void WorkingMemory::clear() {
    std::unique_lock<std::shared_mutex> lock(mutex_);
    turns_.clear();
}

size_t WorkingMemory::size() const {
    std::shared_lock<std::shared_mutex> lock(mutex_);
    return turns_.size();
}

size_t WorkingMemory::capacity() const { return capacity_; }

// ============================================================================
// L2 — EPISODIC MEMORY
// ============================================================================

int64_t EpisodicStore::add(EpisodicMemory memory) {
    std::unique_lock<std::shared_mutex> lock(mutex_);
    memory.id = nextId_++;
    memory.created_at = Clock::now();   // L2 birth time drives the decay clock
    memory.last_access = memory.created_at;
    items_.push_back(std::move(memory));
    return items_.back().id;
}

std::vector<EpisodicMemory> EpisodicStore::queryTopK(
    const std::vector<float>& queryEmbedding, size_t k) const {
    std::shared_lock<std::shared_mutex> lock(mutex_);
    if (k == 0 || items_.empty()) return {};

    // Score everything, then partial-sort so only the top-k are ordered —
    // O(n log k) instead of a full O(n log n) sort on every recall.
    std::vector<std::pair<double, size_t>> scored;  // (score, index)
    scored.reserve(items_.size());
    for (size_t i = 0; i < items_.size(); ++i) {
        scored.emplace_back(
            cosineSimilarity(queryEmbedding, items_[i].embedding), i);
    }
    const size_t take = std::min(k, scored.size());
    std::partial_sort(scored.begin(), scored.begin() + take, scored.end(),
                      [](const auto& a, const auto& b) { return a.first > b.first; });

    std::vector<EpisodicMemory> result;
    result.reserve(take);
    for (size_t i = 0; i < take; ++i)
        result.push_back(items_[scored[i].second]);
    return result;
}

std::vector<EpisodicMemory> EpisodicStore::snapshot() const {
    std::shared_lock<std::shared_mutex> lock(mutex_);
    return items_;
}

void EpisodicStore::removeMany(const std::vector<int64_t>& ids) {
    if (ids.empty()) return;
    std::unique_lock<std::shared_mutex> lock(mutex_);
    // Mark-and-sweep: build a set for O(1) membership, then erase.
    // This keeps O(n) total instead of O(n * ids) with repeated find-erase.
    std::unordered_set<int64_t> doomed(ids.begin(), ids.end());
    items_.erase(std::remove_if(items_.begin(), items_.end(),
                                [&](const EpisodicMemory& m) {
                                    return doomed.count(m.id) > 0;
                                }),
                 items_.end());
}

void EpisodicStore::touch(int64_t id) {
    std::unique_lock<std::shared_mutex> lock(mutex_);
    const auto now = Clock::now();
    for (auto& m : items_) {
        if (m.id == id) {
            m.last_access = now;
            return;
        }
    }
}

void EpisodicStore::clear() {
    std::unique_lock<std::shared_mutex> lock(mutex_);
    items_.clear();
}

size_t EpisodicStore::size() const {
    std::shared_lock<std::shared_mutex> lock(mutex_);
    return items_.size();
}

// ============================================================================
// L3 — COLD STORAGE (native SQLite)
// ============================================================================
//
// RAII statement wrapper: prepares once, reuses across calls, always
// finalizes in the destructor. Move-only (no accidental copies of a live
// statement).
// ----------------------------------------------------------------------------

namespace {

class Stmt {
public:
    Stmt(sqlite3* db, const char* sql) : stmt_(nullptr) {
        // Prepare the statement; on failure throw with the DB error text so
        // the caller always learns the real cause (schema drift, corrupt db).
        const int rc = sqlite3_prepare_v2(db, sql, -1, &stmt_, nullptr);
        if (rc != SQLITE_OK) {
            const std::string err = sqlite3_errmsg(db);
            throw std::runtime_error("SQLite prepare failed: " + err);
        }
    }
    ~Stmt() {
        if (stmt_) sqlite3_finalize(stmt_);  // RAII: always release
    }
    Stmt(const Stmt&) = delete;
    Stmt& operator=(const Stmt&) = delete;

    sqlite3_stmt* get() const { return stmt_; }

    // Execute a statement that returns no rows (INSERT/UPDATE/DELETE).
    void step() {
        const int rc = sqlite3_step(stmt_);
        if (rc != SQLITE_DONE) {
            const std::string err = sqlite3_errmsg(sqlite3_db_handle(stmt_));
            throw std::runtime_error("SQLite step failed (rc=" +
                                     std::to_string(rc) + "): " + err);
        }
        sqlite3_reset(stmt_);  // rewind for reuse
    }

    // Bind a signed 64-bit integer.
    void bind(int idx, int64_t v) { sqlite3_bind_int64(stmt_, idx, v); }
    // Bind a UTF-8 string (SQLITE_TRANSIENT: SQLite copies the bytes).
    void bind(int idx, const std::string& v) {
        sqlite3_bind_text(stmt_, idx, v.c_str(), static_cast<int>(v.size()),
                          SQLITE_TRANSIENT);
    }
    // Bind a double.
    void bind(int idx, double v) { sqlite3_bind_double(stmt_, idx, v); }
    // Bind a raw float blob (the embedding vector).
    void bind(int idx, const std::vector<float>& v) {
        sqlite3_bind_blob(stmt_, idx, v.data(),
                          static_cast<int>(v.size() * sizeof(float)),
                          SQLITE_TRANSIENT);
    }
    // Reset bindings so the statement can be reused with fresh values.
    void reset() { sqlite3_reset(stmt_); sqlite3_clear_bindings(stmt_); }

private:
    sqlite3_stmt* stmt_;
};

}  // namespace

ColdStorage::ColdStorage(std::string dbPath) {
    // SQLITE_OPEN_FULLMUTEX: serializes access at the C-API level even
    // though we also guard with our own mutex — defense in depth for any
    // future path that forgets to take the mutex.
    const int flags = SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE |
                      SQLITE_OPEN_FULLMUTEX;
    const int rc = sqlite3_open_v2(dbPath.c_str(), &db_, flags, nullptr);
    if (rc != SQLITE_OK) {
        std::string err = db_ ? sqlite3_errmsg(db_) : "unknown sqlite error";
        if (db_) sqlite3_close(db_);  // release partial handle before throwing
        db_ = nullptr;
        throw std::runtime_error("Failed to open L3 memory database '" +
                                 dbPath + "': " + err);
    }

    // ---- Durability pragmas -------------------------------------------------
    // WAL: concurrent readers + single writer, far better crash safety than
    // the default rollback journal, and reads never block writes.
    execSafe("PRAGMA journal_mode=WAL;");
    execSafe("PRAGMA synchronous=NORMAL;");   // fsync on checkpoint, not every
                                              // commit (WAL is crash-safe here)
    execSafe("PRAGMA busy_timeout=5000;");    // wait 5s instead of failing on
                                              // a locked db (another process)

    // ---- Schema ---------------------------------------------------------------
    // l3_memories mirrors the in-memory EpisodicMemory struct. created_at /
    // last_access are stored as unix seconds (INTEGER) so the Ebbinghaus
    // decay can be recomputed after a process restart.
    execSafe(
        "CREATE TABLE IF NOT EXISTS l3_memories ("
        "  id          INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  role        TEXT    NOT NULL,"
        "  content     TEXT    NOT NULL,"
        "  m0          REAL    NOT NULL,"
        "  s           REAL    NOT NULL,"
        "  created_at  INTEGER NOT NULL,"
        "  last_access INTEGER NOT NULL,"
        "  embedding   BLOB"                      // raw float32 vector
        ");");
    execSafe("CREATE INDEX IF NOT EXISTS idx_l3_created ON l3_memories(created_at);");
}

ColdStorage::~ColdStorage() {
    // Guard: another thread may be mid-persist when we destruct (only
    // happens on teardown races; take the lock to be strictly correct).
    std::lock_guard<std::mutex> lock(mutex_);
    if (db_) {
        sqlite3_close(db_);  // finalize checkpoints WAL and frees the handle
        db_ = nullptr;
    }
}

void ColdStorage::execSafe(const char* sql) {
    char* errMsg = nullptr;
    const int rc = sqlite3_exec(db_, sql, nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        std::string err = errMsg ? errMsg : "unknown error";
        sqlite3_free(errMsg);
        throw std::runtime_error("SQLite exec failed: " + err);
    }
}

void ColdStorage::persist(const EpisodicMemory& m) {
    std::lock_guard<std::mutex> lock(mutex_);
    // Prepared once per call is acceptable (GC evicts in bursts, not hot
    // paths); the statement is still prepared/finalized via RAII.
    Stmt stmt(db_,
              "INSERT INTO l3_memories (role, content, m0, s, created_at,"
              "                         last_access, embedding)"
              "VALUES (?, ?, ?, ?, ?, ?, ?)");
    stmt.bind(1, m.role);
    stmt.bind(2, m.content);
    stmt.bind(3, m.m0);
    stmt.bind(4, m.s);
    stmt.bind(5, static_cast<int64_t>(
                    std::chrono::duration_cast<std::chrono::seconds>(
                        m.created_at.time_since_epoch()).count()));
    stmt.bind(6, static_cast<int64_t>(
                    std::chrono::duration_cast<std::chrono::seconds>(
                        m.last_access.time_since_epoch()).count()));
    stmt.bind(7, m.embedding);
    stmt.step();
}

std::vector<std::pair<double, EpisodicMemory>> ColdStorage::search(
    const std::vector<float>& queryEmbedding, size_t k) const {
    std::lock_guard<std::mutex> lock(mutex_);
    if (k == 0) return {};

    Stmt stmt(db_,
              "SELECT id, role, content, m0, s, created_at, last_access,"
              "       embedding FROM l3_memories");

    std::vector<std::pair<double, EpisodicMemory>> scored;
    while (true) {
        const int rc = sqlite3_step(stmt.get());
        if (rc == SQLITE_DONE) break;
        if (rc != SQLITE_ROW) {
            throw std::runtime_error(
                "L3 scan failed: " + std::string(sqlite3_errmsg(db_)));
        }

        EpisodicMemory m;
        m.id          = sqlite3_column_int64(stmt.get(), 0);
        m.role        = reinterpret_cast<const char*>(sqlite3_column_text(stmt.get(), 1));
        m.content     = reinterpret_cast<const char*>(sqlite3_column_text(stmt.get(), 2));
        m.m0          = sqlite3_column_double(stmt.get(), 3);
        m.s           = sqlite3_column_double(stmt.get(), 4);
        const int64_t created = sqlite3_column_int64(stmt.get(), 5);
        const int64_t accessed = sqlite3_column_int64(stmt.get(), 6);
        m.created_at  = Clock::time_point(std::chrono::seconds(created));
        m.last_access = Clock::time_point(std::chrono::seconds(accessed));

        // Decode the embedding blob back into a float vector.
        const int bytes = sqlite3_column_bytes(stmt.get(), 7);
        if (bytes > 0) {
            const auto* raw =
                static_cast<const float*>(sqlite3_column_blob(stmt.get(), 7));
            m.embedding.assign(raw, raw + bytes / static_cast<int>(sizeof(float)));
        }

        scored.emplace_back(cosineSimilarity(queryEmbedding, m.embedding),
                            std::move(m));
    }

    // Rank desc, keep top-k. Cold recall is rare — a full sort is fine.
    std::sort(scored.begin(), scored.end(),
              [](const auto& a, const auto& b) { return a.first > b.first; });
    if (scored.size() > k) scored.resize(k);
    return scored;
}

size_t ColdStorage::count() const {
    std::lock_guard<std::mutex> lock(mutex_);
    Stmt stmt(db_, "SELECT COUNT(*) FROM l3_memories");
    if (sqlite3_step(stmt.get()) != SQLITE_ROW)
        throw std::runtime_error("L3 count failed: " +
                                 std::string(sqlite3_errmsg(db_)));
    return static_cast<size_t>(sqlite3_column_int64(stmt.get(), 0));
}

void ColdStorage::clear() {
    std::lock_guard<std::mutex> lock(mutex_);
    Stmt stmt(db_, "DELETE FROM l3_memories");
    stmt.step();
}

// ============================================================================
// MEMORY MANAGER
// ============================================================================

MemoryManager::MemoryManager(Config cfg)
    : cfg_(std::move(cfg)),
      l1_(cfg_.l1Capacity),
      l3_(std::make_unique<ColdStorage>(cfg_.dbPath)) {
    // Start the background GC worker. It waits on a condition variable so
    // destruction can wake it immediately instead of a long sleep.
    gcThread_ = std::thread([this]() { gcWorkerLoop(); });
}

MemoryManager::~MemoryManager() {
    // Signal + wake the worker, then join. The worker never touches L1/L2/L3
    // after stop_ is observed, so teardown is race-free by construction.
    stop_.store(true);
    gcWakeCv_.notify_all();
    if (gcThread_.joinable()) gcThread_.join();
}

void MemoryManager::addTurn(const std::string& role, const std::string& content) {
    // L1 push. The deque returns the evicted turn only when at capacity —
    // that eviction is the trigger for L2 promotion (strict 12-turn window).
    auto evicted = l1_.push(role, content);
    if (!evicted) return;  // window not full yet: stay in working memory

    // --- Promotion: L1 -> L2 ------------------------------------------------
    // NOTE: compute the embedding from the source string BEFORE moving it —
    // std::move leaves the source in an unspecified (typically empty) state,
    // and an empty embedding would poison every future similarity score.
    EpisodicMemory memory;
    memory.role = evicted->role;
    memory.content = evicted->content;
    memory.embedding = embedText(memory.content, cfg_.embedDim);
    evicted->content.clear();  // release the duplicated buffer now

    // Snapshot the current L2 and L1 windows for significance scoring.
    // (Taken *after* the push so the fresh turn counts as context.)
    const auto l2Snapshot = l2_.snapshot();
    const auto l1Context = l1_.context();
    double maxSim = 0.0;
    for (const auto& existing : l2Snapshot)
        maxSim = std::max(maxSim,
                          cosineSimilarity(memory.embedding, existing.embedding));
    memory.m0 = 0.5 + 0.5 * (1.0 - maxSim);
    double relevance = 0.0;
    for (const auto& turn : l1Context)
        relevance = std::max(relevance, cosineSimilarity(
            memory.embedding, embedText(turn.content, cfg_.embedDim)));
    memory.s = std::clamp(relevance, 0.0, 1.0);

    l2_.add(std::move(memory));  // now lives in episodic memory
}

std::vector<MemoryTurn> MemoryManager::context() const {
    return l1_.context();  // oldest -> newest, ready for LLM serialization
}

std::vector<RecallHit> MemoryManager::recall(const std::string& query,
                                             size_t k) {
    if (k == 0 || query.empty()) return {};
    const auto q = embedText(query, cfg_.embedDim);

    std::vector<RecallHit> hits;

    // Tier 1: hot episodic memory (L2) — cosine top-k.
    for (const auto& m : l2_.queryTopK(q, k)) {
        hits.push_back({m, Tier::L2, cosineSimilarity(q, m.embedding)});
    }

    // Tier 2: cold storage (L3) — SQLite scan + cosine rank.
    for (const auto& [score, m] : l3_->search(q, k)) {
        hits.push_back({m, Tier::L3, score});
    }

    // Merge-rank across tiers, keep the global top-k.
    std::sort(hits.begin(), hits.end(),
              [](const RecallHit& a, const RecallHit& b) {
                  return a.score > b.score;
              });
    if (hits.size() > k) hits.resize(k);

    // Refresh last_access on L2 hits (recency feedback for future decay).
    for (const auto& hit : hits) {
        if (hit.tier == Tier::L2) l2_.touch(hit.memory.id);
    }
    return hits;
}

void MemoryManager::runGarbageCollection() {
    // 1) Snapshot L2 (shared lock, released before any write) — the worker
    //    never holds two tier locks at once (see lock-order notes in header).
    auto items = l2_.snapshot();
    if (items.empty()) return;

    // 2) Score every item with the Ebbinghaus curve and pick eviction
    //    candidates: R below the threshold, or (on overflow) the weakest R.
    const double lambda = cfg_.lambda;
    const double floor = cfg_.evictThreshold;

    std::vector<int64_t> evictIds;
    std::vector<std::pair<double, int64_t>> survivors;  // (R, id), R >= floor

    for (const auto& m : items) {
        const double r = retentionScore(m, lambda);
        if (r < floor) {
            evictIds.push_back(m.id);   // decayed below threshold -> cold
        } else {
            survivors.emplace_back(r, m.id);
        }
    }

    // Capacity trim: if we still exceed l2Capacity after decay eviction,
    // evict the weakest survivors (lowest R) until we fit.
    const size_t afterDecay = items.size() - evictIds.size();
    if (afterDecay > cfg_.l2Capacity) {
        std::sort(survivors.begin(), survivors.end());  // ascending R
        const size_t overflow = afterDecay - cfg_.l2Capacity;
        for (size_t i = 0; i < overflow && i < survivors.size(); ++i)
            evictIds.push_back(survivors[i].second);
    }

    if (evictIds.empty()) return;

    // 3) Persist evicted items to L3 (their own mutex), then drop from L2.
    for (const auto& m : items) {
        if (std::find(evictIds.begin(), evictIds.end(), m.id) != evictIds.end()) {
            try {
                l3_->persist(m);  // cold storage: survives restarts
            } catch (const std::exception& e) {
                // Never let a storage failure kill the GC worker; the item
                // simply stays in L2 until the next pass.
                std::fprintf(stderr,
                             "[memory] L3 persist failed for id=%lld: %s\n",
                             static_cast<long long>(m.id), e.what());
            }
        }
    }
    l2_.removeMany(evictIds);
}

MemoryManager::Stats MemoryManager::stats() const {
    Stats s;
    s.l1_turns = l1_.size();
    s.l2_episodes = l2_.size();
    try {
        s.l3_stored = l3_->count();
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[memory] L3 count failed: %s\n", e.what());
    }
    return s;
}

void MemoryManager::gcWorkerLoop() {
    // Wait on the condition variable with a timeout equal to the GC cadence.
    // notify_all() on shutdown wakes us immediately; the stop_ flag then
    // terminates the loop without ever touching tier state.
    std::unique_lock<std::mutex> lock(gcWakeMutex_);
    while (!stop_.load()) {
        gcWakeCv_.wait_for(lock, cfg_.gcInterval, [this]() {
            return stop_.load();  // predicate form: no spurious-wake drift
        });
        if (stop_.load()) break;

        try {
            runGarbageCollection();
        } catch (const std::exception& e) {
            // The GC must never crash the assistant; log and keep going.
            std::fprintf(stderr, "[memory] GC pass failed: %s\n", e.what());
        }
    }
}

}  // namespace dommem