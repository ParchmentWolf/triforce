"""With RX_VK_FRAMEGEN_REFRESH=1 a fixed frame generation multiplier makes no more frames than the display can show
(gpu/vk/framegen_refresh.h, vk_framegen.cpp framegen_record; no game, no GPU).

(Triforce, 11-21, the upscaler audit's UPS-05.) The Frame generation row's 2x to 8x made that many frames for each of the
game's whatever the display's refresh rate: the owner's log has 5x on a 165 Hz display with the game near 66 frames a
second, 331 frames a second presented, half of them never on the screen, each present call 2.2 to 3.0 ms.

This compiles framegen_refresh.h alone and checks the rule: the frames are the display's refreshes in a frame of the game,
rounded up, a tenth of a refresh forgiven; never more than the row's number, never fewer than the game's own frame; an
unknown frame time or refresh rate leaves the row's number; and the switch is off unless set.

And reads the source: framegen_record takes the row's multiplier through set_multiplier as before, and only then, with
the switch on and the row at 2x to 8x, through the rule, with the game's recent frame time and the display's period; the
row's Auto and AMD FSR's are not touched; and the switch is in the switches table.

    python -I -B tests/test_framegen_refresh.py [--cxx clang++]
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
#include <cstdint>
#include <cstdio>
#include <initializer_list>
#include "framegen_refresh.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
using namespace framegen_refresh;
static int64_t ns(double fps) { return (int64_t)(1e9 / fps); }
int main() {
    CHECK(!on(nullptr) && !on("") && !on("0") && on("1"));
    CHECK(period_ns(165000) == 6060606 && period_ns(60000) == 16666666 && period_ns(0) == 0 && period_ns(-1) == 0);
    const int64_t hz165 = period_ns(165000), hz120 = period_ns(120000), hz60 = period_ns(60000), hz240 = period_ns(240000);
    // (the owner's log: 5x, the game near 66 frames a second, 165 Hz: 2.5 refreshes a frame, 3 frames, not 5)
    CHECK(frames(5, ns(66), hz165) == 3);
    CHECK(frames(2, ns(66), hz165) == 2 && frames(3, ns(66), hz165) == 3 && frames(8, ns(66), hz165) == 3);
    // (a game at a whole fraction of the refresh rate is not given one more for its frames' jitter)
    CHECK(frames(4, ns(60), hz120) == 2 && frames(4, ns(59.5), hz120) == 2 && frames(4, ns(60.5), hz120) == 2);
    CHECK(frames(4, ns(30), hz120) == 4 && frames(8, ns(30), hz120) == 4 && frames(8, ns(30), hz240) == 8);
    CHECK(frames(4, ns(60), hz60) == 1 && frames(2, ns(60), hz60) == 1);   // (at the display's rate: the game's frames alone)
    CHECK(frames(4, ns(200), hz60) == 1 && frames(4, ns(165), hz165) == 1);   // (faster than the display: never under 1)
    CHECK(frames(2, ns(40), hz60) == 2 && frames(4, ns(40), hz60) == 2 && frames(4, ns(45), hz60) == 2);
    CHECK(frames(8, ns(20), hz165) == 8 && frames(8, ns(24), hz165) == 7);
    // (nothing known, or nothing to cap: the row's number)
    CHECK(frames(5, 0, hz165) == 5 && frames(5, ns(66), 0) == 5 && frames(5, -1, hz165) == 5);
    CHECK(frames(1, ns(66), hz165) == 1 && frames(0, ns(66), hz165) == 0);
    // (never more than the row asks, never fewer than one, over every row and a sweep of rates)
    for (int m = 1; m <= 8; m++)
        for (int fps = 10; fps <= 400; fps += 7)
            for (int64_t p : {hz60, hz120, hz165, hz240}) {
                const int f = frames(m, ns(fps), p);
                CHECK(f >= 1 && f <= m);
                // (what is shown never falls short of the display where the row's number would have reached it)
                if (m > 1 && (double)m * fps >= 1e9 / (double)p) CHECK((double)f * fps >= 0.9 * 1e9 / (double)p || f == m);
            }
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    fg = (VK / "vk_framegen.cpp").read_text(encoding="utf-8")

    check('#include "framegen_refresh.h"' in fg, "vk_framegen.cpp does not use the rule")
    rec = block(fg, "bool framegen_record(VkCommandBuffer cmd, VkImageView src, uint32_t sw, uint32_t sh, const int crop[4]) {")
    at = [rec.index(part) for part in (
        "fg.cv.wait(lk, [] { return !fg.sets[fg.next_set].busy && (!pace::display_yields() || fg.jobs.empty()); });",
        "int m = framegen_rows::set_multiplier(multiplier(), fg.mult);",
        'static const bool refresh_cap = framegen_refresh::on(getenv("RX_VK_FRAMEGEN_REFRESH"));',
        "if (refresh_cap && opts.framegen >= 2 && opts.framegen <= kMaxMult) {",
        "m = framegen_refresh::frames(m, fg.game_ns, framegen_refresh::period_ns(display_refresh_mhz()));",
        "const bool blend = fg.have_prev && !gap;",
        "if (opts.framegen == 1) {",
        "if (set->made == 0 && !none && blend && m > 1) {",
        "for (int k = 1; k < m; k++) make_frame(cmd, prev, cur, set->frame[k - 1], (float)k / (float)m, uw, uh);")]
    check(at == sorted(at), "framegen_record does not take the row's multiplier through set_multiplier and then, with the switch, the rule")
    check(rec.count("framegen_refresh::frames(") == 1 and "framegen_refresh::" not in fg.replace(rec, "").replace('#include "framegen_refresh.h"', ""),
          "the rule is asked somewhere else than framegen_record's fixed multipliers")
    auto = rec[rec.index("if (opts.framegen == 1) {"):rec.index("bool none = false;")]
    check("framegen_refresh" not in auto, "the row's Auto goes through the rule: it has its own, by the display's refreshes")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_FRAMEGEN_REFRESH=1`" in dev, "docs/development.md: RX_VK_FRAMEGEN_REFRESH=1 is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="framegen-refresh-") as tmp:
        c, exe = Path(tmp) / "refresh.cpp", Path(tmp) / "refresh.exe"
        c.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the rule as made:\n" + r.stdout)
    print("PASS: with RX_VK_FRAMEGEN_REFRESH=1 a fixed multiplier makes no more frames than the display can show")


if __name__ == "__main__":
    main()
