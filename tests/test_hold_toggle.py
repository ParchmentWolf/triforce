"""Hold-to-toggle: a press of an enabled button holds it and the next lets it go; a menu, a loss of focus or a pause
drops the latch, and a button still down after it counts again only once it was let go (host/hold_toggle.h,
host/nn_hid.c npad_states, the Controls tab's Hold to toggle rows).

The rule is compiled as it is and run on authored presses. Read in the sources: the rows and their saved keys, the
option that hands them to the host as one mask, where the latch is applied (after the remapping, the host's own presses
apart, never Plus or Minus), and what resets it (the Insert menu, the game's menus, the window's focus, a rebinding).

python -I -B tests/test_hold_toggle.py [--cc clang]
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]
ROOT = Path(__file__).resolve().parents[1]

RULE = r'''
#include "hold_toggle.h"
#include <stdio.h>
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)
int main(void) {
    HoldToggle s = {0, 0, 0};
    const uint64_t r = 1 << 7, zl = 1 << 8, a = 1;
    CHECK(hold_toggle_apply(&s, r, r, 0) == r);
    CHECK(hold_toggle_apply(&s, r, r, 0) == r);   /* (held on: not a new press) */
    CHECK(hold_toggle_apply(&s, 0, r, 0) == r);   /* (let go: still held for the game) */
    CHECK(hold_toggle_apply(&s, r, r, 0) == 0);   /* (the next press lets it go) */
    hold_toggle_apply(&s, 0, r, 0);
    CHECK(hold_toggle_apply(&s, r | zl, r | zl, 0) == (r | zl));
    CHECK(hold_toggle_apply(&s, a, r | zl, 0) == (r | zl | a));   /* (a button that does not toggle passes as it is) */
    CHECK(hold_toggle_apply(&s, 0, r | zl, 1) == 0);         /* (a menu: every latch dropped) */
    CHECK(hold_toggle_apply(&s, r | zl, r | zl, 0) == 0);    /* (down as play comes back: not a new press) */
    hold_toggle_apply(&s, 0, r | zl, 0);
    CHECK(hold_toggle_apply(&s, r, r | zl, 0) == r);         /* (let go and pressed: counts again) */
    CHECK(hold_toggle_apply(&s, 0, 0, 0) == 0);              /* (its row turned off: the latch goes) */
    CHECK(hold_toggle_apply(&s, r, 0, 0) == r);              /* (off: ordinary input) */
    CHECK(hold_toggle_apply(&s, 0, 0, 0) == 0);
    printf(fails ? "%d FAILED\n" : "toggle: all passed\n", fails);
    return fails != 0;
}
'''


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="hold-toggle-") as tmp:
        source, exe = Path(tmp) / "toggle.c", Path(tmp) / "toggle.exe"
        source.write_text(RULE, encoding="utf-8")
        build = subprocess.run([args.cc, "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "host"), str(source), "-o", str(exe)],
                               capture_output=True, text=True)
        check(build.returncode == 0, "the rule does not compile:\n" + build.stderr)
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        check(run.returncode == 0 and "all passed" in run.stdout, run.stdout + run.stderr)
    read = lambda *p: ROOT.joinpath(*p).read_text(encoding="utf-8")
    api, menu, header, replay = read("gpu", "vk", "vk_api.h"), read("gpu", "vk", "vk_menu.cpp"), read("gpu", "vk", "vk_menu.h"), read("gpu", "vk", "vk_replay.cpp")
    hid, display, sdl, schema = read("host", "nn_hid.c"), read("host", "display.c"), read("host", "posix", "display_sdl.c"), \
        read("launcher", "Logic", "GameOptions", "GameOptionsSchema.cs")
    # the rows, a button each, off by default; the launcher has the same
    check("enum { HOS_OPT_HOLD_TOGGLE = 191 };" in api, "HOS_OPT_HOLD_TOGGLE is not option 191")
    check("int toggle[10] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0};" in header, "the rows' values are not off by default")
    rows = re.findall(r'\{TAB_CONTROLS, "Toggle (\w+)", &opts\.toggle\[HOS_SW_(\w+)\], 0, 1, 1, tx_onoff,', menu)
    check(sorted(rows) == sorted((n, n) for n in "A B X Y LS RS L R ZL ZR".split()), "the Hold to toggle rows are not a row a button: %s" % rows)
    check(sorted(re.findall(r'Row\(GameOptionTab\.Controls, "Hold to toggle", "Toggle (\w+)", 0, 1, 1, 0,', schema)) == sorted(n for n, _ in rows),
          "the launcher's rows are not the menu's")
    option = block(replay, "t.option = [](int id) -> int {")
    check("if (id == HOS_OPT_HOLD_TOGGLE) {" in option and "mask |= (opts.toggle[b] != 0) << b;" in option,
          "the rows do not reach the host as one mask")
    # the latch: after the remapping, the host's own presses apart, never Plus or Minus
    states = block(hid, "static void npad_states(Ctx *c) {")
    at = [states.index(s) for s in ("read_input(&buttons, stick);", "rx_option(HOS_OPT_HOLD_TOGGLE, 0)",
                                    "hold_toggle_apply(&toggles, own, enabled, reset || pause != 0) | taps;", "mods_input(&buttons, stick);")]
    check(at == sorted(at), "the latch is not applied right after the input is read")
    check("const uint64_t stay = (1ULL << B_PLUS) | (1ULL << B_MINUS);" in states and "& ~stay;" in states, "Plus or Minus can toggle")
    check("const uint64_t taps = host_taps_now, own = buttons & ~taps;" in states, "the host's own presses are latched")
    check("InterlockedExchange(&toggle_reset, 0) || rx_option(1, 0) ||" in states, "the Insert menu or a reset does not drop the latch")
    scripted = block(hid, "static void scripted_input(uint64_t *buttons, uint64_t *taps, int32_t stick[4]) {")
    check("*(presses[i].host ? taps : buttons) |= presses[i].buttons;" in scripted and "p.host = live == 2;" in hid and
          "parse_presses(text, script_elapsed_ms(hos_now_ns()), 2);" in block(hid, "static void host_taps(void) {"),
          "the host's taps are not kept apart from the player's presses")
    # what resets it
    for where, text in (("binds_default", block(hid, "static void binds_default(void) {")), ("hos_bind", block(hid, "void hos_bind(int set, int button, int slot, int code) {")),
                        ("host/display.c menus_mouse", block(display, "static void menus_mouse(HWND w, int insert_open, int game_open) {")),
                        ("host/posix/display_sdl.c menu_mouse", block(sdl, "static void menu_mouse(int open) {"))):
        check("hos_input_clear_toggles();" in text, where + " does not drop the latches")
    focus = display[display.index("    case WM_KILLFOCUS:"):]
    check("hos_input_clear_toggles();" in focus[:focus.index("break;")], "a loss of focus does not drop the latches")
    lost = sdl[sdl.index("case HOS_SDL_EV_FOCUS_LOST:"):]
    check("hos_input_clear_toggles();" in lost[:lost.index("break;")], "a loss of focus does not drop the latches (SDL)")
    print("PASS: hold-to-toggle: the rule, its rows and option, the latch after the remapping, and its resets")


if __name__ == "__main__":
    main()
