"""Virtual cores: HOS_VCORE_WIDE=1 lets a game thread whose mask names two or more cores take any free core (host/
hos_thread.c vc_allowed; no game).

(Triforce, 11-22, the performance audit's GAME-22, after Source B's.) Off unless set. A thread with a one-core mask,
which guards the game's lock-free per-core data, and a thread with no mask stay where they were, with the switch or
without it.

host/hos_thread.c's virtual cores (vc_lock to vc_yield) are cut out unchanged and run on real threads with tests/
vcore_spin_test.c's stand-ins (pthreads for Windows' lock and condition variable, its clock, its hold() that fails when a
core is run by two threads). The scripted cases stand on the test's own clock and wait for states, never for a time:

- two cores held, the third free: a thread whose mask names the two held ones waits for one of them without the switch
  (and gets it when its holder lets go: the wake-up is not lost), and takes the free third at once with it; the core
  number it then answers is the core it holds;
- all three held, the third let go: with the switch the release grants it to that waiter; without it the waiter goes on
  waiting for one of its own two, and gets it at that one's release;
- a thread with a one-core mask and a thread with no mask (its ideal core) wait for their own core beside two free
  ones, with the switch too.
Two broken rules (a one-core mask widened, a thread with no mask widened) must fail the script with the switch on.

A storm, with the switch and without: eight threads of three priorities and masks of one, two and three cores hand three
cores to each other tens of thousands of times; no core is ever run by two threads, none runs without a core, a
one-core thread only ever holds its own core, without the switch every thread only cores of its mask, and nothing is
left owned or queued at the end.

    python -I -B tests/test_vcore_wide.py [--cc clang]
"""
import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "clang"]

ROOT = Path(__file__).resolve().parents[1]
FAR = "60000000"   # (60 s: no escape and no time slice in these cases)


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
/* ---- (Triforce, GAME-22) HOS_VCORE_WIDE ---- */
typedef struct {
    HosThread t;
    int got, go;   /* got: the core it holds + 1 once it has one */
} Taker;
static void *take(void *arg) {
    Taker *k = (Taker *)arg;
    vc_acquire(&k->t);
    __atomic_store_n(&k->got, k->t.vc_held, __ATOMIC_RELEASE);
    hold(&k->t);   /* (fails when another thread runs on that core, or when it has none) */
    wait_for(&k->go, 1);
    vc_release(&k->t);
    return NULL;
}
static void taker(Taker *k, const char *name, int priority, uint64_t mask, int ideal, pthread_t *th) {
    memset(k, 0, sizeof *k);
    thread_init(&k->t, name, priority, mask);
    k->t.ideal_core = ideal;
    pthread_create(th, NULL, take, k);
}
static int64_t waits_now(void) {
    AcquireSRWLockExclusive(&vc_lock);
    const int64_t v = vc_st.waits;
    ReleaseSRWLockExclusive(&vc_lock);
    return v;
}
static void done(Taker *k, pthread_t th) {
    __atomic_store_n(&k->go, 1, __ATOMIC_RELEASE);
    pthread_join(th, NULL);
}
/* waits until k waits for a core; a taker that took one instead ends the case at once (it would never queue) */
static void must_wait(Taker *k) {
    while (!__atomic_load_n(&k->t.vc_queued, __ATOMIC_ACQUIRE)) {
        const int got = __atomic_load_n(&k->got, __ATOMIC_ACQUIRE);
        if (got) {
            printf("FAIL: %s took core %d instead of waiting for a core of its own\n", k->t.name, got - 1);
            fflush(stdout);
            _Exit(1);
        }
        sleep_us(200);
    }
}
static void script(int wide) {
    static HosThread h0, h1, h2;
    static Taker a, b, n;
    pthread_t ta, tb, tn;
    cores = 3;
    test_clock = 1000000000000LL;   /* (standing still: no time slice, no escape) */
    thread_init(&h0, "holder 0", 10, 1);
    thread_init(&h1, "holder 1", 10, 2);
    thread_init(&h2, "holder 2", 10, 4);

    /* 1. cores 0 and 1 held, core 2 free: a thread of cores 0 and 1 (worse than the holders: it asks for nothing) */
    vc_acquire(&h0), vc_acquire(&h1);
    CHECK(h0.vc_held == 1 && h1.vc_held == 2);
    taker(&a, "two cores", 20, 3, -2, &ta);
    if (wide) {
        wait_for(&a.got, 1);
        CHECK(a.got == 3);                      /* the free third core, at once */
        CHECK(waits_now() == 0);
        CHECK(hos_thread_core(&a.t) == 2);      /* GetCurrentCoreNumber: the core it holds, not one of its mask */
    } else {
        must_wait(&a);
        wait_for(&sleeps_begun, 1);
        CHECK(a.got == 0 && a.t.vc_held == 0);  /* it waits beside a free core, as before */
        vc_release(&h0);                        /* the waker: one of its own cores let go */
        wait_for(&a.got, 1);                    /* (and the wake-up is not lost) */
        CHECK(a.got == 1);
        vc_acquire(&h2);                        /* (core 2 was free all along) */
        CHECK(h2.vc_held == 3);
        vc_release(&h2);
    }
    done(&a, ta);
    if (wide) vc_release(&h0);
    vc_release(&h1);
    end_state();

    /* 2. all three held; the waiter of cores 0 and 1 is asleep; core 2 is let go, then core 0 */
    vc_acquire(&h0), vc_acquire(&h1), vc_acquire(&h2);
    int slept = __atomic_load_n(&sleeps_begun, __ATOMIC_ACQUIRE);
    taker(&a, "two cores", 20, 3, -2, &ta);
    must_wait(&a);
    wait_for(&sleeps_begun, slept + 1);
    vc_release(&h2);                            /* (the grant is made inside the release) */
    if (wide) {
        wait_for(&a.got, 1);
        CHECK(a.got == 3);                      /* granted the core outside its mask */
    } else {
        CHECK(__atomic_load_n(&a.t.vc_held, __ATOMIC_ACQUIRE) == 0 && a.t.vc_queued == 1);   /* not its core: it goes on waiting */
        vc_release(&h0);
        wait_for(&a.got, 1);
        CHECK(a.got == 1);
    }
    done(&a, ta);
    if (wide) vc_release(&h0);
    vc_release(&h1);
    end_state();

    /* 3. core 0 held, cores 1 and 2 free: a one-core thread and a thread with no mask wait for core 0, the switch or not */
    vc_acquire(&h0);
    slept = __atomic_load_n(&sleeps_begun, __ATOMIC_ACQUIRE);
    taker(&b, "one core", 20, 1, -2, &tb);
    must_wait(&b);
    clock_step(1000);                           /* (the one-core thread has waited longer) */
    taker(&n, "no mask", 20, 0, 0, &tn);
    must_wait(&n);
    wait_for(&sleeps_begun, slept + 2);
    CHECK(b.got == 0 && n.got == 0);
    AcquireSRWLockExclusive(&vc_lock);
    CHECK(vc_owner[1] == NULL && vc_owner[2] == NULL);   /* (two cores stood free the whole time) */
    ReleaseSRWLockExclusive(&vc_lock);
    vc_release(&h0);                            /* the waker: core 0 goes to the one that waited longest */
    wait_for(&b.got, 1);
    CHECK(b.got == 1 && n.got == 0);
    done(&b, tb);                               /* and then to the other */
    wait_for(&n.got, 1);
    CHECK(n.got == 1);
    done(&n, tn);
    end_state();
}

/* the storm: as vcore_spin_test.c's, with masks of one, two and three cores */
static long outside;   /* (holds of a core outside the thread's mask) */
static void *wide_thread(void *arg) {
    Worker *w = (Worker *)arg;
    HosThread *t = &w->t;
    __atomic_add_fetch(&storm_ready, 1, __ATOMIC_ACQ_REL);
    while (__atomic_load_n(&storm_ready, __ATOMIC_ACQUIRE) < 8) sched_yield();
    vc_acquire(t);
    for (int i = 0; i < w->iters && !__atomic_load_n(&failures, __ATOMIC_RELAXED); i++) {
        hold(t);
        if (t->vc_held && !(t->core_mask >> (t->vc_held - 1) & 1)) {
            if (__builtin_popcountll(t->core_mask) == 1) FAIL("%s, a one-core thread, ran on core %d", t->name, t->vc_held - 1);
            __atomic_add_fetch(&outside, 1, __ATOMIC_RELAXED);
        }
        const unsigned r = rnd(&w->seed) % 100;
        if (r < 50) {
            if (t->vc_kick) vc_yield(t, t->vc_kick == 1);
        } else if (r < 65) {
            vc_yield(t, 0);
        } else {
            vc_release(t);
            if (r < 80) sched_yield();
            else if (r < 90)
                for (unsigned k = rnd(&w->seed) % 2000; k; k--) _mm_pause();
            vc_acquire(t);
        }
        if (!t->vc_held) FAIL("%s came back without a core", t->name);
    }
    vc_release(t);
    return NULL;
}
static void wide_storm(int wide) {
    static Worker w[8];
    static const int prio[8] = {10, 10, 16, 16, 16, 28, 28, 28};
    static const uint64_t mask[8] = {3, 1, 6, 2, 4, 5, 3, 7};
    pthread_t th[8];
    for (int i = 0; i < 8; i++) {
        char name[16];
        snprintf(name, sizeof name, "w%d", i);
        thread_init(&w[i].t, name, prio[i], mask[i]);
        w[i].iters = 25000;
        w[i].seed = 4321u + (unsigned)i * 7919u;
        pthread_create(&th[i], NULL, wide_thread, &w[i]);
    }
    for (int i = 0; i < 8; i++) pthread_join(th[i], NULL);
    for (int i = 0; i < 8; i++) CHECK(!w[i].t.vc_held && !w[i].t.vc_queued);
    end_state();
    if (!wide) CHECK(outside == 0);   /* without the switch: only ever a core of its mask */
    AcquireSRWLockExclusive(&vc_lock);
    printf("SEEN: %lld waits, %ld holds of a core outside the mask\n", (long long)vc_st.waits, outside);
    ReleaseSRWLockExclusive(&vc_lock);
}
int main(int argc, char **argv) {
    const char *c = argc > 1 ? argv[1] : "";
    const int wide = getenv("HOS_VCORE_WIDE") && atoi(getenv("HOS_VCORE_WIDE")) != 0;
    {
        pthread_t dog;
        pthread_create(&dog, NULL, watchdog, NULL);
        pthread_detach(dog);
    }
    if (!strcmp(c, "script")) script(wide);
    else if (!strcmp(c, "storm")) wide_storm(wide);
    else FAIL("unknown case %s", c);
    if (failures) return 1;
    printf("PASS %s\n", c);
    return 0;
}
'''

RULE = "    if (wide && __builtin_popcount(m) > 1) return all;\n"
# (each: what the broken rule widens, what replaces the rule's line)
MUTANTS = [
    ("a one-core mask", "    if (wide && __builtin_popcount(m) > 0) return all;\n"),
    ("a thread with no mask", "    if (wide && __builtin_popcount(m) != 1) return all;\n"),
]


def read_source(thread, cores, dev):
    allowed = block(cores, "static unsigned vc_allowed(HosThread *t) {")
    read = 'if (wide < 0) wide = getenv("HOS_VCORE_WIDE") && atoi(getenv("HOS_VCORE_WIDE")) != 0;'
    if "static int wide = -1;" not in allowed or read not in allowed:
        fail("vc_allowed does not read HOS_VCORE_WIDE once, off unless it is a number other than 0")
    if not allowed.index("if (any) return all;") < allowed.index("unsigned m = (unsigned)(t->core_mask & all);") < allowed.index(RULE) \
            < allowed.index("if (!m) m = 1u << hos_thread_core(t);"):
        fail("vc_allowed: the widening is not of the game's own mask, before a thread with no mask is given its core")
    hle = block(thread, "HLE(_ZN2nn2os17SetThreadCoreMaskEPNS0_10ThreadTypeEim) {")
    if "core_mask_note(t, (int)ARG(1), ARG(2));" not in hle:
        fail("SetThreadCoreMask no longer notes what the game asks for")
    note = block(thread, "static void core_mask_note(HosThread *t, int ideal, uint64_t mask) {")
    if "if (named < 2 && !every && !hos_trace) return;" not in note or 'hos_log("vcores: %s (priority %d) asks for ideal core %d' not in note:
        fail("core_mask_note does not log a mask of two or more cores always")
    if "| `HOS_VCORE_WIDE=1` |" not in dev:
        fail("docs/development.md: HOS_VCORE_WIDE is not in the switches table")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    thread = (ROOT / "host/hos_thread.c").read_text(encoding="utf-8")
    dev = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    try:
        cores = thread[thread.index("static SRWLOCK vc_lock = SRWLOCK_INIT;"):thread.index("int hos_vcore_away(void) {")]
        read_source(thread, cores, dev)
        spin = (ROOT / "tests/vcore_spin_test.c").read_text(encoding="utf-8")
        stand_ins = spin[:spin.index("/* ---- the scripted hand-off")]   # (the stand-ins, the helpers, hold() and the storm's pieces)
    except ValueError as e:
        fail("a text this test reads is not there (%s)" % e)
    if cores.count(RULE) != 1:
        fail("the rule's line is not in the virtual cores once")
    compiler = shutil.which(args.cc)
    if not compiler:
        raise SystemExit("C compiler not found: " + args.cc)
    env = {k: v for k, v in os.environ.items() if not k.startswith("HOS_")}
    env.update(HOS_VCORE_ESCAPE_US=FAR, HOS_VCORE_ESCAPE_EQ_US=FAR)
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="vcore-wide-") as temporary:
        top = Path(temporary)

        def build(name, block_text):
            folder = top / name
            folder.mkdir()
            (folder / "vcore_block.inc").write_text(block_text, encoding="utf-8")
            (folder / "wide.c").write_text(stand_ins + CASES, encoding="utf-8")
            exe = folder / "wide.exe"
            built = subprocess.run([compiler, "-std=gnu17", "-O2", "-Wall", "-Werror", "-Wno-unused-function", "-Wno-unused-variable",
                                    "-Wno-unknown-warning-option", "-Wno-unused-but-set-variable", "-Wno-unused-but-set-global",
                                    "-pthread", "-I" + str(folder), str(folder / "wide.c"), "-o", str(exe)],
                                   capture_output=True, text=True, timeout=180)
            if built.returncode:
                print(built.stdout + built.stderr)
                fail("the fixture did not build (%s)" % name)
            return exe

        def run(exe, case, switches):
            return subprocess.run([str(exe), case], env=dict(env, **switches), capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=120, creationflags=flags)

        exe = build("as-made", cores)
        for what, switches in (("not set", {}), ("0", {"HOS_VCORE_WIDE": "0"}), ("1", {"HOS_VCORE_WIDE": "1"})):
            done = run(exe, "script", dict(switches, HOS_VCORE_SLICE_US=FAR, HOS_VCORE_SPIN_US="0"))
            if done.returncode or "PASS script" not in done.stdout:
                print(done.stdout[-4000:])
                fail("the scripted cases, HOS_VCORE_WIDE %s" % what)
            print("PASS script, HOS_VCORE_WIDE %s: %s" % (what, "a two-core thread takes any free core, one-core and no-mask threads stay"
                                                      if what == "1" else "every thread waits for a core of its own, as before"))
        for what, switches in (("not set", {}), ("1", {"HOS_VCORE_WIDE": "1"})):
            done = run(exe, "storm", switches)
            seen = [line for line in done.stdout.splitlines() if line.startswith("SEEN: ")]
            if done.returncode or "PASS storm" not in done.stdout or not seen:
                print(done.stdout[-4000:])
                fail("the storm, HOS_VCORE_WIDE %s" % what)
            print("PASS storm, HOS_VCORE_WIDE %s: no core run by two threads, none without a core; %s" % (what, seen[0][6:]))
        for i, (what, new) in enumerate(MUTANTS):
            done = run(build("mutant%d" % i, cores.replace(RULE, new)), "script", {"HOS_VCORE_WIDE": "1", "HOS_VCORE_SLICE_US": FAR, "HOS_VCORE_SPIN_US": "0"})
            if done.returncode == 0:
                fail("a rule that widens %s too still passed the script" % what)
            print("PASS mutation: a rule that widens %s too fails the script" % what)
    print("PASS: HOS_VCORE_WIDE=1 widens only masks of two or more cores, no core is ever run by two threads, and it is off unless set")


if __name__ == "__main__":
    main()
