"""A submission's part ends only right before a plain draw, on Intel's GPUs (gpu/vk/barrier_rules.h; no game, no GPU).

(Triforce, 11-22, the performance audit's REPLAY-14, after Source A's.) On an Arc B580 a command buffer that begins with
mesh draws drew its later plain draws as exploded triangles. Source A ends a part only right before a plain draw; here
a helper thread's segment can begin with mesh draws too, so the dry pass makes its points the same way.

Compiles a small driver against the header and checks:
  split_before_draw   unset: on for vendor 0x8086 (Intel), off for NVIDIA, AMD and any other; 0 off and 1 on with any
                      vendor; an empty value is unset;
  cut_ok              only a plain draw with rendering on and no rasterizer discard: not a mesh draw or a dispatch (not
                      plain), not with rendering off, not with the rasterizer discarding.

And reads gpu/vk/vk_replay.cpp: the op loop's top asks cut_ok with the three plain draw ops and the state before the op,
on the replay's own thread only; maybe_split at the count sets part_end_wanted and returns where the rule is on, and
splits only when the loop's top calls it; the dry pass sets dry_point_wanted at its count where the rule is on and makes
the point at the plain draw with the state before it; both flags are cleared with a new submission or dry pass; and the
docs row.

    python -I -B tests/test_split_before_draw.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

DRIVER = r'''
#include <cstdint>
#include <cstddef>
#include "barrier_rules.h"
#include <cstdio>
#include <initializer_list>

using namespace mkwvk::barrier_rules;
static int checks, fails;
static void want(const char* what, bool got, bool wanted) {
    checks++;
    if (got != wanted) fails++, printf("FAIL %s: %d, want %d\n", what, (int)got, (int)wanted);
}

int main() {
    const uint32_t intel = 0x8086, nvidia = 0x10DE, amd = 0x1002, other = 0x5143;
    want("unset, Intel", split_before_draw(nullptr, intel), true);
    for (const uint32_t v : {nvidia, amd, other}) {
        want("unset, another vendor", split_before_draw(nullptr, v), false);
        want("empty is unset, another vendor", split_before_draw("", v), false);
        want("1, another vendor", split_before_draw("1", v), true);
        want("0, another vendor", split_before_draw("0", v), false);
    }
    want("empty is unset, Intel", split_before_draw("", intel), true);
    want("0, Intel", split_before_draw("0", intel), false);
    want("1, Intel", split_before_draw("1", intel), true);
    // cut_ok(plain draw, rendering on, rasterizer discard)
    want("a plain draw that draws", cut_ok(true, true, false), true);
    want("a mesh draw or a dispatch", cut_ok(false, true, false), false);
    want("a plain draw with rendering off", cut_ok(true, false, false), false);
    want("a plain draw with the rasterizer discarding", cut_ok(true, true, true), false);
    want("nothing at all", cut_ok(false, false, true), false);
    if (fails) printf("split before draw: FAILED (%d of %d checks)\n", fails, checks);
    else printf("split before draw: all %d checks passed\n", checks);
    return fails != 0;
}
'''


def block(src, start):
    at = src.index(start)
    return src[at:src.index("\n}\n", at)]


def check_source():
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    loop = block(replay, "void replay(VkCommandBuffer& cmd, NvnState& s, const uint8_t* p, const uint8_t* end = nullptr) {")
    top = ("        if (!worker && (part_end_wanted || dry_point_wanted) &&\n"
           "            barrier_rules::cut_ok(h.op == NOP_DRAW || h.op == NOP_DRAW_IDX || h.op == NOP_DRAW_INDIRECT, "
           "s.render_enabled, s.raster_discard)) {\n")
    if top not in loop or loop.index(top) > loop.index("switch (h.op) {"):
        raise SystemExit("replay: the op loop's top does not ask cut_ok with the three plain draws and the state before the op, "
                         "on the replay's own thread, before the op is replayed")
    cut = loop[loop.index(top):loop.index("switch (h.op) {")]
    order = [cut.find(n) for n in (
        "if (dry && dry_point_wanted) {", "dry_point_wanted = false;",
        "if (!seg_early_hook || seg_early_hook->wants(dry_work, p)) {",
        "par_points.push_back({p, s, ub_updates.size(), par_conds.size(), dry_work});",
        "} else if (!dry && part_end_wanted) {", "part_end_now = true;", "maybe_split(cmd);", "part_end_now = false;")]
    if min(order) < 0 or order != sorted(order):
        raise SystemExit("replay: the cut before a plain draw does not make the dry pass's point there, or the serial replay's split")
    count = ("                if (++dry_work % par_point_every() == 0) {\n"
             "                    // ((Triforce, 11-22, REPLAY-14) on Intel the point is made at the next plain draw: the loop's top)\n"
             "                    if (split_before_draw_on()) dry_point_wanted = true;\n")
    if count not in loop or "else if (!seg_early_hook || seg_early_hook->wants(dry_work, p + h.size)) {" not in loop:
        raise SystemExit("replay: the dry pass's count does not hand its point to the next plain draw where the rule is on, and "
                         "make it at once where it is off")
    if "if (!worker) maybe_split(cmd);" not in loop:
        raise SystemExit("replay: the serial replay no longer counts its parts after each draw and dispatch")
    split = block(replay, "void maybe_split(VkCommandBuffer& cmd) {")
    order = [split.find(n) for n in (
        "if (tail_on()) return;", "if (part_end_now) {", "part_end_wanted = false;",
        "if (!rec_cur || rec_parts + 1 >= kMaxParts || dump_on()) return;", "} else {", "if (part_end_wanted) return;",
        "if (!rec_cur || every <= 0 || ++part_work < every || rec_parts + 1 >= kMaxParts || dump_on()) return;",
        "if (split_before_draw_on()) {", "part_end_wanted = true;", "end_pass(cmd);", "submit_recording(*rec_cur, false, 0, true);",
        "part_work = 0;")]
    if min(order) < 0 or order != sorted(order):
        raise SystemExit("maybe_split: at the count it does not hold the part's end for the next plain draw where the rule is on, "
                         "or the held cut does not go through the same split")
    if replay.count("part_work = 0, part_end_wanted = false;") != 2:
        raise SystemExit("a new submission does not clear part_end_wanted with part_work")
    if replay.count("dry_work = 0, dry_point_wanted = false;") != 2:
        raise SystemExit("a new dry pass does not clear dry_point_wanted with dry_work")
    rules = block(replay, "bool split_rules(int which) {")
    if 'barrier_rules::split_before_draw(getenv("RX_VK_SPLIT_BEFORE_DRAW"), dev.props.vendorID);' not in rules:
        raise SystemExit("split_rules does not read RX_VK_SPLIT_BEFORE_DRAW with the vendor, once")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    if "| `RX_VK_SPLIT_BEFORE_DRAW=0` or `1` |" not in docs:
        raise SystemExit("docs/development.md: the switches table has no row for RX_VK_SPLIT_BEFORE_DRAW")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="split-draw-") as tmp:
        cpp, exe = Path(tmp) / "split_draw_test.cpp", Path(tmp) / "split-draw.exe"
        cpp.write_text(DRIVER, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "gpu/vk"), str(cpp), "-o", str(exe)],
                       check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.returncode:
            raise SystemExit("FAIL: the split-before-draw rule's checks failed")


if __name__ == "__main__":
    main()
