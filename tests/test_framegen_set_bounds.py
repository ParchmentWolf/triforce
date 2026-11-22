"""Frame interpolation never writes past the frames its sets were made with, whatever the Frame generation row does while
a present waits (gpu/vk/framegen_rows.h set_multiplier and game_slot, vk_framegen.cpp framegen_record and ensure_size; no
game).

(Triforce, 11-20) The owner's "upscaling crash": three runs of 11-20 ended in an access violation reading 0x590 inside
NVIDIA's driver, in a vkCmdCopyImage run by the recorder thread while a present waited for it. Each had frame
interpolation on, and the Frame generation row had been stepped up in the options (Auto, then 3x at the next start, then
5x). The sets' frames are made for the row's multiplier when a present begins; the present then waits for the display
thread to let a set go, and while frames are made that thread runs the menu, so a step of the row lands in the wait. The
multiplier read again after it was more than the frames made: the made frames went into the frames there were and the
game's own into an image that was never made.

This compiles framegen_rows.h alone and checks the two rules: the multiplier a present records with is the row's and no
more than the frames made; the game's frame goes after the made ones and into the set's last frame at most. Then, for
every number of frames a set can be made with and every multiplier the row can go to in the wait, that every frame a
present writes is one the set has.

And reads the source for what only the game shows: the sets made with as many frames as the multiplier read there, and
that number kept; framegen_record taking its multiplier through set_multiplier with the frames made, after the wait, and
no bare multiplier(); the game's frame's place through game_slot before the copy; Auto's frames counted from the frames
made.

    python -I -B tests/test_framegen_set_bounds.py [--cxx clang++]
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


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


PROGRAM = r"""
#include <cstddef>
#include <cstdio>
#include "framegen_rows.h"
using namespace mkwvk::framegen_rows;
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
int main() {
    // the multiplier a present records with
    CHECK(set_multiplier(3, 3) == 3 && set_multiplier(2, 3) == 2 && set_multiplier(8, 8) == 8);
    CHECK(set_multiplier(4, 3) == 3 && set_multiplier(5, 3) == 3 && set_multiplier(8, 4) == 4);   // (stepped up in the wait)
    CHECK(set_multiplier(0, 3) == 1 && set_multiplier(-2, 3) == 1);                              // (Off in the wait: the game's frame)
    CHECK(set_multiplier(5, 0) == 1 && set_multiplier(5, 1) == 1);
    // the game's frame's place
    CHECK(game_slot(2, 3) == 2 && game_slot(0, 3) == 0 && game_slot(7, 8) == 7);
    CHECK(game_slot(3, 3) == 2);   // (the crash: three made frames over sets of three, the game's into a fourth)
    CHECK(game_slot(1, 1) == 0);   // (AMD FSR 4 in the wait, over sets made for the game's frames alone)
    CHECK(game_slot(0, 0) == 0 && game_slot(-1, 3) == 0);
    // a present, as framegen_record writes it: the made frames into 0 to m - 2, the game's after them
    for (int made_with = 1; made_with <= kMaxMult; made_with++)
        for (int row = 0; row <= kMaxMult; row++) {
            const int m = set_multiplier(row, made_with);
            for (int k = 1; k < m; k++) CHECK(k - 1 < made_with);
            const int game = game_slot(m - 1, made_with);
            CHECK(game >= 0 && game < made_with);
            CHECK(row > made_with || row < 1 || (m == row && game == row - 1));   // (a row the sets were made for: as it asks)
        }
    CHECK(game_slot(1, 2) == 1 && game_slot(1, 8) == 1);   // (AMD's one made frame, sets of two or more: the game's second)
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    fg = (VK / "vk_framegen.cpp").read_text(encoding="utf-8")

    size = block(fg, "bool ensure_size(VkCommandBuffer cmd, uint32_t w, uint32_t h) {")
    check("const int mult = multiplier();" in size and "for (int k = 0; k < mult; k++)" in size and "fg.mult = mult;" in size,
          "ensure_size: the sets' frames are not made for one reading of the multiplier, kept as fg.mult")

    record = block(fg, "bool framegen_record(VkCommandBuffer cmd, VkImageView src, uint32_t sw, uint32_t sh, const int crop[4]) {")
    taken = "m = framegen_rows::set_multiplier(multiplier(), fg.mult);"
    check(taken in record, "framegen_record: the multiplier is not held to the frames the sets were made with")
    check(record.count("multiplier()") == 1, "framegen_record reads the row's multiplier again, past the frames made")
    wait = record.index("fg.cv.wait(lk,")
    check(record.index("ensure_size(cmd,") < wait < record.index(taken),
          "framegen_record: the multiplier is taken before the wait for a set, where the menu may still step the row")
    slot, copy = "set->made = framegen_rows::game_slot(set->made, fg.mult);", "set->frame[set->made].image"
    check(slot in record and record.index(slot) < record.index(copy), "framegen_record: the game's frame may go past the set's last frame")
    check(record.count(copy) == 1, "framegen_record copies the game's frame into a set in a second place")
    check("n = auto_slots(before, now, period, fg.slot_next, t, at, std::min(fg.mult, kMaxMult));" in record,
          "Auto's frames are not counted from the frames the sets were made with")

    with tempfile.TemporaryDirectory(prefix="framegen-set-bounds-") as tmp:
        src, exe = Path(tmp) / "bounds.cpp", Path(tmp) / "bounds.exe"
        src.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the frames a present writes:\n" + r.stdout)
    print("PASS: a present writes only frames its sets were made with, whatever the Frame generation row does in its wait")


if __name__ == "__main__":
    main()
