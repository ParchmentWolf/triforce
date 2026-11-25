"""The FPS counter row's levels between On and Full (gpu/vk/fps_levels.h): the saved values keep their meaning, the row steps
in the order of what each shows, the parts of a frame add up to it, and the graph's scale. Compiled and run; no game.

python -I -B tests/test_fps_levels.py [--cxx g++]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "g++"]
ROOT = Path(__file__).resolve().parents[1]

C = r'''
#include "fps_levels.h"
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
using namespace mkwvk::fps_levels;
int main() {
    // (an options file from before: 0 Off, 1 On, 2 Full, as they were)
    CHECK(kOff == 0 && kOn == 1 && kFull == 2 && !std::strcmp(name(0), "Off") && !std::strcmp(name(1), "On") && !std::strcmp(name(2), "Full"));
    // (the row's order: Off, On, Frame time, Graph, Breakdown, Dev, Full; it stops at its ends)
    int v = kOff;
    const int want[] = {kOn, kFrameTime, kGraph, kBreakdown, kDev, kFull, kFull};
    for (int w : want) {
        v = step(v, 1);
        CHECK(v == w);
    }
    CHECK(step(kOff, -1) == kOff && step(kFrameTime, -1) == kOn && step(kFull, -1) == kDev);
    CHECK(measures(kFull) && measures(kFrameTime) && measures(kDev) && !measures(kOn) && !measures(kOff));
    CHECK(shows_graph(kGraph) && !shows_graph(kFrameTime) && !shows_graph(kFull) && shows_breakdown(kDev) && !shows_dev(kBreakdown));
    // (the parts: the renderer's own time is its prep less its waits; the game's the rest of the frame)
    double p[kParts];
    split(16.0, 6.0, 1.0, 2.0, p);
    CHECK(std::fabs(p[kRender] - 3.0) < 1e-9 && std::fabs(p[kPipeWait] - 1.0) < 1e-9 && std::fabs(p[kShaderWait] - 2.0) < 1e-9);
    CHECK(std::fabs(p[kGame] - 10.0) < 1e-9);
    split(4.0, 6.0, 1.0, 1.0, p);   // (more than the frame: scaled to it, the game none)
    CHECK(std::fabs(p[kRender] + p[kPipeWait] + p[kShaderWait] - 4.0) < 1e-9 && p[kGame] < 1e-9);
    // (the graph: twice the target, more while the usual frame does not fit; Uncapped from 4 ms)
    CHECK(graph_top(16.6667, 10) > 33.3 && graph_top(16.6667, 10) < 33.4);
    CHECK(graph_top(16.6667, 40) > 66.6 && graph_top(16.6667, 40) < 66.7);
    CHECK(graph_top(0, 2) == 4 && graph_top(0, 30) == 64);
    char b[64];
    frame_time_text(b, sizeof b, 16.67);
    CHECK(!std::strcmp(b, "16.7 ms"));
    low_text(b, sizeof b, 50);
    CHECK(!std::strcmp(b, "1% low 20.0 ms"));
    low_text(b, sizeof b, -1);
    CHECK(!std::strcmp(b, "1% low -"));
    per_frame_line(b, sizeof b, 3000, 2);
    CHECK(!std::strcmp(b, "1500"));
    std::printf("fps levels: saved values, order, parts, graph scale and texts\n");
    return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    with tempfile.TemporaryDirectory(prefix="fps-levels-") as tmp:
        src = Path(tmp) / "t.cpp"
        src.write_text(C, encoding="utf-8")
        exe = Path(tmp) / ("t.exe" if sys.platform == "win32" else "t")
        subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Werror", "-I", str(ROOT / "gpu/vk"), "-o", str(exe), str(src)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        if r.returncode:
            raise SystemExit(r.stderr.strip())


if __name__ == "__main__":
    main()
