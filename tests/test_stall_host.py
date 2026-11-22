"""The host's part of a long frame, a line beside the renderer's stall line (host/stall_host.h, host/mkw_glue.c
hos_stall_host_presented; no game).

(Triforce, 11-22, the performance audit's OS-51, after Source B's.) The stall line splits a frame of 50 ms or more on the
replay's side and calls the rest outside the replay and the present. The host counts where it spends that rest (file
reads, writes, flushes, save commits, discards, zero-fills, decommits, give-back passes, the waits for a virtual core),
and a present that comes the stall line's threshold or more after the last one logs it with the process's page faults
and CPU time.

- stall_host.h compiled and run: the threshold from the two switches (RX_VK_STALL_LOG's, 50 ms unset, off at 0;
  HOS_STALL_HOST=0 off); a cause's adds and its take, also from eight threads at once (every add counted, the longest the
  longest); the line for a frame with causes, for one with none ("none of the host's causes": ruled out), with lines
  left out before it; the bound (3 a second, 1500 a session).
- hos_stall_host_presented cut out of mkw_glue.c and run on a scripted clock: no line for a short frame, and what a
  short frame counted is not carried into a later long one; a long frame's line has what was counted since the present
  before it, the page faults and CPU time of that frame only (Windows' 32-bit fault count wrapping included) and the
  core waits; a run of long frames is bounded; with HOS_STALL_HOST=0 or RX_VK_STALL_LOG=0 nothing is counted, nothing
  is asked of the system and nothing is logged; a threshold of 100 ms is kept.
- on Windows, process_counters and process_work compiled against Windows itself and run: the fault count rises when
  fresh memory is touched, the CPU time when the processor is used.
- the sources read: each counted call is between its begin and end (the read's and the discard's end before the
  virtual core is taken back, so the wait for the core is counted once, as a core wait), the virtual cores count their
  waits, the present makes the look, and the switch is in the switches table.

    python -I -B tests/test_stall_host.py [--cc clang]
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
HOST = ROOT / "host"


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


HEADER = r'''
#include <pthread.h>
#include <string.h>
#include "stall_host.h"
static int fails;
#define CHECK(x) do { if (!(x)) { printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
StallHostCause hos_stall_host[STALL_HOST_CAUSES];
int64_t hos_stall_host_us = -1;
int64_t hos_now_ns(void) { return 1; }
static StallHostCause shared;
static void *adder(void *arg) {
    const int64_t me = (int64_t)(intptr_t)arg;
    for (int i = 1; i <= 20000; i++) stall_host_add(&shared, i + me, 4096);
    return NULL;
}
static void same(const char *got, const char *want) {
    if (strcmp(got, want)) { printf("FAIL: the line is\n  %s\nnot\n  %s\n", got, want); fails++; }
}
int main(void) {
    /* the threshold */
    CHECK(stall_host_threshold_us(NULL, NULL) == 50000);        /* the stall line's 50 ms */
    CHECK(stall_host_threshold_us("100", NULL) == 100000 && stall_host_threshold_us("12.5", NULL) == 12500);
    CHECK(stall_host_threshold_us("0", NULL) == 0);             /* no stall line: none of this */
    CHECK(stall_host_threshold_us("abc", NULL) == 0 && stall_host_threshold_us("-5", NULL) == 0);   /* (as the renderer reads it) */
    CHECK(stall_host_threshold_us(NULL, "0") == 0 && stall_host_threshold_us("80", "0") == 0);     /* HOS_STALL_HOST=0 */
    CHECK(stall_host_threshold_us(NULL, "1") == 50000 && stall_host_threshold_us("80", "1") == 80000);
    /* a cause */
    StallHostCause c = {0, 0, 0, 0};
    stall_host_add(&c, 3000000, 1 << 20), stall_host_add(&c, 41000000, 11 << 20), stall_host_add(&c, 500000, 0);
    stall_host_add(&c, -7, 0);   /* (a clock that went back counts as no time) */
    CHECK(c.ns == 44500000 && c.count == 4 && c.bytes == (12 << 20) && c.longest == 41000000);
    StallHostCause t = stall_host_take(&c);
    CHECK(t.ns == 44500000 && t.count == 4 && t.bytes == (12 << 20) && t.longest == 41000000);
    CHECK(c.ns == 0 && c.count == 0 && c.bytes == 0 && c.longest == 0);
    t = stall_host_take(&c);
    CHECK(t.count == 0 && t.ns == 0);
    /* eight threads adding at once: nothing lost, the longest is the longest */
    pthread_t th[8];
    for (intptr_t i = 0; i < 8; i++) pthread_create(&th[i], NULL, adder, (void *)(i * 100000));
    for (int i = 0; i < 8; i++) pthread_join(th[i], NULL);
    CHECK(shared.count == 8 * 20000 && shared.bytes == 8LL * 20000 * 4096);
    CHECK(shared.ns == 8LL * (20000LL * 20001 / 2) + 20000LL * 100000 * (0 + 1 + 2 + 3 + 4 + 5 + 6 + 7));
    CHECK(shared.longest == 20000 + 700000);
    /* the line */
    char line[1024];
    StallHostFrame f;
    memset(&f, 0, sizeof f);
    f.frame = 4812, f.gap_ns = 143200000;
    f.cause[STALL_HOST_READ] = (StallHostCause){52000000, 3, 12 << 20, 41000000};
    f.cause[STALL_HOST_FLUSH] = (StallHostCause){18000000, 1, 0, 18000000};
    f.cause[STALL_HOST_DISCARD] = (StallHostCause){9000000, 2, 180 << 20, 6100000};
    f.cause[STALL_HOST_CORE_WAIT] = (StallHostCause){64000000, 212, 0, 31000000};
    f.page_faults = 41000, f.kernel_ns = 38000000, f.user_ns = 120000000;
    CHECK(stall_host_line(&f, line, sizeof line) == (int)strlen(line));
    same(line, "vi: stall, the host's part: frame 4812, 143.2 ms: file reads 3 (12.0 MB, 52.0 ms, longest 41.0), flushes 1 (18.0 ms, "
               "longest 18.0); discards 2 (180.0 MB, 9.0 ms, longest 6.1); core waits 64.0 ms (212, longest 31.0); 41000 page faults; "
               "kernel 38.0 ms, user 120.0");
    memset(&f, 0, sizeof f);
    f.frame = 7, f.gap_ns = 61000000, f.page_faults = 12, f.kernel_ns = 1000000, f.user_ns = 59500000, f.held = 2;
    stall_host_line(&f, line, sizeof line);
    same(line, "vi: stall, the host's part: frame 7, 61.0 ms: none of the host's causes; 12 page faults; kernel 1.0 ms, user 59.5 "
               "(2 such lines left out before this one)");
    memset(&f, 0, sizeof f);
    f.frame = 9, f.gap_ns = 250000000;
    f.cause[STALL_HOST_WRITE] = (StallHostCause){2000000, 1, 1 << 19, 2000000};
    f.cause[STALL_HOST_COMMIT] = (StallHostCause){30000000, 1, 0, 30000000};
    f.cause[STALL_HOST_ZERO] = (StallHostCause){4000000, 1, 64 << 20, 4000000};
    f.cause[STALL_HOST_DECOMMIT] = (StallHostCause){1000000, 2, 2 << 20, 700000};
    f.cause[STALL_HOST_GIVE_BACK] = (StallHostCause){5000000, 1, 16 << 20, 5000000};
    stall_host_line(&f, line, sizeof line);
    same(line, "vi: stall, the host's part: frame 9, 250.0 ms: file writes 1 (0.5 MB, 2.0 ms, longest 2.0), save commits 1 (30.0 ms, "
               "longest 30.0), zero-fills 1 (64.0 MB, 4.0 ms, longest 4.0), decommits 2 (2.0 MB, 1.0 ms, longest 0.7), give-backs 1 "
               "(16.0 MB, 5.0 ms, longest 5.0); 0 page faults; kernel 0.0 ms, user 0.0");
    char small[40];   /* (a buffer too small: cut, never written past) */
    CHECK(stall_host_line(&f, small, sizeof small) >= (int)sizeof small - 1 && strlen(small) == sizeof small - 1);
    /* the bound: three at once, the fourth held; a third of a second later one more; 1500 in all */
    StallHostBound b = STALL_HOST_BOUND;
    int64_t now = 1000000000;
    CHECK(stall_host_bound_take(&b, now) && stall_host_bound_take(&b, now) && stall_host_bound_take(&b, now));
    CHECK(!stall_host_bound_take(&b, now) && b.held == 1);
    now += 340000000;
    CHECK(stall_host_bound_take(&b, now) && !stall_host_bound_take(&b, now) && b.held == 2);
    int told = 4;
    for (int i = 0; i < 4000; i++) told += stall_host_bound_take(&b, now += 1000000000);
    CHECK(told == 1500 && b.told == 1500);
    if (!fails) printf("PASS: the threshold, a cause from eight threads, the line and the bound\n");
    return fails != 0;
}
'''

LOOK = r'''
#include <string.h>
#include "stall_host.h"
static int fails;
#define CHECK(x) do { if (!(x)) { printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
typedef long long LONG64;
StallHostCause hos_stall_host[STALL_HOST_CAUSES];
int64_t hos_stall_host_us = -1;
volatile LONG64 hos_present_count;
/* the stand-ins: a clock the case moves, the process's counts as the case sets them, the core waits it queues, the log kept */
static int64_t clock_ns = 5000000000LL;
int64_t hos_now_ns(void) { return clock_ns; }
static uint64_t faults_now;
static int64_t kernel_now, user_now, wait_ns, wait_n, wait_longest;
static int asked, lines;
static char last[1024];
static void process_work(uint64_t *page_faults, int64_t *kernel_ns, int64_t *user_ns) {
    asked++;
    *page_faults = faults_now, *kernel_ns = kernel_now, *user_ns = user_now;
}
void hos_vcore_waits_take(int64_t *ns, int64_t *count, int64_t *longest) {
    *ns = wait_ns, *count = wait_n, *longest = wait_longest;
    wait_ns = wait_n = wait_longest = 0;
}
static void hos_log(const char *fmt, const char *line) {
    (void)fmt;
    lines++;
    snprintf(last, sizeof last, "%s", line);
}
@PRESENTED@
/* a present ms after the last one */
static void present(double ms) {
    clock_ns += (int64_t)(ms * 1e6);
    hos_present_count++;
    hos_stall_host_presented();
}
/* a counted call that takes ms */
static void call(int cause, double ms, uint64_t bytes) {
    const int64_t began = stall_host_begin();
    clock_ns += (int64_t)(ms * 1e6);
    stall_host_end(cause, began, bytes);
}
int main(int argc, char **argv) {
    const char *c = argc > 1 ? argv[1] : "";
    if (!strcmp(c, "off")) {   /* HOS_STALL_HOST=0, or RX_VK_STALL_LOG=0 */
        CHECK(stall_host_begin() == 0);
        call(STALL_HOST_READ, 80, 1 << 20);
        present(16), present(300), present(300);
        CHECK(lines == 0 && asked == 0 && hos_stall_host[STALL_HOST_READ].count == 0);
    } else if (!strcmp(c, "threshold")) {   /* RX_VK_STALL_LOG=100 */
        present(16), present(80);
        CHECK(lines == 0);
        present(120);
        CHECK(lines == 1 && strstr(last, ", 120.0 ms:"));
    } else {
        CHECK(stall_host_begin() == clock_ns);
        present(16);   /* the first present: nothing to measure from */
        CHECK(lines == 0 && asked == 1);
        /* a short frame with a flush in it: no line, and its flush is not the next frame's */
        call(STALL_HOST_FLUSH, 9, 0);
        wait_ns = 2000000, wait_n = 5, wait_longest = 900000;
        faults_now = 0xFFFFFFF0u, kernel_now = 1000000000, user_now = 5000000000LL;
        present(7);
        CHECK(lines == 0 && asked == 2 && hos_stall_host[STALL_HOST_FLUSH].count == 0);
        /* a long frame: three reads, a discard, core waits; the fault count wraps */
        call(STALL_HOST_READ, 41, 6 << 20), call(STALL_HOST_READ, 5, 3 << 20), call(STALL_HOST_READ, 6, 3 << 20);
        call(STALL_HOST_DISCARD, 4.5, 180 << 20);
        wait_ns = 64000000, wait_n = 212, wait_longest = 31000000;
        faults_now = 0x10, kernel_now += 38000000, user_now += 120000000;
        present(143.2 - 56.5);
        CHECK(lines == 1 && asked == 3);
        if (strcmp(last, "vi: stall, the host's part: frame 3, 143.2 ms: file reads 3 (12.0 MB, 52.0 ms, longest 41.0); discards 1 "
                         "(180.0 MB, 4.5 ms, longest 4.5); core waits 64.0 ms (212, longest 31.0); 32 page faults; kernel 38.0 ms, "
                         "user 120.0")) {
            printf("FAIL: the long frame's line is\n  %s\n", last);
            fails++;
        }
        /* exactly at the threshold: a line; just under: none; and nothing counted: ruled out */
        present(50);
        CHECK(lines == 2 && strstr(last, "frame 4, 50.0 ms: none of the host's causes; 0 page faults; kernel 0.0 ms, user 0.0"));
        present(49.9);
        CHECK(lines == 2);
        /* long frames in a row: three a second at most, the ones left out said by the next line */
        clock_ns += 5000000000LL;
        hos_stall_host_presented();   /* (a 5 s frame: the bound is full again after it) */
        CHECK(lines == 3);
        for (int i = 0; i < 6; i++) present(60);
        /* (two lines left for the first two; the next three are left out; by the sixth a third of a second has passed) */
        CHECK(lines == 6 && strstr(last, "(3 such lines left out before this one)"));
        present(2000);
        CHECK(lines == 7 && !strstr(last, "left out"));
    }
    if (!fails) printf("PASS %s\n", c);
    return fails != 0;
}
'''

WORK = r'''
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static int fails;
#define CHECK(x) do { if (!(x)) { printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
@COUNTERS@
@WORK@
int main(void) {
    uint64_t f0, f1;
    int64_t k0, u0, k1, u1;
    process_work(&f0, &k0, &u0);
    CHECK(f0 > 0 && k0 >= 0 && u0 >= 0);
    volatile unsigned char *p = (volatile unsigned char *)VirtualAlloc(NULL, 64 << 20, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    CHECK(p != NULL);
    for (size_t i = 0; p && i < (64u << 20); i += 4096) p[i] = 1;   /* 16384 first touches */
    volatile uint64_t x = 1;
    const ULONGLONG until = GetTickCount64() + 120;
    while (GetTickCount64() < until) x = x * 6364136223846793005ULL + 1;   /* 120 ms of the processor */
    process_work(&f1, &k1, &u1);
    CHECK((uint32_t)(f1 - f0) >= 4096);                           /* (a fault a page, or nearly) */
    CHECK(k1 >= k0 && u1 >= u0 && (k1 - k0) + (u1 - u0) > 0);    /* (Windows counts in 15.6 ms steps, on a PC that may be busy) */
    printf("this process: %u page faults for 64 MB of first touches, %.0f ms in the kernel and %.0f in its own code\n",
           (unsigned)(uint32_t)(f1 - f0), (k1 - k0) / 1e6, (u1 - u0) / 1e6);
    if (!fails) printf("PASS: the process's page faults and CPU time as Windows counts them\n");
    return fails != 0;
}
'''


def between(text, begin, body, end, what):
    """begin, then body, then end, in that order, each there"""
    try:
        if not text.index(begin) < text.index(body) < text.index(end, text.index(body)):
            fail(what)
    except ValueError:
        fail(what)


def read_sources():
    fs = (HOST / "nn_fs.c").read_text(encoding="utf-8")
    mem = (HOST / "hos_mem.c").read_text(encoding="utf-8")
    thread = (HOST / "hos_thread.c").read_text(encoding="utf-8")
    nvn = (HOST / "nvn_native.c").read_text(encoding="utf-8")
    glue = (HOST / "mkw_glue.c").read_text(encoding="utf-8")
    dev = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    for name, text in (("nn_fs.c", fs), ("hos_mem.c", mem), ("mkw_glue.c", glue)):
        if '#include "stall_host.h"' not in text:
            fail("host/%s does not include stall_host.h" % name)
    read = block(fs, "static uint64_t read_at(")
    between(read, "const int64_t stall0 = stall_host_begin();", "ReadFile(fh->h,", "stall_host_end(STALL_HOST_READ, stall0, done);",
            "nn_fs.c read_at: the read is not counted")
    if not read.index("hos_vcore_away();") < read.index("stall_host_begin();") or \
            not read.index("stall_host_end(STALL_HOST_READ") < read.index("if (away) hos_vcore_back();"):
        fail("nn_fs.c read_at: the read's time takes in the wait for the virtual core, which the core waits count already")
    between(block(fs, "HLE(_ZN2nn2fs9WriteFileENS0_10FileHandleElPKvmRKNS0_11WriteOptionE) {"), "const int64_t stall0 = stall_host_begin();",
            "WriteFile(fh->h,", "stall_host_end(STALL_HOST_WRITE, stall0, put);", "nn_fs.c WriteFile: the write is not counted")
    between(block(fs, "HLE(_ZN2nn2fs9FlushFileENS0_10FileHandleE) {"), "const int64_t stall0 = stall_host_begin();", "FlushFileBuffers(",
            "stall_host_end(STALL_HOST_FLUSH, stall0, 0);", "nn_fs.c FlushFile: the flush is not counted")
    between(block(fs, "HLE(_ZN2nn2fs6CommitEPKc) {"), "const int64_t stall0 = stall_host_begin();", "save_tx_stage(&tx_mounts[i].p);",
            "stall_host_end(STALL_HOST_COMMIT, stall0, 0);", "nn_fs.c Commit: the save's staging is not counted")
    discard = block(mem, "static void discard_pages(")
    between(discard, "const int64_t stall0 = stall_host_begin();", "hos_guest_fill(lo, 0, hi - lo)",   # (MEM-13: the fill, then its mark)
            "stall_host_end(STALL_HOST_ZERO, stall0, hi - lo);", "hos_mem.c discard_pages: the zero-fill under an import is not counted")
    between(discard, "const int64_t stall0 = stall_host_begin();", "VirtualAlloc(GP(lo), (SIZE_T)(hi - lo), MEM_RESET, PAGE_READWRITE);",
            "stall_host_end(STALL_HOST_DISCARD, stall0, hi - lo);", "hos_mem.c discard_pages: the discard is not counted")
    if not discard.index("stall_host_end(STALL_HOST_DISCARD") < discard.index("if (away) hos_vcore_back();"):
        fail("hos_mem.c discard_pages: the discard's time takes in the wait for the virtual core")
    between(block(mem, "HLE(_ZN2nn2os15FreeMemoryPagesEmm)"), "stall_host_begin()", "MEM_DECOMMIT)",
            "stall_host_end(STALL_HOST_DECOMMIT, stall0, hi > lo ? hi - lo : 0);", "hos_mem.c FreeMemoryPages: the decommit is not counted")
    between(block(mem, "int64_t hos_mem_give_back(uint64_t max_bytes) {"), "const int64_t stall0 = stall_host_begin();", "gc_give_back(",
            "stall_host_end(STALL_HOST_GIVE_BACK, stall0, given);", "hos_mem.c hos_mem_give_back: the pass is not counted")
    acquire = block(thread, "static void vc_acquire(HosThread *t) {")
    if "__atomic_add_fetch(&vc_gap.ns, waited, __ATOMIC_RELAXED), __atomic_add_fetch(&vc_gap.n, 1, __ATOMIC_RELAXED);" not in acquire or \
            "if (waited > __atomic_load_n(&vc_gap.longest, __ATOMIC_RELAXED)) __atomic_store_n(&vc_gap.longest, waited, __ATOMIC_RELAXED);" not in acquire:
        fail("hos_thread.c vc_acquire: a wait for a core is not added to the waits since the last present")
    take = block(thread, "void hos_vcore_waits_take(int64_t *ns, int64_t *count, int64_t *longest) {")
    if take.count("__atomic_exchange_n(&vc_gap.") != 3:
        fail("hos_thread.c hos_vcore_waits_take does not take the three counts and leave them at zero")
    present = block(nvn, "NV(nvnQueuePresentTexture) {")
    if not present.index("hos_vi_native_presented();") < present.index("hos_stall_host_presented();"):
        fail("nvn_native.c: the present does not make the host's look after it is counted and paced")
    work = block(glue, "static void process_work(uint64_t *page_faults, int64_t *kernel_ns, int64_t *user_ns) {")
    if "*page_faults = m.PageFaultCount;" not in work or "GetProcessTimes(GetCurrentProcess(), &made, &ended, &kernel, &user)" not in work:
        fail("mkw_glue.c process_work: not the process's page faults and its kernel and user time")
    if "StallHostCause hos_stall_host[STALL_HOST_CAUSES];" not in glue or "int64_t hos_stall_host_us = -1;" not in glue:
        fail("mkw_glue.c: the counters or the threshold not read yet are not defined")
    if "| `HOS_STALL_HOST=0` |" not in dev:
        fail("docs/development.md: HOS_STALL_HOST is not in the switches table")
    return glue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    try:
        glue = read_sources()
        presented = block(glue, "void hos_stall_host_presented(void) {")
        counters = glue[glue.index("typedef struct {\n    DWORD cb, PageFaultCount;"):glue.index("void hos_process_memory(")]
        work = block(glue, "static void process_work(uint64_t *page_faults, int64_t *kernel_ns, int64_t *user_ns) {")
    except ValueError as e:
        fail("a text this test reads is not there (%s)" % e)
    compiler = shutil.which(args.cc)
    if not compiler:
        raise SystemExit("C compiler not found: " + args.cc)
    env = {k: v for k, v in os.environ.items() if k not in ("RX_VK_STALL_LOG", "HOS_STALL_HOST")}
    with tempfile.TemporaryDirectory(prefix="stall-host-") as temporary:
        folder = Path(temporary)

        def build(name, text, extra=()):
            (folder / (name + ".c")).write_text(text, encoding="utf-8")
            exe = folder / (name + ".exe")
            built = subprocess.run([compiler, "-std=gnu17", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(HOST), str(folder / (name + ".c")),
                                    "-o", str(exe), *extra], capture_output=True, text=True, timeout=180)
            if built.returncode:
                print(built.stdout + built.stderr)
                fail("the %s fixture did not build" % name)
            return exe

        def run(exe, case="", **switches):
            done = subprocess.run([str(exe), case], env=dict(env, **switches), capture_output=True, text=True, timeout=120)
            if done.returncode or "PASS" not in done.stdout:
                print(done.stdout[-3000:] + done.stderr[-1000:])
                fail("%s %s %s" % (exe.stem, case, switches or ""))
            return done.stdout.strip()

        print(run(build("header", HEADER, ["-pthread"])))
        look = build("look", LOOK.replace("@PRESENTED@", presented))
        run(look, "on")
        run(look, "on", RX_VK_STALL_LOG="50", HOS_STALL_HOST="1")
        run(look, "off", HOS_STALL_HOST="0")
        run(look, "off", RX_VK_STALL_LOG="0")
        run(look, "threshold", RX_VK_STALL_LOG="100")
        print("PASS: the present's look: short frames say nothing and carry nothing over, a long frame's line is that frame's, "
              "long frames in a row are bounded, both switches turn all of it off")
        if sys.platform == "win32":
            print(run(build("work", WORK.replace("@COUNTERS@", counters).replace("@WORK@", work))))
        else:
            print("SKIP: the process's counts are Windows' (not this system)")
    print("PASS: the host's part of a long frame is counted where it is spent and logged beside the stall line")


if __name__ == "__main__":
    main()
