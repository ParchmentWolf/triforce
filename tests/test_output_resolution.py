"""Exercise the host and menu's docked output sizes without a game dump.

The rule (gpu/vk/output_sizes.h): the Output resolution is the picture's size, the game's frame 16:9 at its height. A size
that is not 16:9 (5120x1440, 5120x2160, a screen's or a Custom one of such a shape) is a picture of exactly that size,
whatever the Ultrawide row says; a 16:9 size takes the row's shape.

The row offers the fixed sizes and the size of every connected screen, by the monitor's name. A screen's size is saved as
a size (Custom's, output_width= and output_height=), never as a place in the list of screens: the same options file gives
the same picture whichever screens are connected, in whatever order, and a size whose screen is gone is Custom. An old
file's output_res=7 (Screen) is the screen the window opens on, as it was, and the menu keeps it as that size.

host/nn_applet.c's own code (the size, the frame, the shape, the render target pool) and gpu/vk/vk_menu.cpp's (the row's
choices, their texts and order, the picture shown), cut out and run on the same options file and the same screens, must
agree.
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXED = ((2048, 1152), (2560, 1440), (3840, 2160), (1920, 1080), (5120, 1440), (5120, 2880), (5120, 2160), (1536, 864))


def size(text):
    """'3840x1600' as (w, h)"""
    w, h = text.split("x")
    return int(w), int(h)


def names(screens, at):
    """The screens of a size by name: once each, counted where several share one; one without a name is 'Screen'"""
    seen = []
    for used, name in screens:
        if size(used) == at:
            seen.append(name or "Screen")
    return ", ".join(("%dx " % seen.count(n) if seen.count(n) > 1 else "") + n for n in dict.fromkeys(seen))


def row_labels(screens, custom, env=False, legacy=None, remembered=None):
    """The row's choices in its order, by this file's own rule: the fixed sizes (a screen of one of them named there, but not
    at the game's own 2048x1152), each other screen size once, the old Screen while it is still chosen, and Custom unless a
    screen has its size. Smallest to largest by width then height, of one size in that order, one with no size at the end.
    screens: (the size the game takes it at, name); custom: its size, None for none; legacy: the old Screen's size or ''"""
    entries = []
    for v, at in enumerate(FIXED):
        who = "handheld" if v == 7 else names(screens, at) if v else ""
        entries.append((at, "%dx%d" % at + (" (%s)" % who if who else "")))
    own = []
    for used, _ in screens:
        if not env and size(used) not in FIXED[1:7] and size(used) not in own:
            own.append(size(used))
            entries.append((size(used), "%s (%s)" % (used, names(screens, size(used)))))
    if legacy is not None:
        who = names(screens, size(legacy)) if legacy else ""
        entries.append((size(legacy) if legacy else None, ("%s (%s)" % (legacy, who) if who else "Screen (%s)" % legacy) if legacy
                        else "Screen (not known)"))
    if custom is None or size(custom) not in own:
        entries.append((size(custom) if custom else None, "Custom (%s)" % (custom or "not set")))
    if remembered and remembered != custom and size(remembered) not in own:
        entries.append((size(remembered), "Custom (%s)" % remembered))
    entries.sort(key=lambda e: (e[0] is None, e[0] or (0, 0)))   # (stable: of one size as added)
    return "|".join(label for _, label in entries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()

    host = (ROOT / "host/nn_applet.c").read_text(encoding="utf-8")
    menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")

    def check(cond, what):
        if not cond:
            raise SystemExit("FAIL: " + what)

    # the Custom size's rows: output_width= and output_height= by their names, with a restart, shown while Custom or a screen's
    # size is chosen, fixed while HOS_OUTPUT_SIZE sets the size; the file's version says that the 5120-wide sizes are pictures
    for name, value, lo, hi in (("Output width", "output_width", "OUTPUT_MIN_W", "OUTPUT_MAX_W"),
                                ("Output height", "output_height", "OUTPUT_MIN_H", "OUTPUT_MAX_H")):
        row = menu.find('{TAB_DISPLAY, "%s", &opts.%s, %s, %s, 8, ' % (name, value, lo, hi))
        check(row > menu.find('{TAB_DISPLAY, "Output resolution", &opts.output_res') > 0, "the menu has no %s row under Output resolution" % name)
        check(menu[row:menu.index("},", row)].rstrip().endswith("nullptr, true"), "the %s row is not read at the start (a restart)" % name)
    shown = menu[menu.index("bool row_shown(int i) {"):menu.index("\n}\n", menu.index("bool row_shown(int i) {"))]
    check("((rows[i].value != &opts.output_width && rows[i].value != &opts.output_height) ||" in shown
          and "output_choice(opts.output_res) == OUTPUT_CUSTOM) &&" in shown, "the Custom size's rows show without Custom chosen")
    check("if ((value == &opts.output_width || value == &opts.output_height) && custom_env()) return true;" in menu,
          "the Custom size's rows can be changed while HOS_OUTPUT_SIZE sets the size")
    # (10: the keys' Plus alone changed, host/nn_hid.c binds_load; the output numbers' schema is OUTPUT_OPTIONS_VERSION, 9, on)
    check('out += "options_version=10\\n";' in menu, "the options file is not written as version 10 (output_sizes.h OUTPUT_OPTIONS_VERSION and later)")
    check("#define OUTPUT_OPTIONS_VERSION 9" in (ROOT / "gpu/vk/output_sizes.h").read_text(encoding="utf-8"),
          "output_sizes.h: the 5120-wide sizes are not pictures from options_version 8")
    check("rows[i].name != kUseWindowSize || (opts.output_res == OUTPUT_CUSTOM && !custom_env())" in shown
          and "use_window_size(dev.swap_extent.width, dev.swap_extent.height);" in menu,
          "the Custom copy action must use the drawable size and respect the environment override")
    # the row walks its choices, a screen's size among them, and menu_init takes the screens and an old file's Screen
    check('custom_rows_read(side("output_width"), side("output_height"));' in menu[menu.index("void menu_init() {"):],
          "menu_init does not read Custom's size from the file's own two numbers (custom_rows_read)")
    sizes_h = (ROOT / "gpu/vk/output_sizes.h").read_text(encoding="utf-8")
    used = sizes_h[sizes_h.index("static inline int output_size_used("):sizes_h.index("/* output_width= and output_height= as an options file")]
    check("output_width_range(uh, wide, &lo, &hi);" in used and "for (" not in used and "while (" not in used,
          "output_sizes.h: output_size_used does not choose the width in one step from the widths its height allows")
    check("output_custom_read(&w, &h);" in host, "nn_applet.c does not read Custom's size as the menu does (output_custom_read)")
    check("if (!output_step(dir, true)) return;" in menu[menu.index("void set_row(Row& r, int v, int dir, bool keep"):],
          "set_row does not walk the Output resolution row's choices (output_step)")
    init = menu[menu.index("void menu_init() {"):]
    check("screen_add(list[i].w, list[i].h, list[i].name, list[i].opens != 0);" in init and
          init.index("output_adopt_screen();") > init.index("screen_add(list[i].w"), "menu_init does not take the host's screens, then an old file's Screen")
    # (walking the row past a screen's size leaves that size in the Custom rows: no restart is asked for them under a fixed size)
    check("restart_inert(rows[i]) ? restart_state.start[restart_slot[i]] : restart_value_of(rows[i])" in menu,
          "the Custom size's rows ask for a restart while a fixed size is chosen")
    # the screens go from the host to the menu through MkwVkHost, at its end (the interface's version with it)
    api = (ROOT / "gpu/vk/vk_api.h").read_text(encoding="utf-8")
    check("    int (*screens)(MkwVkScreen *out, int cap);\n" in api and api.index("int (*screens)(") > api.index("int (*bench)("),
          "vk_api.h: MkwVkHost has no screens after bench")
    backend = (ROOT / "host/rx_backend.c").read_text(encoding="utf-8")
    check("host_romfs_dir, host_wide_menus, hos_bench_state, hos_prompts_pad_face, host_screens, " in backend,
          "rx_backend.c does not give the menu the host's screens")

    fixture = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iterator>
#include <string>
#include <utility>
#include <vector>
#include "gpu/vk/output_sizes.h"
#include "gpu/vk/ultrawide_rows.h"
#include "host/hos_screens.h"

using DWORD = unsigned long;
constexpr int MAX_PATH = 260;
constexpr int SM_CXSCREEN = 0, SM_CYSCREEN = 1;
// (the connected screens: TEST_SCREENS=<w>x<h>=<name>;..., a '*' before the size of the one the window opens on, else the
// first; none set: no screen known)
int hos_screens(HosScreen *out, int cap) {
    const char *e = getenv("TEST_SCREENS");
    int n = 0, opens = -1;
    std::string all = e ? e : "";
    while (!all.empty() && n < cap) {
        std::string one = all.substr(0, all.find(';'));
        all = all.find(';') == std::string::npos ? "" : all.substr(all.find(';') + 1);
        const bool star = one[0] == '*';
        if (star) one = one.substr(1), opens = n;
        long w = 0, h = 0;
        if (!output_parse_size(one.substr(0, one.find('=')).c_str(), &w, &h)) abort();
        out[n] = HosScreen{(int)w, (int)h, 0, {}};
        snprintf(out[n].name, sizeof out[n].name, "%s", one.find('=') == std::string::npos ? "" : one.substr(one.find('=') + 1).c_str());
        n++;
    }
    if (n) out[opens < 0 ? 0 : opens].opens = 1;
    return n;
}
void hos_screen_size(int *w, int *h) {   // (host/display.c: the one the window opens on)
    HosScreen list[16];
    const int n = hos_screens(list, 16);
    *w = *h = 0;
    for (int i = 0; i < n; i++)
        if (list[i].opens) *w = list[i].w, *h = list[i].h;
}
int GetSystemMetrics(int i) {   // (the main monitor, for an old file's Monitor's shape: the first screen)
    HosScreen list[16];
    return hos_screens(list, 16) ? (i == SM_CYSCREEN ? list[0].h : list[0].w) : 0;
}
DWORD hos_game_path_a(char *path, int size) { return snprintf(path, size, "./hookshot.exe"); }
#include <cstdarg>
static std::string logged;   // (the host's log lines of the run, each ended)
void hos_log(const char *format, ...) {
    char line[600];
    va_list args;
    va_start(args, format);
    vsnprintf(line, sizeof line, format, args);
    va_end(args);
    logged += line, logged += '\n';
}
volatile uint64_t hos_wide_out = 0;   // (host/hos_main.c: the widescreen picture, 0 = none; nn_applet.c reads it)
int hos_scene_rgba16f(void) { return 0; }   // (host/nn_vi.c: the scene's colour target, the game's own here; tests/test_rt_pool_minimum.py has the RGBA16F cases)
struct { int handheld, output_res, output_width, output_height, ultrawide; } opts;
namespace mkwvk {
int up_now = 0;   // (the Upscaler shown: 0 the game's own, 1 DLSS, 2 DLAA)
int upscaler() { return up_now; }
}
#include "gpu/vk/upscaler_rows.h"
#include "gpu/vk/merged_rows.h"   // ((Triforce, options_version 7) the Output resolution's handheld profile, 7)
using namespace mkwvk;
namespace ur = upscaler_rows;
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); failed = 1; } } while (0)
#define CHECK_STR(got, want) do { const std::string g_ = (got), w_ = (want); if (g_ != w_) { \
    fprintf(stderr, "FAIL:%d %s is \"%s\", expected \"%s\"\n", __LINE__, #got, g_.c_str(), w_.c_str()); failed = 1; } } while (0)
static int failed;
static std::string wxh(unsigned w, unsigned h) { return std::to_string(w) + "x" + std::to_string(h); }
// (the second build: the menu's code as it is off Windows, whatever this PC is. After every system header)
#ifdef FIXTURE_OFF_WINDOWS
#undef _WIN32
#endif
''' + host[host.index("int hos_ini_option(const char *key, int otherwise);"):host.index("HLE(_ZN2nn2oe16GetOperationModeEv)")] + menu[
        menu.index("struct Out {"):menu.index("/// The Render resolution: the value chosen")] + menu[
        menu.index("const char* tx_output_res("):menu.index("const char* tx_speed(")] + menu[
        menu.index("const char* tx_ultrawide(int v) {"):menu.index("const char* tx_wide_hud(")] + r'''
struct Row { int* value; };
Row rows[] = {{&opts.output_width}, {&opts.output_height}};
static int saves;
void save() { ++saves; }
void set_row(Row& row, int value, int, bool keep) { *row.value = value; if (keep) save(); }
''' + menu[menu.index("void use_window_size("):menu.index("// ---- (hookshot) the Controls page:")] + r'''
static std::string labels() {
    std::string all;
    for (const OutEntry& x : output_entries()) all += (all.empty() ? "" : "|") + output_label(x);
    return all;
}
int main(int argc, char **argv) {
    assert(argc == 10);
    const int mode = atoi(argv[1]);
    // ---- the host: the size chosen, the game's frame, the size's own shape
    CHECK(output_mode() == mode);
    CHECK_STR(wxh(hos_output_size(0), hos_output_size(1)), argv[2]);
    CHECK_STR(std::to_string((int)(hos_output_ratio() * 10000.0f + 0.5f)), argv[5]);
    // (the picture as host/hos_main.c makes it: the size's own shape, else the Ultrawide row's; tests/test_ultrawide_shapes.py
    // runs that block itself)
    const int version = hos_ini_option("options_version", 0);
    const int row = ultrawide_row_read(hos_ini_option("ultrawide", 0), version, GetSystemMetrics(SM_CXSCREEN), GetSystemMetrics(SM_CYSCREEN));
    unsigned pw = 0, ph = 0;
    const float own = hos_output_ratio();
    if (output_picture(hos_output_size(1), own > 0.0f ? own : ultrawide_row_ratio(row), own > 0.0f, &pw, &ph))
        hos_wide_out = (uint64_t)ph << 32 | pw;
    const std::string picture = pw ? wxh(pw, ph) : std::string(mode ? argv[2] : "2048x1152");
    if (mode) CHECK_STR(picture, argv[8]);
    CHECK_STR(std::to_string(hos_rt_pool_size(305ull << 20) >> 20), argv[4]);   // (512 MB at least: nn_applet.c)
    // (TEST_LOG pins the explanation of an older file's migrated choice or picture)
    if (const char* want = getenv("TEST_LOG")) {
        if (logged.find(want) == std::string::npos) fprintf(stderr, "FAIL: the log has no \"%s\":\n%s", want, logged.c_str()), failed = 1;
    }

    // ---- the menu, as menu_init has it from the same file and the same screens
    opts.handheld = handheld();
    // (Custom's rows from the file's own two numbers, 0 with no line: menu_init)
    custom_rows_read(hos_ini_option("output_width", 0), hos_ini_option("output_height", 0));
    HosScreen list[16];
    const int n = hos_screens(list, 16);
    for (int i = 0; i < n; i++) screen_add(list[i].w, list[i].h, list[i].name, list[i].opens != 0);
    // (an old file's Ultrawide row by the main monitor, the host's on every system: main_screen)
    opts.ultrawide = ultrawide_row_read(std::min(std::max(hos_ini_option("ultrawide", 0), 0), 3), version, (int)main_screen().w, (int)main_screen().h);
    CHECK(opts.ultrawide == std::min(std::max(row, 0), 3));
    opts.output_res = output_file_read(hos_ini_option("output_res", 0), version, opts.ultrawide, output_size_fields());
    if (const char* e = getenv("HOS_OUTPUT_RES")) opts.output_res = output_choice(atoi(e));
    if (opts.handheld) opts.output_res = 7;
    output_adopt_screen();
    CHECK(kLastOutput == 9);
    CHECK(output_choice(-1) == 0 && output_choice(4) == 4 && output_choice(6) == 6 && output_choice(7) == 7 && output_choice(8) == 8 && output_choice(9) == 9 && output_choice(10) == 0);
    // (the row's choices, smallest to largest: the fixed sizes, the screens' among them by name, Custom; and the one chosen)
    CHECK_STR(labels(), argv[6]);
    CHECK_STR(tx_output_res(opts.output_res), argv[3]);
    // (the menu's choice runs what the host runs: its frame and its picture, the Render resolution's 100%)
    if (!opts.handheld) {
        CHECK_STR(wxh(output_frame(opts.output_res).w, output_frame(opts.output_res).h), mode ? argv[2] : "2048x1152");
        CHECK(output_shaped(opts.output_res) == (own > 0.0f));
    }
    unsigned scene_w, scene_h;
    game_size(1.0f, scene_w, scene_h);
    CHECK_STR(wxh(scene_w, scene_h), argv[8]);
    CHECK_STR(tx_shape(opts.ultrawide), argv[7]);   // (the Ultrawide row: its choice, or the size's own shape)
    CHECK(shape_owner() == (own > 0.0f ? 1 : 0));
    // (the Custom rows: their sides as chosen, HOS_OUTPUT_SIZE's while it is set; the size the game makes of them is the row's)
    CHECK_STR(std::string(tx_custom_width(opts.output_width)) + "x" + tx_custom_height(opts.output_height), argv[9]);
    if (mode == 3 && !pw) CHECK_STR(tx_resolution(2), "75% (1440x810)");
    if (mode == 3 && !pw) {   // (DLSS at 1080p: its modes' render sizes, each a twelfth of the output, exact; DLAA the full size)
        up_now = ur::DLSS;
        CHECK(strcmp(tx_resolution(3), "Quality (67%)") == 0 && strcmp(tx_resolution(6), "Ultra Performance (33%)") == 0);
        const unsigned want[][3] = {{3, 1280, 720}, {5, 1120, 630}, {4, 960, 540}, {6, 640, 360}};
        for (const auto& m : want) {
            game_size(ur::percent(m[0]) / 100.0f, scene_w, scene_h);
            CHECK(scene_w == m[1] && scene_h == m[2] && scene_w * 1080 == scene_h * 1920);
        }
        up_now = ur::DLAA;   // ((Triforce, options_version 7) the Render resolution's Native (100%) step)
        CHECK(strcmp(tx_resolution(1), "Native (100%)") == 0);
        up_now = ur::GAME;
    }
    if (pw == 3840 && ph == 1600) CHECK_STR(tx_resolution(2), "75% (2880x1200)");   // (the 3D's size is the picture's share)

    // ---- a size from outside keeps its shape (5:4 to 48:9) whatever its sides, stays within every limit and on its side of
    // 16:9, and what comes out is taken as itself when given again (the menu saves it and the host reads it back): at once,
    // by how its width is chosen (output_width_range), with no second try
    for (long w = 200; w <= 12000; w += 61)
        for (long h = 120; h <= 6000; h += 37) {
            unsigned uw = 0, uh = 0, vw = 0, vh = 0;
            CHECK(output_size_used(w, h, &uw, &uh) && output_size_used(uw, uh, &vw, &vh));
            const double in = std::min(std::max((double)w / h, OUTPUT_SHAPE_MIN), OUTPUT_SHAPE_MAX), out = (double)uw / uh;
            const bool side = output_shape_is_game(in) ? output_shape_is_game(out)
                                                       : !output_shape_is_game(out) && (in > 16.0 / 9.0) == (out > 16.0 / 9.0);
            if (uw != vw || uh != vh || uw % 8 || uw < OUTPUT_MIN_W || uw > OUTPUT_MAX_W || uh < OUTPUT_MIN_H || uh > OUTPUT_MAX_H ||
                (double)uw * uh > OUTPUT_MAX_PIXELS || std::fabs(out / in - 1.0) > 0.011 ||   // (8 pixels of width, or 16:9's 1%)
                out > OUTPUT_SHAPE_MAX || out < OUTPUT_SHAPE_MIN || !side) {
                fprintf(stderr, "FAIL: %ldx%ld is taken as %ux%u (again: %ux%u)\n", w, h, uw, uh, vw, vh);
                failed = 1;
            }
        }
    {
        unsigned uw = 0, uh = 0;
        CHECK(output_size_used(7680, 4320, &uw, &uh) && uw == 5120 && uh == 2880);   // (not 7680x2880's 2.67:1)
        CHECK(output_size_used(3840, 1600, &uw, &uh) && uw == 3840 && uh == 1600);
        CHECK(!output_size_used(0, 1440, &uw, &uh) && !output_size_used(2560, -1, &uw, &uh));
    }

    // ---- walking the row: each step is the next choice of the row as it is then, to both ends; a screen's size is taken as
    // Custom's size (a size, not a place among the screens), a fixed size as its number
    for (int dir = -1; dir <= 1; dir += 2) {
        for (int guard = 0; guard < 64; guard++) {
            const std::vector<OutEntry> before = output_entries();
            const int at = output_entry_now(before);
            CHECK(output_step(dir, false) == (dir < 0 ? at > 0 : at + 1 < (int)before.size()));
            if (!output_step(dir, true)) break;
            const OutEntry& to = before[at + dir];
            CHECK_STR(tx_output_res(opts.output_res), output_label(to));
            CHECK(opts.output_res == to.id);
            if (to.native.h) {
                CHECK(opts.output_res == OUTPUT_CUSTOM && custom_size().w == to.size.w && custom_size().h == to.size.h);
                // (saved as the game takes it: what the rows hold is the picture, and reads back as itself)
                CHECK(opts.output_width == (int)to.size.w && opts.output_height == (int)to.size.h);
            }
        }
        CHECK(!output_step(dir, false));
    }
    // A non-rounded input survives a screen selection, restart and unplug. The disconnected
    // picture continues to use the saved screen size until the player chooses Custom again.
    if (!custom_env()) {
        screens.clear();
        screen_add(3840, 1600, "Monitor", true);
        opts.output_res = OUTPUT_CUSTOM;
        remembered_custom = {};
        custom_rows_read(3437, 1440);
        CHECK(output_step(1, true));
        CHECK(opts.output_width == 3840 && opts.output_height == 1600);
        CHECK(remembered_custom.w == 3437 && remembered_custom.h == 1440);
        remembered_custom = {};
        opts.output_res = 2;
        read_remembered_custom("3437x1440");
        CHECK(remembered_custom.w == 3437 && remembered_custom.h == 1440);
        screens.clear();
        CHECK(labels().find("Custom (3840x1600)") == std::string::npos);
        CHECK(labels().find("Custom (3440x1440)") != std::string::npos);
        opts.output_res = OUTPUT_CUSTOM;
        screens.clear();
        CHECK_STR(tx_output_res(opts.output_res), "Custom (3840x1600)");
        CHECK(output_step(-1, true));
        CHECK(opts.output_width == 3437 && opts.output_height == 1440 && !remembered_custom.h);
        use_window_size(0, 1080);
        CHECK(!saves && opts.output_width == 3437 && opts.output_height == 1440);
        use_window_size(7680, 4320);
        CHECK(saves == 1 && opts.output_width == 5120 && opts.output_height == 2880);
        use_window_size(3840, 1600);
        CHECK(saves == 2 && opts.output_width == 3840 && opts.output_height == 1600);
    }
    return failed;
}
'''
    v8 = "options_version=9\n"
    lg, dell = "LG ULTRAGEAR", "DELL U2720Q"

    def case(saved, mode, frame, now, pool, *, picture=None, shape=0, row="16:9", ini="", handheld=0, res=None, screens=(),
             env_size=None, custom="2560x1440", rows=None, legacy=None, log=None, remembered="2560x1440"):
        """saved, handheld, HOS_OUTPUT_RES, the screens ((native size, name) or (native, name, the size the game takes it
        at), a '*' before the native size of the one the window opens on), the ini's other lines, HOS_OUTPUT_SIZE -> the
        host's mode and frame, the row's text now, the pool in MB, the size's own shape x 10000, the Ultrawide row's text,
        the picture, Custom's size as the game takes it (None: none), the Custom rows' texts, the old Screen still chosen,
        and an optional migration log expectation; remembered is Custom's saved size before adopting Screen"""
        # Cases retain the audited branch's numbering in their declarations.
        # Current fixtures use 8/9; old-version fixtures exercise migration from 7/8.
        old_screen = res == "7" or res is None and saved == 7
        if ini.startswith("options_version=9") and saved in (7, 8): saved += 1
        if mode in (7, 8): mode += 1
        if res in ("7", "8"): res = str(int(res) + 1)
        if handheld: now, custom = "1536x864 (handheld)", "2560x1440"
        used = [(s[2] if len(s) > 2 else s[0].lstrip("*"), s[1]) for s in screens]
        return (saved, handheld, res, ";".join(s[0] + ("=" + s[1] if s[1] else "") for s in screens), ini, env_size, mode, frame, now,
                pool, shape, row_labels(used, custom, env_size is not None, legacy,
                                        remembered if old_screen and not handheld and env_size is None
                                        and now.split(" (")[0] not in ("%dx%d" % f for f in FIXED[1:7]) and screens else None), row,
                picture or ("2048x1152" if mode == 0 else frame), rows or custom or "Not setxNot set", log)

    cases = (
        # ---- the fixed 16:9 sizes: the game's frame, and its picture with Ultrawide on 16:9
        case(0, 0, "2560x1440", "2048x1152", 512, ini=v8),
        # A monitor at the handheld profile's size is still a docked Custom picture.
        case(7, 7, "1536x864", "1536x864 (Screen)", 512, ini=v8,
             screens=[("1536x864", "")], custom="1536x864"),
        case(1, 1, "2560x1440", "2560x1440", 512, ini=v8),
        case(2, 2, "3840x2160", "3840x2160", 687, ini=v8),
        case(3, 3, "1920x1080", "1920x1080", 512, ini=v8),
        case(1, 3, "1920x1080", "1920x1080", 512, ini=v8, res="3"),
        # (the handheld profile runs the game's own output; the row keeps the choice for docked)
        case(3, 0, "2560x1440", "1920x1080", 512, ini=v8, res="3", handheld=1, picture="1536x864"),
        case(4, 0, "2560x1440", "5120x1440", 512, ini=v8, handheld=1, picture="1536x864"),
        case(10, 0, "2560x1440", "2048x1152", 512, ini=v8),
        case(5, 5, "5120x2880", "5120x2880", 900, ini=v8),
        # (a 16:9 size takes the Ultrawide row's shape at its height: 21:9 is 64:27 in whole multiples of 8 pixels; at the 4K
        # output a 32:9 picture is kept to 3840x2160's pixels, as before)
        case(1, 1, "2560x1440", "2560x1440", 512, ini=v8 + "ultrawide=2\n", picture="3416x1440", row="21:9"),
        case(3, 3, "1920x1080", "1920x1080", 512, ini=v8 + "ultrawide=1\n", picture="1728x1080", row="16:10"),
        case(2, 2, "3840x2160", "3840x2160", 687, ini=v8 + "ultrawide=3\n", picture="5400x1520", row="32:9"),
        case(0, 0, "2560x1440", "2048x1152", 610, ini=v8 + "ultrawide=3\n", picture="4096x1152", row="32:9"),
        # ---- the fixed sizes that are not 16:9: the picture itself, the frame 16:9 at its height, whatever the row says
        case(4, 4, "2560x1440", "5120x1440", 610, ini=v8, picture="5120x1440", shape=35556, row="32:9 (5120x1440)"),
        case(6, 6, "3840x2160", "5120x2160", 900, ini=v8, picture="5120x2160", shape=23704, row="21:9 (5120x2160)"),
        case(1, 6, "3840x2160", "5120x2160", 900, ini=v8, res="6", picture="5120x2160", shape=23704, row="21:9 (5120x2160)"),
        case(4, 4, "2560x1440", "5120x1440", 610, ini=v8 + "ultrawide=2\n", picture="5120x1440", shape=35556,
             row="32:9 (5120x1440)"),
        # (a file from before options_version 8, where they were the game's frame: with the row on their own shape or on 16:9
        # they stay, the picture theirs; with the row on another shape the 16:9 size of their height, the same picture)
        case(4, 4, "2560x1440", "5120x1440", 610, ini="options_version=7\nultrawide=3\n", picture="5120x1440", shape=35556,
             row="32:9 (5120x1440)"),
        case(4, 4, "2560x1440", "5120x1440", 610, ini="options_version=7\n", picture="5120x1440", shape=35556,
             row="32:9 (5120x1440)"),
        case(4, 1, "2560x1440", "2560x1440", 512, ini="options_version=7\nultrawide=2\n", picture="3416x1440", row="21:9",
             log="oe: output resolution 5120x1440 with Ultrawide on another shape, from before options_version 9: "
                 "2560x1440 now, the same picture"),
        case(6, 6, "3840x2160", "5120x2160", 900, ini="options_version=7\nultrawide=2\n", picture="5120x2160", shape=23704,
             row="21:9 (5120x2160)"),
        case(6, 2, "3840x2160", "3840x2160", 687, ini="options_version=7\nultrawide=3\n", picture="5400x1520", row="32:9"),
        case(6, 2, "3840x2160", "3840x2160", 687, ini="options_version=7\nultrawide=1\n", picture="3456x2160", row="16:10"),
        # (before options_version 6 the row's 1 was the monitor's shape: on a 5120x1440 monitor 32:9, 5120x1440's own; the
        # screen of a fixed size is named at that size)
        case(4, 4, "2560x1440", "5120x1440 (Screen)", 610, ini="options_version=5\nultrawide=1\n", screens=[("5120x1440", "")],
             picture="5120x1440", shape=35556, row="32:9 (5120x1440)"),
        # (the same row at a 16:9 size, on a 3440x1440 monitor: 21:9 for the host and for the menu, on every system)
        case(1, 1, "2560x1440", "2560x1440", 512, ini="options_version=5\nultrawide=1\n", screens=[("3440x1440", lg)],
             picture="3416x1440", row="21:9"),

        # Stock 0.7 ignores the retired profile line at version 8; native 0.6's version 9 still carries it.
        case(1, 1, "2560x1440", "2560x1440", 512, ini="options_version=8\nhandheld_profile=1\n"),
        # Native 0.5.2's numbers move past stock 0.6's handheld without changing the choice or picture.
        case(8, 8, "2848x1600", "Custom (3840x1600)", 512,
             ini="options_version=8\noutput_width=3840\noutput_height=1600\n", picture="3840x1600", shape=24000,
             row="2.40:1 (3840x1600)", custom="3840x1600",
             log="oe: output resolution Custom (8) from native 0.5.2: now 9 under options_version 9, the same choice"),
        case(7, 7, "2848x1600", "3840x1600 (Screen)", 512,
             ini="options_version=8\noutput_width=3840\noutput_height=1600\n", screens=[("3840x1600", "")],
             picture="3840x1600", shape=24000, row="2.40:1 (3840x1600)", custom="3840x1600",
             log="oe: output resolution Screen (7) from native 0.5.2: now 8 under options_version 9, the same choice",
             remembered="3840x1600"),

        # ---- the connected screens: each one's size is a choice, by its name; choosing it saves that size (Custom's)
        case(8, 8, "2848x1600", "3840x1600 (2x %s)" % lg, 512, ini=v8 + "output_width=3840\noutput_height=1600\n",
             screens=[("3840x1600", lg), ("3840x1600", lg), ("2560x1440", dell)], picture="3840x1600", shape=24000,
             row="2.40:1 (3840x1600)", custom="3840x1600"),   # (two of one size: one choice; the 2560x1440 one names the fixed size)
        # (the same file with the screens in another order, with one of them gone, and with none: the same picture)
        case(8, 8, "2848x1600", "3840x1600 (2x %s)" % lg, 512, ini=v8 + "output_width=3840\noutput_height=1600\n",
             screens=[("2560x1440", dell), ("3840x1600", lg), ("3840x1600", lg)], picture="3840x1600", shape=24000,
             row="2.40:1 (3840x1600)", custom="3840x1600"),
        case(8, 8, "2848x1600", "3840x1600 (%s)" % lg, 512, ini=v8 + "output_width=3840\noutput_height=1600\n",
             screens=[("3840x1600", lg)], picture="3840x1600", shape=24000, row="2.40:1 (3840x1600)", custom="3840x1600"),
        case(8, 8, "2848x1600", "Custom (3840x1600)", 512, ini=v8 + "output_width=3840\noutput_height=1600\n",
             screens=[("2560x1440", dell)], picture="3840x1600", shape=24000, row="2.40:1 (3840x1600)", custom="3840x1600"),
        case(8, 8, "2848x1600", "Custom (3840x1600)", 512, ini=v8 + "output_width=3840\noutput_height=1600\n",
             picture="3840x1600", shape=24000, row="2.40:1 (3840x1600)", custom="3840x1600"),
        # (screens of different names at one size, one with no name, and one whose size the game takes smaller)
        case(1, 1, "2560x1440", "2560x1440", 512, ini=v8,
             screens=[("3440x1440", dell), ("3440x1440", lg), ("1920x1200", ""), ("7680x2160", "Odyssey", "7224x2032")]),

        # ---- an old file's Screen (output_res=7): the screen the window opens on, as it was; the menu keeps it as that size
        case(7, 7, "2848x1600", "3840x1600 (Screen)", 512, ini=v8, screens=[("3840x1600", "")], picture="3840x1600", shape=24000,
             row="2.40:1 (3840x1600)", custom="3840x1600"),
        case(7, 7, "2848x1600", "3840x1600 (Screen)", 512, ini=v8 + "ultrawide=2\n", screens=[("3840x1600", "")],
             picture="3840x1600", shape=24000, row="2.40:1 (3840x1600)", custom="3840x1600"),   # (not the row's 21:9, 3792x1600)
        case(7, 7, "2560x1440", "3440x1440 (%s)" % lg, 512, ini=v8, screens=[("3440x1440", lg)], picture="3440x1440", shape=23889,
             row="2.39:1 (3440x1440)", custom="3440x1440"),
        case(7, 7, "1920x1080", "2560x1080 (Screen)", 512, ini=v8, screens=[("2560x1080", "")], picture="2560x1080", shape=23704,
             row="21:9 (2560x1080)", custom="2560x1080"),
        # (an old-version file with Screen or Custom and an Ultrawide row still gets the size's own picture)
        case(7, 7, "2848x1600", "3840x1600 (Screen)", 512, ini="options_version=7\nultrawide=2\n", screens=[("3840x1600", "")],
             picture="3840x1600", shape=24000, row="2.40:1 (3840x1600)", custom="3840x1600"),
        case(8, 8, "2560x1440", "Custom (3440x1440)", 512, ini="options_version=7\noutput_width=3440\noutput_height=1440\nultrawide=3\n",
             picture="3440x1440", shape=23889, row="2.39:1 (3440x1440)", custom="3440x1440"),
        case(7, 7, "1920x1080", "2560x1080 (Screen)", 512, ini="options_version=7\nultrawide=2\n", screens=[("2560x1080", "")],
             picture="2560x1080", shape=23704, row="21:9 (2560x1080)", custom="2560x1080"),
        # (an old-version size above the pixel cap keeps its own shape when reduced)
        case(8, 8, "3616x2032", "Custom (7224x2032)", 900, ini="options_version=7\noutput_width=7680\noutput_height=2160\nultrawide=1\n",
             picture="7224x2032", shape=35551, row="32:9 (7224x2032)", custom="7224x2032", rows="7680x2160"),
        # (the one the window opens on, not the first of the list)
        case(7, 7, "2848x1600", "3840x1600 (%s)" % lg, 512, ini=v8, screens=[("2560x1440", dell), ("*3840x1600", lg)],
             picture="3840x1600", shape=24000, row="2.40:1 (3840x1600)", custom="3840x1600"),
        # (a screen of a fixed size: that fixed choice, the same picture)
        case(7, 7, "2560x1440", "5120x1440 (Screen)", 610, ini=v8, screens=[("5120x1440", "")], picture="5120x1440", shape=35556,
             row="32:9 (5120x1440)"),
        case(7, 7, "3840x2160", "5120x2160 (Screen)", 900, ini=v8, screens=[("5120x2160", "")], picture="5120x2160", shape=23704,
             row="21:9 (5120x2160)"),
        case(7, 7, "2560x1440", "2560x1440 (Screen)", 512, ini=v8, screens=[("2560x1440", "")]),
        case(7, 7, "2560x1440", "2560x1440 (Screen)", 512, ini=v8 + "ultrawide=2\n", screens=[("2560x1440", "")],
             picture="3416x1440", row="21:9"),
        case(1, 7, "2136x1200", "1920x1200 (Screen)", 512, ini=v8, res="7", screens=[("1920x1200", "")], picture="1920x1200",
             shape=16000, row="16:10 (1920x1200)", custom="1920x1200"),
        case(7, 7, "1824x1024", "1280x1024 (Screen)", 512, ini=v8, screens=[("1280x1024", "")], picture="1280x1024", shape=12500,
             row="1.25:1 (1280x1024)", custom="1280x1024"),
        # (a 16:9 screen 1366 wide: the game's frame at its height; more pixels than 5120x2880's: smaller in its shape)
        # (saved as the size the game takes, which reads back as itself)
        case(7, 7, "1368x768", "1368x768 (Screen)", 512, ini=v8, screens=[("1366x768", "", "1368x768")], custom="1368x768"),
        case(7, 7, "3616x2032", "7224x2032 (Screen)", 900, ini=v8, screens=[("7680x2160", "", "7224x2032")], picture="7224x2032",
             shape=35551, row="32:9 (7224x2032)", custom="7224x2032"),
        # (a screen taller than 2880 keeps its shape: 7680x4320 is 16:9, the fixed 5120x2880, not 7680x2880's 2.67:1; a
        # 5120x3200 one stays 16:10)
        case(7, 7, "5120x2880", "5120x2880 (8K)", 900, ini=v8, screens=[("7680x4320", "8K", "5120x2880")]),
        case(7, 7, "5120x2880", "4608x2880 (Screen)", 900, ini=v8, screens=[("5120x3200", "", "4608x2880")], picture="4608x2880",
             shape=16000, row="16:10 (4608x2880)", custom="4608x2880"),
        case(7, 1, "2560x1440", "2560x1440", 512, ini=v8),   # (no screen known: 2560x1440)
        case(7, 0, "2560x1440", "3840x1600 (Screen)", 512, ini=v8, handheld=1, screens=[("3840x1600", "")], picture="1536x864",
             custom="3840x1600"),
        # (HOS_OUTPUT_SIZE is Custom's size for the run: the old Screen stays what it is, and no screen's size can be chosen)
        case(7, 7, "2848x1600", "3840x1600 (Screen)", 512, ini=v8, screens=[("3840x1600", "")], env_size="1920x1080",
             picture="3840x1600", shape=24000, row="2.40:1 (3840x1600)", custom="1920x1080", legacy="3840x1600"),

        # ---- Custom: the ini's size (the Output width and Output height rows), HOS_OUTPUT_SIZE over it
        case(8, 8, "2560x1440", "Custom (3440x1440)", 512, ini=v8 + "output_width=3440\noutput_height=1440\n",
             screens=[("3840x1600", "")], picture="3440x1440", shape=23889, row="2.39:1 (3440x1440)", custom="3440x1440"),
        case(8, 8, "1920x1080", "Custom (1920x1080)", 512, ini=v8 + "output_width=3440\noutput_height=1440\n",
             env_size="1920x1080", custom="1920x1080"),
        case(8, 8, "2560x1440", "Custom (3440x1440)", 512, ini=v8 + "output_width=3437\noutput_height=1440\n",
             picture="3440x1440", shape=23889, row="2.39:1 (3440x1440)", custom="3440x1440", rows="3437x1440"),
        # (a size past the limits keeps its shape and is made smaller or larger in it, for the host as for the menu, whose
        # rows then hold the size taken: 10000x5000 is 2:1 at 5120x2880's pixels, 100x100 the squarest picture, 5:4)
        case(8, 8, "4824x2712", "Custom (5424x2712)", 900, ini=v8 + "output_width=10000\noutput_height=5000\n",
             picture="5424x2712", shape=20000, row="2.00:1 (5424x2712)", custom="5424x2712"),
        case(8, 8, "5120x2880", "Custom (5120x2880)", 900, ini=v8 + "output_width=7680\noutput_height=4320\n",
             custom="5120x2880"),
        case(8, 8, "5120x2880", "Custom (5120x2880)", 900, ini=v8, env_size="7680x4320", custom="5120x2880", rows="7680x4320"),
        case(8, 8, "912x512", "Custom (640x512)", 512, ini=v8 + "output_width=100\noutput_height=100\n", picture="640x512",
             shape=12500, row="1.25:1 (640x512)", custom="640x512"),
        # (the rows' own ends, as the rows can be set: 7680x2880 is 8:3, at 5120x2880's pixels)
        case(8, 8, "4168x2344", "Custom (6248x2344)", 900, ini=v8 + "output_width=7680\noutput_height=2880\n",
             picture="6248x2344", shape=26655, row="2.67:1 (6248x2344)", custom="6248x2344", rows="7680x2880"),
        case(8, 8, "2560x1440", "Custom (2560x1440)", 512,
             ini=v8 + "output_width=0\noutput_height=-3\n"),   # (a side that is not a size: the row's default)
        case(8, 8, "3840x2160", "Custom (5120x2160)", 900, ini=v8 + "output_width=5120\noutput_height=2160\n",
             picture="5120x2160", shape=23704, row="21:9 (5120x2160)", custom="5120x2160"),
        case(8, 8, "1920x1080", "Custom (5760x1080)", 515, ini=v8 + "output_width=7680\noutput_height=1080\n",
             picture="5760x1080", shape=53333, row="5.33:1 (5760x1080)", custom="5760x1080", rows="7680x1080"),   # (48:9 at most)
        # (a 16:9 Custom takes the Ultrawide row's shape, as a fixed 16:9 size does)
        case(8, 8, "2560x1440", "Custom (2560x1440)", 610, ini=v8 + "output_width=2560\noutput_height=1440\nultrawide=3\n",
             picture="5120x1440", row="32:9"),
        # (no lines yet: the rows' defaults, 2560x1440, for the host as for the menu; one line: the other side's default)
        case(8, 8, "2560x1440", "Custom (2560x1440)", 512, ini=v8),
        case(8, 8, "2560x1440", "Custom (3440x1440)", 512, ini=v8 + "output_width=3440\n", picture="3440x1440", shape=23889,
             row="2.39:1 (3440x1440)", custom="3440x1440"),
        case(8, 1, "2560x1440", "Custom (not set)", 512, ini=v8 + "output_width=3440\noutput_height=1440\n", env_size="3440",
             custom=None),   # (HOS_OUTPUT_SIZE not WxH: not taken, and not the ini's either: the host's 2560x1440)
    )
    with tempfile.TemporaryDirectory(prefix="output-resolution-") as tmp:
        work = Path(tmp)
        source, exe = work / "fixture.cpp", work / "fixture.exe"
        source.write_text(fixture, encoding="utf-8")
        # (twice: as this system builds the menu, and as a system that is not Windows does, where it takes the main monitor
        # from the host's screens; every case must hold for both)
        exes = (exe, work / "fixture_off_windows.exe")
        subprocess.run([args.cxx, "-std=c++17", "-I", str(ROOT), str(source), "-o", str(exes[0])], check=True)
        subprocess.run([args.cxx, "-std=c++17", "-DFIXTURE_OFF_WINDOWS", "-I", str(ROOT), str(source), "-o", str(exes[1])], check=True)
        bad = 0
        for (saved, handheld, override, screens, ini, env_size, mode, frame, now, pool, shape, labels, row, picture,
             rows, log) in cases:
            (work / "triforce_options.ini").write_text(f"output_res={saved}\nhandheld_profile={handheld}\n{ini}", encoding="ascii")
            env = os.environ.copy()
            for key in ("HOS_OUTPUT_RES", "HOS_HANDHELD", "HOS_RT_POOL_MB", "HOS_OUTPUT_SIZE", "HOS_ASPECT", "TEST_SCREENS", "TEST_LOG"):
                env.pop(key, None)
            if log is not None:
                env["TEST_LOG"] = log
            if override is not None:
                env["HOS_OUTPUT_RES"] = override
            if screens:
                env["TEST_SCREENS"] = screens
            if env_size is not None:
                env["HOS_OUTPUT_SIZE"] = env_size
            for built in exes:
                run = subprocess.run([str(built), str(mode), frame, now, str(pool), str(shape), labels, row, picture, rows],
                                     cwd=work, env=env, capture_output=True, text=True)
                if run.returncode:
                    bad += 1
                    print(f"{built.name}: output_res={saved} handheld={handheld} HOS_OUTPUT_RES={override} screens={screens} "
                          f"HOS_OUTPUT_SIZE={env_size} {ini!r}:\n{run.stderr}")
                    break
        if bad:
            raise SystemExit(f"FAIL: {bad} of {len(cases)} cases")
    print("PASS: output sizes as pictures (fixed, the connected screens' by name, Custom: frame, shape, limits, the old Screen "
          "and the old 5120-wide frames), the row's choices and their order, the Ultrawide row's shape for 16:9 sizes, 1080p "
          "override, handheld, render-target budgets and DLSS sizes")


if __name__ == "__main__":
    main()
