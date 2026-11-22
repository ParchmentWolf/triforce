"""A redraw of the stored draws sets only what differs from what its pass has set (gpu/vk/redraw_state.h,
vk_temporal.cpp capture_motion; no game, no GPU).

(Triforce, 11-21, the upscaler audit's UPS-03.) The stored draws are drawn again into the motion vectors in one pass,
about 900 a frame in the owner's log. Each set the primitive topology, the primitive restart and its index buffer before
it drew, whatever the draw before had set: nearly every draw of the scene is a triangle list without restart.

This compiles redraw_state.h alone and checks the rule: a pass's first draw sets all three; a draw the same as the one
before sets none; each of the three is set again when it alone changes, and the index buffer when its buffer, its offset
or its type does; what was set is what the last command said, so a value that comes back is set again; a new pass knows
nothing of the one before; with RX_VK_REDRAW_STATE=0 every draw sets all three; and over a frame of 900 draws the commands
left out are counted.

And reads the source: capture_motion asks the rule before each of the three commands, with one Pass of its own made after
begin_redraw and the switch read once; the push constants and the draw itself are recorded for every draw; and the switch
is in the switches table.

    python -I -B tests/test_redraw_state.py [--cxx clang++]
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
#include "redraw_state.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
using namespace redraw_state;
int main() {
    CHECK(!every(nullptr) && !every("") && !every("1") && every("0"));
    {   // the first draw sets all three; the same again sets none
        Pass p;
        CHECK(topology(p, 3) && restart(p, false) && index(p, 0x1000, 64, 1));
        CHECK(!topology(p, 3) && !restart(p, false) && !index(p, 0x1000, 64, 1));
        CHECK(p.set == 3 && p.left == 3);
        // (each alone, when it changes)
        CHECK(topology(p, 4) && !restart(p, false) && !index(p, 0x1000, 64, 1));
        CHECK(!topology(p, 4) && restart(p, true) && !index(p, 0x1000, 64, 1));
        // (the index buffer: another buffer, another offset, another type)
        CHECK(index(p, 0x2000, 64, 1) && !index(p, 0x2000, 64, 1));
        CHECK(index(p, 0x2000, 128, 1) && !index(p, 0x2000, 128, 1));
        CHECK(index(p, 0x2000, 128, 0) && !index(p, 0x2000, 128, 0));
        // (what is set is what the last command said: a value that comes back is set again)
        CHECK(topology(p, 3) && topology(p, 4) && topology(p, 3) && !topology(p, 3));
        CHECK(restart(p, false) && restart(p, true) && !restart(p, true));
        CHECK(index(p, 0x1000, 64, 1) && index(p, 0x2000, 128, 0) && index(p, 0x1000, 64, 1));
    }
    {   // a draw without indices leaves the bound index buffer as it is: the next indexed draw of the same one sets nothing
        Pass p;
        CHECK(topology(p, 3) && restart(p, false) && index(p, 0x1000, 0, 1));
        CHECK(!topology(p, 3) && !restart(p, false));   // (a plain array of vertices: no index asked)
        CHECK(!index(p, 0x1000, 0, 1));
    }
    {   // topology 0 (a point list) and a buffer at offset 0 are set too: nothing is taken as set before it was
        Pass p;
        CHECK(topology(p, 0) && restart(p, false) && index(p, 0, 0, 0));
        CHECK(!topology(p, 0) && !restart(p, false) && !index(p, 0, 0, 0));
    }
    {   // a new pass knows nothing of the one before
        Pass a;
        topology(a, 3), restart(a, false), index(a, 0x1000, 0, 1);
        Pass b;
        CHECK(topology(b, 3) && restart(b, false) && index(b, 0x1000, 0, 1));
    }
    {   // RX_VK_REDRAW_STATE=0: every draw sets all three, as before
        Pass p;
        p.all = true;
        for (int i = 0; i < 50; i++) CHECK(topology(p, 3) && restart(p, false) && index(p, 0x1000, 64, 1));
        CHECK(p.set == 150 && p.left == 0);
    }
    {   // a frame of 900 triangle lists without restart, a new index buffer place every third draw: 2 + 300 commands, not 2,700
        Pass p;
        for (uint32_t i = 0; i < 900; i++) {
            if (topology(p, 3)) {}
            if (restart(p, false)) {}
            if (index(p, 0x1000, (uint64_t)(i / 3) * 96, 1)) {}
        }
        CHECK(p.set == 2 + 300 && p.left == 2700 - 302);
    }
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    src = (VK / "vk_temporal.cpp").read_text(encoding="utf-8")

    check('#include "redraw_state.h"' in src, "vk_temporal.cpp does not use the rule")
    motion = block(src, "int capture_motion(VkCommandBuffer cmd, const Camera& cam, const float* before, const float* reproject, uint32_t rw,")
    at = [motion.index(part) for part in (
        "if (!begin_redraw(cmd, s.capture, cam, before, to.jitter_before, reproject, rw, rh, dview, to.motion)) return 0;",
        'static const bool set_every = redraw_state::every(getenv("RX_VK_REDRAW_STATE"));',
        "redraw_state::Pass set;",
        "set.all = set_every;",
        "for (const Redraw& d : draws) {",
        "vkCmdPushConstants(cmd, s.actor_layout, VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof d.push, &d.push);",
        "if (redraw_state::topology(set, (uint32_t)k.topology)) vkCmdSetPrimitiveTopology(cmd, k.topology);",
        "if (redraw_state::restart(set, k.restart)) vkCmdSetPrimitiveRestartEnable(cmd, k.restart ? VK_TRUE : VK_FALSE);",
        "if (redraw_state::index(set, (uint64_t)d.ib.buffer, (uint64_t)d.ib.offset, (uint32_t)type))",
        "vkCmdBindIndexBuffer(cmd, d.ib.buffer, d.ib.offset, type);",
        "vkCmdDrawIndexed(cmd, (uint32_t)k.count, 1, 0, k.base_vertex, 0);",
        "vkCmdDraw(cmd, (uint32_t)k.count, 1, (uint32_t)k.base_vertex, 0);",
        "vkCmdEndRendering(cmd);")]
    check(at == sorted(at), "capture_motion does not ask the rule before each of the three commands, in a pass of its own after begin_redraw")
    loop = motion[motion.index("for (const Redraw& d : draws) {"):motion.index("vkCmdEndRendering(cmd);")]
    check(loop.count("vkCmdSetPrimitiveTopology(") == 1 and loop.count("vkCmdSetPrimitiveRestartEnable(") == 1 and
          loop.count("vkCmdBindIndexBuffer(") == 1, "a state command is recorded without the rule being asked")
    check(motion.count("redraw_state::Pass set;") == 1 and "redraw_state::Pass" not in src.replace(motion, ""),
          "the pass's state is not capture_motion's own, made anew for each pass")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_REDRAW_STATE=0`" in dev, "docs/development.md: RX_VK_REDRAW_STATE=0 is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="redraw-state-") as tmp:
        c, exe = Path(tmp) / "state.cpp", Path(tmp) / "state.exe"
        c.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the rule as made:\n" + r.stdout)
    print("PASS: a redraw of the stored draws sets only what differs from what its pass has set")


if __name__ == "__main__":
    main()
