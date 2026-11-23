"""Ultrawide's menu sides: when the renderer shows them (gpu/vk/wide_sides_rule.h, vk_framegen.cpp wide_sides).

Seen in the game at 3840x1600 with Ultrawide menus on Centred: the file select over the title showed its blurred backdrop
in the middle 16:9 and the sharp title movie at both sides. The host gave the margin; the renderer turned its sides off two
presents after turning them on, because the file select's backdrop is drawn by the program that also draws the item
wheel's background, and a frame that draws that was taken for the item wheel, whose background keeps the whole picture
and gets no sides. The rule, compiled alone and run:

- play (the world drawn): no sides; a menu with no world (the pause menu, the map): the row's sides;
- the item wheel (the blur of the last picture drawn, no centred menu): none, as before;
- the same blur drawn while the host says a menu with the centred backdrop runs (the file select): the row's sides;
- the row on Full width, a 16:9 picture, or no margin from the host (the filled title movie alone): none, whatever is drawn.

And the wiring by the source: wide_sides asks the host (MkwVkHost.wide_backdrop, the interface's version with it) and
decides by the rule; host/rx_backend.c answers with host/oot_title_movie.c's menu screens.

    python -I -B tests/test_wide_sides.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''
#include <cstdio>
#include "gpu/vk/wide_sides_rule.h"
using mkwvk::wide_sides_rule::show;
static int failed;
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); failed = 1; } } while (0)
int main() {
    const float margin = (1.0f - (16.0f / 9.0f) / 2.4f) / 2.0f;   // (3840x1600)
    const int64_t never = 0;
    for (int row = 1; row <= 2; row++) {   // (out of focus, black)
        // play: the world drawn this frame, or within the grace
        for (int64_t ago = 0; ago <= 3; ago++) CHECK(show(row, margin, 1000, 1000 - ago, never, false) == 0);
        CHECK(show(row, margin, 1000, 1000, never, true) == 0);   // (whatever the host says of the menus)
        // a menu with no world: the pause menu, the map, a loading screen
        CHECK(show(row, margin, 1000, 996, never, false) == row);
        CHECK(show(row, margin, 1000, 996, 996, false) == row);   // (a blur long ago)
        // the item wheel: the blur of the last picture, no centred menu
        for (int64_t ago = 0; ago <= 3; ago++) CHECK(show(row, margin, 1000, 900, 1000 - ago, false) == 0);
        // the file select over the title, as in the run: the sides on at present 3087, the blur drawn from 3089 on, the
        // world never drawn, the menu's screen running throughout
        for (int64_t now = 3087; now <= 4772; now += 5) CHECK(show(row, margin, now, never, now >= 3089 ? now : never, true) == row);
        // and what turned them off there: the same frames without the host's word
        CHECK(show(row, margin, 3087, never, never, false) == row && show(row, margin, 3089, never, 3089, false) == 0);
        // the title alone: no margin from the host
        CHECK(show(row, 0.0f, 3000, never, never, false) == 0 && show(row, 0.0f, 3000, never, 3000, true) == 0);
    }
    // the row on Full width, and a 16:9 picture
    CHECK(show(0, margin, 1000, 900, never, false) == 0 && show(0, margin, 1000, 900, 1000, true) == 0);
    CHECK(show(1, 0.0f, 1000, 900, never, false) == 0 && show(1, -0.1f, 1000, 900, never, false) == 0);
    if (!failed) std::puts("wide sides: play, a menu, the item wheel, a centred backdrop drawn by the wheel's program");
    return failed;
}
'''


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    framegen = (ROOT / "gpu/vk/vk_framegen.cpp").read_text(encoding="utf-8")
    start = framegen.index("WideSides wide_sides() {")
    sides = framegen[start:framegen.index("\n}\n", start)]
    check("const bool centred_menu = host->wide_backdrop && host->wide_backdrop() != 0;" in sides,
          "wide_sides does not ask the host whether a menu with the centred backdrop runs")
    check("wide_sides_rule::show(opts.wide_menus, margin, presents_now, world_drawn_at.load(std::memory_order_relaxed),\n"
          "                                           wheel_drawn_at.load(std::memory_order_relaxed), centred_menu);" in sides,
          "wide_sides does not decide by wide_sides_rule.h")
    check("presents_now - wheel_drawn_at" not in sides, "wide_sides still takes every blur of the last picture for the item wheel")
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    check("if (cp->key == 0x02ff9920c2571cc2ULL) wheel_drawn_at.store(presents_now, std::memory_order_relaxed);" in draw,
          "vk_draw.cpp no longer notes the blur of the last picture")
    api = (ROOT / "gpu/vk/vk_api.h").read_text(encoding="utf-8")
    check("    int (*wide_backdrop)(void);\n} MkwVkHost;" in api and "#define MKWVK_API_VERSION 18" in api,
          "vk_api.h: MkwVkHost does not end with wide_backdrop at version 18")
    backend = (ROOT / "host/rx_backend.c").read_text(encoding="utf-8")
    check("return oot_menu_backdrop_runs() || rx_option(HOS_OPT_MODS_MUSIC, 0) == 2;" in backend and
          "hos_bench_state, hos_prompts_pad_face, host_screens, host_wide_backdrop,\n};" in backend,
          "rx_backend.c does not answer wide_backdrop with the menu screens that run, at the table's end")
    with tempfile.TemporaryDirectory(prefix="wide-sides-") as tmp:
        source, exe = Path(tmp) / "fixture.cpp", Path(tmp) / "fixture.exe"
        source.write_text(FIXTURE, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT), str(source), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("PASS: ultrawide's menu sides for play, a menu, the item wheel, and a centred backdrop the wheel's program draws")


if __name__ == "__main__":
    main()
