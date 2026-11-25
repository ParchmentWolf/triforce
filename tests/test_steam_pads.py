"""Valve's own pads under Steam, for their motion sensors, and the Steam Deck's built-in controls (host/steam_pads.h,
used by host/pad_sdl.c and host/nn_hid.c).

Started from Steam, the game gets an SDL_GAMECONTROLLER_IGNORE_DEVICES list with Valve's controllers in it, so SDL
opens only Steam Input's stand-in pad, which has no gyroscope. The header is compiled and checked:

- Valve's entries (0x28de, either case) come out of the list and the others stay, in order, as Steam wrote them;
- the Steam Deck's built-in controls (0x28de/0x1205, either case) stay in the list, as Steam set them;
- a list with no Valve entry, an empty one and none at all come back with nothing taken out;
- a list SDL reads from a file (@path), and one too long for the buffer, are left as they are (-1, nothing written);
- a real Valve pad gives its motion only while a Steam stand-in pad is open; a stand-in pad, another maker's pad, or
  a Valve pad with no stand-in open plays as before;
- the Deck's built-in controls are Valve's vendor with the Deck's product and no Steam Input handle, nothing else.

A player without Steam Input and without a Steam Deck sees none of it, and the test holds that: the environment is
Steam's only with both of its variables (its list, not empty, and its stand-in pads' variable, set and not 0); with
what an SDL that cannot tell answers (vendor 0, product 0, handle 0) no rule takes a pad, whatever else is open; and
HOS_STEAM_PADS=0 (off, no, false) is the switch that turns the rules off. The source: host/pad_sdl.c edits the list only
behind steam_rules(), steam_pads_from_steam() and hos_sdl_knows_steam_pads(), keeps a pad's identity 0 with the switch
off, and skips a pad's buttons only by steam_pads_motion_only(); host/nn_hid.c takes the mouse from the game only by
hos_sdl_pads_deck_builtin().

python -I -B tests/test_steam_pads.py [--cc clang]
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]

# (a list as Steam sets it, shortened: Valve's pads, then a Flydigi and a Sony pad Steam also reads itself)
STEAM_LIST = "0x28de/0x1002,0x28de/0x1205,0x28de/0x1304,0x28DE/0x11E0,0x2dc8/0x6000,0x054c/0x0ce6"

FIXTURE = r'''#include <stdio.h>
#include <string.h>
#include "steam_pads.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); return 1; } } while (0)
int main(void) {
    char out[256];
    /* Steam's list: three Valve entries out, the Steam Deck's and the rest kept in order */
    CHECK(steam_pads_without_valve("STEAM_LIST", out, sizeof out) == 3);
    CHECK(!strcmp(out, "0x28de/0x1205,0x2dc8/0x6000,0x054c/0x0ce6"));
    /* the Steam Deck's on its own, either case: kept */
    CHECK(steam_pads_without_valve("0x28DE/0x1205", out, sizeof out) == 0 && !strcmp(out, "0x28DE/0x1205"));
    /* only Valve's: an empty list */
    CHECK(steam_pads_without_valve("0x28de/0x1304", out, sizeof out) == 1 && !out[0]);
    /* none of Valve's: the same list back */
    CHECK(steam_pads_without_valve("0x2dc8/0x6000,0x054c/0x0ce6", out, sizeof out) == 0);
    CHECK(!strcmp(out, "0x2dc8/0x6000,0x054c/0x0ce6"));
    /* empty and missing */
    CHECK(steam_pads_without_valve("", out, sizeof out) == 0 && !out[0]);
    CHECK(steam_pads_without_valve(NULL, out, sizeof out) == 0 && !out[0]);
    /* empty entries and a trailing comma drop out */
    CHECK(steam_pads_without_valve("0x054c/0x0ce6,,0x28de/0x1304,", out, sizeof out) == 1);
    CHECK(!strcmp(out, "0x054c/0x0ce6"));
    /* a list from a file stays as it is */
    CHECK(steam_pads_without_valve(" @/tmp/list.txt", out, sizeof out) == -1 && !out[0]);
    /* too long for the buffer: left as it is */
    char small[16];
    CHECK(steam_pads_without_valve("0x28de/0x1304,0x2dc8/0x6000,0x054c/0x0ce6", small, sizeof small) == -1 && !small[0]);
    CHECK(steam_pads_without_valve("0x28de/0x1304", small, 0) == -1);
    /* motion only: a real Valve pad while a stand-in is open */
    CHECK(steam_pads_motion_only(0x28de, 0, 1) == 1);
    CHECK(steam_pads_motion_only(0x28de, 0, 0) == 0);                     /* no stand-in: plays as before */
    CHECK(steam_pads_motion_only(0x28de, 0xfa9962907718ULL, 1) == 0);    /* the stand-in itself */
    CHECK(steam_pads_motion_only(0x054c, 0, 1) == 0);                     /* another maker's pad */
    /* the Deck's built-in controls: Valve's, the Deck's product id, no Steam handle */
    CHECK(steam_pads_deck_builtin(0x28de, 0x1205, 0) == 1);
    CHECK(steam_pads_deck_builtin(0x28de, 0x1205, 0xfa9962907718ULL) == 0);   /* Steam's stand-in for them */
    CHECK(steam_pads_deck_builtin(0x28de, 0x1002, 0) == 0);                   /* a Steam Controller */
    CHECK(steam_pads_deck_builtin(0x054c, 0x1205, 0) == 0);                   /* another maker's product id */
    CHECK(steam_pads_deck_builtin(0, 0, 0) == 0);                             /* unknown identity */
    /* the environment is Steam's only with both of its variables */
    CHECK(steam_pads_from_steam("STEAM_LIST", "1") == 1);
    CHECK(steam_pads_from_steam("STEAM_LIST", NULL) == 0);     /* a list a player set by hand: theirs */
    CHECK(steam_pads_from_steam("STEAM_LIST", "") == 0 && steam_pads_from_steam("STEAM_LIST", "0") == 0);
    CHECK(steam_pads_from_steam(NULL, "1") == 0 && steam_pads_from_steam("", "1") == 0);   /* unset or emptied */
    CHECK(steam_pads_from_steam(NULL, NULL) == 0);             /* no Steam at all */
    /* what an SDL that cannot tell answers for every pad (0, 0, 0), and every other maker's pad with no handle: no
       rule takes it, a stand-in open or not */
    for (int stand_in = 0; stand_in < 2; stand_in++) {
        CHECK(steam_pads_motion_only(0, 0, stand_in) == 0);
        CHECK(steam_pads_motion_only(0x045e, 0, stand_in) == 0 && steam_pads_motion_only(0x054c, 0, stand_in) == 0);
        CHECK(steam_pads_motion_only(0x057e, 0, stand_in) == 0);
    }
    CHECK(steam_pads_deck_builtin(0x045e, 0x028e, 0) == 0 && steam_pads_deck_builtin(0x054c, 0x0ce6, 0) == 0);
    /* the switch */
    CHECK(steam_pads_off(NULL) == 0 && steam_pads_off("") == 0 && steam_pads_off("1") == 0 && steam_pads_off("on") == 0);
    CHECK(steam_pads_off("0") == 1 && steam_pads_off("off") == 1 && steam_pads_off("no") == 1 && steam_pads_off("false") == 1);
    puts("ok: Steam's ignore list without Valve's pads, their motion-only rule, the Deck's built-in controls, and none of "
         "it without Steam's environment, a Steam handle or the Deck's id");
    return 0;
}
'''.replace("STEAM_LIST", STEAM_LIST)


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def check_sources():
    pad = (ROOT / "host" / "pad_sdl.c").read_text(encoding="utf-8")
    hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
    sdl = (ROOT / "host" / "hos_sdl.c").read_text(encoding="utf-8")
    # the list: behind the switch, Steam's environment and an SDL that tells the stand-in pads apart, before SDL starts
    start = block(pad, "static int pads_start(void) {")
    gate = ('if (steam_rules() && steam_pads_from_steam(list, getenv("SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD")) &&\n'
            "            hos_sdl_knows_steam_pads() && steam_pads_without_valve(list, kept, sizeof kept) > 0 &&\n"
            '            hos_sdl_hint_override("SDL_GAMECONTROLLER_IGNORE_DEVICES", kept))')
    check(gate in start and start.index(gate) < start.index("hos_sdl_init(HOS_SDL_GAMEPAD)"),
          "host/pad_sdl.c edits Steam's ignore list outside Steam's environment, or after SDL has read it")
    check(pad.count("hos_sdl_hint_override(") == 1 and hid.count("hos_sdl_hint_override(") == 0, "the list is edited elsewhere too")
    # a pad's identity: 0 with the switch off, so no rule takes it
    poll = block(pad, "static void pads_poll(void) {")
    for field, call in (("vendor", "hos_sdl_pad_vendor"), ("product", "hos_sdl_pad_product"), ("steam", "hos_sdl_pad_steam_handle")):
        check("pads[slot].%s = steam_rules() ? %s(gc) : 0;" % (field, call) in poll, "a pad's %s is read with HOS_STEAM_PADS=0" % field)
    # a pad's buttons are skipped by the motion-only rule alone, and the Deck's flag is set by its rule alone
    check("const int motion_only = steam_pads_motion_only(pads[i].vendor, pads[i].steam, stand_in);" in poll and
          "if (motion_only) {\n                motion_only_used(i, now);\n                continue;\n            }" in poll,
          "a pad's buttons are left out by something other than the motion-only rule")
    check("for (int i = 0; i < MAX_PADS; i++) stand_in |= pads[i].gc && pads[i].steam;" in poll,
          "a stand-in pad is something other than an open pad with a Steam Input handle")
    check(poll.count("deck_builtin = 1;") == 1 and
          "if (steam_pads_deck_builtin(pads[i].vendor, pads[i].product, pads[i].steam)) deck_builtin = 1;" in poll and
          pad.count("state_deck_builtin = ") == 1 and "state_deck_builtin = deck_builtin;" in poll,
          "the Deck's built-in controls are told by something other than their rule")
    # the optional calls answer 0 from an SDL without them
    for call, field in (("hos_sdl_pad_vendor", "PadVendor"), ("hos_sdl_pad_product", "PadProduct")):
        check("uint16_t %s(void *pad) { return f.%s ? CALL(uint16_t (*)(void *), %s)(pad) : 0; }" % (call, field, field) in sdl,
              "%s does not answer 0 from an SDL without the call" % call)
    check("return f.PadSteamHandle ? CALL(uint64_t (*)(void *), PadSteamHandle)(pad) : 0;" in sdl,
          "hos_sdl_pad_steam_handle does not answer 0 from an SDL without the call")
    check("int hos_sdl_knows_steam_pads(void) { return f.PadVendor && f.PadSteamHandle && f.SetHintPriority; }" in sdl,
          "the list may be edited by an SDL that cannot tell a stand-in pad")
    # the mouse: taken from the game only beside the Deck's built-in controls
    read = block(hid, "static void read_input(")
    check("const int deck_builtin_input = hos_sdl_pads_deck_builtin();" in read and read.count("deck_builtin_input") == 4,
          "host/nn_hid.c read_input asks about the Deck's controls elsewhere, or no longer does")
    check("const int native = mode == 1 && !deck_builtin_input;" in read and
          "if (deck_builtin_input) mouse[2] = mouse[3] = 0;" in read and
          "mouse_buttons_arm(captured && !deck_builtin_input, menu_mouse);" in read,
          "the mouse beside the Deck's built-in controls still steers the camera or presses a control")
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`HOS_STEAM_PADS=0`" in docs, "docs/development.md has no row for HOS_STEAM_PADS")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    check_sources()
    with tempfile.TemporaryDirectory() as d:
        src, exe = Path(d) / "steam_pads_test.c", Path(d) / "steam_pads_test"
        src.write_text(FIXTURE, encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "host"), str(src), "-o",
                        str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip())
        if r.returncode:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
