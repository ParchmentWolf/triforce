"""NVIDIA DLSS frame generation is given the camera's motion alone, not the upscaler chain's (gpu/vk/fg_motion.h,
vk_fsr3_inputs.cpp chain_motion; no game, no GPU).

(Triforce, 11-22, the owner's DLSS frame generation flicker.) With the chain's motion copied over FSR's inputs (FG-4) the
whole picture flickered again while the camera moved, with the clip-space fix of 11-20 in the build. The owner's runs:
RX_VK_FG_OWN_MOTION=0 (the camera's alone) had no flicker; the chain's motion with the upscaler audit's commits all set back
had it.

This compiles fg_motion.h alone and checks the rule: with DLSS frame generation the chain's motion is not given, unless
RX_VK_DLSSG_OWN_MOTION is set and not 0; without it (AMD's frame generation, FSR 3.1's interpolation) it is, as before;
RX_VK_FG_OWN_MOTION=0 keeps the camera's alone for every generator, over RX_VK_DLSSG_OWN_MOTION too; the switches read as
the renderer reads them (unset, empty, 0).

And reads the source: chain_motion asks the rule with dlssg::active() and both switches before it takes the lock or copies
anything, and returns false then; the old switch's line stays (tests/test_framegen_amd.py reads it); and the switch is in
the switches table.

    python -I -B tests/test_fg_motion.py [--cxx clang++]
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
#include <cstdio>
#include "fg_motion.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
using namespace fg_motion;
int main() {
    CHECK(!set_on(nullptr) && !set_on("") && !set_on("0") && set_on("1") && set_on("2"));
    CHECK(!camera_alone(nullptr) && !camera_alone("") && camera_alone("0") && !camera_alone("1"));
    // (DLSS frame generation: the camera's alone by default; the chain's with RX_VK_DLSSG_OWN_MOTION=1)
    CHECK(!chain(true, nullptr, nullptr));
    CHECK(!chain(true, nullptr, "0") && !chain(true, nullptr, ""));
    CHECK(chain(true, nullptr, "1"));
    // (AMD's frame generation, FSR 3.1's interpolation: the chain's, as before; the DLSS switch says nothing to them)
    CHECK(chain(false, nullptr, nullptr) && chain(false, nullptr, "0") && chain(false, nullptr, "1"));
    CHECK(chain(false, "1", nullptr));
    // (RX_VK_FG_OWN_MOTION=0: the camera's alone for every generator, over the DLSS switch too)
    CHECK(!chain(false, "0", nullptr) && !chain(true, "0", nullptr) && !chain(true, "0", "1") && !chain(false, "0", "1"));
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    src = (VK / "vk_fsr3_inputs.cpp").read_text(encoding="utf-8")

    check('#include "fg_motion.h"' in src, "vk_fsr3_inputs.cpp does not use the rule")
    motion = block(src, "bool chain_motion(VkCommandBuffer cmd, VkImage motion, uint32_t width, uint32_t height) {")
    ask = 'if (!fg_motion::chain(dlssg::active(), getenv("RX_VK_FG_OWN_MOTION"), getenv("RX_VK_DLSSG_OWN_MOTION"))) return false;'
    check(ask in motion, "chain_motion does not ask the rule with DLSS frame generation's state and both switches")
    check(motion.index(ask) < motion.index("std::lock_guard lk(s.mu);") < motion.index("vkCmdCopyImage(cmd, motion, VK_IMAGE_LAYOUT_GENERAL, s.motion.image"),
          "chain_motion copies or takes its lock before the rule says whether the chain's motion is given")
    check(motion.count("vkCmdCopyImage(") == 1 and "s.frame.chain_motion = true;" in motion,
          "chain_motion copies more than once, or no longer notes the chain's motion")
    check('env_switch("RX_VK_FG_OWN_MOTION") == 0' in motion, "the old switch's line is gone (tests/test_framegen_amd.py reads it)")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_DLSSG_OWN_MOTION=1`" in dev, "docs/development.md: RX_VK_DLSSG_OWN_MOTION=1 is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="fg-motion-") as tmp:
        c, exe = Path(tmp) / "motion.cpp", Path(tmp) / "motion.exe"
        c.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the rule as made:\n" + r.stdout)
    print("PASS: NVIDIA DLSS frame generation is given the camera's motion alone, the chain's only with RX_VK_DLSSG_OWN_MOTION=1")


if __name__ == "__main__":
    main()
