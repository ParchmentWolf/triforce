"""The VRAM mirrors' budget by the card (gpu/vk/mirror_budget.h, vk_memory.cpp mirror_budget; no game/GPU).

The rule is compiled from the header and run on made-up cards (MB in, MB out): discrete 6144 -> 1536, 5992 -> 1498, 4608 -> 576,
4096 -> 512, 8192 -> 2048, 16384 -> 3072, 24576 -> 3072; integrated 6144 -> 768, 6656 -> 832, 8192 -> 2048; video memory not known
-> 3072. The source: mirror_budget reads RX_VK_MIRROR_MB before the rule, asks the rule with the card's device type, and no longer
reads the quality preset's opts.mirror_mb; the docs row says the rule.

    python -I -B tests/test_mirror_budget.py [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

CASES = [  # (MB of video memory, discrete, MB of mirrors)
    (6144, True, 1536), (5992, True, 1498), (4608, True, 576), (4096, True, 512), (8192, True, 2048), (16384, True, 3072),
    (24576, True, 3072), (6144, False, 768), (6656, False, 832), (8192, False, 2048), (0, True, 3072), (0, False, 3072),
]

FIXTURE = r'''#include <cstdio>
#include <cstdlib>
#include "mirror_budget.h"
int main(int argc, char** argv) {
    for (int i = 1; i + 1 < argc; i += 2) {
        const unsigned long long vram = strtoull(argv[i], nullptr, 10) << 20;
        std::printf("%llu\n", (unsigned long long)(mkwvk::mirror_size::bytes(vram, atoi(argv[i + 1]) != 0) >> 20));
    }
    return 0;
}
'''


def fail(message):
    raise SystemExit("FAIL: " + message)


def check_source():
    mem = (ROOT / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")
    dev = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    body = mem[mem.index("uint64_t mirror_budget() {"):]
    body = body[:body.index("\n}\n")]
    env = body.index('getenv("RX_VK_MIRROR_MB")')
    rule = body.index("mirror_size::bytes(vram, discrete)")
    if env > rule:
        fail("mirror_budget asks the rule before RX_VK_MIRROR_MB")
    if "dev.props.deviceType == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU" not in body:
        fail("mirror_budget no longer tells the rule whether the card is discrete")
    if "opts.mirror_mb" in body:
        fail("mirror_budget reads the quality preset's opts.mirror_mb again")
    if "vram / 8" in body:
        fail("mirror_budget has a rule of its own besides mirror_budget.h")
    if "a quarter of the video memory on a discrete card over 4.5 GB" not in dev:
        fail("docs/development.md's RX_VK_MIRROR_MB row does not say the rule")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    try:
        check_source()
    except ValueError as e:
        fail("a text this test reads moved (%s)" % e)
    flags = subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="mirror-budget-") as tmp:
        cpp = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / ("fixture" + (".exe" if os.name == "nt" else ""))
        cpp.write_text(FIXTURE, encoding="utf-8")
        built = subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Werror", "-I" + str(ROOT / "gpu/vk"), str(cpp), "-o", str(exe)],
                               capture_output=True, text=True, creationflags=flags)
        if built.returncode:
            print(built.stdout + built.stderr)
            fail("the fixture did not build")
        args = [str(x) for vram, discrete, _ in CASES for x in (vram, int(discrete))]
        done = subprocess.run([str(exe)] + args, capture_output=True, text=True, timeout=60, creationflags=flags)
        got = done.stdout.split()
        if done.returncode or len(got) != len(CASES):
            fail("the fixture failed: " + (done.stdout + done.stderr).strip())
        wrong = ["%d MB %s: %s MB, wanted %d" % (v, "discrete" if d else "integrated", g, want)
                 for (v, d, want), g in zip(CASES, got) if int(g) != want]
        if wrong:
            fail("\n  ".join([""] + wrong))
    print("PASS: the mirrors' budget: a quarter on discrete cards over 4.5 GB (at most 3 GB), an eighth below and on integrated GPUs "
          "up to 6.5 GB, 3 GB unknown; RX_VK_MIRROR_MB first (%d cards)" % len(CASES))


if __name__ == "__main__":
    main()
