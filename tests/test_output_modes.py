"""The Output resolution row's display modes and common sizes (gpu/vk/output_modes.h): a screen's modes worth a place first,
then the common sizes no larger than the screen, each once; every common one when the screen is not known. Compiled and run.

python -I -B tests/test_output_modes.py [--cxx g++]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "g++"]
ROOT = Path(__file__).resolve().parents[1]

C = r'''
#include "output_modes.h"
#include <cstdio>
#include <cstdlib>
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
using namespace mkwvk::output_modes;
static bool in(const std::vector<Size>& v, unsigned w, unsigned h) {
    for (const Size& s : v)
        if (s.w == w && s.h == h) return true;
    return false;
}
int main() {
    const std::vector<Size> modes = {{800, 600}, {1920, 1080}, {2560, 1080}, {1920, 1080}, {3440, 1440}};
    const std::vector<Size> o = offered(3440, 1440, modes);
    CHECK(o.size() > 3 && o[0].w == 1920 && o[1].w == 2560 && o[2].w == 3440);   // (the modes first, each once)
    CHECK(!in(o, 800, 600));                                                     // (too small for the row)
    CHECK(in(o, 2560, 1440) && in(o, 1680, 1050) && in(o, 1440, 1080));          // (common ones up to the screen)
    CHECK(!in(o, 3840, 2160) && !in(o, 3840, 1600) && !in(o, 5120, 1440));       // (none larger either way)
    int n = 0;
    for (const Size& s : o) n += s.w == 1920 && s.h == 1080;
    CHECK(n == 1);
    const std::vector<Size> all = offered(0, 0, {});
    CHECK(all.size() == sizeof kCommon / sizeof kCommon[0] && in(all, 7680, 1440));
    std::printf("output modes: the screen's modes, then the common sizes up to it, each once\n");
    return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    with tempfile.TemporaryDirectory(prefix="output-modes-") as tmp:
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
