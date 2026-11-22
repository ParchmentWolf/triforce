"""A freed region's discard and the freeing thread's virtual core: HOS_DISCARD_KEEP_CORE (host/hos_mem.c discard_core,
hos_region_free, discard_pages; no game).

(Triforce, 11-22, the performance audit's OS-40, after Source A's.) Not set, everything is as before: the core is given
up only for the discard's own kernel call and only with the memory limit on. 0 is Source A's: the freeing thread gives
its core up before the whole of the discard and takes it back once, after the region is unlisted. 1 keeps the core
through every discard.

hos_region_free and the rule are cut out of hos_mem.c, hos_vcore_away and hos_vcore_back out of hos_thread.c, and run
over the real virtual cores (vc_lock to vc_yield, with tests/vcore_spin_test.c's stand-ins) and a discard that stands in
for the kernel's and takes the core as discard_pages does (the rule's answer for its own call). A process a switch
value, the switch being read once:

- alone: a region with something to discard, the limit off and on; a region of the game's with none of its pages (a
  bare free); an address that is no region. What the core is at the import's zero-fill and at the kernel's call, how
  often it is taken back, that the region is still listed and marked while it is discarded and the regions' lock is
  free then, and that the thread has its core again when the free returns;
- the wait this changes, on two threads: the freeing thread and another game thread allowed only on its core. With 0 the
  other thread runs on the core while the discard is made, takes the regions' lock and finds the region still listed;
  the freeing thread then waits for the core, having let the lock go first, so the other thread, still holding the core,
  takes the lock again, finds the region gone, and gives the core back: nobody waits for good. Not set and with 1 the
  other thread gets the core only after the free;
- the rule alone, over the switch's values and the limit.
Broken frees must fail: the core taken back under the regions' lock (the other thread, which holds the core, cannot get
the lock), never taken back, given up for a bare free, and given up when the switch is not set.

    python -I -B tests/test_region_free_vcore.py [--cc clang]
"""
import argparse
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "clang"]

ROOT = Path(__file__).resolve().parents[1]
FAR = "60000000"


def fail(message):
    raise SystemExit("FAIL: " + message)


def block(source, marker):
    start = source.index(marker)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


CASES = r'''
/* ---- (Triforce, OS-40) hos_mem.c's freed regions over the real virtual cores ---- */
static _Thread_local HosThread *cur;
@AWAY@
@BACK@
@RANGE@
static Range store[8];
static Range *regions = store;
static int nregions;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
#define LOCK() pthread_mutex_lock(&lock)
#define UNLOCK() pthread_mutex_unlock(&lock)
static int64_t limit_on;
static int64_t hos_mem_limit(void) { return limit_on; }
static int hos_mem_census_on(void) { return 1; }
#define GC_SPACE (1ull << 40)
enum { GC_GAME = 1 };
enum { HOS_MEM_DISCARDED = 3 };
static int census, notes;
static uint64_t game_pages_in = 0x1000;
static uint64_t gc_count(int *m, int kind, uint64_t lo, uint64_t hi) { (void)m, (void)kind, (void)lo, (void)hi; return game_pages_in; }
static void hos_mem_note(int what, uint64_t addr, uint64_t size) { (void)addr, (void)size; CHECK(what == HOS_MEM_DISCARDED); notes++; }
@RULE@
/* the discard, standing in for hos_mem.c's: what the core is at the import's zero-fill, then the call's own give-up by the
   rule, the kernel's call (the case's hook: what another thread does meanwhile), and the core back if it gave it up */
static int discards, core_at_zero_fill, core_at_kernel, listed_at_discard, lock_free_at_discard;
static void (*during)(void);
static void discard_pages(uint64_t addr, uint64_t size) {
    (void)size;
    discards++;
    core_at_zero_fill = cur->vc_held;
    lock_free_at_discard = pthread_mutex_trylock(&lock) == 0;
    if (lock_free_at_discard) {
        listed_at_discard = 0;
        for (int i = 0; i < nregions; i++) listed_at_discard |= regions[i].addr == addr && regions[i].freeing;
        pthread_mutex_unlock(&lock);
    }
    const int away = discard_core_call_away(discard_core(), hos_mem_limit() != 0) ? hos_vcore_away() : 0;
    core_at_kernel = cur->vc_held;
    if (during) during();
    if (away) hos_vcore_back();
}
@NEEDED@
@PAGES@
@MARK@
static int64_t region_frees_bare;
static int64_t region_frees_away, region_back_longest_ns;
@FREE@

static HosThread f, w;
static const uint64_t R = 0x100000000ull;
static int listed(uint64_t addr) {
    int n = 0;
    for (int i = 0; i < nregions; i++) n += regions[i].addr == addr;
    return n;
}
static void region(uint64_t addr, int game) {
    regions[nregions].addr = addr, regions[nregions].size = 0x40000, regions[nregions].freeing = 0, regions[nregions].game = game;
    nregions++;
}
static int64_t takes(void) {
    AcquireSRWLockExclusive(&vc_lock);
    const int64_t v = vc_st.takes;
    ReleaseSRWLockExclusive(&vc_lock);
    return v;
}
/* the other game thread, allowed only on the freeing thread's core */
static int w_ran, w_saw_listed, w_saw_gone, with_region_away;
static void *other(void *arg) {
    (void)arg;
    cur = &w;
    hos_vcore_back();                              /* (waits for core 0: until the freeing thread gives it up) */
    LOCK();
    w_saw_listed = listed(R);
    UNLOCK();
    __atomic_store_n(&w_ran, 1, __ATOMIC_RELEASE);
    if (with_region_away) {
        wait_for(&f.vc_queued, 1);                 /* the freeing thread waits for its core, which this thread holds */
        int got = 0;                               /* it must have let the lock go before it queued */
        for (int i = 0; i < 10000 && !(got = pthread_mutex_trylock(&lock) == 0); i++) sleep_us(200);
        if (!got) {
            printf("FAIL: the freeing thread waits for its core with the regions' lock held: the thread that holds the core cannot go on\n");
            fflush(stdout);
            _Exit(1);
        }
        w_saw_gone = !listed(R);
        UNLOCK();
    }
    hos_vcore_away();
    return NULL;
}
static void let_other_run(void) {                  /* the kernel's milliseconds: the other thread runs on the core meanwhile */
    wait_for(&w_ran, 1);
}
static void other_still_waits(void) {
    CHECK(w.vc_queued == 1 && !__atomic_load_n(&w_ran, __ATOMIC_ACQUIRE));
}
int main(int argc, char **argv) {
    const char *c = argc > 1 ? argv[1] : "";
    const int mode = discard_core();
    {
        pthread_t dog;
        pthread_create(&dog, NULL, watchdog, NULL);
        pthread_detach(dog);
    }
    cores = 2;
    test_clock = 1000000000000LL;                  /* (standing still: no time slice, no escape) */
    thread_init(&f, "freeing", 20, 1);
    thread_init(&w, "other", 20, 1);
    cur = &f;
    hos_vcore_back();
    CHECK(f.vc_held == 1);
    if (!strcmp(c, "alone")) {
        const int region_away = discard_core_region_away(mode);
        for (limit_on = 0; limit_on <= 1; limit_on++) {
            const int call_away = discard_core_call_away(mode, (int)limit_on);
            region(R + 0x1000000, 0), region(R, 0);
            const int64_t t0 = takes();
            discards = notes = 0;
            hos_region_free(R);
            CHECK(discards == 1 && f.vc_held == 1 && !f.vc_queued);            /* the thread has its core when the free returns */
            CHECK(listed_at_discard && lock_free_at_discard);                   /* listed and marked meanwhile, the lock free */
            CHECK(nregions == 1 && !listed(R) && regions[0].addr == R + 0x1000000);
            CHECK((core_at_zero_fill != 0) == !region_away);                    /* held over the zero-fill unless the region gave it up */
            CHECK((core_at_kernel != 0) == !(region_away || call_away));        /* and over the kernel's call unless either did */
            CHECK(takes() - t0 == (region_away || call_away ? 1 : 0));          /* taken back once, by whoever gave it up */
            nregions = 0;
        }
        /* a region of the game's with none of its pages, the limit on: nothing to discard, the core kept in every mode */
        limit_on = 1, game_pages_in = 0;
        region(R, 1);
        const int64_t t1 = takes();
        discards = notes = 0;
        hos_region_free(R);
        CHECK(discards == 0 && notes == 1 && region_frees_bare == 1 && takes() == t1 && f.vc_held == 1 && nregions == 0);
        hos_region_free(R), hos_region_free(R + 0x5000);                        /* freed already, and no region: nothing */
        CHECK(discards == 0 && notes == 1 && takes() == t1 && f.vc_held == 1);
        game_pages_in = 0x1000;
        CHECK(region_frees_away == (region_away ? 2 : 0));
        /* the rule */
        CHECK(discard_core_rule(NULL) == DISCARD_CORE_AS_BEFORE && discard_core_rule("") == DISCARD_CORE_AS_BEFORE);
        CHECK(discard_core_rule("0") == DISCARD_CORE_GIVEN_UP && discard_core_rule("1") == DISCARD_CORE_KEPT && discard_core_rule("2") == DISCARD_CORE_KEPT);
        CHECK(!discard_core_region_away(DISCARD_CORE_AS_BEFORE) && discard_core_region_away(DISCARD_CORE_GIVEN_UP) && !discard_core_region_away(DISCARD_CORE_KEPT));
        CHECK(!discard_core_call_away(DISCARD_CORE_AS_BEFORE, 0) && discard_core_call_away(DISCARD_CORE_AS_BEFORE, 1));   /* (as before: the limit's) */
        CHECK(discard_core_call_away(DISCARD_CORE_GIVEN_UP, 0) && discard_core_call_away(DISCARD_CORE_GIVEN_UP, 1));
        CHECK(!discard_core_call_away(DISCARD_CORE_KEPT, 0) && !discard_core_call_away(DISCARD_CORE_KEPT, 1));
    } else if (!strcmp(c, "two")) {
        with_region_away = discard_core_region_away(mode);
        limit_on = 0;
        region(R, 0);
        pthread_t th;
        pthread_create(&th, NULL, other, NULL);
        wait_for(&w.vc_queued, 1);                 /* the other thread waits for the core this one holds */
        during = with_region_away ? let_other_run : other_still_waits;
        hos_region_free(R);
        CHECK(f.vc_held == 1 && !listed(R));
        if (with_region_away) {
            pthread_join(th, NULL);
            CHECK(w_ran && w_saw_listed == 1 && w_saw_gone == 1);   /* it ran during the discard, and again once the region was gone */
            CHECK(core_at_zero_fill == 0 && core_at_kernel == 0);
        } else {
            CHECK(!__atomic_load_n(&w_ran, __ATOMIC_ACQUIRE) && core_at_zero_fill == 1 && core_at_kernel == 1);
            hos_vcore_away();                      /* (a block of the freeing thread's: only now the other one runs) */
            pthread_join(th, NULL);
            CHECK(w_ran && w_saw_listed == 0);
            hos_vcore_back();
        }
        CHECK(f.vc_held == 1);
    } else {
        FAIL("unknown case %s", c);
    }
    hos_vcore_away();
    end_state();
    if (failures) return 1;
    printf("PASS %s\n", c);
    return 0;
}
'''

AWAY = "        if (discard_core_region_away(discard_core())) away = hos_vcore_away();\n"
NEEDED = "    if (hos_region_discard_needed(game && hos_mem_limit(), hos_mem_census_on(), game_pages)) {\n"
BACK = "        hos_vcore_back();\n"
LAST_UNLOCK = "    UNLOCK();\n    /* ((Triforce, 11-22, OS-40) the core back, after the lock is let go:"
# (each: what the broken free does, the switch's value and the case that must fail, and the change to the cut hos_region_free)
MUTANTS = [
    ("takes the core back under the regions' lock", "0", "two", [(BACK, ""), (LAST_UNLOCK, "    if (away) hos_vcore_back();\n" + LAST_UNLOCK)]),
    ("never takes the core back", "0", "alone", [(BACK, "")]),
    ("gives the core up for a bare free", "0", "alone", [(AWAY, ""), (NEEDED, "    if (discard_core_region_away(discard_core())) away = hos_vcore_away();\n" + NEEDED)]),
    ("gives the core up with the switch not set", None, "alone", [(AWAY, "        away = hos_vcore_away();\n")]),
    ("gives the core up with the switch at 1", "1", "two", [(AWAY, "        away = hos_vcore_away();\n")]),
]


def read_sources(mem, dev):
    free = block(mem, "void hos_region_free(uint64_t addr) {")
    order = [NEEDED, AWAY, "        discard_pages(addr, freed_size);\n", "            nregions--;\n", LAST_UNLOCK, "    if (away) {\n", BACK]
    at = -1
    for needle in order:
        nxt = free.find(needle, at + 1)
        if nxt < 0:
            fail("hos_mem.c hos_region_free: %r is not there, or not after what comes before it" % needle.strip())
        at = nxt
    if free.count("hos_vcore_away()") != 1 or free.count("hos_vcore_back()") != 1 or free.count("LOCK();") != 4:
        fail("hos_mem.c hos_region_free: more than one give-up or take-back, or its two locked parts changed")
    discard = block(mem, "static void discard_pages(uint64_t addr, uint64_t size) {")
    if "const int away = discard_core_call_away(discard_core(), hos_mem_limit() != 0) ? hos_vcore_away() : 0;" not in discard:
        fail("hos_mem.c discard_pages: the call's own give-up is not the rule's")
    core = block(mem, "static int discard_core(void) {")
    if 'mode = discard_core_rule(getenv("HOS_DISCARD_KEEP_CORE"));' not in core or "static int mode = -1;" not in core:
        fail("hos_mem.c discard_core: HOS_DISCARD_KEEP_CORE is not read once through the rule")
    if "| `HOS_DISCARD_KEEP_CORE=0`, `=1` |" not in dev:
        fail("docs/development.md: HOS_DISCARD_KEEP_CORE is not in the switches table")
    return free


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    try:
        mem = (ROOT / "host/hos_mem.c").read_text(encoding="utf-8")
        thread = (ROOT / "host/hos_thread.c").read_text(encoding="utf-8")
        free = read_sources(mem, (ROOT / "docs/development.md").read_text(encoding="utf-8"))
        range_t = re.findall(r"^typedef struct \{[^}]*\} Range;$", mem, re.M)
        pages_used = re.findall(r"^static uint64_t pages_used\[[^\n]*\];$", mem, re.M)
        if len(range_t) != 1 or len(pages_used) != 1:
            fail("hos_mem.c's Range or pages_used not found once")
        pieces = {"@AWAY@": block(thread, "int hos_vcore_away(void) {"), "@BACK@": block(thread, "void hos_vcore_back(void) {"),
                  "@RANGE@": range_t[0], "@PAGES@": pages_used[0], "@MARK@": block(mem, "static void pages_mark_used_locked("),
                  "@RULE@": mem[mem.index("enum { DISCARD_CORE_AS_BEFORE, DISCARD_CORE_GIVEN_UP, DISCARD_CORE_KEPT };"):mem.index("static void discard_pages(")],
                  "@NEEDED@": block(mem, "int hos_region_discard_needed(int game_region, int census_on, uint64_t game_pages) {")}
        cores = thread[thread.index("static SRWLOCK vc_lock = SRWLOCK_INIT;"):thread.index("int hos_vcore_away(void) {")]
        spin = (ROOT / "tests/vcore_spin_test.c").read_text(encoding="utf-8")
        stand_ins = spin[:spin.index("/* ---- storm: many hand-offs")]
    except (ValueError, OSError) as e:
        fail("a text this test reads is not there (%s)" % e)
    compiler = shutil.which(args.cc)
    if not compiler:
        raise SystemExit("C compiler not found: " + args.cc)
    env = {k: v for k, v in os.environ.items() if not k.startswith("HOS_")}
    env.update(HOS_VCORE_ESCAPE_US=FAR, HOS_VCORE_ESCAPE_EQ_US=FAR, HOS_VCORE_SLICE_US=FAR, HOS_VCORE_SPIN_US="0")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="region-free-") as temporary:
        top = Path(temporary)

        def build(name, free_text):
            folder = top / name
            folder.mkdir()
            (folder / "vcore_block.inc").write_text(cores, encoding="utf-8")
            text = stand_ins + CASES
            for mark, piece in dict(pieces, **{"@FREE@": free_text}).items():
                text = text.replace(mark, piece)
            (folder / "free.c").write_text(text, encoding="utf-8")
            exe = folder / "free.exe"
            built = subprocess.run([compiler, "-std=gnu17", "-O1", "-Wall", "-Werror", "-Wno-unused-function", "-Wno-unused-variable",
                                    "-Wno-unknown-warning-option", "-Wno-unused-but-set-variable", "-Wno-unused-but-set-global", "-pthread",
                                    "-I" + str(folder), str(folder / "free.c"), "-o", str(exe)], capture_output=True, text=True, timeout=180)
            if built.returncode:
                print(built.stdout + built.stderr)
                fail("the fixture did not build (%s)" % name)
            return exe

        def run(exe, case, switch):
            case_env = dict(env) if switch is None else dict(env, HOS_DISCARD_KEEP_CORE=switch)
            try:
                return subprocess.run([str(exe), case], env=case_env, capture_output=True, text=True, timeout=120, creationflags=flags)
            except subprocess.TimeoutExpired:
                return subprocess.CompletedProcess([], 1, "no end in 120 s (a thread waits for good)", "")

        exe = build("as-made", free)
        for switch, what in ((None, "not set: as before"), ("0", "0: the core given up for the whole discard"), ("1", "1: the core kept")):
            for case in ("alone", "two"):
                done = run(exe, case, switch)
                if done.returncode or "PASS " + case not in done.stdout:
                    print(done.stdout[-3000:] + done.stderr[-1000:])
                    fail("HOS_DISCARD_KEEP_CORE %s, the case %s" % (what, case))
            print("PASS HOS_DISCARD_KEEP_CORE " + what)
        for i, (what, switch, case, changes) in enumerate(MUTANTS):
            text = free
            for old, new in changes:
                if text.count(old) != 1:
                    fail("mutation %r: %r is not in the cut hos_region_free once (update the test with the code)" % (what, old.strip()))
                text = text.replace(old, new)
            done = run(build("mutant%d" % i, text), case, switch)
            if done.returncode == 0:
                fail("a free that %s still passed" % what)
            said = [line for line in done.stdout.splitlines() if line.startswith("FAIL")] or [done.stdout.strip()[-120:]]
            print("PASS mutation: a free that %s fails (%s)" % (what, said[0][:120]))
    print("PASS: a freed region's discard keeps or gives up the core by HOS_DISCARD_KEEP_CORE, as before when it is not set, and nobody waits for good")


if __name__ == "__main__":
    main()
