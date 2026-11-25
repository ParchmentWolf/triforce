/* SDL3 or SDL2 behind one set of calls (hos_sdl.h). Each call is SDL3's or SDL2's, the same work under other names;
   SDL3 returns C's bool where SDL2 returned 0 for success or an SDL_bool, and the events and a few structures are laid
   out differently (both read here at their offsets: SDL_Event is 128 bytes in SDL3, 56 in SDL2). */
#include "hos.h"
#include "hos_sdl.h"
#include "pad_kind.h"   /* ((Triforce) 11-20: instruments and dance mats left out of the game's input) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include "audio_output_devices.h"   /* ((Triforce) HOS_OUTPUT_ID_CAP and audio_output_copy_id: the playback devices by name) */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#ifdef _WIN32   /* ((Triforce) a DualSense's own sound card by its device container: hos_sdl_pad_audio_endpoint) */
#include <setupapi.h>
#include <devpropdef.h>
#include <mmdeviceapi.h>
#include <propsys.h>
#include <objbase.h>
#endif

static int version;   /* 3, 2, or 0 none */
static struct {
    void *InitSubSystem, *SetHint, *GetError;
    /* window */
    void *CreateWindow, *SetWindowPosition, *SetWindowFullscreen, *SetRelativeMouseMode, *GetPrimaryDisplay,
        *GetDesktopDisplayMode, *Vulkan_CreateSurface, *PixelSize, *GetKeyboardState, *GetMouseState, *WaitEventTimeout,
        *PollEvent, *GetWindowSize, *LoadPNG, *SetWindowIcon, *DestroySurface, *GetWindowDisplay, *GetCurrentDisplayMode;
    void *GetDisplays, *GetDisplayName;   /* ((Triforce) optional: every display, hos_sdl_displays) */
    void *ShowSimpleMessageBox;           /* ((Triforce, 11-24) optional: hos_sdl_message_box) */
    /* sound */
    void *OpenAudioDevice, *PauseAudioDevice, *OpenAudioDeviceStream, *ResumeAudioStreamDevice, *PutAudioStreamData;
    /* controllers */
    void *PadOpen, *PadClose, *PadConnected, *PadsUpdate, *PadButton, *PadAxis, *PadName, *PadRumble;
    void *PadType, *PadEffect;   /* (optional: HD rumble, host/pad_sdl.c) */
    void *PadRumbleTriggers;     /* (optional: the motors in an Xbox pad's triggers, host/pad_sdl.c) */
    void *PadHasSensor, *PadSensorEnable, *PadSensorData;   /* (motion: optional, NULL in an SDL without them) */
    /* ((Triforce) 11-24: Steam's stand-in pads and the Steam Deck's own controls: optional, host/steam_pads.h) */
    void *PadVendor, *PadProduct, *PadSteamHandle, *SetHintPriority;
    void *GetGamepads, *GetGamepadID, *Free;   /* (SDL3) */
    void *NumJoysticks, *IsGameController, *DeviceInstanceID, *GetJoystick, *JoystickInstanceID;   /* (SDL2; GetJoystick SDL3's too, for the log) */
    void *JoystickGUID, *PadMapping;   /* ((Triforce) optional, for the log of a controller's connection: no serial number, no device path) */
    void *JoyTypeOf, *PadNameOf;   /* ((Triforce) 11-20, optional: a controller's type and name before it is opened: pad_kind.h) */
} f;
#define CALL(type, fn) ((type)f.fn)

static HMODULE load_one(const char *dll) {   /* beside the executable, else the system's */
    char path[MAX_PATH];
    DWORD n = GetModuleFileNameA(NULL, path, sizeof path);
    while (n && path[n - 1] != '\\' && path[n - 1] != '/') n--;
    snprintf(path + n, sizeof path - n, "%s", dll);
    HMODULE m = n ? LoadLibraryA(path) : NULL;   /* (no folder: a bare name would search the current folder and PATH) */
#ifdef _WIN32   /* (hookshot: else the system's, not the current folder's or PATH's) */
    return m ? m : LoadLibraryExA(dll, NULL, LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
#else
    return m ? m : LoadLibraryA(dll);
#endif
}
static int get_all(HMODULE m, int three) {
#define GET(field, name) if (!(*(FARPROC *)&f.field = GetProcAddress(m, name))) { hos_log("sdl: SDL%d has no %s", three ? 3 : 2, name); return 0; }
#define GET2(field, n3, n2) GET(field, three ? n3 : n2)
    GET(InitSubSystem, "SDL_InitSubSystem");
    GET(SetHint, "SDL_SetHint");
    GET(GetError, "SDL_GetError");
    GET(CreateWindow, "SDL_CreateWindow");
    GET(SetWindowFullscreen, "SDL_SetWindowFullscreen");
    GET2(SetRelativeMouseMode, "SDL_SetWindowRelativeMouseMode", "SDL_SetRelativeMouseMode");
    GET(GetDesktopDisplayMode, "SDL_GetDesktopDisplayMode");
    GET(Vulkan_CreateSurface, "SDL_Vulkan_CreateSurface");
    GET2(PixelSize, "SDL_GetWindowSizeInPixels", "SDL_Vulkan_GetDrawableSize");
    GET(GetKeyboardState, "SDL_GetKeyboardState");
    GET(GetMouseState, "SDL_GetMouseState");
    GET(GetWindowSize, "SDL_GetWindowSize");
    GET(WaitEventTimeout, "SDL_WaitEventTimeout");
    GET(PollEvent, "SDL_PollEvent");
    GET2(PadOpen, "SDL_OpenGamepad", "SDL_GameControllerOpen");
    GET2(PadClose, "SDL_CloseGamepad", "SDL_GameControllerClose");
    GET2(PadConnected, "SDL_GamepadConnected", "SDL_GameControllerGetAttached");
    GET2(PadsUpdate, "SDL_UpdateGamepads", "SDL_GameControllerUpdate");
    GET2(PadButton, "SDL_GetGamepadButton", "SDL_GameControllerGetButton");
    GET2(PadAxis, "SDL_GetGamepadAxis", "SDL_GameControllerGetAxis");
    GET2(PadName, "SDL_GetGamepadName", "SDL_GameControllerName");
    GET2(PadRumble, "SDL_RumbleGamepad", "SDL_GameControllerRumble");
    /* (SDL2 2.0.12 and 2.0.16 on, SDL3 3.2 on: without them every pad keeps the motor rumble) */
    *(FARPROC *)&f.PadType = GetProcAddress(m, three ? "SDL_GetGamepadType" : "SDL_GameControllerGetType");
    *(FARPROC *)&f.PadEffect = GetProcAddress(m, three ? "SDL_SendGamepadEffect" : "SDL_GameControllerSendEffect");
    /* ((Triforce) the triggers' motors: SDL2 2.0.14 on and every SDL3; without the call they stay still) */
    *(FARPROC *)&f.PadRumbleTriggers = GetProcAddress(m, three ? "SDL_RumbleGamepadTriggers" : "SDL_GameControllerRumbleTriggers");
    /* (motion sensors: SDL 2.0.14 on and every SDL3; without them the pads still play, with no gyro) */
    *(FARPROC *)&f.PadHasSensor = GetProcAddress(m, three ? "SDL_GamepadHasSensor" : "SDL_GameControllerHasSensor");
    *(FARPROC *)&f.PadSensorEnable = GetProcAddress(m, three ? "SDL_SetGamepadSensorEnabled" : "SDL_GameControllerSetSensorEnabled");
    *(FARPROC *)&f.PadSensorData = GetProcAddress(m, three ? "SDL_GetGamepadSensorData" : "SDL_GameControllerGetSensorData");
    /* ((Triforce) 11-24: Steam's stand-in pads told apart from the real ones: SDL 2.30 on and SDL3 3.2 on; without them
       Steam's controller ignore list stays as Steam set it, and no pad is anyone's stand-in) */
    *(FARPROC *)&f.PadVendor = GetProcAddress(m, three ? "SDL_GetGamepadVendor" : "SDL_GameControllerGetVendor");
    *(FARPROC *)&f.PadProduct = GetProcAddress(m, three ? "SDL_GetGamepadProduct" : "SDL_GameControllerGetProduct");
    *(FARPROC *)&f.PadSteamHandle = GetProcAddress(m, three ? "SDL_GetGamepadSteamHandle" : "SDL_GameControllerGetSteamHandle");
    *(FARPROC *)&f.SetHintPriority = GetProcAddress(m, "SDL_SetHintWithPriority");
    /* ((Triforce) 11-20) a controller's type and name by its place in the list, for the instruments left out (pad_kind.h) */
    *(FARPROC *)&f.JoyTypeOf = GetProcAddress(m, three ? "SDL_GetJoystickTypeForID" : "SDL_JoystickGetDeviceType");
    *(FARPROC *)&f.PadNameOf = GetProcAddress(m, three ? "SDL_GetGamepadNameForID" : "SDL_GameControllerNameForIndex");
    /* ((Triforce) every connected display and its name: SDL3's list of ids, SDL2's count; without them the main one alone) */
    *(FARPROC *)&f.GetDisplays = GetProcAddress(m, three ? "SDL_GetDisplays" : "SDL_GetNumVideoDisplays");
    *(FARPROC *)&f.GetDisplayName = GetProcAddress(m, "SDL_GetDisplayName");
    *(FARPROC *)&f.ShowSimpleMessageBox = GetProcAddress(m, "SDL_ShowSimpleMessageBox");
    /* ((Triforce) a controller's hardware GUID and its active mapping, for the log: hos_sdl_pad_log_connection) */
    *(FARPROC *)&f.JoystickGUID = GetProcAddress(m, three ? "SDL_GetJoystickGUID" : "SDL_JoystickGetGUID");
    *(FARPROC *)&f.PadMapping = GetProcAddress(m, three ? "SDL_GetGamepadMapping" : "SDL_GameControllerMapping");
    if (three) {
        *(FARPROC *)&f.GetJoystick = GetProcAddress(m, "SDL_GetGamepadJoystick");   /* (optional: the log's alone) */
        GET(SetWindowPosition, "SDL_SetWindowPosition");
        GET(GetPrimaryDisplay, "SDL_GetPrimaryDisplay");
        GET(OpenAudioDeviceStream, "SDL_OpenAudioDeviceStream");
        GET(ResumeAudioStreamDevice, "SDL_ResumeAudioStreamDevice");
        GET(PutAudioStreamData, "SDL_PutAudioStreamData");
        GET(GetGamepads, "SDL_GetGamepads");
        GET(GetGamepadID, "SDL_GetGamepadID");
        GET(Free, "SDL_free");
        *(FARPROC *)&f.LoadPNG = GetProcAddress(m, "SDL_LoadPNG");   /* (3.4 on: the icon, when there) */
        *(FARPROC *)&f.SetWindowIcon = GetProcAddress(m, "SDL_SetWindowIcon");
        *(FARPROC *)&f.DestroySurface = GetProcAddress(m, "SDL_DestroySurface");
        *(FARPROC *)&f.GetWindowDisplay = GetProcAddress(m, "SDL_GetDisplayForWindow");   /* (the refresh: hos_sdl_refresh_mhz) */
        *(FARPROC *)&f.GetCurrentDisplayMode = GetProcAddress(m, "SDL_GetCurrentDisplayMode");
    } else {
        *(FARPROC *)&f.Free = GetProcAddress(m, "SDL_free");   /* (optional: without it no mapping, which is SDL's to free, is asked for) */
        *(FARPROC *)&f.GetWindowDisplay = GetProcAddress(m, "SDL_GetWindowDisplayIndex");   /* (the refresh: hos_sdl_refresh_mhz) */
        *(FARPROC *)&f.GetCurrentDisplayMode = GetProcAddress(m, "SDL_GetCurrentDisplayMode");
        GET(OpenAudioDevice, "SDL_OpenAudioDevice");
        GET(PauseAudioDevice, "SDL_PauseAudioDevice");
        GET(NumJoysticks, "SDL_NumJoysticks");
        GET(IsGameController, "SDL_IsGameController");
        GET(DeviceInstanceID, "SDL_JoystickGetDeviceInstanceID");
        GET(GetJoystick, "SDL_GameControllerGetJoystick");
        GET(JoystickInstanceID, "SDL_JoystickInstanceID");
    }
#undef GET2
#undef GET
    return 1;
}
int hos_sdl_load(void) {
    static volatile LONG state;   /* 0 not tried, 1 loading, 2 done */
    if (InterlockedCompareExchange(&state, 1, 0) == 0) {
        const char *want = getenv("HOS_SDL_VERSION");
        HMODULE m = want && atoi(want) == 2 ? NULL : load_one("SDL3.dll");
        if (m && get_all(m, 1)) version = 3;
        else if ((m = load_one("SDL2.dll")) && get_all(m, 0)) version = 2;
        hos_log(version ? "sdl: SDL%d" : "sdl: no SDL3 or SDL2 found: no window, sound or SDL controllers", version);
        InterlockedExchange(&state, 2);
    }
    while (state != 2) Sleep(0);
    return version;
}

int hos_sdl_init(uint32_t subsystems) {
    if (!hos_sdl_load()) return 0;
    return version == 3 ? CALL(_Bool (*)(uint32_t), InitSubSystem)(subsystems)
                        : CALL(int (*)(uint32_t), InitSubSystem)(subsystems) == 0;
}
void hos_sdl_hint(const char *name, const char *value) {
    if (!hos_sdl_load()) return;
    if (version == 3) CALL(_Bool (*)(const char *, const char *), SetHint)(name, value);
    else CALL(int (*)(const char *, const char *), SetHint)(name, value);
}
/* ((Triforce) 11-24) a hint over the environment's own (SDL_HINT_OVERRIDE, 2 in both): a variable Steam sets for the
   games it starts wins over SDL_SetHint. 0 when the SDL has no SDL_SetHintWithPriority */
int hos_sdl_hint_override(const char *name, const char *value) {
    if (!hos_sdl_load() || !f.SetHintPriority) return 0;
    if (version == 3) return CALL(_Bool (*)(const char *, const char *, int), SetHintPriority)(name, value, 2);
    return CALL(int (*)(const char *, const char *, int), SetHintPriority)(name, value, 2) != 0;
}
void hos_sdl_identity(const char *name, const char *app_id) {
    if (!hos_sdl_load()) return;
    if (version == 3) {
        static void *set;
        if (!set) {
            HMODULE m = load_one("SDL3.dll");   /* (the one loaded: the same handle back) */
            set = m ? (void *)GetProcAddress(m, "SDL_SetAppMetadata") : NULL;
        }
        if (set) ((_Bool (*)(const char *, const char *, const char *))set)(name, NULL, app_id);
        return;
    }
    hos_sdl_hint("SDL_APP_NAME", name);
#ifndef _WIN32   /* (SDL2 reads the window's class from these, not from hints) */
    setenv("SDL_VIDEO_WAYLAND_WMCLASS", app_id, 0);
    setenv("SDL_VIDEO_X11_WMCLASS", app_id, 0);
#endif
}
const char *hos_sdl_error(void) { return version ? CALL(const char *(*)(void), GetError)() : "no SDL"; }

/* ---- the window ---- */
enum { WIN_SHOWN2 = 0x4, WIN_RESIZABLE = 0x20, WIN_HIGH_DENSITY = 0x2000, WIN_VULKAN = 0x10000000, CENTRED = 0x2FFF0000 };
void *hos_sdl_window(const char *title, int width, int height) {
    if (version == 2)
        return CALL(void *(*)(const char *, int, int, int, int, uint32_t), CreateWindow)(
            title, CENTRED, CENTRED, width, height, WIN_SHOWN2 | WIN_RESIZABLE | WIN_HIGH_DENSITY | WIN_VULKAN);
    void *w = CALL(void *(*)(const char *, int, int, uint64_t), CreateWindow)(title, width, height,
                                                                              WIN_RESIZABLE | WIN_HIGH_DENSITY | WIN_VULKAN);
    if (w) CALL(_Bool (*)(void *, int, int), SetWindowPosition)(w, CENTRED, CENTRED);
    return w;
}
void hos_sdl_fullscreen(void *window, int on) {
    if (version == 3) CALL(_Bool (*)(void *, _Bool), SetWindowFullscreen)(window, on != 0);
    else CALL(int (*)(void *, uint32_t), SetWindowFullscreen)(window, on ? 0x1001 /* FULLSCREEN_DESKTOP */ : 0);
}
void hos_sdl_relative_mouse(void *window, int on) {
    if (version == 3) CALL(_Bool (*)(void *, _Bool), SetRelativeMouseMode)(window, on != 0);
    else CALL(int (*)(int), SetRelativeMouseMode)(on);
}
int hos_sdl_desktop_size(int *width, int *height) {
    if (version == 3) {   /* (SDL_DisplayMode: displayID, format, w and h at 8 and 12 in screen units, pixel_density at
                             16: in pixels, as SDL2 gave them) */
        const uint8_t *m = CALL(const uint8_t *(*)(uint32_t), GetDesktopDisplayMode)(CALL(uint32_t (*)(void), GetPrimaryDisplay)());
        if (!m) return 0;
        int w, h;
        float density;
        memcpy(&w, m + 8, 4), memcpy(&h, m + 12, 4), memcpy(&density, m + 16, 4);
        if (!(density > 0)) density = 1;
        *width = (int)(w * density + 0.5f), *height = (int)(h * density + 0.5f);
        return 1;
    }
    struct { uint32_t format; int w, h, refresh_rate; void *driverdata; } m;
    if (CALL(int (*)(int, void *), GetDesktopDisplayMode)(0, &m)) return 0;
    *width = m.w, *height = m.h;
    return 1;
}
int hos_sdl_displays(HosSdlDisplay *out, int cap) {
    int n = 0;
    if (!f.GetDisplays) return 0;
    if (version == 3) {   /* (SDL_GetDisplays: the ids, freed with SDL_free; SDL_DisplayMode as above) */
        int count = 0;
        uint32_t *ids = CALL(uint32_t *(*)(int *), GetDisplays)(&count);
        /* (the main display first, whatever SDL's order: it is the one hos_sdl_desktop_size reads) */
        const uint32_t main_id = CALL(uint32_t (*)(void), GetPrimaryDisplay)();
        for (int i = 1; ids && i < count; i++)
            if (ids[i] == main_id) ids[i] = ids[0], ids[0] = main_id;
        for (int i = 0; ids && i < count && n < cap; i++) {
            const uint8_t *m = CALL(const uint8_t *(*)(uint32_t), GetDesktopDisplayMode)(ids[i]);
            if (!m) continue;
            int w, h;
            float density;
            memcpy(&w, m + 8, 4), memcpy(&h, m + 12, 4), memcpy(&density, m + 16, 4);
            if (!(density > 0)) density = 1;
            const char *name = f.GetDisplayName ? CALL(const char *(*)(uint32_t), GetDisplayName)(ids[i]) : NULL;
            out[n].w = (int)(w * density + 0.5f), out[n].h = (int)(h * density + 0.5f);
            snprintf(out[n].name, sizeof out[n].name, "%s", name ? name : "");
            n++;
        }
        if (ids) CALL(void (*)(void *), Free)(ids);
        return n;
    }
    const int count = CALL(int (*)(void), GetDisplays)();   /* (SDL2: by index, 0 the main display) */
    for (int i = 0; i < count && n < cap; i++) {
        struct { uint32_t format; int w, h, refresh_rate; void *driverdata; } m;
        if (CALL(int (*)(int, void *), GetDesktopDisplayMode)(i, &m)) continue;
        const char *name = f.GetDisplayName ? CALL(const char *(*)(int), GetDisplayName)(i) : NULL;
        out[n].w = m.w, out[n].h = m.h;
        snprintf(out[n].name, sizeof out[n].name, "%s", name ? name : "");
        n++;
    }
    return n;
}
int hos_sdl_refresh_mhz(void *window) {
    if (!window || !f.GetWindowDisplay || !f.GetCurrentDisplayMode) return 0;
    float hz = 0;
    if (version == 3) {   /* (SDL_DisplayMode: refresh_rate, a float, at 20) */
        const uint32_t id = CALL(uint32_t (*)(void *), GetWindowDisplay)(window);
        const uint8_t *m = id ? CALL(const uint8_t *(*)(uint32_t), GetCurrentDisplayMode)(id) : NULL;
        if (m) memcpy(&hz, m + 20, 4);
    } else {
        const int index = CALL(int (*)(void *), GetWindowDisplay)(window);
        struct { uint32_t format; int w, h, refresh_rate; void *driverdata; } m;
        if (index >= 0 && CALL(int (*)(int, void *), GetCurrentDisplayMode)(index, &m) == 0) hz = (float)m.refresh_rate;
    }
    return hz > 1 && hz < 1000 ? (int)(hz * 1000 + 0.5f) : 0;
}
int hos_sdl_vulkan_surface(void *window, void *instance, void *surface_out) {
    return version == 3 ? CALL(_Bool (*)(void *, void *, const void *, void *), Vulkan_CreateSurface)(window, instance, NULL, surface_out)
                        : CALL(int (*)(void *, void *, void *), Vulkan_CreateSurface)(window, instance, surface_out) != 0;
}
void hos_sdl_pixel_size(void *window, int *width, int *height) {
    if (version == 3) CALL(_Bool (*)(void *, int *, int *), PixelSize)(window, width, height);
    else CALL(void (*)(void *, int *, int *), PixelSize)(window, width, height);
}
const uint8_t *hos_sdl_keys(int *count) {   /* (SDL3's bool and SDL2's Uint8: a byte each) */
    return CALL(const uint8_t *(*)(int *), GetKeyboardState)(count);
}
/* ((Triforce, 11-24) an error message in a window of its own, over the game's (NULL: none), until the player closes it
   (SDL_ShowSimpleMessageBox, flag SDL_MESSAGEBOX_ERROR, 0x10 in both SDLs; SDL3 answers a bool, SDL2 0 when shown) */
int hos_sdl_message_box(void *window, const char *title, const char *text) {
    if (!f.ShowSimpleMessageBox) return 0;
    if (version == 3) return CALL(_Bool (*)(uint32_t, const char *, const char *, void *), ShowSimpleMessageBox)(0x10, title, text, window) ? 1 : 0;
    return CALL(int (*)(uint32_t, const char *, const char *, void *), ShowSimpleMessageBox)(0x10, title, text, window) == 0;
}
void hos_sdl_icon(void *window, const char *png) {
    if (version != 3 || !f.LoadPNG || !f.SetWindowIcon || !f.DestroySurface) return;
    void *icon = CALL(void *(*)(const char *), LoadPNG)(png);
    if (!icon) return;
    CALL(_Bool (*)(void *, void *), SetWindowIcon)(window, icon);
    CALL(void (*)(void *), DestroySurface)(icon);
}
uint32_t hos_sdl_mouse_buttons(void) {
    return version == 3 ? CALL(uint32_t (*)(float *, float *), GetMouseState)(NULL, NULL)
                        : CALL(uint32_t (*)(int *, int *), GetMouseState)(NULL, NULL);
}
void hos_sdl_window_size(void *window, int *width, int *height) {
    if (version == 3) CALL(_Bool (*)(void *, int *, int *), GetWindowSize)(window, width, height);
    else CALL(void (*)(void *, int *, int *), GetWindowSize)(window, width, height);
}

/* ---- events ---- */
static void read_event(const uint8_t *raw, HosSdlEvent *e) {
    uint32_t type;
    memcpy(&type, raw, 4);
    memset(e, 0, sizeof *e);
    int32_t i[2];
    if (version == 3) {
        switch (type) {
        case 0x100: e->type = HOS_SDL_EV_QUIT; break;
        case 0x207: e->type = HOS_SDL_EV_RESIZED; break;   /* (PIXEL_SIZE_CHANGED) */
        case 0x20d: e->type = HOS_SDL_EV_MOUSE_LEAVE; break;
        case 0x20e: e->type = HOS_SDL_EV_FOCUS_GAINED; break;
        case 0x20f: e->type = HOS_SDL_EV_FOCUS_LOST; break;
        case 0x210: e->type = HOS_SDL_EV_CLOSE; break;
        case 0x300:   /* (SDL_KeyboardEvent: scancode at 24, mod at 32, repeat at 37) */
            e->type = HOS_SDL_EV_KEY_DOWN;
            memcpy(i, raw + 24, 4), e->scancode = i[0];
            memcpy(&e->mod, raw + 32, 2), e->repeat = raw[37];
            break;
        case 0x20c: e->type = HOS_SDL_EV_MOUSE_ENTER; break;
        case 0x400:   /* (SDL_MouseMotionEvent: x and y at 28 and 32, xrel and yrel at 36 and 40, floats) */
            e->type = HOS_SDL_EV_MOUSE_MOTION;
            memcpy(&e->x, raw + 28, 4), memcpy(&e->y, raw + 32, 4);
            memcpy(&e->dx, raw + 36, 4), memcpy(&e->dy, raw + 40, 4);
            break;
        case 0x401:
        case 0x402:   /* (SDL_MouseButtonEvent: button at 24, x and y at 28 and 32, floats) */
            e->type = type == 0x401 ? HOS_SDL_EV_MOUSE_DOWN : HOS_SDL_EV_MOUSE_UP;
            e->button = raw[24];
            memcpy(&e->x, raw + 28, 4), memcpy(&e->y, raw + 32, 4);
            break;
        case 0x403: {   /* (SDL_MouseWheelEvent: y at 28, a float; direction at 32, 1 flipped) */
            uint32_t dir;
            e->type = HOS_SDL_EV_MOUSE_WHEEL;
            memcpy(&e->wheel, raw + 28, 4), memcpy(&dir, raw + 32, 4);
            if (dir == 1) e->wheel = -e->wheel;
            break;
        }
        }
        return;
    }
    switch (type) {
    case 0x100: e->type = HOS_SDL_EV_QUIT; break;
    case 0x200:   /* (SDL_WindowEvent: what at 12) */
        e->type = raw[12] == 6 ? HOS_SDL_EV_RESIZED : raw[12] == 10 ? HOS_SDL_EV_MOUSE_ENTER : raw[12] == 11 ? HOS_SDL_EV_MOUSE_LEAVE
                : raw[12] == 12 ? HOS_SDL_EV_FOCUS_GAINED : raw[12] == 13 ? HOS_SDL_EV_FOCUS_LOST
                : raw[12] == 14 ? HOS_SDL_EV_CLOSE : HOS_SDL_EV_OTHER;
        break;
    case 0x300:   /* (SDL_KeyboardEvent: repeat at 13, scancode at 16, mod at 24) */
        e->type = HOS_SDL_EV_KEY_DOWN;
        memcpy(i, raw + 16, 4), e->scancode = i[0];
        memcpy(&e->mod, raw + 24, 2), e->repeat = raw[13];
        break;
    case 0x400:   /* (SDL_MouseMotionEvent: x and y at 20 and 24, xrel and yrel at 28 and 32, whole pixels) */
        e->type = HOS_SDL_EV_MOUSE_MOTION;
        memcpy(i, raw + 20, 8), e->x = (float)i[0], e->y = (float)i[1];
        memcpy(i, raw + 28, 8), e->dx = (float)i[0], e->dy = (float)i[1];
        break;
    case 0x401:
    case 0x402:   /* (SDL_MouseButtonEvent: button at 16, x and y at 20 and 24, whole pixels) */
        e->type = type == 0x401 ? HOS_SDL_EV_MOUSE_DOWN : HOS_SDL_EV_MOUSE_UP;
        e->button = raw[16];
        memcpy(i, raw + 20, 8), e->x = (float)i[0], e->y = (float)i[1];
        break;
    case 0x403: {   /* (SDL_MouseWheelEvent: y at 20, whole notches; direction at 24, 1 flipped) */
        uint32_t dir;
        e->type = HOS_SDL_EV_MOUSE_WHEEL;
        memcpy(i, raw + 20, 4), memcpy(&dir, raw + 24, 4);
        e->wheel = (float)(dir == 1 ? -i[0] : i[0]);
        break;
    }
    }
}
int hos_sdl_wait_event(HosSdlEvent *e, int timeout_ms) {
    _Alignas(8) uint8_t raw[128];
    const int got = version == 3 ? CALL(_Bool (*)(void *, int32_t), WaitEventTimeout)(raw, timeout_ms)
                                 : CALL(int (*)(void *, int), WaitEventTimeout)(raw, timeout_ms) != 0;
    if (got) read_event(raw, e);
    return got;
}
int hos_sdl_poll_event(HosSdlEvent *e) {
    _Alignas(8) uint8_t raw[128];
    const int got = version == 3 ? CALL(_Bool (*)(void *), PollEvent)(raw) : CALL(int (*)(void *), PollEvent)(raw) != 0;
    if (got) read_event(raw, e);
    return got;
}

/* ---- sound ---- */
typedef struct {
    void (*pull)(void *user, uint8_t *out, int len);
    void *user;
    int frame;   /* bytes a sample frame (all channels) */
} Pull;
static void pull3(void *p, void *stream, int want, int total) {   /* (SDL3: a stream asks for want more bytes) */
    (void)total;
    const Pull *s = (const Pull *)p;
    uint8_t buf[4096];
    /* whole sample frames at a time: SDL3 takes no part of one (4096 bytes is not whole 5.1 frames, 12 bytes each:
       every piece was refused and 5.1 played silence) */
    const int most = (int)sizeof buf / s->frame * s->frame;
    for (int n; want > 0; want -= n) {
        n = want < most ? want : most;
        s->pull(s->user, buf, n);
        CALL(_Bool (*)(void *, const void *, int), PutAudioStreamData)(stream, buf, n);
    }
}
static void pull2(void *p, uint8_t *out, int len) {   /* (SDL2: a device callback fills its buffer) */
    const Pull *s = (const Pull *)p;
    s->pull(s->user, out, len);
}
/* SDL3's format of the default device; SDL2's default audio info (2.24 on: the bundled 2.32 has it). Looked up here,
   not at load: an SDL without it still plays, in stereo. */
static int playback_chosen_channels(void);
int hos_sdl_audio_channels(void) {
    if (!hos_sdl_load() || !hos_sdl_init(HOS_SDL_AUDIO)) return 2;
    const int chosen = playback_chosen_channels();   /* ((Triforce) the Output device row's device, on Linux) */
    if (chosen > 0) return chosen;
    HMODULE m = load_one(version == 3 ? "SDL3.dll" : "SDL2.dll");   /* (the one loaded: the same handle back) */
    if (!m) return 2;
    int n = 0;
    if (version == 3) {
        void *get = (void *)GetProcAddress(m, "SDL_GetAudioDeviceFormat");
        struct { uint32_t format; int channels, freq; } spec = {0, 0, 0};
        int frames = 0;
        if (get && ((_Bool (*)(uint32_t, void *, int *))get)(0xFFFFFFFFu /* the default output */, &spec, &frames))
            n = spec.channels;
    } else {
        void *get = (void *)GetProcAddress(m, "SDL_GetDefaultAudioInfo"), *release = (void *)GetProcAddress(m, "SDL_free");
        struct {
            int freq;
            uint16_t format;
            uint8_t channels, silence;
            uint16_t samples, padding;
            uint32_t size;
            void *callback, *userdata;
        } spec;
        memset(&spec, 0, sizeof spec);
        char *name = NULL;
        if (get && ((int (*)(char **, void *, int))get)(&name, &spec, 0) == 0) n = spec.channels;
        if (name && release) ((void (*)(void *))release)(name);
    }
    return n > 0 ? n : 2;
}

/* ---- (Triforce) the playback devices by name, and a stream on one of them: the game's own sound on Linux (waveOut's SDL
   stand-in, host/posix/win32_posix.c: the default, or the Output device row's device), and host/rumble_renhdrum.c's (a
   DualSense's four-channel sound card on its cable, beside the game's own sound). SDL's physical ids and list positions
   are not lasting: each device is kept by its driver and name ("sdl:<driver>:<name>"), with a token that keeps its
   meaning for the whole run, even when the list is read again while a stream opens. A device named twice is left out
   (SDL2 opens a name's first). Listing them opens no stream. A renamed device is one gone ---- */
typedef struct PlaybackEndpoint {
    struct PlaybackEndpoint *next;
    char id[HOS_OUTPUT_ID_CAP], name[HOS_OUTPUT_NAME_CAP];
    unsigned token;
    uint32_t physical;
    int present;
    int channels;   /* (what the device plays, 0 when SDL cannot say; host/rumble_renhdrum.c looks for four) */
} PlaybackEndpoint;
static PlaybackEndpoint *playback_endpoints;
static unsigned playback_next;
static int playback_loaded, playback_initialized;
static SRWLOCK playback_lock = SRWLOCK_INIT;
static struct {
    void *Devices, *Name, *Driver, *Free, *Close, *Destroy, *Format, *Status;
} playback;

static int playback_ready(void) {   /* playback_lock held */
    if (playback_loaded) return 1;
    if (!hos_sdl_load()) return 0;
    if (!playback_initialized) {
        if (!hos_sdl_init(HOS_SDL_AUDIO)) return 0;
        playback_initialized = 1;
    }
    HMODULE m = load_one(version == 3 ? "SDL3.dll" : "SDL2.dll");   /* (the one loaded: the same handle back) */
    if (!m) return 0;
#define PLAY_GET(field, symbol) (*(FARPROC *)&playback.field = GetProcAddress(m, symbol))
    PLAY_GET(Devices, version == 3 ? "SDL_GetAudioPlaybackDevices" : "SDL_GetNumAudioDevices");
    PLAY_GET(Name, "SDL_GetAudioDeviceName");
    PLAY_GET(Driver, "SDL_GetCurrentAudioDriver");
    PLAY_GET(Free, "SDL_free");
    PLAY_GET(Close, "SDL_CloseAudioDevice");
    PLAY_GET(Destroy, "SDL_DestroyAudioStream");
    PLAY_GET(Format, version == 3 ? "SDL_GetAudioDeviceFormat" : "SDL_GetAudioDeviceSpec");
    PLAY_GET(Status, "SDL_GetAudioDeviceStatus");
#undef PLAY_GET
    playback_loaded = playback.Devices && playback.Name && playback.Driver && playback.Free &&
                      (version == 3 ? playback.Destroy != NULL : playback.Close != NULL);
    return playback_loaded;
}
static const char *playback_name(uint32_t physical) {
    return version == 3 ? ((const char *(*)(uint32_t))playback.Name)(physical)
                        : ((const char *(*)(int, int))playback.Name)((int)physical, 0);
}
static int playback_refresh(void) {   /* playback_lock held */
    for (PlaybackEndpoint *p = playback_endpoints; p; p = p->next) p->present = 0;
    if (!playback_ready()) return 0;
    const char *driver = ((const char *(*)(void))playback.Driver)();
    if (!driver) return 0;
    int total = 0, count = 0;
    uint32_t *all = NULL;
    if (version == 3) all = ((uint32_t *(*)(int *))playback.Devices)(&total);
    else total = ((int (*)(int))playback.Devices)(0);
    for (int i = 0; i < total && (version == 2 || all); i++) {
        const uint32_t physical = version == 3 ? all[i] : (uint32_t)i;
        const char *name = playback_name(physical);
        char id[HOS_OUTPUT_ID_CAP], valid[HOS_OUTPUT_ID_CAP];
        if (!name || !*name || strlen(name) >= HOS_OUTPUT_NAME_CAP) continue;
        int n = snprintf(id, sizeof id, "sdl:%s:%s", driver, name);
        if (n < 0 || (size_t)n >= sizeof id || !audio_output_copy_id(valid, sizeof valid, id)) continue;
        int duplicates = 0;
        for (int j = 0; j < total; j++) {
            const char *other = playback_name(version == 3 ? all[j] : (uint32_t)j);
            if (other && !strcmp(name, other)) duplicates++;
        }
        if (duplicates != 1) continue;   /* (opening SDL2 by this name would take the first) */
        PlaybackEndpoint *p;
        for (p = playback_endpoints; p && strcmp(p->id, id); p = p->next) {}
        if (!p) {
            if (playback_next >= INT_MAX) continue;
            p = (PlaybackEndpoint *)calloc(1, sizeof *p);
            if (!p) continue;
            strcpy(p->id, id), strcpy(p->name, name);
            p->token = playback_next++;
            p->next = playback_endpoints, playback_endpoints = p;
        }
        p->physical = physical, p->present = 1;
        p->channels = 0;
        if (playback.Format) {
            struct { int a, b, c, d, e, g, h, i; } spec;   /* (SDL3's {format, channels, freq}, SDL2's SDL_AudioSpec) */
            int frames = 0;
            memset(&spec, 0, sizeof spec);
            if (version == 3 && ((_Bool (*)(uint32_t, void *, int *))playback.Format)(physical, &spec, &frames))
                p->channels = spec.b;
            else if (version == 2 && ((int (*)(int, int, void *))playback.Format)((int)physical, 0, &spec) == 0)
                p->channels = ((const uint8_t *)&spec)[6];   /* (int freq, Uint16 format, Uint8 channels) */
        }
        count++;
    }
    if (all) ((void (*)(void *))playback.Free)(all);
    return count;
}
int hos_sdl_output_count(void) {
    AcquireSRWLockExclusive(&playback_lock);
    int count = playback_refresh();
    ReleaseSRWLockExclusive(&playback_lock);
    return count;
}
int hos_sdl_output_info(int index, char *id, int id_capacity, char *name, int name_capacity) {
    if (index < 0 || !id || !name || id_capacity <= 0 || name_capacity <= 0) return 0;
    int ok = 0;
    AcquireSRWLockShared(&playback_lock);
    for (PlaybackEndpoint *p = playback_endpoints; p; p = p->next)
        if (p->present && index-- == 0) {
            if (strlen(p->name) < (size_t)name_capacity && audio_output_copy_id(id, (size_t)id_capacity, p->id)) {
                strcpy(name, p->name);
                ok = 1;
            }
            break;
        }
    ReleaseSRWLockShared(&playback_lock);
    return ok;
}
int hos_sdl_output_channels(int index) {
    int channels = 0;
    AcquireSRWLockShared(&playback_lock);
    for (PlaybackEndpoint *p = playback_endpoints; p; p = p->next)
        if (p->present && index-- == 0) {
            channels = p->channels;
            break;
        }
    ReleaseSRWLockShared(&playback_lock);
    return channels;
}
int hos_sdl_output_resolve(const char *id) {
    int token = -1;
    if (!id || !*id) return -1;
    AcquireSRWLockExclusive(&playback_lock);
    playback_refresh();
    for (PlaybackEndpoint *p = playback_endpoints; p; p = p->next)
        if (p->present && !strcmp(p->id, id)) {
            token = (int)p->token;
            break;
        }
    ReleaseSRWLockExclusive(&playback_lock);
    return token;
}
typedef struct {
    Pull base;   /* (first: pull3 and pull2 read it) */
    void *stream;
    uint32_t device;
    unsigned token;
    uint32_t physical;
    uint64_t checked;
    int alive;
} DevicePull;
static SRWLOCK audio_open_lock = SRWLOCK_INIT;   /* (one stream opens at a time: the sample frames' hint is the process's) */
void *hos_sdl_audio_open_device(unsigned device, int freq, int channels, int s16, int frames,
                                void (*pull)(void *user, uint8_t *out, int len), void *user) {
    uint32_t physical = 0xFFFFFFFFu;
    const char *name = NULL;
    AcquireSRWLockExclusive(&playback_lock);
    int ready = playback_ready();
    if (ready && device != UINT_MAX) {
        playback_refresh();
        ready = 0;
        for (PlaybackEndpoint *p = playback_endpoints; p; p = p->next)
            if (p->token == device && p->present) {
                physical = p->physical, name = p->name;   /* (kept for the run: the list never frees one) */
                ready = 1;
                break;
            }
    }
    ReleaseSRWLockExclusive(&playback_lock);
    if (!ready) return NULL;
    const uint16_t format = s16 ? 0x8010 /* S16LE */ : 0x8120 /* F32LE */;   /* (both's numbers) */
    const char *env_samples = getenv("SDL_AUDIO_DEVICE_SAMPLE_FRAMES");
    DevicePull *p = (DevicePull *)calloc(1, sizeof *p);
    if (!p) return NULL;
    p->base.pull = pull, p->base.user = user, p->base.frame = channels * (s16 ? 2 : 4);
    p->token = device, p->physical = physical, p->alive = 1;
    if (version == 3) {
        const struct { uint32_t format; int channels, freq; } spec = {format, channels, freq};
        /* (frames: SDL3's device buffer for this stream alone, 0 its default here, 480; SDL_AUDIO_DEVICE_SAMPLE_FRAMES over
           it. The hint is set for the open and taken away after, so the game's own output keeps what it asked for) */
        char samples[16];
        snprintf(samples, sizeof samples, "%d", frames > 0 ? frames : 480);
        AcquireSRWLockExclusive(&audio_open_lock);
        if (!env_samples) hos_sdl_hint("SDL_AUDIO_DEVICE_SAMPLE_FRAMES", samples);
        p->stream = CALL(void *(*)(uint32_t, const void *, void (*)(void *, void *, int, int), void *), OpenAudioDeviceStream)(
            physical, &spec, pull3, &p->base);
        if (!env_samples) hos_sdl_hint("SDL_AUDIO_DEVICE_SAMPLE_FRAMES", NULL);
        ReleaseSRWLockExclusive(&audio_open_lock);
        if (p->stream && CALL(_Bool (*)(void *), ResumeAudioStreamDevice)(p->stream)) return p;
        if (p->stream) ((void (*)(void *))playback.Destroy)(p->stream);
        free(p);
        return NULL;
    }
    struct {
        int freq;
        uint16_t format;
        uint8_t channels, silence;
        uint16_t samples, padding;
        uint32_t size;
        void (*callback)(void *, uint8_t *, int);
        void *userdata;
    } want, have;
    memset(&want, 0, sizeof want);
    want.freq = freq, want.format = format, want.channels = (uint8_t)channels;
    want.samples = (uint16_t)(env_samples && atoi(env_samples) > 0 ? atoi(env_samples) : frames > 0 ? frames : 512);   /* (SDL2: a power of two) */
    want.callback = pull2, want.userdata = &p->base;
    const uint32_t dev = CALL(uint32_t (*)(const char *, int, const void *, void *, int), OpenAudioDevice)(name, 0, &want, &have, 0);
    if (!dev) {
        free(p);
        return NULL;
    }
    CALL(void (*)(uint32_t, int), PauseAudioDevice)(dev, 0);
    p->device = dev;
    return p;
}
/* ((Triforce) the channels of the Output device row's device (host/audio_output_devices.c) on Linux, where the game's own
   sound plays on it through waveOut's SDL stand-in (host/posix/win32_posix.c); 0 for the default, an unknown one, one not
   connected, HOS_AUDIO_DEVICE's run and Windows (there nn_audio.c asks the device itself) */
static int playback_chosen_channels(void) {
#ifdef _WIN32
    return 0;
#else
    char wanted[HOS_OUTPUT_ID_CAP] = {0};
    unsigned generation = 0;
    const char *forced = getenv("HOS_AUDIO_DEVICE");
    if (forced && *forced) return 0;
    hos_audio_output_preference(wanted, sizeof wanted, &generation);
    if (!*wanted) return 0;
    int channels = 0;
    AcquireSRWLockExclusive(&playback_lock);
    if (playback_ready()) {
        playback_refresh();
        for (PlaybackEndpoint *p = playback_endpoints; p; p = p->next)
            if (p->present && !strcmp(p->id, wanted)) { channels = p->channels; break; }
    }
    ReleaseSRWLockExclusive(&playback_lock);
    return channels;
#endif
}
void hos_sdl_audio_close(void *audio) {
    DevicePull *p = (DevicePull *)audio;
    if (!p) return;
    /* (both wait for a callback under way: never called with a lock that callback takes) */
    if (p->stream) ((void (*)(void *))playback.Destroy)(p->stream);
    else ((void (*)(uint32_t))playback.Close)(p->device);
    free(p);
}
int hos_sdl_audio_alive(void *audio) {   /* (looked at once a second at most: the list is read again then) */
    DevicePull *p = (DevicePull *)audio;
    if (!p) return 0;
    const uint64_t now = (uint64_t)GetTickCount64();
    if (now - p->checked < 1000) return p->alive;
    p->checked = now;
    if (p->token != UINT_MAX) {
        AcquireSRWLockExclusive(&playback_lock);
        playback_refresh();
        p->alive = 0;
        for (PlaybackEndpoint *e = playback_endpoints; e; e = e->next)
            if (e->token == p->token && e->present && (version == 2 || e->physical == p->physical)) {
                p->alive = 1;
                break;
            }
        ReleaseSRWLockExclusive(&playback_lock);
    }
    if (version == 2 && playback.Status && ((int (*)(uint32_t))playback.Status)(p->device) == 0) p->alive = 0;   /* (SDL_AUDIO_STOPPED) */
    return p->alive;
}

/* ---- (hookshot) microphones: SDL3's recording devices, or SDL2's capture devices (the Linux AppImage carries SDL2): a
   stream each opened, in the format asked for, read as the game asks ---- */
static struct {
    void *GetDevices, *DeviceName, *Available, *GetData, *Clear, *Destroy;   /* (SDL3) */
    void *NumDevices, *DeviceName2, *CloseDevice, *LockDevice, *UnlockDevice;   /* (SDL2) */
    int tried, ok;
} rec;
#define REC_GET(field, name) (*(FARPROC *)&rec.field = GetProcAddress(m, name))
static int rec_ready(void) {
    if (!hos_sdl_load()) return 0;
    if (!rec.tried) {
        rec.tried = 1;
        HMODULE m = load_one(version == 3 ? "SDL3.dll" : "SDL2.dll");   /* (the one loaded: the same handle back) */
        if (m && version == 3) {
            REC_GET(GetDevices, "SDL_GetAudioRecordingDevices"), REC_GET(DeviceName, "SDL_GetAudioDeviceName");
            REC_GET(Available, "SDL_GetAudioStreamAvailable"), REC_GET(GetData, "SDL_GetAudioStreamData");
            REC_GET(Clear, "SDL_ClearAudioStream"), REC_GET(Destroy, "SDL_DestroyAudioStream");
            rec.ok = rec.GetDevices && rec.DeviceName && rec.Available && rec.GetData && rec.Clear && rec.Destroy;
        } else if (m) {
            REC_GET(NumDevices, "SDL_GetNumAudioDevices"), REC_GET(DeviceName2, "SDL_GetAudioDeviceName");
            REC_GET(CloseDevice, "SDL_CloseAudioDevice"), REC_GET(LockDevice, "SDL_LockAudioDevice");
            REC_GET(UnlockDevice, "SDL_UnlockAudioDevice");
            rec.ok = rec.NumDevices && rec.DeviceName2 && rec.CloseDevice && rec.LockDevice && rec.UnlockDevice;
        }
        if (!rec.ok) hos_log("sdl: no recording functions: no microphone");
    }
    return rec.ok && hos_sdl_init(HOS_SDL_AUDIO);
}
#undef REC_GET
/* SDL2: the capture callback fills a ring of about a second, the oldest dropped when full; read under the device's lock */
typedef struct {
    uint32_t dev;
    uint8_t *ring;
    int cap, start, len;
} Mic2;
static void mic2_push(void *user, uint8_t *in, int n) {   /* (SDL2's audio thread, the device locked) */
    Mic2 *m = (Mic2 *)user;
    if (n > m->cap) in += n - m->cap, n = m->cap;
    const int drop = m->len + n - m->cap;
    if (drop > 0) m->start = (m->start + drop) % m->cap, m->len -= drop;
    const int at = (m->start + m->len) % m->cap, first = n < m->cap - at ? n : m->cap - at;
    memcpy(m->ring + at, in, (size_t)first);
    memcpy(m->ring, in + first, (size_t)(n - first));
    m->len += n;
}
static void mic2_lock(Mic2 *m, int on) { ((void (*)(uint32_t))(on ? rec.LockDevice : rec.UnlockDevice))(m->dev); }

int hos_sdl_mic_list(uint32_t *ids, char (*names)[128], int max) {
    if (!rec_ready()) return 0;
    int n = 0;
    if (version == 2) {   /* (SDL2 names them by index: the id is the index + 1, 0 the default) */
        const int count = ((int (*)(int))rec.NumDevices)(1);
        for (int i = 0; i < count && n < max; i++, n++) {
            const char *name = ((const char *(*)(int, int))rec.DeviceName2)(i, 1);
            ids[n] = (uint32_t)i + 1;
            snprintf(names[n], 128, "%s", name ? name : "Microphone");
        }
        return n;
    }
    int count = 0;
    uint32_t *all = ((uint32_t *(*)(int *))rec.GetDevices)(&count);
    for (int i = 0; all && i < count && n < max; i++, n++) {
        const char *name = ((const char *(*)(uint32_t))rec.DeviceName)(all[i]);
        ids[n] = all[i];
        snprintf(names[n], 128, "%s", name ? name : "Microphone");
    }
    if (all) CALL(void (*)(void *), Free)(all);
    return n;
}
void *hos_sdl_mic_open(uint32_t id, int freq, int channels, uint16_t sdl_format) {
    if (!rec_ready()) return NULL;
    if (version == 2) {
        const int bytes = (sdl_format & 0xFF) / 8 * channels;
        Mic2 *m = (Mic2 *)calloc(1, sizeof *m);
        if (!m || !(m->ring = (uint8_t *)malloc((size_t)freq * bytes))) {
            free(m);
            return NULL;
        }
        m->cap = freq * bytes;
        struct {
            int freq;
            uint16_t format;
            uint8_t channels, silence;
            uint16_t samples, padding;
            uint32_t size;
            void (*callback)(void *, uint8_t *, int);
            void *userdata;
        } want, have;
        memset(&want, 0, sizeof want);
        want.freq = freq, want.format = sdl_format, want.channels = (uint8_t)channels, want.samples = 512;
        want.callback = mic2_push, want.userdata = m;
        /* (no changes allowed: SDL converts the device's sound to this. SDL2's id is a place in its list, so the caller takes
           it from a list made just before (host/nn_audio_in.c find_device). SDL2 opens a device by its name: of two with one
           name it takes the first, whichever was chosen; telling them apart is SDL3's) */
        const char *name = id ? ((const char *(*)(int, int))rec.DeviceName2)((int)id - 1, 1) : NULL;
        m->dev = CALL(uint32_t (*)(const char *, int, const void *, void *, int), OpenAudioDevice)(name, 1, &want, &have, 0);
        if (!m->dev) {   /* (the caller says so, once: hos_sdl_error) */
            free(m->ring), free(m);
            return NULL;
        }
        CALL(void (*)(uint32_t, int), PauseAudioDevice)(m->dev, 0);
        return m;
    }
    const struct { uint32_t format; int channels, freq; } spec = {sdl_format, channels, freq};
    void *s = CALL(void *(*)(uint32_t, const void *, void *, void *), OpenAudioDeviceStream)(
        id ? id : 0xFFFFFFFEu /* SDL_AUDIO_DEVICE_DEFAULT_RECORDING */, &spec, NULL, NULL);
    if (s && !CALL(_Bool (*)(void *), ResumeAudioStreamDevice)(s)) {   /* (one that does not start did not open) */
        ((void (*)(void *))rec.Destroy)(s);
        s = NULL;
    }
    return s;   /* (none: the caller says so, once: hos_sdl_error) */
}
int hos_sdl_mic_available(void *mic) {
    if (!mic || !rec.ok) return 0;
    if (version == 2) {
        Mic2 *m = (Mic2 *)mic;
        mic2_lock(m, 1);
        const int n = m->len;
        mic2_lock(m, 0);
        return n;
    }
    return ((int (*)(void *))rec.Available)(mic);
}
int hos_sdl_mic_read(void *mic, void *dst, int bytes) {
    if (!mic || !rec.ok || bytes <= 0) return 0;
    if (version == 2) {
        Mic2 *m = (Mic2 *)mic;
        mic2_lock(m, 1);
        const int n = bytes < m->len ? bytes : m->len, first = n < m->cap - m->start ? n : m->cap - m->start;
        memcpy(dst, m->ring + m->start, (size_t)first);
        memcpy((uint8_t *)dst + first, m->ring, (size_t)(n - first));
        m->start = (m->start + n) % m->cap, m->len -= n;
        mic2_lock(m, 0);
        return n;
    }
    const int n = ((int (*)(void *, void *, int))rec.GetData)(mic, dst, bytes);
    return n > 0 ? n : 0;
}
void hos_sdl_mic_clear(void *mic) {
    if (!mic || !rec.ok) return;
    if (version == 2) {
        Mic2 *m = (Mic2 *)mic;
        mic2_lock(m, 1);
        m->start = m->len = 0;
        mic2_lock(m, 0);
        return;
    }
    ((_Bool (*)(void *))rec.Clear)(mic);
}
void hos_sdl_mic_close(void *mic) {
    if (!mic || !rec.ok) return;
    if (version == 2) {
        Mic2 *m = (Mic2 *)mic;
        ((void (*)(uint32_t))rec.CloseDevice)(m->dev);   /* (the callback has stopped when this returns) */
        free(m->ring), free(m);
        return;
    }
    ((void (*)(void *))rec.Destroy)(mic);
}

/* ---- controllers ---- */
/* ((Triforce) 11-20) whether the controller at SDL's place `what` (SDL3: its id; SDL2: its device index) is an instrument or a
   dance mat, left out of the game's input (pad_kind.h); each one said once (by its id) */
static int pad_left_out(int what, int32_t id) {
    static int all = -1;
    if (all < 0) all = getenv("HOS_SDL_ALL_PADS") && atoi(getenv("HOS_SDL_ALL_PADS")) != 0;
    if (all) return 0;
    const int type = !f.JoyTypeOf ? 0 : version == 3 ? CALL(int (*)(uint32_t), JoyTypeOf)((uint32_t)what) : CALL(int (*)(int), JoyTypeOf)(what);
    const char *name = !f.PadNameOf ? NULL : version == 3 ? CALL(const char *(*)(uint32_t), PadNameOf)((uint32_t)what)
                                                          : CALL(const char *(*)(int), PadNameOf)(what);
    const char *why = pad_kind_left_out(type, name);
    if (!why) return 0;
    static int32_t said[8];
    static int nsaid;
    int known = 0;
    for (int i = 0; i < nsaid; i++) known |= said[i] == id;
    if (!known) {
        if (nsaid < 8) said[nsaid++] = id;
        hos_log("hid: controller \"%s\" left out: %s, not a gamepad (its whammy, tilt or pads would read as held buttons for "
                "player 1; HOS_SDL_ALL_PADS=1 keeps it)", name ? name : "?", why);
    }
    return 1;
}
int hos_sdl_pads_list(int32_t *ids, int *opens, int max) {   /* (SDL3 opens by id; SDL2 by device index) */
    int n = 0;
    if (version == 3) {
        int count = 0;
        uint32_t *got = CALL(uint32_t *(*)(int *), GetGamepads)(&count);
        for (int i = 0; got && i < count && n < max; i++)
            if (!pad_left_out((int)got[i], (int32_t)got[i])) ids[n] = (int32_t)got[i], opens[n] = (int)got[i], n++;
        if (got) CALL(void (*)(void *), Free)(got);
        return n;
    }
    const int nj = CALL(int (*)(void), NumJoysticks)();
    for (int j = 0; j < nj && n < max; j++) {
        if (!CALL(int (*)(int), IsGameController)(j)) continue;
        const int32_t id = CALL(int32_t (*)(int), DeviceInstanceID)(j);
        if (!pad_left_out(j, id)) ids[n] = id, opens[n] = j, n++;
    }
    return n;
}
void *hos_sdl_pad_open(int what) {
    return version == 3 ? CALL(void *(*)(uint32_t), PadOpen)((uint32_t)what) : CALL(void *(*)(int), PadOpen)(what);
}
static void pad_headphones_forget(void *pad);
void hos_sdl_pad_close(void *pad) {
    pad_headphones_forget(pad);   /* ((Triforce) its jack's reader goes with it: SDL may hand the address to the next pad) */
    CALL(void (*)(void *), PadClose)(pad);
}
int hos_sdl_pad_connected(void *pad) {
    return version == 3 ? CALL(_Bool (*)(void *), PadConnected)(pad) : CALL(int (*)(void *), PadConnected)(pad) != 0;
}
void hos_sdl_pads_update(void) { CALL(void (*)(void), PadsUpdate)(); }
int hos_sdl_pad_button(void *pad, int button) {
    return version == 3 ? CALL(_Bool (*)(void *, int), PadButton)(pad, button)
                        : CALL(uint8_t (*)(void *, int), PadButton)(pad, button) != 0;
}
int16_t hos_sdl_pad_axis(void *pad, int axis) { return CALL(int16_t (*)(void *, int), PadAxis)(pad, axis); }
const char *hos_sdl_pad_name(void *pad) {
    const char *n = CALL(const char *(*)(void *), PadName)(pad);
    return n ? n : "?";
}
/* (Triforce) A controller's connection in the log, with what a bug report about its buttons needs: the hardware GUID SDL
   has for it (SDL_GUID / SDL_JoystickGUID, the same 16 bytes in SDL2 and SDL3: the maker, the product and the driver, not
   a serial number) and the mapping in use. The mapping may be SDL's database's, the driver's or the user's own: SDL does
   not say which, and none is not a sign that it chose a default. Its string is SDL's allocator's */
typedef struct { uint8_t data[16]; } HosSdlGuid;
void hos_sdl_pad_log_connection(void *pad, int motion) {
    char guid[33] = "unavailable";
    if (f.GetJoystick && f.JoystickGUID) {
        void *joystick = CALL(void *(*)(void *), GetJoystick)(pad);
        if (joystick) {
            const HosSdlGuid id = CALL(HosSdlGuid (*)(void *), JoystickGUID)(joystick);
            static const char hex[] = "0123456789abcdef";
            unsigned any = 0;
            for (int i = 0; i < 16; i++) {
                guid[2 * i] = hex[id.data[i] >> 4], guid[2 * i + 1] = hex[id.data[i] & 15];
                any |= id.data[i];
            }
            guid[32] = 0;
            if (!any) strcpy(guid, "unknown");
        }
    }
    const int can_map = f.PadMapping && f.Free;
    char *mapping = can_map ? CALL(char *(*)(void *), PadMapping)(pad) : NULL;
    const char *status = !can_map ? "unavailable" : mapping ? "available" : "none";
    const char *name = mapping ? strchr(mapping, ',') : NULL;
    int name_len = 1;
    if (name) {
        name++;
        for (name_len = 0; name_len < 128 && name[name_len] && name[name_len] != ','; name_len++) {}
    } else name = "?";
    int mapping_len = 0;
    if (mapping)
        while (mapping_len < 1024 && mapping[mapping_len]) mapping_len++;
    hos_log("hid: controller \"%.128s\" connected (SDL)%s; guid=%s; mapping=%s; mapping-name=\"%.*s\"", hos_sdl_pad_name(pad),
            motion ? ", with a gyroscope" : "", guid, status, name_len, name);
    /* (a log line holds 1024 bytes: the mapping whole, in parts of 512 with their number) */
    for (int at = 0; at < mapping_len; at += 512) {
        const int n = mapping_len - at < 512 ? mapping_len - at : 512;
        hos_log("hid: guid=%s; mapping-string[%d/%d]=\"%.*s\"%s", guid, at / 512 + 1, (mapping_len + 511) / 512, n, mapping + at,
                at + n == mapping_len && mapping[mapping_len] ? " (cut)" : "");
    }
    if (mapping) CALL(void (*)(void *), Free)(mapping);
}
int32_t hos_sdl_pad_id(void *pad) {
    return version == 3 ? (int32_t)CALL(uint32_t (*)(void *), GetGamepadID)(pad)
                        : CALL(int32_t (*)(void *), JoystickInstanceID)(CALL(void *(*)(void *), GetJoystick)(pad));
}
void hos_sdl_pad_rumble(void *pad, uint16_t low, uint16_t high, uint32_t ms) {
    if (version == 3) CALL(_Bool (*)(void *, uint16_t, uint16_t, uint32_t), PadRumble)(pad, low, high, ms);
    else CALL(int (*)(void *, uint16_t, uint16_t, uint32_t), PadRumble)(pad, low, high, ms);
}
int hos_sdl_pad_has_trigger_rumble(void) { return f.PadRumbleTriggers != NULL; }
int hos_sdl_pad_rumble_triggers(void *pad, uint16_t left, uint16_t right, uint32_t ms) {
    if (!f.PadRumbleTriggers) return 0;
    if (version == 3) return CALL(_Bool (*)(void *, uint16_t, uint16_t, uint32_t), PadRumbleTriggers)(pad, left, right, ms);
    return CALL(int (*)(void *, uint16_t, uint16_t, uint32_t), PadRumbleTriggers)(pad, left, right, ms) == 0;
}
int hos_sdl_pad_type(void *pad) { return f.PadType ? CALL(int (*)(void *), PadType)(pad) : 0; }
int hos_sdl_pad_has_effect(void) { return f.PadEffect != NULL; }
int hos_sdl_pad_effect(void *pad, const void *data, int size) {
    if (!f.PadEffect) return 0;
    if (version == 3) return CALL(_Bool (*)(void *, const void *, int), PadEffect)(pad, data, size);
    return CALL(int (*)(void *, const void *, int), PadEffect)(pad, data, size) == 0;
}
/* (motion) type: HOS_SDL_SENSOR_ACCEL or _GYRO, the same numbers in both */
int hos_sdl_pad_has_sensor(void *pad, int type) {
    if (!f.PadHasSensor || !f.PadSensorEnable || !f.PadSensorData) return 0;
    return version == 3 ? CALL(_Bool (*)(void *, int), PadHasSensor)(pad, type)
                        : CALL(int (*)(void *, int), PadHasSensor)(pad, type) != 0;
}
int hos_sdl_pad_sensor_enable(void *pad, int type, int on) {
    if (!f.PadSensorEnable) return 0;
    return version == 3 ? CALL(_Bool (*)(void *, int, _Bool), PadSensorEnable)(pad, type, on != 0)
                        : CALL(int (*)(void *, int, int), PadSensorEnable)(pad, type, on != 0) == 0;
}
int hos_sdl_pad_sensor(void *pad, int type, float *data, int n) {
    if (!f.PadSensorData) return 0;
    return version == 3 ? CALL(_Bool (*)(void *, int, float *, int), PadSensorData)(pad, type, data, n)
                        : CALL(int (*)(void *, int, float *, int), PadSensorData)(pad, type, data, n) == 0;
}
/* ((Triforce) 11-24: Steam's stand-in pads, host/steam_pads.h) whether the SDL tells them apart; a pad's USB vendor and
   product (0 unknown); its Steam Input handle, not 0 for a Steam stand-in pad */
int hos_sdl_knows_steam_pads(void) { return f.PadVendor && f.PadSteamHandle && f.SetHintPriority; }
uint16_t hos_sdl_pad_vendor(void *pad) { return f.PadVendor ? CALL(uint16_t (*)(void *), PadVendor)(pad) : 0; }
uint16_t hos_sdl_pad_product(void *pad) { return f.PadProduct ? CALL(uint16_t (*)(void *), PadProduct)(pad) : 0; }
uint64_t hos_sdl_pad_steam_handle(void *pad) {
    return f.PadSteamHandle ? CALL(uint64_t (*)(void *), PadSteamHandle)(pad) : 0;
}
/* ---- (Triforce) vibration (host/pad_sdl.c, host/rumble_renhdrum.c): a pad's transport, its device path and a second
   handle on its HID device, written beside SDL's own (a DualSense's Bluetooth haptics, a Steam Controller's grips). Looked
   up on first use, not with the rest at load: an SDL without them still plays, and those pads keep their motors. The
   path only opens the device; it is never logged ---- */
static struct {
    int looked;
    void *Wireless, *Path, *HidOpenPath, *HidWrite, *HidClose, *HidReadTimeout;
} vib_calls;
static void vib_calls_look(void) {
    if (vib_calls.looked) return;
    vib_calls.looked = 1;
    HMODULE m = version ? load_one(version == 3 ? "SDL3.dll" : "SDL2.dll") : NULL;   /* (the one loaded: the same handle) */
    if (!m) return;
    /* (a pad's transport: SDL3 3.2 on. SDL2 cannot say, and a DualSense is then placed by its sound card) */
    if (version == 3) *(FARPROC *)&vib_calls.Wireless = GetProcAddress(m, "SDL_GetJoystickConnectionState");
    *(FARPROC *)&vib_calls.Path = GetProcAddress(m, version == 3 ? "SDL_GetGamepadPath" : "SDL_GameControllerPath");
    *(FARPROC *)&vib_calls.HidOpenPath = GetProcAddress(m, "SDL_hid_open_path");   /* (SDL2 2.0.18 on, every SDL3) */
    *(FARPROC *)&vib_calls.HidWrite = GetProcAddress(m, "SDL_hid_write");
    *(FARPROC *)&vib_calls.HidClose = GetProcAddress(m, "SDL_hid_close");
    *(FARPROC *)&vib_calls.HidReadTimeout = GetProcAddress(m, "SDL_hid_read_timeout");   /* (a DualSense's jack, below) */
}
/* 1 wireless, 0 a cable, -1 when the SDL cannot say */
int hos_sdl_pad_wireless(void *pad) {
    vib_calls_look();
    if (!vib_calls.Wireless || !f.GetJoystick || !pad) return -1;
    void *joystick = CALL(void *(*)(void *), GetJoystick)(pad);
    if (!joystick) return -1;
    /* SDL_JoystickConnectionState: -1 invalid, 0 unknown, 1 wired, 2 wireless */
    const int state = ((int (*)(void *))vib_calls.Wireless)(joystick);
    if (state < 1) return -1;
    return state == 2 ? 1 : 0;
}
const char *hos_sdl_pad_path(void *pad) {
    vib_calls_look();
    const char *p = vib_calls.Path && pad ? ((const char *(*)(void *))vib_calls.Path)(pad) : NULL;
    return p ? p : "";
}
int hos_sdl_hid_can(void) {
    vib_calls_look();
    return vib_calls.HidOpenPath && vib_calls.HidWrite && vib_calls.HidClose;
}
void *hos_sdl_hid_open(const char *path) {
    if (!hos_sdl_hid_can() || !path || !*path) return NULL;
    if (version == 3) return ((void *(*)(const char *))vib_calls.HidOpenPath)(path);
    return ((void *(*)(const char *, int))vib_calls.HidOpenPath)(path, 0);   /* (SDL2's: not exclusive) */
}
int hos_sdl_hid_write(void *hid, const void *data, int size) {
    return hid && vib_calls.HidWrite ? ((int (*)(void *, const unsigned char *, size_t))vib_calls.HidWrite)(
                                           hid, (const unsigned char *)data, (size_t)size)
                                     : -1;
}
void hos_sdl_hid_close(void *hid) {
    if (hid && vib_calls.HidClose) ((int (*)(void *))vib_calls.HidClose)(hid);
}
/* ((Triforce) the controller speaker, host/pad_speaker.c) A DualSense's own four-channel sound card: the HID interface and
   the Windows audio endpoint matched by their device container. SDL gives only the endpoint's name, so that name must be
   the only one of its kind in both lists; never a guess when either is not known. Its token, or -1 (and always -1 off
   Windows: the speaker then never shares a stream, and the vibration plays as before) */
int hos_sdl_pad_audio_endpoint(void *pad) {
#ifdef _WIN32
    static const DEVPROPKEY container = {{0x8c7ed206, 0x3f8a, 0x4827, {0xb3, 0xab, 0xae, 0x9e, 0x1f, 0xae, 0xfc, 0x6c}}, 2};
    static const PROPERTYKEY label = {{0xa45c254e, 0xdf1c, 0x4efd, {0x80, 0x20, 0x67, 0xd1, 0x46, 0xa8, 0x50, 0xe0}}, 14};
    static const GUID clsid = {0xbcde0395, 0xe52f, 0x467c, {0x8e, 0x3d, 0xc4, 0x57, 0x92, 0x91, 0x69, 0x2e}};
    static const GUID iid = {0xa95664d2, 0x9614, 0x4f35, {0xa7, 0x46, 0xde, 0x8d, 0xb6, 0x36, 0x17, 0xe6}};
    const char *path = hos_sdl_pad_path(pad);
    WCHAR wide[1024];
    if (!*path || !MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, wide, 1024)) return -1;
    HDEVINFO set = SetupDiCreateDeviceInfoList(NULL, NULL);
    if (set == INVALID_HANDLE_VALUE) return -1;
    SP_DEVICE_INTERFACE_DATA iface = {.cbSize = sizeof iface};
    SP_DEVINFO_DATA dev = {.cbSize = sizeof dev};
    GUID pad_container;
    static const GUID no_container = {0};
    DEVPROPTYPE type = 0;
    union { SP_DEVICE_INTERFACE_DETAIL_DATA_W d; WCHAR room[2048]; } detail;
    detail.d.cbSize = sizeof detail.d;
    int ok = SetupDiOpenDeviceInterfaceW(set, wide, 0, &iface) &&
             SetupDiGetDeviceInterfaceDetailW(set, &iface, &detail.d, sizeof detail, NULL, &dev) &&
             SetupDiGetDevicePropertyW(set, &dev, &container, &type, (BYTE *)&pad_container, sizeof pad_container, NULL, 0) &&
             type == DEVPROP_TYPE_GUID && memcmp(&pad_container, &no_container, sizeof pad_container);
    SetupDiDestroyDeviceInfoList(set);
    if (!ok) return -1;
    HRESULT com = CoInitializeEx(NULL, COINIT_MULTITHREADED);
    IMMDeviceEnumerator *e = NULL;
    IMMDeviceCollection *list = NULL;
    int token = -1, matches = 0;
    char matched_name[HOS_OUTPUT_NAME_CAP] = "";
    if (SUCCEEDED(CoCreateInstance(&clsid, NULL, CLSCTX_ALL, &iid, (void **)&e)) && e &&
        SUCCEEDED(e->lpVtbl->EnumAudioEndpoints(e, eRender, DEVICE_STATE_ACTIVE, &list)) && list) {
        UINT count = 0;
        list->lpVtbl->GetCount(list, &count);
        for (UINT i = 0; i < count; i++) {
            IMMDevice *d = NULL;
            IPropertyStore *p = NULL;
            PROPVARIANT c, n;
            memset(&c, 0, sizeof c), memset(&n, 0, sizeof n);
            if (SUCCEEDED(list->lpVtbl->Item(list, i, &d)) && d &&
                SUCCEEDED(d->lpVtbl->OpenPropertyStore(d, STGM_READ, &p)) && p &&
                SUCCEEDED(p->lpVtbl->GetValue(p, (const PROPERTYKEY *)&container, &c)) && c.vt == VT_CLSID && c.puuid &&
                !memcmp(c.puuid, &pad_container, sizeof pad_container) &&
                SUCCEEDED(p->lpVtbl->GetValue(p, &label, &n)) && n.vt == VT_LPWSTR && n.pwszVal) {
                char name[HOS_OUTPUT_NAME_CAP];
                if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, n.pwszVal, -1, name, sizeof name, NULL, NULL)) {
                    const int total = hos_sdl_output_count();
                    for (int j = 0; j < total; j++) {
                        char id[HOS_OUTPUT_ID_CAP], sdl_name[HOS_OUTPUT_NAME_CAP];
                        if (hos_sdl_output_info(j, id, sizeof id, sdl_name, sizeof sdl_name) &&
                            !strcmp(name, sdl_name) && hos_sdl_output_channels(j) >= 4) {
                            token = hos_sdl_output_resolve(id);
                            if (token >= 0) matches++, strcpy(matched_name, name);
                        }
                    }
                }
            }
            PropVariantClear(&c), PropVariantClear(&n);
            if (p) p->lpVtbl->Release(p);
            if (d) d->lpVtbl->Release(d);
        }
        /* (an SDL name cannot tell two Windows endpoints with the same label apart) */
        int labels = 0;
        for (UINT i = 0; matches == 1 && i < count; i++) {
            IMMDevice *d = NULL;
            IPropertyStore *p = NULL;
            PROPVARIANT n;
            memset(&n, 0, sizeof n);
            if (SUCCEEDED(list->lpVtbl->Item(list, i, &d)) && d &&
                SUCCEEDED(d->lpVtbl->OpenPropertyStore(d, STGM_READ, &p)) && p &&
                SUCCEEDED(p->lpVtbl->GetValue(p, &label, &n)) && n.vt == VT_LPWSTR && n.pwszVal) {
                char name[HOS_OUTPUT_NAME_CAP];
                if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, n.pwszVal, -1, name, sizeof name, NULL, NULL) &&
                    !strcmp(name, matched_name))
                    labels++;
            }
            PropVariantClear(&n);
            if (p) p->lpVtbl->Release(p);
            if (d) d->lpVtbl->Release(d);
        }
        if (labels != 1) matches = 0;
    }
    if (list) list->lpVtbl->Release(list);
    if (e) e->lpVtbl->Release(e);
    if (SUCCEEDED(com)) CoUninitialize();
    return matches == 1 ? token : -1;
#else
    (void)pad;
    return -1;
#endif
}
/* ((Triforce) the controller speaker, once a second) Headphones in a DualSense's jack: 1 in, 0 out, -1 when it cannot be
   read (an SDL without its HID calls, a pad whose report says nothing). The pad's USB input report (0x01) carries it at
   byte 54, bit 0 (bit 1: a microphone): read on a second handle to the pad (hos_sdl_hid_open, as the vibration's
   Bluetooth reports are written), which Windows hands every report as it does SDL's own, emptied of the reports queued
   since the last second. Its path is never logged */
static void *hp_dev, *hp_pad;   /* (the reader's second handle, and the pad it reads: for that pad's open life only) */
static int hp_failed, hp_last = -2;
static void pad_headphones_forget(void *pad) {   /* (the pad closed: its handle closed, its status and failure forgotten) */
    if (!pad || pad != hp_pad) return;
    if (hp_dev) hos_sdl_hid_close(hp_dev);
    hp_dev = NULL, hp_pad = NULL, hp_failed = 0, hp_last = -2;
}
int hos_sdl_pad_headphones(void *pad) {
    vib_calls_look();
    if (!vib_calls.HidReadTimeout || !vib_calls.HidOpenPath || !vib_calls.HidClose || !pad) return -1;
    if (pad != hp_pad) {
        if (hp_dev) hos_sdl_hid_close(hp_dev);
        hp_dev = NULL, hp_pad = pad, hp_failed = 0, hp_last = -2;
    }
    if (!hp_dev) {
        if (hp_failed) return -1;
        hp_dev = hos_sdl_hid_open(hos_sdl_pad_path(pad));
        if (!hp_dev) {
            hp_failed = 1;
            hos_log("sdl: the DualSense's input report could not be read beside SDL's: its headphones are not seen");
            return -1;
        }
    }
    unsigned char report[80], seen[80];
    int got = 0;
    for (int i = 0; i < 256; i++) {   /* (up to a second of reports queued: the newest counts) */
        const int n = ((int (*)(void *, unsigned char *, size_t, int))vib_calls.HidReadTimeout)(hp_dev, report, sizeof report, 0);
        if (n < 0) {
            hos_sdl_hid_close(hp_dev);
            hp_dev = NULL;
            return -1;
        }
        if (n == 0) break;
        if (report[0] == 0x01 && n >= 55) memcpy(seen, report, sizeof seen), got = 1;
    }
    if (!got) return hp_last >= 0 ? hp_last : -1;
    const int now = seen[54] & 1;
    if (now != hp_last) hos_log("sdl: the DualSense's plug status 0x%02x", seen[54]);
    hp_last = now;
    return now;
}
#undef CALL
