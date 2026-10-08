#pragma once
#include <SDL.h>

bool stream_menu_event(SDL_Event* event);
void stream_menu_present(SDL_Renderer* renderer);
void stream_menu_renderer_destroyed(SDL_Renderer* renderer);
#ifdef VASTGAME_GLES_MENU
void stream_menu_gl_present(SDL_Window* window);
void stream_menu_gl_context_destroyed(SDL_GLContext context);
#endif
