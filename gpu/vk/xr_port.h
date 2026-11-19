// What VR's files (vk_xr.cpp) share: the log, the VR rows (vk_xr_cfg: the Insert
// menu's VR tab), the few platform calls, and the menu's place for the counter.
#pragma once

#include <chrono>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>

#include "vk_internal.h"
#include "vk_xr.h"

#ifndef _WIN32
#include <dlfcn.h>
#include <unistd.h>
#endif

#define rt_log(...) mkwvk::logf(__VA_ARGS__)

inline const char *cfg_value(const char *key) { return vk_xr_cfg(key); }
inline int cfg_int(const char *key) { return atoi(vk_xr_cfg(key)); }
inline int cfg_bool(const char *key) { return atoi(vk_xr_cfg(key)) != 0; }

enum { PLAT_PATH_MAX = 1024 };

inline uint64_t plat_now_ns() {
    return (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch())
        .count();
}
inline void plat_sleep_ms(int ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
// a thread of its own, detached (its name and flags are not used); 1 when it started
inline int plat_thread_spawn(void (*fn)(void *), void *arg, const char *, int) {
    try {
        std::thread(fn, arg).detach();
        return 1;
    } catch (...) {
        return 0;
    }
}
inline int plat_file_exists(const char *path) {
    FILE *f = fopen(path, "rb");
    if (f) fclose(f);
    return f != nullptr;
}
inline int plat_getenv(const char *name, char *out, size_t n) {
    const char *v = getenv(name);
    if (!v || !*v) return 0;
    snprintf(out, n, "%s", v);
    return 1;
}
inline void plat_setenv(const char *name, const char *value) {
#ifdef _WIN32
    _putenv_s(name, value);
#else
    setenv(name, value, 1);
#endif
}
inline void *plat_lib_open(const char *path) {
#ifdef _WIN32
    return (void *)LoadLibraryA(path);
#else
    return dlopen(path, RTLD_NOW | RTLD_LOCAL);
#endif
}
inline void *plat_lib_sym(void *lib, const char *name) {
#ifdef _WIN32
    return (void *)GetProcAddress((HMODULE)lib, name);
#else
    return dlsym(lib, name);
#endif
}
// the executable's own path (0 when not known)
inline int plat_exe_path(char *out, size_t n) {
#ifdef _WIN32
    const DWORD got = GetModuleFileNameA(nullptr, out, (DWORD)n);
    return got > 0 && got < n;
#else
    const ssize_t got = readlink("/proc/self/exe", out, n - 1);
    if (got <= 0) return 0;
    out[got] = 0;
    return 1;
#endif
}
inline char *plat_last_sep(char *path) {
    char *a = strrchr(path, '/'), *b = strrchr(path, '\\');
    return a > b ? a : b;
}

// the menu (vk_menu.cpp): open now, and the screen place of the counter's overlay (window pixels {x, y, w, h}; 0 when not
// shown)
namespace mkwvk {
bool menu_is_open();
}
int menu_perf_rect(int r[4]);
inline int menu_is_open() { return mkwvk::menu_is_open(); }
