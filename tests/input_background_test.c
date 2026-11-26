/* Authored memory, clock and API spies; input_actual.inc contains the unmodified production path. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
#include "input_constants.inc"
/* API spies must not collide with Windows SDK/import-library names. */
#define GetCurrentProcessId fixture_GetCurrentProcessId
#define InterlockedCompareExchange64 fixture_InterlockedCompareExchange64

typedef void *HWND;
typedef uint32_t DWORD;
typedef intptr_t LONG_PTR;
typedef struct { uint64_t x[32]; } Ctx;
enum { GWL_EXSTYLE = -20, WS_EX_TOOLWINDOW = 0x80, WS_EX_NOACTIVATE = 0x8000000,
       VK_MENU = 0x12, VK_RETURN = 0x0d, VK_ESCAPE = 0x1b, VK_LEFT = 0x25, VK_UP, VK_RIGHT, VK_DOWN,
       VK_LBUTTON = 1, VK_RBUTTON = 2, VK_MBUTTON = 4, VK_XBUTTON1 = 5, VK_XBUTTON2 = 6,
       VK_TAB = 0x09, VK_SHIFT = 0x10, VK_CONTROL = 0x11, VK_CAPITAL = 0x14 };   /* (the Walk key row's keys) */
static int front, menu_background, bootstrap_polls, pad_merges, key_queries, mouse_queries, focus_queries, commands;
static int no_window;   /* (no window in front at all: GetForegroundWindow answers NULL) */
typedef int64_t LONG64;
volatile LONG64 hos_present_count = 1000;
static int frame_reads;
LONG64 InterlockedCompareExchange64(volatile LONG64 *p, LONG64 value, LONG64 expected) {
    const LONG64 old = *p;
    frame_reads++;
    if (old == expected) *p = value;
    return old;
}
static int64_t now_ns = 10000000000LL, sampling;
static int key_bind[HOS_KEY_N][2], pad_raw_now;   /* (the keys-only controls after the Switch's buttons) */
/* ((Triforce) 11-24: the ocarina's note layer's words, which host/nn_hid.c keeps beside its bindings: no note wait here
   (hos_oc_wait stays 0) and no note row bound, so nothing is consumed and the game's word is the buttons' own) */
static int pad_bind[HOS_KEY_N][2];   /* (Input 1 and Input 2) */
static uint64_t pad_after_menu;
static uint64_t oc_consumed_pads __attribute__((unused));   /* (read by bound_pad_buttons, a stand-in here) */
static long oc_consumed_keys[256];
static int oc_live;
volatile uint64_t hos_oc_note_bits;
volatile int hos_oc_wait, hos_oc_last_kind;
volatile unsigned hos_oc_beat;
static unsigned char *memory;
static char last_log[256];
volatile int64_t hos_hid_last_read;
volatile int hos_nvn_sync_log_on;
static void *at(uint64_t address) { CHECK(address <= 512 - 8); return memory + address; }
/* (host/hos.h's, over this fixture's 512 bytes: NULL unless all n bytes lie in them) */
static void *hos_guest_range(uint64_t a, uint64_t n) { return a <= 512 && n <= 512 - a ? memory + a : NULL; }
#define GP(a) at(a)
#define G32(a) (*(uint32_t *)at(a))
#define G64(a) (*(uint64_t *)at(a))
#define ARG(n) (c->x[n])
#define RET(value) (c->x[0] = (uint64_t)(value))

/* (the Insert menu's Walk key row and Walk scale, 0 the scale's default, and whether Caps Lock, the row's first key, is held) */
static int walk_row, walk_scale, walk_held;
/* ((Triforce) the "options-back" case: our options open (rx_option 1) over the game's Options screen, the mouse's right
   button held, and the game's Back tapped for it) */
static int options_open, options_front, right_held;
static char tapped[64];
/* (the "held-input" case: the keys and the pad hold only what the case holds, the Z key (ZL's here) and the pad's buttons) */
static int quiet, z_held;
/* (the "menu-side-buttons" case: whether one of the game's menus has the mouse, and Mouse 4, A's here, is held) */
static int game_menu_mouse, side_held;
/* ((Triforce) 11-24, the "deck-mouse" case: the Steam Deck's built-in controls give the input, host/pad_sdl.c's answer;
   the mouse captured, its left button, Y's here, held, and its motion as the right stick) */
static int deck_builtin, mouse_captured, left_held;
static int32_t mouse_motion;
static uint64_t pad_held;
int rx_option(int id, int otherwise) {
    if (id == HOS_OPT_WALK_KEY) return walk_row;
    if (id == 1 && options_open) return 1;
    if (id == HOS_OPT_WALK_SCALE && walk_scale) return walk_scale;
    return id == 4 ? menu_background : id == 1 ? 0 : otherwise;
}
int64_t hos_now_ns(void) { return now_ns; }
void hos_log(const char *format, ...) {
    va_list args; va_start(args, format); vsnprintf(last_log, sizeof last_log, format, args); va_end(args);
}
HWND GetForegroundWindow(void) { focus_queries++; return no_window ? (HWND)0 : (HWND)(uintptr_t)(front ? 1 : 2); }
/* (the program in front, by its file name: production asks Windows) */
static void front_program(DWORD pid, char *name, int size) { (void)pid; snprintf(name, (size_t)size, "fixture.exe"); }
DWORD GetWindowThreadProcessId(HWND window, DWORD *pid) { *pid = window == (HWND)(uintptr_t)1 ? 10 : 20; return 1; }
DWORD GetCurrentProcessId(void) { return 10; }
LONG_PTR GetWindowLongPtrA(HWND window, int index) { (void)window; (void)index; return 0; }
int GetClassNameA(HWND window, char *text, int size) { (void)window; return snprintf(text, (size_t)size, "fixture"); }
short GetAsyncKeyState(int key) {
    key_queries++;
    if (quiet) return (z_held && key == 'Z') || (side_held && key == VK_XBUTTON1) || (left_held && key == VK_LBUTTON) ? (short)-32768 : 0;
    return key == 'P' || key == 'D' || (walk_held && key == VK_CAPITAL) || (right_held && key == VK_RBUTTON) ? (short)-32768 : 0;
}
int hos_sdl_pads(uint64_t *buttons, int32_t stick[4]) {
    bootstrap_polls++; *buttons = 1ULL << B_Y; stick[0] = -31000; return 1;
}
int hos_sdl_pads_deck_builtin(void) { return deck_builtin; }   /* (host/pad_sdl.c's: the "deck-mouse" case) */
int vr_session_on(void) { return 0; }   /* ((Triforce VR) host/vr_game.c's: no headset here */
/* (the pads' inputs still held after the Insert menu: none here, pad_raw_now staying 0, so the bindings are never asked) */
static uint64_t pad_raw_game;
static uint64_t bound_pad_buttons(uint64_t raw) { (void)raw; CHECK(!"no pad input was held after the menu"); return 0; }
void pads_read(uint64_t *buttons, int32_t stick[4]) {
    /* The physical backend boundary is a spy; actual routing merges its result with the script below. */
    if (quiet) { pad_merges++; *buttons |= pad_held; return; }
    pad_merges++; *buttons |= 1ULL << B_B; stick[0] = -12000; stick[2] = 8000;
}
void binds_load(void) {
    key_bind[B_X][0] = 'P', key_bind[B_ZL][0] = 'Z';
    key_bind[B_A][1] = VK_XBUTTON1;   /* (Mouse 4 on A, for the "menu-side-buttons" case; held in no other) */
    key_bind[B_Y][1] = VK_LBUTTON;    /* (the mouse's left button on Y, as out of the box, for the "deck-mouse" case) */
    /* (the left stick's and the camera's keys are bindings too: the defaults, WASD and the arrows) */
    key_bind[HOS_KEY_MOVE_UP][0] = 'W', key_bind[HOS_KEY_MOVE_DOWN][0] = 'S', key_bind[HOS_KEY_MOVE_LEFT][0] = 'A';
    key_bind[HOS_KEY_MOVE_RIGHT][0] = 'D', key_bind[HOS_KEY_CAM_UP][0] = VK_UP, key_bind[HOS_KEY_CAM_DOWN][0] = VK_DOWN;
    key_bind[HOS_KEY_CAM_LEFT][0] = VK_LEFT, key_bind[HOS_KEY_CAM_RIGHT][0] = VK_RIGHT;
    pad_bind[HOS_KEY_TOGGLE_HUD][0] = pad_bind[HOS_KEY_TOGGLE_HUD][1] = -1;   /* ((Triforce) Toggle HUD unbound, as out of the box) */
}
/* ((Triforce) host/hos_wide_ui.c's: Toggle HUD is unbound here, so never pressed) */
void hos_gameplay_hud_toggle(void) { CHECK(!"Toggle HUD pressed with nothing bound to it"); }
/* the native mouse look (no camera found: the motion goes to mouse_stick) and the mouse's sensitivity, which
   read_input calls */
int hos_mouse_native(void) { return -1; }
int hos_mouse_in_game_menu(void) { return game_menu_mouse; }   /* (host/display.c's) */
void hos_mouse_native_free(int free) { (void)free; }
/* ((Triforce, 11-22) whether the right stick turns the camera, told after every read: behind another window too, where the
   pads alone turned it, and the native mouse put the angles back each frame) */
static int native_held = -1;
void hos_mouse_native_stick(int held) { native_held = held; }
static void mouse_setup(void) {}
static void mouse_sens_keys(void) {}
int mouse_stick(int32_t *x, int32_t *y, int held) { (void)y; (void)held; mouse_queries++; *x = mouse_motion; return mouse_captured; }
/* (the options tabs inside the game's own Options screen, which read_input looks at: never open here, so the Back it
   would tap for the game is never asked for) */
int hos_binding(int set, int button, int slot) { (void)set; (void)button; (void)slot; return -1; }
void hos_prompts_live(void) {}   /* ((Triforce) host/prompts.c: the button prompts follow the controls) */
volatile int hos_prompts_row = -1;   /* (host/prompts.c: "!prompts" in the live input) */
void hos_bind(int set, int button, int slot, int code) { (void)set, (void)button, (void)slot, (void)code; }   /* ("!bind") */
int hos_oot_options_front(void) { return options_front; }
/* (the sprint button, which takes its press out of the buttons while Link plays: off here; and the pipeline crawl's
   lines of a live script, which no case writes) */
void hos_oot_sprint_pad(uint64_t *buttons) { (void)buttons; }
void hos_oot_live_crawl(const char *line) { (void)line; CHECK(!"unexpected crawl line"); }
void hos_hid_tap(const char *press) { CHECK(options_front && "unexpected tap of the game's Back"); snprintf(tapped, sizeof tapped, "%s", press); }
void rx_request_frame_dump(void) { commands++; }
void rx_set_screenshot_ms(int64_t ms) { (void)ms; commands++; }
void rx_request_rdoc_capture(int frames) { (void)frames; commands++; }
void rx_flash_dark_arm(void) { commands++; }
/* ((Triforce) host/input_movie.c: no recording and no playback here: every read is the player's, and each one is offered
   to the recording once) */
#include "../host/input_movie.h"
static int movie_begins, movie_ends;
int hos_input_movie_begin(MoviePad *given) { (void)given; movie_begins++; return 0; }
void hos_input_movie_end(const MoviePad *p) { (void)p; movie_ends++; CHECK(movie_ends == movie_begins); }

#include "input_actual.inc"

static void packet(uint64_t buttons, int32_t lx, int32_t ly, int32_t rx) {
    static int64_t expected_sampling;
    Ctx context = {{0}};
    context.x[0] = 64; context.x[1] = 2; context.x[2] = 16; context.x[30] = 0x1234;
    G32(16) = NPAD_NO1;
    memset(memory + 64, 0xa5, 2 * STATE_SIZE + 8);
    native_held = -1;
    npad_states(&context);
    CHECK(context.x[0] == 2);
    CHECK(native_held == (rx != 0));   /* (the stick the game is given, told to the native mouse, the window in front or not) */
    expected_sampling++;
    for (int i = 0; i < 2; i++) {
        const uint64_t address = 64 + (uint64_t)i * STATE_SIZE;
        CHECK(G64(address) == (uint64_t)(expected_sampling - i));
        CHECK(G64(address + 8) == buttons);
        CHECK((int32_t)G32(address + 16) == lx && (int32_t)G32(address + 20) == ly);
        CHECK((int32_t)G32(address + 24) == rx && G32(address + 28) == 0);
        CHECK(G32(address + 32) == ATTR_CONNECTED && G32(address + 36) == 0);
    }
    for (int i = 0; i < 8; i++) CHECK(memory[64 + 2 * STATE_SIZE + i] == 0xa5);
    CHECK(commands == 0);
    CHECK(hos_npad_buttons == buttons);   /* (the mods' cheats see the buttons the game was given: host/mod_cheats.c) */
}

static void append_live(const char *text) {
    const char *path = getenv("HOS_INPUT_LIVE"); CHECK(path);
    FILE *file = fopen(path, "ab"); CHECK(file);
    CHECK(fputs(text, file) >= 0 && fclose(file) == 0);
}

static void frame_clock_case(const char *name) {
    const int hold = !strcmp(name, "frame-hold");
    const int live = !strcmp(name, "live-frame");
    const int reuse = !strcmp(name, "reuse-frame");
    const int wall = !strcmp(name, "wall") || !strcmp(name, "zero") || !strcmp(name, "empty");
    CHECK(hold || live || reuse || wall);
    front = hold || wall;
    packet(hold || wall ? 1ULL << B_A : 0, 0, hold || wall ? 32767 : 0, 0);
    if (hold) {
        now_ns += 7000000000LL; /* no native present returns during a compile */
        packet(1ULL << B_A, 0, 32767, 0);
        CHECK(hos_hid_last_read == now_ns); /* HID diagnostics stay wall-clock */
        hos_present_count = 1011;
        packet(1ULL << B_A, 0, 32767, 0);
        hos_present_count = 1012; /* exactly 200 virtual ms, relative to initial frame 1000 */
        packet(0, 0, 0, 0);
        CHECK(pad_merges == 0 && key_queries == 0 && mouse_queries == 0);
        hos_present_count = 1311;
        packet(0, 0, 0, 0); /* exclusive margin still held at 5183 ms */
        hos_present_count = 1312;
        packet((1ULL << B_B) | (1ULL << B_X), 32767, 0, 8000);
        CHECK(pad_merges > 0 && frame_reads > 0);
    } else if (wall) {
        now_ns += 7000000000LL;
        packet((1ULL << B_B) | (1ULL << B_X), 32767, 0, 8000);
        CHECK(pad_merges > 0 && frame_reads == 0);
    } else if (live) {
        append_live("0:A+LUP/200"); now_ns += 30000000;
        packet(0, 0, 0, 0); /* incomplete live line remains unconsumed */
        hos_present_count = 1060;
        append_live("\n"); now_ns += 30000000;
        packet(1ULL << B_A, 0, 32767, 0);
        CHECK(presses[0].start_ms == 1000 && presses[0].end_ms == 1200);
        append_live("0:B/200\n"); now_ns += 5000000;
        packet(1ULL << B_A, 0, 32767, 0); /* file polling stays on the 30 ms wall clock */
        now_ns += 30000000;
        packet((1ULL << B_A) | (1ULL << B_B), 0, 32767, 0);
        CHECK(presses[1].start_ms == 1000);
        now_ns += 7000000000LL;
        packet((1ULL << B_A) | (1ULL << B_B), 0, 32767, 0);
        hos_present_count = 1072;
        packet(0, 0, 0, 0);
    } else {
        for (int i = 0; i < MAX_PRESSES; i++) CHECK(parse_presses("0:A/200", 0, 1) == 1);
        now_ns += 7000000000LL;
        CHECK(parse_presses("0:B/200", 0, 1) == 0);
        hos_present_count = 1012;
        CHECK(parse_presses("0:B/200", 200, 1) == 0); /* original strict reuse boundary */
        hos_present_count = 1013;
        CHECK(parse_presses("0:B/200", 216, 1) == 1);
        packet(1ULL << B_B, 0, 0, 0);
        CHECK(npresses == MAX_PRESSES);
    }
    CHECK(bootstrap_polls == 1);
}

int main(int argc, char **argv) {
    CHECK(argc == 2);
    CHECK(!pads_in_background(NULL, 0));   /* out of the box: the window in front only */
    CHECK(pads_in_background(NULL, 1));    /* the menu's row */
    CHECK(pads_in_background("1", 0));     /* HOS_INPUT_BACKGROUND=1 without the menu */
    CHECK(!pads_in_background("0", 1));    /* HOS_INPUT_BACKGROUND=0 wins over the menu */
    memory = calloc(512, 1); CHECK(memory);
    const char *name = argv[1];
    if (!strcmp(name, "frame-hold") || !strcmp(name, "live-frame") || !strcmp(name, "reuse-frame") ||
        !strcmp(name, "wall") || !strcmp(name, "zero") || !strcmp(name, "empty")) {
        frame_clock_case(name);
        printf("PASS: actual input frame clock %s\n", name);
        free(memory);
        return 0;
    }
    if (!strcmp(name, "no-window")) {
        /* No window is in front for a moment, with the game's in front before it: the pads and the keys still count. For
           longer than a quarter of a second nothing counts, and everything counts again once the game's window is back */
        const uint64_t held = (1ULL << B_B) | (1ULL << B_X);
        front = 1;
        packet((1ULL << B_A) | held, 32767, 32767, 8000);
        now_ns += 201000000;
        no_window = 1;
        packet(held, 32767, 0, 8000);
        const int merges = pad_merges, keys = key_queries;
        now_ns += 251000000;
        packet(0, 0, 0, 0);
        CHECK(pad_merges == merges && key_queries == keys);
        CHECK(strstr(last_log, "game window not in front"));
        no_window = 0;
        now_ns += 3000000;
        packet(held, 32767, 0, 8000);
        CHECK(strstr(last_log, "was not in front for"));
        CHECK(bootstrap_polls == 1);
        printf("PASS: no window in front for a moment keeps the input %s\n", name);
        free(memory);
        return 0;
    }
    if (!strcmp(name, "options-back")) {
        /* (Triforce) Our tabs open inside the game's own Options screen, left: with the mouse's right button held (the menu's
           Back, as Esc is) the game's Back is tapped for it, as for the pad's B and Esc; left with nothing held (L or R, a
           click on the game's own tab), no tap */
        front = 1, options_front = 1;
        Ctx context = {{0}};
        for (int step = 0; step < 6; step++) {
            options_open = step == 1 || step == 4, right_held = step >= 4;
            context.x[0] = 64, context.x[1] = 2, context.x[2] = 16, context.x[30] = 0x1234;
            G32(16) = NPAD_NO1;
            npad_states(&context);
            now_ns += 16666667;
            if (step == 2) CHECK(tapped[0] == 0);
        }
        CHECK(!strcmp(tapped, "0:B/80"));
        printf("PASS: our tabs left with the right button are the game's Back too %s\n", name);
        free(memory);
        return 0;
    }
    if (!strcmp(name, "walk")) {
        /* (Triforce) The Walk key row. The script holds A and the left stick up; the pad holds B and its stick 12000 to
           the left; the keys hold P (X) and D (move right). Off, D pushes the stick all the way. Caps Lock chosen and not
           held: the same. Held: D pushes it 0.51 of the way, the row's default, and the script's push up is as it was;
           0.90 the same way; at 0.20 the pad's 12000 is the further of the two and is what the game gets, as of any two
           sticks. Off again with the key still held: all the way */
        const uint64_t all = (1ULL << B_A) | (1ULL << B_B) | (1ULL << B_X);
        front = 1;
        packet(all, 32767, 32767, 8000);
        walk_row = 1;
        packet(all, 32767, 32767, 8000);
        walk_held = 1;
        packet(all, 16711, 32767, 8000);
        walk_scale = 90;
        packet(all, 29490, 32767, 8000);
        walk_scale = 20;
        packet(all, -12000, 32767, 8000);
        walk_row = 0;
        packet(all, 32767, 32767, 8000);
        walk_row = 2, walk_scale = 0;   /* (Shift is the walk key, and it is Caps Lock that is held: no walk) */
        packet(all, 32767, 32767, 8000);
        CHECK(bootstrap_polls == 1);
        printf("PASS: the walk key scales the movement keys' stick alone %s\n", name);
        free(memory);
        return 0;
    }
    if (!strcmp(name, "menu-side-buttons")) {
        /* While one of the game's menus has the mouse (the capture gone to it), a side button bound to A is still A, as
           a key is: it confirmed nothing in the text box's choices. Free in play (no menu, no capture) it is no control;
           one held as the menu takes the mouse counts only after it was let go. Through the real read_input */
        const uint64_t a = 1ULL << B_A;
        front = quiet = 1;
        packet(0, 0, 0, 0);
        side_held = 1; packet(0, 0, 0, 0);          /* the mouse free in play: no control */
        game_menu_mouse = 1; packet(0, 0, 0, 0);    /* held as the menu opens: not until let go */
        side_held = 0; packet(0, 0, 0, 0);
        side_held = 1; packet(a, 0, 0, 0);          /* pressed in the menu: A */
        packet(a, 0, 0, 0);
        side_held = 0; packet(0, 0, 0, 0);
        game_menu_mouse = 0; side_held = 1; packet(0, 0, 0, 0);   /* the menu closed, the mouse free again: no control */
        side_held = 0; packet(0, 0, 0, 0);
        printf("PASS: the mouse's side buttons stay their controls' while one of the game's menus has the mouse %s" "%c", name, 10);
        free(memory);
        return 0;
    }
    if (!strcmp(name, "deck-mouse")) {
        /* The Steam Deck's built-in controls show the system a mouse as well as the pad (in Steam's Desktop layout R2 is
           a left click, L2 a right one, and the right stick moves it), so a control bound to a mouse button fired twice,
           once from the pad and once from that click. While those controls give the input the mouse's buttons are no
           control's and its motion steers nothing; it is still taken in, and one of the game's menus keeps its side
           buttons. Any other pad, and a PC without a Steam Deck's controls, as before. Through the real read_input */
        const uint64_t a = 1ULL << B_A, y = 1ULL << B_Y;
        front = quiet = mouse_captured = 1;
        packet(0, 0, 0, 0);
        left_held = 1; packet(y, 0, 0, 0);            /* an ordinary pad: the left button is Y, as its binding says */
        mouse_motion = 20000; packet(y, 0, 0, 20000); /* and the mouse's motion is the camera's */
        pad_held = a; deck_builtin = 1;
        int before = mouse_queries;
        packet(a, 0, 0, 0);                           /* the Deck's own controls: the click is not Y, the motion not the camera's */
        CHECK(mouse_queries > before);                /* (the pointer still taken in) */
        left_held = 0; packet(a, 0, 0, 0);            /* let go and pressed again while they give the input: still nothing */
        left_held = 1; packet(a, 0, 0, 0);
        pad_held = 0; deck_builtin = 0;
        packet(0, 0, 0, 20000);                       /* the controls go, the button held through: let go first */
        left_held = 0; packet(0, 0, 0, 20000);
        left_held = 1; packet(y, 0, 0, 20000);
        left_held = 0; mouse_motion = 0; packet(0, 0, 0, 0);
        deck_builtin = 1; mouse_captured = 0; game_menu_mouse = 1;   /* one of the game's menus has the mouse: */
        packet(0, 0, 0, 0);
        side_held = 1; packet(a, 0, 0, 0);            /* its side button is still A's there, the Deck's controls or not */
        side_held = 0; packet(0, 0, 0, 0);
        deck_builtin = 0; game_menu_mouse = 0;
        printf("PASS: a Steam Deck's built-in controls give their actions once, not again through the mouse they also show %s" "%c", name, 10);
        free(memory);
        return 0;
    }
    if (!strcmp(name, "held-input")) {
        /* The player's input hides the game menus' cursor until the mouse moves (host/display.c gm_cursor_shown), so an
           input counts when it goes down, not at every read while it stays down: the ocarina's song sheet is open while ZL
           is held, and a ZL held on a pad or the Z key counted at every read, so the cursor the mouse had just shown was
           hidden again before the menu used it and its hover failed. Through the real read_input */
        const uint64_t zl = 1ULL << B_ZL, l = 1ULL << B_L;
        front = quiet = 1;
        packet(0, 0, 0, 0); CHECK(player_stamps == 0);
        z_held = 1; packet(zl, 0, 0, 0); CHECK(player_stamps == 1);   /* a key goes down: the player's input */
        for (int i = 0; i < 5; i++) packet(zl, 0, 0, 0);
        CHECK(player_stamps == 1);                                    /* held: not at every read */
        z_held = 0; packet(0, 0, 0, 0); CHECK(player_stamps == 1);    /* let go: not an input */
        z_held = 1; packet(zl, 0, 0, 0); CHECK(player_stamps == 2);   /* down again: one more */
        z_held = 0; packet(0, 0, 0, 0);
        pad_held = zl; packet(zl, 0, 0, 0); CHECK(player_stamps == 3);   /* a pad's button the same */
        for (int i = 0; i < 5; i++) packet(zl, 0, 0, 0);
        CHECK(player_stamps == 3);
        pad_held = zl | l; packet(zl | l, 0, 0, 0); CHECK(player_stamps == 4);   /* a second one, the first held */
        pad_held = l; packet(l, 0, 0, 0); CHECK(player_stamps == 4);
        pad_held = 0; packet(0, 0, 0, 0); CHECK(player_stamps == 4);
        printf("PASS: an input held down is the player's input when it goes down, not at every read %s\n", name);
        free(memory);
        return 0;
    }
    front = !strcmp(name, "foreground") || !strcmp(name, "exclusive-foreground");
    menu_background = !strcmp(name, "pads-menu") || !strcmp(name, "pads-off");
    const int exclusive = !strncmp(name, "exclusive-", 10);
    const int pads = !exclusive && (front || !strcmp(name, "pads-env") || !strcmp(name, "pads-menu"));
    const uint64_t physical = pads ? (1ULL << B_B) | (front ? 1ULL << B_X : 0) : 0;
    if (!strcmp(name, "live-background")) {
        packet(0, 0, 0, 0);
        append_live("0:A+LUP/200"); now_ns += 30000000;
        packet(0, 0, 0, 0); /* incomplete authored line is not consumed */
        append_live("\n"); now_ns += 30000000;
        packet(1ULL << B_A, 0, 32767, 0);
        now_ns += 200000000;
        packet(0, 0, 0, 0); /* consumed once, then released at the actual hold boundary */
    } else if (!strcmp(name, "no-script-background")) {
        packet(0, 0, 0, 0);
    } else {
        packet((1ULL << B_A) | physical, pads ? (front ? 32767 : -12000) : 0, 32767, pads ? 8000 : 0);
        now_ns += 201000000;
        packet(physical, pads ? (front ? 32767 : -12000) : 0, 0, pads ? 8000 : 0);
        if (exclusive) {
            CHECK(pad_merges == 0 && key_queries == 0 && mouse_queries == 0);
            now_ns += 5100000000LL;
            packet(front ? (1ULL << B_B) | (1ULL << B_X) : 0, front ? 32767 : 0, 0, front ? 8000 : 0);
        }
    }
    CHECK(bootstrap_polls == 1); /* production startup poll is allowed, but its Y/stick result is discarded */
    if (!front) {
        CHECK(key_queries == 0 && mouse_queries == 0);
        if (!pads) CHECK(pad_merges == 0);
    }
    if (!strcmp(name, "script-background")) CHECK(strstr(last_log, "game window not in front"));
    if (front) CHECK(pad_merges > 0 && key_queries > 0 && mouse_queries > 0);
    CHECK(focus_queries > 0);
    printf("PASS: actual scripted parse/merge/Npad route %s\n", name);
    free(memory);
    return 0;
}
