"""(Triforce, 11-23) The dynamic resolution's GPU time as the union of the recordings' intervals (gpu/vk/gpu_busy.h; no game, no GPU).

The clock summed each recording's interval; with AMD's early first timestamps a frame's intervals overlap and the sum
counted the overlaps again (14.9 ms against a 7.8 ms span on an RX 6700 XT), so Resolution Auto drew the 3D at its smallest
on a card half idle. Run here: intervals apart, overlapping, inside one another, touching, empty or backwards, read back out
of order; and a frame of overlapping recordings, whose sum is near twice its span and whose union is the span. The source
is read for the two places that collect the intervals, the clock that uses the union, and its switch.

    python -I -B tests/test_gpu_busy.py [--cxx g++]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''
#include <cstdio>
#include "gpu_busy.h"
using mkwvk::gpu_busy::Union;
static int fails;
#define CHECK(c, what) do { if (!(c)) { fails++; std::printf("FAIL line %d: %s\n", __LINE__, what); } } while (0)
int main() {
    { Union u; u.add(0, 10); u.add(20, 30); CHECK(u.ticks == 20 && u.end == 30, "apart: both counted"); }
    { Union u; u.add(0, 10); u.add(5, 15); CHECK(u.ticks == 15, "overlapping: the overlap once"); }
    { Union u; u.add(0, 10); u.add(2, 8); CHECK(u.ticks == 10 && u.end == 10, "inside: nothing more"); }
    { Union u; u.add(0, 10); u.add(10, 12); CHECK(u.ticks == 12, "touching: both"); }
    { Union u; u.add(5, 5); u.add(9, 3); CHECK(u.ticks == 0 && u.end == 0, "empty or backwards: nothing"); }
    { Union u; u.add(10, 20); u.add(0, 15); CHECK(u.ticks == 10, "out of order: only what lies past the end, never over"); }
    {   /* a frame: 24 recordings of 0.6 ms each, each begun 0.3 ms after the last (its first timestamp while the last still
           runs): their sum is twice the span, their union the span */
        Union u;
        unsigned long long sum = 0;
        for (int i = 0; i < 24; i++) {
            const unsigned long long a = 300ull * i, b = a + 600;
            u.add(a, b), sum += b - a;
        }
        CHECK(sum == 14400 && u.ticks == 7500, "a frame of overlapping recordings: the union is its span");
        /* the next frame after an idle gap counts on from there */
        u.add(20000, 21000);
        CHECK(u.ticks == 8500, "after a gap: the next frame's on top");
    }
    if (!fails) std::printf("all checks passed\n");
    return fails != 0;
}
'''


def check_source():
    rep = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    for needle, why in (
            ('#include "gpu_busy.h"', "the header is not included"),
            ("gpu_busy_add(t[0], t[1]);", "the uploads' intervals are not in the union"),
            ("gpu_busy_add(t[0], t[tn - 1]);", "the recordings' intervals are not in the union"),
            ('getenv("RX_VK_DYNRES_UNION")', "RX_VK_DYNRES_UNION is not read"),
            ("const int64_t g = ts_dyn_union() ? gpu_busy_ns() : st_gpu_ns + st_gpu_up_ns;",
             "the dynamic resolution's clock does not take the union"),
            ("const double dw = (double)(st_wait_ns - waited_last) + (double)host_waits.take(nullptr, nullptr);",
             "the clock does not count the host's other waits for the GPU"),
            ("const ::gpu_wait_kinds::Exclude compositor;", "the compositor's image counts as a wait for the GPU"),
            ("if (ts_ema_behind_ns >= 2e6) ts_gpu_limited = true;\n    else if (ts_ema_behind_ns < 1e6) ts_gpu_limited = false;",
             "the card is not called the limit at 2 ms of waits a frame, and let go of it under 1 ms"),
            ("const bool gpu_limit = !ts_dyn_union() || ts_gpu_limited;",
             "the clock does not tell a card that holds the replay back from one that does not"),
            ("ts_dyn_scale = std::clamp(ts_ema_gpu_ns / ts_ema_span_ns, 0.02, gpu_limit ? 8.0 : 1.0);",
             "the clock is not held to the span while the card is not the frame's limit")):
        if needle not in rep:
            raise SystemExit("gpu/vk/vk_replay.cpp: " + why)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="gpu-busy-") as d:
        tmp = Path(d)
        (tmp / "t.cpp").write_text(FIXTURE, encoding="utf-8")
        exe = tmp / ("t.exe" if sys.platform == "win32" else "t")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-O1", "-I", str(ROOT / "gpu/vk"),
                        str(tmp / "t.cpp"), "-o", str(exe)], check=True)
        run = subprocess.run([str(exe)], text=True, capture_output=True, timeout=60)
        sys.stdout.write(run.stdout)
        if run.returncode or "all checks passed" not in run.stdout:
            raise SystemExit("the union's checks failed" + run.stderr)


if __name__ == "__main__":
    main()
