"""XInput is read off the game's thread (host/nn_hid.c, pads_read and the XInput code before it).

With no controller SDL reads, pads_read asked XInput for its pads, and each second it asked all four empty slots again,
in one read on the game's thread. XInputGetState on an empty slot is slow on Windows (it looks for the device again),
so players on a keyboard and mouse got a hitch every second, and plugging in a controller "raised the frame rate".

Production's pads_read and everything nn_hid.c puts between pad_raw_now and it (the dead zones, the XInput code) are
compiled with fakes for SDL (no pads), the clock and XInputGetState, and called on this thread for 1.5 s as the game
calls it. The fake has a controller in slot 0 holding A and the three others empty, and records which thread asks it.
Checked: the game's thread never asks XInput, and the controller's A still reaches pads_read's reading. No device is
read.

python -I -B tests/test_xinput_thread.py [--cc gcc]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]

PRELUDE = r"""#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
typedef DWORD ThreadId;
static ThreadId thread_self(void) { return GetCurrentThreadId(); }
static int thread_same(ThreadId a, ThreadId b) { return a == b; }
static int64_t hos_now_ns(void) {
    LARGE_INTEGER f, t;
    QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&t);
    return (int64_t)(t.QuadPart / f.QuadPart) * 1000000000LL + (int64_t)(t.QuadPart % f.QuadPart) * 1000000000LL / f.QuadPart;
}
#else
#include <pthread.h>
#include <time.h>
typedef long LONG;
typedef uint16_t WORD;
typedef uint32_t DWORD;
typedef void *HMODULE;
typedef void *HANDLE;
#define WINAPI
#define ERROR_SUCCESS 0
typedef pthread_t ThreadId;
static ThreadId thread_self(void) { return pthread_self(); }
static int thread_same(ThreadId a, ThreadId b) { return pthread_equal(a, b); }
#define LOAD_LIBRARY_SEARCH_SYSTEM32 0x800
static HMODULE LoadLibraryExA(const char *name, void *file, unsigned flags) { (void)name; (void)file; (void)flags; return NULL; }
static HMODULE LoadLibraryA(const char *name) { (void)name; return NULL; }
static void *GetProcAddress(HMODULE m, const char *name) { (void)m; (void)name; return NULL; }
static LONG InterlockedExchange(volatile LONG *p, LONG v) { return __atomic_exchange_n(p, v, __ATOMIC_SEQ_CST); }
typedef pthread_rwlock_t SRWLOCK;
#define SRWLOCK_INIT PTHREAD_RWLOCK_INITIALIZER
static void AcquireSRWLockShared(SRWLOCK *p) { pthread_rwlock_rdlock(p); }
static void ReleaseSRWLockShared(SRWLOCK *p) { pthread_rwlock_unlock(p); }
static void AcquireSRWLockExclusive(SRWLOCK *p) { pthread_rwlock_wrlock(p); }
static void ReleaseSRWLockExclusive(SRWLOCK *p) { pthread_rwlock_unlock(p); }
typedef DWORD(WINAPI *LPTHREAD_START_ROUTINE)(void *);
struct start { LPTHREAD_START_ROUTINE fn; void *arg; };
static void *thread_start(void *p) { struct start s = *(struct start *)p; free(p); s.fn(s.arg); return NULL; }
static HANDLE CreateThread(void *attr, size_t stack, LPTHREAD_START_ROUTINE fn, void *arg, DWORD flags, DWORD *id) {
    (void)attr; (void)stack; (void)flags; (void)id;
    struct start *s = malloc(sizeof *s);
    s->fn = fn, s->arg = arg;
    pthread_t t;
    if (pthread_create(&t, NULL, thread_start, s)) return NULL;
    pthread_detach(t);
    return (HANDLE)1;
}
static int CloseHandle(HANDLE h) { (void)h; return 1; }
static void Sleep(DWORD ms) { struct timespec t = {ms / 1000, (long)(ms % 1000) * 1000000L}; nanosleep(&t, NULL); }
static int64_t hos_now_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (int64_t)t.tv_sec * 1000000000LL + t.tv_nsec;
}
#endif
#define ERROR_DEVICE_NOT_CONNECTED_ 1167
#define XUSER_MAX_COUNT 4
enum { XINPUT_GAMEPAD_DPAD_UP = 1, XINPUT_GAMEPAD_DPAD_DOWN = 2, XINPUT_GAMEPAD_DPAD_LEFT = 4, XINPUT_GAMEPAD_DPAD_RIGHT = 8,
       XINPUT_GAMEPAD_START = 16, XINPUT_GAMEPAD_BACK = 32, XINPUT_GAMEPAD_LEFT_THUMB = 64, XINPUT_GAMEPAD_RIGHT_THUMB = 128,
       XINPUT_GAMEPAD_LEFT_SHOULDER = 256, XINPUT_GAMEPAD_RIGHT_SHOULDER = 512, XINPUT_GAMEPAD_A = 4096,
       XINPUT_GAMEPAD_B = 8192, XINPUT_GAMEPAD_X = 16384, XINPUT_GAMEPAD_Y = 32768 };
typedef struct { WORD wButtons; uint8_t bLeftTrigger, bRightTrigger; int16_t sThumbLX, sThumbLY, sThumbRX, sThumbRY; } XINPUT_GAMEPAD;
typedef struct { DWORD dwPacketNumber; XINPUT_GAMEPAD Gamepad; } XINPUT_STATE;
typedef DWORD(WINAPI *XInputGetStateFn)(DWORD, XINPUT_STATE *);

/* the game's thread, and what the fake XInput saw */
static ThreadId game_thread;
static volatile int asked_on_game, asked_elsewhere, empty_asked_elsewhere;
static DWORD WINAPI fake_xinput(DWORD user, XINPUT_STATE *s) {
    if (thread_same(thread_self(), game_thread)) __atomic_add_fetch(&asked_on_game, 1, __ATOMIC_RELAXED);
    else {
        __atomic_add_fetch(&asked_elsewhere, 1, __ATOMIC_RELAXED);
        if (user) __atomic_add_fetch(&empty_asked_elsewhere, 1, __ATOMIC_RELAXED);
    }
    if (user) return ERROR_DEVICE_NOT_CONNECTED_;   /* (slots 1 to 3: empty) */
    memset(s, 0, sizeof *s);
    s->Gamepad.wButtons = XINPUT_GAMEPAD_A;
    return ERROR_SUCCESS;
}
static XInputGetStateFn xinput_get = fake_xinput;

void hos_host_thread_register_self(const char *name) { (void)name; }
static void hos_log(const char *format, ...) { (void)format; }
int rx_option(int id, int otherwise) { (void)id; (void)otherwise; return 0; }   /* (the default dead zone, no inversion) */
int hos_sdl_pads(uint64_t *buttons, int32_t stick[4]) {   /* (SDL has no pads) */
    (void)buttons; (void)stick;
    return 0;
}
static void binds_load(void) {}
static volatile LONG pad_bind[HOS_SW_N][2];   /* (Input 1 and Input 2) */
static uint64_t hud_pad_mask(void) { return 0; }   /* ((Triforce) Toggle HUD unbound, as out of the box: no input of its own) */
static uint64_t oc_consumed_pads;   /* ((Triforce) 11-24: the inputs that are ocarina notes at a read: none here) */
"""

MAIN = r"""
int main(void) {
    for (int i = 0; i < HOS_SW_N; i++) pad_bind[i][0] = pad_default[i], pad_bind[i][1] = -1;
    game_thread = thread_self();
    (void)pad_raw_game;   /* (read_input's, after the Insert menu: tests/test_pads_after_menu.py) */
    const int64_t start = hos_now_ns();
    int a_seen = 0;
    while (hos_now_ns() - start < 1500000000LL) {   /* (past the empty slots' one-second retry) */
        uint64_t buttons = 0;
        int32_t stick[4] = {0};
        pads_read(&buttons, stick);
        a_seen |= (int)((uint32_t)pad_raw_now >> HOS_PAD_SOUTH) & 1;
        Sleep(3);   /* (past pads_read's 2 ms cache) */
    }
    if (asked_on_game)
        fprintf(stderr, "the game's thread asked XInputGetState %d times (%d elsewhere)\n", asked_on_game, asked_elsewhere);
    CHECK(asked_on_game == 0);
    CHECK(asked_elsewhere > 0);
    CHECK(empty_asked_elsewhere >= 6);   /* (the three empty slots, asked again after a second, by the thread) */
    CHECK(a_seen);
    puts("PASS: XInput is read on a thread of its own, never the game's, and its pad still reaches pads_read");
    return 0;
}
"""


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
    api = (ROOT / "gpu" / "vk" / "vk_api.h").read_text(encoding="utf-8")
    # (from the pads' raw bits to the end of pads_read: the dead zones, XInput's read and its thread, pads_read itself)
    start = hid.index("static volatile LONG pad_raw_now;")
    body = hid[start:hid.index("static void pads_read(")] + block(hid, "static void pads_read(")
    code = "\n".join((
        block(api, "enum { HOS_SW_A") + ";", block(api, "enum { HOS_PAD_SOUTH") + ";",
        block(api, "enum { HOS_PAD_LS_UP") + ";", block(api, "enum { HOS_OPT_RUMBLE_CURVE = 50") + ";",
        PRELUDE,
        block(hid, "static const signed char pad_default[HOS_SW_N] =") + ";",
        block(hid, "static void stick_max("),
        body,
        MAIN))
    with tempfile.TemporaryDirectory(prefix="triforce-xinput-thread-") as tmp:
        src = Path(tmp) / "t.c"
        src.write_text(code, encoding="utf-8")
        exe = Path(tmp) / "t.exe"
        threads = [] if sys.platform == "win32" else ["-pthread"]
        subprocess.run([a.cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                        "-Wno-deprecated-declarations", *threads, "-o", str(exe), str(src)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        if r.returncode:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
