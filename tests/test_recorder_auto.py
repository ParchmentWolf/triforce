"""The recorder thread's default by the GPU and the cores (gpu/vk/recorder_auto.h, vk_main.cpp pick_device; no game/GPU).

The rule is compiled from the header and run on made-up PCs: NVIDIA with 24 logical processors on and with 8 off (the rule since
11-16, unchanged); AMD with 6 physical cores (12 logical) on, 8 on, 4 cores and 8 logical (a Steam Deck) off, 5 off, the cores not
known off, AMD's older Windows driver (amd_older_compiler) off with 16 cores; Intel and an unknown vendor off with 32 cores. The
count: 4 of 8 two-thread cores in the affinity counts 4, one logical processor of a core counts the core, none counts 0. The
source: vk_main.cpp fills VendorFacts with the driver's properties, counts the process's physical cores and calls the rule before
create_device; RX_VK_RECORDER still decides over it (mode_from_env); the lab knob norec leaves the hold with no producer.

    python -I -B tests/test_recorder_auto.py [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''#include <cstdio>
#include "recorder_auto.h"
using namespace mkwvk::recorder_default;
static int bad = 0;
static void expect(bool got, bool want, const char* what) {
    if (got != want) { std::printf("FAIL %s: %d, wanted %d\n", what, (int)got, (int)want); bad++; }
}
int main() {
    expect(rule(0x10DE, 24, 12, false), true, "NVIDIA 24 logical");
    expect(rule(0x10DE, 12, 6, false), true, "NVIDIA 12 logical");
    expect(rule(0x10DE, 8, 8, false), false, "NVIDIA 8 logical");
    expect(rule(0x10DE, 11, 16, false), false, "NVIDIA 11 logical, 16 physical");
    expect(rule(0x10DE, 32, 0, false), true, "NVIDIA, physical unknown");
    expect(rule(0x1002, 12, 6, false), true, "AMD 6c/12t");
    expect(rule(0x1002, 16, 8, false), true, "AMD 8c/16t");
    expect(rule(0x1002, 6, 6, false), true, "AMD 6c/6t");
    expect(rule(0x1002, 8, 4, false), false, "AMD 4c/8t (Steam Deck)");
    expect(rule(0x1002, 10, 5, false), false, "AMD 5c/10t");
    expect(rule(0x1002, 24, 0, false), false, "AMD, physical unknown");
    expect(rule(0x1002, 32, 16, true), false, "AMD older Windows driver");
    expect(rule(0x8086, 32, 16, false), false, "Intel");
    expect(rule(0x13B5, 32, 16, false), false, "another vendor");
    expect(why(0x1002, 8, 4, false) == kAmdFew, true, "why: AMD few");
    expect(why(0x1002, 24, 0, false) == kAmdUnknown, true, "why: AMD unknown");
    expect(why(0x1002, 32, 16, true) == kAmdOlder, true, "why: AMD older");
    for (int w = kNvidia; w <= kOther; w++) expect(text((Why)w) && *text((Why)w), true, "a text for each why");
    const uint64_t smt[8] = {0x3, 0xC, 0x30, 0xC0, 0x300, 0xC00, 0x3000, 0xC000};
    expect(physical_cores(smt, 8, 0xFFFF) == 8, true, "8 of 8 cores");
    expect(physical_cores(smt, 8, 0x00FF) == 4, true, "4 of 8 cores in the affinity");
    expect(physical_cores(smt, 8, 0x5555) == 8, true, "one logical processor a core");
    expect(physical_cores(smt, 8, 0x30000) == 0, true, "none in the affinity");
    expect(physical_cores(smt, 0, ~0ull) == 0, true, "no cores read");
    if (bad) return 1;
    std::printf("OK\n");
    return 0;
}
'''


def fail(message):
    raise SystemExit("FAIL: " + message)


def check_source():
    main = (ROOT / "gpu/vk/vk_main.cpp").read_text(encoding="utf-8")
    rec = (ROOT / "gpu/vk/vk_recorder.h").read_text(encoding="utf-8")
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    dev = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    pick = main[main.index("bool pick_device() {"):main.index("bool create_device() {")]
    for needle in ("facts.driver_id = drv.driverID;", "facts.driver_info = drv.driverInfo;", "process_physical_cores()",
                   "recorder_default::why(facts.vendor_id, logical, physical, amd_older_compiler(facts))",
                   "recorder_auto(recorder_default::on(why));"):
        if needle not in pick:
            fail("pick_device no longer has: " + needle)
    if "recorder_auto(dev.props.vendorID == 0x10DE" in main:
        fail("vk_main.cpp still has the NVIDIA-only rule of its own")
    count = main[main.index("static unsigned process_physical_cores() {"):main.index("bool pick_device() {")]
    for needle in ("GetLogicalProcessorInformation(", "GetProcessAffinityMask(", "RelationProcessorCore",
                   "recorder_default::physical_cores("):
        if needle not in count:
            fail("process_physical_cores no longer has: " + needle)
    env = rec[rec.index("inline int mode_from_env() {"):rec.index("inline int mode_init() {")]
    if "if (!e) return g_auto_thread ? THREAD : OFF;" not in env:
        fail("mode_from_env no longer takes the default only with RX_VK_RECORDER unset")
    if "if (mode() == THREAD && !(g_direct_hook && g_direct_hook())) t_prod = &g_rec;" not in rec:
        fail("DrainingMutex::enter no longer leaves the producer out for the lab knob")
    if 'g_direct_hook = [] { return lab_ab::on("norec"); }' not in replay:
        fail("vk_replay.cpp no longer sets the norec hook")
    if "on an AMD GPU with 6 physical cores or more" not in dev:
        fail("docs/development.md's RX_VK_RECORDER row does not say the AMD default")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    try:
        check_source()
    except ValueError as e:
        fail("a text this test reads moved (%s)" % e)
    flags = subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="recorder-auto-") as tmp:
        cpp = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / ("fixture" + (".exe" if os.name == "nt" else ""))
        cpp.write_text(FIXTURE, encoding="utf-8")
        built = subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Werror", "-I" + str(ROOT / "gpu/vk"), str(cpp), "-o", str(exe)],
                               capture_output=True, text=True, creationflags=flags)
        if built.returncode:
            print(built.stdout + built.stderr)
            fail("the fixture did not build")
        done = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60, creationflags=flags)
        if done.returncode or done.stdout.strip() != "OK":
            fail((done.stdout + done.stderr).strip())
    print("PASS: the recorder's default: NVIDIA with 12 logical processors or more as before, AMD with 6 physical cores or more "
          "but its older Windows driver, nothing else; the count of cores in the affinity; vk_main.cpp calls the rule")


if __name__ == "__main__":
    main()
