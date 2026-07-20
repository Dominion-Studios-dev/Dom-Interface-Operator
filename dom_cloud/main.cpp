#include "crow.h"
#include <iostream>
#include <fstream>
#include <string>
#include <cstdlib>
#include <sstream>
#include <vector>
#include <memory>
#include <stdexcept>
#include <algorithm>
#include <functional>
#include <map>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

// ============================================================================
// CONFIGURATION
// ============================================================================
const std::string RULES_FILE = "shared/dom_rules.txt";
const std::string RAM_FILE = "memory/ram.json";
const std::string HDD_FILE = "memory/hdd.json";
const std::string COMMANDS_FILE = "shared/dom_commands.json";
const std::string REQUEST_FILE = "memory/.request.json";
const std::string RESPONSE_FILE = "memory/.response.json";
const size_t MAX_RAM_LINES = 12;

// ============================================================================
// UTILITIES
// ============================================================================
std::string trim(const std::string& str) {
    size_t first = str.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return "";
    size_t last = str.find_last_not_of(" \t\r\n");
    return str.substr(first, (last - first + 1));
}

std::string stripAnsi(const std::string& input) {
    std::string output;
    bool inEscape = false;
    for (size_t i = 0; i < input.size(); ++i) {
        if (input[i] == '\x1B' || (i + 1 < input.size() && input[i] == '\\' && input[i+1] == 'e')) {
            inEscape = true;
            if (input[i] == '\\') i++;
            continue;
        }
        if (inEscape) {
            if ((input[i] >= 'A' && input[i] <= 'Z') || (input[i] >= 'a' && input[i] <= 'z'))
                inEscape = false;
            continue;
        }
        if ((input[i] >= 32 && input[i] <= 126) || input[i] == '\n' || input[i] == '\t')
            output += input[i];
    }
    return output;
}

std::string runCommand(const std::string& cmd) {
    char buffer[128];
    std::string result;
    std::unique_ptr<FILE, int(*)(FILE*)> pipe(popen(cmd.c_str(), "r"), pclose);
    if (!pipe) return "Error: Failed to execute command.";
    while (fgets(buffer, sizeof(buffer), pipe.get()) != nullptr)
        result += buffer;
    return result;
}

// ============================================================================
// ENVIRONMENT
// ============================================================================
std::string getApiKey() {
    const char* env_key = std::getenv("GROQ_API_KEY");
    if (env_key) return trim(env_key);
    return "";
}

std::string loadRules() {
    std::ifstream f(RULES_FILE);
    if (!f.is_open())
        return "You are Dom Interface, a loyal desktop AI assistant for Master Ardis.";
    std::stringstream buf;
    buf << f.rdbuf();
    return buf.str();
}

// ============================================================================
// MEMORY (RAM / HDD)
// ============================================================================
json loadJson(const std::string& path, json fallback = json::array()) {
    std::ifstream f(path);
    if (f.is_open()) {
        json data;
        try { f >> data; return data; } catch (...) {}
    }
    return fallback;
}

void saveJson(const std::string& path, const json& data) {
    std::ofstream f(path);
    if (f.is_open()) f << data.dump(4);
}

void updateRAM(const std::string& role, const std::string& content) {
    json ram = loadJson(RAM_FILE, json::array());
    ram.push_back({{"role", role}, {"content", content}});
    while (ram.size() > MAX_RAM_LINES)
        ram.erase(ram.begin());
    saveJson(RAM_FILE, ram);
}

json loadHDD() {
    return loadJson(HDD_FILE, json::object());
}

void saveHDD(const json& data) {
    saveJson(HDD_FILE, data);
}

// ============================================================================
// GROQ API
// ============================================================================
std::string fireGroqRequest(const json& messages, const std::string& apiKey) {
    json body;
    body["model"] = "llama-3.1-8b-instant";
    body["messages"] = messages;

    std::ofstream reqFile(REQUEST_FILE);
    if (!reqFile.is_open()) return "ERROR_SIGNAL";
    reqFile << body.dump();
    reqFile.close();

    std::string cmd = "curl -s -X POST \"https://api.groq.com/openai/v1/chat/completions\" "
                      "-H \"Authorization: Bearer " + apiKey + "\" "
                      "-H \"Content-Type: application/json\" "
                      "-d @\"" + REQUEST_FILE + "\" > \"" + RESPONSE_FILE + "\" 2>/dev/null";
    std::system(cmd.c_str());

    std::ifstream resFile(RESPONSE_FILE);
    if (resFile.is_open()) {
        json res;
        try {
            resFile >> res;
            if (res.contains("choices") && !res["choices"].empty())
                return res["choices"][0]["message"]["content"];
        } catch (...) {}
    }
    return "ERROR_SIGNAL";
}

// ============================================================================
// TAG PROTOCOL — PARSER + REGISTRY
// ============================================================================
// Extract all tags of a given type from AI response
std::vector<std::string> extractTags(const std::string& text, const std::string& tagPrefix) {
    std::vector<std::string> results;
    size_t pos = 0;
    while ((pos = text.find(tagPrefix, pos)) != std::string::npos) {
        size_t end = text.find("]", pos);
        if (end != std::string::npos) {
            results.push_back(text.substr(pos + tagPrefix.size(), end - pos - tagPrefix.size()));
            pos = end + 1;
        } else {
            break;
        }
    }
    return results;
}

// Strip all tags from text for clean output
std::string cleanOutputText(std::string text) {
    std::vector<std::string> prefixes = {"[RUN:", "[SAVE:", "[PROBE:", "[RECALL:",
                                          "[FILE:", "[SEARCH:", "[REMIND:",
                                          "[SCREENSHOT]", "[NOTIFY:", "[MODE:"};
    for (const auto& prefix : prefixes) {
        size_t pos;
        while ((pos = text.find(prefix)) != std::string::npos) {
            size_t end = text.find("]", pos);
            if (end != std::string::npos)
                text.erase(pos, end - pos + 1);
            else
                break;
        }
    }
    return trim(text);
}

// Tag handler function type
using TagHandler = std::function<std::string(const std::string&)>;

// Tag registry — maps tag prefixes to handler functions
class TagRegistry {
public:
    void registerTag(const std::string& prefix, TagHandler handler) {
        handlers[prefix] = handler;
    }

    // Process all tags in a response, return combined results
    std::string processAll(const std::string& aiResponse) {
        std::string combined;
        for (auto& [prefix, handler] : handlers) {
            auto tags = extractTags(aiResponse, prefix);
            for (const auto& tag : tags) {
                std::string result = handler(tag);
                if (!result.empty()) {
                    if (!combined.empty()) combined += "\n";
                    combined += result;
                }
            }
        }
        return combined;
    }

private:
    std::map<std::string, TagHandler> handlers;
};

// ============================================================================
// TAG HANDLERS
// ============================================================================
std::string handleRun(const std::string& cmdKey) {
    json cmds = loadJson(COMMANDS_FILE, json::object());
    if (cmds.contains(cmdKey)) {
        std::string actual = cmds[cmdKey].get<std::string>();
        std::cout << "\n[EXEC] " << actual << "\n";
        std::system(actual.c_str());
        return "";
    }
    return "[RUN] Unknown command: " + cmdKey;
}

std::string handleProbe(const std::string& probeKey) {
    json cmds = loadJson(COMMANDS_FILE, json::object());
    if (cmds.contains(probeKey)) {
        std::string cmd = cmds[probeKey].get<std::string>();
        std::cout << "\n[PROBE] " << probeKey << " -> " << cmd << "\n";
        std::string rawLogs = runCommand(cmd);
        rawLogs = stripAnsi(rawLogs);

        json hdd = loadHDD();
        hdd["last_system_probe"] = rawLogs;
        saveHDD(hdd);

        return rawLogs;
    }
    return "";
}

std::string handleSave(const std::string& saveCmd) {
    json hdd = loadHDD();
    std::stringstream ss(saveCmd);
    std::string pair;
    bool updated = false;

    while (std::getline(ss, pair, ',')) {
        size_t eq = pair.find('=');
        if (eq != std::string::npos) {
            std::string key = trim(pair.substr(0, eq));
            std::string value = trim(pair.substr(eq + 1));
            if (!key.empty() && (!hdd.contains(key) || hdd[key] != value)) {
                hdd[key] = value;
                updated = true;
            }
        }
    }
    if (updated) saveHDD(hdd);
    return "";
}

std::string handleRecall(const std::string& key) {
    json hdd = loadHDD();
    if (hdd.contains(key)) {
        std::string val = hdd[key].is_string() ? hdd[key].get<std::string>() : hdd[key].dump();
        return "[RECALLED " + key + "]: " + val;
    }
    return "[RECALL] No data for key: " + key;
}

// ============================================================================
// SPEECH
// ============================================================================
void speakText(const std::string& text) {
    if (text.empty()) return;
    std::string safe;
    for (char c : text) {
        if (c == '"' || c == '\'' || c == '`' || c == ';' || c == '&' || c == '|' || c == '$' || c == '(' || c == ')')
            safe += ' ';
        else
            safe += c;
    }
    std::string cmd = "edge-tts --voice en-US-BrianNeural --rate=+15% --text \"" + safe +
                      "\" --write-media \".voice.mp3\" && mpv --volume=140 \".voice.mp3\" > /dev/null 2>&1 &";
    std::system(cmd.c_str());
}

// ============================================================================
// MAIN
// ============================================================================
int main() {
    std::string apiKey = getApiKey();
    if (apiKey.empty()) {
        std::cerr << "[CRITICAL] GROQ_API_KEY not found in environment variables" << std::endl;
        return 1;
    }

    // Register tag handlers
    TagRegistry tags;
    tags.registerTag("[RUN:", handleRun);
    tags.registerTag("[PROBE:", handleProbe);
    tags.registerTag("[SAVE:", handleSave);
    tags.registerTag("[RECALL:", handleRecall);

    crow::SimpleApp app;

    // Healthcheck
    CROW_ROUTE(app, "/")([](){
        return "Dom Interface API is Online and Active.";
    });

    // Ping endpoint (lightweight health check for Hugging Face / Docker)
    CROW_ROUTE(app, "/ping")([](){
        crow::response res;
        res.code = 200;
        res.set_header("Content-Type", "application/json");
        res.body = "{\"status\": \"alive\", \"engine\": \"Dom C++ Core\"}";
        return res;
    });

    // Chat endpoint
    CROW_ROUTE(app, "/chat").methods(crow::HTTPMethod::POST)(
        [&apiKey, &tags](const crow::request& req) {
            json body;
            try {
                body = json::parse(req.body);
            } catch (...) {
                crow::response res(400);
                res.body = "{\"error\": \"Malformed JSON payload\"}";
                res.set_header("Content-Type", "application/json");
                return res;
            }

            if (!body.contains("message") || trim(body["message"].get<std::string>()).empty()) {
                crow::response res(400);
                res.body = "{\"error\": \"Missing or empty 'message' field\"}";
                res.set_header("Content-Type", "application/json");
                return res;
            }

            std::string userInput = body["message"];

            // Update conversation memory
            updateRAM("user", userInput);

            // Build message array with system prompt
            json messages = loadJson(RAM_FILE, json::array());
            json systemPrompt = {{"role", "system"}, {"content", loadRules()}};
            messages.insert(messages.begin(), systemPrompt);

            // Call Groq
            std::string domReply = fireGroqRequest(messages, apiKey);
            if (domReply == "ERROR_SIGNAL") {
                crow::response res(500);
                res.body = "{\"error\": \"Groq API connection failed\"}";
                res.set_header("Content-Type", "application/json");
                return res;
            }

            // Process tags (RUN, SAVE, PROBE, RECALL, etc.)
            std::string tagResults = tags.processAll(domReply);

            // If a PROBE returned data, send it back to LLM for summary
            if (!tagResults.empty() && tagResults.find("[RECALLED") == std::string::npos) {
                json transient = loadJson(RAM_FILE, json::array());
                transient.insert(transient.begin(), systemPrompt);
                transient.push_back({{"role", "user"},
                    {"content", "[INTERNAL SYSTEM METRICS INJECTED]:\n" + tagResults +
                     "\n\nMaster is waiting. Read the metrics data above and provide your concise conversational summary."}});

                std::string analysisReply = fireGroqRequest(transient, apiKey);
                if (analysisReply != "ERROR_SIGNAL")
                    domReply = analysisReply;
            }

            // Save assistant response to memory
            updateRAM("assistant", domReply);

            // Clean and return
            std::string output = cleanOutputText(domReply);
            speakText(output);

            json responseBody;
            responseBody["reply"] = output;

            crow::response res;
            res.code = 200;
            res.set_header("Content-Type", "application/json");
            res.body = responseBody.dump();
            return res;
        }
    );

    const char* port_env = std::getenv("PORT");
    int port = port_env ? std::stoi(port_env) : 7860;

    std::cout << "=== Dom Interface Initialized ===" << std::endl;
    std::cout << "API Web Server active on 0.0.0.0:" << port << "...\n" << std::endl;

    app.bindaddr("0.0.0.0").port(port).multithreaded().run();
    return 0;
}
