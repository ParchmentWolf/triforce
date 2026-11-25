"""Threaded rendering (gpu/vk/threaded_rendering.h, vk_main.cpp threaded_choice; no game/GPU).

The rule is compiled from the header and run on made-up PCs: Off (the row's default, 0) and any value that is none of the row's are
off whatever the CPU; On is both threads whatever the CPU; Auto is both threads from 4 physical cores and off below, off where the
run is not safe, and with no buffer-pool mirrors the recorder thread alone from 6 cores, off below. RX_VK_THREADED's words. The
source: the row is on the Debug tab with Off first, async_on reads the render thread's half only with RX_VK_ASYNC unset, the
recorder's half goes through recorder_auto in pick_device, and the host asks HOS_OPT_RENDER_THREAD only with RX_VK_ASYNC unset.

    python -I -B tests/test_threaded_rendering.py [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''#include <cstdio>
#include <initializer_list>
#include "threaded_rendering.h"
using namespace mkwvk::threaded;
static int bad = 0;
static void expect(bool got, bool want, const char* what) {
    if (got != want) { std::printf("FAIL %s: %d, wanted %d\n", what, (int)got, (int)want); bad++; }
}
int main() {
    for (unsigned cores : {0u, 2u, 4u, 8u, 32u}) {
        expect(choose(OFF, cores, false).on(), false, "Off is off");
        expect(choose(7, cores, false).on(), false, "a value not the row's is off");
        expect(choose(ON, cores, true).render_thread && choose(ON, cores, true).recorder_thread, true, "On is both threads");
        expect(choose(AUTO, cores, true).on(), false, "Auto off where unsafe");
    }
    expect(choose(AUTO, 3, false).on(), false, "Auto, 3 cores: off");
    expect(choose(AUTO, 0, false).on(), false, "Auto, cores unknown: off");
    expect(auto_picked(choose(AUTO, 4, false)), true, "Auto, 4 cores: both threads");
    expect(without_mirrors(choose(AUTO, 4, false), 4).on(), false, "no mirrors, 4 cores: off");
    expect(without_mirrors(choose(AUTO, 5, false), 5).on(), false, "no mirrors, 5 cores: off");
    const Choice rec = without_mirrors(choose(AUTO, 6, false), 6);
    expect(rec.recorder_thread && !rec.render_thread, true, "no mirrors, 6 cores: the recorder thread alone");
    expect(without_mirrors(choose(ON, 2, false), 2).render_thread, true, "On is not changed by the mirrors' rule");
    expect(from_env(nullptr) == -1 && from_env("") == -1 && from_env("x") == -1, true, "unset or unknown: the row");
    expect(from_env("0") == OFF && from_env("off") == OFF, true, "0, off");
    expect(from_env("1") == ON && from_env("on") == ON, true, "1, on");
    expect(from_env("2") == AUTO && from_env("auto") == AUTO, true, "2, auto");
    char line[256];
    for (int w = (int)Why::On; w <= (int)Why::AutoBothThreads; w++) {
        describe(line, sizeof line, {false, false, (Why)w}, 4, "x", w & 1);
        expect(line[0] && line[0] != '?', true, "a line for each why");
    }
    if (bad) return 1;
    std::printf("OK\n");
    return 0;
}
'''


def fail(message):
    raise SystemExit("FAIL: " + message)


def check_source():
    main = (ROOT / "gpu/vk/vk_main.cpp").read_text(encoding="utf-8")
    menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
    menu_h = (ROOT / "gpu/vk/vk_menu.h").read_text(encoding="utf-8")
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    backend = (ROOT / "host/rx_backend.c").read_text(encoding="utf-8")
    if "int threaded_rendering = 0;" not in menu_h:
        fail("the row's default is no longer Off (0)")
    if '{TAB_DEBUG, "Threaded rendering", &opts.threaded_rendering, 0, 2, 1, tx_threaded,' not in menu:
        fail("the Threaded rendering row moved or changed")
    pick = main[main.index("bool pick_device() {"):main.index("bool create_device() {")]
    if "if (threaded_choice().recorder_thread && !recorder_default::on(why)) {" not in pick:
        fail("pick_device no longer turns the recorder on for Threaded rendering")
    choice = main[main.index("const threaded::Choice& threaded_choice() {"):main.index("bool pick_device() {")]
    for needle in ('threaded::from_env(getenv("RX_VK_THREADED"))', "opts.threaded_rendering", "!pools_mirrored()",
                   "if (!dev.physical) {"):
        if needle not in choice:
            fail("threaded_choice no longer has: " + needle)
    if 'getenv("RX_VK_ASYNC") ? atoi(getenv("RX_VK_ASYNC")) != 0 : threaded_render_thread();' not in replay:
        fail("async_on no longer reads the row only with RX_VK_ASYNC unset")
    rec = (ROOT / "gpu/vk/vk_recorder.h").read_text(encoding="utf-8")
    internal = (ROOT / "gpu/vk/vk_internal.h").read_text(encoding="utf-8")
    # the design's other pieces: each off unless Threaded rendering (or its own switch) turns it on
    for needle, where in (
            ('g_parts.store(pe && *pe ? atoi(pe) != 0 : g_parts_default && g_parts_default(), std::memory_order_relaxed);', rec),
            ("if (!g_parts.load(std::memory_order_relaxed)) return;", rec),   # (queue_lock_event: nothing without the hand-off)
            ("::mkwvk::rec::g_parts_default = [] { return threaded_on(); }", replay),
            ("const bool post = rec::parts_wanted() && r.pieces.empty() && !memory_lazy_running();", replay),
            ('v.on = e && *e ? atoi(e) != 0 : threaded_on() && !getenv("RX_VK_CHUNK");', replay),
            ("const bool v = e && *e ? atoi(e) == 1 : threaded_on();", replay),
            ("static const bool v = threaded_on();", replay),
            ("QueueMutex present_mu;", internal)):
        if needle not in where:
            fail("a piece of the design moved or changed: " + needle)
    fn = backend[backend.index("int rx_async_replay(void) {"):backend.index("void rx_nvn_submit_waits(")]
    if fn.index('getenv("RX_VK_ASYNC")') > fn.index("HOS_OPT_RENDER_THREAD"):
        fail("rx_async_replay asks the renderer before RX_VK_ASYNC")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    try:
        check_source()
    except ValueError as e:
        fail("a text this test reads moved (%s)" % e)
    flags = subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="threaded-") as tmp:
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
    print("PASS: Threaded rendering: Off by default and as before, On both threads, Auto by physical cores (the recorder alone "
          "without mirrors from 6); the row, the readers and the host's question in place")


if __name__ == "__main__":
    main()
