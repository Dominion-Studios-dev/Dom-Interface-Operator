#include "crow_all.h" // Lightweight C++ web framework
#include <iostream>
#include <fstream>
#include <string>
#include <cstdlib>
#include <sstream>
#include <vector>
#include <memory>
#include <stdexcept>
#include <algorithm>
#include <regex>
#include <thread>
#include <chrono>
#include <mutex>
#include <atomic>
#include <unordered_set>
#include <nlohmann/json.hpp>
#include <curl/curl.h>
#include <unistd.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <cstring>
#include <ctime>
#include <filesystem>

using json = nlohmann::json;

// ============================================================================
// CORE CONFIGURATION & CONSTANTS (SANDBOX LOCKED)
// ============================================================================
const std::string COMMANDS_FILE = "shared/dom_commands.json";
const std::string RULES_FILE = "shared/dom_rules.txt";

// Python database bridge — replaces all JSON file I/O
const std::string BRIDGE_SCRIPT = "dom_db_bridge.py";

// ============================================================================
// TIMESTAMPED LOGGING
// ============================================================================
std::string currentTimestamp() {
    std::time_t now = std::time(nullptr);
    std::tm tmv{};
    localtime_r(&now, &tmv);
    char buf[32];
    std::strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &tmv);
    return buf;
}

static void logInfo(const std::string& msg)  { std::cout << "[" << currentTimestamp() << "] [INFO]  " << msg << std::endl; }
static void logWarn(const std::string& msg)  { std::cout << "[" << currentTimestamp() << "] [WARN]  " << msg << std::endl; }
static void logErr(const std::string& msg)   { std::cerr << "[" << currentTimestamp() << "] [ERROR] " << msg << std::endl; }

// ============================================================================
// RUNTIME METRICS (uptime / request count for /status)
// ============================================================================
static const std::chrono::steady_clock::time_point g_startTime = std::chrono::steady_clock::now();
static std::atomic<unsigned long> g_requestCount{0};

// ============================================================================
// TELEMETRY SANITIZER: STRIPS LINUX ANSI COLOR CODES & CONTROL JUNK
// ============================================================================
std::string stripAnsiAndControlCodes(const std::string& input) {
    std::string output = "";
    bool inEscapeSequence = false;
    
    for (size_t i = 0; i < input.size(); ++i) {
        if (input[i] == '\x1B' || (i + 1 < input.size() && input[i] == '\\' && input[i+1] == 'e')) {
            inEscapeSequence = true;
            if (input[i] == '\\') i++; 
            continue;
        }
        
        if (inEscapeSequence) {
            if ((input[i] >= 'A' && input[i] <= 'Z') || (input[i] >= 'a' && input[i] <= 'z')) {
                inEscapeSequence = false;
            }
            continue;
        }
        
        if ((input[i] >= 32 && input[i] <= 126) || input[i] == '\n' || input[i] == '\t') {
            output += input[i];
        }
    }
    return output;
}

// ============================================================================
// SAFE PROCESS EXECUTION (fork/execvp — no shell interpolation)
//
// Every function below spawns children with explicit argv arrays, so no
// user/LLM-derived data is ever interpolated through a shell. All children
// are reaped with waitpid() (or reparented to init via double-fork) so no
// zombies can accumulate.
// ============================================================================

// Build a null-terminated argv array for execvp from program name + args.
static std::vector<char*> buildArgv(const std::string& program, const std::vector<std::string>& args) {
    std::vector<char*> argv;
    argv.reserve(args.size() + 2);
    argv.push_back(const_cast<char*>(program.c_str()));
    for (const auto& a : args) argv.push_back(const_cast<char*>(a.c_str()));
    argv.push_back(nullptr);
    return argv;
}

// Execute <program> <args...> via execvp; wait for completion; return exit
// code (or -1 if the child could not be spawned). stdout/stderr are silenced
// when silenceOutput is true.
int execAndWait(const std::string& program, const std::vector<std::string>& args, bool silenceOutput) {
    std::vector<char*> argv = buildArgv(program, args);
    pid_t pid = fork();
    if (pid == 0) {
        if (silenceOutput) {
            int devnull = open("/dev/null", O_WRONLY);
            if (devnull >= 0) {
                dup2(devnull, STDOUT_FILENO);
                dup2(devnull, STDERR_FILENO);
                close(devnull);
            }
        }
        execvp(program.c_str(), argv.data());
        _exit(127);
    }
    if (pid < 0) return -1;
    int status = 0;
    waitpid(pid, &status, 0);
    return WIFEXITED(status) ? WEXITSTATUS(status) : -1;
}

// Spawn a completely detached child (double-fork + setsid, reparented to
// init): fire-and-forget with no zombies and no blocking on the caller.
void execDetached(const std::string& program, const std::vector<std::string>& args) {
    pid_t pid = fork();
    if (pid == 0) {
        setsid();
        pid_t grandchild = fork();
        if (grandchild != 0) _exit(0); // intermediate child exits; init reaps grandchild

        int devnull = open("/dev/null", O_RDWR);
        if (devnull >= 0) {
            dup2(devnull, STDOUT_FILENO);
            dup2(devnull, STDERR_FILENO);
            close(devnull);
        }
        std::vector<char*> argv = buildArgv(program, args);
        execvp(program.c_str(), argv.data());
        _exit(127);
    }
    if (pid > 0) {
        int status = 0;
        waitpid(pid, &status, 0); // reap the intermediate child only
    }
}

// Execute <program> <args...> and capture its stdout (stderr silenced).
// Blocks until the child finishes; the child is always reaped.
std::string execAndCapture(const std::string& program, const std::vector<std::string>& args) {
    int fds[2];
    if (pipe(fds) != 0) return "";
    pid_t pid = fork();
    if (pid == 0) {
        close(fds[0]);
        dup2(fds[1], STDOUT_FILENO);
        close(fds[1]);
        int devnull = open("/dev/null", O_WRONLY);
        if (devnull >= 0) {
            dup2(devnull, STDERR_FILENO);
            close(devnull);
        }
        std::vector<char*> argv = buildArgv(program, args);
        execvp(program.c_str(), argv.data());
        _exit(127);
    }
    if (pid < 0) {
        close(fds[0]);
        close(fds[1]);
        return "";
    }
    close(fds[1]);
    std::string result;
    char buffer[128];
    ssize_t n;
    while ((n = read(fds[0], buffer, sizeof(buffer))) > 0) {
        result.append(buffer, static_cast<size_t>(n));
    }
    close(fds[0]);
    int status = 0;
    waitpid(pid, &status, 0);
    return result;
}

// Run a *trusted static* command string through /bin/sh -c and wait.
// INTENDED USE ONLY for whitelisted constant strings (dom_commands.json)
// that may contain shell syntax (pipes, redirection, backgrounding).
// User or LLM data must NEVER reach `cmd`.
void runShellCommandSync(const std::string& cmd) {
    pid_t pid = fork();
    if (pid == 0) {
        execl("/bin/sh", "sh", "-c", cmd.c_str(), (char*)nullptr);
        _exit(127);
    }
    if (pid > 0) {
        int status = 0;
        waitpid(pid, &status, 0);
    }
}

// ============================================================================
// AUDIO STREAMING PIPELINE (edge-tts → mpv, per-request temp file)
// ============================================================================
std::string trim(const std::string& str);

void speakText(const std::string& text) {
    if (text.empty()) return;
    
    std::string safeVoiceText = "";
    for (char c : text) {
        if (c == '"' || c == '\'' || c == '`' || c == ';' || c == '&' || c == '|' || c == '$' || c == '(' || c == ')') {
            continue;
        } else {
            safeVoiceText += c;
        }
    }
    safeVoiceText = trim(safeVoiceText);
    if (safeVoiceText.empty()) return;

    // Unique per-request file: no shared .voice.mp3 write races between
    // concurrent /chat threads.
    static std::atomic<unsigned long> sVoiceSeq{0};
    std::string outFile = ".voice." + std::to_string(static_cast<long>(::getpid())) + "." +
                          std::to_string(sVoiceSeq.fetch_add(1)) + ".mp3";

    // Keep the HTTP handler non-blocking: TTS runs fully in a detached thread.
    std::thread([safeVoiceText, outFile]() {
        int ttsResult = execAndWait("edge-tts", {
            "--voice", "en-US-BrianNeural",
            "--rate=+15%",
            "--text", safeVoiceText,
            "--write-media", outFile
        }, true);
        if (ttsResult != 0) {
            std::remove(outFile.c_str());
            return;
        }
        execDetached("mpv", {"--volume=140", outFile});
        // Give mpv a generous window to open the file, then clean up.
        std::this_thread::sleep_for(std::chrono::seconds(120));
        std::remove(outFile.c_str());
    }).detach();
}

// Remove .voice.*.mp3 leftovers (crashed runs / interrupted TTS) from the
// working directory. Called once at startup.
void sweepStaleVoiceFiles() {
    namespace fs = std::filesystem;
    try {
        for (const auto& entry : fs::directory_iterator(".")) {
            const std::string name = entry.path().filename().string();
            if (name.rfind(".voice.", 0) == 0 &&
                name.size() > 7 &&
                name.compare(name.size() - 4, 4, ".mp3") == 0) {
                std::remove(name.c_str());
                logInfo("Removed stale voice file: " + name);
            }
        }
    } catch (...) {}
}

// ============================================================================
// UTILITY & STRING PROCESSING
// ============================================================================
std::string trim(const std::string& str) {
    size_t first = str.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return "";
    size_t last = str.find_last_not_of(" \t\r\n");
    return str.substr(first, (last - first + 1));
}

// ============================================================================
// FILE I/O & ENVIRONMENT LAYER
// ============================================================================
std::string getApiKey() {
    const char* env_key = std::getenv("GROQ_API_KEY");
    if (env_key) {
        return trim(env_key);
    }
    return "";
}

std::string getMasterSecret() {
    const char* secret = std::getenv("DOM_MASTER_SECRET");
    if (secret) {
        return trim(secret);
    }
    return "";
}

std::string loadCustomRules() {
    std::ifstream rulesFile(RULES_FILE);
    if (!rulesFile.is_open()) {
        return "You are Dom Interface, a loyal desktop AI assistant for Master Ardis.";
    }
    std::stringstream buffer;
    buffer << rulesFile.rdbuf();
    return buffer.str();
}

// Capture the output of a shell pipeline. Used ONLY with trusted static
// command strings (string constants / whitelist entries) — never user data.
// pclose() internally waits for the child, so no zombies can accumulate.
std::string runCommandAndCaptureOutput(const std::string& cmd) {
    char buffer[128];
    std::string result = "";
    std::unique_ptr<FILE, int(*)(FILE*)> pipe(popen(cmd.c_str(), "r"), pclose);
    if (!pipe) {
        return "Error: Failed to open system telemetry pipeline.";
    }
    while (fgets(buffer, sizeof(buffer), pipe.get()) != nullptr) {
        result += buffer;
    }
    return result;
}

// ============================================================================
// PYTHON DATABASE BRIDGE (argv-based — injection-safe)
// ============================================================================
void execDbBridge(const std::vector<std::string>& args) {
    std::vector<std::string> full;
    full.reserve(args.size() + 1);
    full.push_back(BRIDGE_SCRIPT);
    full.insert(full.end(), args.begin(), args.end());
    execAndWait("python3", full, true);
}

std::string captureDbBridge(const std::vector<std::string>& args) {
    std::vector<std::string> full;
    full.reserve(args.size() + 1);
    full.push_back(BRIDGE_SCRIPT);
    full.insert(full.end(), args.begin(), args.end());
    return execAndCapture("python3", full);
}

// ============================================================================
// NTFY NOTIFICATION DISPATCHER (detached curl, argv-based)
// ============================================================================
void sendNtfyNotification(const std::string& message) {
    std::string safeText = "";
    for (char c : message) {
        if (c == '"') safeText += " ";
        else safeText += c;
    }
    if (safeText.empty()) return;
    execDetached("curl", {
        "-s", "-X", "POST",
        "https://ntfy.sh/dom-interface",
        "-H", "Title: Dom Interface",
        "-H", "Tags: robot_face",
        "-d", safeText
    });
}

// ============================================================================
// STATE & MEMORY MANAGERS (RAM / HDD)
// ============================================================================
void updateRAM(const std::string& role, const std::string& content) {
    execDbBridge({"ram:push", role, content, "root"});
}

void checkAndSaveToHDD(const std::string& reply) {
    static const std::regex saveRegex("\\[SAVE:\\s*([^=]+)=([^\\]]+)\\]");
    std::smatch match;
    std::string::const_iterator searchStart(reply.cbegin());
    while (std::regex_search(searchStart, reply.cend(), match, saveRegex)) {
        std::string key = match[1].str();
        std::string value = match[2].str();
        logInfo("Saving memory: " + key + " -> " + value);

        execDbBridge({"hdd:set", key, value});

        searchStart = match.suffix().first;
    }
}

// ============================================================================
// SYSTEM EXECUTION LAYER (RUN / PROBE)
// ============================================================================
void checkAndExecuteCommand(const std::string& aiResponse) {
    size_t startPos = aiResponse.find("[RUN:");
    if (startPos != std::string::npos) {
        size_t endPos = aiResponse.find("]", startPos);
        if (endPos != std::string::npos) {
            std::string cmdKey = aiResponse.substr(startPos + 5, endPos - (startPos + 5));
            cmdKey = trim(cmdKey);
            
            std::ifstream cmdFile(COMMANDS_FILE);
            if (cmdFile.is_open()) {
                try {
                    json cmdData;
                    cmdFile >> cmdData;
                    if (cmdData.contains(cmdKey)) {
                        std::string actualSystemCommand = cmdData[cmdKey];
                        logInfo("[Executing System Authorization] " + actualSystemCommand);
                        runShellCommandSync(actualSystemCommand); // trusted static whitelist value
                    }
                } catch(...) {}
                cmdFile.close();
            }
        }
    }
}

std::string processTelemetryProbes(const std::string& aiResponse) {
    size_t startPos = aiResponse.find("[PROBE:");
    if (startPos != std::string::npos) {
        size_t endPos = aiResponse.find("]", startPos);
        if (endPos != std::string::npos) {
            std::string probeKey = aiResponse.substr(startPos + 7, endPos - (startPos + 7));
            probeKey = trim(probeKey);
            
            std::ifstream cmdFile(COMMANDS_FILE);
            if (cmdFile.is_open()) {
                try {
                    json cmdData;
                    cmdFile >> cmdData;
                    if (cmdData.contains(probeKey)) {
                        std::string targetCmd = cmdData[probeKey];
                        logInfo("[System Notice] Dom pulling system logs via: " + targetCmd);
                        
                        std::string rawLogs = runCommandAndCaptureOutput(targetCmd);
                        rawLogs = stripAnsiAndControlCodes(rawLogs);
                        
                        execDbBridge({"hdd:set", "last_system_probe", rawLogs});
                        
                        return rawLogs;
                    }
                } catch(...) {}
                cmdFile.close();
            }
        }
    }
    return "";
}

// ============================================================================
// LONG-RUNNING TASK DETECTION & BACKGROUND EXECUTION
// ============================================================================
bool isLongRunningProbe(const std::string& probeKey) {
    return (probeKey == "maintain" || probeKey == "probe_emails" ||
            probeKey == "clean_email" || probeKey == "system_stats");
}

void dispatchBackgroundTask(const std::string& taskCmd, const std::string& taskName) {
    std::thread([taskCmd, taskName]() {
        logInfo("[BACKGROUND] Starting task: " + taskName);
        std::string result = runCommandAndCaptureOutput(taskCmd);
        result = stripAnsiAndControlCodes(result);
        if (result.empty()) result = "Task completed with no output.";
        sendNtfyNotification(taskName + " finished.\n" + result);
        logInfo("[BACKGROUND] Task completed: " + taskName);
    }).detach();
}

// ============================================================================
// NETWORK LAYER (GROQ INTEGRATION via in-process libcurl)
//
// The request body is streamed in memory with CURLOPT_WRITEFUNCTION into a
// per-call std::string. No shared temp files on disk, so concurrent /chat
// threads can never corrupt each other's request/response.
// ============================================================================
static size_t groqWriteCallback(void* contents, size_t size, size_t nmemb, void* userp) {
    const size_t total = size * nmemb;
    static_cast<std::string*>(userp)->append(static_cast<const char*>(contents), total);
    return total;
}

std::string fireGroqRequest(const json& messagesPayload, const std::string& apiKey) {
    json requestBody;
    requestBody["model"] = "llama-3.1-8b-instant";
    requestBody["messages"] = messagesPayload;
    const std::string payload = requestBody.dump();
    const std::string authHeader = "Authorization: Bearer " + apiKey;

    CURL* curl = curl_easy_init();
    if (!curl) return "ERROR_SIGNAL";

    struct curl_slist* headers = nullptr;
    headers = curl_slist_append(headers, "Content-Type: application/json");
    headers = curl_slist_append(headers, authHeader.c_str());

    std::string responseBuffer; // per-request buffer; separate stack frame per thread
    curl_easy_setopt(curl, CURLOPT_URL, "https://api.groq.com/openai/v1/chat/completions");
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE_LARGE, static_cast<curl_off_t>(payload.size()));
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, payload.c_str());
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, groqWriteCallback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &responseBuffer);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 120L);
    curl_easy_setopt(curl, CURLOPT_HTTP_VERSION, CURL_HTTP_VERSION_2TLS);
    curl_easy_setopt(curl, CURLOPT_USERAGENT, "Dom-Interface/2.1");

    const CURLcode result = curl_easy_perform(curl);
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);

    if (result != CURLE_OK || responseBuffer.empty()) {
        return "ERROR_SIGNAL";
    }

    try {
        json resJson = json::parse(responseBuffer);
        if (resJson.contains("choices") && !resJson["choices"].empty()) {
            return resJson["choices"][0]["message"]["content"];
        }
    } catch (...) {}
    return "ERROR_SIGNAL";
}

std::string cleanOutputText(std::string text) {
    std::vector<std::string> tags = {"[RUN:", "[SAVE:", "[PROBE:"};
    for (const std::string& tag : tags) {
        size_t pos;
        while ((pos = text.find(tag)) != std::string::npos) {
            size_t endPos = text.find("]", pos);
            if (endPos != std::string::npos) {
                text.erase(pos, endPos - pos + 1);
            } else {
                break;
            }
        }
    }
    return trim(text);
}

// ============================================================================
// WEBSOCKET TELEMETRY BROADCASTER
// ============================================================================
static std::mutex g_wsMutex;
static std::unordered_set<crow::websocket::connection*> g_wsConnections;

void startTelemetryBroadcaster() {
    std::thread([]() {
        while (true) {
            std::this_thread::sleep_for(std::chrono::seconds(2));

            std::string cpuRaw = runCommandAndCaptureOutput(
                "top -bn1 | grep 'Cpu(s)' | awk '{print $2}'");
            std::string memRaw = runCommandAndCaptureOutput(
                "free -m | awk '/^Mem:/{printf \"%.1f\", $3/$2*100}'");

            float cpuVal = 0.0f;
            float memVal = 0.0f;
            try { cpuVal = std::stof(trim(cpuRaw)); } catch (...) {}
            try { memVal = std::stof(trim(memRaw)); } catch (...) {}

            json telemetry;
            telemetry["cpu"] = cpuVal;
            telemetry["memory"] = memVal;
            std::string payload = telemetry.dump();

            std::lock_guard<std::mutex> lock(g_wsMutex);
            for (auto* conn : g_wsConnections) {
                if (conn) {
                    try { conn->send_text(payload); } catch (...) {}
                }
            }
        }
    }).detach();
}

// ============================================================================
// ENTRY POINT
// ============================================================================
int main() {
    std::string apiKey = getApiKey();
    if (apiKey.empty()) {
        logErr("GROQ_API_KEY not found in environment variables!");
        return 1;
    }

    std::string masterSecret = getMasterSecret();
    if (masterSecret.empty()) {
        logErr("DOM_MASTER_SECRET not found in environment variables!");
        return 1;
    }

    curl_global_init(CURL_GLOBAL_DEFAULT);

    sweepStaleVoiceFiles();

    execDbBridge({"init"});
    execDbBridge({"ram:clear", "root"});

    // Start WebSocket telemetry broadcaster
    startTelemetryBroadcaster();

    crow::SimpleApp app;

    // Route 1: Healthcheck Endpoint
    CROW_ROUTE(app, "/")([](){
        return "Dom Interface API is Online and Active.";
    });

    // Route 2: Ping Endpoint
    CROW_ROUTE(app, "/ping")([](){
        crow::response res;
        res.code = 200;
        res.set_header("Content-Type", "application/json");
        res.body = "{\"status\": \"alive\", \"engine\": \"Dom C++ Core\"}";
        return res;
    });

    // Route 3: Status Endpoint (uptime, counters, connectivity)
    CROW_ROUTE(app, "/status")([](){
        const long uptimeSeconds = static_cast<long>(
            std::chrono::duration_cast<std::chrono::seconds>(
                std::chrono::steady_clock::now() - g_startTime).count());

        size_t wsClients = 0;
        {
            std::lock_guard<std::mutex> lock(g_wsMutex);
            wsClients = g_wsConnections.size();
        }

        const char* bind_env = std::getenv("DOM_BIND");
        const char* port_env = std::getenv("PORT");

        json status;
        status["status"] = "online";
        status["engine"] = "Dom C++ Core";
        status["uptime_seconds"] = uptimeSeconds;
        status["requests_served"] = g_requestCount.load();
        status["websocket_clients"] = wsClients;
        status["bind_address"] = (bind_env && *bind_env) ? bind_env : "127.0.0.1";
        status["port"] = port_env ? std::stoi(port_env) : 7860;
        status["groq_model"] = "llama-3.1-8b-instant";
        status["time"] = currentTimestamp();

        crow::response res;
        res.code = 200;
        res.set_header("Content-Type", "application/json");
        res.body = status.dump();
        return res;
    });

    // Route 4: WebSocket Telemetry Endpoint
    CROW_WEBSOCKET_ROUTE(app, "/telemetry")
        .onopen([&](crow::websocket::connection& conn) {
            logInfo("[WS] Client connected from " + conn.get_remote_ip());
            std::lock_guard<std::mutex> lock(g_wsMutex);
            g_wsConnections.insert(&conn);
        })
        .onclose([&](crow::websocket::connection& conn, const std::string& reason, uint16_t /*code*/) {
            logInfo("[WS] Client disconnected from " + conn.get_remote_ip() + " (" + reason + ")");
            std::lock_guard<std::mutex> lock(g_wsMutex);
            g_wsConnections.erase(&conn);
        })
        .onmessage([&](crow::websocket::connection& conn, const std::string& data, bool isbin) {
            // Client can send commands; echo back for now
            conn.send_text("{\"status\":\"connected\",\"engine\":\"Dom C++ Core\"}");
        });

    // Route 5: Chat API Endpoint (with Authorization + Async probes)
    CROW_ROUTE(app, "/chat").methods(crow::HTTPMethod::POST)([apiKey, masterSecret](const crow::request& req){
        // --- REQUEST BOOKKEEPING ---
        g_requestCount.fetch_add(1);
        logInfo("[CHAT] request from " + req.remote_ip_address +
                " (" + std::to_string(req.body.size()) + " bytes)");

        // --- AUTHORIZATION CHECK ---
        std::string authHeader = req.get_header_value("Authorization");
        if (authHeader.empty() || authHeader != "Bearer " + masterSecret) {
            crow::response errorRes(401);
            errorRes.body = "{\"error\": \"Unauthorized access\"}";
            errorRes.set_header("Content-Type", "application/json");
            return errorRes;
        }

        json body;
        try {
            body = json::parse(req.body);
        } catch (...) {
            crow::response errorRes(400);
            errorRes.body = "{\"error\": \"Malformed JSON payload\"}";
            errorRes.set_header("Content-Type", "application/json");
            return errorRes;
        }

        if (!body.contains("message")) {
            crow::response errorRes(400);
            errorRes.body = "{\"error\": \"Missing required field: 'message'\"}";
            errorRes.set_header("Content-Type", "application/json");
            return errorRes;
        }

        std::string userInput = body["message"];
        if (trim(userInput).empty()) {
            crow::response errorRes(400);
            errorRes.body = "{\"error\": \"Message content cannot be empty\"}";
            errorRes.set_header("Content-Type", "application/json");
            return errorRes;
        }

        // --- Core Execution Logic ---
        updateRAM("user", userInput);

        json messagesArray = json::array();
        std::string ramJson = captureDbBridge({"ram:load", "root"});
        if (!ramJson.empty()) {
            try { messagesArray = json::parse(ramJson); } catch(...) {}
        }

        std::string customRules = loadCustomRules();
        json systemPrompt = {{"role", "system"}, {"content", customRules}};
        messagesArray.insert(messagesArray.begin(), systemPrompt);

        std::string domReply = fireGroqRequest(messagesArray, apiKey);
        if (domReply == "ERROR_SIGNAL") {
            crow::response errorRes(500);
            errorRes.body = "{\"error\": \"Dom Interface: Log parser sync drop.\"}";
            errorRes.set_header("Content-Type", "application/json");
            return errorRes;
        }

        checkAndSaveToHDD(domReply);

        // --- Check for long-running probes: dispatch async and respond immediately ---
        bool isLongRun = false;
        {
            size_t probeStart = domReply.find("[PROBE:");
            if (probeStart != std::string::npos) {
                size_t probeEnd = domReply.find("]", probeStart);
                if (probeEnd != std::string::npos) {
                    std::string probeKey = domReply.substr(probeStart + 7, probeEnd - (probeStart + 7));
                    probeKey = trim(probeKey);

                    if (isLongRunningProbe(probeKey)) {
                        std::ifstream cmdFile(COMMANDS_FILE);
                        if (cmdFile.is_open()) {
                            try {
                                json cmdData;
                                cmdFile >> cmdData;
                                if (cmdData.contains(probeKey)) {
                                    std::string actualCmd = cmdData[probeKey];
                                    dispatchBackgroundTask(actualCmd, probeKey);
                                    isLongRun = true;
                                }
                            } catch (...) {}
                            cmdFile.close();
                        }
                    }
                }
            }
        }

        if (isLongRun) {
            updateRAM("assistant", "Task initiated, Master. Running in background...");
            json responseBody;
            responseBody["reply"] = "Task initiated, Master. Running in background...";
            crow::response res;
            res.code = 200;
            res.set_header("Content-Type", "application/json");
            res.body = responseBody.dump();
            return res;
        }

        checkAndExecuteCommand(domReply);

        std::string telemetryStatus = processTelemetryProbes(domReply);
        if (!telemetryStatus.empty()) {
            json transientArray = json::array();
            std::string transientJson = captureDbBridge({"ram:load", "root"});
            if (!transientJson.empty()) {
                try { transientArray = json::parse(transientJson); } catch(...) {}
            }
            transientArray.insert(transientArray.begin(), systemPrompt);
            
            std::string promptOverride = "[INTERNAL SYSTEM METRICS INJECTED]:\n" + telemetryStatus + 
                                         "\n\nMaster is waiting. Read the metrics data above and immediately provide your concise conversational summary.";
            transientArray.push_back({{"role", "user"}, {"content", promptOverride}});

            std::string analysisReply = fireGroqRequest(transientArray, apiKey);
            if (analysisReply != "ERROR_SIGNAL") {
                domReply = analysisReply;
            }
        }

        updateRAM("assistant", domReply);

        std::string output = cleanOutputText(domReply);
        speakText(output);

        json responseBody;
        responseBody["reply"] = output;

        crow::response res;
        res.code = 200;
        res.set_header("Content-Type", "application/json");
        res.body = responseBody.dump();
        return res;
    });

    // Detect Render/Hugging Face assigned port dynamically
    const char* port_env = std::getenv("PORT");
    int port = port_env ? std::stoi(port_env) : 7860;

    // Bind address hardening: default to loopback only. Cloud deployments
    // override with DOM_BIND=0.0.0.0 in their environment.
    const char* bind_env = std::getenv("DOM_BIND");
    std::string bindAddr = (bind_env && *bind_env) ? bind_env : "127.0.0.1";

    logInfo("=== Dom Interface Initialized ===");
    logInfo("API Web Server active on " + bindAddr + ":" + std::to_string(port) + "...");
    logInfo("GROQ model: llama-3.1-8b-instant | Custom rules: " + RULES_FILE);

    app.bindaddr(bindAddr).port(port).multithreaded().run();

    // Graceful shutdown: crow handles SIGINT/SIGTERM internally and returns
    // here once the server has stopped accepting traffic.
    logInfo("Shutting down — flushing state...");
    sweepStaleVoiceFiles();
    curl_global_cleanup();
    logInfo("Dom Interface stopped cleanly.");
    return 0;
}