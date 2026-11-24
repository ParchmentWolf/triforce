"""(Triforce, 11-23) One L3 for the game's main thread, its presenting thread and the replay's core (host/hos_l3_home.h,
host/hos_thread.c; no game, no CPU of the kind).

On a processor with two or more L3 caches of the same size (AMD's two-die Ryzen 9 parts), the die of the lowest
logical processor the process may use is the home: the core kept for the replay is its last core, and the main and
presenting threads are kept on its other cores, so that what the main thread writes is in the L3 the replay reads it
from. Run here on authored topologies:

- a 5900X (2 dies of 6 cores, SMT on and off), a 5950X (2 of 8), a 7950X: the first die; the kept core its last; the two
  threads on its other cores, the other threads as before;
- a 5600X, a 7800X3D, an Intel processor of two kinds (one L3): nothing;
- a 7950X3D (L3 caches of different sizes): nothing here (host/hos_x3d.h has it);
- a 3900X (four 3-core CCXs), a 3700X (two 4-core CCXs): nothing, too few cores;
- a process held to one die, or without logical processor 0: the die of its lowest processor, or nothing;
- more than one processor group, a list that puts a processor under two L3 caches: nothing.

The source is read for what cannot run here: HOS_L3_HOME=0 turns it off, the cache die goes first, the log says what was
found, the kept core is chosen among the home's cores, and hos_thread_pin keeps the two threads there.

    python -I -B tests/test_l3_home.py [--cc gcc]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


FIXTURE = r'''
#include <stdint.h>
#include <stdio.h>
#include "hos_l3_home.h"

static int fails;
#define CHECK(cond, what) do { if (!(cond)) { fails++; printf("FAIL line %d: %s\n", __LINE__, what); } } while (0)

@PICK_RESERVED@

#define MB(n) ((uint64_t)(n) << 20)
#define KB(n) ((uint64_t)(n) << 10)
static HosCache caches[512];
static uint64_t cores[256];
static unsigned char classes[256];
static int ncaches, ncores;
static void fresh(void) { ncaches = ncores = 0; }
static void add_cores(int n, int per, int first, uint64_t l2, unsigned char cls) {
    for (int i = 0; i < n; i++) {
        const uint64_t m = ((1ull << per) - 1) << (first + i * per);
        cores[ncores] = m, classes[ncores++] = cls;
        caches[ncaches++] = (HosCache){1, m, KB(32)};
        caches[ncaches++] = (HosCache){2, m, l2};
    }
}
static void add_l3(uint64_t mask, uint64_t bytes) { caches[ncaches++] = (HosCache){3, mask, bytes}; }
static HosL3Home h;
static uint64_t pick(uint64_t allowed, int groups) { return hos_l3_home_pick(caches, ncaches, cores, ncores, allowed, groups, &h); }
/* the replay's core as hos_thread.c picks it: among the home's cores when there is one */
static uint64_t reserved(uint64_t home) {
    uint64_t m[256];
    unsigned char c[256];
    int n = 0;
    for (int i = 0; i < ncores; i++)
        if (!home || (cores[i] & home)) m[n] = cores[i], c[n++] = classes[i];
    return pick_reserved_core(m, c, n);
}

int main(void) {
    /* Ryzen 9 5900X: 12 cores with SMT, two dies of 6, an L3 of 32 MB each */
    fresh();
    add_cores(12, 2, 0, KB(512), 0);
    add_l3(0xFFF, MB(32)), add_l3(0xFFF000, MB(32));
    CHECK(pick(0xFFFFFF, 1) == 0xFFF && h.why == HOS_L3_HOME_USED && h.cores == 6 && h.domains == 2, "5900X: the first die");
    CHECK(reserved(0xFFF) == 0xC00, "5900X: the kept core is the first die's last (it was the processor's last, 0xC00000)");
    CHECK(reserved(0) == 0xC00000, "5900X: without a home, the processor's last core, as before");
    CHECK(hos_l3_home_thread_mask(0xFFFFFF, 0xFFF, 0xC00) == 0x3FF, "5900X: the two threads on the first die's other five cores");
    CHECK(hos_l3_home_thread_mask(0xFFFFFF, 0, 0xC00000) == 0, "no home: the two threads get nothing of their own");
    /* (the same, the process without logical processor 0: the die of its lowest) */
    CHECK(pick(0xFFFFFE, 1) == 0xFFE && h.cores == 6, "5900X without LP 0: the first die, what is left of it");
    CHECK(pick(0xFFFFFC, 1) == 0 && h.home == 0xFFC && h.why == HOS_L3_HOME_FEW && h.cores == 5, "5900X without core 0: five cores, too few");
    CHECK(pick(0xFFF000, 1) == 0 && h.why == HOS_L3_HOME_ONE, "5900X held to the second die: one L3, nothing");
    CHECK(pick(0xFFFFFF, 2) == 0 && h.why == HOS_L3_HOME_GROUPS, "more than one processor group: nothing");

    /* Ryzen 9 5900X with SMT off: 12 logical processors */
    fresh();
    add_cores(12, 1, 0, KB(512), 0);
    add_l3(0x3F, MB(32)), add_l3(0xFC0, MB(32));
    CHECK(pick(0xFFF, 1) == 0x3F && h.cores == 6, "5900X, SMT off: the first die");
    /* (6 logical processors on the die: pick_reserved_core keeps none under 8, so the two threads have all six) */
    CHECK(reserved(0x3F) == 0, "5900X, SMT off: no core kept on the die");
    CHECK(hos_l3_home_thread_mask(0xFFF, 0x3F, 0) == 0x3F, "5900X, SMT off: the two threads on the whole first die");

    /* Ryzen 9 5950X / 7950X: 16 cores with SMT, two dies of 8 */
    fresh();
    add_cores(16, 2, 0, MB(1), 0);
    add_l3(0xFFFF, MB(32)), add_l3(0xFFFF0000, MB(32));
    CHECK(pick(0xFFFFFFFF, 1) == 0xFFFF && h.cores == 8, "5950X: the first die");
    CHECK(reserved(0xFFFF) == 0xC000, "5950X: the first die's last core");

    /* Ryzen 5 5600X: 6 cores, one L3 */
    fresh();
    add_cores(6, 2, 0, KB(512), 0);
    add_l3(0xFFF, MB(32));
    CHECK(pick(0xFFF, 1) == 0 && h.why == HOS_L3_HOME_ONE, "5600X: one L3, nothing");

    /* Ryzen 7 7800X3D: one L3 of 96 MB */
    fresh();
    add_cores(8, 2, 0, MB(1), 0);
    add_l3(0xFFFF, MB(96));
    CHECK(pick(0xFFFF, 1) == 0 && h.why == HOS_L3_HOME_ONE, "7800X3D: nothing");

    /* Ryzen 9 7950X3D: L3 caches of 96 and 32 MB: hos_x3d.h's */
    fresh();
    add_cores(16, 2, 0, MB(1), 0);
    add_l3(0xFFFF, MB(96)), add_l3(0xFFFF0000, MB(32));
    CHECK(pick(0xFFFFFFFF, 1) == 0 && h.why == HOS_L3_HOME_MIXED, "7950X3D: nothing here");

    /* Ryzen 9 3900X: four CCXs of 3 cores, 16 MB each; Ryzen 7 3700X: two of 4 */
    fresh();
    add_cores(12, 2, 0, KB(512), 0);
    add_l3(0x3F, MB(16)), add_l3(0xFC0, MB(16)), add_l3(0x3F000, MB(16)), add_l3(0xFC0000, MB(16));
    CHECK(pick(0xFFFFFF, 1) == 0 && h.why == HOS_L3_HOME_FEW && h.cores == 3 && h.domains == 4, "3900X: too few cores");
    fresh();
    add_cores(8, 2, 0, KB(512), 0);
    add_l3(0xFF, MB(16)), add_l3(0xFF00, MB(16));
    CHECK(pick(0xFFFF, 1) == 0 && h.why == HOS_L3_HOME_FEW, "3700X: too few cores");

    /* Intel Core i7-13700K: 8 performance cores with SMT, 8 efficiency cores, one L3 */
    fresh();
    add_cores(8, 2, 0, MB(2), 1);
    add_cores(8, 1, 16, MB(4), 0);
    add_l3(0xFFFFFF, MB(30));
    CHECK(pick(0xFFFFFF, 1) == 0 && h.why == HOS_L3_HOME_ONE, "13700K: one L3, nothing");

    /* a list that puts a processor under two L3 caches */
    fresh();
    add_cores(12, 2, 0, KB(512), 0);
    add_l3(0xFFF, MB(32)), add_l3(0xFF0FF0, MB(32));
    CHECK(pick(0xFFFFFF, 1) == 0 && h.why == HOS_L3_HOME_NONE, "overlapping L3 caches: nothing");
    fresh();
    add_cores(4, 2, 0, KB(512), 0);
    CHECK(pick(0xFF, 1) == 0 && h.why == HOS_L3_HOME_NONE, "no L3 listed: nothing");

    /* the two threads, by name */
    CHECK(hos_l3_home_thread("sead::MainThread") && hos_l3_home_thread("MainThread") && hos_l3_home_thread("Presentation Thread"),
          "the main and presenting threads");
    CHECK(!hos_l3_home_thread("OptimizeChangeBank") && !hos_l3_home_thread("AudioThread") && !hos_l3_home_thread("") &&
          !hos_l3_home_thread(0), "no other thread");

    if (!fails) printf("all checks passed\n");
    return fails != 0;
}
'''


def check_source(thread):
    detect = block(thread, "static uint64_t x3d_detect(")
    cpus = block(thread, "static uint64_t hos_x3d_cpus(")
    last = block(thread, "static uint64_t last_fastest_core(")
    pin = block(thread, "void hos_thread_pin(")
    for text, needle, why in (
            (thread, '#include "hos_l3_home.h"', "the header is not included"),
            (detect, "hos_l3_home_pick(caches, ncaches, cores, ncores, (uint64_t)proc, (int)GetActiveProcessorGroupCount(), home);",
             "the home is not picked from the caches the cache die's rule reads"),
            (cpus, 'getenv("HOS_L3_HOME")', "HOS_L3_HOME is not read"),
            (cpus, "if (!mask && h.why == HOS_L3_HOME_USED && !home_off) l3_home_mask = h.home;",
             "the home is used with a cache die, with HOS_L3_HOME=0, or when the rule did not fire"),
            (cpus, 'hos_log("cpu: logical processors %#llx share one of %d L3 caches', "what was found is not logged"),
            (last, "const uint64_t home = die ? 0 : l3_home_mask;", "the kept core is not chosen with the home"),
            (last, "(!home || ((uint64_t)e->Processor.GroupMask[0].Mask & home))", "the kept core is not among the home's cores"),
            (pin, "if (l3_home_mask && hos_l3_home_thread(name)) {", "the two threads are not kept on the home"),
            (pin, "hos_l3_home_thread_mask((uint64_t)proc, l3_home_mask, reserved)", "the two threads' affinity is not the header's")):
        if needle not in text:
            raise SystemExit("host/hos_thread.c: " + why)
    # (the reserved core first: hos_reserved_cpus reads the caches before the home is looked at)
    if pin.index("hos_reserved_cpus()") > pin.index("if (l3_home_mask && hos_l3_home_thread(name)) {"):
        raise SystemExit("host/hos_thread.c: hos_thread_pin reads the home before the caches are read")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    thread = (ROOT / "host/hos_thread.c").read_text(encoding="utf-8")
    check_source(thread)
    fixture = FIXTURE.replace("@PICK_RESERVED@", block(thread, "static uint64_t pick_reserved_core("))
    with tempfile.TemporaryDirectory(prefix="l3home-") as d:
        tmp = Path(d)
        (tmp / "t.c").write_text(fixture, encoding="utf-8")
        exe = tmp / ("t.exe" if sys.platform == "win32" else "t")
        subprocess.run([args.cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-O1", "-I", str(ROOT / "host"),
                        str(tmp / "t.c"), "-o", str(exe)], check=True)
        run = subprocess.run([str(exe)], text=True, capture_output=True, timeout=60)
        sys.stdout.write(run.stdout)
        if run.returncode or "all checks passed" not in run.stdout:
            raise SystemExit("the home's checks failed" + run.stderr)


if __name__ == "__main__":
    main()
