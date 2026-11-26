/* nn::hid: one Pro Controller (FullKey style) on Npad No.1, from every XInput gamepad and the keyboard and mouse at
   once. Buttons map by position (the Xbox bottom face button is the Switch's bottom one, B).

   (hookshot) What presses each button, on a gamepad and on the keyboard, is the player's: the Insert menu's Controls
   page (gpu/vk/vk_menu.cpp) changes it, kept in triforce_options.ini (binds_load). The defaults:
   Keyboard (totk-pc-recomp's layout): WASD left stick, arrows or IJKL right stick (camera), Space X (jump), E A
   (action), Shift B (run/cancel), Q L (abilities), R R, Z ZL, X or F ZR (bow), Ctrl left-stick click (crouch), C
   right-stick click (first person), Tab Plus (not Enter: controller software sends Enter for a pad's A), M Minus (map), 1 2 3 4 d-pad left, up, right, down. Only
   while the game's window is in front (the key state is global).
   Mouse (after a click in the window, display.c; Esc releases): its motion is the right stick (mouse panning,
   mouse_stick), or with the Insert menu's "Mouse camera" set to Native (HOS_MOUSE_NATIVE=1 or 0 overrides it) turns
   the camera itself (mouse_native.c); left button Y (attack), right button ZL (shield, lock on). - and = change its sensitivity (x0.8 /
   x1.25, shown in the title bar, kept by the Insert menu's Mouse sensitivity row); HOS_MOUSE_SENS=<x> sets it,
   HOS_MOUSE_INVERT_Y=1 (or the menu's Invert mouse vertical) flips up/down, HOS_MOUSE_INVERT_X=1 (or its Invert mouse
   horizontal) left/right.

   Controllers count only while the game's window is in front, like the keyboard, unless the Insert menu's "Controller in
   background" is on (or HOS_INPUT_BACKGROUND=1; =0 keeps them to the window in front whatever the menu says): then a
   game streamed from a screen of its own, or left running behind another window, still follows the pad. The keyboard
   and mouse stay with the window in front either way.

   HOS_INPUT_SCRIPT (test runs): timed presses added to the input, "<seconds>:<button>[+<button>...][/<ms held>],..."
   with buttons A B X Y L R ZL ZR PLUS MINUS LS RS LEFT UP RIGHT DOWN and the stick directions LUP LDOWN LLEFT
   LRIGHT RUP RDOWN RLEFT RRIGHT; held 200 ms unless given. Example: "50:A,52:A,80:LUP/4000".

   Npad states share one layout (NpadCommonState): { s64 sampling; u64 buttons; s32 lx, ly; s32 rx, ry; u32 attributes;
   pad } = 0x28 bytes. */
#include "hos.h"
#include "hos_paths.h"
#include "control.h"   /* ((Triforce) the control bridge's presses: read_input) */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <xinput.h>
#include "../gpu/vk/vk_api.h"   /* (the controls' names: HOS_SW_*, HOS_PAD_*) */
#include "hold_toggle.h"   /* ((Triforce) 11-24: hold-to-toggle's latch) */
#include "hos_motion.h"
#include "vr_game.h"   /* ((Triforce VR) vr_pad_read, vr_session_on) */
#include "input_movie.h"   /* ((Triforce) MoviePad, MovieMotion: input recordings, host/input_movie.c) */
_Static_assert(sizeof(HosMotionState) == sizeof(((MovieMotion *)0)->v), "a motion reading is 18 floats in a recording");
#include "flight_jump.h"   /* ((Triforce, 11-24) the no-clip flight's Jump) */

enum { B_A = 0, B_B, B_X, B_Y, B_LS, B_RS, B_L, B_R, B_ZL, B_ZR, B_PLUS, B_MINUS, B_LEFT, B_UP, B_RIGHT, B_DOWN };
#define STATE_SIZE 0x28
#define NPAD_NO1 0
#define STYLE_FULLKEY 1u
#define ATTR_CONNECTED 1u

typedef DWORD(WINAPI *XInputGetStateFn)(DWORD, XINPUT_STATE *);
static XInputGetStateFn xinput_get;
static int64_t sampling;

int rx_option(int id, int otherwise);
/* (the Insert menu takes the keyboard while it is open) */
static int key(int vk) { return !rx_option(1, 0) && (GetAsyncKeyState(vk) & 0x8000) != 0; }

int hos_mouse_take(int32_t *dx, int32_t *dy);   /* display.c */

/* The captured mouse's sensitivity (mouse_stick below): - and = change it, kept in <user>/mouse_sens.txt */
double hos_mouse_sens = 0;   /* (display.c shows it in the title) */
extern const char *hos_user_dir;

static void mouse_sens_save(void) {
    char path[512];
    snprintf(path, sizeof path, "%s/mouse_sens.txt", hos_user_dir ? hos_user_dir : "user");
    /* ((Triforce) 11-24: written whole beside the file and then put in its place, as the host's other small files are
       (mod_cheats.c on_save): a crash or a kill while it was written left it empty or cut short, and the next start
       read no sensitivity from it) */
    char fresh[530];
    snprintf(fresh, sizeof fresh, "%s.new", path);
    FILE *f = fopen(fresh, "w");
    if (!f) return;
    const int ok = fprintf(f, "%.3f\n", hos_mouse_sens) > 0;
    if (fclose(f) || !ok || !MoveFileExA(fresh, path, MOVEFILE_REPLACE_EXISTING)) remove(fresh);
}

/* The Insert menu keeps the sensitivity (its Mouse sensitivity row, option 7, in percent), read with each read; - and =
   change it there. HOS_MOUSE_SENS still wins, and then - and = keep it in <user>/mouse_sens.txt as before. A value in
   mouse_sens.txt from before is moved into the menu once, while the menu's is still its default; the file is renamed
   mouse_sens.txt.moved then, so the menu's value is not replaced by it again at a later start */
void rx_option_set(int id, int value);
static int sens_from_file;   /* (mouse_setup: <user>/mouse_sens.txt was there) */
static void mouse_sens_keys(void) {
    static int prev_minus, prev_plus, from_env = -1;
    if (from_env < 0) {
        from_env = getenv("HOS_MOUSE_SENS") && atof(getenv("HOS_MOUSE_SENS")) > 0;
        if (!from_env && sens_from_file && rx_option(7, -1) >= 0) {   /* (the menu is there to take it) */
            if (hos_mouse_sens > 0 && fabs(hos_mouse_sens - 1.0) > 0.01 && rx_option(7, 100) == 100)
                rx_option_set(7, (int)lround(hos_mouse_sens * 100));
            char from[512], to[520];
            snprintf(from, sizeof from, "%s/mouse_sens.txt", hos_user_dir ? hos_user_dir : "user");
            snprintf(to, sizeof to, "%s.moved", from);
            remove(to);
            if (rename(from, to)) hos_log("hid: %s could not be renamed after its move into the menu", from);
        }
    }
    if (!from_env) hos_mouse_sens = rx_option(7, 100) / 100.0;
    const int minus = key(VK_OEM_MINUS) || key(VK_SUBTRACT), plus = key(VK_OEM_PLUS) || key(VK_ADD);
    if ((minus && !prev_minus) || (plus && !prev_plus)) {
        hos_mouse_sens *= minus && !prev_minus ? 0.8 : 1.25;
        if (hos_mouse_sens < 0.1) hos_mouse_sens = 0.1;
        if (hos_mouse_sens > 5) hos_mouse_sens = 5;
        if (from_env) mouse_sens_save();
        else rx_option_set(7, (int)lround(hos_mouse_sens * 100));
    }
    prev_minus = minus;
    prev_plus = plus;
}

/* The mouse as the right stick, "mouse panning" as MacNativeGames does it (games/totk/runtime/mouse_look.h,
   github.com/ly05010419/MacNativeGames, MIT; the idea is yuzu's): every movement adds to a held deflection, and a
   tick every 10 ms shows it to the game and then lets it decay. The camera keeps turning while the mouse moves and
   settles smoothly when it stops, whatever the mouse's report rate, the game's frame rate or how often it reads the
   pad (the old speed-per-8-ms stick jumped between reads). The decay grows with the deflection (1 - length^2 *
   decay), at least min_decay a tick; the held length is cut to 1.5 (past the stick's edge, so a steady turn is easy
   to hold) and shown at most 1. A movement that leaves less than 20% is lifted to 20%, past the game's dead zone.
   MacNativeGames' decay (18%, at least 6%) suits a trackpad: with a mouse the camera drifted on for 0.4 s after it
   stopped. Here 30%, at least 20% (HOS_MOUSE_DECAY / HOS_MOUSE_MIN_DECAY, percent): it stops within ~0.1 s, and one
   raw count moves the stick by sensitivity * 0.03, so at 1 the deflection follows 100-700 counts/s (0.2 to ~0.9)
   and is full from ~1000. */
enum { MOUSE_TICK_NS = 10000000 };
static double look_x, look_y;   /* (the held deflection, stick units, y up) */

static double mouse_percent(const char *name, double fallback) {
    const char *e = getenv(name);
    return e && atof(e) >= 0 && atof(e) <= 100 ? atof(e) / 100 : fallback;
}

static void mouse_look_move(double dx, double dy) {
    const double k = hos_mouse_sens * 0.03;
    look_x += dx * k;
    look_y += dy * k;
    const double length = sqrt(look_x * look_x + look_y * look_y), least = 0.2;
    if (length > 0 && length < least) look_x *= least / length, look_y *= least / length;
}

static void mouse_look_tick(void) {
    static double decay_rate = -1, min_decay;
    if (decay_rate < 0) {
        decay_rate = mouse_percent("HOS_MOUSE_DECAY", 0.30);
        min_decay = mouse_percent("HOS_MOUSE_MIN_DECAY", 0.20);
    }
    double length = sqrt(look_x * look_x + look_y * look_y);
    if (length > 1.5) look_x *= 1.5 / length, look_y *= 1.5 / length, length = 1.5;
    const double c = length < 1 ? length : 1, decay = 1 - c * c * decay_rate, most = 1 - min_decay;
    const double keep = decay < most ? (decay > 0 ? decay : 0) : most;
    look_x *= keep;
    look_y *= keep;
    if (fabs(look_x) < 1e-6 && fabs(look_y) < 1e-6) look_x = look_y = 0;
}

/* (host/oot_menu.c) A drag of the free mouse in the game's own menus (the map, the tapestry): panned as
   the camera's mouse is (mouse_look_move, mouse_look_tick: the same sensitivity, least deflection and decay), on the
   left stick (right = 0: the map's and the tapestry's pan) or the right (1: Key Items' stones turned). The pixels it
   moved (y up) come from the game's thread; the read takes them. The camera's 0.03 a count is for raw counts, several
   to a screen pixel at a mouse's usual DPI: a pixel here is HOS_MENU_DRAG_GAIN of them (6) */
/* (display.c hides the free mouse in the game's menus while the player uses a pad or the keys) the last
   time the player's pads (a button, a stick past a third) or bound keys were used */
static volatile LONG64 player_input_ns;
int64_t hos_player_input_ns(void) { return InterlockedCompareExchange64(&player_input_ns, 0, 0); }
static void player_used(void) { InterlockedExchange64(&player_input_ns, hos_now_ns()); }
/* ((Triforce, 11-19) the device the player used last: 0 none yet, 1 the keys or the mouse (a bound key, a bound mouse
   button or the captured mouse's motion), 2 a controller (a button, a stick past 12000), for host/prompts.c's Button prompts
   Auto (the face of the next start) and the overlay's icons. read_input only stores it, and only when it changes; and counts
   each device's uses (hos_input_uses: prompts.c tells a player using the keys from a key pressed once) */
static volatile LONG input_last, input_uses[3];
int hos_input_last(void) { return (int)input_last; }
unsigned hos_input_uses(int device) { return device >= 1 && device <= 2 ? (unsigned)input_uses[device] : 0; }
static void device_used(LONG device) {
    InterlockedIncrement(&input_uses[device]);
    if (input_last != device) InterlockedExchange(&input_last, device);
}
static volatile LONG drag_dx, drag_dy, drag_right;
static double drag_x, drag_y;
void hos_hid_drag(int dx, int dy, int right) {
    if (right != (int)drag_right) InterlockedExchange(&drag_right, right);
    InterlockedExchangeAdd(&drag_dx, dx);
    InterlockedExchangeAdd(&drag_dy, dy);
}
static void host_drag_read(int32_t stick[4]) {
    static int64_t next_tick;
    const int64_t now = hos_now_ns();
    const int dx = (int)InterlockedExchange(&drag_dx, 0), dy = (int)InterlockedExchange(&drag_dy, 0);
    if (dx || dy) {
        static double gain = -1;
        if (gain < 0) {
            const char *e = getenv("HOS_MENU_DRAG_GAIN");
            gain = e && atof(e) > 0 ? atof(e) : 6.0;
        }
        const double k = (hos_mouse_sens > 0 ? hos_mouse_sens : 1.0) * 0.03 * gain;
        drag_x += dx * k;
        drag_y += dy * k;
        const double length = sqrt(drag_x * drag_x + drag_y * drag_y), least = 0.2;
        if (length > 0 && length < least) drag_x *= least / length, drag_y *= least / length;
    }
    if (drag_x == 0 && drag_y == 0) { next_tick = 0; return; }
    double ox = drag_x, oy = drag_y;
    const double shown = sqrt(ox * ox + oy * oy);
    if (shown > 1) ox /= shown, oy /= shown;
    const int32_t v[2] = {(int32_t)(ox * 32767), (int32_t)(oy * 32767)};
    const int at = drag_right ? 2 : 0;
    for (int i = 0; i < 2; i++)
        if ((v[i] < 0 ? -v[i] : v[i]) > (stick[at + i] < 0 ? -stick[at + i] : stick[at + i])) stick[at + i] = v[i];
    /* (the decay, a tick each 10 ms since the last read, as the camera's) */
    int64_t ticks = next_tick ? (now - next_tick) / MOUSE_TICK_NS + 1 : 1;
    if (ticks > 10) ticks = 10;
    next_tick = now + MOUSE_TICK_NS;
    static double decay_rate = -1, min_decay;
    if (decay_rate < 0) decay_rate = mouse_percent("HOS_MOUSE_DECAY", 0.30), min_decay = mouse_percent("HOS_MOUSE_MIN_DECAY", 0.20);
    for (int64_t t = 0; t < ticks; t++) {
        double length = sqrt(drag_x * drag_x + drag_y * drag_y);
        if (length > 1.5) drag_x *= 1.5 / length, drag_y *= 1.5 / length, length = 1.5;
        const double c = length < 1 ? length : 1, decay = 1 - c * c * decay_rate, most = 1 - min_decay;
        const double keep = decay < most ? (decay > 0 ? decay : 0) : most;
        drag_x *= keep, drag_y *= keep;
    }
    if (fabs(drag_x) < 1e-6 && fabs(drag_y) < 1e-6) drag_x = drag_y = 0;
}

/* While the ability wheel is open (L held, Q on the keyboard), the mouse points instead of panning (MacNativeGames
   2d0f0f0, MIT): the wheel picks the ability the right stick points at, and with panning the stick settled back to
   the centre as soon as the mouse stopped, taking the pick with it. The stick starts at the centre, stays where the
   mouse puts it (cut to length 1) and is centred again when L is let go, so the camera does not turn by itself after
   the wheel closes. */
static int invert = -1;
static void mouse_setup(void) {   /* (once: the sensitivity kept in <user>/mouse_sens.txt, HOS_MOUSE_SENS, the inversion) */
    if (invert < 0) {
        invert = getenv("HOS_MOUSE_INVERT_Y") != NULL;
        hos_mouse_sens = 1.0;
        char path[512];
        snprintf(path, sizeof path, "%s/mouse_sens.txt", hos_user_dir ? hos_user_dir : "user");
        FILE *f = fopen(path, "r");
        if (f) {
            double v;
            if (fscanf(f, "%lf", &v) == 1 && v > 0) hos_mouse_sens = v;
            fclose(f);
            sens_from_file = 1;
        }
        const char *e = getenv("HOS_MOUSE_SENS");
        if (e && atof(e) > 0) hos_mouse_sens = atof(e);
    }
}

/* ((Triforce) mouse_native.c, for a test script's MX= and MY=) The sensitivity the native mouse camera turns by:
   hos_mouse_sens once a read went the mouse's way, and before that HOS_MOUSE_SENS or the menu's, 0.1 to 5 as its keys
   keep it: a script's mouse motion under HOS_INPUT_EXCLUSIVE, which returns before the mouse, turned the camera by 0
   degrees. Nothing is set up here */
double hos_mouse_sensitivity(void) {
    double s = hos_mouse_sens;
    if (s > 0) return s;
    const char *e = getenv("HOS_MOUSE_SENS");
    s = e && atof(e) > 0 ? atof(e) : rx_option(7, 100) / 100.0;
    return s < 0.1 ? 0.1 : s > 5 ? 5 : s;
}

static int mouse_stick(int32_t *rx, int32_t *ry, int pointing) {
    static int64_t next_tick;
    static int32_t shown[2];
    static int captured, was_pointing;
    mouse_setup();
    mouse_sens_keys();
    static int env_invert = -1;   /* (HOS_MOUSE_INVERT_Y, or the menu's Invert mouse vertical, option 8) */
    if (env_invert < 0) env_invert = invert;
    invert = env_invert || rx_option(8, 0);
    /* ((Triforce) 11-24: HOS_MOUSE_INVERT_X=1, or the menu's Invert mouse horizontal, option 190 (HOS_OPT_MOUSE_INVERT_X):
       left and right, as the camera's own angles take it in mouse_native.c) */
    static int env_invert_x = -1;
    if (env_invert_x < 0) { const char *e = getenv("HOS_MOUSE_INVERT_X"); env_invert_x = e && atoi(e) != 0; }
    const int invert_x = env_invert_x || rx_option(HOS_OPT_MOUSE_INVERT_X, 0);
    const int64_t now = hos_now_ns();
    if (now >= next_tick) {
        int32_t dx, dy;
        captured = hos_mouse_take(&dx, &dy);
        if (pointing != was_pointing) look_x = look_y = 0, was_pointing = pointing;
        if (!captured) look_x = look_y = 0;
        else if (pointing) {
            const double k = hos_mouse_sens * 0.03;
            look_x += (invert_x ? -dx : dx) * k;
            look_y += (invert ? dy : -dy) * k;
            const double length = sqrt(look_x * look_x + look_y * look_y);
            if (length > 1) look_x /= length, look_y /= length;
        } else if (dx || dy) mouse_look_move(invert_x ? -dx : dx, invert ? dy : -dy);
        /* (the ticks since the last read: the first shows the deflection, the rest only decay it; at most 10, a
           read after a pause starts afresh) */
        const int64_t ticks = next_tick ? (now - next_tick) / MOUSE_TICK_NS + 1 : 1;
        double ox = look_x, oy = look_y;
        if (!pointing) {   /* (Triforce: the Camera speed row is the stick's; the game multiplies this deflection by it too) */
            double hos_camera_speed(void);   /* (host/prompts.c) */
            const double cam = hos_camera_speed();
            ox /= cam, oy /= cam;
        }
        const double shown_length = sqrt(ox * ox + oy * oy);
        if (shown_length > 1) ox /= shown_length, oy /= shown_length;
        shown[0] = (int32_t)lround(ox * 32767);
        shown[1] = (int32_t)lround(oy * 32767);
        if (!pointing)
            for (int64_t i = 0; i < (ticks < 10 ? ticks : 10); i++) mouse_look_tick();
        next_tick = (next_tick && ticks <= 10 ? next_tick + ticks * MOUSE_TICK_NS : now + MOUSE_TICK_NS);
    }
    if (!captured) return 0;
    *rx = shown[0];
    *ry = shown[1];
    return 1;
}

/* A bound key is down: Enter held with Alt is no button (Alt+Enter is fullscreen, host/display.c and
   host/posix/display_sdl.c). tests/test_alt_enter.py */
static int kmap_down(int vk, int (*down)(int)) { return down(vk) && !(vk == VK_RETURN && down(VK_MENU)); }

#ifndef __EMSCRIPTEN__
/* (Triforce) The program whose window is in front, for game_in_front's log line: its file's name alone, never its folder
   (a user's name) or the window's title (a document's or a page's name). "?" where Windows does not say.
   tests/test_input_background.py has its own */
static void front_program(DWORD pid, char *name, int size) {
    snprintf(name, (size_t)size, "?");
#ifdef _WIN32
    HANDLE p = pid ? OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid) : NULL;
    if (!p) return;
    char path[MAX_PATH];
    DWORD n = sizeof path;
    if (QueryFullProcessImageNameA(p, 0, path, &n)) {
        const char *base = strrchr(path, '\\');
        snprintf(name, (size_t)size, "%s", base ? base + 1 : path);
    }
    CloseHandle(p);
#else
    (void)pid;
#endif
}
#endif

static int game_in_front(void) {
    DWORD pid = 0;
    HWND w = GetForegroundWindow();
    if (w) GetWindowThreadProcessId(w, &pid);
    int front = pid == GetCurrentProcessId();
#ifndef __EMSCRIPTEN__
    static int last_normal_was_us = 1, was_front = 1;
    static int64_t none_since, changed_ns;
    const int64_t now = hos_now_ns();
    /* (Triforce) No window in front at all: Windows answers so for a moment while the window in front changes, and a
       notification or an overlay coming and going is such a change. Taken as "not in front", each such moment let every
       button go and centred the sticks for a read, with the game still in front: a held shield dropped, a run stopped.
       The answer before it stands for a quarter of a second of that; longer (a locked PC) is not in front */
    if (!w) {
        if (!none_since) none_since = now;
        if (now - none_since < 250000000LL) return was_front;
    } else {
        none_since = 0;
    }
    LONG_PTR ex = 0;
    if (w && !front) {
        ex = GetWindowLongPtrA(w, GWL_EXSTYLE);
        const int overlay = (ex & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)) != 0;
        if (overlay && last_normal_was_us) front = 1;
        else last_normal_was_us = 0;
    } else if (front) {
        last_normal_was_us = 1;
    }
    if (front != was_front) {
        /* (Triforce) for a report of a controller that "disconnects": which program took the front (its file's name and its
           window's extended styles, by which an overlay is told from a window), and for how long the game was behind it:
           the controllers do not count all that time unless Controller in background is on */
        char cls[64] = "", program[64];
        if (w) GetClassNameA(w, cls, sizeof cls);
        front_program(pid, program, sizeof program);
        hos_log("hid: game window %s (foreground window: process %lu, class \"%s\", program %s, styles %#lx)%s",
                front ? "in front" : "not in front", (unsigned long)pid, cls, program, (unsigned long)ex,
                front ? "" : ": the controllers do not count until it is in front again, unless Controller in background is on");
        if (front && changed_ns) hos_log("hid: the game window was not in front for %.1f s", (now - changed_ns) / 1e9);
        changed_ns = now;
        was_front = front;
    }
#endif
    return front;
}

/* HOS_INPUT_SCRIPT, and HOS_INPUT_LIVE=<file>: lines appended to that file while the game runs are presses in the
   script's syntax, their times counted from when the line is read ("0:LUP/2000,2:A"): a test can steer the game
   by looking at its screenshots. */
typedef struct { int64_t start_ms, end_ms; uint64_t buttons; int32_t stick[4]; int32_t mouse[2]; int host; } Press;   /* (host: hos_hid_tap's) */
#define MAX_PRESSES 1024
static Press presses[MAX_PRESSES];
static int npresses = -1;
static int64_t script_t0, script_end_ms;
static int script_frame_clock;
static int64_t script_frame0;
extern volatile LONG64 hos_present_count;   /* native game presents, not generated frames or HID polls */
/* HOS_INPUT_FRAME_CLOCK=1: the existing script seconds/millisecond holds advance at 60 native frames per second.
   Live-file polling and HID diagnostics keep their wall clocks. Default/0/empty retains wall-clock scripts. */
static int64_t script_elapsed_ms(int64_t now) {
    if (!script_frame_clock) return (now - script_t0) / 1000000;
    const int64_t frames = InterlockedCompareExchange64(&hos_present_count, 0, 0) - script_frame0;
    return frames * 1000 / 60;
}

static int parse_presses(const char *s, int64_t base_ms, int live);   /* (live: 0 the script, 1 HOS_INPUT_LIVE, 2 the host's) */

static void parse_script(void) {
    {   /* start SDL's controller thread now: pads are open by the time the game window comes to the front */
        int hos_sdl_pads(uint64_t *buttons, int32_t stick[4]);
        uint64_t b = 0;
        int32_t st[4] = {0};
        hos_sdl_pads(&b, st);
    }
    npresses = 0;
    script_t0 = hos_now_ns();
    {
        const char *e = getenv("HOS_INPUT_FRAME_CLOCK");
        script_frame_clock = e && atoi(e) != 0;
        if (script_frame_clock) {
            script_frame0 = InterlockedCompareExchange64(&hos_present_count, 0, 0);
            hos_log("hid: input frame clock origin=%lld native presents; rate=60", (long long)script_frame0);
        }
    }
    parse_presses(getenv("HOS_INPUT_SCRIPT"), 0, 0);
    if (npresses)
        hos_log("hid: input script of %d presses (last at %.0f s; the player's devices count too); origin_ns=%lld", npresses,
                script_end_ms / 1000.0, (long long)script_t0);
}

static void live_input(void) {
    static const char *path;
    static int64_t next_check, offset;
    static int looked;
    if (!looked) { looked = 1; path = getenv("HOS_INPUT_LIVE"); }
    if (!path) return;
    const int64_t now = hos_now_ns();
    if (now < next_check) return;
    next_check = now + 30000000;
    FILE *f = fopen(path, "rb");
    if (!f) return;
    if (fseek(f, (long)offset, SEEK_SET) == 0) {
        char line[4096];
        while (fgets(line, sizeof line, f)) {
            const size_t n = strlen(line);
            if (!n || line[n - 1] != '\n') break;   /* a line still being written: read it next time */
            offset += (int64_t)n;
            const int64_t at = script_elapsed_ms(now);
            if (line[0] == '!') {   /* commands: !dump = a frame dump of the next frame (as RX_DUMP_AT) */
                void rx_request_frame_dump(void);   /* gpu/render/rx_debug.cpp */
                if (!strncmp(line, "!dump", 5)) rx_request_frame_dump();
                extern volatile int hos_nvn_sync_log_on;   /* nvn_native.c: "!synclog" */
                if (!strncmp(line, "!synclog", 8)) hos_nvn_sync_log_on = 1;
                void rx_set_screenshot_ms(int64_t ms);   /* gpu/render/rx_core.cpp: "!shots <ms>" */
                if (!strncmp(line, "!shots ", 7)) rx_set_screenshot_ms(atoll(line + 7));
                void rx_request_rdoc_capture(int frames);   /* gpu/render/rx_debug.cpp: "!rdoc [frames]" */
                if (!strncmp(line, "!rdoc", 5)) rx_request_rdoc_capture(atoi(line + 5));
                void rx_flash_dark_arm(void);   /* gpu/render/rx_core.cpp: arms RX_FLASH_DARK_DUMP (RX_FLASH_DARK_AFTER=-1) */
                if (!strncmp(line, "!flasharm", 9)) rx_flash_dark_arm();
                extern volatile int hos_oot_live_action;   /* host/hos_main.c: "!cheat <action>", as the Cheats page sends */
                if (!strncmp(line, "!cheat ", 7)) __atomic_store_n(&hos_oot_live_action, atoi(line + 7), __ATOMIC_RELAXED);
                if (!strncmp(line, "!hud", 4)) {   /* ((Triforce, 11-25) the Toggle HUD row's toggle, for the lab's footage */
                    void hos_gameplay_hud_toggle(void);
                    hos_gameplay_hud_toggle();
                }
                {   /* ((Triforce) the button prompts' live part, host/prompts.c: "!bind <HOS_SW_*> <HOS_PAD_*>", as the
                       Controls page; "!prompts <0 Auto, HOS_PROMPT_* + 1>", as the Button prompts row) */
                    void hos_bind(int set, int button, int slot, int code);
                    int bind_b = -1, bind_pad = -2;
                    if (!strncmp(line, "!bind ", 6) && sscanf(line + 6, "%d %d", &bind_b, &bind_pad) == 2 && bind_b >= 0 &&
                        bind_b < HOS_SW_N)
                        hos_bind(HOS_BIND_PAD, bind_b, 0, bind_pad);
                    extern volatile int hos_prompts_row;
                    if (!strncmp(line, "!prompts ", 9)) __atomic_store_n(&hos_prompts_row, atoi(line + 9), __ATOMIC_RELAXED);
                }
                /* ((Triforce) "!type <text>": typed into the menu as the keyboard's characters would be (host/display.c; ASCII; "\b"
                   a Backspace), for the Mods screen's search in test runs, which have no window to type into) */
                if (!strncmp(line, "!type ", 6) && rx_option(HOS_OPT_TEXT_WANTED, 0))
                    for (const char *t = line + 6; *t && *t != '\r' && *t != '\n'; t++)
                        rx_option_set(HOS_OPT_TEXT_CHAR, t[0] == '\\' && t[1] == 'b' ? (t++, 8) : (unsigned char)*t);
                void hos_oot_live_crawl(const char *line);   /* host/hos_main.c: "!banc", "!pos", "!hold", "!where" (the pipeline crawl) */
                if (!strncmp(line, "!banc ", 6) || !strncmp(line, "!give ", 6) || !strncmp(line, "!items", 6) || !strncmp(line, "!pos ", 5) || !strncmp(line, "!hold ", 6) ||
                    !strncmp(line, "!where", 6))
                    hos_oot_live_crawl(line);
                hos_log("hid: live command at %.1f s: %.*s", at / 1000.0, (int)(n > 1 ? n - 1 : 0), line);
                continue;
            }
            const int got = parse_presses(line, at, 1);
            hos_log("hid: live input at %.1f s: %d presses (%.*s)", at / 1000.0, got, (int)(n > 1 ? n - 1 : 0), line);
        }
    }
    fclose(f);
}

static int parse_presses(const char *s, int64_t base_ms, int live) {
    static const struct { const char *name; int b; int axis; int dir; } names[] = {
        {"A", B_A}, {"B", B_B}, {"X", B_X}, {"Y", B_Y}, {"LS", B_LS}, {"RS", B_RS}, {"L", B_L}, {"R", B_R},
        {"ZL", B_ZL}, {"ZR", B_ZR}, {"PLUS", B_PLUS}, {"MINUS", B_MINUS}, {"LEFT", B_LEFT}, {"UP", B_UP},
        {"RIGHT", B_RIGHT}, {"DOWN", B_DOWN}, {"LUP", -1, 1, 1}, {"LDOWN", -1, 1, -1}, {"LLEFT", -1, 0, -1},
        {"LRIGHT", -1, 0, 1}, {"RUP", -1, 3, 1}, {"RDOWN", -1, 3, -1}, {"RLEFT", -1, 2, -1}, {"RRIGHT", -1, 2, 1}};
    int got = 0;
    const int64_t now_ms = script_elapsed_ms(hos_now_ns());
    while (s && *s) {
        while (*s == ' ' || *s == '\t') s++;
        Press p;
        memset(&p, 0, sizeof p);
        char *end;
        double t = strtod(s, &end);
        if (end == s || *end != ':') break;
        s = end + 1;
        int64_t hold = 200;
        for (;;) {
            size_t n = strcspn(s, "+/,@\r\n");
            /* ((Triforce) MX=<counts>, MY=<counts>: the mouse's motion each frame while it is held, for the native mouse
               camera's tests: hos_script_mouse_take) */
            if (n > 3 && s[0] == 'M' && (s[1] == 'X' || s[1] == 'Y') && s[2] == '=')
                p.mouse[s[1] == 'Y'] = (int32_t)strtol(s + 3, NULL, 10);
            int axis = -1;
            for (unsigned i = 0; i < sizeof names / sizeof *names; i++)
                if (strlen(names[i].name) == n && !strncmp(s, names[i].name, n)) {
                    if (names[i].b >= 0) p.buttons |= 1ULL << names[i].b;
                    else p.stick[axis = names[i].axis] = names[i].dir * 32767;
                }
            s += n;
            if (*s == '@') {   /* ((Triforce, 11-25) a stick part of the way: "RLEFT@30" is 30%, the lab's slow camera pans */
                char *e;
                const long pct = strtol(s + 1, &e, 10);
                if (axis >= 0 && pct >= 0 && pct <= 100) p.stick[axis] = p.stick[axis] * (int32_t)pct / 100;
                s = e;
            }
            if (*s != '+') break;
            s++;
        }
        if (*s == '/') hold = strtol(s + 1, (char **)&s, 10);
        p.start_ms = base_ms + (int64_t)(t * 1000);
        p.end_ms = p.start_ms + hold;
        p.host = live == 2;
        int slot = npresses < MAX_PRESSES ? npresses : -1;
        if (slot < 0)   /* full: reuse a press that is over */
            for (int i = 0; i < MAX_PRESSES && slot < 0; i++)
                if (presses[i].end_ms < now_ms) slot = i;
        if (slot < 0) break;
        if (!live && p.end_ms > script_end_ms) script_end_ms = p.end_ms;
        presses[slot] = p;
        if (slot == npresses) npresses++;
        got++;
        if (*s == ',') s++;
    }
    return got;
}

/* the host's own presses and stick (host/oot_menu.c: the game's menus' mouse), below: taken with the script's */
static void host_taps(void);
static void host_stick_read(int32_t stick[4]);
static void host_drag_read(int32_t stick[4]);   /* (above) */

/* ((Triforce) the script's mouse motion, MX= and MY=, as counts the native mouse camera takes with the window's:
   host/mouse_native.c. The controller's thread adds, the camera's update takes; with no such press, two loads) */
static int32_t script_mouse[2];
int hos_script_mouse_take(int32_t *dx, int32_t *dy) {
    *dx = *dy = 0;
    if (!__atomic_load_n(&script_mouse[0], __ATOMIC_RELAXED) && !__atomic_load_n(&script_mouse[1], __ATOMIC_RELAXED)) return 0;
    *dx = __atomic_exchange_n(&script_mouse[0], 0, __ATOMIC_RELAXED);
    *dy = __atomic_exchange_n(&script_mouse[1], 0, __ATOMIC_RELAXED);
    return *dx || *dy;
}

/* ((Triforce) 11-24: the host's taps go to *taps, not *buttons: they are the game's menus' mouse clicks, not the player's
   presses, so hold-to-toggle does not latch them: hold_toggle.h, npad_states) */
static void scripted_input(uint64_t *buttons, uint64_t *taps, int32_t stick[4]) {
    if (npresses < 0) parse_script();
    live_input();
    host_taps();
    const int64_t ms = script_elapsed_ms(hos_now_ns());
    for (int i = 0; i < npresses; i++)
        if (ms >= presses[i].start_ms && ms < presses[i].end_ms) {
            *(presses[i].host ? taps : buttons) |= presses[i].buttons;
            for (int k = 0; k < 4; k++)
                if (presses[i].stick[k]) stick[k] = presses[i].stick[k];
            if (presses[i].mouse[0]) __atomic_fetch_add(&script_mouse[0], presses[i].mouse[0], __ATOMIC_RELAXED);
            if (presses[i].mouse[1]) __atomic_fetch_add(&script_mouse[1], presses[i].mouse[1], __ATOMIC_RELAXED);
        }
    host_stick_read(stick);
    host_drag_read(stick);
}

/* (host/oot_menu.c) presses from the host, in the script's syntax ("0:A/100"), from now: the game's pause
   menu's clicks. Any thread; the next read takes them */
static SRWLOCK tap_lock = SRWLOCK_INIT;
static char tap_text[256];
void hos_hid_tap(const char *press) {
    AcquireSRWLockExclusive(&tap_lock);
    const size_t n = strlen(tap_text);
    if (n + strlen(press) + 2 < sizeof tap_text) snprintf(tap_text + n, sizeof tap_text - n, "%s%s", n ? "," : "", press);
    ReleaseSRWLockExclusive(&tap_lock);
}
/* a stick from the host (the pause menu's map: a drag pans, the wheel zooms): the four axes (left x, y,
   right x, y; +-32767) until hold_ms from now, the latest call's */
static volatile LONG host_stick[4];
static volatile LONG64 host_stick_until;
void hos_hid_stick(int lx, int ly, int rx, int ry, int hold_ms) {
    InterlockedExchange(&host_stick[0], lx), InterlockedExchange(&host_stick[1], ly);
    InterlockedExchange(&host_stick[2], rx), InterlockedExchange(&host_stick[3], ry);
    InterlockedExchange64(&host_stick_until, hos_now_ns() + (int64_t)hold_ms * 1000000);
}
static void host_stick_read(int32_t stick[4]) {
    if (hos_now_ns() >= InterlockedCompareExchange64(&host_stick_until, 0, 0)) return;
    {   /* (HOS_MENU_TRACE: the stick as the game reads it, at most 4 a second) */
        static int trace = -1;
        static int64_t logged;
        if (trace < 0) trace = getenv("HOS_MENU_TRACE") != NULL;
        if (trace && hos_now_ns() - logged > 250000000)
            logged = hos_now_ns(), hos_log("hid: the host's stick %ld %ld %ld %ld read", (long)host_stick[0], (long)host_stick[1],
                                          (long)host_stick[2], (long)host_stick[3]);
    }
    for (int i = 0; i < 4; i++) {
        const int32_t v = (int32_t)host_stick[i];
        if ((v < 0 ? -v : v) > (stick[i] < 0 ? -stick[i] : stick[i])) stick[i] = v;
    }
}
static void host_taps(void) {
    char text[sizeof tap_text];
    AcquireSRWLockExclusive(&tap_lock);
    memcpy(text, tap_text, sizeof text);
    tap_text[0] = 0;
    ReleaseSRWLockExclusive(&tap_lock);
    if (text[0]) parse_presses(text, script_elapsed_ms(hos_now_ns()), 2);
}

static void stick_max(int32_t stick[4], const int32_t v[4]) {
    for (int i = 0; i < 4; i++)
        if ((v[i] < 0 ? -v[i] : v[i]) > (stick[i] < 0 ? -stick[i] : stick[i])) stick[i] = v[i];
}

/* ---- (hookshot) the controls: the gamepad input (by position) and the keys that press each Switch button, from
   triforce_options.ini beside the executable when it has them: pad_<button>=<HOS_PAD_* position, -1 none> and
   key_<button>=<key code>,<key code> (Windows key codes, 0 none), <button> one of bind_names. Read once, at the
   first use; what the file leaves out keeps its default. Keys only, after the Switch's buttons (HOS_KEY_*): the left
   stick's and the camera's directions; then the ocarina's five note controls ((Triforce) 11-24), which take a gamepad
   input too. A key can be a mouse button (1 2 4 5 6: left, right, middle, 4, 5), which counts
   only while the mouse is captured; 4 and 5 also while one of the game's menus has it (mouse_buttons_arm) ---- */
static const char *const bind_names[HOS_KEY_N] = {"a", "b", "x", "y", "ls", "rs", "l", "r", "zl", "zr", "plus",
                                                  "minus", "left", "up", "right", "down", "move_up", "move_down",
                                                  "move_left", "move_right", "cam_up", "cam_down", "cam_left",
                                                  "cam_right", "note_l", "note_r", "note_a", "note_y", "note_x",
                                                  "toggle_hud"};
static const signed char pad_default[HOS_SW_N] = {
    HOS_PAD_EAST, HOS_PAD_SOUTH, HOS_PAD_NORTH, HOS_PAD_WEST, HOS_PAD_LSTICK, HOS_PAD_RSTICK, HOS_PAD_LSHOULDER,
    HOS_PAD_RSHOULDER, HOS_PAD_LTRIGGER, HOS_PAD_RTRIGGER, HOS_PAD_START, HOS_PAD_BACK, HOS_PAD_LEFT, HOS_PAD_UP,
    HOS_PAD_RIGHT, HOS_PAD_DOWN};
/* ((Triforce) 11-24) the ocarina's note rows: a gamepad input and two keys each, none out of the box (the game's own
   buttons play until a row is bound), and outside the other rows' rule that one input presses one control: a note's
   input can be some other control's at once, and is the note's alone while the game waits for a note (oc_notes) */
static int is_note_row(int i) { return i >= HOS_KEY_OC_NOTE_L && i <= HOS_KEY_OC_NOTE_X; }
/* ((Triforce) the Toggle HUD row: a gamepad input and two keys of its own, none out of the box, outside the rule that one
   input presses one control: an input it has is its alone while it has it (the other row keeps it, and has it again once
   Toggle HUD is cleared or bound elsewhere: hud_shortcut) */
static int is_hud_row(int i) { return i == HOS_KEY_TOGGLE_HUD; }
static int has_pad(int i) { return i < HOS_SW_N || is_note_row(i) || is_hud_row(i); }
/* (a mouse button bound to a note row would be seen by nobody: oc_notes never reads the mouse) */
static int is_mouse_vk(int vk) { return vk == VK_LBUTTON || vk == VK_RBUTTON || vk == VK_MBUTTON || vk == 0x05 || vk == 0x06; }
/* (the keys of totk-pc-recomp's docs/controls.md, github.com/valentderah/totk-pc-recomp, MIT; Plus is Tab alone: see
   the note in the table; the mouse's left button Y, attack, and right button ZL, shield and lock-on, as before; WASD the
   left stick, the arrows or IJKL the camera) */
static const unsigned char key_default[HOS_KEY_N][2] = {
    {'E'}, {VK_SHIFT}, {VK_SPACE}, {VK_LBUTTON}, {VK_CONTROL}, {'C'}, {'Q'}, {'R'}, {'Z', VK_RBUTTON}, {'X', 'F'},
    /* (Plus: Tab alone. Enter is the key Steam Input's Desktop layout sends for a pad's A when the game is started
       outside Steam (as on the Steam Deck in Desktop Mode), and other controller software does the same, so every A
       press also opened the game's pause menu. Enter was the second key until options_version 10: binds_load moves a
       file's old default pair away, and a player's own choice is kept) */
    {VK_TAB}, {'M'}, {'1'}, {'2'}, {'3'}, {'4'}, {'W'}, {'S'}, {'A'}, {'D'}, {VK_UP, 'I'}, {VK_DOWN, 'K'},
    {VK_LEFT, 'J'}, {VK_RIGHT, 'L'}, {0}, {0}, {0}, {0}, {0},   /* (the five note rows start unset: oc_pad_word) */
    {0}};   /* ((Triforce) Toggle HUD: unset) */
/* (the menu changes them as the game reads them. pad_bind: -1 for the keys-only controls, !has_pad, and for a note row
   with no gamepad input. ((Triforce) 11-24) Two gamepad inputs a Switch button, either presses it (the Controls page's Input 1
   and Input 2: pad_<button>=<input>[,<input>]); a note row has its first alone) */
static volatile LONG pad_bind[HOS_KEY_N][2], key_bind[HOS_KEY_N][2];
/* ((Triforce) the gamepad inputs Toggle HUD has, 1 << HOS_PAD_*: no other control's while it has them, hud_shortcut) */
static uint64_t hud_pad_mask(void) {
    uint64_t m = 0;
    for (int k = 0; k < 2; k++) {
        const int p = (int)pad_bind[HOS_KEY_TOGGLE_HUD][k];
        if (hos_pad_bindable(p)) m |= 1ULL << p;
    }
    return m;
}
/* ---- ((Triforce) 11-24) the ocarina's five note controls, driven by the wait the lifted game reports
   (nx2/oot_patches.py patch_ocarina_wait: the note-wait action's start and tick) ---- */
volatile uint64_t hos_oc_note_bits;   /* (the note rows held at the last read: bit i, HOS_KEY_OC_NOTE_L + i) */
volatile int hos_oc_wait;             /* (0 no wait; 1 the game waits for a note button; 2 it waits another way) */
volatile int hos_oc_last_kind;        /* (the wait action's input kind, as it began) */
volatile unsigned hos_oc_beat;        /* (stamped by the wait action's tick: a wait nobody ticks is not a wait) */
static LONG oc_consumed_keys[256];    /* (the keys that are notes at this read, no other control's: bound_down) */
static uint64_t oc_consumed_pads;     /* (the same for the gamepads' inputs, 1 << HOS_PAD_*: bound_pad_buttons) */
static int oc_live;                   /* (oc_notes ran this read with a button wait on: oc_pad_word) */
/* ((Triforce) 11-24) hold-to-toggle (hold_toggle.h): the latches, npad_states' alone, and a reset asked from any thread:
   the Insert menu or one of the game's menus opened, the window lost the focus, a control was bound again */
static volatile LONG toggle_reset;
static HoldToggle toggles;
static uint64_t host_taps_now;   /* (read_input: the host's own presses of this read, in its buttons too) */
void hos_input_clear_toggles(void) { InterlockedExchange(&toggle_reset, 1); }

static void binds_default(void) {
    hos_input_clear_toggles();
    for (int i = 0; i < HOS_KEY_N; i++) {
        InterlockedExchange(&pad_bind[i][0], i < HOS_SW_N ? pad_default[i] : -1);   /* (the note rows: -1, unset) */
        InterlockedExchange(&pad_bind[i][1], -1);
        for (int k = 0; k < 2; k++) InterlockedExchange(&key_bind[i][k], key_default[i][k]);
    }
}

static void binds_load(void) {
    static volatile LONG state;   /* 0 not read, 1 being read, 2 read */
    if (state == 2) return;
    if (InterlockedCompareExchange(&state, 1, 0) != 0) {
        while (state != 2) Sleep(0);
        return;
    }
    binds_default();
    char path[MAX_PATH];
    const DWORD len = hos_game_path_a(path, MAX_PATH);
    char *slash = len ? (strrchr(path, 92) ? strrchr(path, 92) : strrchr(path, 47)) : NULL;   /* (linux: '/') */
    FILE *f = NULL;
    if (slash) {
        snprintf(slash + 1, (size_t)(path + MAX_PATH - slash - 1), "triforce_options.ini");
        f = fopen(path, "r");
    }
    int changed = 0;
    if (f) {
        char line[80];
        int version = 0, had_keys = 0;   /* (options_version: 3 since the mouse's buttons are bindings) */
        while (fgets(line, sizeof line, f)) {
            char *eq = strchr(line, '=');
            if (!eq) continue;
            *eq = 0;
            if (!strcmp(line, "options_version")) version = atoi(eq + 1);
            const int pad = !strncmp(line, "pad_", 4), keys = !strncmp(line, "key_", 4);
            had_keys |= keys;
            for (int i = 0; (pad || keys) && i < HOS_KEY_N; i++) {
                if (strcmp(line + 4, bind_names[i]) || (pad && !has_pad(i))) continue;
                changed++;
                if (pad) {
                    const char *comma = strchr(eq + 1, ',');
                    const int v = atoi(eq + 1), w = comma && i < HOS_SW_N ? atoi(comma + 1) : -1;
                    pad_bind[i][0] = hos_pad_bindable(v) ? v : -1;
                    pad_bind[i][1] = hos_pad_bindable(w) && w != pad_bind[i][0] ? w : -1;
                } else {
                    const char *comma = strchr(eq + 1, ',');
                    const int a = atoi(eq + 1), b = comma ? atoi(comma + 1) : 0;
                    const int note = is_note_row(i);   /* (a note is a key or a gamepad input, never a mouse click) */
                    key_bind[i][0] = a > 0 && a < 256 && !(note && is_mouse_vk(a)) ? a : 0;
                    key_bind[i][1] = b > 0 && b < 256 && !(note && is_mouse_vk(b)) ? b : 0;
                }
            }
        }
        fclose(f);
        /* An options file from before version 3 wrote key_y and key_zl without the mouse's buttons, which pressed Y and ZL
           by themselves then: they go into the second slot when it is empty and no other control has them */
        if (version < 3 && had_keys) {
            static const int mouse_to[2][2] = {{HOS_SW_Y, VK_LBUTTON}, {HOS_SW_ZL, VK_RBUTTON}};
            for (int m = 0; m < 2; m++) {
                int taken = 0;
                for (int i = 0; i < HOS_KEY_N; i++)
                    for (int k = 0; k < 2; k++) taken |= key_bind[i][k] == mouse_to[m][1];
                if (!taken && !key_bind[mouse_to[m][0]][1]) key_bind[mouse_to[m][0]][1] = mouse_to[m][1];
            }
        }
        /* Plus was Tab and Enter until options_version 10. Enter is the key controller software (Steam Input's Desktop
           layout, for one) sends for a pad's A, so every A press also opened the game's pause menu: a file's old default
           pair, exactly, moves to Tab alone. A file whose Plus is anything else was chosen and is kept, as is the pair in
           a file of version 10 or later (chosen in the Controls page since). The menu's next save writes it and the
           version (gpu/vk/vk_menu.cpp save) */
        if (version < 10 && key_bind[HOS_SW_PLUS][0] == VK_TAB && key_bind[HOS_SW_PLUS][1] == VK_RETURN) {
            key_bind[HOS_SW_PLUS][1] = 0;
            hos_log("hid: Plus is Tab alone: Enter, which controller software sends for a pad's A, is no longer its "
                    "second key (the Controls page can put it back)");
        }
    }
    if (changed) hos_log("hid: %d controls from triforce_options.ini", changed);
    InterlockedExchange(&state, 2);
}
int hos_binding(int set, int button, int slot) {
    binds_load();
    if (button < 0 || button >= HOS_KEY_N || slot < 0 || slot > 1)
        return set == HOS_BIND_PAD ? -1 : 0;
    return set == HOS_BIND_PAD ? (int)pad_bind[button][slot] : (int)key_bind[button][slot];
}
/* A gamepad input bound where another has it trades places with the input it replaces; into an empty slot it is taken from
   the other only when that one keeps a gamepad input of its own (no button is left without one: else nothing changes). A
   key moved to it is taken from the others. ((Triforce) 11-24) The ocarina's note rows are outside both rules: they take
   nothing and nothing is taken from them, so one input can be a note and its other control at once (the note wait has it as
   a note alone, oc_notes); they have one gamepad input, slot 0 */
void hos_bind(int set, int button, int slot, int code) {
    binds_load();
    hos_input_clear_toggles();
    if (button < 0) {
        binds_default();
        return;
    }
    if (button >= HOS_KEY_N || slot < 0 || slot > 1) return;
    if (set == HOS_BIND_PAD) {
        if (!has_pad(button) || (slot && button >= HOS_SW_N) || (code != -1 && !hos_pad_bindable(code))) return;
        const LONG old = pad_bind[button][slot];
        if (button < HOS_SW_N && code >= 0 && code != old) {   /* (among the Switch's buttons; the note rows keep theirs) */
            for (int i = 0; i < HOS_SW_N; i++)
                for (int k = 0; k < 2; k++)
                    if (pad_bind[i][k] == code && old < 0 && pad_bind[i][1 - k] < 0) return;   /* (its only input: kept) */
            for (int i = 0; i < HOS_SW_N; i++)
                for (int k = 0; k < 2; k++) {
                    if (pad_bind[i][k] != code) continue;
                    if (old >= 0) InterlockedExchange(&pad_bind[i][k], old);
                    else if (k == 0) InterlockedExchange(&pad_bind[i][0], pad_bind[i][1]), InterlockedExchange(&pad_bind[i][1], -1);
                    else InterlockedExchange(&pad_bind[i][1], -1);
                }
        }
        InterlockedExchange(&pad_bind[button][slot], code);
    } else {
        if (code < 0 || code > 255) return;
        if (is_note_row(button) && is_mouse_vk(code)) return;   /* (a note is a key or a gamepad input, never a mouse click) */
        for (int i = 0; i < HOS_KEY_N && !is_note_row(button) && !is_hud_row(button); i++)
            for (int k = 0; k < 2 && !is_note_row(i) && !is_hud_row(i); k++)
                if (code && key_bind[i][k] == code) InterlockedExchange(&key_bind[i][k], 0);
        InterlockedExchange(&key_bind[button][slot], code);
    }
}

/* ---- ((Triforce) the Controls page's per-control reset and its confirmed rebinds, MkwVkHost 22) ----
   hos_binding_is_default: whether a control's bindings are its defaults (a Switch button: its gamepad input as pad_default,
   no Input 2; the keys as key_default; a note row: none). hos_reset_binding: those defaults back for that control alone, 0
   (nothing changed) when another control has one of its defaults: a reset takes nothing from another control (the note rows
   share as ever). hos_rebind_control: hos_bind's change, made only when the controls it would take the input from (a bit
   each, HOS_SW_* / HOS_KEY_*: conflicts) are the ones the player agreed to (approved); 0 and nothing changed otherwise, or
   when hos_bind would refuse it (a button's only gamepad input stays with it). The rules are hos_bind's: a gamepad input
   trades places with the one it replaces; a key is taken from the others */
int hos_binding_is_default(int button) {
    binds_load();
    if (button < 0 || button >= HOS_KEY_N) return 1;
    const int pad = button < HOS_SW_N ? pad_default[button] : -1;
    return pad_bind[button][0] == pad && pad_bind[button][1] == -1 && key_bind[button][0] == key_default[button][0] &&
           key_bind[button][1] == key_default[button][1];
}

int hos_reset_binding(int button) {
    binds_load();
    if (button < 0 || button >= HOS_KEY_N) return 0;
    const int pad = button < HOS_SW_N ? pad_default[button] : -1, first = key_default[button][0], second = key_default[button][1];
    for (int i = 0; i < HOS_KEY_N; i++) {
        if (i == button) continue;
        for (int k = 0; k < 2; k++) {
            const int key = key_bind[i][k];
            if ((pad >= 0 && i < HOS_SW_N && pad_bind[i][k] == pad) ||
                (key && (key == first || key == second) && !is_note_row(i) && !is_note_row(button)))
                return 0;
        }
    }
    hos_input_clear_toggles();
    InterlockedExchange(&pad_bind[button][0], pad);
    InterlockedExchange(&pad_bind[button][1], -1);
    InterlockedExchange(&key_bind[button][0], first);
    InterlockedExchange(&key_bind[button][1], second);
    return 1;
}

int hos_rebind_control(int set, int button, int slot, int code, uint64_t approved, uint64_t *conflicts) {
    binds_load();
    *conflicts = 0;
    if (button < 0 || button >= HOS_KEY_N || slot < 0 || slot > 1) return 0;
    if (set == HOS_BIND_PAD) {
        if (!has_pad(button) || (slot && button >= HOS_SW_N) || code < 0 || !hos_pad_bindable(code)) return 0;
        const LONG old = pad_bind[button][slot];
        if (button < HOS_SW_N && code != old) {   /* (as hos_bind: among the Switch's buttons; the note rows keep theirs) */
            for (int i = 0; i < HOS_SW_N; i++)
                for (int k = 0; k < 2; k++)
                    if (pad_bind[i][k] == code && old < 0 && pad_bind[i][1 - k] < 0) return 0;   /* (its only input: kept) */
            for (int i = 0; i < HOS_SW_N; i++)
                if (i != button && (pad_bind[i][0] == code || pad_bind[i][1] == code)) *conflicts |= 1ull << i;
        }
    } else {
        if (set != HOS_BIND_KEY || code <= 0 || code > 255 || (is_note_row(button) && is_mouse_vk(code))) return 0;
        for (int i = 0; i < HOS_KEY_N && !is_note_row(button); i++)
            if (i != button && !is_note_row(i) && (key_bind[i][0] == code || key_bind[i][1] == code)) *conflicts |= 1ull << i;
    }
    if (*conflicts && *conflicts != approved) return 0;
    if (set == HOS_BIND_PAD) hos_bind(set, button, slot, code);
    else hos_bind(set, button, 0, code), hos_bind(set, button, 1, 0);   /* (as the page binds a key: the one key) */
    return 1;
}

/* (the pads' inputs the Insert menu had, pad_raw_now's bits: each waits until let go, read_input; (Triforce) 11-24: the
   ocarina's note layer leaves them out too, oc_notes) */
static uint64_t pad_after_menu;
static volatile LONG pad_raw_now;   /* the gamepads' inputs at the last read, 1 << HOS_PAD_* */
static uint64_t pad_raw_game;       /* (pads_read: the last read's inputs without the menu's Back+Start chord) */
uint32_t hos_pad_raw(void) { return (uint32_t)pad_raw_now; }

/* A stick axis cut at the dead zone, as XInput's and SDL's pads both are (pad_sdl.c): zone is the Insert menu's "Stick
   dead zone" (option 11), 0 XInput's own 7849 (~24%, the only one before issue 752), 1 to 5 5%, 10%, 15%,
   20%, 30%. Per axis, as before: the game's own dead zone still follows */
int32_t hos_stick_axis(int16_t v, int zone) {
    static const int32_t cut[6] = {7849, 1638, 3277, 4915, 6553, 9830};
    const int32_t a = v < -32767 ? -32767 : v, t = cut[(unsigned)zone < 6 ? zone : 0];
    return (a > t || a < -t) ? a : 0;
}
/* (Triforce, after NX2navi's lstick_deadzone and rstick_deadzone) A stick's own dead zone, the Insert menu's "Left stick
   dead zone" and "Right stick dead zone" (stick 0 the left, 1 the right): -1 none of its own, "As Stick dead zone", the
   default; else 0 to 50, percent of an axis's travel. The option is one more than the row's value, so that 0, which is
   also what an option table that does not know the rows answers, is none of its own. */
int hos_stick_own(int stick) {
    const int v = rx_option(stick ? HOS_OPT_RSTICK_ZONE : HOS_OPT_LSTICK_ZONE, 0) - 1;
    return v < 0 ? -1 : v > 50 ? 50 : v;
}
/* An axis cut at its stick's dead zone: the stick's own (own, percent: 5 cuts where the Stick dead zone row's 5% does)
   or, when it has none (-1), the menu's Stick dead zone (zone), which is hos_stick_axis as it was. Per axis and with no
   rescaling of the travel left, as that row: the game's own dead zone still follows. 0 cuts nothing. */
int32_t hos_stick_axis_own(int16_t v, int zone, int own) {
    if (own < 0) return hos_stick_axis(v, zone);
    const int32_t a = v < -32767 ? -32767 : v, t = ((own > 50 ? 50 : own) * 32767 + 50) / 100;
    return (a > t || a < -t) ? a : 0;
}

/* (Triforce) A stick cut at its dead zone as a pair, for XInput's and SDL's pads: inside the circle of the zone both
   axes are 0, outside it both pass as they are, so a push keeps its direction. Cut axis by axis, (12000, -4000) reached
   the game as (12000, 0): a diagonal snapped towards the horizontal, and at full tilt every direction within 14 degrees
   of an axis was that axis. The circle's radius is where hos_stick_axis_own cuts one axis (the stick's own zone, or
   with none, -1, the Stick dead zone's), so along an axis every input gives what it gave before, and a zone of 0 cuts
   nothing. tests/test_stick_dead_zone.py */
void hos_filter_stick(int16_t x, int16_t y, int zone, int own, int32_t out[2]) {
    static const int32_t cut[6] = {7849, 1638, 3277, 4915, 6553, 9830};
    const int32_t a = x < -32767 ? -32767 : x, b = y < -32767 ? -32767 : y;
    const int32_t t = own < 0 ? cut[(unsigned)zone < 6 ? zone : 0] : ((own > 50 ? 50 : own) * 32767 + 50) / 100;
    const int active = a * a + b * b > t * t;   /* (both are clamped to 32767, so the sum fits in an int32_t) */
    out[0] = active ? a : 0;
    out[1] = active ? b : 0;
}

/* (Triforce) XInput's controllers, read on a thread of their own (xinput_main), never on the game's: XInputGetState on
   a slot with no controller in it is slow (it looks for the device again, a millisecond or more, longer with Bluetooth
   or a virtual pad's driver installed), and with no controller SDL reads, the game's input read asked all four empty
   slots each second, in one read. Players on a keyboard and mouse got that hitch every second, and a controller
   plugged in "raised the frame rate". pads_read now takes the thread's last reading. */
static volatile int xinput_was[XUSER_MAX_COUNT];   /* (the slots XInput had a controller in when last asked) */
static volatile int xinput_pads_now;               /* (xinput_poll: XInput has a controller, while it is polled) */
static void xinput_any(void) {
    int any = 0;
    for (int q = 0; q < XUSER_MAX_COUNT; q++) any |= xinput_was[q];
    xinput_pads_now = any;
}
/* ((Triforce, 11-24) XInput's triggers, by SDL's rule (host/pad_sdl.c trigger_pull): slot p's trigger t (0 left, 1 right)
   at its reading a (0 to 255) presses only once it has read let go (64 or below, the press threshold) for a second
   without a break since its controller was connected. A device whose trigger reads held for good held ZL or ZR for
   every pad here too, when XInput's pads are the ones read (SDL has none, or HOS_XINPUT=1). The second is counted over
   polls that follow each other: after a time without polls (SDL had the pads) it starts again. now: this poll's time;
   fresh: the slot was just connected. Only xinput_poll's thread calls it */
#define XINPUT_TRIGGER_REST_NS 1000000000LL
static int xinput_trigger(int p, int t, int a, int64_t now, int fresh) {
    static int64_t rest_ns[XUSER_MAX_COUNT][2], seen_ns[XUSER_MAX_COUNT][2];
    static unsigned char counts[XUSER_MAX_COUNT][2], said[XUSER_MAX_COUNT][2];
    static int64_t connected_ns[XUSER_MAX_COUNT];
    if (fresh) { counts[p][t] = 0; rest_ns[p][t] = 0; said[p][t] = 0; connected_ns[p] = now; }
    if (now - seen_ns[p][t] > 250000000LL) rest_ns[p][t] = 0;   /* (not polled meanwhile: not "without a break") */
    seen_ns[p][t] = now;
    if (a > 64) {
        rest_ns[p][t] = 0;
    } else {
        if (!rest_ns[p][t]) rest_ns[p][t] = now;
        if (now - rest_ns[p][t] >= XINPUT_TRIGGER_REST_NS) counts[p][t] = 1;
    }
    if (!counts[p][t] && a > 64 && !said[p][t] && now - connected_ns[p] >= 3000000000LL) {
        said[p][t] = 1;
        hos_log("hid: controller %d: its %s trigger reads %d of 255 and has not read let go for a second since it was "
                "connected, so it does not count until it does", p, t ? "right" : "left", a);
    }
    return counts[p][t] && a > 64;
}
static void xinput_poll(int64_t now, uint64_t *out_raw, int32_t s[4]) {
    static int64_t retry[XUSER_MAX_COUNT];
    uint64_t raw = 0;
#ifdef __EMSCRIPTEN__
    xinput_get = XInputGetState;
#endif
    if (!xinput_get) {
        static int64_t load_retry;
        if (now >= load_retry) {
            load_retry = now + 5000000000LL;
#ifdef _WIN32   /* (hookshot: System32's, not one beside the game, in the current folder or on PATH) */
            HMODULE x = LoadLibraryExA("xinput1_4.dll", NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
            if (!x) x = LoadLibraryExA("xinput9_1_0.dll", NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
#else
            HMODULE x = LoadLibraryA("xinput1_4.dll");
            if (!x) x = LoadLibraryA("xinput9_1_0.dll");
#endif
            if (x) xinput_get = (XInputGetStateFn)GetProcAddress(x, "XInputGetState");
        }
    }
    static const struct { WORD x; int b; } map[] = {
        {XINPUT_GAMEPAD_A, HOS_PAD_SOUTH}, {XINPUT_GAMEPAD_B, HOS_PAD_EAST}, {XINPUT_GAMEPAD_X, HOS_PAD_WEST},
        {XINPUT_GAMEPAD_Y, HOS_PAD_NORTH}, {XINPUT_GAMEPAD_LEFT_THUMB, HOS_PAD_LSTICK},
        {XINPUT_GAMEPAD_RIGHT_THUMB, HOS_PAD_RSTICK}, {XINPUT_GAMEPAD_LEFT_SHOULDER, HOS_PAD_LSHOULDER},
        {XINPUT_GAMEPAD_RIGHT_SHOULDER, HOS_PAD_RSHOULDER}, {XINPUT_GAMEPAD_START, HOS_PAD_START},
        {XINPUT_GAMEPAD_BACK, HOS_PAD_BACK}, {XINPUT_GAMEPAD_DPAD_LEFT, HOS_PAD_LEFT},
        {XINPUT_GAMEPAD_DPAD_UP, HOS_PAD_UP}, {XINPUT_GAMEPAD_DPAD_RIGHT, HOS_PAD_RIGHT},
        {XINPUT_GAMEPAD_DPAD_DOWN, HOS_PAD_DOWN}};
    for (int p = 0; p < XUSER_MAX_COUNT && xinput_get; p++) {
        if (now < retry[p]) continue;
        XINPUT_STATE xs;
        if (xinput_get((DWORD)p, &xs) != ERROR_SUCCESS) {
            if (xinput_was[p]) hos_log("hid: controller %d disconnected", p);
            xinput_was[p] = 0;
            xinput_any();
            retry[p] = now + 1000000000LL;
            continue;
        }
        const int fresh = !xinput_was[p];
        if (fresh) hos_log("hid: controller %d connected", p);
        xinput_was[p] = 1;
        xinput_pads_now = 1;
        const WORD w = xs.Gamepad.wButtons;
        for (unsigned i = 0; i < sizeof map / sizeof *map; i++)
            if (w & map[i].x) raw |= 1ULL << map[i].b;
        if (xinput_trigger(p, 0, xs.Gamepad.bLeftTrigger, now, fresh)) raw |= 1ULL << HOS_PAD_LTRIGGER;
        if (xinput_trigger(p, 1, xs.Gamepad.bRightTrigger, now, fresh)) raw |= 1ULL << HOS_PAD_RTRIGGER;
        const int16_t thumb[4] = {xs.Gamepad.sThumbLX, xs.Gamepad.sThumbLY, xs.Gamepad.sThumbRX, xs.Gamepad.sThumbRY};
        int32_t v[4];
        int rx_option(int id, int otherwise);
        const int zone = rx_option(11, 0);   /* (the menu's Stick dead zone) */
        const int own[2] = {hos_stick_own(0), hos_stick_own(1)};   /* ((Triforce) each stick's own, -1 none) */
        hos_filter_stick(thumb[0], thumb[1], zone, own[0], v);       /* (each stick as a pair: its direction kept) */
        hos_filter_stick(thumb[2], thumb[3], zone, own[1], v + 2);
        if (rx_option(16, 0)) v[2] = -v[2];
        if (rx_option(17, 0)) v[3] = -v[3];
        stick_max(s, v);
    }
    *out_raw |= raw;
}

static SRWLOCK xinput_lock = SRWLOCK_INIT;
static uint64_t xinput_raw;              /* (xinput_main's last reading, by position: 1 << HOS_PAD_*) */
static int32_t xinput_stick[4];
static volatile int64_t xinput_wanted_ns;   /* (pads_read wanted XInput's pads then: SDL had none, or HOS_XINPUT=1) */
#define XINPUT_WANTED_NS 100000000LL        /* (wanted this recently: the thread reads) */

static void xinput_publish(uint64_t raw, const int32_t s[4]) {
    AcquireSRWLockExclusive(&xinput_lock);
    xinput_raw = raw;
    memcpy(xinput_stick, s, sizeof xinput_stick);
    ReleaseSRWLockExclusive(&xinput_lock);
}

#ifndef __EMSCRIPTEN__
/* every 2 ms while a controller is there (pads_read's own pace), every 100 ms while none is (an empty slot is asked
   again each second); nothing while SDL has the pads */
static DWORD WINAPI xinput_main(void *arg) {
    (void)arg;
    void hos_host_thread_register_self(const char *name);   /* (mkw_glue.c: the thread's name) */
    hos_host_thread_register_self("gamepads (XInput)");
    for (;;) {
        const int64_t now = hos_now_ns();
        uint64_t raw = 0;
        int32_t s[4] = {0};
        const int wanted = now - __atomic_load_n(&xinput_wanted_ns, __ATOMIC_RELAXED) < XINPUT_WANTED_NS;
        if (wanted) xinput_poll(now, &raw, s);
        xinput_publish(raw, s);   /* (not wanted: nothing held, so a reading from before SDL took over never comes back) */
        Sleep(wanted && xinput_pads_now ? 2 : 100);
    }
    return 0;
}
#endif

/* XInput's pads into raw and s: the thread's last reading (started at the first ask), or read here where there are
   no threads */
static void xinput_read(int64_t now, uint64_t *raw, int32_t s[4]) {
    __atomic_store_n(&xinput_wanted_ns, now, __ATOMIC_RELAXED);
#ifdef __EMSCRIPTEN__
    xinput_poll(now, raw, s);
#else
    static volatile LONG started;
    if (!started && !InterlockedExchange(&started, 1)) {
        HANDLE h = CreateThread(NULL, 0, xinput_main, NULL, 0, NULL);
        if (h) CloseHandle(h);
    }
    int32_t v[4];
    AcquireSRWLockShared(&xinput_lock);
    *raw |= xinput_raw;
    memcpy(v, xinput_stick, sizeof v);
    ReleaseSRWLockShared(&xinput_lock);
    stick_max(s, v);
#endif
}

/* The Switch's buttons the gamepads' inputs press (raw: 1 << HOS_PAD_*), by the Controls page's bindings */
static uint64_t bound_pad_buttons(uint64_t raw) {
    binds_load();
    uint64_t b = 0;
    raw &= ~oc_consumed_pads;   /* ((Triforce) 11-24: an input that is an ocarina note at this read is no button's: oc_notes) */
    raw &= ~hud_pad_mask();     /* ((Triforce) Toggle HUD's alone) */
    for (int i = 0; i < HOS_SW_N; i++)
        for (int k = 0; k < 2; k++)   /* ((Triforce) 11-24: either of its two inputs) */
            if (pad_bind[i][k] >= 0 && (raw >> pad_bind[i][k] & 1)) b |= 1ULL << i;
    return b;
}

static void pads_read(uint64_t *buttons, int32_t stick[4]) {
    static int64_t next_read;
    static uint64_t cached_buttons;
    static int32_t cached_stick[4];
    const int64_t now = hos_now_ns();
    if (now < next_read) {
        *buttons |= cached_buttons;
        stick_max(stick, cached_stick);
        return;
    }
    next_read = now + 2000000;
    uint64_t raw = 0;   /* (by position: 1 << HOS_PAD_*) */
    int32_t s[4] = {0};
    int sdl_pads = 0;
    {   /* every controller SDL knows (DualSense, DualShock 4, Switch Pro, ...: hos/pad_sdl.c) */
        int hos_sdl_pads(uint64_t *buttons, int32_t stick[4]);
        static int was;
        const int n = hos_sdl_pads(&raw, s);
        if (n != was) hos_log("hid: %d controller%s through SDL", n, n == 1 ? "" : "s");
        was = n;
        sdl_pads = n;
    }
    /* Polling XInput alongside SDL causes double-reads and conflicting button mappings when Steam Input
       or controller wrappers emulate an XInput controller for a pad SDL is already reading (#1480, #1583).
       Only poll XInput when SDL has no open controllers, unless HOS_XINPUT=1 is explicitly requested. */
    static int poll_xinput_env = -1;
    if (poll_xinput_env < 0) poll_xinput_env = getenv("HOS_XINPUT") != NULL;
    if (!sdl_pads || poll_xinput_env) {
        xinput_read(now, &raw, s);
    } else if (xinput_get) {
        /* (Triforce, 11-12) SDL has the pads: XInput is only looked at, ten times a second, for the pads it had before
           SDL opened its own. A pad whose buttons XInput shows down while SDL shows none, 20 looks with no look between
           where SDL showed one: SDL's button input is not arriving (pad_sdl.c's SDL_JOYSTICK_THREAD), said once */
        static int64_t next_look;
        static int silent, said;
        if (!said && now >= next_look) {
            next_look = now + 100000000LL;
            const uint64_t triggers = 1ULL << HOS_PAD_LTRIGGER | 1ULL << HOS_PAD_RTRIGGER;
            for (int p = 0; p < XUSER_MAX_COUNT; p++) {
                if (!xinput_was[p]) continue;
                XINPUT_STATE xs;
                if (xinput_get((DWORD)p, &xs) != ERROR_SUCCESS) {
                    hos_log("hid: controller %d disconnected", p);
                    xinput_was[p] = 0;
                    xinput_any();
                    continue;
                }
                if (!xs.Gamepad.wButtons) continue;
                if (raw & ~triggers) {
                    silent = 0;
                    continue;
                }
                if (++silent >= 20) {
                    said = 1;
                    hos_log("hid: XInput shows controller %d's buttons down and SDL shows none, 20 times running: SDL's "
                            "button and stick input is not arriving (HOS_NO_SDL=1 in triforce_env.txt reads the "
                            "controllers through XInput alone)", p);
                    break;
                }
            }
        }
    }
    {   /* ((Triforce) 11-17) the menus' pad bits also say where the left stick is pushed, past half its travel (vk_api.h
           HOS_PAD_LS_*): the overlay's lists move by the stick as the game's do. Not the game's: raw itself is unchanged */
        uint64_t menu = raw;
        if (s[1] > 16384) menu |= 1ULL << HOS_PAD_LS_UP;
        if (s[1] < -16384) menu |= 1ULL << HOS_PAD_LS_DOWN;
        if (s[0] < -16384) menu |= 1ULL << HOS_PAD_LS_LEFT;
        if (s[0] > 16384) menu |= 1ULL << HOS_PAD_LS_RIGHT;
        if (s[3] > 16384) menu |= 1ULL << HOS_PAD_RS_UP;
        if (s[3] < -16384) menu |= 1ULL << HOS_PAD_RS_DOWN;
        InterlockedExchange(&pad_raw_now, (LONG)menu);
    }
    /* Back and Start together open the Insert menu (gpu/vk/vk_menu.cpp, for pads whose Home button the system
       keeps): they reach the game only one at a time */
    const uint64_t chord = 1ULL << HOS_PAD_BACK | 1ULL << HOS_PAD_START;
    if ((raw & chord) == chord) raw &= ~chord;
    pad_raw_game = raw;
    const uint64_t b = bound_pad_buttons(raw);
    cached_buttons = b;
    memcpy(cached_stick, s, sizeof s);
    *buttons |= b;
    stick_max(stick, s);
}

/* (Triforce) Whether XInput has a controller now, for the Button prompts row's Auto (host/prompts.c auto_face), which asks
   once, at the game's start, and only when SDL names none: a controller read through XInput alone (HOS_NO_SDL=1, no SDL
   beside the game, or one SDL had not opened yet) gets the Xbox's icons ((11-19) the Switch's before), XInput reading
   only pads of the Xbox's layout, and only a PC with no controller there gets the keys' or the last run's device's */
int hos_xinput_connected(void) {
    XInputGetStateFn get = xinput_get;
#ifdef _WIN32   /* (as pads_read: System32's) */
    if (!get) {
        HMODULE x = LoadLibraryExA("xinput1_4.dll", NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
        if (!x) x = LoadLibraryExA("xinput9_1_0.dll", NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
        if (x) get = (XInputGetStateFn)GetProcAddress(x, "XInputGetState");
    }
#endif
    for (DWORD p = 0; get && p < XUSER_MAX_COUNT; p++) {
        XINPUT_STATE xs;
        if (get(p, &xs) == ERROR_SUCCESS) return 1;
    }
    return 0;
}

/* Whether the controllers count while another window is in front: HOS_INPUT_BACKGROUND=1 or 0 decides when it is set,
   otherwise the Insert menu's "Controller in background" row */
static int pads_in_background(const char *env, int menu) {
    return env ? atoi(env) != 0 : menu != 0;
}
/* ((Triforce VR) vr_game.c: in the headset the window is seldom in front, so a gamepad counts beside the hand controllers */
int vr_session_on(void);

/* (hookshot) Whether a pad's motion counts: when its buttons do, with the game's window in front, or behind another
   window when the player asked for the pads there. Otherwise GetSixAxisSensorStates hands out the pad at rest, so a
   gyro moved while the player is in another window does not turn the camera. tests/test_motion_background.py */
static int motion_counts(int front, const char *env, int menu) {
    return front || pads_in_background(env, menu);
}

#ifndef VK_XBUTTON1
#define VK_XBUTTON1 0x05
#define VK_XBUTTON2 0x06
#endif
/* A mouse button counts only while the mouse is captured, and one held when the capture began only after it was let go
   (the click that captures never reaches the game). menu: one of the game's menus has the mouse (host/display.c
   hos_mouse_in_game_menu; Windows). Its left, right and middle buttons are that menu's clicks there; the side buttons
   are no menu's, so they stay their controls' as a key does: Mouse 4 on A confirmed nothing in the text box's choices */
static int mouse_vk_slot(int vk) {
    return vk == VK_LBUTTON ? 0 : vk == VK_RBUTTON ? 1 : vk == VK_MBUTTON ? 2 : vk == VK_XBUTTON1 ? 3 : vk == VK_XBUTTON2 ? 4 : -1;
}
static int mouse_armed[5];
static void mouse_buttons_arm(int captured, int menu) {   /* (once a read) */
    static const int vks[5] = {VK_LBUTTON, VK_RBUTTON, VK_MBUTTON, VK_XBUTTON1, VK_XBUTTON2};
    for (int i = 0; i < 5; i++) mouse_armed[i] = (captured || (menu && i >= 3)) && (mouse_armed[i] || !key(vks[i]));
}
/* (Triforce, after NX2navi's walk_key) The walk key's code, 0 none: the Insert menu's Walk key row, set at each read
   (read_input, walk_key_code). While a key is the walk key it is no control's key: Shift, by default B's, would press B
   with every walking step. What the Controls page binds it to is not touched, and counts again once the row is Off or
   on another key */
static int walk_vk;
/* whether a control's key is down: a key always (kmap_down: not Enter with Alt), a mouse button only with mouse (the
   mouse captured or a game menu's, and the button armed); the walk key never */
static int bound_down(int i, int mouse) {
    for (int k = 0; k < 2; k++) {
        const int vk = (int)key_bind[i][k];
        if (vk <= 0 || vk == walk_vk) continue;
        if (oc_consumed_keys[vk]) continue;   /* ((Triforce) 11-24: an ocarina note at this read, not this control: oc_notes) */
        if (!is_hud_row(i) && (vk == (int)key_bind[HOS_KEY_TOGGLE_HUD][0] || vk == (int)key_bind[HOS_KEY_TOGGLE_HUD][1]))
            continue;   /* ((Triforce) Toggle HUD's key: its alone while it has it) */
        const int m = mouse_vk_slot(vk);
        if (m >= 0 ? mouse && mouse_armed[m] && key(vk) : kmap_down(key_bind[i][k], key)) return 1;
    }
    return 0;
}

/* ((Triforce) The Controls page's Toggle HUD row: a press of its gamepad input or one of its keys hides the HUD in play, the
   next shows it again (host/hos_wide_ui.c hos_gameplay_hud_toggle: for the session). readable: the player's input counts at
   this read (not while the Insert menu is open, the window is behind, or a script or the benchmark has the input); mouse:
   a mouse button bound to it counts (bound_down). An input already down when it becomes readable (the press that closed the
   menu, a rebinding, the focus coming back) first has to be let go */
static void hud_shortcut(int readable, int mouse) {
    static int armed;
    if (!readable) {
        armed = 0;
        return;
    }
    const int down = (pad_raw_game & hud_pad_mask()) != 0 || bound_down(HOS_KEY_TOGGLE_HUD, mouse);
    if (down && armed) {
        void hos_gameplay_hud_toggle(void);
        hos_gameplay_hud_toggle();
    }
    armed = !down;
}

/* (Triforce, after NX2navi's walk_key and walk_scale) A key is down or up, so the movement keys push the left stick all
   the way and on the keyboard alone Link always runs. The walk key, while held with them, makes it a part of the way.
   The Insert menu's Walk key row's values, in its order: Off, then Caps Lock (no control's key by default), Shift (B's),
   Ctrl (the left stick press's) and Tab (one of Plus's). Alt is not among them: Windows takes an Alt let go alone for
   its window menu, and beeps at a key pressed with it (host/display.c hands both on to it) */
static int walk_key_code(int row) {
    static const int codes[] = {0, VK_CAPITAL, VK_SHIFT, VK_CONTROL, VK_TAB};
    return row > 0 && row < (int)(sizeof codes / sizeof *codes) ? codes[row] : 0;
}
/* The movement keys' left stick (keys[0] and keys[1], each -32767, 0 or 32767) while the walk key is held: percent, the
   Walk scale row's, of all the way, 20 to 90 (0 or less, as from an option table that does not know the row: 51, the
   row's default). Two keys at once push a diagonal: each axis then gets the scale over the square root of 2, so the
   stick is as far from its centre as with one key, the same walk in all eight directions (unscaled, two keys are the
   corner of the square, past the stick's round edge, as before). The camera's keys (keys[2], keys[3]) stay: a walk is
   the left stick's */
static void walk_keys(int32_t keys[4], int percent) {
    if (percent <= 0) percent = 51;
    if (percent < 20) percent = 20;
    if (percent > 90) percent = 90;
    const int both = keys[0] && keys[1];
    for (int k = 0; k < 2; k++) {
        keys[k] = keys[k] * percent / 100;
        if (both) keys[k] = keys[k] * 46341 / 65536;   /* (65536 over the square root of 2) */
    }
}

static uint64_t flight_input;
static uint64_t free_camera_axes;
static int free_camera_height;
static int move_stick_held;   /* ((Triforce) the left stick pushed, as the game got it: hos_move_stick_held) */

/* ((Triforce) host/hos_main.c hos_oot_cct_speed, the Debug tab's Movement speed tool) 1 while the left stick the game was
   last given is pushed past an eighth of its travel: the player steers Link */
int hos_move_stick_held(void) { return __atomic_load_n(&move_stick_held, __ATOMIC_RELAXED); }

uint64_t hos_flight_input(void) {
    return __atomic_load_n(&flight_input, __ATOMIC_RELAXED);
}

uint64_t hos_free_camera_input(int *height) {
    *height = __atomic_load_n(&free_camera_height, __ATOMIC_RELAXED);
    return __atomic_load_n(&free_camera_axes, __ATOMIC_RELAXED);
}

/* ((Triforce, 11-24) The no-clip flight's Jump, as the game has it: X, or B with its Swap Jump Controls (host/flight_jump.h;
   Link's update reads the option, host/hos_main.c). It was B always, which this game's Jump is not by default, so a
   double-tap of Jump never took off. HOS_FLIGHT_JUMP=B: B always, as before) */
static uint64_t flight_jump(void) {
    extern volatile int hos_oot_jump_swapped;
    static int mode = -1;
    if (mode < 0) {
        mode = flight_jump_mode_env(getenv("HOS_FLIGHT_JUMP"));
        if (mode != FLIGHT_JUMP_GAME)
            hos_log("hid: no-clip flight takes off with %s, whatever the game's Swap Jump Controls says (HOS_FLIGHT_JUMP)",
                    mode == FLIGHT_JUMP_ALWAYS_B ? "B" : "X");
    }
    return flight_jump_bit(mode, __atomic_load_n(&hos_oot_jump_swapped, __ATOMIC_RELAXED));
}

static int flight_jump_shortcut(uint64_t *buttons, int mode, int menu_open, int free_camera) {
    int hos_oot_flight_shortcut_ready(void);
    static int64_t first_press;
    static int held, consume_jump;
    const uint64_t jump = flight_jump();
    const int down = !!(*buttons & jump);
    if (mode < 0 || menu_open || free_camera || !hos_oot_flight_shortcut_ready() || !game_in_front()) {
        first_press = 0;
        held = 1;
        consume_jump = 0;
        return mode > 0;
    }
    if (down && !held) {
        const int64_t now = hos_now_ns();
        if (first_press && now - first_press <= 300000000) {
            mode = !mode;
            rx_option_set(HOS_OPT_CHEAT_FLIGHT, mode);
            mode = rx_option(HOS_OPT_CHEAT_FLIGHT, -1);
            first_press = 0;
            consume_jump = mode == 0;
            hos_log("cheats: no-clip flight %s (a double-tap of %s)", mode > 0 ? "took off" : "landed",
                    jump == 1ULL << B_B ? "B" : "X");
        } else {
            first_press = now;
        }
    } else if (!down) {
        consume_jump = 0;
    }
    held = down;
    if (consume_jump) *buttons &= ~jump;
    return mode > 0;
}

/* ((Triforce) 11-24) The ocarina's note layer, rebuilt at every read_input: the note rows held, then their inputs
   marked consumed, so the keys and pads read after it leave them to the notes. player: the player's devices count at
   this read (not in benchmark mode). While the game waits for no note button the rows do nothing at all, and with
   no row bound (as shipped) a wait changes nothing either: oc_pad_word leaves an unset row's button to the game */
static void oc_notes(int player) {
    binds_load();
    int wait = hos_oc_wait;
    /* (a wait nobody ticks is not a wait: an action a pause cancelled must not keep eating the shared keys) */
    if (wait == 1) {
        static unsigned last_beat;
        static int64_t beat_ns;
        const unsigned beat = hos_oc_beat;
        const int64_t now = hos_now_ns();
        if (beat != last_beat || !beat_ns) last_beat = beat, beat_ns = now;
        else if (now - beat_ns > 500000000LL) wait = hos_oc_wait = 0;
    }
    static int last_wait;
    if (wait != last_wait) {
        last_wait = wait;
        hos_log("oc: the note wait turned %s (the action's kind %d)",
                wait == 1 ? "on (buttons)" : wait == 2 ? "on (another way)" : "off", hos_oc_last_kind);
    }
    memset(oc_consumed_keys, 0, sizeof oc_consumed_keys);
    oc_consumed_pads = 0;
    oc_live = 0;
    if (wait != 1 || !player) {
        hos_oc_note_bits = 0;
        return;
    }
    uint64_t bits = 0;
    const uint64_t raw = (uint64_t)(uint32_t)pad_raw_now & ~(pad_after_menu | hud_pad_mask());
    for (int i = 0; i < 5; i++) {   /* (held: before anything is marked, so a note's key reads as any key does) */
        const int row = HOS_KEY_OC_NOTE_L + i;
        const int pad = (int)pad_bind[row][0];
        int held = hos_pad_bindable(pad) && (raw >> pad & 1);
        for (int k = 0; k < 2 && !held; k++) {   /* (the walk key too: Link does not walk while the ocarina waits) */
            const int vk = (int)key_bind[row][k];
            held = vk > 0 && vk < 256 && mouse_vk_slot(vk) < 0 && kmap_down(vk, key);
        }
        if (held) bits |= 1ULL << i;
    }
    for (int i = 0; i < 5; i++) {
        const int row = HOS_KEY_OC_NOTE_L + i;
        const int pad = (int)pad_bind[row][0];
        if (hos_pad_bindable(pad)) oc_consumed_pads |= 1ULL << pad;
        for (int k = 0; k < 2; k++) {
            const int vk = (int)key_bind[row][k];
            if (vk > 0 && vk < 256 && mouse_vk_slot(vk) < 0) oc_consumed_keys[vk] = 1;
        }
    }
    hos_oc_note_bits = bits;
    oc_live = 1;
}

/* (npad_states writes the game's one merged word: during a button wait its five note buttons are the note controls) */
static uint64_t oc_pad_word(uint64_t buttons) {
    if (!oc_live || hos_oc_wait != 1) return buttons;
    /* (no notes where read_input gives the game no player input either: menu open, background; the pads' inputs
       still held after the menu are left out in oc_notes) */
    if (rx_option(1, 0) || !game_in_front()) return buttons;
    static const uint64_t note_to[5] = {1ULL << HOS_SW_L, 1ULL << HOS_SW_R, 1ULL << HOS_SW_A,
                                        1ULL << HOS_SW_Y, 1ULL << HOS_SW_X};
    uint64_t w = buttons;
    for (int i = 0; i < 5; i++) {
        const int row = HOS_KEY_OC_NOTE_L + i;
        if (pad_bind[row][0] < 0 && !key_bind[row][0] && !key_bind[row][1]) continue;   /* (unset: that button plays on) */
        /* (kind 2, the song lesson, teaches the game's own note buttons: the remap adds to them, never replaces) */
        if (hos_oc_last_kind != 2) w &= ~note_to[i];
        if (hos_oc_note_bits & (1ULL << i)) w |= note_to[i];
    }
    return w;
}

static void read_input(uint64_t *buttons, int32_t stick[4]) {
    *buttons = 0;
    memset(stick, 0, 4 * sizeof *stick);
    /* ((Triforce) 11-24: the host's own presses, the game's menus' mouse clicks, are in the buttons as before and also
       kept apart: npad_states takes them out for the hold-to-toggle latch) */
    uint64_t taps = 0;
    scripted_input(buttons, &taps, stick);
    *buttons |= taps;
    host_taps_now = taps;
    /* ((Triforce, 11-19) benchmark mode (host/hos_bench.c) drives the game itself: its presses and stick alone, with the window
       in front or behind other windows; the player's devices do not count while it runs (a mouse or a pad would move the camera
       it measures) */
    int hos_bench_input_only(void);
    const int bench = hos_bench_input_only();
    oc_notes(!bench);   /* ((Triforce) 11-24: marks the note rows' inputs consumed before the pads and keys below are read) */
    if (bench) {
        hud_shortcut(0, 0);
        return;
    }
    /* (Triforce) HOS_CONTROL: the control bridge's presses (host/control.c); one that asked to be exclusive keeps the
       player's devices out while it lasts. Without HOS_CONTROL: one load and back */
    if (hos_control_input(buttons, stick)) return;
    /* A scripted run (a test) takes no input from the player's devices until 5 s after its last press (a variable
       left set in a shell no longer leaves the game without controls), and otherwise the pads count only
       while the game's window is in front, like the keyboard: XInput is global, so a test run in the background
       used to follow the player's pad (and pressed things in its own menus). */
    /* (hookshot) The player's devices count during a script too (the user plays along in test runs, 2026-11-05):
       the presses add to theirs. HOS_INPUT_EXCLUSIVE=1: the script alone until 5 s after its last press, as before */
    static int exclusive = -1;
    if (exclusive < 0) exclusive = getenv("HOS_INPUT_EXCLUSIVE") != NULL;
    if (exclusive && npresses > 0 && script_elapsed_ms(hos_now_ns()) < script_end_ms + 5000) {
        hud_shortcut(0, 0);
        return;
    }
    /* (hookshot, issue 389) A scripted press (HOS_INPUT_SCRIPT, HOS_INPUT_LIVE) is the test's own, not the
       player's: it counts with the game's window behind another one, so a test run can drive the game on one
       monitor while the player works in the front window. HOS_INPUT_BACKGROUND still decides the pads. */
    static int scripted_background = -1;
    if (scripted_background < 0) {
        scripted_background = getenv("HOS_INPUT_SCRIPT_BACKGROUND") != NULL;
        if (scripted_background) hos_log("hid: scripted input runs with the game in the background (HOS_INPUT_SCRIPT_BACKGROUND)");
    }
    /* ((Triforce VR) in the headset the window is seldom in front: a VR session in focus reads as in front, so a gamepad
       beside the hand controllers is the game's in its menus too, not only the bare pads below) */
    if (!game_in_front() && !scripted_background && !vr_session_on()) {   /* (the pads alone, when the player asked for them behind other windows) */
        static const char *env;
        static int looked;
        if (!looked) looked = 1, env = getenv("HOS_INPUT_BACKGROUND");
        /* ((Triforce, 11-18) while the Insert menu is open the pads are its own here too (it reads them in the background
           now: gpu/vk/vk_menu.cpp pads_ok), as in front below; read all the same, so the menu's bits stay current) */
        if (pads_in_background(env, rx_option(4, 0))) {
            uint64_t pb = 0;
            int32_t ps[4] = {0};
            pads_read(&pb, ps);
            if (!rx_option(1, 0)) {
                *buttons |= pb;
                stick_max(stick, ps);
            }
        }
        hud_shortcut(0, 0);   /* ((Triforce) Toggle HUD: with the window in front only) */
        return;
    }
    {   /* (Triforce) The options' tabs inside the game's own Options screen (host/oot_menu.c, gpu/vk/vk_menu.cpp): one of
           our tabs left with Back (the gamepad input B is bound to, Esc, a key bound to B, or the mouse's right button) is the game's Back as well, as in its own
           menus one Back leaves the screen from any tab. The press itself never reaches the game (below), so B is
           tapped for it. A tab left with L or R is the game's own tab: no tap */
        int hos_oot_options_front(void);
        static int was_open;
        const int open = rx_option(1, 0);
        /* (and the keys bound to B, as the game's own tab has them: our tabs take a modifier there (Shift, B's default) as it is
           let go (gpu/vk/vk_menu.cpp menu_tick, so that Shift+Tab still steps back a tab), so it is up by the time they close:
           one seen down within the last 300 ms counts) */
        static int64_t b_key_ns;
        const int64_t now = hos_now_ns();
        for (int k = 0; k < 2; k++) {
            const int vk = hos_binding(HOS_BIND_KEY, HOS_SW_B, k);
            if (vk >= 8 && (GetAsyncKeyState(vk) & 0x8000)) b_key_ns = now;
        }
        if (was_open && !open && hos_oot_options_front()) {
            const int b = hos_binding(HOS_BIND_PAD, HOS_SW_B, 0);
            if ((b >= 0 && b < HOS_PAD_N && ((uint32_t)pad_raw_now >> b & 1)) || (GetAsyncKeyState(VK_ESCAPE) & 0x8000) ||
                (GetAsyncKeyState(VK_RBUTTON) & 0x8000) || (b_key_ns && now - b_key_ns < 300000000LL))
                hos_hid_tap("0:B/80");
        }
        was_open = open;
    }
    uint64_t down = 0;   /* (the pads' buttons and the bound keys down at this read) */
    {   /* (hookshot) while the Insert menu is open the pads are its own, as the keyboard is (key()), and after it
           closed each input it had waits until it is let go (the press that closed it never reaches the game); the
           others count again at once, so one input that stays down (a worn trigger, a second pad) no longer keeps
           the rest from the game. (Triforce) A stick the menu had, pushed past half its travel (pad_raw_now's
           HOS_PAD_LS_* and HOS_PAD_RS_* bits: the menu's lists move by it), waits the same way; the other stick
           counts at once */
        uint64_t pb = 0;
        int32_t ps[4] = {0};
        pads_read(&pb, ps);
        down = pb;
        static int menu_was;
        const int menu = rx_option(1, 0);
        if (menu || menu_was) pad_after_menu |= (uint32_t)pad_raw_now;   /* (the first read after the close too) */
        else pad_after_menu &= (uint32_t)pad_raw_now;
        menu_was = menu;
        if (!menu) {
            const uint64_t ls = 1ULL << HOS_PAD_LS_UP | 1ULL << HOS_PAD_LS_DOWN | 1ULL << HOS_PAD_LS_LEFT | 1ULL << HOS_PAD_LS_RIGHT;
            const uint64_t rs = 1ULL << HOS_PAD_RS_UP | 1ULL << HOS_PAD_RS_DOWN;
            int32_t gs[4];
            memcpy(gs, ps, sizeof gs);
            if (pad_after_menu & ls) gs[0] = gs[1] = 0;
            if (pad_after_menu & rs) gs[2] = gs[3] = 0;
            *buttons |= pad_after_menu ? bound_pad_buttons(pad_raw_game & ~pad_after_menu) : pb;
            stick_max(stick, gs);
        }
        const int pushed = ps[0] > 12000 || ps[0] < -12000 || ps[1] > 12000 || ps[1] < -12000 || ps[2] > 12000 || ps[2] < -12000 ||
                           ps[3] > 12000 || ps[3] < -12000;
        if (pushed) player_used();
        if (pb || pushed) device_used(2);
    }
    binds_load();   /* (the keys: key_default's, or triforce_options.ini's; the mouse's buttons once its capture is known) */
    walk_vk = walk_key_code(rx_option(HOS_OPT_WALK_KEY, 0));   /* ((Triforce) before the keys are read: it is none of theirs) */
    for (int i = 0; i < HOS_SW_N; i++)
        if (bound_down(i, 0)) *buttons |= 1ULL << i, down |= 1ULL << i, device_used(1);
    /* (a button or a key counts as the player's input when it goes down, not at every read while it stays down: held, as
       ZL is for the ocarina's song sheet, it kept the game menus' cursor hidden, which the mouse shows by moving) */
    static uint64_t down_was;
    if (down & ~down_was) player_used();
    down_was = down;
    int32_t mouse[4] = {0};
    /* the mouse's motion: the camera itself (mouse_native.c) with the menu's Mouse camera on Native, else the right
       stick; also the stick while the game does not give the camera free control (a menu, a lock-on, the pause menu,
       other cameras: mouse_native.c) and while a button it takes the stick for is held: ZR (the bow's aim), L (the
       item wheel) or R, where the mouse points as it does in As the stick */
    static const char *native_env;
    static int native_looked;
    if (!native_looked) native_looked = 1, native_env = getenv("HOS_MOUSE_NATIVE");
    /* ((Triforce) 11-24) The Steam Deck's built-in controls show the system a mouse as well as a pad, and Steam's Desktop
       layout presses that mouse's buttons for the triggers (R2 a left click, L2 a right one) and moves it with the right
       stick. The pad's own inputs already carry those actions, so while those controls give the game its input
       (host/pad_sdl.c hos_sdl_pads_deck_builtin, host/steam_pads.h: never on a PC that is not a Steam Deck) the mouse's
       motion steers nothing and its buttons are no control's: Native's camera hook is not asked for, the stick path's
       motion is dropped, and the buttons are not armed below. The mouse is still taken in (mouse_stick) so its pointer
       stays held at the centre, and one of the game's menus keeps its pointer and clicks */
    int hos_sdl_pads_deck_builtin(void);
    const int deck_builtin_input = hos_sdl_pads_deck_builtin();
    const int mode = native_env ? atoi(native_env) != 0 : rx_option(6, 0);   /* ((Triforce) 2: Off, the mouse never captured) */
    const int native = mode == 1 && !deck_builtin_input;
    int hos_mouse_native(void);
    void hos_mouse_native_free(int free);
    const uint64_t game_stick = (1ULL << B_ZR) | (1ULL << B_L) | (1ULL << B_R);
    int captured = 0, as_stick = mode == 0;
    if (native) {
        mouse_setup();
        mouse_sens_keys();
        hos_mouse_native_free(!((*buttons | toggles.latched) & game_stick));   /* ((Triforce) a latched ZR, L or R aims too) */
        captured = hos_mouse_native();
        if (captured < 0) captured = 0, as_stick = 1;
    }
    if (as_stick) {
        captured = mouse_stick(&mouse[2], &mouse[3], (int)((*buttons | toggles.latched) >> B_L & 1));
        if (deck_builtin_input) mouse[2] = mouse[3] = 0;   /* (taken for the pointer's sake, never the camera's) */
        if (captured) stick_max(stick, mouse);
    }
    /* (the side buttons in the game's menus) */
    int hos_mouse_in_game_menu(void);   /* display.c */
    const int menu_mouse = hos_mouse_in_game_menu();
    /* ((Triforce) 11-24: not beside the Deck's built-in controls, above. Armed at every read, so a button held while that
       applies is let go before it counts again, as the click that captures is) */
    mouse_buttons_arm(captured && !deck_builtin_input, menu_mouse);
    hud_shortcut(!rx_option(1, 0), captured || menu_mouse);   /* ((Triforce) the Toggle HUD row, not while the Insert menu is open) */
    captured |= menu_mouse;   /* (from here on: whether a mouse button can be a control; the armed ones are) */
    if (captured)
        for (int i = 0; i < HOS_SW_N; i++)
            if (bound_down(i, 1)) *buttons |= 1ULL << i, device_used(1);
    /* ((Triforce) the captured mouse turning the camera: past an eighth of the stick's travel, not the mouse nudged) */
    if (mouse[2] > 4096 || mouse[2] < -4096 || mouse[3] > 4096 || mouse[3] < -4096) device_used(1);
    /* (the left stick's and the camera's keys: WASD and the arrows or IJKL by default) */
    const int cx = bound_down(HOS_KEY_CAM_RIGHT, captured) - bound_down(HOS_KEY_CAM_LEFT, captured),
              cy = bound_down(HOS_KEY_CAM_UP, captured) - bound_down(HOS_KEY_CAM_DOWN, captured);
    int32_t keys[4] = {(bound_down(HOS_KEY_MOVE_RIGHT, captured) - bound_down(HOS_KEY_MOVE_LEFT, captured)) * 32767,
                       (bound_down(HOS_KEY_MOVE_UP, captured) - bound_down(HOS_KEY_MOVE_DOWN, captured)) * 32767,
                       cx * 32767, cy * 32767};
    if (keys[0] || keys[1] || cx || cy) device_used(1);   /* ((Triforce) the movement and camera keys) */
    /* ((Triforce) the walk key held: the movement keys push the left stick a part of the way. The keys' alone: a
       controller's stick and the scripted presses are as they are) */
    if (walk_vk && key(walk_vk)) walk_keys(keys, rx_option(HOS_OPT_WALK_SCALE, 51));
    stick_max(stick, keys);
    if (keys[0] || keys[1] || keys[2] || keys[3]) player_used();   /* (display.c: the game menus' cursor hides again) */
}

static void vibration_send(uint64_t handle, uint64_t value);
volatile int64_t hos_hid_last_read;

volatile uint64_t hos_npad_buttons;   /* (Triforce) the buttons of the last state the game was given: host/mod_cheats.c */
/* (Triforce) The Mods entry under a game list's last button (host/oot_menu.c, gpu/vk/vk_menu.cpp), from npad_states' read: while
   the game's cursor is on that last button and our menu is shut, Down (the D-pad's, or the left stick held down) is the
   entry's, not the game's: the renderer takes the cursor onto Mods at its first frame.
   While the Mods entry or its screen has the cursor the game gets no input (a pad's is the menu's already, read_input, and the
   keys' too, key()). What is left is a test's scripted presses (the script, the live input file): they go to the menu as a
   pad's would (HOS_OPT_MODS_PRESS), not to the game. Buttons held as the cursor goes back to the game are not the game's until
   let go (the Up that left Mods does not move the game's cursor too).
   ((Triforce, 11-19) the lab's "a normal DOWN from Title Screen skips Mods to Quit": the Down that brought the cursor onto
   Mods, still held at the next read, counted there as a new press of the entry's (the buttons before were taken as none
   held), on to Quit; a 16 ms Down, gone by then, landed on Mods. A press is new against the buttons of the read before,
   whichever side had them: those held as the cursor comes onto Mods, its Down among them, are held, not pressed. And the
   directions held are told at each read (HOS_MODS_HELD_*), so the menu repeats a held one at its rate as it repeats a
   pad's or a key's) */
static void mods_input(uint64_t *buttons_io, int32_t stick[4]) {
    int hos_oot_mods_down(void);
    uint64_t buttons = *buttons_io;
    const uint64_t raw = buttons;   /* (as the devices and the script gave them, before the entry takes its Down) */
    /* ((Triforce) 11-17) the left stick pushed past half its travel, as the D-pad */
    const int raw_dir = stick[1] > 16384 ? HOS_MODS_PRESS_UP : stick[1] < -16384 ? HOS_MODS_PRESS_DOWN
                      : stick[0] < -16384 ? HOS_MODS_PRESS_LEFT : stick[0] > 16384 ? HOS_MODS_PRESS_RIGHT : 0;
    static int was_down;
    /* (a press only: the Down that brought the game's cursor onto the last button, still held, is not one.
       ((Triforce, 11-19) the stick's Down where the menu's pad bits have it, past half its travel (HOS_PAD_LS_DOWN,
       pads_read): at -16000 it came onto Mods a read before the menu saw the stick's Down, which it then took as a
       Down of its own, on to Quit) */
    const int down = (int)(buttons >> B_DOWN & 1) || stick[1] < -16384;
    /* ((Triforce, 11-19) a Down held from higher up the list: the game's own repeat takes its cursor onto the last button,
       and the Down, held from before, was no press there, so the cursor stayed on that button as long as it was held. A
       held Down goes on onto Mods as a repeat, at the menu's held-direction rate (vk_menu.cpp menu_tick: after 0.35 s held,
       then a step of 83 ms, 33 ms past 1.5 s): at its first step on the last button once the hold is past the first delay.
       A Down pressed on the button above, which moves the game's cursor onto the last one, needs the first 0.35 s held as
       any repeat does: a short press stays there. Its word is 5, a repeat's: the menu repeats on from Mods at the step) */
    static int64_t down_ns, last_ns;   /* (when this Down was pressed; when it was first held on the last button, 0 none) */
    static int repeated;               /* (its repeat onto Mods told: once a hold) */
    const int64_t now = hos_now_ns();
    if (down && !was_down) down_ns = now, repeated = 0;
    if (!rx_option(1, 0) && hos_oot_mods_down() && down) {
        buttons &= ~(1ULL << B_DOWN);
        stick[1] = 0;
        if (!was_down) {
            rx_option_set(HOS_OPT_MODS_ENTER, 1), last_ns = 0;
        } else if (!repeated) {
            if (!last_ns) last_ns = now;
            const int64_t held = now - down_ns, step = held > 1500000000LL ? 33000000LL : 83000000LL;
            if (held >= 350000000LL && now - last_ns >= step) rx_option_set(HOS_OPT_MODS_ENTER, 5), repeated = 1, last_ns = 0;
        }
    } else {
        last_ns = 0;
    }
    was_down = down;
    static uint64_t prev, held_over;
    static int sel_was, stick_over, stick_was;
    const int sel = rx_option(HOS_OPT_MODS_SELECTED, 0) != 0;
    if (sel) {
        static const struct { int bit, press; } map[] = {{B_UP, HOS_MODS_PRESS_UP}, {B_DOWN, HOS_MODS_PRESS_DOWN},
            {B_LEFT, HOS_MODS_PRESS_LEFT}, {B_RIGHT, HOS_MODS_PRESS_RIGHT}, {B_A, HOS_MODS_PRESS_A}, {B_B, HOS_MODS_PRESS_B},
            {B_L, HOS_MODS_PRESS_L}, {B_R, HOS_MODS_PRESS_R}};
        const uint64_t fresh = buttons & ~prev;
        int bits = 0, held = raw_dir;
        for (int i = 0; i < (int)(sizeof map / sizeof *map); i++) {
            if (fresh >> map[i].bit & 1) bits |= map[i].press;
            if (buttons >> map[i].bit & 1) held |= map[i].press;
        }
        if (raw_dir && raw_dir != stick_was) bits |= raw_dir;
        stick_was = raw_dir;
        /* (each read: the presses, and the directions held, which the menu repeats; the report bit says it is one) */
        rx_option_set(HOS_OPT_MODS_PRESS, bits | (held & HOS_MODS_PRESS_DIRS) << HOS_MODS_HELD_SHIFT | HOS_MODS_REPORT);
        prev = buttons;
        buttons = 0;
        memset(stick, 0, 4 * sizeof *stick);
    } else {
        if (sel_was) held_over = prev | buttons, stick_over = 1;   /* ((Triforce, 11-19) and the keys: the menu's while it was open) */
        held_over &= buttons;
        buttons &= ~held_over;
        if (stick_over && stick[0] > -12000 && stick[0] < 12000 && stick[1] > -12000 && stick[1] < 12000) stick_over = 0;
        if (stick_over) stick[0] = stick[1] = 0;
        prev = raw, stick_was = raw_dir;   /* (held now: not pressed at the first read with Mods chosen) */
    }
    sel_was = sel;
    *buttons_io = buttons;
}

/* GetNpadStates(State* out, int count, unsigned int const& npadId): the latest state first */
static void npad_states(Ctx *c) {
    uint64_t out = ARG(0);
    /* ((Triforce) at most the 16 states a console keeps, all in guest memory: a count from the game's arguments wrote
       0x28 bytes a state past any buffer, and past the guest window) */
    int count = (int)ARG(1) < 0 ? 0 : (int)ARG(1) > 16 ? 16 : (int)ARG(1);
    if (!hos_guest_range(out, (uint64_t)count * STATE_SIZE) || !hos_guest_range(ARG(2), 4)) {
        RET(0);
        return;
    }
    uint32_t id = G32(ARG(2));
    uint64_t buttons = 0;
    int32_t stick[4] = {0};
    int connected = id == NPAD_NO1;
    {
        static int64_t last_read;
        static uint32_t seen_ids[16];
        static int nseen;
        const int64_t now = hos_now_ns();
        if (connected && last_read && now - last_read > 2000000000LL)
            hos_log("hid: the game read no controller for %.1f s (lr %#llx)", (now - last_read) / 1e9,
                    (unsigned long long)c->x[30]);
        if (connected) last_read = hos_hid_last_read = now;
        void hos_prompts_live(void);   /* ((Triforce) prompts.c: a new face or new controls shown at once) */
        if (connected) hos_prompts_live();
        int known = 0;
        for (int i = 0; i < nseen; i++) known |= seen_ids[i] == id;
        if (!known && nseen < 16) {
            seen_ids[nseen++] = id;
            hos_log("hid: the game reads npad %#x (%s, lr %#llx)", id, connected ? "No.1" : "not connected",
                    (unsigned long long)c->x[30]);
        }
    }
    {   /* (Triforce) the Scan amiibo page's choice is taken here, whatever the game shows (host/nn_nfp.c) */
        void hos_amiibo_poll(void);
        hos_amiibo_poll();
    }
    /* ((Triforce) input recordings, host/input_movie.c: a test tool, off unless HOS_INPUT_RECORD or HOS_INPUT_PLAY is set
       or the control bridge starts one; then one atomic load here and in hos_input_movie_end below.
       HOS_INPUT_PLAY: a recording's read is the recording's alone: none of the merge below runs, so neither the player's
       devices, the script, the bridge, the toggles nor the filters reach the game.
       HOS_INPUT_RECORD: a game frame has one pad, its first read's (its later reads are given the same: an input that
       changed between two reads of a frame reached the game's jobs or not as their race went) */
    int hos_input_movie_begin(MoviePad *given);
    void hos_input_movie_end(const MoviePad *p);
    MoviePad given;
    const int played = connected && hos_input_movie_begin(&given);
    uint64_t axes = 0, flight = 0;   /* (the free camera and flight cheats' inputs, taken from the sticks) */
    int height = 0;
    if (played) {   /* (the pads still read for the Insert menu (hos_pad_raw), not the game's input; behind other windows
                       only as the player's Controller in background row lets them) */
        static const char *env;
        static int looked;
        if (!looked) looked = 1, env = getenv("HOS_INPUT_BACKGROUND");
        if (game_in_front() || vr_session_on() || pads_in_background(env, rx_option(4, 0))) {
            uint64_t menu_buttons = 0;
            int32_t menu_stick[4] = {0, 0, 0, 0};
            pads_read(&menu_buttons, menu_stick);
        }
    }
    if (connected && !played) {
        read_input(&buttons, stick);
        {   /* ((Triforce) 11-24) hold-to-toggle, the Controls tab's rows (option HOS_OPT_HOLD_TOGGLE: the enabled buttons,
               1 << HOS_SW_*; never Plus or Minus): one latch after the remapping, for the keys, the mouse's buttons and
               the pads alike. Dropped while the Insert menu is open, when the window is not in front (unless the pads
               count there), at a reset (hos_input_clear_toggles) and at a press of Plus or Minus, so the pause and the
               map open with shield and aim let go. The host's own presses pass as they are */
            const uint64_t stay = (1ULL << B_PLUS) | (1ULL << B_MINUS);
            const uint64_t enabled = (uint64_t)(uint32_t)rx_option(HOS_OPT_HOLD_TOGGLE, 0) & ((1ULL << B_PLUS) - 1) & ~stay;
            const uint64_t taps = host_taps_now, own = buttons & ~taps;
            const int reset = InterlockedExchange(&toggle_reset, 0) || rx_option(1, 0) ||
                              (enabled && !game_in_front() && !(vr_session_on() || pads_in_background(getenv("HOS_INPUT_BACKGROUND"), rx_option(4, 0))));
            const uint64_t pause = own & ~toggles.previous & stay;
            if (enabled || toggles.latched) buttons = hold_toggle_apply(&toggles, own, enabled, reset || pause != 0) | taps;
            else toggles.previous = own, toggles.blocked = 0;
        }
        vr_pad_read(c, &buttons, stick);   /* ((Triforce VR) the Touch controllers, first person's strafe: vr_game.c) */
        /* (mouse_native.c) the keys, the pads and the scripted presses are the right stick too: while they turn the camera,
           its angles are the native mouse's new start, so the two do not undo each other. ((Triforce, 11-22) Told after
           every read, not at the end of the window-in-front one alone: with the window behind another and Controller in
           background on, the pad's turns were put back each frame and the camera moved a frame's worth (#bug-tracker,
           11-21); the benchmark's camera turn too) */
        void hos_mouse_native_stick(int held);
        hos_mouse_native_stick(stick[2] != 0 || stick[3] != 0);
        mods_input(&buttons, stick);   /* (Triforce) the Mods entry's: below */
        {   /* (Triforce) the sprint button's press is its own while Link plays (host/oot_sprint.c) */
            void hos_oot_sprint_pad(uint64_t *buttons);
            hos_oot_sprint_pad(&buttons);
        }
        const int menu_open = rx_option(1, 0);
        const int free_camera = rx_option(HOS_OPT_CHEAT_CAMERA, 0);
        const int flying = flight_jump_shortcut(&buttons, rx_option(HOS_OPT_CHEAT_FLIGHT, -1), menu_open, free_camera);
        if (free_camera && !menu_open) {
            for (int i = 0; i < 4; i++) axes |= (uint64_t)(uint16_t)stick[i] << (16 * i);
            height = (int)(buttons >> B_R & 1) - (int)(buttons >> B_L & 1);
            memset(stick, 0, sizeof stick);
            buttons &= ~((1ULL << B_L) | (1ULL << B_R));
        } else if (flying && !menu_open) {
            const uint64_t climb = flight_jump() | (1ULL << B_R);   /* ((Triforce, 11-24) the game's Jump: flight_jump) */
            const int vertical = !!(buttons & climb) - (int)(buttons >> B_L & 1);
            flight = (uint16_t)stick[0] | (uint64_t)(uint16_t)stick[1] << 16 |
                     (uint64_t)(uint16_t)vertical << 32;
            stick[0] = stick[1] = 0;
            buttons &= ~(climb | (1ULL << B_L));
        }
        __atomic_store_n(&flight_input, flight, __ATOMIC_RELAXED);
        __atomic_store_n(&move_stick_held, abs(stick[0]) > 4096 || abs(stick[1]) > 4096, __ATOMIC_RELAXED);   /* ((Triforce) the Movement speed tool) */
        __atomic_store_n(&free_camera_axes, axes, __ATOMIC_RELAXED);
        __atomic_store_n(&free_camera_height, height, __ATOMIC_RELAXED);
    }
    uint64_t hos_title_input(uint64_t buttons);   /* totk_title.c: the title menu's credits entries */
    if (connected && !played) buttons = hos_title_input(buttons);
    uint64_t hos_frame_step_buttons(uint64_t buttons);   /* nn_vi.c: the frame step of the wheel and quick menus */
    if (connected && !played) buttons = hos_frame_step_buttons(buttons);
    /* ((Triforce) 11-24) while the game waits for a note button, the five are the note controls' (oc_notes): the last
       word in what the game is given */
    if (connected && !played) buttons = oc_pad_word(buttons);
    /* ((Triforce) what the game is given: recorded here (HOS_INPUT_RECORD), or the recording's (HOS_INPUT_PLAY, and a
       recorded frame's later reads), with the cheats' inputs as it had them) */
    if (played) {
        buttons = given.bits;
        memcpy(stick, given.stick, sizeof given.stick);
        __atomic_store_n(&flight_input, given.flight, __ATOMIC_RELAXED);
        __atomic_store_n(&move_stick_held, abs(stick[0]) > 4096 || abs(stick[1]) > 4096, __ATOMIC_RELAXED);
        __atomic_store_n(&free_camera_axes, given.axes, __ATOMIC_RELAXED);
        __atomic_store_n(&free_camera_height, given.height, __ATOMIC_RELAXED);
    } else if (connected) {
        const MoviePad pad = {buttons, {stick[0], stick[1], stick[2], stick[3]}, flight, axes, height};
        hos_input_movie_end(&pad);   /* (recording: the frame's pad; else one load and back) */
    }
    /* (Triforce) the buttons the game is given, for the mods' cheats that run while buttons are held (host/mod_cheats.c) */
    if (connected) __atomic_store_n(&hos_npad_buttons, buttons, __ATOMIC_RELAXED);
    int64_t s = ++sampling;
    for (int i = 0; i < count; i++) {
        uint64_t e = out + (uint64_t)i * STATE_SIZE;
        memset(GP(e), 0, STATE_SIZE);
        G64(e) = (uint64_t)(s - i);
        G64(e + 8) = buttons;
        memcpy(GP(e + 16), stick, 16);
        G32(e + 32) = connected ? ATTR_CONNECTED : 0;
    }
    RET(count);
}
HLE(_ZN2nn3hid13GetNpadStatesEPNS0_16NpadFullKeyStateEiRKj) { npad_states(c); }
HLE(_ZN2nn3hid13GetNpadStatesEPNS0_17NpadHandheldStateEiRKj) { npad_states(c); }
HLE(_ZN2nn3hid13GetNpadStatesEPNS0_16NpadJoyDualStateEiRKj) { npad_states(c); }
HLE(_ZN2nn3hid13GetNpadStatesEPNS0_16NpadJoyLeftStateEiRKj) { npad_states(c); }
HLE(_ZN2nn3hid13GetNpadStatesEPNS0_17NpadJoyRightStateEiRKj) { npad_states(c); }
/* GetNpadStyleSet(unsigned int const&) -> BitFlagSet<32, NpadStyleTag> */
HLE(_ZN2nn3hid15GetNpadStyleSetERKj) { RET(G32(ARG(0)) == NPAD_NO1 ? STYLE_FULLKEY : 0); }

HLE(_ZN2nn3hid14InitializeNpadEv) {}
HLE(_ZN2nn3hid18InitializeKeyboardEv) {}
HLE(_ZN2nn3hid15InitializeMouseEv) {}
HLE(_ZN2nn3hid14DisconnectNpadERKj) {}
HLE(_ZN2nn3hid18SetNpadJoyHoldTypeENS0_15NpadJoyHoldTypeE) {}
HLE(_ZN2nn3hid22SetSupportedNpadIdTypeEPKjm) {}
HLE(_ZN2nn3hid24SetSupportedNpadStyleSetENS_4util10BitFlagSetILi32ENS0_12NpadStyleTagEEE) {}
HLE(_ZN2nn3hid18StartSixAxisSensorERKNS0_19SixAxisSensorHandleE) {}

/* ShowControllerSupport(ControllerSupportResultInfo*, ControllerSupportArg const&) -> Result: one player, No.1 */
HLE(_ZN2nn3hid21ShowControllerSupportEPNS0_27ControllerSupportResultInfoERKNS0_20ControllerSupportArgE) {
    memset(GP(ARG(0)), 0, 8);
    *(uint8_t *)GP(ARG(0)) = 1;
    G32(ARG(0) + 4) = NPAD_NO1;
    RET(0);
}

/* Handles: six-axis ones are opaque u32s; a vibration handle is {u8 style type (3 = full key), u8 npad id, u8 device
   index (0 left, 1 right), u8 reserved}, which the SDK's vibration classes read. Vibration goes nowhere yet. */
HLE(_ZN2nn3hid23GetSixAxisSensorHandlesEPNS0_19SixAxisSensorHandleEiRKjNS_4util10BitFlagSetILi32ENS0_12NpadStyleTagEEE) {
    /* (hookshot) OoT asks for two (a Joy-Con pair) but runs its motion path only when three come back: at two its
       third source (the console's own, through JCMS) stays dead, and that branch is what marks motion active for the
       aim (spluton, issue 112). The count says three; only the handles asked for are written, so a caller's array
       sized for two is never written past (the handles are opaque: GetSixAxisSensorStates does not read them). */
    const int asked = (int)ARG(1) < 0 ? 0 : (int)ARG(1) > 16 ? 16 : (int)ARG(1);
    static int logged;
    if (!logged) logged = 1, hos_log("hid: six-axis handles: %d asked for, %d reported", asked, asked < 3 ? 3 : asked);
    for (int i = 0; i < asked; i++) G32(ARG(0) + 4 * (uint64_t)i) = 0x100u + (uint32_t)i;
    RET(asked < 3 ? 3 : asked);
}
/* SixAxisSensorState, 0x60 bytes: {i64 delta time (ns), i64 sampling number, f32 acceleration[3] (G), angular velocity[3]
   (revolutions a second), angle[3] (revolutions), direction[3][3], u32 attributes (1 connected), pad}. Newest first.
   (hookshot) With Motion controls on and a pad with a gyroscope (host/pad_sdl.c), the state OoT aims with
   (host/hos_motion.h: the full state, as the console and Eden build it); else a pad lying still. */
HLE(_ZN2nn3hid22GetSixAxisSensorStatesEPNS0_18SixAxisSensorStateEiRKNS0_19SixAxisSensorHandleE) {
    /* (the sampling number goes up once per reading, as the hardware's does: while live it is the readings' own count,
       moved on past the last number handed out; each entry is its own reading, with the time since the one before) */
    static int64_t six_sampling, six_base;
    static int was_live;
    const uint64_t out = ARG(0);
    int count = (int)ARG(1) < 1 ? 0 : (int)ARG(1) > HOS_MOTION_HISTORY ? HOS_MOTION_HISTORY : (int)ARG(1);
    if (!hos_guest_range(out, (uint64_t)count * 0x60)) count = 0;   /* ((Triforce) the states in guest memory, or none) */
    static const float at_rest[18] = {0, 0, -1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1};
    int hos_sdl_motion_history(HosMotionSample *out, int max);   /* pad_sdl.c */
    HosMotionSample h[HOS_MOTION_HISTORY];
    static const char *background_env;
    static int background_looked;
    if (!background_looked) background_looked = 1, background_env = getenv("HOS_INPUT_BACKGROUND");
    /* ((Triforce) input recordings, host/input_movie.c: the readings handed out, recorded (HOS_INPUT_RECORD), or the
       recording's alone (HOS_INPUT_PLAY); with neither, one atomic load and nothing copied) */
    int hos_input_movie_active(void);
    int hos_input_movie_playing(void);
    int hos_input_movie_gyro(MovieMotion *h, int max, int live);
    const int movie = hos_input_movie_active();
    const int counts = motion_counts(game_in_front(), background_env, rx_option(4, 0)) && !(movie && hos_input_movie_playing());
    int live = count && counts ? hos_sdl_motion_history(h, count) : 0;
    if (movie) {
        MovieMotion mm[HOS_MOTION_HISTORY];
        for (int i = 0; i < live; i++) {
            mm[i].n = h[i].n, mm[i].dt = h[i].dt_ns;
            memcpy(mm[i].v, &h[i].st, sizeof mm[i].v);
        }
        const int was = live;
        live = hos_input_movie_gyro(mm, count, live);
        if (live != was || hos_input_movie_playing())
            for (int i = 0; i < live; i++) {
                h[i].n = mm[i].n, h[i].dt_ns = mm[i].dt;
                memcpy(&h[i].st, mm[i].v, sizeof mm[i].v);
            }
    }
    /* (each switch between live and at rest moves the numbers a whole history past the last ones given out, so no entry
       of one ever has a number an entry of the other had) */
    if (live) {
        if (!was_live || six_base + h[0].n < six_sampling) six_base = six_sampling + HOS_MOTION_HISTORY - h[0].n;
        six_sampling = six_base + h[0].n;
    } else {
        six_sampling += was_live ? HOS_MOTION_HISTORY : 1;
    }
    was_live = live > 0;
    const int n = live ? live : count;
    for (int i = 0; i < n; i++) {
        const uint64_t e = out + (uint64_t)i * 0x60;
        float v[18];
        memset(GP(e), 0, 0x60);
        if (live) {
            const HosMotionState *m = &h[i].st;
            memcpy(v, m->accel, 12), memcpy(v + 3, m->gyro, 12), memcpy(v + 6, m->rotation, 12), memcpy(v + 9, m->direction, 36);
            G64(e) = (uint64_t)(h[i].dt_ns > 0 ? h[i].dt_ns : 5000000);
            G64(e + 8) = (uint64_t)(six_base + h[i].n);
        } else {
            memcpy(v, at_rest, sizeof v);
            G64(e) = 5000000;
            G64(e + 8) = (uint64_t)(six_sampling - i);
        }
        memcpy(GP(e + 0x10), v, sizeof v);
        G32(e + 0x58) = 1;
    }
    RET(n);
}
HLE(_ZN2nn3hid25GetVibrationDeviceHandlesEPNS0_21VibrationDeviceHandleEiRKjNS_4util10BitFlagSetILi32ENS0_12NpadStyleTagEEE) {
    int n = (int)ARG(1) < 2 ? (int)ARG(1) : 2;
    for (int i = 0; i < n; i++) G32(ARG(0) + 4 * (uint64_t)i) = 3u | (G32(ARG(2)) & 0xFF) << 8 | (uint32_t)i << 16;
    RET(n);
}
HLE(_ZN2nn3hid25InitializeVibrationDeviceERKNS0_21VibrationDeviceHandleE) {}
HLE(_ZN2nn3hid18SendVibrationValueERKNS0_21VibrationDeviceHandleERKNS0_14VibrationValueE) { vibration_send(ARG(0), ARG(1)); }

/* nn::hid::detail vibration: what the SDK's own classes (VibrationNode, VibrationTarget, VibrationPlayer) call; on
   hardware each is an IPC to hid. A device is an LRA on its side of the controller, always mounted and permitted. */
/* A vibration value for one of the two motors of the pad (handle +2 = device index): the pads that rumble (SDL) get
   the stronger of the two sides' heavy and light motor strengths. (OoT sends both sides the same values.) */
/* (issue 263) An HD rumble amplitude is not a motor's: OoT asks for 0.02-0.06 for most effects, a few percent of a DualSense's or an
   Xbox pad's motor, nothing you feel. Eden's SDL driver's mapping (Eglantine src/input_common/drivers/sdl_driver.cpp, GPL-3.0):
   (a + a^0.35) / 2, then less for higher frequencies, to give some feel of them */
static float rumble_motor(float amp, float freq, float start, float width) {
    if (amp <= 0.0f) return 0.0f;
    float scale = 1.0f;
    if (freq > start) {
        scale = 1.0f - (freq - start) / width;
        if (scale < 0.3f) scale = 0.3f;
    }
    const float boosted = (amp + powf(amp, 0.35f)) * 0.5f;
    return boosted * scale > 1.0f ? 1.0f : boosted * scale;
}
/* How much of a band at this frequency the heavy (low-frequency) motor plays, 0 to 1; the light motor plays the rest.
   The Switch's HD rumble bands overlap (low about 41-626 Hz, high about 82-1253 Hz, 160 and 320 Hz by default; OoT asks
   for about 100-130 Hz low and 250-300 Hz high), so the band a value came in says less than its frequency: up to 160 Hz
   is all heavy, from 200 Hz all light, and between them a crossfade on a log scale (log2(1.25), about a third of an
   octave). The defaults and what OoT sends land on the same motors as before, with room below OoT's high band; a high
   band played low reaches the heavy motor, a low band played high the light one. */
#define RUMBLE_HEAVY_TOP 160.0f
#define RUMBLE_LIGHT_BOTTOM 200.0f
static float rumble_heavy_share(float freq) {
    if (!(freq > RUMBLE_HEAVY_TOP)) return 1.0f;   /* (also a NaN or a 0 Hz value: the heavy motor, as the low band went) */
    if (freq >= RUMBLE_LIGHT_BOTTOM) return 0.0f;
    const float s = 1.0f - log2f(freq / RUMBLE_HEAVY_TOP) / log2f(RUMBLE_LIGHT_BOTTOM / RUMBLE_HEAVY_TOP);
    return s < 0.0f ? 0.0f : s > 1.0f ? 1.0f : s;   /* (rounding: sqrtf below takes 1 - s) */
}
/* One VibrationValue {amp_low, freq_low, amp_high, freq_high} -> the motors' strengths, 0 to 1: motor[0] heavy, motor[1]
   light. Each band keeps its strength (rumble_motor, with its band's falloff) and is split between the motors by its
   frequency with constant power (sqrt of the shares), so a band in the crossfade is not felt weaker; each motor takes
   the stronger of the two bands' parts. */
static void rumble_map(const float v[4], float motor[2]) {
    const float low = rumble_motor(v[0], v[1], 140.0f, 400.0f), high = rumble_motor(v[2], v[3], 200.0f, 700.0f);
    const float lh = rumble_heavy_share(v[1]), hh = rumble_heavy_share(v[3]);
    const float heavy[2] = {low * sqrtf(lh), high * sqrtf(hh)}, light[2] = {low * sqrtf(1.0f - lh), high * sqrtf(1.0f - hh)};
    motor[0] = heavy[0] > heavy[1] ? heavy[0] : heavy[1];
    motor[1] = light[0] > light[1] ? light[0] : light[1];
}
static void vibration_send(uint64_t handle, uint64_t value) {
    static float amp[2][2];
    float v[4];
    memcpy(v, GP(value), sizeof v);
    const int dev = (G32(handle) >> 16) & 1;
    rumble_map(v, amp[dev]);
    {   /* (hookshot, issue 263) what the game asks for: the first values, then a count now and then */
        static long long n, strong;
        static float peak;
        if (v[0] > peak) peak = v[0];
        if (v[2] > peak) peak = v[2];
        if ((v[0] > 0.01f || v[2] > 0.01f) && strong++ < 6)
            hos_log("hid: vibration #%lld: handle %08x, low %.2f @ %.0f Hz, high %.2f @ %.0f Hz", n, G32(handle), v[0], v[1], v[2], v[3]);
        if ((++n & 4095) == 0) hos_log("hid: %lld vibration values, strongest %.2f since the last count", n, peak), peak = 0;
    }
    void hos_sdl_rumble_hd(int side, const float value[4]);   /* pad_sdl.c: the value as it is, for HD rumble */
    hos_sdl_rumble_hd(dev, v);
    /* ((Triforce) the same four values, as they are, to RenHDrum's backends (host/rumble_renhdrum.c; nothing without
       renhdrum.dll): they keep the bands apart, which rumble_map above has flattened for the motors */
    void rh_push(int side, const float value[4]);
    rh_push(dev, v);
    void hos_sdl_rumble(float low, float high);   /* pad_sdl.c */
    hos_sdl_rumble(amp[0][0] > amp[1][0] ? amp[0][0] : amp[1][0], amp[0][1] > amp[1][1] ? amp[0][1] : amp[1][1]);
}
static void vibration_value_idle(uint64_t v) {   /* VibrationValue {f32 amp_low, freq_low, amp_high, freq_high} */
    float idle[4] = {0.0f, 160.0f, 0.0f, 320.0f};
    memcpy(GP(v), idle, sizeof idle);
}
HLE(_ZN2nn3hid6detail15PermitVibrationEb) { RET(0); }
HLE(_ZN2nn3hid6detail20IsVibrationPermittedEPb) { *(uint8_t *)GP(ARG(0)) = 1; RET(0); }
HLE(_ZN2nn3hid6detail27BeginPermitVibrationSessionEv) { RET(0); }
HLE(_ZN2nn3hid6detail25EndPermitVibrationSessionEv) { RET(0); }
HLE(_ZN2nn3hid6detail25InitializeVibrationDeviceERKNS0_21VibrationDeviceHandleE) { RET(0); }
/* GetVibrationDeviceInfo(VibrationDeviceInfo* {u32 type; u32 position}, handle const&): LRA (1), left 1 / right 2 */
HLE(_ZN2nn3hid6detail22GetVibrationDeviceInfoEPNS0_19VibrationDeviceInfoERKNS0_21VibrationDeviceHandleE) {
    G32(ARG(0)) = 1;
    G32(ARG(0) + 4) = ((G32(ARG(1)) >> 16) & 1) + 1;
    RET(0);
}
HLE(_ZN2nn3hid6detail18SendVibrationValueERKNS0_21VibrationDeviceHandleERKNS0_14VibrationValueE) {
    vibration_send(ARG(0), ARG(1));
    RET(0);
}
HLE(_ZN2nn3hid6detail19SendVibrationValuesEPKNS0_21VibrationDeviceHandleEPKNS0_14VibrationValueEi) {
    for (int i = 0; i < (int)ARG(2) && i < 8; i++) vibration_send(ARG(0) + 4 * (uint64_t)i, ARG(1) + 16 * (uint64_t)i);
    RET(0);
}
HLE(_ZN2nn3hid6detail23GetActualVibrationValueEPNS0_14VibrationValueERKNS0_21VibrationDeviceHandleE) {
    vibration_value_idle(ARG(0));
    RET(0);
}
HLE(_ZN2nn3hid6detail25SendVibrationGcErmCommandERKNS0_21VibrationDeviceHandleERKNS0_21VibrationGcErmCommandE) { RET(0); }
HLE(_ZN2nn3hid6detail30GetActualVibrationGcErmCommandEPNS0_21VibrationGcErmCommandERKNS0_21VibrationDeviceHandleE) {
    G32(ARG(0)) = 0;   /* Stop */
    RET(0);
}
HLE(_ZN2nn3hid6detail24IsVibrationDeviceMountedEPbRKNS0_21VibrationDeviceHandleE) { *(uint8_t *)GP(ARG(0)) = 1; RET(0); }
HLE(_ZN2nn3hid6detail21EnqueueVibrationValueERKNS0_21VibrationDeviceHandleERKNS0_14VibrationValueE) {
    vibration_send(ARG(0), ARG(1));
    RET(0);
}
HLE(_ZN2nn3hid6detail28FlushEnqueuedVibrationValuesEv) { RET(0); }

/* ---- (mkw-recomp) the touch screen: none touched. GetTouchScreenStates<16>(TouchScreenState<16>*, int count) ->
   states written: one, with no touches (the lifted SDK version read the touch screen's shared memory, which this
   runtime does not have). TouchScreenState<16>: {s64 sampling number, s32 count, s32 reserved, TouchState[16]}. */
HLE(_ZN2nn3hid21InitializeTouchScreenEv) {}
HLE(_ZN2nn3hid20GetTouchScreenStatesILm16EEEiPNS0_16TouchScreenStateIXT_EEEi) {
    static volatile LONG64 sampling;
    if ((int)ARG(1) < 1) { RET(0); return; }
    memset(GP(ARG(0)), 0, 16 + 16 * 0x28);
    G64(ARG(0)) = (uint64_t)InterlockedIncrement64(&sampling);
    RET(1);
}
