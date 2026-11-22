"""Only depth-only occlusion windows counted, behind a switch that is off (gpu/vk/occ_answer.h Counter::colour_draw;
vk_replay.cpp occ_draw_colour, occ_depth_only; vk_draw.cpp draw; no game, no GPU).

(Triforce, 11-22, the performance audit's GPUWORK-01, after Source A's.) The game's occlusion tests draw depth only. A
query here opens at a window's first draw in the pass and stays open to the report or the pass's end, so it can enclose
draws that write colour, and a query's end waits for the work it encloses. Source A counts a run only when its draws
write no colour. Here: every draw that writes a colour target is told to the count before a query may begin. That is
counted for the occlusion line whether or not the rule is on (the windows that met one, the colour draws recorded under
an open query). With RX_VK_OCC_DEPTH_ONLY=1, or in the lab's "occdepth" phases, the count is given up there: its open
query ends before the colour draw, no query begins again until the next reset, and its report is incomplete, so the
record keeps the placeholder and what it gates is drawn. Off by default: it culls fewer objects.

Runs tests/occ_answer_test.cpp (the header's cases, the colour ones among them: tests/test_occ_answer.py runs it too,
after source checks of its own).

Cuts occ_depth_only, occ_draw_colour, occ_draw_begin and occ_close out of vk_replay.cpp and records windows through them
on a stand-in command buffer:
  - off: a window of a depth draw, a colour draw and a depth draw is one query over all three, measured, as before, and
    the window and its colour draw under the query are counted;
  - on (the switch, and the lab's knob): the query ends before the colour draw, none begins after it, the report is
    incomplete for that reason; the next window, depth only, is measured again;
  - a colour draw first in its window, on: no query at all for that window;
  - 64 colour draws under one query, off: counted in one step of 64.

Reads the source: draw tells a colour draw (its write mask's colour bits) to the count right before occ_draw_begin, only
in an open pass with the queries live; the switch is read once and is off unless set; the report's breakdown has the
reason; the line is logged; vk_draw.h declares the hook; the switches table has the row.

    python -I -B tests/test_occ_depth_only.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#include "occ_answer.h"
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s (events: %s)\n", __LINE__, #x, events.c_str()); return 1; } } while (0)

namespace occ = mkwvk::occ;
using VkCommandBuffer = int;
using VkQueryPool = int;
using VkQueryControlFlags = uint32_t;
namespace lab_ab {
bool knob = false;
bool on(const char* name) { return knob && !strcmp(name, "occdepth"); }
}
std::string events;   // (what was recorded: B<i> a query begun, E<i> ended, D a depth draw, C a colour draw)
void vkCmdBeginQuery(VkCommandBuffer, VkQueryPool, uint32_t i, VkQueryControlFlags) { events += "B" + std::to_string(i) + " "; }
void vkCmdEndQuery(VkCommandBuffer, VkQueryPool, uint32_t i) { events += "E" + std::to_string(i) + " "; }
constexpr uint32_t kOccPerSlot = 1024;
struct OccSlot { uint32_t used = 0; } occ_slots[2];
VkQueryPool occ_pool = 1;
VkQueryControlFlags occ_flags = 0;
std::atomic<bool> occ_keep{false};
thread_local bool occ_open_here = false;
static occ::Counter counter;
occ::Counter& occ_ctr() { return counter; }
static const uint64_t kSerial = 7;
uint64_t occ_serial_of(VkCommandBuffer, int* slot) { *slot = 0; return kSerial; }
/* CUT */

static const VkCommandBuffer cmd = 5;
static void draw(bool colour) {   // (vk_draw.cpp draw's order)
    counter.draw_enter(occ_keep);
    if (colour) occ_draw_colour(cmd);
    occ_draw_begin(cmd);
    events += colour ? "C " : "D ";
    counter.draw_issued(occ_keep);
}
static occ::Counter::Outcome report(occ::Rep* r) {   // (vk_replay.cpp's report: the open query ends, then the count)
    bool keep_now = false;
    occ_close(counter, cmd);
    return counter.report(occ_keep, kSerial, occ_slots[0].used, r, &keep_now);
}

int main(int argc, char** argv) {
    const std::string mode = argc > 1 ? argv[1] : "";
    const bool rule = mode != "off";
    if (mode == "knob") lab_ab::knob = true;
    CHECK(occ_depth_only() == rule);
    occ::Rep r;
    // a window with a colour draw between two depth draws
    counter.reset(0, kSerial, occ_slots[0].used);
    draw(false), draw(true), draw(false);
    const occ::Counter::Outcome first = report(&r);
    if (!rule) {
        CHECK(events == "B0 D C D E0 " && first == occ::Counter::kMeasured && r.first == 0 && r.n == 1);
        CHECK(occ_colour_windows == 1 && occ_colour_lost == 0 && counter.why == occ::Counter::kNone);
        // 64 colour draws under one query: counted in one step
        events.clear();
        counter.reset(0, kSerial, occ_slots[0].used);
        draw(false);
        for (int i = 0; i < 62; i++) draw(true);
        CHECK(occ_colour_open == 0);
        draw(true);   // (the 64th of this thread, the first window's one among them)
        CHECK(occ_colour_open == 64 && occ_colour_windows == 2 && report(&r) == occ::Counter::kMeasured && r.n == 1);
        std::printf("ok off\n");
        return 0;
    }
    CHECK(events == "B0 D E0 C D " && first == occ::Counter::kIncomplete && counter.why == occ::Counter::kColour);
    CHECK(occ_colour_windows == 1 && occ_colour_lost == 1 && !occ_open_here && occ_slots[0].used == 1);
    // the next window, depth only: measured, with a query of its own
    events.clear();
    counter.reset(0, kSerial, occ_slots[0].used);
    draw(false), draw(false);
    CHECK(report(&r) == occ::Counter::kMeasured && events == "B1 D D E1 " && r.first == 1 && r.n == 1 && occ_colour_lost == 1);
    // a colour draw first in its window: no query at all
    events.clear();
    counter.reset(0, kSerial, occ_slots[0].used);
    draw(true), draw(false), draw(true);
    CHECK(report(&r) == occ::Counter::kIncomplete && events == "C D C " && counter.why == occ::Counter::kColour && occ_colour_lost == 2);
    CHECK(occ_slots[0].used == 2 && occ_colour_windows == 2);
    std::printf("ok %s\n", mode.c_str());
    return 0;
}
"""


def block(text, marker):
    start = text.index(marker)
    at = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[at] == "{") - (text[at] == "}")
        at += 1
    return text[start:at]


def need(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def ordered(text, parts, why):
    last = 0
    for p in parts:
        k = text.find(p, last)
        need(k >= 0, why + " (missing, or out of order: " + p + ")")
        last = k + len(p)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    only = block(replay, "bool occ_depth_only() {")
    need('static const bool env = getenv("RX_VK_OCC_DEPTH_ONLY") && atoi(getenv("RX_VK_OCC_DEPTH_ONLY")) != 0;' in only and
         'return env || lab_ab::on("occdepth");' in only, "the switch is not RX_VK_OCC_DEPTH_ONLY, off unless set, with the lab's occdepth knob")
    colour = block(replay, "void occ_draw_colour(VkCommandBuffer cmd) {")
    ordered(colour, ["c.colour_draw(occ_keep.load(std::memory_order_relaxed), occ_depth_only());", "if (!m.lose) return;",
                     "occ_close(c, cmd);", "c.lose_colour();"], "occ_draw_colour does not end the open query and give the count up only under the rule")
    ordered(replay, ["void occ_close(occ::Counter& c, VkCommandBuffer cmd) {", "c.why == occ::Counter::kColour ? occ_st.inc_colour",
                     "bool occ_depth_only() {", "void occ_present_tick() {", "occ_st.colour_line(line, sizeof line, 600, occ_depth_only());",
                     "void occ_draw_colour(VkCommandBuffer cmd) {", "void occ_draw_begin(VkCommandBuffer cmd) {"],
            "vk_replay.cpp: the report's breakdown, the line or the hook is missing")
    body = block(draw, "void draw(VkCommandBuffer cmd, NvnState& s, const DrawArgs& d) {")
    ordered(body, ["uint16_t writes;", "writes = draw_hazards(cmd, p, s, at);", "begin_pass(cmd, at);",
                   "if (occ_live && ps.open && (writes & 0xFF)) occ_draw_colour(cmd);\n    if (occ_live && ps.open) occ_draw_begin(cmd);"],
            "draw does not tell a colour draw to the count right before a query may begin")
    need(body.count("occ_draw_colour(") == 1, "draw tells a colour draw to the count in more than one place")
    hazards = block(draw, "uint16_t draw_hazards(")
    need("if (at.color[i] && target_write_mask(p, s, i)) writes |= (uint16_t)(1u << i);" in hazards and "writes |= 1u << 8;" in hazards,
         "the write mask's colour bits are no longer bits 0 to 7 with the depth's at 8")
    need("void occ_draw_colour(VkCommandBuffer cmd);" in (ROOT / "gpu/vk/vk_draw.h").read_text(encoding="utf-8"), "vk_draw.h does not declare the hook")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    need("`RX_VK_OCC_DEPTH_ONLY=1`" in docs and "occdepth" in docs, "docs/development.md: the switches table has no RX_VK_OCC_DEPTH_ONLY row")
    cut = replay[replay.index("bool occ_depth_only() {"):replay.index("/// Once a present: the sealed recordings done read")]
    cut += block(replay, "void occ_close(occ::Counter& c, VkCommandBuffer cmd) {") + "\n" + colour + "\n" + \
        block(replay, "void occ_draw_begin(VkCommandBuffer cmd) {")
    env = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_")}
    flags = ["-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-D_CRT_SECURE_NO_WARNINGS", "-I" + str(ROOT / "gpu/vk")]
    with tempfile.TemporaryDirectory(prefix="occ-depth-only-") as tmp:
        tmp = Path(tmp)
        header = tmp / "occ_answer_test.exe"
        subprocess.run([args.cxx, *flags, str(ROOT / "tests/occ_answer_test.cpp"), "-o", str(header)], check=True)
        subprocess.run([str(header)], check=True, env=env, timeout=120)
        cpp, exe = tmp / "fixture.cpp", tmp / "fixture.exe"
        cpp.write_text(FIXTURE.replace("/* CUT */", cut), encoding="utf-8")
        subprocess.run([args.cxx, *flags, str(cpp), "-o", str(exe)], check=True)
        for mode, more in (("off", {}), ("on", {"RX_VK_OCC_DEPTH_ONLY": "1"}), ("knob", {}), ("off", {"RX_VK_OCC_DEPTH_ONLY": "0"})):
            r = subprocess.run([str(exe), mode], capture_output=True, text=True, timeout=60, env={**env, **more})
            need(r.returncode == 0 and r.stdout.strip() == "ok " + mode, "the windows recorded (%s): %s" % (mode, r.stdout.strip() or r.returncode))
            print(r.stdout.strip())
    print("PASS: a window that meets a colour draw is counted for the line, and given up only with RX_VK_OCC_DEPTH_ONLY=1 "
          "(off by default)")


if __name__ == "__main__":
    main()
