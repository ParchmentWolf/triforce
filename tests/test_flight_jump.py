"""The Debug tab's No-clip flight takes off with the game's own Jump (host/flight_jump.h, host/nn_hid.c, host/hos_main.c;
no game).

The tool came from a game whose jump is B, and kept B: its double-tap took off and B held climbed. This game's Jump is X
(the keyboard's Space), or B with its Swap Jump Controls, so the Jump the player double-tapped never took off and the
row looked as if it did nothing (the owner, 11-24: "no clip not working").

Compiles host/flight_jump.h's rules and runs them: X by default and while the option is not read yet, B with Swap Jump
Controls on, HOS_FLIGHT_JUMP=B or X whatever the option says. Checks that MurmurHash3("OptionData.IsChangeJumpButton") is
the hash the header names (the game's option, as option.sav keys it), and reads the sources: nn_hid.c's shortcut and its
climb take the bit from flight_jump() and no longer name B; hos_main.c reads the option at Link's update and says it; the
Debug tab's help and the switches table say it.

    python -I -B tests/test_flight_jump.py [--cc gcc]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def murmur3(data, seed=0):
    c1, c2, h, m = 0xcc9e2d51, 0x1b873593, seed, 0xffffffff
    n = len(data) // 4
    for i in range(n):
        k = int.from_bytes(data[4 * i:4 * i + 4], "little")
        k = (k * c1) & m
        k = ((k << 15) | (k >> 17)) & m
        h ^= (k * c2) & m
        h = ((h << 13) | (h >> 19)) & m
        h = (h * 5 + 0xe6546b64) & m
    tail, k = data[4 * n:], 0
    for i in reversed(range(len(tail))):
        k ^= tail[i] << (8 * i)
    if tail:
        k = (k * c1) & m
        k = ((k << 15) | (k >> 17)) & m
        h ^= (k * c2) & m
    h ^= len(data)
    h ^= h >> 16
    h = (h * 0x85ebca6b) & m
    h ^= h >> 13
    h = (h * 0xc2b2ae35) & m
    return h ^ (h >> 16)


def function(text, head):
    start = text.index(head)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


PROGRAM = r"""
#include <stdio.h>
#include "flight_jump.h"
#define CHECK(x) do { if (!(x)) { printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)
int main(void) {
    const unsigned long long B = 1ULL << 1, X = 1ULL << 2;
    CHECK(flight_jump_mode_env(NULL) == FLIGHT_JUMP_GAME);
    CHECK(flight_jump_mode_env("") == FLIGHT_JUMP_GAME);
    CHECK(flight_jump_mode_env("0") == FLIGHT_JUMP_GAME);
    CHECK(flight_jump_mode_env("BX") == FLIGHT_JUMP_GAME);
    CHECK(flight_jump_mode_env("B") == FLIGHT_JUMP_ALWAYS_B && flight_jump_mode_env("b") == FLIGHT_JUMP_ALWAYS_B);
    CHECK(flight_jump_mode_env("X") == FLIGHT_JUMP_ALWAYS_X && flight_jump_mode_env("x") == FLIGHT_JUMP_ALWAYS_X);
    /* the game's Jump: X, B with Swap Jump Controls; X while the option is not read yet (the game's default) */
    CHECK(flight_jump_bit(FLIGHT_JUMP_GAME, 0) == X);
    CHECK(flight_jump_bit(FLIGHT_JUMP_GAME, -1) == X);
    CHECK(flight_jump_bit(FLIGHT_JUMP_GAME, 1) == B);
    /* the switch: whatever the option says */
    for (int s = -1; s <= 1; s++) {
        CHECK(flight_jump_bit(FLIGHT_JUMP_ALWAYS_B, s) == B);
        CHECK(flight_jump_bit(FLIGHT_JUMP_ALWAYS_X, s) == X);
    }
    printf("ok\n");
    return 0;
}
"""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()

    header = (ROOT / "host/flight_jump.h").read_text(encoding="utf-8")
    named = re.search(r"#define FLIGHT_JUMP_HASH 0x([0-9a-f]{8})u", header)
    check(named is not None, "flight_jump.h names no FLIGHT_JUMP_HASH")
    check(int(named.group(1), 16) == murmur3(b"OptionData.IsChangeJumpButton"),
          "FLIGHT_JUMP_HASH is not MurmurHash3(\"OptionData.IsChangeJumpButton\")")

    with tempfile.TemporaryDirectory() as tmp:
        src, exe = Path(tmp) / "flight_jump_test.c", Path(tmp) / "flight_jump_test.exe"
        src.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "host"), str(src), "-o", str(exe)],
                       check=True)
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        check(run.returncode == 0 and run.stdout.strip() == "ok", "the rules: %s%s" % (run.stdout, run.stderr))

    hid = (ROOT / "host/nn_hid.c").read_text(encoding="utf-8")
    shortcut = function(hid, "static int flight_jump_shortcut(")
    check("const uint64_t jump = flight_jump();" in shortcut, "the double-tap is not the game's Jump (flight_jump)")
    check("B_B" not in shortcut.replace('jump == 1ULL << B_B ? "B" : "X"', ""), "the double-tap still names B")
    check("const uint64_t climb = flight_jump() | (1ULL << B_R);" in hid, "holding Jump to climb is not the game's Jump")
    check("(1ULL << B_B) | (1ULL << B_R)" not in hid, "the climb still holds B")
    jump = function(hid, "static uint64_t flight_jump(void) {")
    check('flight_jump_mode_env(getenv("HOS_FLIGHT_JUMP"))' in jump and "hos_oot_jump_swapped" in jump,
          "flight_jump does not follow HOS_FLIGHT_JUMP and the game's option")

    main_c = (ROOT / "host/hos_main.c").read_text(encoding="utf-8")
    check("volatile int hos_oot_jump_swapped = -1;" in main_c, "hos_main.c does not hold the game's option")
    tick = function(main_c, "static void oot_update_player_cheats(")
    check("oot_gamedata_bool(c, FLIGHT_JUMP_HASH, &swapped)" in tick and "hos_oot_jump_swapped = is;" in tick,
          "Link's update does not read the game's Swap Jump Controls")

    menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
    check("X (Space), or B with the game's Swap Jump Controls" in menu, "the No-clip flight row does not say which button")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    check("`HOS_FLIGHT_JUMP=B`" in docs, "docs/development.md's switches have no HOS_FLIGHT_JUMP row")
    print("PASS: no-clip flight takes off with the game's Jump (X, or B with Swap Jump Controls)")


if __name__ == "__main__":
    main()
