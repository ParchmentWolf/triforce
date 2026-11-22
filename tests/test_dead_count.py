"""What destroying the dead images costs a present is counted (gpu/vk/dead_count.h, vk_texture.cpp texture_frame; no game,
no GPU).

(Triforce, 11-21, the performance audit's THREAD-21, its first step.) texture_frame destroys every dead image the GPU is
done with in the middle of the present being recorded. The audit's port bounds that to a share a present, and its own
proof asks for the cost first: under 3 ms in every present, the bounded step is not built. This is the count.

This compiles dead_count.h alone: a present's loop adds to the totals, the worst present is kept with what it destroyed
and left, a present of 2 ms or more gets a line and one of 3 ms or more is counted apart, the totals' line is due every
600 presents and only when a present was counted, and reset starts afresh.

And reads the source: texture_frame times its loop, counts a destroyed image and a pooled one apart, and the loop itself
is as it was (the compaction's break, the GPU's progress, the pool, the four destroys).

    python -I -B tests/test_dead_count.py [--cxx clang++]
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


PROGRAM = r"""
#include <cstdint>
#include <cstdio>
#include "dead_count.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
int main() {
    dead_count::Counts c;
    CHECK(!c.due(600));                                   // (nothing counted yet: no line)
    CHECK(!c.note(3, 5, 0.4, 7));
    CHECK(c.presents == 1 && c.destroyed == 3 && c.pooled == 5 && c.worst_ms == 0.4 && c.worst_destroyed == 3 && c.worst_left == 7);
    CHECK(!c.note(0, 0, 0.0, 0) && c.presents == 2 && c.worst_ms == 0.4);
    CHECK(!c.note(40, 0, 1.99, 2) && c.over_say == 0 && c.worst_ms == 1.99 && c.worst_destroyed == 40);
    CHECK(c.note(300, 12, 2.0, 9) && c.over_say == 1 && c.over_worth == 0);        // (2 ms: a line of its own)
    CHECK(c.note(700, 0, 18.6, 0) && c.over_say == 2 && c.over_worth == 1);        // (3 ms or more: the audit's line)
    CHECK(c.worst_ms == 18.6 && c.worst_destroyed == 700 && c.worst_left == 0);
    CHECK(!c.note(1, 1, 0.1, 0) && c.worst_ms == 18.6);                            // (a smaller one after it does not replace it)
    CHECK(c.presents == 6 && c.destroyed == 1044 && c.pooled == 18);
    CHECK(c.ms > 23.08 && c.ms < 23.10);
    CHECK(c.due(600) && c.due(1200) && !c.due(601) && !c.due(599));
    c.reset();
    CHECK(c.presents == 0 && c.destroyed == 0 && c.worst_ms == 0 && c.over_say == 0 && !c.due(600));
    CHECK(dead_count::kSayMs == 2.0 && dead_count::kWorthMs == 3.0 && dead_count::kReport == 600);
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    tex = (VK / "vk_texture.cpp").read_text(encoding="utf-8").replace("\r\n", "\n")
    start = tex.index("void texture_frame(uint64_t completed) {")
    frame = tex[start:tex.index("\n}\n", start)]
    check('#include "dead_count.h"' in tex, "vk_texture.cpp does not use dead_count.h")
    at = 0
    for part in ("static dead_count::Counts dead_ct;", "const auto dead_t0 = std::chrono::steady_clock::now();",
                 "for (auto it = dead.begin(); it != dead.end();) {", "if (compact.in_pass) break;",
                 "if (it->value > completed) {", "pool_put(*it);", "dead_pooled++;",
                 "for (VkImageView v : it->views) vkDestroyImageView(dev.device, v, nullptr);",
                 "destroy_image(it->image, it->allocation);", "if (it->buffer) destroy_buffer(it->buffer, it->buffer_alloc);",
                 "for (VkDeviceMemory m : it->memory) vkFreeMemory(dev.device, m, nullptr);", "dead_destroyed++;",
                 "dead_ct.note(dead_destroyed, dead_pooled, dead_ms, dead.size())", "if (dead_ct.due(frame_no)) {",
                 "dead_ct.reset();", "pool_trim();"):
        at = frame.find(part, at)
        check(at >= 0, "texture_frame: the dead images' loop is not timed and counted as it was (missing, or out of order: " + part + ")")
        at += len(part)

    with tempfile.TemporaryDirectory(prefix="dead-count-") as tmp:
        c, exe = Path(tmp) / "dead.cpp", Path(tmp) / "dead.exe"
        c.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the counts as made:\n" + r.stdout)
    print("PASS: what destroying the dead images costs a present is counted")


if __name__ == "__main__":
    main()
