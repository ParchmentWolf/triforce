"""The lab's in-run A/B with a wait at every draw or dispatch (gpu/vk/lab_ab.h e_draw, e_dispatch, d_present_after; the
performance audit's REPLAY-51, after Source B's; no game, no GPU).

lab_ab.h compiled and run: RX_VK_LAB_AB=e_draw:200,e_dispatch:2000,d_present_after:1000 is read as three knobs; in the none
phases and the other knobs' phases each() returns at once and counts nothing; in its own phase it waits at least the knob's
nanoseconds at every call, on any thread, and counts each wait; at the phase's end one line gives its waits and ms a second,
and the counts start again; d_present_after waits once a frame in its phase as the d_ knobs do. Then the sources: draw() and
dispatch() wait before their profile clocks; the present's after-wait follows drain(0); the replay logs a phase's line and
warns once when RX_VK_PARALLEL is not pinned.

    python -I -B tests/test_lab_ab_each.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def in_order(text, parts, where):
    at = 0
    for part in parts:
        found = text.find(part, at)
        if found < 0:
            raise SystemExit("%s: %r is missing, or not after the part before it (update the test with the code)" % (where, part))
        at = found + len(part)


TEST = r'''
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>
#include "lab_ab.h"
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
using namespace mkwvk;
static int64_t timed(int event, int n) {
    const auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < n; i++) lab_ab::each(event);
    return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - t0).count();
}
static void to_phase(int want) {   // (presents until the phase's knob is `want`)
    for (int i = 0; i < 100000; i++) {
        const int c = lab_ab::phase_tick();
        if ((c < 0 ? -c - 1 : c) == want) return;
    }
    CHECK(false);
}
int main() {
    lab_ab::init();
    CHECK(lab_ab::n_knobs == 3 && !std::strcmp(lab_ab::knobs[0].name, "e_draw") && lab_ab::knobs[0].value == 200);
    CHECK(!std::strcmp(lab_ab::knobs[1].name, "e_dispatch") && lab_ab::knobs[1].value == 2000);
    CHECK(!std::strcmp(lab_ab::knobs[2].name, "d_present_after") && lab_ab::knobs[2].value == 1000 && lab_ab::any_each());
    // (no phase yet: no wait, nothing counted)
    CHECK(timed(lab_ab::E_DRAW, 1000) < 5000000 && lab_ab::each_spins[lab_ab::E_DRAW].load() == 0);
    to_phase(0);
    CHECK(lab_ab::each_ns[lab_ab::E_DRAW].load() == 0 && lab_ab::each_ns[lab_ab::E_DISPATCH].load() == 0);
    timed(lab_ab::E_DRAW, 1000);
    CHECK(lab_ab::each_spins[lab_ab::E_DRAW].load() == 0);
    // (e_draw's phase: at least 200 ns a draw, each counted, on two threads; dispatches untouched)
    to_phase(1);
    CHECK(lab_ab::each_ns[lab_ab::E_DRAW].load() == 200 && lab_ab::each_ns[lab_ab::E_DISPATCH].load() == 0);
    const int64_t spent = timed(lab_ab::E_DRAW, 2000);
    std::thread other([] { for (int i = 0; i < 500; i++) lab_ab::each(lab_ab::E_DRAW); });
    other.join();
    CHECK(spent >= 2000 * 200);
    CHECK(lab_ab::each_spins[lab_ab::E_DRAW].load() == 2500 && lab_ab::each_spun_ns[lab_ab::E_DRAW].load() >= 2500ull * 200);
    timed(lab_ab::E_DISPATCH, 100);
    CHECK(lab_ab::each_spins[lab_ab::E_DISPATCH].load() == 0);
    // (its end: the line, and the counts start again)
    to_phase(0);
    CHECK(std::strstr(lab_ab::each_line, "phase e_draw:200 over") && std::strstr(lab_ab::each_line, "(2500 waits in"));
    CHECK(lab_ab::each_spins[lab_ab::E_DRAW].load() == 0 && lab_ab::each_ns[lab_ab::E_DRAW].load() == 0);
    // (e_dispatch's phase: 2000 ns a dispatch)
    to_phase(2);
    CHECK(lab_ab::each_ns[lab_ab::E_DISPATCH].load() == 2000 && lab_ab::each_ns[lab_ab::E_DRAW].load() == 0);
    CHECK(timed(lab_ab::E_DISPATCH, 300) >= 300 * 2000 && lab_ab::each_spins[lab_ab::E_DISPATCH].load() == 300);
    to_phase(0);
    CHECK(std::strstr(lab_ab::each_line, "phase e_dispatch:2000 over") && std::strstr(lab_ab::each_line, "(300 waits in"));
    // (d_present_after's phase: no event waits, and no line at its end; its delay once a frame, at least 1 ms)
    to_phase(3);
    CHECK(lab_ab::each_line[0] == 0);
    CHECK(lab_ab::each_ns[lab_ab::E_DISPATCH].load() == 0 && lab_ab::each_ns[lab_ab::E_DRAW].load() == 0);
    auto t0 = std::chrono::steady_clock::now();
    lab_ab::delay("present_after");
    const int64_t first = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - t0).count();
    t0 = std::chrono::steady_clock::now();
    lab_ab::delay("present_after");
    const int64_t second = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - t0).count();
    CHECK(first >= 1000 && second < 500);
    lab_ab::delay("present");   // (d_present is another knob: nothing here)
    std::puts("PASS lab_ab.h: e_draw, e_dispatch and d_present_after read; waits only in their phases, at least their time, "
              "counted on any thread; the phase's line; d_present_after once a frame");
    return 0;
}
'''

MUTATIONS = [
    ("no wait without its knob", "    if (!ns) return;\n    const auto t0", "    const auto t0"),
    ("each wait counted", "    each_spins[event].fetch_add(1, std::memory_order_relaxed);\n", ""),
    ("the waits set by the phase", "    each_tick(k);   //", "    (void)0;   //"),
    ("only the phase's own event", "k > 0 && !strcmp(knobs[k - 1].name, each_names[e])", "k > 0"),
    ("the counts start again", "const uint64_t spins = each_spins[e].exchange(0, std::memory_order_relaxed);",
     "const uint64_t spins = each_spins[e].load(std::memory_order_relaxed);"),
]


def check_source(draw, replay, dev):
    d = block(draw, "void draw(VkCommandBuffer cmd, NvnState& s, const DrawArgs& d) {")
    in_order(d, ["Pass& ps = pass();", "lab_ab::each(lab_ab::E_DRAW);", "PROF_HOT(PROF_DRAW);"], "vk_draw.cpp draw(): the wait before the profile")
    disp = block(draw, "void dispatch(VkCommandBuffer cmd, NvnState& s, uint32_t x, uint32_t y, uint32_t z, uint64_t indirect) {")
    if not disp.split("\n", 2)[1].strip().startswith("lab_ab::each(lab_ab::E_DISPATCH);"):
        raise SystemExit("vk_draw.cpp dispatch(): the lab's wait is not its first statement")
    in_order(disp, ["lab_ab::each(lab_ab::E_DISPATCH);", "PROF(PROF_DISPATCH);", "DispatchClock dclock;"], "vk_draw.cpp dispatch()")
    pres = block(replay, "void present(const nvn_tex* t, const int crop[4]) {")
    in_order(pres, ['lab_ab::delay("present");', "drain(0);", 'lab_ab::delay("present_after");', "do_present(t, crop);"],
             "vk_replay.cpp present(): d_present before the drain, d_present_after just after it")
    tick = block(replay, "void status_tick() {")
    in_order(tick, ["const int lab_col = lab_ab::phase_tick();", 'if (lab_ab::each_line[0]) logf("%s", lab_ab::each_line)',
                    'if (lab_ab::any_each() && !getenv("RX_VK_PARALLEL"))'], "vk_replay.cpp status_tick: the phase's line and the warning")
    if "e_draw" not in dev or "d_present_after" not in dev:
        raise SystemExit("docs/development.md: the e_ knobs and d_present_after are not in RX_VK_LAB_AB's row")


def build(cxx, d, name, include):
    cpp, exe = d / (name + ".cpp"), d / (name + ".exe")
    cpp.write_text(TEST, encoding="utf-8")
    r = subprocess.run([cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-pthread", "-I" + str(include),
                        str(cpp), "-o", str(exe)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return (exe, "") if r.returncode == 0 else (None, r.stdout)


def run(exe):
    env = dict(os.environ, RX_VK_LAB_AB="e_draw:200,e_dispatch:2000,d_present_after:1000", RX_VK_LAB_AB_FRAMES="10",
               RX_VK_LAB_AB_SKIP="0")
    return subprocess.run([str(exe)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120, env=env)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cxx", default=os.environ.get("CXX", "g++"))
    a = ap.parse_args()
    check_source((VK / "vk_draw.cpp").read_text(encoding="utf-8"), (VK / "vk_replay.cpp").read_text(encoding="utf-8"),
                 (ROOT / "docs" / "development.md").read_text(encoding="utf-8"))
    print("PASS sources: draw() and dispatch() wait before their clocks, d_present_after after drain(0), the phase's line and "
          "the warning, the row")
    header = (VK / "lab_ab.h").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="lab-ab-each-") as tmp:
        d = Path(tmp)
        exe, out = build(a.cxx, d, "each", VK)
        if not exe:
            raise SystemExit("the build failed:\n" + out)
        r = run(exe)
        if r.returncode:
            raise SystemExit("the test failed:\n" + r.stdout)
        print(r.stdout.strip())
        for i, (what, old, new) in enumerate(MUTATIONS):
            if header.count(old) != 1:
                raise SystemExit("mutation %r: its text is not once in lab_ab.h (update the test with the header)" % what)
            inc = d / ("mutant%d" % i)
            inc.mkdir()
            (inc / "lab_ab.h").write_text(header.replace(old, new), encoding="utf-8")
            exe, out = build(a.cxx, d, "mutant%d" % i, inc)
            if exe and run(exe).returncode == 0:
                raise SystemExit("mutation %r: the test still passed without it" % what)
        print("PASS mutations: %d rules of the e_ knobs, each taken out, fail the test" % len(MUTATIONS))


if __name__ == "__main__":
    main()
