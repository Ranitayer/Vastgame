// Opt-in, process-local native Linux Moonlight reporting. No network uploads.
#include "client/crashpad_client.h"
#include "client/crash_report_database.h"
#include "client/settings.h"
#include <cstdlib>
#include <cstdio>
#include <filesystem>
#include <map>
#include <string>
#include <unistd.h>

__attribute__((constructor)) static void initialize_crashpad() {
    const char* directory = std::getenv("VASTGAME_CRASH_DIR");
    const char* handler = std::getenv("VASTGAME_CRASH_HANDLER");
    if (!directory || !handler) return;
    try {
        char executable[4096];
        const auto length = readlink("/proc/self/exe", executable, sizeof(executable) - 1);
        if (length <= 0) return;
        executable[length] = 0;
        const auto name = std::filesystem::path(executable).filename().string();
        // Child utilities and crashpad_handler inherit LD_PRELOAD; never register them.
        if (name != "moonlight" && name != "moonlight-qt" && name != "vastgame-crashpad-probe") return;
        const auto root = std::filesystem::path(directory);
        if (!root.is_absolute() || !std::filesystem::is_directory(root) || !std::filesystem::is_regular_file(handler)) return;
        const base::FilePath database_path(directory);
        auto database = crashpad::CrashReportDatabase::Initialize(database_path);
        if (!database || !database->GetSettings()->SetUploadsEnabled(false)) {
            std::fprintf(stderr, "Vastgame: crash report database unavailable; streaming continues\n");
            return;
        }
        std::map<std::string, std::string> annotations{{"product", "Vastgame Moonlight"}};
        for (auto key : {"game_id", "session_id"}) {
            const auto filename = root / (std::string(key) + ".txt");
            if (FILE* file = std::fopen(filename.c_str(), "r")) {
                char value[128] = {};
                if (std::fgets(value, sizeof(value), file)) annotations[key] = value;
                std::fclose(file);
            }
        }
        static crashpad::CrashpadClient client;
        // Attach only the bounded session context and Moonlight log. No credentials/configs.
        std::vector<base::FilePath> attachments;
        for (auto name : {"session.json", "moonlight.log"}) {
            auto path = root / name;
            if (std::filesystem::is_regular_file(path)) attachments.emplace_back(path.string());
        }
        if (!client.StartHandler(base::FilePath(handler), database_path, base::FilePath(), "", "",
                                 annotations, {}, false, false, attachments)) {
            std::fprintf(stderr, "Vastgame: Crashpad unavailable; streaming continues\n");
        }
    } catch (...) {
        std::fprintf(stderr, "Vastgame: crash reporting initialization failed; streaming continues\n");
    }
}
