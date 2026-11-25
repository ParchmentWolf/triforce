"""A guest thread that escaped a long wait for a virtual core (host/hos_thread.c vc_acquire: it runs without one) takes a
core again after its next block, like every other thread (no game).

Before, hos_vcore_away answered 0 for the escaped thread (it held no core to give up), so its `if (away) hos_vcore_back();`
never ran and the thread kept running with no core, under the core number of a core another thread held, for the rest of
its life: beside a thread held to that same one core too, which the one-core rule of 11-23 (no escape at 250 ms behind a
holder of better priority, HOS_VCORE_PIN_ESCAPE_MS) keeps apart only while the thread still waits. A hos_vcore_back
without its away (a thread's start) ends an escape too: a flag left up while the thread holds a core would make an inner
block's away answer 1 and take a core in the middle of the outer block.

The real HosThread, hos_thread_core, the whole virtual-core block (vc_lock to vc_yield), hos_vcore_away, hos_vcore_back and
hos_cv_sleep are cut out of host/hos_thread.c unchanged and compiled with a single-threaded harness: a clock the waits
move (1 ms a look, as the real wait times out), locks that do nothing, a log that counts the escapes. The cases:

- two holders of equal priority that never give their cores up: the waiter escapes at HOS_VCORE_ESCAPE_US (250 ms); after
  its next block (hos_vcore_away / hos_vcore_back, and the same through hos_cv_sleep) it holds the core that came free,
  answers that core's number, and gives it up at the block after as every holder does;
- a block inside a block: only the outermost one takes the core again, none is taken inside it;
- a back without its away on an escaped thread: it takes the free core, and a block inside a block after it takes none in
  the middle of the outer one; the same back while both cores are held escapes again, and that escape ends at the next
  block too;
- a thread that holds no core and never escaped takes none after a block, as before;
- the one-core rule with it: a waiter held to one core behind a holder of better priority there does not escape at
  250 ms; it does at the backstop (5 s), and after its next block it waits for that core again instead of running on
  beside the holder (the wait is a second 5 s here, where the holder never lets go), and takes it once it is free;
- a request whose interrupt was lost: a better waiter asks a holder, whose interrupt goes to its thread's context just as
  it switches to a fiber. The request stays pending, counted once, and the waiter's next look publishes the interrupt
  again, in the context the holder runs now; the holder's checkpoint there then hands the core over, with no escape.

    python -I -B tests/test_vcore_escape.py [--cc clang]
"""
import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "clang"]

ROOT = Path(__file__).resolve().parents[1]


def fail(message):
    raise SystemExit("FAIL: " + message)


def block(source, marker):
    start = source.index(marker)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end] + (";" if source[end:end + 1] == ";" else "")


HARNESS = r"""
#include <emmintrin.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef void *HANDLE;
typedef int BOOL;
typedef unsigned long DWORD;
typedef struct { void *p; } SRWLOCK, *PSRWLOCK;
typedef struct { void *p; } CONDITION_VARIABLE, *PCONDITION_VARIABLE;
#define SRWLOCK_INIT {0}
#define HOS_TLS_SLOTS 64
typedef struct { uint64_t x[32]; volatile int poll; } Ctx;
typedef struct { unsigned long dwNumberOfProcessors; } SYSTEM_INFO;
static void GetSystemInfo(SYSTEM_INFO *si) { si->dwNumberOfProcessors = 8; }   /* (8: no waiter spins, vc_spin_most) */
static int64_t now_ns = 1000000000;
static int64_t hos_now_ns(void) { return now_ns; }
enum { HOS_CHAIN_WAIT = 1, HOS_CHAIN_WOKE, HOS_CHAIN_SIGNAL, HOS_CHAIN_SLEEP, HOS_CHAIN_AWAKE, HOS_CHAIN_PRESENT };   /* ((Triforce) HOS_CHAIN off) */
#define HOS_CHAIN(kind, key) ((void)(kind), (void)(key))
static int escapes_logged;
static void hos_log(const char *fmt, ...) { if (strstr(fmt, "ran without a core")) escapes_logged++; }
static int hos_cores(void) { return 2; }
static int sleeps;
static void (*on_sleep)(void);   /* (what the other threads do during one look: only a case sets it) */
/* (no other thread runs here, except what on_sleep does: a wait for a core only lets the clock go on, 1 ms a look, as the
   real one times out) */
static BOOL SleepConditionVariableSRW(PCONDITION_VARIABLE cv, PSRWLOCK lk, DWORD ms, unsigned long f) {
    (void)cv, (void)lk, (void)f;
    now_ns += (int64_t)(ms ? ms : 1) * 1000000;
    sleeps++;
    if (on_sleep) on_sleep();
    return 1;
}
static void WakeConditionVariable(PCONDITION_VARIABLE cv) { (void)cv; }
static void AcquireSRWLockExclusive(PSRWLOCK l) { (void)l; }
static void ReleaseSRWLockExclusive(PSRWLOCK l) { (void)l; }
static uint64_t sim_cpu_mask;
static int hos_sim_cpu_count(uint64_t mask) { return __builtin_popcountll(mask); }
@STRUCT@
typedef struct HosThread HosThread;
static HosThread *cur;
int hos_vcores_on(void);
@CORE@
@VCORES@
@AWAY@
@BACK@
@CV_SLEEP@
static int bad;
static void check(int ok, const char *what) { if (!ok) { printf("FAIL: %s\n", what); bad = 1; } }
static void thread(HosThread *t, const char *name, int prio, uint64_t mask) {
    memset(t, 0, sizeof *t);
    snprintf(t->name, sizeof t->name, "%s", name);
    t->priority = prio, t->core_mask = mask, t->ideal_core = -2;
}
static void fresh(void) { memset(vc_owner, 0, sizeof vc_owner), vc_nq = 0; }
/* a request whose interrupt is lost: the holder switches to a fiber just as it is asked, then polls in the fiber's context */
static HosThread lost_holder, lost_asker;
static Ctx fiber;
static int lost, published_again, handed;
static void lose_then_serve(void) {
    if (!lost) {   /* the first look: the request is made, its interrupt in the thread's own context */
        check(lost_holder.vc_kick == 1 && lost_holder.ctx.poll == 1, "a better waiter asks the holder and publishes its interrupt");
        lost_holder.ctx.poll = 0, lost_holder.run_ctx = &fiber, lost = 1;   /* (in a context the holder no longer runs) */
        return;
    }
    if (fiber.poll && !handed) {   /* published again, where the holder runs now: its checkpoint there */
        published_again = 1, fiber.poll = 0;
        check(lost_holder.vc_kick == 1, "the request was still pending when its interrupt was published again");
        vc_release(&lost_holder), handed = 1;   /* (vc_yield's first half: the core to the waiter that asked) */
    }
}
/* the holders of both cores never give them up while t waits: t escapes; then one holder blocks */
static void escape(HosThread *t, HosThread *h0, HosThread *h1) {
    cur = h0; hos_vcore_back();
    cur = h1; hos_vcore_back();
    check(h0->vc_held && h1->vc_held, "the two holders hold the two cores");
    const int before = escapes_logged, slept = sleeps;
    cur = t; hos_vcore_back();
    check(escapes_logged == before + 1 && !t->vc_held, "the waiter escaped (ran without a core)");
    check(sleeps - slept > 240 && sleeps - slept < 270, "at HOS_VCORE_ESCAPE_US, 250 ms");
    cur = h1; check(hos_vcore_away() == 1, "a holder gives its core up for a block");
    cur = t;
}
int main(void) {
    static HosThread h0, h1, t, u, b, w;
    thread(&h0, "holder0", 16, 1), thread(&h1, "holder1", 16, 2), thread(&t, "waiter", 16, 3);

    escape(&t, &h0, &h1);   /* a block of the escaped thread (hos_sleep_ns, hos_thread_wait, the NVN waits, ...) */
    const int away = hos_vcore_away();
    check(away == 1, "hos_vcore_away tells an escaped thread to take a core after its block");
    if (away) hos_vcore_back();
    check(t.vc_held == 2, "after its block the escaped thread holds the free core");
    check(hos_thread_core(&t) == 1 && hos_thread_core(&t) != hos_thread_core(&h0),
          "and reports that core's number, not the one the other holder runs on");
    check(hos_vcore_away() == 1 && !t.vc_held, "and gives it up at its next block as every holder does");

    thread(&t, "waiter", 16, 3), thread(&h0, "holder0", 16, 1), thread(&h1, "holder1", 16, 2);
    fresh();
    escape(&t, &h0, &h1);   /* the same through hos_cv_sleep (the nn::os waits) */
    SRWLOCK lk = SRWLOCK_INIT;
    CONDITION_VARIABLE cv = {0};
    hos_cv_sleep(&cv, &lk, 1);
    check(t.vc_held == 2, "after a hos_cv_sleep the escaped thread holds the free core");

    thread(&t, "waiter", 16, 3), thread(&h0, "holder0", 16, 1), thread(&h1, "holder1", 16, 2);
    fresh();
    escape(&t, &h0, &h1);   /* a block inside a block: only the outer one takes the core again */
    const int outer = hos_vcore_away();
    const int inner = hos_vcore_away();
    check(outer == 1 && inner == 0, "only the outermost block of an escaped thread takes a core after it");
    if (inner) hos_vcore_back();
    check(!t.vc_held, "no core is taken inside the outer block");
    if (outer) hos_vcore_back();
    check(t.vc_held == 2, "the core is taken after the outer block");

    thread(&t, "waiter", 16, 3), thread(&h0, "holder0", 16, 1), thread(&h1, "holder1", 16, 2);
    fresh();
    escape(&t, &h0, &h1);   /* a back without its away (as at a thread's start) takes the core: the escape is over */
    hos_vcore_back();
    check(t.vc_held == 2, "a back without an away gives the escaped thread the free core");
    const int outer2 = hos_vcore_away();
    const int inner2 = hos_vcore_away();
    check(outer2 == 1 && inner2 == 0, "after a back without an away, a block inside a block takes no core after it");
    if (inner2) hos_vcore_back();
    check(!t.vc_held, "no core is taken inside the outer block after a back without an away");
    if (outer2) hos_vcore_back();
    check(t.vc_held == 2, "the core is taken after the outer block");

    thread(&t, "waiter", 16, 3), thread(&h0, "holder0", 16, 1), thread(&h1, "holder1", 16, 2);
    fresh();
    escape(&t, &h0, &h1);   /* a back without its away that escapes again: that escape ends at the next block */
    cur = &h1; hos_vcore_back();
    cur = &t;
    const int again0 = escapes_logged;
    hos_vcore_back();
    check(escapes_logged == again0 + 1 && !t.vc_held, "a back without an away escapes again while both cores are held");
    check(hos_vcore_away() == 1, "and the thread still takes a core after its next block");

    thread(&u, "never-held", 16, 3);   /* a thread that holds no core and never escaped: nothing to take after a block */
    cur = &u;
    check(hos_vcore_away() == 0, "a thread that never escaped and holds no core takes none after a block");

    /* the one-core rule (11-23) with it: w, held to core 1, behind b, of better priority and held to core 1 too */
    fresh();
    thread(&b, "better", 16, 2), thread(&w, "pinned", 28, 2);
    cur = &b; hos_vcore_back();
    check(b.vc_held == 2, "the better thread holds core 1");
    int before = escapes_logged, slept = sleeps;
    cur = &w; hos_vcore_back();
    check(escapes_logged == before + 1 && !w.vc_held, "the one-core waiter escaped at last");
    check(sleeps - slept > 4990 && sleeps - slept < 5020, "at the backstop, 5 s, not at 250 ms");
    before = escapes_logged, slept = sleeps;
    int again = hos_vcore_away();   /* its next block, the holder still there: it waits for its core again */
    check(again == 1, "the escaped one-core thread is to take its core after its block");
    if (again) hos_vcore_back();
    check(sleeps - slept > 4990 && !w.vc_held && escapes_logged == before + 1,
          "behind the same holder it waits again (it did not run on beside it), to the backstop");
    cur = &b; check(hos_vcore_away() == 1, "the better thread blocks");
    cur = &w;
    slept = sleeps;
    again = hos_vcore_away();
    if (again) hos_vcore_back();
    check(again == 1 && w.vc_held == 2 && sleeps == slept, "and after its next block the thread holds its own core, at once");
    cur = &b; slept = sleeps, before = escapes_logged;
    hos_vcore_back();   /* the better thread wants its core back: w (worse) is asked, never answers here, so b escapes */
    check(escapes_logged == before + 1 && sleeps - slept < 270, "a better waiter behind a worse holder escapes at 250 ms, as before");

    /* a request whose interrupt was lost at a fiber switch is published again at the waiter's next look */
    fresh();
    thread(&lost_holder, "holder", 20, 1), thread(&lost_asker, "asker", 10, 1);
    cur = &lost_holder; hos_vcore_back();
    before = escapes_logged, slept = sleeps;
    on_sleep = lose_then_serve;
    cur = &lost_asker; hos_vcore_back();
    on_sleep = NULL;
    check(published_again && handed, "the interrupt is published again, in the context the holder runs now");
    check(lost_asker.vc_held == 1 && escapes_logged == before, "and the waiter gets the core from the holder's checkpoint, with no escape");
    check(sleeps - slept == 2, "at its second look, not at the 250 ms escape");
    if (!bad) puts("ok");
    return bad;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    parser.add_argument("--source", type=Path, default=ROOT / "host/hos_thread.c")
    args = parser.parse_args()
    src = args.source.read_text(encoding="utf-8")
    try:
        start = src.index("static SRWLOCK vc_lock = SRWLOCK_INIT;")
        fixture = (HARNESS.replace("@STRUCT@", block(src, "struct HosThread {"))
                   .replace("@CORE@", block(src, "int hos_thread_core(HosThread *t) {"))
                   .replace("@VCORES@", src[start:src.index("int hos_vcore_away(void) {", start)])
                   .replace("@AWAY@", block(src, "int hos_vcore_away(void) {"))
                   .replace("@BACK@", block(src, "void hos_vcore_back(void) {"))
                   .replace("@CV_SLEEP@", block(src, "int hos_cv_sleep(void *cv, void *lk, unsigned ms) {")))
    except ValueError as e:
        fail("a text this test reads is not there (%s)" % e)
    compiler = shutil.which(args.cc)
    if not compiler:
        raise SystemExit("C compiler not found: " + args.cc)
    env = {k: v for k, v in os.environ.items() if not k.startswith("HOS_")}
    env["HOS_VCORE_SPIN_US"] = "0"   # (no spin: the harness's clock moves only in a sleep)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="vcore-escape-") as temporary:
        folder = Path(temporary)
        (folder / "fixture.c").write_text(fixture, encoding="utf-8")
        exe = folder / ("fixture.exe" if os.name == "nt" else "fixture")
        built = subprocess.run([compiler, "-std=gnu17", "-O1", "-w", str(folder / "fixture.c"), "-o", str(exe)],
                               capture_output=True, text=True, timeout=180)
        if built.returncode:
            print(built.stdout + built.stderr)
            fail("the fixture did not build")
        result = subprocess.run([str(exe)], env=env, capture_output=True, text=True, timeout=60, creationflags=flags)
        print(result.stdout, end="")
        if result.returncode or "ok" not in result.stdout:
            fail("an escaped thread does not take a core again after its block")
    print("PASS: an escape ends at the thread's next block: it takes a core again there, the outermost block only, and a "
          "one-core thread waits for its own core again")


if __name__ == "__main__":
    main()
