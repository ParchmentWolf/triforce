"""The Mods screen as it opens: it fades in as the game's lists and windows do (gpu/vk/mods_page_anim.h, vk_menu.cpp
draw_menu and menu_tick; no game).

(Triforce, 11-20) The owner's "Mod menu fade in". The entry that opens the Mods screen is animated as the game's own (the
title's, and Mods and Quit under the pause menu's System list), and Quit's dialog opens with the game's window's In; the
screen itself came whole on the frame after the press. This compiles mods_page_anim.h alone and checks:

- the In's alpha: nothing at its start, all of it at frame 15, never going back on the way, slow to start (under a third
  half way, as the layouts' slopes 0.02 and 0.14 make it);
- the screen from tick to tick: nothing of it shows before its first step (a drawing between the press and the tick's end
  must not show it whole for a frame), its In runs from the tick it came at, it takes input once the In has played, a
  screen that goes and comes again plays its In again, and a still shows it as it stands.

And reads the source for what only the game shows: the screen stepped at every tick's end with whether it is the page
shown; no input passed to it while its In plays; everything draw_menu draws from the page's first vertex faded by the
In's amount, the Full panel left as it is; and the entries that opened it still drawn under it while the In plays, going
as the screen comes.

    python -I -B tests/test_mods_page_anim.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def function(text, head):
    start = text.index(head)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


PROGRAM = r"""
#include <cmath>
#include <cstdio>
#include "mods_page_anim.h"
using namespace mods_page;
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
static bool near(float a, float b, float tol = 0.01f) { return std::fabs(a - b) <= tol; }
int main() {
    // the In's alpha
    CHECK(kInNs == 15 * kFrameNs);
    CHECK(near(in_alpha(0), 0) && near(in_alpha(-5), 0) && near(in_alpha(kInNs), 1) && near(in_alpha(100 * kFrameNs), 1));
    float last = 0;
    for (int64_t t = 0; t <= kInNs; t += kFrameNs / 4) {
        const float a = in_alpha(t);
        CHECK(a >= last - 1e-4f && a >= 0 && a <= 1);
        last = a;
    }
    CHECK(in_alpha(kInNs / 2) > 0.2f && in_alpha(kInNs / 2) < 0.34f);   // (slow to start)
    CHECK(in_alpha(3 * kFrameNs) < 0.1f && in_alpha(12 * kFrameNs) > 0.6f && in_alpha(14 * kFrameNs) > 0.85f);

    // the screen from tick to tick
    const int64_t t0 = 5000000000LL;
    Page p;
    CHECK(near(p.alpha(t0), 0) && !p.ready(t0));       // (asked for, not stepped yet: nothing of it, no input)
    CHECK(near(p.alpha(t0, true), 1));                 // (a still: as it stands)
    p.step(t0, true);
    CHECK(p.shown && p.since_ns == t0);
    CHECK(near(p.alpha(t0), 0) && !p.ready(t0));
    p.step(t0 + 4 * kFrameNs, true);                   // (the ticks after: the same In, not a new one)
    CHECK(p.since_ns == t0);
    CHECK(p.alpha(t0 + 4 * kFrameNs) > 0 && p.alpha(t0 + 4 * kFrameNs) < 0.2f && !p.ready(t0 + 4 * kFrameNs));
    CHECK(!p.ready(t0 + kInNs - 1) && p.ready(t0 + kInNs) && near(p.alpha(t0 + kInNs), 1));
    CHECK(near(p.alpha(t0 + 4 * kFrameNs, true), 1));  // (a picture that compares)
    p.step(t0 + 60 * kFrameNs, false);                 // (Back: gone at once)
    CHECK(!p.shown && p.since_ns == 0 && !p.ready(t0 + 60 * kFrameNs));
    p.step(t0 + 90 * kFrameNs, true);                  // (opened again: its In again)
    CHECK(p.since_ns == t0 + 90 * kFrameNs && near(p.alpha(t0 + 90 * kFrameNs), 0) && !p.ready(t0 + 91 * kFrameNs));
    CHECK(p.ready(t0 + 90 * kFrameNs + kInNs));
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    menu = (VK / "vk_menu.cpp").read_text(encoding="utf-8")

    check('#include "mods_page_anim.h"' in menu and "mods_page::Page mods_screen;" in menu, "vk_menu.cpp does not keep the Mods screen's In")
    alpha = function(menu, "float mods_screen_alpha() {")
    check("page == kModsPage ? mods_screen.alpha(prof_now(), !ease_live || still) : 1.0f" in alpha,
          "the In's amount is not the Mods screen's alone, or a still does not show it as it stands")

    tick = function(menu, "void menu_tick() {")
    check("mods_screen.step(prof_now(), open_now.load() && page == kModsPage);" in tick, "the screen is not stepped at every tick")
    check(tick.index("mods_screen.step(") > tick.index("if (mods_screen.ready(prof_now())) mods_tick("),
          "the screen is stepped before the page's input: the tick that opens it would pass input on")
    check(tick.count("mods_tick(press, tab_left, tab_right, mouse, moved, ptr, mx, my, changed);") == 1 and
          "if (mods_screen.ready(prof_now())) mods_tick(press, tab_left, tab_right, mouse, moved, ptr, mx, my, changed);" in tick,
          "the Mods screen takes input while its In plays")

    draw = function(menu, "void draw_menu(ui::Ctx& c, bool perf_under) {")
    first, dim = draw.index("const int vtx_page = c.d->VtxBuffer.Size;"), draw.index("ui::system_bg(c)")
    check(first < dim, "the page's first vertex is taken after its background: the background would come at once")
    fade = "for (int i = vtx_page; mods_in < 1 && i < c.d->VtxBuffer.Size; i++)"
    check(fade in draw and "if (i < perf0 || i >= perf1) c.d->VtxBuffer[i].col = ui::alpha(c.d->VtxBuffer[i].col, mods_in);" in draw,
          "the page is not faded by the In's amount, or the Full panel fades with it")
    check(draw.index("panel_between(c.d);") < draw.index(fade) < draw.index("put_on_grid(c.d, vtx0, cmd0, menu_map, window_clip, perf0, perf1);"),
          "the fade is not over the whole page: after the panel's layer is merged, before the page is put on its grid")
    check(draw.index(fade) < draw.index("if (menu_map.ox <= 0 && menu_map.oy <= 0 && menu_map.kx == 1) return;"),
          "a 16:9 window returns before the fade")
    under = draw.index("if (mods_in < 1 && (mods_list_fresh() || mods_title_fading())) {")
    check(under < first and "draw_mods_row_shut(c);" in draw[under:first] and "ui::alpha(c.d->VtxBuffer[i].col, 1 - mods_in)" in draw[under:first],
          "the entries that opened the screen are not drawn under it, going as it comes, while its In plays")

    with tempfile.TemporaryDirectory(prefix="mods-page-anim-") as tmp:
        src, exe = Path(tmp) / "anim.cpp", Path(tmp) / "anim.exe"
        src.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the Mods screen's In as made:\n" + r.stdout)
    print("PASS: the Mods screen fades in as the game's lists and windows, takes input after, and never shows whole first")


if __name__ == "__main__":
    main()
