"""The waits at Windows' commit limit: the game's commits, the host's own allocations and the renderer's `new`
(host/host_alloc.h, host/mkw_glue.c commit_wait and hos_xmalloc, gpu/vk/new_wait.h, vk_main.cpp new_refused; no game).

(Triforce, 11-22, the performance audit's OS-04, after Source A's and Source B's.) A refusal at the limit is tried again
every 50 ms for HOS_COMMIT_WAIT_MS (5000 unless set; 0: no wait).

- host_alloc.h's numbers and loop; then commit_wait, cut out of mkw_glue.c over a VirtualAlloc that refuses as the case
  says, a process a case (the switch is read once): refused twice more and then made (150 ms slept, one line); refused
  for good (100 tries, 5 s, one line); another error (given up at once); the switch at 0 (no try, no sleep, no line), at
  200 (4 tries) and far too large (60 s at most);
- hos_xmalloc, hos_xcalloc and hos_xrealloc, cut out of mkw_glue.c over a C library that refuses as the case says: no
  refusal costs nothing; refused three times, then made after 150 ms; refused for good: NULL after 5 s and the
  out-of-memory notice, once however many fail; a size of 0 is not waited for; a refused realloc keeps its block and
  its bytes; the switch at 0: NULL at once;
- new_wait.h's rule; then new_refused, cut out of vk_main.cpp and set as the new handler of the fixture, with the commit
  left as the case says and real allocations that cannot be made: near the limit a `new` waits its 5 s and throws, the
  same thread's next refusal throws at once (5 s a thread), another thread has its own; with 4 GiB or more left, or the
  commit not known, it throws at once; a nothrow new in a NoWait scope answers null at once, and without the scope
  waits like any other; the switch at 0: at once;
- the sources: the host's tables that end the game on NULL allocate through the three; every nothrow new of the
  renderer is in a NoWait scope; mkwvk_init sets the handler; the switch is in the switches table.

    python -I -B tests/test_commit_limit.py [--cc clang] [--cxx clang++]
"""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "clang", "--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "host"
VK = ROOT / "gpu" / "vk"


def fail(message):
    raise SystemExit("FAIL: " + message)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


WINDOWS = r'''
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "host_alloc.h"
static int fails;
#define CHECK(x) do { if (!(x)) { printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
/* Windows, standing in */
typedef size_t SIZE_T;
typedef long LONG;
typedef unsigned long DWORD;
typedef void *LPVOID;
typedef void *HANDLE;
#define WINAPI
#define MEM_COMMIT 0x1000
#define PAGE_READWRITE 4
#define ERROR_COMMITMENT_LIMIT 1455
static int slept_ms, logs, boxes;
static char last_log[256];
static void Sleep(DWORD ms) { slept_ms += (int)ms; }
static LONG InterlockedIncrement(volatile LONG *v) { return ++*v; }
static LONG InterlockedExchange(volatile LONG *v, LONG to) { const LONG was = *v; *v = to; return was; }
static HANDLE CreateThread(void *a, size_t b, DWORD (*fn)(LPVOID), void *c, DWORD d, void *e) { (void)a, (void)b, (void)fn, (void)c, (void)d, (void)e; boxes++; return NULL; }
static void CloseHandle(HANDLE h) { (void)h; }
static void hos_log(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(last_log, sizeof last_log, fmt, ap);
    va_end(ap);
    logs++;
}
'''

COMMIT = WINDOWS + r'''
static int refuse, tries;
static DWORD error = ERROR_COMMITMENT_LIMIT;
static void *VirtualAlloc(void *p, SIZE_T n, int a, int b) {
    (void)n, (void)a, (void)b;
    tries++;
    if (refuse > 0) { refuse--; return NULL; }
    return p;
}
static DWORD GetLastError(void) { return error; }
@WAIT_MS@
@COMMIT_WAIT@
int main(int argc, char **argv) {
    const char *c = argc > 1 ? argv[1] : "";
    static char page[4096];
    if (!strcmp(c, "made")) {            /* the caller's own try was refused; two more are, the third is made */
        refuse = 2;
        CHECK(commit_wait(page, 4096) == 1 && slept_ms == 150 && tries == 3 && logs == 1 && strstr(last_log, "made after 150 ms"));
        refuse = 0;
        CHECK(commit_wait(page, 4096) == 1 && slept_ms == 200 && tries == 4);   /* (made at the first try again) */
    } else if (!strcmp(c, "never")) {    /* refused for good */
        refuse = 1 << 30;
        CHECK(commit_wait(page, 4096) == 0 && slept_ms == atoi(argv[2]) && tries == atoi(argv[2]) / 50 && logs == 1);
        CHECK(strstr(last_log, "still refused after") != NULL);
    } else if (!strcmp(c, "other")) {    /* not the limit's refusal: given up at once */
        refuse = 1 << 30, error = 8;
        CHECK(commit_wait(page, 4096) == 0 && slept_ms == 50 && tries == 1 && logs == 0);
    } else if (!strcmp(c, "off")) {      /* HOS_COMMIT_WAIT_MS=0 */
        refuse = 0;
        CHECK(commit_wait(page, 4096) == 0 && slept_ms == 0 && tries == 0 && logs == 0);
    } else {                             /* the numbers */
        CHECK(host_alloc_wait_ms(NULL) == 5000 && host_alloc_wait_ms("") == 5000);
        CHECK(host_alloc_wait_ms("0") == 0 && host_alloc_wait_ms("-5") == 0 && host_alloc_wait_ms("x") == 0);
        CHECK(host_alloc_wait_ms("200") == 200 && host_alloc_wait_ms("60000") == 60000 && host_alloc_wait_ms("999999") == 60000);
        CHECK(host_alloc_tries(5000) == 100 && host_alloc_tries(200) == 4 && host_alloc_tries(49) == 0 && host_alloc_tries(0) == 0 && host_alloc_tries(-1) == 0);
        CHECK(hos_commit_wait_ms() == 5000);
    }
    if (!fails) printf("PASS %s\n", c);
    return fails != 0;
}
'''

ALLOC = WINDOWS + r'''
/* the C library, refusing as the case says */
static int refuse, asked;
static void *lib_malloc(size_t n) { asked++; if (refuse > 0 && n) { refuse--; return NULL; } return malloc(n); }
static void *lib_calloc(size_t c, size_t n) { asked++; if (refuse > 0 && c && n) { refuse--; return NULL; } return calloc(c, n); }
static void *lib_realloc(void *p, size_t n) { asked++; if (refuse > 0 && n) { refuse--; return NULL; } return realloc(p, n); }
#define malloc lib_malloc
#define calloc lib_calloc
#define realloc lib_realloc
@WAIT_MS@
@ALLOC@
#undef malloc
#undef calloc
#undef realloc
static void *count_try(void *ctx) { int *n = (int *)ctx; return ++*n >= 3 ? ctx : NULL; }
static int stepped;
static void count_sleep(int ms) { stepped += ms; }
int main(int argc, char **argv) {
    const char *c = argc > 1 ? argv[1] : "";
    if (!strcmp(c, "off")) {             /* HOS_COMMIT_WAIT_MS=0: NULL at once, and the notice */
        refuse = 1;
        CHECK(hos_xmalloc(64) == NULL && slept_ms == 0 && asked == 1 && boxes == 1);
    } else {
        /* the loop alone: the third try gives it */
        int n = 0, waited = -1;
        CHECK(host_alloc_retry(count_try, &n, 100, count_sleep, &waited) == &n && n == 3 && waited == 150 && stepped == 150);
        n = -1000, stepped = 0;
        CHECK(host_alloc_retry(count_try, &n, 4, count_sleep, &waited) == NULL && waited == 200 && stepped == 200);
        CHECK(host_alloc_retry(count_try, &n, 0, count_sleep, &waited) == NULL && waited == 0);
        /* nothing refused: nothing slept, nothing said */
        void *a = hos_xmalloc(100), *b = hos_xcalloc(10, 10), *r = hos_xrealloc(NULL, 50);
        CHECK(a && b && r && slept_ms == 0 && logs == 0 && asked == 3);
        memset(r, 0x5a, 50);
        for (int i = 0; i < 100; i++) CHECK(((unsigned char *)b)[i] == 0);
        /* refused three times (the first try and two more), then made */
        refuse = 3;
        void *m = hos_xmalloc(4096);
        CHECK(m && slept_ms == 150 && logs == 1 && strstr(last_log, "made after 150 ms") && boxes == 0);
        refuse = 2, slept_ms = 0;
        unsigned char *z = (unsigned char *)hos_xcalloc(8, 32);
        CHECK(z && slept_ms == 100 && z[0] == 0 && z[255] == 0);
        /* a refused realloc keeps its block and gives its bytes on once it is made */
        refuse = 4, slept_ms = 0;
        unsigned char *g = (unsigned char *)hos_xrealloc(r, 5000);
        CHECK(g && slept_ms == 200 && g[0] == 0x5a && g[49] == 0x5a);
        /* a size of 0 is the C library's own answer, never waited for */
        slept_ms = 0, refuse = 0;
        free(hos_xmalloc(0)), free(hos_xcalloc(0, 16)), free(hos_xcalloc(16, 0));
        CHECK(slept_ms == 0);
        /* refused for good: NULL after the 5 s, the notice once however many fail */
        refuse = 1 << 30, logs = 0;
        CHECK(hos_xmalloc(1 << 20) == NULL && slept_ms == 5000 && boxes == 1 && logs == 2 && strstr(last_log, "out of memory"));
        slept_ms = 0;
        CHECK(hos_xcalloc(4, 4) == NULL && hos_xrealloc(g, 9000) == NULL && slept_ms == 10000 && boxes == 1);
        CHECK(g[0] == 0x5a);             /* (the block a refused realloc was given is still its own) */
        free(a), free(b), free(m), free(z), free(g);
    }
    if (!fails) printf("PASS %s\n", c);
    return fails != 0;
}
'''

NEW = r'''
#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <new>
#include <string>
#include <thread>
#include "new_wait.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
namespace mkwvk {
static std::atomic<int> slept_ms{0}, logs{0};
static void Sleep(int ms) { slept_ms += ms; }
static void logf(const char*, ...) { logs++; }
static bool known = true;
static uint64_t left = 1ull << 30;   // (1 GiB of commit left: at the limit)
static bool new_commit_left(uint64_t* avail) { *avail = left; return known; }
/* REFUSED */
} // namespace mkwvk
using namespace mkwvk;
static volatile size_t huge = ~size_t(0) / 4;   // (no memory can hold it: every such `new` is refused)
// 1: bad_alloc thrown; the sleeps it made are in slept_ms
static int refused_new() {
    try {
        ::operator delete(::operator new(huge));   // (the function itself: a new-expression's allocation may be left out by the compiler)
        return 0;
    } catch (const std::bad_alloc&) {
        return 1;
    }
}
int main(int argc, char** argv) {
    const std::string c = argc > 1 ? argv[1] : "";
    using namespace new_wait;
    std::set_new_handler(new_refused);
    if (c == "off") {                        // HOS_COMMIT_WAIT_MS=0
        CHECK(refused_new() == 1 && slept_ms.load() == 0);
    } else {
        // the rule
        CHECK(kNear == (4ull << 30) && kStepMs == 50);
        CHECK(wait_ms(nullptr) == 5000 && wait_ms("") == 5000 && wait_ms("0") == 0 && wait_ms("-1") == 0 && wait_ms("300") == 300 && wait_ms("999999") == 60000);
        CHECK(waits(true, 1ull << 30, 0, 5000, 0) && waits(true, kNear - 1, 4950, 5000, 0));
        CHECK(!waits(true, kNear, 0, 5000, 0) && !waits(true, 64ull << 30, 0, 5000, 0));   // (4 GiB or more left: not the limit's)
        CHECK(!waits(false, 0, 0, 5000, 0));                                               // (the commit not known)
        CHECK(!waits(true, 0, 5000, 5000, 0) && !waits(true, 0, 0, 0, 0));                 // (its time used up; no wait asked)
        CHECK(!waits(true, 0, 0, 5000, 1));                                                // (a NoWait scope)
        // the handler as the runtime calls it: one step slept and back for another try, while it waits
        new_refused(), new_refused(), new_refused();
        CHECK(slept_ms.load() == 150 && t_waited_ms == 150 && logs.load() == 3);
        t_waited_ms = 0, slept_ms = 0;
        // a `new` that cannot be made, at the limit: 5 s of tries, then it throws; this thread's next one throws at once
        CHECK(refused_new() == 1 && slept_ms.load() == 5000 && t_waited_ms == 5000);
        CHECK(refused_new() == 1 && slept_ms.load() == 5000);
        // another thread has its own 5 s
        std::thread([] { CHECK(t_waited_ms == 0 && refused_new() == 1 && t_waited_ms == 5000); }).join();
        CHECK(slept_ms.load() == 10000 && logs.load() == 8 + 0);                           // (the first 8 waits are said)
        // far from the limit, and the commit not known: at once
        t_waited_ms = 0, slept_ms = 0, left = 8ull << 30;
        CHECK(refused_new() == 1 && slept_ms.load() == 0);
        left = 1ull << 30, known = false;
        CHECK(refused_new() == 1 && slept_ms.load() == 0);
        known = true;
        // a nothrow new: null at once in a NoWait scope; like any other outside one
        {
            NoWait at_once;
            CHECK(t_no_wait == 1);
            { NoWait inner; CHECK(t_no_wait == 2); }
            CHECK(::operator new(huge, std::nothrow) == nullptr && slept_ms.load() == 0);
        }
        CHECK(t_no_wait == 0);
        CHECK(::operator new(huge, std::nothrow) == nullptr && slept_ms.load() == 5000);
    }
    if (!fails) std::printf("PASS %s\n", c.c_str());
    return fails ? 1 : 0;
}
'''

# (file, what must be there once: the host's tables that end the game on NULL)
HOST_SITES = [
    ("nvn_native.c", "if (c > POOL_MAX) return hos_xmalloc(n);"),
    ("nvn_native.c", "return b ? b : hos_xmalloc((size_t)1 << c);"),
    ("nvn_native.c", "cmd_rec *k = (cmd_rec *)hos_xcalloc((size_t)1 << CMD_CHUNK_BITS, sizeof *k);"),
    ("nvn_native.c", "cmd_free = (uint32_t *)hos_xrealloc(cmd_free, cap_cmd_free * sizeof *cmd_free);"),
    ("nvn_native.c", "uint64_t *t = (uint64_t *)hos_xcalloc(cap, sizeof *t);"),
    ("nvn_native.c", "live_table *pub = (live_table *)hos_xmalloc(sizeof *pub);"),
    ("nvn_native.c", "dead = (dead_copy *)hos_xrealloc(dead, cap_dead * sizeof *dead);"),
    ("nvn_native.c", "nvn_tex **t = (nvn_tex **)hos_xcalloc(n, sizeof *t);"),
    ("nn_video.c", "host_objs = (HostObj *)hos_xrealloc(host_objs, cap_host_objs * sizeof *host_objs);"),
    ("nn_video.c", "Pool *o = (Pool *)hos_xcalloc(1, sizeof *o);"),
]


def read_sources():
    glue = (HOST / "mkw_glue.c").read_text(encoding="utf-8")
    for name, needle in HOST_SITES:
        text = (HOST / name).read_text(encoding="utf-8")
        if text.count(needle) != 1 or '#include "host_alloc.h"' not in text:
            fail("host/%s: %r is not there once: that table no longer waits at the commit limit" % (name, needle))
    for path in sorted(VK.glob("*.cpp")) + sorted(VK.glob("*.h")):
        if path.name == "new_wait.h":
            continue
        lines = path.read_text(encoding="utf-8").split("\n")
        for i, line in enumerate(lines):
            if "std::nothrow" in line and not line.lstrip().startswith("//"):
                if not any("new_wait::NoWait at_once;" in before for before in lines[max(0, i - 2):i]):
                    fail("gpu/vk/%s:%d: a nothrow new outside a NoWait scope: at the commit limit it waits 5 s for a null it has "
                         "its own answer to" % (path.name, i + 1))
    main = (VK / "vk_main.cpp").read_text(encoding="utf-8")
    init = block(main, "static const MkwVkRenderer* init_body(const MkwVkHost* h) {")   # (mkwvk_init's work, behind its catch: cxx_escape.h)
    if "std::set_new_handler(new_refused);" not in init:
        fail("vk_main.cpp mkwvk_init does not set the renderer's new handler")
    refused = block(main, "void new_refused() {")
    for need in ('new_wait::wait_ms(getenv("HOS_COMMIT_WAIT_MS"))', "throw std::bad_alloc();", "Sleep(new_wait::kStepMs);",
                 "new_wait::waits(known, avail, new_wait::t_waited_ms, max_ms, new_wait::t_no_wait)"):
        if need not in refused:
            fail("vk_main.cpp new_refused: %r is not there" % need)
    if "ms.ullAvailPageFile" not in block(main, "bool new_commit_left(uint64_t* avail) {"):
        fail("vk_main.cpp new_commit_left does not read the system's commit left")
    commit = block(glue, "int hos_commit(uint64_t addr, uint64_t size) {")
    if "commit_err == ERROR_COMMITMENT_LIMIT && commit_wait(GP(lo), (SIZE_T)(hi - lo))" not in commit:
        fail("mkw_glue.c hos_commit no longer waits out a refusal at the commit limit")
    if "| `HOS_COMMIT_WAIT_MS=<ms>` |" not in (ROOT / "docs/development.md").read_text(encoding="utf-8"):
        fail("docs/development.md: HOS_COMMIT_WAIT_MS is not in the switches table")
    last = block(glue, "void *hos_xrealloc(void *p, size_t n) {")
    alloc = glue[glue.index("typedef struct { int kind; void *p; size_t count, n; } HostAllocAsk;"):glue.index(last) + len(last)]
    return {"@WAIT_MS@": block(glue, "int hos_commit_wait_ms(void) {"), "@COMMIT_WAIT@": block(glue, "static int commit_wait(void *p, SIZE_T size) {"),
            "@ALLOC@": re.sub(r"^DWORD WINAPI hos_out_of_memory_box\(LPVOID\);$", "static DWORD hos_out_of_memory_box(LPVOID p) { (void)p; return 0; }",
                              alloc, flags=re.M)}, refused


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    try:
        pieces, refused = read_sources()
    except (ValueError, OSError) as e:
        fail("a text this test reads is not there (%s)" % e)
    env = {k: v for k, v in os.environ.items() if k != "HOS_COMMIT_WAIT_MS"}
    with tempfile.TemporaryDirectory(prefix="commit-limit-") as tmp:
        def build(name, text, cxx=False):
            for mark, piece in pieces.items():
                text = text.replace(mark, piece)
            src, exe = Path(tmp) / (name + (".cpp" if cxx else ".c")), Path(tmp) / (name + ".exe")
            src.write_text(text, encoding="utf-8")
            command = [args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-pthread", "-I" + str(VK)] if cxx else \
                [args.cc, "-std=gnu17", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-Wno-unused-variable", "-Wno-unknown-warning-option",
                 "-Wno-unused-but-set-variable", "-Wno-unused-but-set-global", "-I" + str(HOST)]
            built = subprocess.run(command + [str(src), "-o", str(exe)], capture_output=True, text=True)
            if built.returncode:
                print(built.stdout + built.stderr)
                fail("the %s fixture did not build" % name)
            return exe

        def run(exe, *case, switch=None):
            case_env = dict(env) if switch is None else dict(env, HOS_COMMIT_WAIT_MS=switch)
            done = subprocess.run([str(exe), *case], env=case_env, capture_output=True, text=True, timeout=120)
            if done.returncode or "PASS" not in done.stdout:
                print(done.stdout[-3000:] + done.stderr[-1000:])
                fail("%s %s, HOS_COMMIT_WAIT_MS %s" % (exe.stem, " ".join(case), "not set" if switch is None else switch))

        commit = build("commit", COMMIT)
        run(commit, "numbers")
        run(commit, "made")
        run(commit, "never", "5000")
        run(commit, "other")
        run(commit, "off", switch="0")
        run(commit, "never", "200", switch="200")
        run(commit, "never", "60000", switch="999999")
        print("PASS: the game's commits: tried again every 50 ms for HOS_COMMIT_WAIT_MS, not at 0, not for another error")
        alloc = build("alloc", ALLOC)
        run(alloc, "wait")
        run(alloc, "off", switch="0")
        print("PASS: the host's allocations: the same wait, then NULL and the notice once; a size of 0 and the switch at 0 never wait")
        new = build("new", NEW.replace("/* REFUSED */", refused), cxx=True)
        run(new, "wait")
        run(new, "off", switch="0")
        print("PASS: the renderer's new: 5 s a thread at the limit, at once with 4 GiB left or in a NoWait scope, and with the switch at 0")
    print("PASS: a refusal at Windows' commit limit is waited out in all three places, for HOS_COMMIT_WAIT_MS")


if __name__ == "__main__":
    main()
