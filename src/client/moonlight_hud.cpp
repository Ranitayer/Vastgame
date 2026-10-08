// Linux SDL2/SDL_ttf bridge: retain Moonlight's own measurements and compositor.
// Only used by Vastgame's native Moonlight process, never installed system-wide.
#include <SDL.h>
#include <SDL_ttf.h>
#include "stream_menu.h"
#include <dlfcn.h>
#include <atomic>
#include <algorithm>
#include <cstdlib>
#include <cstdio>
#include <fstream>
#include <mutex>
#include <sstream>
#include <string>
#include <vector>
#include <unistd.h>

static std::mutex mutex;
static std::atomic<bool> visible{true};
#ifdef VASTGAME_GLES_MENU
static thread_local bool presenting_sdl = false;
#endif
static std::string root() {
    const char* dir = std::getenv("VASTGAME_HUD_DIR");
    return dir ? dir : "";
}
static void publish(const std::string& name, const std::string& value) {
    if (root().empty()) return;
    auto path = root() + "/" + name;
    auto tmp = path + "." + std::to_string(getpid()) + ".tmp";
    { std::ofstream out(tmp); out << value; if (!out.good()) return; }
    std::rename(tmp.c_str(), path.c_str());
}
static bool shortcut(SDL_Event* event) {
    if (!event || (event->type != SDL_KEYDOWN && event->type != SDL_KEYUP)) return false;
    auto mod = event->key.keysym.mod;
    if (!(mod & KMOD_CTRL) || !(mod & KMOD_ALT) || !(mod & KMOD_SHIFT)) return false;
    if (event->key.keysym.sym == SDLK_h) {
        if (event->type == SDL_KEYDOWN && !event->key.repeat) visible = !visible;
        return true;
    }
    return false;
}
extern "C" int SDL_PollEvent(SDL_Event* event) {
    static auto real = reinterpret_cast<decltype(&SDL_PollEvent)>(dlsym(RTLD_NEXT, "SDL_PollEvent"));
    int result;
    do { result = real(event); } while (result && (shortcut(event) || stream_menu_event(event)));
    return result;
}
extern "C" int SDL_WaitEventTimeout(SDL_Event* event, int timeout) {
    static auto real = reinterpret_cast<decltype(&SDL_WaitEventTimeout)>(dlsym(RTLD_NEXT, "SDL_WaitEventTimeout"));
    int result = real(event, timeout);
    if (result && (shortcut(event) || stream_menu_event(event))) { SDL_zero(*event); }
    return result;
}
extern "C" int SDL_WaitEvent(SDL_Event* event) {
    static auto real = reinterpret_cast<decltype(&SDL_WaitEvent)>(dlsym(RTLD_NEXT, "SDL_WaitEvent"));
    int result = real(event);
    if (result && (shortcut(event) || stream_menu_event(event))) { SDL_zero(*event); }
    return result;
}
extern "C" void SDL_RenderPresent(SDL_Renderer* renderer) {
    static auto real = reinterpret_cast<decltype(&SDL_RenderPresent)>(dlsym(RTLD_NEXT, "SDL_RenderPresent"));
    stream_menu_present(renderer);
#ifdef VASTGAME_GLES_MENU
    presenting_sdl = true;
#endif
    real(renderer);
#ifdef VASTGAME_GLES_MENU
    presenting_sdl = false;
#endif
}
#ifdef VASTGAME_GLES_MENU
extern "C" void SDL_GL_SwapWindow(SDL_Window* window) {
    static auto real = reinterpret_cast<decltype(&SDL_GL_SwapWindow)>(dlsym(RTLD_NEXT, "SDL_GL_SwapWindow"));
    if (!presenting_sdl) stream_menu_gl_present(window);
    real(window);
}
extern "C" void SDL_GL_DeleteContext(SDL_GLContext context) {
    static auto real = reinterpret_cast<decltype(&SDL_GL_DeleteContext)>(dlsym(RTLD_NEXT, "SDL_GL_DeleteContext"));
    stream_menu_gl_context_destroyed(context);
    real(context);
}
#endif
extern "C" void SDL_DestroyRenderer(SDL_Renderer* renderer) {
    static auto real = reinterpret_cast<decltype(&SDL_DestroyRenderer)>(dlsym(RTLD_NEXT, "SDL_DestroyRenderer"));
    stream_menu_renderer_destroyed(renderer);
    real(renderer);
}
extern "C" SDL_Surface* TTF_RenderUTF8_Blended_Wrapped(TTF_Font* font, const char* text,
                                                       SDL_Color color, Uint32 wrap) {
    static auto real = reinterpret_cast<decltype(&TTF_RenderUTF8_Blended_Wrapped)>(
        dlsym(RTLD_NEXT, "TTF_RenderUTF8_Blended_Wrapped"));
    if (root().empty() || !text || std::string(text).find("Video stream:") != 0)
        return real(font, text, color, wrap);
    std::lock_guard<std::mutex> lock(mutex);
    publish("moonlight.txt", text);
    // Keep collecting statistics even while the custom overlay is hidden.
    if (!visible) {
        auto surface = SDL_CreateRGBSurfaceWithFormat(0, 1, 1, 32, SDL_PIXELFORMAT_RGBA32);
        if (surface) SDL_FillRect(surface, nullptr, 0);
        return surface;
    }
    std::ifstream in(root() + "/hud.txt");
    std::string line;
    struct Line { std::string text; SDL_Color ink; };
    std::vector<Line> lines;
    while (std::getline(in, line) && lines.size() < 13) {
        SDL_Color ink{222, 231, 243, 255};
        unsigned r, g, b;
        if (line.size() >= 8 && line[0] == '#' && line[7] == '|' &&
            std::sscanf(line.c_str() + 1, "%2x%2x%2x", &r, &g, &b) == 3) {
            ink = SDL_Color{Uint8(r), Uint8(g), Uint8(b), 255}; line.erase(0, 8);
        }
        lines.push_back({line.substr(0, 110), ink});
    }
    if (lines.empty()) lines = {{"VASTGAME · Connecting telemetry...", {101, 230, 172, 255}}};
    static TTF_Font* hudFont = nullptr;
    const char* setting = std::getenv("VASTGAME_HUD_SCALE");
    float dpi = 96;
    int display = 0;
    if (auto* window = SDL_GetKeyboardFocus()) display = std::max(0, SDL_GetWindowDisplayIndex(window));
    if (SDL_GetDisplayDPI(display, &dpi, nullptr, nullptr) || dpi < 50) dpi = 96;
    const float scale = std::clamp(setting ? float(std::atof(setting)) : dpi / 96, .85f, 1.8f);
    if (!hudFont) {
        const char* file = std::getenv("VASTGAME_HUD_FONT");
        if (file) hudFont = TTF_OpenFont(file, int(12 * scale));
    }
    auto selectedFont = hudFont ? hudFont : font;
    const int oldOutline = TTF_GetFontOutline(selectedFont);
    TTF_SetFontOutline(selectedFont, 0);
    const int lineHeight = TTF_FontLineSkip(selectedFont) + 1;
    int width = 1;
    for (const auto& value : lines) {
        int w = 0, h = 0;
        TTF_SizeUTF8(selectedFont, value.text.c_str(), &w, &h); width = std::max(width, w + 16);
    }
    width = std::min(width, int(600 * scale));
    auto surface = SDL_CreateRGBSurfaceWithFormat(0, width + 8, lineHeight * lines.size() + 16,
                                                 32, SDL_PIXELFORMAT_RGBA32);
    if (!surface) { TTF_SetFontOutline(selectedFont, oldOutline); return real(font, text, color, wrap); }
    SDL_FillRect(surface, nullptr, 0);
    // Moonlight draws an outline pass, followed by its normal text pass.
    // Render only the text pass: no background, outline, border or score bar.
    if ((selectedFont == font ? oldOutline : TTF_GetFontOutline(font)) == 0) {
        int y = 8;
        for (size_t i = 0; i < lines.size(); i++, y += lineHeight) {
            auto rendered = real(selectedFont, lines[i].text.c_str(), lines[i].ink, width - 16);
            if (rendered) {
                SDL_Rect dest{8, y, rendered->w, rendered->h};
                SDL_BlitSurface(rendered, nullptr, surface, &dest); SDL_FreeSurface(rendered);
            }
        }
    }
    TTF_SetFontOutline(selectedFont, oldOutline);
    return surface;
}
