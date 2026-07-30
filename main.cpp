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
#include <unordered_set>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

// ============================================================================
// CORE CONFIGURATION & CONSTANTS (SANDBOX LOCKED)
// ============================================================================
const std::string COMMANDS_FILE = "shared/dom_commands.json";
const std::string RULES_FILE = "shared/dom_rules.txt";
const std::string REQUEST_FILE = "dom_sandbox/core_memory/.request.json";
const std::string RESPONSE_FILE = "dom_sandbox/core_memory/.response.json";

// Python database bridge — replaces all JSON file I/O
const std::string BRIDGE_SCRIPT = "dom_db_bridge.py";

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
// AUDIO STREAMING PIPELINE
// ============================================================================
void speakText(const std::string& text) {
    if (text.empty()) return;
    
    std::string safeVoiceText = "";
    for (char c : text) {
        if (c == '"' || c == '\'' || c == '`' || c == ';' || c == '&' || c == '|' || c == '$' || c == '(' || c == ')') {
            safeVoiceText += ' ';
        } else {
            safeVoiceText += c;
        }
    }
    
    std::string ttsCommand = "edge-tts --voice en-US-BrianNeural --rate=+15% --text \"" + safeVoiceText + "\" --write-media \".voice.mp3\" && mpv --volume=140 \".voice.mp3\" > /dev/null 2>&1 &";
    std::system(ttsCommand.c_str());
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
// PYTHON DATABASE BRIDGE (replaces JSON file I/O)
// ============================================================================
std::string shellEscape(const std::string& s) {
    std::string out;
    for (char c : s) {
        if (c == '"' || c == '\\') { out += '\\'; out += c; }
        else { out += c; }
    }
    return out;
}

void execDbBridge(const std::string& args) {
    std::string cmd = "python3 \"" + BRIDGE_SCRIPT + "\" " + args;
    std::system(cmd.c_str());
}

std::string captureDbBridge(const std::string& args) {
    std::string cmd = "python3 \"" + BRIDGE_SCRIPT + "\" " + args + " 2>/dev/null";
    return runCommandAndCaptureOutput(cmd);
}

// ============================================================================
// NTFY NOTIFICATION DISPATCHER
// ============================================================================
void sendNtfyNotification(const std::string& message) {
    std::string safeText = "";
    for (char c : message) {
        if (c == '"') safeText += " ";
        else safeText += c;
    }
    std::string cmd = "curl -s -X POST \"https://ntfy.sh/dom-interface\" "
                      "-H \"Title: Dom Interface\" "
                      "-H \"Tags: robot_face\" "
                      "-d \"" + safeText + "\" > /dev/null 2>&1";
    std::system(cmd.c_str());
}

// ============================================================================
// STATE & MEMORY MANAGERS (RAM / HDD)
// ============================================================================
void updateRAM(const std::string& role, const std::string& content) {
    std::string args = "ram:push \"" + shellEscape(role) + "\" \"" + shellEscape(content) + "\" root";
    execDbBridge(args);
}

void checkAndSaveToHDD(const std::string& reply) {
    static const std::regex saveRegex("\\[SAVE:\\s*([^=]+)=([^\\]]+)\\]");
    std::smatch match;
    std::string::const_iterator searchStart(reply.cbegin());
    while (std::regex_search(searchStart, reply.cend(), match, saveRegex)) {
        std::string key = match[1].str();
        std::string value = match[2].str();
        std::cout << "Saving memory: " << key << " -> " << value << std::endl;

        std::string args = "hdd:set \"" + shellEscape(key) + "\" \"" + shellEscape(value) + "\"";
        execDbBridge(args);

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
                        std::cout << "\n[Executing System Authorization: " << actualSystemCommand << "]\n";
                        std::system(actualSystemCommand.c_str());
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
                        std::cout << "\n[System Notice: Dom pulling system logs via: " << targetCmd << "]\n";
                        
                        std::string rawLogs = runCommandAndCaptureOutput(targetCmd);
                        rawLogs = stripAnsiAndControlCodes(rawLogs);
                        
                        std::string args = "hdd:set \"last_system_probe\" \"" + shellEscape(rawLogs) + "\"";
                        execDbBridge(args);
                        
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
        std::cout << "\n[BACKGROUND] Starting task: " << taskName << "\n";
        std::string result = runCommandAndCaptureOutput(taskCmd);
        result = stripAnsiAndControlCodes(result);
        if (result.empty()) result = "Task completed with no output.";
        sendNtfyNotification(taskName + " finished.\n" + result);
        std::cout << "\n[BACKGROUND] Task completed: " << taskName << "\n";
    }).detach();
}

// ============================================================================
// NETWORK LAYER (GROQ INTEGRATION)
// ============================================================================
std::string fireGroqRequest(const json& messagesPayload, const std::string& apiKey) {
    json requestBody;
    requestBody["model"] = "llama-3.1-8b-instant";
    requestBody["messages"] = messagesPayload;

    std::ofstream reqFile(REQUEST_FILE);
    if (!reqFile.is_open()) return "ERROR_SIGNAL";
    reqFile << requestBody.dump();
    reqFile.close();

    std::string command = "curl -X POST \"https://api.groq.com/openai/v1/chat/completions\" "
                          "-H \"Authorization: Bearer " + apiKey + "\" "
                          "-H \"Content-Type: application/json\" "
                          "-d @\"" + REQUEST_FILE + "\" > \"" + RESPONSE_FILE + "\" 2>/dev/null";
    
    std::system(command.c_str());

    std::ifstream responseFile(RESPONSE_FILE);
    if (responseFile.is_open()) {
        try {
            json resJson;
            responseFile >> resJson;
            responseFile.close();
            if (resJson.contains("choices") && !resJson["choices"].empty()) {
                return resJson["choices"][0]["message"]["content"];
            }
        } catch (...) {
            responseFile.close();
        }
    }
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
        std::cerr << "[CRITICAL ERROR]: GROQ_API_KEY not found in environment variables!" << std::endl;
        return 1;
    }

    std::string masterSecret = getMasterSecret();
    if (masterSecret.empty()) {
        std::cerr << "[CRITICAL ERROR]: DOM_MASTER_SECRET not found in environment variables!" << std::endl;
        return 1;
    }

    execDbBridge("init");
    execDbBridge("ram:clear root");

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

    // Route 3: WebSocket Telemetry Endpoint
    CROW_WEBSOCKET_ROUTE(app, "/telemetry")
        .onopen([&](crow::websocket::connection& conn) {
            std::cout << "\n[WS] Client connected: " << conn.get_remote_ip() << "\n";
            std::lock_guard<std::mutex> lock(g_wsMutex);
            g_wsConnections.insert(&conn);
        })
        .onclose([&](crow::websocket::connection& conn, const std::string& reason, uint16_t /*code*/) {
            std::cout << "\n[WS] Client disconnected: " << conn.get_remote_ip() << "\n";
            std::lock_guard<std::mutex> lock(g_wsMutex);
            g_wsConnections.erase(&conn);
        })
        .onmessage([&](crow::websocket::connection& conn, const std::string& data, bool isbin) {
            // Client can send commands; echo back for now
            conn.send_text("{\"status\":\"connected\",\"engine\":\"Dom C++ Core\"}");
        });

    // Route 4: Chat API Endpoint (with Authorization + Async probes)
    CROW_ROUTE(app, "/chat").methods(crow::HTTPMethod::POST)([apiKey, masterSecret](const crow::request& req){
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
        std::string ramJson = captureDbBridge("ram:load root");
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
            std::string transientJson = captureDbBridge("ram:load root");
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

    std::cout << "=== Dom Interface Initialized ===" << std::endl;
    std::cout << "API Web Server active on 0.0.0.0:" << port << "...\n" << std::endl;
    
    app.bindaddr("0.0.0.0").port(port).multithreaded().run();
    return 0;
}
