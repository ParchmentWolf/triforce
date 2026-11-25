"""The game's YieldThread without the processor's yield, HOS_OS_YIELD=0 (host/hos_thread.c os_yield and the YieldThread
HLE; no game).

(Triforce, 11-22, the performance audit's THREAD-41, after Source A's.) A yield of the game's is answered twice: the
virtual core is handed to a waiting game thread of equal or better priority, and then the processor is given up too
(SwitchToThread, a call into the kernel thousands of times a second). HOS_OS_YIELD=0 drops the second; off unless set.

Two fixtures, both of code cut out of hos_thread.c unchanged:

- os_yield, the HLE and sleep_away over counting stand-ins, a process a case (the switch is read once): not set, 1 and
  any other number both answers, as before; 0 only the virtual core's; 0 with HOS_VCORES=0 both (the processor's yield
  is then the only one); SleepThread(0) keeps both whatever the switch says.
- the wait a yield loop is: the HLE over the real virtual cores (vc_lock to hos_vcore_yield, with tests/
  vcore_spin_test.c's stand-ins for Windows' lock and condition variable) on real threads. A yielder holds the only
  core and yields in a loop until a flag is set; the waker must get that core to set it. With HOS_OS_YIELD=0:
  a waker as good gets the core from the yield itself and one that is better gets it at the yield after its request (no
  wake-up lost: the loop ends, no escape, the processor's yield never called); a waker that is worse is not given the
  core by a yield, with the switch or without it (the console's yield), and runs through the virtual cores' escape as
  before: the switch changes nothing there. And the case the entry warns of, on Windows: the whole process held to one
  logical processor, the waker on a core of its own, so that only the system's time slice can let it run while the
  yielder spins: the loop still ends, with the switch at 0 and at 1, and the time it took is printed (not judged: it is
  the stall to measure in the game).

    python -I -B tests/test_os_yield.py [--cc clang]
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "clang"]

ROOT = Path(__file__).resolve().parents[1]
HLE_MARK = "HLE(_ZN2nn2os11YieldThreadEv) {"


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


COUNTS = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
typedef struct Ctx Ctx;
#define HLE(sym) void imp_##sym(Ctx *c)
static int vcore_yields, os_yields, vcores, aways, backs, slept;
static void hos_vcore_yield(void) { vcore_yields++; }
static int hos_vcores_on(void) { return vcores; }
static int hos_vcore_away(void) { aways++; return 1; }
enum { HOS_CHAIN_WAIT = 1, HOS_CHAIN_WOKE, HOS_CHAIN_SIGNAL, HOS_CHAIN_SLEEP, HOS_CHAIN_AWAKE, HOS_CHAIN_PRESENT };   /* ((Triforce) HOS_CHAIN off) */
#define HOS_CHAIN(kind, key) ((void)(kind), (void)(key))
static void hos_vcore_back(void) { backs++; }
static int SwitchToThread(void) { os_yields++; return 1; }
static void sleep_for(int64_t ns, int guest) { (void)ns, (void)guest; slept++; }
@OS_YIELD@
@HLE@
@SLEEP_AWAY@
int main(int argc, char **argv) {
    vcores = argc > 1 ? atoi(argv[1]) : 1;
    for (int i = 0; i < 5; i++) imp__ZN2nn2os11YieldThreadEv(NULL);
    printf("yield %d %d\n", vcore_yields, os_yields);
    vcore_yields = os_yields = 0;
    sleep_away(0, 1), sleep_away(0, 0);   /* SleepThread(0), the game's and the host's */
    printf("sleep0 %d %d %d\n", vcore_yields, os_yields, slept + aways + backs);
    sleep_away(20000, 1);
    printf("sleep %d %d %d %d\n", slept, aways, backs, os_yields);
    return 0;
}
'''

# (HOS_OS_YIELD, virtual cores on) -> "the virtual core's yields, the processor's" of five YieldThread calls
COUNT_CASES = [
    (None, 1, "5 5"),    # not set: both, as before
    ("1", 1, "5 5"),
    ("2", 1, "5 5"),
    ("", 1, "5 5"),      # (set to nothing: as not set)
    ("0", 1, "5 0"),     # the virtual core's only
    ("0", 0, "5 5"),     # no virtual cores: the processor's yield is the only one, kept
    (None, 0, "5 5"),
]

CASES = r'''
/* ---- (Triforce, THREAD-41) the yield loop over the real virtual cores ---- */
static _Thread_local HosThread *cur;
static int os_yields;
static int SwitchToThread(void) {
    __atomic_add_fetch(&os_yields, 1, __ATOMIC_RELAXED);
    sched_yield();
    return 1;
}
#define HLE(sym) static void imp_##sym(Ctx *c)
@AWAY@
@BACK@
@VYIELD@
@OS_YIELD@
@HLE@

static HosThread yielder, waker;
static int ready, flag, got_core;
static long loops;
static int64_t ready_at, woke_ns;
static int64_t real_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}
/* the waiter of the model: it holds a core and yields until the condition (flag) is true */
static void *yield_loop(void *arg) {
    (void)arg;
    cur = &yielder;
    hos_vcore_back();
    ready_at = real_ns();
    __atomic_store_n(&ready, 1, __ATOMIC_RELEASE);
    while (!__atomic_load_n(&flag, __ATOMIC_ACQUIRE)) {
        imp__ZN2nn2os11YieldThreadEv(NULL);
        loops++;
    }
    hos_vcore_away();
    return NULL;
}
/* the waker: it needs a core to make the condition true */
static void *wake(void *arg) {
    (void)arg;
    cur = &waker;
    wait_for(&ready, 1);
    hos_vcore_back();
    got_core = waker.vc_held;
    __atomic_store_n(&flag, 1, __ATOMIC_RELEASE);
    woke_ns = real_ns() - ready_at;   /* (from the loop's start until its condition is true) */
    hos_vcore_away();
    return NULL;
}
static int64_t count(int64_t *field) {
    AcquireSRWLockExclusive(&vc_lock);
    const int64_t v = *field;
    ReleaseSRWLockExclusive(&vc_lock);
    return v;
}
/* waker_prio against the yielder's 20; waker_mask: 1 the yielder's core, 2 a core of its own */
static void run(int waker_prio, uint64_t waker_mask) {
    cores = 2;
    thread_init(&yielder, "yielder", 20, 1);
    thread_init(&waker, "waker", waker_prio, waker_mask);
    pthread_t a, b;
    pthread_create(&a, NULL, yield_loop, NULL);
    pthread_create(&b, NULL, wake, NULL);
    pthread_join(b, NULL);
    pthread_join(a, NULL);   /* (the loop ended: the wake-up was not lost) */
    CHECK(flag == 1 && loops > 0);
    CHECK(!yielder.vc_held && !waker.vc_held && !yielder.vc_queued && !waker.vc_queued);
}
int main(int argc, char **argv) {
    const char *c = argc > 1 ? argv[1] : "";
    const int os = getenv("HOS_OS_YIELD") ? atoi(getenv("HOS_OS_YIELD")) != 0 : 1;
    {
        pthread_t dog;
        pthread_create(&dog, NULL, watchdog, NULL);
        pthread_detach(dog);
    }
    if (!strcmp(c, "as-good") || !strcmp(c, "better")) {
        run(!strcmp(c, "better") ? 10 : 20, 1);
        CHECK(got_core == 1);                 /* the waker held the yielder's core when it set the flag */
        CHECK(count(&vc_st.yields) >= 1);     /* handed over by a yield */
        CHECK(count(&vc_st.escapes) == 0);    /* never by the escape */
        end_state();
    } else if (!strcmp(c, "worse")) {         /* HOS_VCORE_ESCAPE_EQ_US small: a yield gives way to equal or better only */
        run(30, 1);
        CHECK(got_core == 0);
        CHECK(count(&vc_st.yields) == 0 && count(&vc_st.escapes) == 1);
    } else if (!strcmp(c, "own-core")) {      /* the waker needs no core of the yielder's, only a processor */
        run(20, 2);
        CHECK(got_core == 2 && count(&vc_st.escapes) == 0);
        end_state();
        printf("WOKE %.1f ms after the loop began, %ld yields\n", woke_ns / 1e6, loops);
    } else {
        FAIL("unknown case %s", c);
    }
    if (os) CHECK(__atomic_load_n(&os_yields, __ATOMIC_RELAXED) == loops);   /* as before: the processor given up at every yield */
    else CHECK(__atomic_load_n(&os_yields, __ATOMIC_RELAXED) == 0);          /* HOS_OS_YIELD=0: never */
    if (failures) return 1;
    printf("PASS %s\n", c);
    return 0;
}
'''

FAR = "60000000"   # (60 s: no escape, no time slice, unless a case sets one)
# case -> its switches (each also run with HOS_OS_YIELD=1, as before, where the same must hold)
THREAD_CASES = {
    "as-good": {},
    "better": {},
    "worse": {"HOS_VCORE_ESCAPE_EQ_US": "30000"},
    "own-core": {},
}


def read_source(thread, dev):
    oy = block(thread, "static int os_yield(void) {")
    if 'const char *e = getenv("HOS_OS_YIELD");' not in oy or "on = e && *e ? atoi(e) != 0 : 1;" not in oy or "static int on = -1;" not in oy:
        fail("os_yield is not HOS_OS_YIELD read once, on unless it is 0")
    hle = block(thread, HLE_MARK)
    if "hos_vcore_yield();" not in hle or "if (os_yield() || !hos_vcores_on()) SwitchToThread();" not in hle or \
            hle.index("hos_vcore_yield();") > hle.index("SwitchToThread();"):
        fail("YieldThread does not hand the virtual core over first, or its processor's yield is not behind the switch")
    away = block(thread, "static void sleep_away(int64_t ns, int guest) {")
    if "hos_vcore_yield();\n        SwitchToThread();" not in away or "os_yield" in away:
        fail("SleepThread(0) no longer gives the processor up: only YieldThread is behind the switch")
    if "| `HOS_OS_YIELD=0` |" not in dev:
        fail("docs/development.md: HOS_OS_YIELD is not in the switches table")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    thread = (ROOT / "host/hos_thread.c").read_text(encoding="utf-8")
    dev = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    try:
        read_source(thread, dev)
        pieces = {"@OS_YIELD@": block(thread, "static int os_yield(void) {"), "@HLE@": block(thread, HLE_MARK),
                  "@SLEEP_AWAY@": block(thread, "static void sleep_away(int64_t ns, int guest) {"),
                  "@AWAY@": block(thread, "int hos_vcore_away(void) {"), "@BACK@": block(thread, "void hos_vcore_back(void) {"),
                  "@VYIELD@": block(thread, "void hos_vcore_yield(void) {")}
        cores = thread[thread.index("static SRWLOCK vc_lock = SRWLOCK_INIT;"):thread.index("int hos_vcore_away(void) {")]
        spin = (ROOT / "tests/vcore_spin_test.c").read_text(encoding="utf-8")
        stand_ins = spin[:spin.index("/* ---- storm: many hand-offs")]   # (the lock, the condition variable, the thread, the helpers)
    except ValueError as e:
        fail("a text this test reads is not there (%s)" % e)
    compiler = shutil.which(args.cc)
    if not compiler:
        raise SystemExit("C compiler not found: " + args.cc)
    env = {k: v for k, v in os.environ.items() if not k.startswith("HOS_")}
    with tempfile.TemporaryDirectory(prefix="os-yield-") as temporary:
        folder = Path(temporary)

        def build(name, text, extra=()):
            for mark, piece in pieces.items():
                text = text.replace(mark, piece)
            (folder / (name + ".c")).write_text(text, encoding="utf-8")
            exe = folder / (name + ".exe")
            # (the stand-ins are the spin test's: what its own cases use and these do not is not an error here)
            built = subprocess.run([compiler, "-std=gnu17", "-O2", "-Wall", "-Werror", "-Wno-unused-function", "-Wno-unused-variable",
                                    "-Wno-unused-but-set-variable", "-Wno-unknown-warning-option", "-Wno-unused-but-set-global",
                                    "-I" + str(folder), str(folder / (name + ".c")), "-o", str(exe), *extra],
                                   capture_output=True, text=True, timeout=180)
            if built.returncode:
                print(built.stdout + built.stderr)
                fail("the %s fixture did not build" % name)
            return exe

        counts = build("counts", COUNTS)
        for value, vcores, want in COUNT_CASES:
            case_env = dict(env) if value is None else dict(env, HOS_OS_YIELD=value)
            out = subprocess.run([str(counts), str(vcores)], env=case_env, capture_output=True, text=True, timeout=60).stdout.split("\n")
            what = "HOS_OS_YIELD %s, virtual cores %s" % ("not set" if value is None else repr(value), "on" if vcores else "off")
            if out[0] != "yield " + want:
                fail("%s: five yields gave %r (the virtual core's, the processor's), not %r" % (what, out[0], want))
            if out[1] != "sleep0 2 2 0":
                fail("%s: SleepThread(0) twice gave %r, not both yields each and no sleep" % (what, out[1]))
            if out[2] != "sleep 1 1 1 2":
                fail("%s: a 20 us sleep gave %r, not one sleep with the core given up and taken back" % (what, out[2]))
        print("PASS: five yields, by the switch and the virtual cores: %s" %
              ", ".join("%s/%s: %s" % ("unset" if v is None else repr(v), "vcores" if c else "no vcores", w) for v, c, w in COUNT_CASES))

        (folder / "vcore_block.inc").write_text(cores, encoding="utf-8")
        cases = build("cases", stand_ins + CASES, ["-pthread"])
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        for case, extra in THREAD_CASES.items():
            for value in ("0", "1"):
                case_env = dict(env, HOS_VCORE_ESCAPE_US=FAR, HOS_VCORE_ESCAPE_EQ_US=FAR, HOS_VCORE_SLICE_US=FAR, HOS_VCORE_SPIN_US="0",
                                HOS_OS_YIELD=value)
                case_env.update(extra)
                done = subprocess.run([str(cases), case], env=case_env, capture_output=True, text=True, timeout=120, creationflags=flags)
                if done.returncode or "PASS " + case not in done.stdout:
                    print(done.stdout[-3000:])
                    fail("the yield loop, a waker %s, HOS_OS_YIELD=%s" % (case, value))
            print("PASS: a yield loop and a waker %s: the loop ends with HOS_OS_YIELD=0 and =1" % case)
        if os.name == "nt":
            # the whole process on one logical processor: only the system's time slice lets the waker run while the yielder spins
            for value in ("1", "0"):
                case_env = dict(env, HOS_VCORE_ESCAPE_US=FAR, HOS_VCORE_ESCAPE_EQ_US=FAR, HOS_VCORE_SLICE_US=FAR, HOS_VCORE_SPIN_US="0",
                                HOS_OS_YIELD=value)
                done = subprocess.run(["cmd", "/c", "start", "", "/b", "/wait", "/affinity", "1", str(cases), "own-core"], env=case_env,
                                      capture_output=True, text=True, timeout=120, creationflags=flags)
                woke = [line for line in done.stdout.splitlines() if line.startswith("WOKE ")]
                if "PASS own-core" not in done.stdout or not woke:
                    print(done.stdout[-3000:] + done.stderr[-1000:])
                    fail("on one logical processor the yield loop did not end, HOS_OS_YIELD=%s" % value)
                print("one logical processor, HOS_OS_YIELD=%s: the waker set the flag %s" % (value, woke[0][5:]))
        else:
            print("SKIP: the one-processor case holds the process with Windows' start /affinity")
    print("PASS: YieldThread keeps both yields unless HOS_OS_YIELD=0, and a yield loop's waker is never lost without the processor's")


if __name__ == "__main__":
    main()
