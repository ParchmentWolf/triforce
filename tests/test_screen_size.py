"""The connected screens as the Windows host finds them (host/display.c hos_screens, hos_screen_size), for the Output
resolution: every monitor's size in pixels, its own name, and which one the game's window opens on.

The window is made at CW_USEDEFAULT, after the game has taken its output size. Windows names the monitor it was started
from in STARTUPINFO's hStdOutput when the shell started it from a taskbar or a jump list (and no standard handles are
passed there): that monitor then, else the main one. A monitor's name is its EDID's, through the display configuration;
one that has none (a laptop's panel) has an empty name. The functions themselves, cut out and run against stand-ins for
the Windows calls they make, so the check runs on every OS:

    python -I -B tests/test_screen_size.py [--cc gcc]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "host/hos_screens.h"

/* ---- stand-ins for what host/display.c takes from windows.h ---- */
typedef void *HANDLE, *HMONITOR, *HDC;
typedef unsigned long DWORD;
typedef long LONG;
typedef int BOOL;
typedef unsigned int UINT32, UINT;
typedef intptr_t LPARAM;
typedef uint16_t WCHAR;
typedef struct { LONG left, top, right, bottom; } RECT, *LPRECT;
typedef struct { DWORD cbSize; RECT rcMonitor, rcWork; DWORD dwFlags; } MONITORINFO;
typedef struct { DWORD cbSize; RECT rcMonitor, rcWork; DWORD dwFlags; char szDevice[32]; } MONITORINFOEXA;
typedef struct { DWORD cb; DWORD dwFlags; HANDLE hStdInput, hStdOutput, hStdError; } STARTUPINFOW;
typedef struct { uint32_t LowPart; int32_t HighPart; } LUID;
typedef struct { LUID adapterId; UINT32 id; } DISPLAYCONFIG_PATH_SOURCE_INFO, DISPLAYCONFIG_PATH_TARGET_INFO;
typedef struct { DISPLAYCONFIG_PATH_SOURCE_INFO sourceInfo; DISPLAYCONFIG_PATH_TARGET_INFO targetInfo; UINT32 flags; } DISPLAYCONFIG_PATH_INFO;
typedef struct { UINT32 infoType; } DISPLAYCONFIG_MODE_INFO;
typedef struct { int type; UINT32 size; LUID adapterId; UINT32 id; } DISPLAYCONFIG_DEVICE_INFO_HEADER;
typedef struct { DISPLAYCONFIG_DEVICE_INFO_HEADER header; WCHAR viewGdiDeviceName[32]; } DISPLAYCONFIG_SOURCE_DEVICE_NAME;
typedef struct {
    DISPLAYCONFIG_DEVICE_INFO_HEADER header;
    struct { UINT32 friendlyNameFromEdid : 1; } flags;
    WCHAR monitorFriendlyDeviceName[64];
} DISPLAYCONFIG_TARGET_DEVICE_NAME;
#define CALLBACK
#define TRUE 1
#define STARTF_USESTDHANDLES 0x100
#define MONITORINFOF_PRIMARY 1
#define SM_CXSCREEN 0
#define SM_CYSCREEN 1
#define ERROR_SUCCESS 0
#define QDC_ONLY_ACTIVE_PATHS 2
#define CP_UTF8 65001
enum { DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME = 1, DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME = 2 };

/* ---- the system: three monitors. The main one is second in the system's order; one has no name of its own ---- */
static const struct {
    RECT at;
    int primary;
    const char *device, *name;   /* (name NULL: none in its EDID) */
} monitors[3] = {
    {{-3440, 160, 0, 1600}, 0, "\\\\.\\DISPLAY2", "LG ULTRAGEAR"},
    {{0, 0, 3840, 1600}, 1, "\\\\.\\DISPLAY1", "38GN950"},
    {{3840, 0, 5760, 1200}, 0, "\\\\.\\DISPLAY3", NULL},
};
static HMONITOR handle(int i) { return (HMONITOR)(uintptr_t)(0x10001 + i * 2); }
static int monitor_of(HMONITOR m) {
    for (int i = 0; i < 3; i++)
        if (m == handle(i)) return i;
    return -1;
}
static STARTUPINFOW started;
static int no_configuration;   /* (1: the display configuration says nothing, as in a remote session) */
static void GetStartupInfoW(STARTUPINFOW *si) { *si = started; }
static BOOL GetMonitorInfoA(HMONITOR m, MONITORINFO *mi) {
    const int i = monitor_of(m);
    if (i < 0 || (mi->cbSize != sizeof(MONITORINFO) && mi->cbSize != sizeof(MONITORINFOEXA))) return 0;
    mi->rcMonitor = monitors[i].at, mi->dwFlags = monitors[i].primary ? MONITORINFOF_PRIMARY : 0;
    if (mi->cbSize == sizeof(MONITORINFOEXA)) snprintf(((MONITORINFOEXA *)mi)->szDevice, 32, "%s", monitors[i].device);
    return 1;
}
static int GetSystemMetrics(int i) { return i == SM_CXSCREEN ? 3840 : i == SM_CYSCREEN ? 1600 : -1; }
static BOOL EnumDisplayMonitors(HDC dc, LPRECT clip, BOOL (*each)(HMONITOR, HDC, LPRECT, LPARAM), LPARAM param) {
    (void)dc, (void)clip;
    for (int i = 0; i < 3; i++)
        if (!each(handle(i), NULL, NULL, param)) break;
    return 1;
}
/* (the display configuration's paths: in another order than the monitors, each source with its GDI device) */
static const int path_monitor[3] = {2, 0, 1};
static LONG GetDisplayConfigBufferSizes(UINT32 flags, UINT32 *paths, UINT32 *modes) {
    if (flags != QDC_ONLY_ACTIVE_PATHS || no_configuration) return 1;
    *paths = 3, *modes = 6;
    return ERROR_SUCCESS;
}
static LONG QueryDisplayConfig(UINT32 flags, UINT32 *np, DISPLAYCONFIG_PATH_INFO *paths, UINT32 *nm, DISPLAYCONFIG_MODE_INFO *modes, void *topology) {
    (void)modes, (void)topology;
    if (flags != QDC_ONLY_ACTIVE_PATHS || *np < 3 || *nm < 6) return 1;
    for (UINT32 i = 0; i < 3; i++) {
        paths[i].sourceInfo.adapterId.LowPart = 7, paths[i].sourceInfo.id = 100 + i;
        paths[i].targetInfo.adapterId.LowPart = 7, paths[i].targetInfo.id = 200 + i;
    }
    *np = 3;
    return ERROR_SUCCESS;
}
static void widen(WCHAR *out, int cap, const char *text) {
    int i = 0;
    for (; text[i] && i + 1 < cap; i++) out[i] = (unsigned char)text[i];
    out[i] = 0;
}
static LONG DisplayConfigGetDeviceInfo(DISPLAYCONFIG_DEVICE_INFO_HEADER *h) {
    if (h->adapterId.LowPart != 7) return 1;
    if (h->type == DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME && h->size == sizeof(DISPLAYCONFIG_SOURCE_DEVICE_NAME) && h->id >= 100 && h->id < 103) {
        widen(((DISPLAYCONFIG_SOURCE_DEVICE_NAME *)h)->viewGdiDeviceName, 32, monitors[path_monitor[h->id - 100]].device);
        return ERROR_SUCCESS;
    }
    if (h->type == DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME && h->size == sizeof(DISPLAYCONFIG_TARGET_DEVICE_NAME) && h->id >= 200 && h->id < 203) {
        DISPLAYCONFIG_TARGET_DEVICE_NAME *t = (DISPLAYCONFIG_TARGET_DEVICE_NAME *)h;
        const char *name = monitors[path_monitor[h->id - 200]].name;
        t->flags.friendlyNameFromEdid = name != NULL;
        widen(t->monitorFriendlyDeviceName, 64, name ? name : "Generic PnP Monitor");
        return ERROR_SUCCESS;
    }
    return 1;
}
static int WideCharToMultiByte(UINT page, DWORD flags, const WCHAR *wide, int n, char *out, int cap, const char *dflt, BOOL *used) {
    int i = 0;
    (void)flags, (void)dflt, (void)used;
    if (page != CP_UTF8 || n != -1) abort();   /* (UTF-8, never the system's code page: tests/test_utf8_paths.py) */
    for (; wide[i]; i++) {
        if (i + 1 >= cap) return 0;
        out[i] = (char)wide[i];
    }
    out[i] = 0;
    return i + 1;
}

@FUNCTIONS@

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); failed = 1; } } while (0)
int main(void) {
    int failed = 0, w, h;
    HosScreen s[8];
    /* started from another program, or a shortcut on the main monitor: every monitor, the main one the window's */
    memset(&started, 0, sizeof started);
    CHECK(hos_screens(s, 8) == 3);
    CHECK(s[0].w == 3440 && s[0].h == 1440 && !s[0].opens && !strcmp(s[0].name, "LG ULTRAGEAR"));
    CHECK(s[1].w == 3840 && s[1].h == 1600 && s[1].opens && !strcmp(s[1].name, "38GN950"));
    CHECK(s[2].w == 1920 && s[2].h == 1200 && !s[2].opens && !strcmp(s[2].name, ""));   /* (no name of its own: none) */
    w = h = -1, hos_screen_size(&w, &h);
    CHECK(w == 3840 && h == 1600);
    /* started from the first monitor's taskbar: the window opens there, whatever its place on the desktop */
    started.hStdOutput = handle(0);
    CHECK(hos_screens(s, 8) == 3 && s[0].opens && !s[1].opens && !s[2].opens);
    w = h = -1, hos_screen_size(&w, &h);
    CHECK(w == 3440 && h == 1440);
    /* standard handles passed (a console, a pipe): hStdOutput is one of them, not a monitor */
    started.dwFlags = STARTF_USESTDHANDLES;
    CHECK(hos_screens(s, 8) == 3 && !s[0].opens && s[1].opens);
    w = h = -1, hos_screen_size(&w, &h);
    CHECK(w == 3840 && h == 1600);
    /* a handle there that is no monitor: the main monitor */
    started.dwFlags = 0, started.hStdOutput = (HANDLE)&started;
    CHECK(hos_screens(s, 8) == 3 && s[1].opens);
    w = h = -1, hos_screen_size(&w, &h);
    CHECK(w == 3840 && h == 1600);
    /* fewer asked for than there are; and no display configuration: the sizes all the same, without names */
    memset(&started, 0, sizeof started);
    CHECK(hos_screens(s, 2) == 2 && s[1].opens);
    no_configuration = 1;
    CHECK(hos_screens(s, 8) == 3 && s[0].w == 3440 && !s[0].name[0] && !s[1].name[0] && s[1].opens);
    if (!failed) puts("screens: every monitor's size and name, and the one the window opens on");
    return failed;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    source = (ROOT / "host/display.c").read_text(encoding="utf-8")
    start = source.index("static HMONITOR shell_monitor(void) {")
    end = source.index("int hos_screens(HosScreen *out, int cap) {")
    functions = source[start:source.index("\n}\n", end) + 3]
    # the window is still made at the default position, which is what puts it on that monitor
    create = source[source.index("hwnd = CreateWindowA("):]
    if "WS_OVERLAPPEDWINDOW, CW_USEDEFAULT,\n                         CW_USEDEFAULT," not in create[:create.index(";")]:
        raise SystemExit("FAIL: host/display.c no longer makes the window at CW_USEDEFAULT: hos_screen_size names another monitor")
    # the Linux window: SDL's displays, read on the main thread before the game; the main one is the window's
    sdl = (ROOT / "host/posix/display_sdl.c").read_text(encoding="utf-8")
    if "void hos_screen_size(int *w, int *h) { *w = hos_posix_window[1], *h = hos_posix_window[2]; }" not in sdl:
        raise SystemExit("FAIL: host/posix/display_sdl.c: hos_screen_size is not the desktop size hos_display_init read")
    init = sdl[sdl.index("int hos_display_init(void) {"):sdl.index("void hos_display_start(void) {")]
    if "screens_read(w, h);" not in init or "int hos_screens(HosScreen *out, int cap) {" not in sdl or "hos_sdl_displays(d, 16)" not in sdl:
        raise SystemExit("FAIL: host/posix/display_sdl.c does not read SDL's displays in hos_display_init for hos_screens")
    lib = (ROOT / "host/hos_sdl.c").read_text(encoding="utf-8")
    if 'three ? "SDL_GetDisplays" : "SDL_GetNumVideoDisplays"' not in lib or '"SDL_GetDisplayName"' not in lib:
        raise SystemExit("FAIL: host/hos_sdl.c does not list the displays with SDL3's and SDL2's own calls")
    applet = (ROOT / "host/nn_applet.c").read_text(encoding="utf-8")
    if "hos_screen_size(&sw, &sh);" not in applet:
        raise SystemExit("FAIL: host/nn_applet.c does not take the old Screen's size from hos_screen_size")
    with tempfile.TemporaryDirectory(prefix="screen-size-") as tmp:
        work = Path(tmp)
        c_file, exe = work / "fixture.c", work / "fixture.exe"
        c_file.write_text(FIXTURE.replace("@FUNCTIONS@", functions), encoding="utf-8")
        subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT), str(c_file), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("PASS: the connected screens: each monitor's size and name, and the one the window opens on (the shell's, else the "
          "main one)")


if __name__ == "__main__":
    main()
