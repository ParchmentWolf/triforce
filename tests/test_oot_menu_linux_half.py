"""host/oot_menu.c's two halves: what other host files call is defined in both, and benchmark mode presses through the start
in both.

The file is one half for the game (#if !defined(HOS_OOT_MENU_NO_MOUSE): Windows, and Linux since the System page's Quit entry)
and another for the tests (#else). A function the first half added for the
rest of the host (v0.5.0's hos_oot_mods_down, nn_hid.c) and not the other half stopped every Linux build at the link (11-18).
This test lists the non-static functions each half defines and the ones host/*.c outside it call, and checks that every one
called from outside is in the non-Windows half too.

(Triforce, 11-22) Benchmark mode's presses through the start's screens (bench_menu) were the Windows half's alone, and on Linux
"Find my best settings" stood on the title screen (#bug-tracker, 11-21). The other half is compiled here (on Windows with
HOS_OOT_MENU_NO_MOUSE, as tests/test_oot_menu_mouse.py does) against a fake guest memory holding a screen's list of entries
(+136 the head, +144 the first node, +156 the entry's offset from its node; entry+24 the button, its focus at +56, its hit box
at *(button+0x58)) and the screen's focus manager (*(*(screen+32)+96)): with benchmark mode on, a screen with a focused button
shown is handed to hos_bench_menu with its vtable, the focused entry and the count, and its A is pressed; no focused button, a
hidden box, no focus manager or benchmark mode off: nothing. The half still has none of the mouse, Quit or Mods.
"""

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "host" / "oot_menu.c"
DEF = re.compile(r"^(?!static\b)[A-Za-z_][\w \t\*]*?\b(hos_\w+)\s*\([^;]*\)\s*\{", re.M)


def halves(text):
    start = text.index("#if !defined(HOS_OOT_MENU_NO_MOUSE)")
    other = text.index("\n#else", start)
    end = text.index("\n#endif", other)
    return text[start:other], text[other:end]


class OotMenuHalvesTest(unittest.TestCase):
    def test_called_from_outside_defined_in_both(self):
        text = SRC.read_text(encoding="utf-8")
        win, other = halves(text)
        win_defs, other_defs = set(DEF.findall(win)), set(DEF.findall(other))
        self.assertIn("hos_oot_menu_tick", other_defs)   # (the parse found the other half's functions)
        outside = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                            for p in sorted((ROOT / "host").glob("*.c")) if p.name != "oot_menu.c")
        called = {name for name in win_defs if re.search(r"\b%s\s*\(" % name, outside)}
        self.assertIn("hos_oot_mods_down", called)
        missing = sorted(called - other_defs)
        self.assertEqual(missing, [], "defined only in oot_menu.c's Windows half, but called from other host files: %s" % missing)

    def test_other_half_has_no_mouse_quit_or_mods(self):
        _, other = halves(SRC.read_text(encoding="utf-8"))
        other = re.sub(r"/\*.*?\*/", "", other, flags=re.S)   # (its comments name the Windows half's)
        for name in ("hos_mouse_game_pointer", "hos_mouse_game_menu", "mods_list_tick", "quit_entry", "mods_entry"):
            self.assertNotRegex(other, r"\b%s" % name, "the non-Windows half has %s" % name)


HOS_H = r"""
#pragma once
#include <stdint.h>
#include <stddef.h>
typedef struct Ctx { uint64_t x[32]; uint64_t vreg[32][2]; } Ctx;
extern uint8_t *fake_heap;
#define FAKE_BASE 0x100000ULL
#define HOS_GUEST_SPACE (FAKE_BASE + (4ULL << 20))
#define GP(a) ((void *)(fake_heap + ((uint64_t)(a) - FAKE_BASE)))
void hos_log(const char *fmt, ...);
int64_t hos_now_ns(void);
"""
VK_API_H = "#pragma once\nenum { HOS_OPT_GAME_OPTIONS = 48 };\n"
BENCH_H = r"""
#pragma once
#include <stdint.h>
enum { HOS_BENCH_MENU_NONE, HOS_BENCH_MENU_PRESS_A };
int hos_bench_on(void);
int hos_bench_menu(uint64_t screen, uint64_t vt, int focus, int focused_entry, int entries, int *entry);
"""
FIXTURE = r"""
#include "hos.h"
#include "hos_bench.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
uint8_t *fake_heap;
static uint64_t heap_top = FAKE_BASE + 0x1000;
int64_t hos_now_ns(void) { return 1000000000LL; }
void hos_log(const char *fmt, ...) { (void)fmt; }
static uint64_t menu_class;
void oot_menu_screen_tick(uint64_t vt) { menu_class = vt; }
void rx_option_set(int id, int value) { (void)id, (void)value; }
void hos_oot_menu_tick(Ctx *c, uint64_t screen);
static int bench, asked, asked_entry, asked_entries;
static uint64_t asked_screen, asked_vt;
int hos_bench_on(void) { return bench; }
int hos_bench_menu(uint64_t screen, uint64_t vt, int focus, int focused_entry, int entries, int *entry) {
    (void)entry;
    asked++, asked_screen = screen, asked_vt = vt, asked_entry = focused_entry, asked_entries = entries;
    return focus ? HOS_BENCH_MENU_PRESS_A : HOS_BENCH_MENU_NONE;
}
static char taps[256];
void hos_hid_tap(const char *press) { strncat(taps, press, sizeof taps - strlen(taps) - 2), strcat(taps, ";"); }
void hos_input_clear_toggles(void) {}   /* ((Triforce) 11-24: host/nn_hid.c's hold-to-toggle latches, dropped by the focus hook) */
/* ((Triforce) the Skip title screen row, host/oot_autoload.c: asked the same way while benchmark mode is off) */
static int skip, skip_asked, skip_entry;
static uint64_t skip_vt;
int hos_oot_autoload_wants(void) { return skip; }
int hos_oot_autoload_menu(uint64_t vt, int focused_entry) { skip_asked++, skip_vt = vt, skip_entry = focused_entry; return 1; }
static uint64_t alloc(size_t n) { const uint64_t a = heap_top; heap_top += (n + 15) & ~(size_t)15; return a; }
static void put64(uint64_t a, uint64_t v) { memcpy(GP(a), &v, 8); }
static uint64_t get64(uint64_t a) { uint64_t v; memcpy(&v, GP(a), 8); return v; }
static void putf(uint64_t a, float f) { memcpy(GP(a), &f, 4); }
/* a screen of n buttons (vtable vt) with its focus manager: the buttons' boxes shown, none focused */
static uint64_t button[8];
static uint64_t screen_of(uint64_t vt, int n) {
    const uint64_t s = alloc(256), ui = alloc(128);
    put64(s, vt), put64(s + 32, ui), put64(ui + 96, alloc(16));
    const int32_t off = 0;
    memcpy(GP(s + 156), &off, 4);
    uint64_t prev = s + 144;
    for (int i = 0; i < n; i++) {
        const uint64_t node = alloc(64), b = alloc(128), box = alloc(0x110);
        put64(prev, node), put64(node + 24, b), put64(b + 0x58, box);
        putf(box + 0x28, 1), putf(box + 0x38, 1), putf(box + 0x4c, 0), putf(box + 0x50, -60.f * i);
        putf(box + 0x84, -200), putf(box + 0x88, -30), putf(box + 0x8c, 400), putf(box + 0x90, 60);
        button[i] = b, prev = node + 8;
    }
    put64(prev, s + 136);
    return s;
}
static int fails;
#define CHECK(x) do { if (!(x)) { printf("FAIL line %d: %s\n", __LINE__, #x); fails++; } } while (0)
int main(void) {
    fake_heap = calloc(1, 4 << 20);
    Ctx ctx;
    memset(&ctx, 0, sizeof ctx);
    const uint64_t title_vt = 0x84c106e8ULL, title = screen_of(title_vt, 4);
    bench = 1;
    hos_oot_menu_tick(&ctx, title);   /* (no button focused yet: the title still fading in) */
    CHECK(asked == 0 && !taps[0] && menu_class == title_vt);
    *(uint8_t *)GP(button[2] + 56) = 1;
    bench = 0;
    hos_oot_menu_tick(&ctx, title);   /* (benchmark mode off: a player's menus, nothing pressed) */
    CHECK(asked == 0 && !taps[0] && menu_class == title_vt);
    bench = 1;
    hos_oot_menu_tick(&ctx, title);
    CHECK(asked == 1 && asked_screen == title && asked_vt == title_vt && asked_entry == 2 && asked_entries == 4);
    CHECK(!strcmp(taps, "0:A/120;"));
    /* (the focused button's box hidden: its page not shown) */
    taps[0] = 0;
    putf(get64(button[2] + 0x58) + 0x28, 0);
    hos_oot_menu_tick(&ctx, title);
    CHECK(asked == 1 && !taps[0]);
    /* (another screen, its focus manager gone: it is not taking the player's input) */
    const uint64_t files = screen_of(0x84c0eba0ULL, 3);
    *(uint8_t *)GP(button[0] + 56) = 1;
    put64(get64(files + 32) + 96, 0);
    hos_oot_menu_tick(&ctx, files);
    CHECK(asked == 1 && !taps[0]);
    put64(get64(files + 32) + 96, alloc(16));
    hos_oot_menu_tick(&ctx, files);
    CHECK(asked == 2 && asked_screen == files && asked_entry == 0 && asked_entries == 3 && !strcmp(taps, "0:A/120;"));
    /* ((Triforce) the Skip title screen row: not asked in benchmark mode, nor while it does not want; asked with the screen's
       vtable and the focused entry otherwise, and its A pressed) */
    skip = 1;
    hos_oot_menu_tick(&ctx, files);
    CHECK(asked == 3 && skip_asked == 0);
    bench = 0, skip = 0, taps[0] = 0;
    hos_oot_menu_tick(&ctx, files);
    CHECK(asked == 3 && skip_asked == 0 && !taps[0]);
    skip = 1;
    hos_oot_menu_tick(&ctx, files);
    CHECK(asked == 3 && skip_asked == 1 && skip_vt == 0x84c0eba0ULL && skip_entry == 0 && !strcmp(taps, "0:A/120;"));
    put64(get64(files + 32) + 96, 0);   /* (its focus manager gone: not asked) */
    hos_oot_menu_tick(&ctx, files);
    CHECK(skip_asked == 1);
    if (!fails) printf("PASS\n");
    return fails != 0;
}
"""


class OotMenuBenchOtherHalfTest(unittest.TestCase):
    def test_bench_presses_through_the_start_without_the_mouse(self):
        compiler = shutil.which("gcc") or shutil.which("clang")
        if not compiler:
            self.skipTest("no C compiler")
        with tempfile.TemporaryDirectory(prefix="triforce-oot-menu-bench-") as tmp:
            tmp = Path(tmp)
            (tmp / "host").mkdir()
            (tmp / "gpu" / "vk").mkdir(parents=True)
            (tmp / "host" / "hos.h").write_text(HOS_H, encoding="utf-8")
            (tmp / "gpu" / "vk" / "vk_api.h").write_text(VK_API_H, encoding="utf-8")
            (tmp / "host" / "hos_bench.h").write_text(BENCH_H, encoding="utf-8")
            shutil.copy(SRC, tmp / "host" / "oot_menu.c")
            shutil.copy(ROOT / "host/oot_title_movie.h", tmp / "host/oot_title_movie.h")
            shutil.copy(ROOT / "host" / "guest_bounds.h", tmp / "host" / "guest_bounds.h")
            (tmp / "host" / "t.c").write_text(FIXTURE, encoding="utf-8")
            binary = tmp / "t.exe"
            other_half = ["-DHOS_OOT_MENU_NO_MOUSE"]   # (the game's builds, Linux's too, have the first half)
            build = subprocess.run([compiler, "-std=gnu11", "-Wall", "-Werror", "-O1", "-g"] + other_half +
                                   [str(tmp / "host" / "t.c"), str(tmp / "host" / "oot_menu.c"), "-o", str(binary)],
                                   text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=1))
