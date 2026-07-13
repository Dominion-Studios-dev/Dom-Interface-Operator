#include "crow.h" // Lightweight C++ web framework
#include <iostream>
#include <fstream>
#include <string>
#include <cstdlib>
#include <sstream>
#include <vector>
#include <memory>
#include <stdexcept>
#include <algorithm>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

// ============================================================================
// CORE CONFIGURATION & CONSTANTS (SANDBOX LOCKED)
// ============================================================================
const std::string ENV_FILE = ".env";
const std::string RULES_FILE = "dom_rules.txt";
const std::string RAM_FILE = "dom_sandbox/core_memory/dom_ram.json";
const std::string HDD_FILE = "dom_sandbox/core_memory/dom_hdd.json";
const std::string COMMANDS_FILE = "dom_sandbox/dom_commands.json";
const std::string REQUEST_FILE = "dom_sandbox/core_memory/.request.json";
const std::string RESPONSE_FILE = "dom_sandbox/core_memory/.response.json";
const size_t MAX_RAM_LINES = 12;

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
    
    std::string ttsCommand = "edge-tts --voice en-US-BrianNeural --rate=+15% --text \"" + safeVoiceText + "\" --write-media .voice.mp3 && mpv --volume=140 .voice.mp3 > /dev/null 2>&1 &";
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
// FILE I/O LAYER
// ============================================================================
std::string getApiKeyFromEnvFile() {
    std::ifstream envFile(ENV_FILE);
    std::string line;
    if (envFile.is_open()) {
        while (getline(envFile, line)) {
            if (line.find("GROQ_API_KEY=") == 0) {
                std::string key = line.substr(13);
                return trim(key);
            }
        }
        envFile.close();
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
// STATE & MEMORY MANAGERS (RAM / HDD)
// ============================================================================
void updateRAM(const std::string& role, const std::string& content) {
    json ramData = json::array();
    std::ifstream ramFile(RAM_FILE);
    if (ramFile.is_open()) {
        try { ramFile >> ramData; } catch(...) {}
        ramFile.close();
    }
    
    ramData.push_back({{"role", role}, {"content", content}});
    
    while (ramData.size() > MAX_RAM_LINES) {
        ramData.erase(ramData.begin());
    }
    
    std::ofstream outFile(RAM_FILE);
    if (outFile.is_open()) {
        outFile << ramData.dump(4);
        outFile.close();
    }
}

void checkAndSaveToHDD(const std::string& aiResponse) {
    size_t startPos = aiResponse.find("[SAVE:");
    if (startPos != std::string::npos) {
        size_t endPos = aiResponse.find("]", startPos);
        if (endPos != std::string::npos) {
            std::string saveCmd = aiResponse.substr(startPos + 6, endPos - (startPos + 6));
            json hddData = json::object();
            
            std::ifstream hddFile(HDD_FILE);
            if (hddFile.is_open()) {
                try { hddFile >> hddData; } catch(...) {}
                hddFile.close();
            }
            
            std::stringstream ss(saveCmd);
            std::string pair;
            bool updated = false;
            
            while (std::getline(ss, pair, ',')) {
                size_t eqPos = pair.find("=");
                if (eqPos != std::string::npos) {
                    std::string key = pair.substr(0, eqPos);
                    std::string value = pair.substr(eqPos + 1);
                    key = trim(key);
                    value = trim(value);
                    if (!key.empty() && (!hddData.contains(key) || hddData[key] != value)) {
                        hddData[key] = value;
                        updated = true;
                    }
                }
            }
            if (updated) {
                std::ofstream outFile(HDD_FILE);
                if (outFile.is_open()) {
                    outFile << hddData.dump(4);
                    outFile.close();
                }
            }
        }
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
                        
                        json hddData = json::object();
                        std::ifstream hddFile(HDD_FILE);
                        if (hddFile.is_open()) {
                            try { hddFile >> hddData; } catch(...) {}
                            hddFile.close();
                        }
                        
                        hddData["last_system_probe"] = rawLogs;
                        std::ofstream outFile(HDD_FILE);
                        if (outFile.is_open()) {
                            outFile << hddData.dump(4);
                            outFile.close();
                        }
                        
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
// NETWORK LAYER
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
                          "-d @" + REQUEST_FILE + " > " + RESPONSE_FILE + " 2>/dev/null";
    
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
// ENTRY POINT (CONVERTED TO CLOUD WEB ENDPOINT)
// ============================================================================
int main() {
    std::string apiKey = getApiKeyFromEnvFile();
    if (apiKey.empty()) {
        std::cerr << "[CRITICAL ERROR]: Could not retrieve your GROQ_API_KEY from .env file!" << std::endl;
        return 1;
    }

    std::ofstream wipeRam(RAM_FILE);
    if (wipeRam.is_open()) {
        wipeRam << "[]";
        wipeRam.close();
    }

    crow::SimpleApp app;

    // Root status route
    CROW_ROUTE(app, "/")([](){
        return "Dom Interface Backend Online.";
    });

    // Reworked Endpoint replacing the console inputs
    CROW_ROUTE(app, "/chat").methods(crow::HTTPMethod::POST)([apiKey](const crow::request& req){
        json body;
        try {
            body = json::parse(req.body);
        } catch (...) {
            return crow::response(400, "Invalid JSON payload");
        }

        if (!body.contains("message")) {
            return crow::response(400, "Missing 'message' field");
        }

        std::string userInput = body["message"];
        if (trim(userInput).empty()) {
            return crow::response(400, "Message cannot be empty");
        }

        // --- Core Execution Logic (Exact Copy from Original Loop) ---
        updateRAM("user", userInput);

        json messagesArray = json::array();
        std::ifstream ramFile(RAM_FILE);
        if (ramFile.is_open()) {
            try { ramFile >> messagesArray; } catch(...) {}
            ramFile.close();
        }

        std::string customRules = loadCustomRules();
        json systemPrompt = {{"role", "system"}, {"content", customRules}};
        messagesArray.insert(messagesArray.begin(), systemPrompt);

        std::string domReply = fireGroqRequest(messagesArray, apiKey);
        if (domReply == "ERROR_SIGNAL") {
            return crow::response(500, "Dom Interface: Log parser sync drop.");
        }

        checkAndSaveToHDD(domReply);
        checkAndExecuteCommand(domReply);

        std::string telemetryStatus = processTelemetryProbes(domReply);
        if (!telemetryStatus.empty()) {
            std::ifstream transientRam(RAM_FILE);
            json transientArray = json::array();
            if (transientRam.is_open()) {
                try { transientRam >> transientArray; } catch(...) {}
                transientRam.close();
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
        // --- End of Core Logic ---

        json responseBody;
        responseBody["reply"] = output;
        return crow::response(responseBody.dump());
    });

    // Detect Render assigned port dynamically
    const char* port_env = std::getenv("PORT");
    int port = port_env ? std::stoi(port_env) : 10000;

    std::cout << "=== Dom Interface Initialized ===" << std::endl;
    std::cout << "HTTP Server running on port " << port << "...\n" << std::endl;
    
    app.port(port).multithreaded().run();
    return 0;
}