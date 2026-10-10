// Small native Moonlight menu. Build the texture only when content or display size changes.
#include "stream_menu.h"
#include <SDL_ttf.h>
#ifdef VASTGAME_GLES_MENU
#include <SDL_opengles2.h>
#endif
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <mutex>
#include <string>
#include <vector>
#include <unistd.h>

namespace {
constexpr SDL_Color background{0x15, 0x1d, 0x28, 255};
constexpr SDL_Color selection{0x39, 0x4a, 0x50, 255};
constexpr SDL_Color accent{0x81, 0x97, 0x96, 255};
constexpr SDL_Color foreground{0xeb, 0xed, 0xe9, 255};
std::mutex guard;
bool opened = false, loaded = false, dirty = true;
int selected = 0, bitrate = 0;
bool vsync = false, pacing = true;
float progress = 0;
Uint32 last_frame = 0, last_status = 0;
std::string status;
std::vector<std::string> resolutions{"native", "1280x720", "1920x1080", "1920x1200", "2560x1440", "2944x1840", "3840x2160"};
std::vector<std::string> rates{"native", "30", "60", "90", "120", "144", "165"};
const std::vector<std::string> codecs{"auto", "H.264", "HEVC", "AV1"};
int resolution_index = 0, rate_index = 0, codec_index = 0;
SDL_Renderer* cached_renderer = nullptr;
SDL_Texture* panel = nullptr;
SDL_Surface* card = nullptr;
TTF_Font *body_font = nullptr, *title_font = nullptr, *small_font = nullptr;
int cached_width = 0, cached_height = 0;
float cached_scale = 0;
unsigned revision = 0, panel_revision = 0;

std::string folder() {
    const char* path = std::getenv("VASTGAME_HUD_DIR");
    return path ? path : "";
}
bool publish(const char* name, const std::string& value) {
    const auto dir = folder();
    if (dir.empty()) return false;
    const auto path = dir + "/" + name;
    const auto tmp = path + "." + std::to_string(getpid()) + ".tmp";
    { std::ofstream out(tmp); out << value; if (!out.good()) return false; }
    return std::rename(tmp.c_str(), path.c_str()) == 0;
}
int index_of(std::vector<std::string>& values, const std::string& value) {
    auto found = std::find(values.begin(), values.end(), value);
    if (found == values.end()) { values.push_back(value); return int(values.size() - 1); }
    return int(found - values.begin());
}
void load() {
    if (loaded) return;
    loaded = true;
    std::ifstream input(folder() + "/menu.state");
    std::string line;
    if (!std::getline(input, line)) return;
    std::vector<std::string> parts;
    size_t start = 0, end;
    while ((end = line.find('|', start)) != std::string::npos) {
        parts.push_back(line.substr(start, end - start)); start = end + 1;
    }
    parts.push_back(line.substr(start));
    if (parts.size() != 6) return;
    resolution_index = index_of(resolutions, parts[0]);
    rate_index = index_of(rates, parts[1]);
    try { bitrate = parts[2] == "auto" ? 0 : std::clamp(std::stoi(parts[2]), 1, 500); }
    catch (...) { bitrate = 0; }
    auto codec = std::find(codecs.begin(), codecs.end(), parts[3]);
    if (codec != codecs.end()) codec_index = int(codec - codecs.begin());
    vsync = parts[4] == "true";
    pacing = parts[5] != "false";
}
void change(int direction) {
    auto cycle = [direction](int index, int count) { return (index + direction + count) % count; };
    switch (selected) {
        case 0: resolution_index = cycle(resolution_index, int(resolutions.size())); break;
        case 1: rate_index = cycle(rate_index, int(rates.size())); break;
        case 2: bitrate = direction < 0 ? std::max(0, bitrate - 5) : std::min(500, bitrate ? bitrate + 5 : 5); break;
        case 3: codec_index = cycle(codec_index, int(codecs.size())); break;
        case 4: vsync = !vsync; break;
        case 5: pacing = !pacing; break;
        default: return;
    }
    status.clear();
    std::remove((folder() + "/menu.status").c_str());
    dirty = true;
}
void save() {
    std::remove((folder() + "/menu.status").c_str());
    const bool queued = publish("menu.request", resolutions[resolution_index] + "|" + rates[rate_index] + "|" +
            (bitrate ? std::to_string(bitrate) : "auto") + "|" + codecs[codec_index] + "|" +
            (vsync ? "true" : "false") + "|" + (pacing ? "true" : "false") + "\n");
    status = queued ? "Saving..." : "Could not save stream settings"; dirty = true;
}
Uint32 color(SDL_Surface* surface, Uint8 r, Uint8 g, Uint8 b, Uint8 a = 255) {
    return SDL_MapRGBA(surface->format, r, g, b, a);
}
Uint32 color(SDL_Surface* surface, SDL_Color ink) {
    return color(surface, ink.r, ink.g, ink.b, ink.a);
}
void rounded(SDL_Surface* surface, int x, int y, int width, int height, int radius, Uint32 ink) {
    for (int row = 0; row < height; ++row) {
        const int edge = std::min(row, height - 1 - row);
        const int inset = edge < radius ? radius - int(std::sqrt(radius * radius - (radius - edge) * (radius - edge))) : 0;
        SDL_Rect line{x + inset, y + row, width - inset * 2, 1};
        SDL_FillRect(surface, &line, ink);
    }
}
void label(SDL_Surface* surface, TTF_Font* font, const std::string& value, int x, int y,
           SDL_Color ink, bool right = false, int row_height = 0) {
    if (!font) return;
    auto* text = TTF_RenderUTF8_Blended(font, value.c_str(), ink);
    if (!text) return;
    if (row_height) {
        int top = 0, bottom = text->h;
        // Center visible glyphs, excluding the font's blank ascent/descent padding.
        if (SDL_LockSurface(text) == 0) {
            auto has_ink = [text](int row) {
                const auto* pixels = reinterpret_cast<const Uint32*>(
                    static_cast<const Uint8*>(text->pixels) + row * text->pitch);
                for (int column = 0; column < text->w; ++column)
                    if (pixels[column] & text->format->Amask) return true;
                return false;
            };
            while (top < bottom && !has_ink(top)) ++top;
            while (bottom > top && !has_ink(bottom - 1)) --bottom;
            SDL_UnlockSurface(text);
        }
        y += (row_height - (bottom - top)) / 2 - top;
    }
    SDL_Rect target{right ? x - text->w : x, y, text->w, text->h};
    SDL_BlitSurface(text, nullptr, surface, &target);
    SDL_FreeSurface(text);
}
void clear_cache() {
    if (panel) SDL_DestroyTexture(panel);
    panel = nullptr;
    cached_renderer = nullptr;
    panel_revision = 0;
}
void build(int width, int height, float scale) {
    if (scale != cached_scale || !body_font) {
        if (body_font) TTF_CloseFont(body_font);
        if (title_font) TTF_CloseFont(title_font);
        if (small_font) TTF_CloseFont(small_font);
        const char* font = std::getenv("VASTGAME_HUD_FONT");
        if (!font) font = "/usr/share/fonts/TTF/DejaVuSans.ttf";
        body_font = TTF_OpenFont(font, std::max(11, int(15 * scale)));
        title_font = TTF_OpenFont(font, std::max(15, int(21 * scale)));
        small_font = TTF_OpenFont(font, std::max(10, int(11 * scale)));
    }
    cached_width = width; cached_height = height; cached_scale = scale;
    auto* surface = SDL_CreateRGBSurfaceWithFormat(0, width, height, 32, SDL_PIXELFORMAT_RGBA32);
    if (!surface) return;
    SDL_FillRect(surface, nullptr, color(surface, 0, 0, 0, 0));
    rounded(surface, 0, 0, width, height, std::max(10, int(20 * scale)), color(surface, background));
    const int pad = int(22 * scale), row_h = int(43 * scale), row_y = int(68 * scale);
    label(surface, title_font, "Stream", pad, int(19 * scale), foreground);
    const std::vector<std::string> titles{"Resolution", "Frame rate", "Bitrate", "Codec", "VSync", "Frame pacing", "Save"};
    const std::vector<std::string> values{
        resolutions[resolution_index] == "native" ? "Native" : resolutions[resolution_index],
        rates[rate_index] == "native" ? "Native" : rates[rate_index] + " FPS",
        bitrate ? std::to_string(bitrate) + " Mbps" : "Auto",
        codecs[codec_index] == "auto" ? "Auto" : codecs[codec_index],
        vsync ? "On" : "Off", pacing ? "On" : "Off", ""};
    for (int i = 0; i < int(titles.size()); ++i) {
        const int y = row_y + i * row_h;
        const int button_y = y - int(3 * scale), button_h = row_h - int(2 * scale);
        if (i == selected)
            rounded(surface, int(10 * scale), button_y, width - int(20 * scale), button_h,
                    int(13 * scale), color(surface, selection));
        label(surface, body_font, titles[i], pad, button_y, foreground, false, button_h);
        label(surface, body_font, values[i], width - pad, button_y,
              i == selected ? foreground : accent, true, button_h);
        if (i == 2) {
            const int track_y = y + int(32 * scale), track_w = width - pad * 2;
            rounded(surface, pad, track_y, track_w, std::max(3, int(4 * scale)), int(2 * scale), color(surface, selection));
            if (bitrate) {
                const int fill = std::max(4, track_w * bitrate / 500);
                rounded(surface, pad, track_y, fill, std::max(3, int(4 * scale)), int(2 * scale), color(surface, accent));
                rounded(surface, pad + fill - int(5 * scale), track_y - int(3 * scale), int(10 * scale), int(10 * scale),
                        int(5 * scale), color(surface, foreground));
            }
        }
    }
    const std::string foot = status.empty() ? "Arrows adjust  ·  Enter saves  ·  Esc closes" : status;
    label(surface, small_font, foot, pad, height - int(28 * scale), accent);
    if (card) SDL_FreeSurface(card);
    card = surface;
    ++revision;
    dirty = false;
}

bool frame(SDL_Window* window, int screen_w, int screen_h, SDL_Rect& target) {
    const Uint32 tick = SDL_GetTicks();
    const Uint32 delta = last_frame ? std::min<Uint32>(tick - last_frame, 50) : 0;
    last_frame = tick;
    progress = std::clamp(progress + (opened ? 1.f : -1.f) * delta / 220.f, 0.f, 1.f);
    if (progress <= 0 || screen_w < 300 || screen_h < 300) return false;
    const int margin = std::clamp(int(std::min(screen_w, screen_h) * .025), 12, 32);
    float dpi = 96;
    if (window) {
        const int display = SDL_GetWindowDisplayIndex(window);
        if (display >= 0 && (SDL_GetDisplayDPI(display, &dpi, nullptr, nullptr) || dpi < 50)) dpi = 96;
    }
    const float scale = std::min({std::clamp(dpi / 96, .85f, 1.8f),
                                  float(screen_w - 2 * margin) / 365,
                                  float(screen_h - 2 * margin) / 420});
    const int width = int(365 * scale), height = int(420 * scale);
    if (tick - last_status >= 250) {
        std::ifstream input(folder() + "/menu.status");
        std::string next;
        if (std::getline(input, next) && next != status) { status = next.substr(0, 72); dirty = true; }
        last_status = tick;
    }
    if (dirty || !card || width != cached_width || height != cached_height || scale != cached_scale)
        build(width, height, scale);
    if (!card) return false;
    const float eased = 1 - std::pow(1 - progress, 3);
    target = {margin, screen_h + margin - int((height + 2 * margin) * eased), width, height};
    return true;
}
}

bool stream_menu_event(SDL_Event* event) {
    if (!event) return false;
    std::lock_guard<std::mutex> lock(guard);
    if ((event->type == SDL_KEYDOWN || event->type == SDL_KEYUP) &&
        event->key.keysym.sym == SDLK_q && (event->key.keysym.mod & KMOD_CTRL) &&
        (event->key.keysym.mod & KMOD_SHIFT) && !(event->key.keysym.mod & (KMOD_ALT | KMOD_GUI))) {
        if (event->type == SDL_KEYDOWN && !event->key.repeat) {
            load(); opened = !opened; dirty = true;
            publish("menu.toggle", opened ? "open\n" : "closed\n");
        }
        return true;
    }
    if (!opened) return false;
    if (event->type == SDL_TEXTINPUT) return true;
    if (event->type != SDL_KEYDOWN && event->type != SDL_KEYUP) return false;
    if (event->key.keysym.sym == SDLK_TAB && (event->key.keysym.mod & KMOD_ALT)) return false;
    // Let releases reach Moonlight so a key held before opening cannot stick in the game.
    if (event->type == SDL_KEYUP) return false;
    if (event->key.repeat) return true;
    switch (event->key.keysym.sym) {
        case SDLK_ESCAPE: opened = false; break;
        case SDLK_UP: selected = (selected + 6) % 7; dirty = true; break;
        case SDLK_DOWN: selected = (selected + 1) % 7; dirty = true; break;
        case SDLK_LEFT: change(-1); break;
        case SDLK_RIGHT: change(1); break;
        case SDLK_RETURN: case SDLK_KP_ENTER: if (selected == 6) save(); else change(1); break;
        default: break;
    }
    return true;
}

void stream_menu_present(SDL_Renderer* renderer) {
    if (folder().empty()) return;
    std::lock_guard<std::mutex> lock(guard);
    if (!opened && progress <= 0) { last_frame = SDL_GetTicks(); return; }
    if (SDL_GetRenderTarget(renderer)) return;
    int screen_w = 0, screen_h = 0;
    if (SDL_GetRendererOutputSize(renderer, &screen_w, &screen_h)) return;
    SDL_Rect target{};
    if (!frame(SDL_RenderGetWindow(renderer), screen_w, screen_h, target)) return;
    if (!panel || renderer != cached_renderer || panel_revision != revision) {
        if (panel) SDL_DestroyTexture(panel);
        panel = SDL_CreateTextureFromSurface(renderer, card);
        cached_renderer = renderer;
        panel_revision = revision;
        if (panel) SDL_SetTextureBlendMode(panel, SDL_BLENDMODE_BLEND);
    }
    if (!panel) return;
    int logical_w = 0, logical_h = 0;
    float scale_x = 1, scale_y = 1;
    SDL_Rect viewport{}, clip{};
    SDL_RenderGetLogicalSize(renderer, &logical_w, &logical_h);
    SDL_RenderGetScale(renderer, &scale_x, &scale_y);
    SDL_RenderGetViewport(renderer, &viewport);
    const SDL_bool clipped = SDL_RenderIsClipEnabled(renderer);
    if (clipped) SDL_RenderGetClipRect(renderer, &clip);
    SDL_RenderSetLogicalSize(renderer, 0, 0);
    SDL_RenderSetScale(renderer, 1, 1);
    SDL_RenderSetViewport(renderer, nullptr);
    SDL_RenderSetClipRect(renderer, nullptr);
    SDL_RenderCopy(renderer, panel, nullptr, &target);
    SDL_RenderSetLogicalSize(renderer, logical_w, logical_h);
    SDL_RenderSetScale(renderer, scale_x, scale_y);
    SDL_RenderSetViewport(renderer, &viewport);
    if (clipped) SDL_RenderSetClipRect(renderer, &clip);
}

void stream_menu_renderer_destroyed(SDL_Renderer* renderer) {
    std::lock_guard<std::mutex> lock(guard);
    if (renderer == cached_renderer) clear_cache();
}

#ifdef VASTGAME_GLES_MENU
namespace {
struct GLMenu {
    SDL_GLContext context = nullptr;
    GLuint program = 0, texture = 0, buffer = 0, vao = 0;
    unsigned uploaded = 0;
    bool unavailable = false;
} gl_menu;

using BindVao = PFNGLBINDVERTEXARRAYOESPROC;
BindVao bind_vao = nullptr;
const char* vao_name(const char* extension, const char* core) {
    return SDL_GL_ExtensionSupported("GL_OES_vertex_array_object") ? extension : core;
}

GLuint shader(GLenum kind, const char* source) {
    GLuint object = glCreateShader(kind);
    if (!object) return 0;
    glShaderSource(object, 1, &source, nullptr);
    glCompileShader(object);
    GLint okay = GL_FALSE;
    glGetShaderiv(object, GL_COMPILE_STATUS, &okay);
    if (okay) return object;
    glDeleteShader(object);
    return 0;
}

bool initialize_gl(SDL_GLContext context) {
    if (gl_menu.context != context) gl_menu = GLMenu{context};
    if (gl_menu.unavailable) return false;
    if (gl_menu.program) return true;
    auto gen_vao = reinterpret_cast<PFNGLGENVERTEXARRAYSOESPROC>(
        SDL_GL_GetProcAddress(vao_name("glGenVertexArraysOES", "glGenVertexArrays")));
    bind_vao = reinterpret_cast<BindVao>(
        SDL_GL_GetProcAddress(vao_name("glBindVertexArrayOES", "glBindVertexArray")));
    if (!gen_vao || !bind_vao) {
        gl_menu.unavailable = true;
        publish("menu.error", "OpenGL vertex arrays unavailable\n");
        return false;
    }
    constexpr const char* vertex =
        "attribute vec2 aPosition; attribute vec2 aTexCoord; uniform vec4 uRect;"
        "varying vec2 vTexCoord; void main() { vTexCoord=aTexCoord;"
        "gl_Position=vec4(uRect.xy+aPosition*uRect.zw,0.0,1.0); }";
    constexpr const char* fragment =
        "precision mediump float; varying vec2 vTexCoord; uniform sampler2D uTexture;"
        "void main() { gl_FragColor=texture2D(uTexture,vTexCoord); }";
    GLuint vs = shader(GL_VERTEX_SHADER, vertex), fs = shader(GL_FRAGMENT_SHADER, fragment);
    if (!vs || !fs) {
        if (vs) glDeleteShader(vs);
        if (fs) glDeleteShader(fs);
        gl_menu.unavailable = true;
        publish("menu.error", "OpenGL menu shader failed\n");
        return false;
    }
    gl_menu.program = glCreateProgram();
    if (!gl_menu.program) {
        glDeleteShader(vs); glDeleteShader(fs); gl_menu.unavailable = true;
        publish("menu.error", "OpenGL menu program allocation failed\n");
        return false;
    }
    glAttachShader(gl_menu.program, vs);
    glAttachShader(gl_menu.program, fs);
    glBindAttribLocation(gl_menu.program, 0, "aPosition");
    glBindAttribLocation(gl_menu.program, 1, "aTexCoord");
    glLinkProgram(gl_menu.program);
    glDeleteShader(vs);
    glDeleteShader(fs);
    GLint okay = GL_FALSE;
    glGetProgramiv(gl_menu.program, GL_LINK_STATUS, &okay);
    if (!okay) {
        glDeleteProgram(gl_menu.program); gl_menu.program = 0; gl_menu.unavailable = true;
        publish("menu.error", "OpenGL menu program failed\n");
        return false;
    }
    glGenTextures(1, &gl_menu.texture);
    glBindTexture(GL_TEXTURE_2D, gl_menu.texture);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    gen_vao(1, &gl_menu.vao);
    bind_vao(gl_menu.vao);
    glGenBuffers(1, &gl_menu.buffer);
    glBindBuffer(GL_ARRAY_BUFFER, gl_menu.buffer);
    constexpr GLfloat quad[] = {
        0,0, 0,1,  1,0, 1,1,  0,1, 0,0,  1,1, 1,0,
    };
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 4*sizeof(GLfloat), nullptr);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 4*sizeof(GLfloat), reinterpret_cast<void*>(2*sizeof(GLfloat)));
    glEnableVertexAttribArray(0);
    glEnableVertexAttribArray(1);
    return true;
}

void enabled(GLenum capability, GLboolean was_enabled) {
    if (was_enabled) glEnable(capability); else glDisable(capability);
}
}

void stream_menu_gl_present(SDL_Window* window) {
    if (folder().empty()) return;
    std::lock_guard<std::mutex> lock(guard);
    if (!opened && progress <= 0) { last_frame = SDL_GetTicks(); return; }
    if (!SDL_GL_GetCurrentContext()) return;
    auto get_version = reinterpret_cast<const GLubyte* (*)(GLenum)>(SDL_GL_GetProcAddress("glGetString"));
    const auto* version = get_version ? get_version(GL_VERSION) : nullptr;
    if (!version || std::strncmp(reinterpret_cast<const char*>(version), "OpenGL ES", 9) != 0) return;
    if (!SDL_GL_GetProcAddress(vao_name("glGenVertexArraysOES", "glGenVertexArrays")) ||
        !SDL_GL_GetProcAddress(vao_name("glBindVertexArrayOES", "glBindVertexArray")))
        return;
    int width = 0, height = 0;
    SDL_GL_GetDrawableSize(window, &width, &height);
    SDL_Rect target{};
    if (!frame(window, width, height, target)) return;
    GLint framebuffer = 0;
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &framebuffer);
    if (framebuffer != 0) return;

    GLint old_program = 0, old_active = 0, old_texture = 0, old_buffer = 0, old_vao = 0;
    GLint viewport[4], blend_src_rgb = 0, blend_dst_rgb = 0, blend_src_alpha = 0, blend_dst_alpha = 0;
    GLint blend_eq_rgb = 0, blend_eq_alpha = 0, unpack = 0;
    GLboolean color_mask[4];
    const GLboolean blend = glIsEnabled(GL_BLEND), scissor = glIsEnabled(GL_SCISSOR_TEST);
    const GLboolean depth = glIsEnabled(GL_DEPTH_TEST), stencil = glIsEnabled(GL_STENCIL_TEST);
    const GLboolean cull = glIsEnabled(GL_CULL_FACE);
    glGetIntegerv(GL_CURRENT_PROGRAM, &old_program);
    glGetIntegerv(GL_ACTIVE_TEXTURE, &old_active);
    glActiveTexture(GL_TEXTURE0);
    glGetIntegerv(GL_TEXTURE_BINDING_2D, &old_texture);
    glGetIntegerv(GL_ARRAY_BUFFER_BINDING, &old_buffer);
    glGetIntegerv(GL_VERTEX_ARRAY_BINDING_OES, &old_vao);
    glGetIntegerv(GL_VIEWPORT, viewport);
    glGetIntegerv(GL_BLEND_SRC_RGB, &blend_src_rgb);
    glGetIntegerv(GL_BLEND_DST_RGB, &blend_dst_rgb);
    glGetIntegerv(GL_BLEND_SRC_ALPHA, &blend_src_alpha);
    glGetIntegerv(GL_BLEND_DST_ALPHA, &blend_dst_alpha);
    glGetIntegerv(GL_BLEND_EQUATION_RGB, &blend_eq_rgb);
    glGetIntegerv(GL_BLEND_EQUATION_ALPHA, &blend_eq_alpha);
    glGetIntegerv(GL_UNPACK_ALIGNMENT, &unpack);
    glGetBooleanv(GL_COLOR_WRITEMASK, color_mask);

    const auto context = SDL_GL_GetCurrentContext();
    if (initialize_gl(context)) {
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, gl_menu.texture);
        if (gl_menu.uploaded != revision) {
            glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, card->w, card->h, 0, GL_RGBA, GL_UNSIGNED_BYTE, card->pixels);
            gl_menu.uploaded = revision;
        }
        glViewport(0, 0, width, height);
        glDisable(GL_SCISSOR_TEST);
        glDisable(GL_DEPTH_TEST);
        glDisable(GL_STENCIL_TEST);
        glDisable(GL_CULL_FACE);
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        glEnable(GL_BLEND);
        glBlendEquation(GL_FUNC_ADD);
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glUseProgram(gl_menu.program);
        glUniform1i(glGetUniformLocation(gl_menu.program, "uTexture"), 0);
        glUniform4f(glGetUniformLocation(gl_menu.program, "uRect"),
            -1.f + 2.f*target.x/width, 1.f - 2.f*(target.y+target.h)/height,
            2.f*target.w/width, 2.f*target.h/height);
        bind_vao(gl_menu.vao);
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    }

    if (bind_vao) bind_vao(old_vao);
    glBindBuffer(GL_ARRAY_BUFFER, old_buffer);
    glUseProgram(old_program);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, old_texture);
    glActiveTexture(old_active);
    glViewport(viewport[0], viewport[1], viewport[2], viewport[3]);
    glBlendEquationSeparate(blend_eq_rgb, blend_eq_alpha);
    glBlendFuncSeparate(blend_src_rgb, blend_dst_rgb, blend_src_alpha, blend_dst_alpha);
    glPixelStorei(GL_UNPACK_ALIGNMENT, unpack);
    glColorMask(color_mask[0], color_mask[1], color_mask[2], color_mask[3]);
    enabled(GL_BLEND, blend); enabled(GL_SCISSOR_TEST, scissor);
    enabled(GL_DEPTH_TEST, depth); enabled(GL_STENCIL_TEST, stencil); enabled(GL_CULL_FACE, cull);
}

void stream_menu_gl_context_destroyed(SDL_GLContext context) {
    std::lock_guard<std::mutex> lock(guard);
    if (gl_menu.context == context) gl_menu = GLMenu{};
}
#endif
