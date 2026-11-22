"""The game's threads on the die with the largest L3 cache (host/hos_x3d.h, host/hos_thread.c; no game, no CPU of the kind).

On AMD's two-die X3D processors one die of eight cores has the 3D V-Cache and the other has not. hos_x3d_pick finds that
die from the caches and cores the system lists, and nothing on any other processor. Run here on authored topologies:

- a 7800X3D (one die, one L3): nothing; a 7950X (two dies alike): nothing; both dies with the cache: nothing;
- a 7950X3D or 9950X3D, the large cache on either die, with and without SMT: the die's processors;
- a 7900X3D (six cores under the large cache) and a mobile part with four large cores: nothing, too few cores;
- an Intel processor of two kinds of core (different L2 caches, one L3): nothing;
- more than one processor group (over 64 logical processors): nothing;
- a process held to the die already, or to under 8 of its cores: nothing;
- a list with no L3, or one that puts a processor under two L3 caches: nothing.

And what follows from the die: the affinity a game thread gets (hos_x3d_thread_mask: on the die, off the replay's core;
with no die exactly what it was before), and the replay's core, which pick_reserved_core (cut out of hos_thread.c) takes
from the die's cores: the die's last core, not the processor's.

(Triforce, 11-22, the performance audit's THREAD-49, after Source A's.) Whether a core of the die is kept for the replay
(hos_x3d_keep_replay_core, hos_x3d_reserved): with SMT off none is, so the game has all 8 of the die's cores; with SMT
on one is, as before; HOS_RESERVE_CORE=1 and a replay on a thread of its own keep one, =0 keeps none. Run from the
caches to the game threads' affinity on the made-up processors above and on this PC's kind (8 cores, 16 logical
processors, one L3), where nothing may change.

The source is read for what cannot run here: HOS_X3D=0 turns it off, the log says what was found, the reader passes the
process's affinity and the group count, the reserved core is chosen among the die's cores, and hos_reserved_cpus asks
the rule with the switch's value and whether the replay has its own thread.

    python -I -B tests/test_x3d_placement.py [--cc gcc]
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
#include "hos_x3d.h"

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
/* n cores of `per` logical processors each from logical processor `first`, each with its own L1 and L2 of l2 bytes */
static void add_cores(int n, int per, int first, uint64_t l2, unsigned char cls) {
    for (int i = 0; i < n; i++) {
        const uint64_t m = ((1ull << per) - 1) << (first + i * per);
        cores[ncores] = m, classes[ncores++] = cls;
        caches[ncaches++] = (HosCache){1, m, KB(32)};
        caches[ncaches++] = (HosCache){1, m, KB(48)};
        caches[ncaches++] = (HosCache){2, m, l2};
    }
}
static void add_l3(uint64_t mask, uint64_t bytes) { caches[ncaches++] = (HosCache){3, mask, bytes}; }
static HosX3d x;
static uint64_t pick(uint64_t allowed, int groups) { return hos_x3d_pick(caches, ncaches, cores, ncores, allowed, groups, &x); }
/* the replay's core as hos_thread.c picks it: among the die's cores when there is a die */
static uint64_t reserved(uint64_t die) {
    uint64_t m[256];
    unsigned char c[256];
    int n = 0;
    for (int i = 0; i < ncores; i++)
        if (!die || (cores[i] & die)) m[n] = cores[i], c[n++] = classes[i];
    return pick_reserved_core(m, c, n);
}
/* ((Triforce, THREAD-49) the core hos_reserved_cpus keeps, from the caches on: the die, its last core, the rule. asked:
   HOS_RESERVE_CORE, -1 not set; own: the replay on a thread of its own) */
static uint64_t kept_die;
static uint64_t kept(uint64_t allowed, int asked, int own) {
    int n = 0;
    kept_die = pick(allowed, 1);
    for (int i = 0; i < ncores; i++)
        if (!kept_die || (cores[i] & kept_die)) n++;
    return hos_x3d_reserved(reserved(kept_die), kept_die, n, asked, own);
}
/* (and the affinity a game thread then gets) */
static uint64_t game(uint64_t allowed, int asked, int own) {
    const uint64_t r = kept(allowed, asked, own);
    return hos_x3d_thread_mask(allowed, kept_die, r);
}

int main(void) {
    /* Ryzen 7 7800X3D: 8 cores with SMT, one L3 of 96 MB */
    fresh();
    add_cores(8, 2, 0, MB(1), 0);
    add_l3(0xFFFF, MB(96));
    CHECK(pick(0xFFFF, 1) == 0 && x.why == HOS_X3D_SAME, "a single-die X3D: nothing");
    CHECK(reserved(0) == 0xC000, "its replay core: the last, as before");

    /* Ryzen 9 7950X: two dies of 8 cores, 32 MB each */
    fresh();
    add_cores(16, 2, 0, MB(1), 0);
    add_l3(0xFFFF, MB(32)), add_l3(0xFFFF0000ull, MB(32));
    CHECK(pick(0xFFFFFFFFull, 1) == 0 && x.why == HOS_X3D_SAME, "two dies alike: nothing");
    CHECK(reserved(0) == 0xC0000000ull, "its replay core: the processor's last, as before");

    /* Ryzen 9 7950X3D: the first die's L3 is 96 MB, the second's 32 MB */
    fresh();
    add_cores(16, 2, 0, MB(1), 0);
    add_l3(0xFFFF, MB(96)), add_l3(0xFFFF0000ull, MB(32));
    CHECK(pick(0xFFFFFFFFull, 1) == 0xFFFF && x.why == HOS_X3D_USED, "a two-die X3D: the die with the large cache");
    CHECK(x.cores == 8 && x.big == MB(96) && x.small == MB(32) && x.die == 0xFFFF, "what was found, for the log");
    CHECK(reserved(0xFFFF) == 0xC000, "the replay's core is the die's last one");
    CHECK(reserved(0) == 0xC0000000ull, "(without the die it would be on the other one)");
    CHECK(hos_x3d_thread_mask(0xFFFFFFFFull, 0xFFFF, 0xC000) == 0x3FFF, "a game thread: on the die, off the replay's core");
    CHECK(hos_x3d_thread_mask(0xFFFFFFFFull, 0xFFFF, 0) == 0xFFFF, "with no core reserved: the die");

    /* the large cache on the second die, and listed second */
    fresh();
    add_cores(16, 2, 0, MB(1), 0);
    add_l3(0xFFFF, MB(32)), add_l3(0xFFFF0000ull, MB(96));
    CHECK(pick(0xFFFFFFFFull, 1) == 0xFFFF0000ull && x.why == HOS_X3D_USED, "the large cache on the second die");
    CHECK(reserved(0xFFFF0000ull) == 0xC0000000ull, "its last core");

    /* the same without SMT: 16 logical processors */
    fresh();
    add_cores(16, 1, 0, MB(1), 0);
    add_l3(0xFF, MB(96)), add_l3(0xFF00, MB(32));
    CHECK(pick(0xFFFF, 1) == 0xFF && x.cores == 8, "SMT off: the die's 8 processors");
    CHECK(reserved(0xFF) == 0x80, "its last core");
    CHECK(hos_x3d_thread_mask(0xFFFF, 0xFF, 0x80) == 0x7F, "a game thread there");

    /* both dies with the large cache */
    fresh();
    add_cores(16, 2, 0, MB(1), 0);
    add_l3(0xFFFF, MB(96)), add_l3(0xFFFF0000ull, MB(96));
    CHECK(pick(0xFFFFFFFFull, 1) == 0 && x.why == HOS_X3D_SAME, "the cache on both dies: nothing");

    /* Ryzen 9 7900X3D: two dies of 6 cores */
    fresh();
    add_cores(12, 2, 0, MB(1), 0);
    add_l3(0xFFF, MB(96)), add_l3(0xFFF000, MB(32));
    CHECK(pick(0xFFFFFF, 1) == 0 && x.why == HOS_X3D_FEW && x.cores == 6 && x.die == 0xFFF, "six cores under the large cache: nothing");

    /* a mobile part: 4 large cores under 16 MB, 8 small ones under 8 MB */
    fresh();
    add_cores(4, 2, 0, MB(1), 0);
    add_cores(8, 2, 8, MB(1), 0);
    add_l3(0xFF, MB(16)), add_l3(0xFFFF00, MB(8));
    CHECK(pick(0xFFFFFF, 1) == 0 && x.why == HOS_X3D_FEW && x.cores == 4, "four large cores: nothing");

    /* Intel Core i9-13900K: 8 performance cores (2 MB of L2 each), 16 efficiency cores (4 MB of L2 for each four,
       listed per core here), one L3 of 36 MB over all 32 logical processors */
    fresh();
    add_cores(8, 2, 0, MB(2), 1);
    add_cores(16, 1, 16, MB(4), 0);
    add_l3(0xFFFFFFFFull, MB(36));
    CHECK(pick(0xFFFFFFFFull, 1) == 0 && x.why == HOS_X3D_SAME, "two kinds of core, one L3: nothing");
    CHECK(reserved(0) == 0xC000, "its replay core: the last performance core, as before");
    CHECK(hos_x3d_thread_mask(0xFFFFFFFFull, 0, 0xC000) == 0xFFFF3FFFull, "a game thread: as before");

    /* an L2 larger on some cores must not count as a die: only L3 caches are looked at */
    fresh();
    add_cores(8, 2, 0, MB(96), 0);
    add_cores(8, 2, 16, MB(32), 0);
    add_l3(0xFFFFFFFFull, MB(64));
    CHECK(pick(0xFFFFFFFFull, 1) == 0 && x.why == HOS_X3D_SAME, "L2 sizes are not looked at");

    /* over 64 logical processors: two processor groups; the calling group's list looks like a two-die X3D */
    fresh();
    add_cores(16, 2, 0, MB(1), 0);
    add_l3(0xFFFF, MB(96)), add_l3(0xFFFF0000ull, MB(32));
    CHECK(pick(0xFFFFFFFFull, 2) == 0 && x.why == HOS_X3D_GROUPS, "more than one processor group: nothing");
    CHECK(pick(0xFFFFFFFFull, 0) == 0 && x.why == HOS_X3D_GROUPS, "a group count that could not be read: nothing");

    /* the process held to some processors at its start: never widened */
    CHECK(pick(0xFFFF, 1) == 0 && x.why == HOS_X3D_ALL, "held to the die already: nothing to do");
    CHECK(pick(0xFFFF0000ull, 1) == 0 && x.why == HOS_X3D_FEW && x.cores == 0, "held to the other die: nothing");
    CHECK(pick(0xFFFF00FFull, 1) == 0 && x.why == HOS_X3D_FEW && x.cores == 4, "held to four of the die's cores: nothing");
    CHECK(pick(0x00FFFFFFull, 1) == 0xFFFF && x.why == HOS_X3D_USED, "held to the die and half the other: the die");
    CHECK(pick(0x5555FFFFull, 1) == 0xFFFF, "(one processor of each other core allowed)");
    CHECK(pick(0xFFFF5555ull, 1) == 0x5555 && x.cores == 8, "one processor of each of the die's cores: those");

    /* lists not to act on */
    fresh();
    add_cores(16, 2, 0, MB(1), 0);
    CHECK(pick(0xFFFFFFFFull, 1) == 0 && x.why == HOS_X3D_NONE, "no L3 listed: nothing");
    add_l3(0xFFFFF, MB(96)), add_l3(0xFFFF0000ull, MB(32));
    CHECK(pick(0xFFFFFFFFull, 1) == 0 && x.why == HOS_X3D_NONE, "a processor under two L3 caches: nothing");
    fresh();
    add_cores(16, 2, 0, MB(1), 0);
    add_l3(0xFFFF, MB(96)), add_l3(0, MB(32)), add_l3(0xFFFF0000ull, 0);
    CHECK(pick(0xFFFFFFFFull, 1) == 0 && x.why == HOS_X3D_SAME, "an L3 with no processors or no size is not one");

    /* a game thread's affinity with no die: what hos_thread_pin did before */
    CHECK(hos_x3d_thread_mask(0xFFFF, 0, 0xC000) == 0x3FFF, "the process's processors but the reserved core's");
    CHECK(hos_x3d_thread_mask(0xFFFF, 0, 0) == 0, "nothing reserved: no affinity set");
    CHECK(hos_x3d_thread_mask(0xC000, 0, 0xC000) == 0, "a process held to the reserved core: no affinity set");
    CHECK(hos_x3d_thread_mask(0xFFFF, 0xFFFF0000ull, 0xC000) == 0x3FFF, "a die the process is not on: as with none");
    CHECK(hos_x3d_thread_mask(0xC0FF, 0xFF00, 0xC000) == 0xC000, "the die's processors all reserved: the die");

    /* ---- (Triforce, THREAD-49) whether a core of the die is kept for the replay ---- */
    CHECK(hos_x3d_keep_replay_core(0xFF, 8, -1, 0) == 0, "8 cores on 8 logical processors, not set: none kept");
    CHECK(hos_x3d_keep_replay_core(0xFFFF, 8, -1, 0) == 1, "8 cores on 16 logical processors, not set: one kept, as before");
    CHECK(hos_x3d_keep_replay_core(0xFF, 8, 1, 0) == 1 && hos_x3d_keep_replay_core(0xFFFF, 8, 1, 0) == 1, "asked for: kept");
    CHECK(hos_x3d_keep_replay_core(0xFF, 8, 0, 0) == 0 && hos_x3d_keep_replay_core(0xFFFF, 8, 0, 0) == 0, "asked not to: none");
    CHECK(hos_x3d_keep_replay_core(0xFFFF, 8, 0, 1) == 0, "asked not to, with the replay's own thread: none, as before");
    CHECK(hos_x3d_keep_replay_core(0xFF, 8, -1, 1) == 1, "the replay on a thread of its own: kept, the thread is pinned there");
    CHECK(hos_x3d_keep_replay_core(0, 8, -1, 0) == 1 && hos_x3d_keep_replay_core(0, 0, -1, 0) == 1, "no die: as before");
    CHECK(hos_x3d_keep_replay_core(0xFF, 0, -1, 0) == 1, "the die's cores not counted: as before");
    CHECK(hos_x3d_reserved(0x80, 0xFF, 8, -1, 0) == 0 && hos_x3d_reserved(0x80, 0xFF, 8, 1, 0) == 0x80, "the kept core, or none");

    /* a two-die X3D with SMT off (16 logical processors): none kept, a game thread has the whole die */
    fresh();
    add_cores(16, 1, 0, MB(1), 0);
    add_l3(0xFF, MB(96)), add_l3(0xFF00, MB(32));
    CHECK(kept(0xFFFF, -1, 0) == 0 && kept_die == 0xFF, "SMT off: no core of the die kept");
    CHECK(game(0xFFFF, -1, 0) == 0xFF, "a game thread there: all 8 of the die's cores");
    CHECK(kept(0xFFFF, 1, 0) == 0x80 && game(0xFFFF, 1, 0) == 0x7F, "HOS_RESERVE_CORE=1: the die's last core, as before");
    CHECK(kept(0xFFFF, -1, 1) == 0x80 && game(0xFFFF, -1, 1) == 0x7F, "RX_VK_ASYNC=1: the replay thread's core is kept");
    CHECK(kept(0xFFFF, 0, 0) == 0 && game(0xFFFF, 0, 0) == 0xFF, "HOS_RESERVE_CORE=0: none, as before");
    /* the large cache on the second die, SMT off */
    fresh();
    add_cores(16, 1, 0, MB(1), 0);
    add_l3(0xFF, MB(32)), add_l3(0xFF00, MB(96));
    CHECK(kept(0xFFFF, -1, 0) == 0 && game(0xFFFF, -1, 0) == 0xFF00, "the second die, SMT off: none kept, the die whole");
    /* the same part with SMT on: one kept, exactly as before */
    fresh();
    add_cores(16, 2, 0, MB(1), 0);
    add_l3(0xFFFF, MB(96)), add_l3(0xFFFF0000ull, MB(32));
    CHECK(kept(0xFFFFFFFFull, -1, 0) == 0xC000 && game(0xFFFFFFFFull, -1, 0) == 0x3FFF, "SMT on: the die's last core kept, as before");
    CHECK(kept(0xFFFFFFFFull, 1, 0) == 0xC000 && kept(0xFFFFFFFFull, -1, 1) == 0xC000, "and with the switch or the replay's own thread");
    /* SMT on, the process held to one logical processor of each core: 8 processors on the die's 8 cores, as SMT off */
    CHECK(kept(0xFFFF5555ull, -1, 0) == 0 && kept_die == 0x5555 && game(0xFFFF5555ull, -1, 0) == 0x5555,
          "one processor a core allowed: none kept");
    /* this PC's kind: 8 cores, 16 logical processors, one L3: no die, and the core is kept whatever the replay's thread */
    fresh();
    add_cores(8, 2, 0, MB(1), 0);
    add_l3(0xFFFF, MB(32));
    CHECK(kept(0xFFFF, -1, 0) == 0xC000 && kept_die == 0 && game(0xFFFF, -1, 0) == 0x3FFF, "8 cores, 16 processors, one L3: as before");
    CHECK(kept(0xFFFF, 1, 0) == 0xC000 && kept(0xFFFF, -1, 1) == 0xC000 && kept(0xFFFF, 0, 0) == 0, "and with the switch");
    /* the same with SMT off (8 logical processors, one L3): still no die, so still kept: the rule is the die's alone */
    fresh();
    add_cores(8, 1, 0, MB(1), 0);
    add_l3(0xFF, MB(96));
    CHECK(kept(0xFF, -1, 0) == 0x80 && kept_die == 0 && game(0xFF, -1, 0) == 0x7F, "one die with SMT off: as before");
    /* two dies alike with SMT off, a six-core cache die, an Intel processor of two kinds of core: no die, as before */
    fresh();
    add_cores(16, 1, 0, MB(1), 0);
    add_l3(0xFF, MB(32)), add_l3(0xFF00, MB(32));
    CHECK(kept(0xFFFF, -1, 0) == 0x8000 && game(0xFFFF, -1, 0) == 0x7FFF, "two dies alike, SMT off: the processor's last core");
    fresh();
    add_cores(12, 1, 0, MB(1), 0);
    add_l3(0x3F, MB(96)), add_l3(0xFC0, MB(32));
    CHECK(kept(0xFFF, -1, 0) == 0x800 && kept_die == 0, "six cores under the large cache, SMT off: no die, the last core kept");
    fresh();
    add_cores(8, 2, 0, MB(2), 1);
    add_cores(16, 1, 16, MB(4), 0);
    add_l3(0xFFFFFFFFull, MB(36));
    CHECK(kept(0xFFFFFFFFull, -1, 0) == 0xC000 && game(0xFFFFFFFFull, -1, 0) == 0xFFFF3FFFull, "two kinds of core: as before");

    printf(fails ? "x3d placement: FAILED\n" : "x3d placement: all checks passed\n");
    return fails != 0;
}
'''


def check_source(thread):
    detect = block(thread, "static uint64_t x3d_detect(")
    cpus = block(thread, "static uint64_t hos_x3d_cpus(")
    last = block(thread, "static uint64_t last_fastest_core(")
    pin = block(thread, "void hos_thread_pin(")
    kept = block(thread, "uint64_t hos_reserved_cpus(void) {")
    for text, needle, why in (
            (detect, "RelationCache", "the caches are not read"),
            (detect, "e->Cache.GroupMask.Group == group", "caches of another processor group are taken"),
            (detect, "(uint64_t)proc, (int)GetActiveProcessorGroupCount(), out)", "the rule no longer gets the process's affinity and the group count"),
            (cpus, 'getenv("HOS_X3D")', "HOS_X3D is not read"),
            (cpus, "if (x.why == HOS_X3D_USED && !off) mask = die;", "the die is used when the rule did not fire, or with HOS_X3D=0"),
            (cpus, "hos_log(\"cpu: logical processors", "what was found is not logged"),
            (last, "const uint64_t die = hos_x3d_cpus();", "the replay's core is not chosen with the die"),
            (last, "(!die || ((uint64_t)e->Processor.GroupMask[0].Mask & die))", "the replay's core is not among the die's cores"),
            (pin, "hos_x3d_thread_mask((uint64_t)proc, die, reserved)", "a game thread's affinity is not the header's"),
            # ((Triforce, THREAD-49) the rule is asked with the switch's value and whether the replay has its own thread)
            (kept, 'const char *e = getenv("HOS_RESERVE_CORE");', "HOS_RESERVE_CORE is not read"),
            (kept, "const int asked = e ? atoi(e) != 0 : -1;", "the switch not set is not told from the switch set"),
            (kept, "if (!asked) return mask;", "HOS_RESERVE_CORE=0 no longer keeps none on every processor"),
            (kept, "const uint64_t die = hos_x3d_cpus();", "the rule is not asked about the die the game's threads are kept on"),
            (kept, "if (cores && fast && !hos_x3d_reserved(fast, die, cores, asked, rx_async_replay())) {",
             "hos_reserved_cpus does not ask the header whether a core of the die is kept"),
            (kept, 'hos_log("cpu: no core kept for the replay on the cache die (HOS_RESERVE_CORE=1: one is)");',
             "keeping no core on the die leaves no line in the log")):
        if needle not in text:
            raise SystemExit("host/hos_thread.c: " + why)
    if kept.index("!hos_x3d_reserved(fast, die, cores, asked, rx_async_replay())") > kept.index("if (cores) return mask = fast;"):
        raise SystemExit("host/hos_thread.c: hos_reserved_cpus keeps the die's core before it asks the rule")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    if "`HOS_RESERVE_CORE=0`, `=1` |" not in dev or "`cpu: no core kept for the replay on the cache die`" not in dev:
        raise SystemExit("docs/development.md: HOS_RESERVE_CORE=1 and the cache die's rule are not in the switches table")
    # (the reader is Windows' alone: Linux and the web keep what they had)
    at = thread.index("static uint64_t x3d_detect(")
    if thread.rindex("#if defined(_WIN32)", 0, at) < thread.rindex("#endif", 0, at):
        raise SystemExit("host/hos_thread.c: x3d_detect is no longer inside #if defined(_WIN32)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    thread = (ROOT / "host/hos_thread.c").read_text(encoding="utf-8")
    check_source(thread)
    fixture = FIXTURE.replace("@PICK_RESERVED@", block(thread, "static uint64_t pick_reserved_core("))
    with tempfile.TemporaryDirectory(prefix="x3d-") as d:
        tmp = Path(d)
        (tmp / "t.c").write_text(fixture, encoding="utf-8")
        exe = tmp / ("t.exe" if sys.platform == "win32" else "t")
        subprocess.run([args.cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-O1", "-I", str(ROOT / "host"),
                        str(tmp / "t.c"), "-o", str(exe)], check=True)
        run = subprocess.run([str(exe)], text=True, capture_output=True, timeout=60)
        sys.stdout.write(run.stdout)
        if run.returncode or "all checks passed" not in run.stdout:
            raise SystemExit("the placement's checks failed" + run.stderr)


if __name__ == "__main__":
    main()
