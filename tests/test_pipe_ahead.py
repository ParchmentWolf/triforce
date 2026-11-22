"""Where the pipelines the draws first need stand in the order, against where the draws are: the count the audit asks for
before a builder of whole pipelines just ahead (gpu/vk/pipe_ahead.h; vk_draw.cpp order_met, graphics_pipeline,
draw_left_out_take; no game, no GPU).

(Triforce, 11-22, the performance audit's PIPE-81, after Source B's: its first step.) In light mode every pipeline of a load
is new at its first draw. The entry would build whole pipelines just ahead of the draws from the order's next places, and
says to count first: each pipeline first drawn, its place ahead of where the draws are (or none), and whether the warm had
linked it; under a third within 1024 places, stop. This is the count alone: nothing is built or kept.

The header is compiled and run: the window's switch (1024 unset, 0 off, clamped to 4096); where a place stands against the
front (none, within, further, behind; from the order's start before the draws are placed); the entry's rule (a third or
more within the window). And the source: order_met counts under the order's lock before the front moves, only with the
order used and the window on, and those within the window the warm had linked; graphics_pipeline tells it whether the
warm's link was taken; the line every 600 presents says whether a builder would be worth it; the switches table has the row.

    python -I -B tests/test_pipe_ahead.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#include <cstdio>
#include "pipe_ahead.h"
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)
using namespace pipe_ahead;
int main() {
    CHECK(window(nullptr) == 1024 && window("") == 1024 && window("0") == 0 && window("-5") == 0 && window("256") == 256);
    CHECK(window("100000") == 4096 && window("1") == 1);
    CHECK(where(-1, 500, 1024) == Where::None && where(-1, -1, 1024) == Where::None);
    CHECK(where(500, 500, 1024) == Where::Near && where(1524, 500, 1024) == Where::Near && where(1525, 500, 1024) == Where::Far);
    CHECK(where(499, 500, 1024) == Where::Behind && where(0, 500, 1024) == Where::Behind);
    CHECK(where(0, -1, 1024) == Where::Near && where(1024, -1, 1024) == Where::Near && where(1025, -1, 1024) == Where::Far);
    CHECK(where(600, 500, 50) == Where::Far);
    CHECK(worth(1, 3) && !worth(1, 4) && worth(34, 100) && !worth(33, 100) && !worth(0, 0) && worth(5, 5));
    std::printf("ok\n");
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
    with tempfile.TemporaryDirectory(prefix="pipe-ahead-") as tmp:
        src, exe = Path(tmp) / "fixture.cpp", Path(tmp) / "fixture.exe"
        src.write_text(FIXTURE, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "gpu/vk"), str(src), "-o", str(exe)],
                       check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        need(r.returncode == 0 and r.stdout.strip() == "ok", "the count's rules: " + (r.stdout.strip() or "exit %d" % r.returncode))
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    need('#include "pipe_ahead.h"' in draw, "vk_draw.cpp does not include pipe_ahead.h")
    need('static const int64_t w = pipe_ahead::window(getenv("RX_VK_PIPE_AHEAD"));' in block(draw, "int64_t pipe_ahead_window() {"),
         "the window is not RX_VK_PIPE_AHEAD, read once")
    om = block(draw, "void order_met(uint64_t key, bool warm_linked = false) {")
    ordered(om, ["std::lock_guard lk(pipe_order_mu);", "pipe_order_rec.add(key);",
                 "if (pipe_order_used.load(std::memory_order_relaxed) && pipe_ahead_window()) {",
                 "pipe_ahead::where(pipe_order_index.at(key), pipe_order_front.furthest, pipe_ahead_window());",
                 "st_ahead[(int)w].fetch_add(1,", "if (w == pipe_ahead::Where::Near && warm_linked) st_ahead_warm.fetch_add(1,",
                 "!pipe_order_front.met(pipe_order_index.at(key))"],
            "order_met does not count before the front moves, under the order's lock, with the order used")
    gp = block(draw, "PipeEntry* graphics_pipeline(")
    ordered(gp, ["VkPipeline linked = warm_link_take(key);", "warm_linked = linked != VK_NULL_HANDLE;", "order_met(key, warm_linked);"],
            "graphics_pipeline does not tell the count whether the warm's link was taken")
    take = block(draw, "int64_t draw_left_out_take() {")
    ordered(take, ["if (pipe_ahead_window()) {", "if (calls >= a_told + 600 && none + placed != a_was) {",
                   "(RX_VK_PIPE_AHEAD)", "pipe_ahead::worth(within, placed + none)"],
            "the count's line is not written every 600 presents while it grows")
    need("vkCreateGraphicsPipelines" not in om and "build_graphics(" not in om, "the count builds something")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    need("`RX_VK_PIPE_AHEAD=<places>`" in docs, "docs/development.md: the switches table has no RX_VK_PIPE_AHEAD row")
    print("PASS: the pipelines first drawn are counted by their place against where the draws are (RX_VK_PIPE_AHEAD); nothing built")


if __name__ == "__main__":
    main()
