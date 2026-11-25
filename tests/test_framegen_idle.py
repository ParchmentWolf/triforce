"""Frame generation's images are let go 120 presents after it stops (gpu/vk/framegen_idle.h, vk_framegen.cpp
framegen_idle, vk_replay.cpp's present; no game, no GPU).

(Triforce, 11-21, the performance audit's PRESENT-18, after Source A's.) The built-in interpolation's frames and
made-frame sets were kept until a resize: turned off, or left for NVIDIA's own frame generation, they stayed in VRAM.

This compiles framegen_idle.h alone and checks the rule: 119 presents off let nothing go and the 120th does; a present
with it on, or one that recorded made frames while the row already reads off, starts the count again; nothing goes with
no images; the images of the picture without the HUD have a count of their own, which only AMD FSR 4's row holds at
zero; RX_VK_FG_KEEP keeps everything while the counts go on.

And reads the source: framegen_idle asks the rule with the row read again, what this present recorded and what there
is; before anything is dropped the display thread is done with its sets and every queue is idle; the present calls it
right after framegen_queue, with what it recorded; the switch is in the switches table.

    python -I -B tests/test_framegen_idle.py [--cxx clang++]
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
#include "framegen_idle.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
using namespace framegen_idle;
int main() {
    CHECK(kPresents == 120);
    {   // off for 119 presents: nothing; the 120th lets them go
        Counts c;
        Release r{};
        for (int i = 0; i < 119; i++) { r = step(c, {false, false, false, true, false}, false); CHECK(!r.shared && !r.hudless); }
        r = step(c, {false, false, false, true, false}, false);
        CHECK(r.shared && !r.hudless && c.off == 120);
    }
    {   // 119 off, then a present that recorded made frames though the row reads off by then: the count starts again
        Counts c;
        for (int i = 0; i < 119; i++) step(c, {false, false, false, true, false}, false);
        Release r = step(c, {false, true, false, true, false}, false);
        CHECK(!r.shared && c.off == 0);
        for (int i = 0; i < 119; i++) { r = step(c, {false, false, false, true, false}, false); CHECK(!r.shared); }
        CHECK(step(c, {false, false, false, true, false}, false).shared);
    }
    {   // on: never, however long
        Counts c;
        for (int i = 0; i < 1000; i++) CHECK(!step(c, {true, i % 2 == 0, false, true, false}, false).shared);
        CHECK(c.off == 0);
    }
    {   // no images: nothing to let go, and the count goes on for when there are
        Counts c;
        for (int i = 0; i < 500; i++) CHECK(!step(c, {false, false, false, false, false}, false).shared);
        CHECK(step(c, {false, false, false, true, false}, false).shared);
    }
    {   // the picture without the HUD: held by AMD FSR 4's row alone; another kind of frame generation lets it go
        Counts c;
        for (int i = 0; i < 300; i++) CHECK(!step(c, {true, true, true, true, true}, false).hudless);
        Release r{};
        for (int i = 0; i < 119; i++) { r = step(c, {true, true, false, true, true}, false); CHECK(!r.hudless && !r.shared); }
        r = step(c, {true, true, false, true, true}, false);
        CHECK(r.hudless && !r.shared);
        CHECK(!step(c, {true, true, false, true, false}, false).hudless);   // (gone: nothing more to let go)
        Counts d;                                                             // (wanted by the row, but frame generation off)
        for (int i = 0; i < 119; i++) step(d, {false, false, true, true, true}, false);
        r = step(d, {false, false, true, true, true}, false);
        CHECK(r.hudless && r.shared);
    }
    {   // RX_VK_FG_KEEP: kept, the counts going on
        Counts c;
        for (int i = 0; i < 400; i++) {
            const Release r = step(c, {false, false, false, true, true}, true);
            CHECK(!r.shared && !r.hudless);
        }
        CHECK(c.off == 400 && step(c, {false, false, false, true, true}, false).shared);
    }
    CHECK(next_off(UINT32_MAX, false, false) == UINT32_MAX);   // (a long run off does not wrap round to on)
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    fg = (VK / "vk_framegen.cpp").read_text(encoding="utf-8")
    replay = (VK / "vk_replay.cpp").read_text(encoding="utf-8")

    check('#include "framegen_idle.h"' in fg, "vk_framegen.cpp does not use the rule")
    idle = block(fg, "void framegen_idle(bool recorded) {")
    check("const bool on = framegen_on();" in idle and
          "framegen_idle::Present p{on, recorded, fsr4fg::frames_wanted(), fg.w != 0, have_hudless};" in idle and
          "const framegen_idle::Release go = framegen_idle::step(counts, p, keep);" in idle,
          "framegen_idle does not ask the rule with the row read again, what this present recorded and what there is")
    check('getenv("RX_VK_FG_KEEP") && atoi(getenv("RX_VK_FG_KEEP")) != 0' in idle, "the switch is not RX_VK_FG_KEEP")
    at = [idle.index(part) for part in (
        "if (!go.shared && !go.hudless) return;",
        "fg.cv.wait(lk, [] { return fg.jobs.empty() && !fg.sets[0].busy && !fg.sets[1].busy && !fg.sets[2].busy; });",
        "device_wait_idle_locked();", "drop_size();", "drop_img(hl.srgb), drop_img(hl.out)")]
    check(at == sorted(at), "an image is dropped before the display thread is done with its sets and every queue is idle")
    check("if (go.shared) {" in idle and "if (go.hudless) {" in idle and idle.index("if (go.hudless) {") < idle.index("std::lock_guard lk(hl.mu);", idle.index("if (go.hudless) {")),
          "the two kinds of images are not let go each by its own count, the HUD-less ones under their lock")
    start = replay.index("if (interpolated) framegen_queue(value);")
    after = replay[start:start + 900]
    # (after the queue and the else that belongs to it, which counts the frame for the FPS line)
    check("framegen_idle(interpolated);" in after and replay.count("framegen_idle(") == 1 and
          after.index("else if (!held) menu_note_frame(") < after.index("framegen_idle(interpolated);"),
          "the present does not count after framegen_queue and its else, with what it recorded")
    check("void framegen_idle(bool recorded);" in (VK / "vk_framegen.h").read_text(encoding="utf-8"), "vk_framegen.h does not declare it")
    # (unchanged, as the tests that compile or read them need: the remake after a resize and AMD's context's own release)
    check("void drop_size() {" in fg and "bool ensure_size(VkCommandBuffer cmd, uint32_t w, uint32_t h) {" in fg and
          "void framegen_present_tick() { fsr4fg::present_tick(); }" in fg, "ensure_size, drop_size or framegen_present_tick changed")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_FG_KEEP=1`" in dev, "docs/development.md: RX_VK_FG_KEEP=1 is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="framegen-idle-") as tmp:
        c, exe = Path(tmp) / "idle.cpp", Path(tmp) / "idle.exe"
        c.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the rule as made:\n" + r.stdout)
    print("PASS: frame generation's images are let go 120 presents after it stops, the GPU idle first")


if __name__ == "__main__":
    main()
