"""(Triforce) RX_MARK_BITMAP=1: a lifted store marks its page only where the page is a GPU page (game-free).

nx2/rtgen.py's A64_MARK in an A64_MARK_BITMAP build tests a bit of host/mark_bitmap.c's a64_gpu_pages for the page of the
store's first byte, and makes its marks (the first and last byte's pages; with A64_MARK_ONE the first's alone) only when the
bit is set. host/nvdrv.c's map_add sets the bits of every mapping's guest range, and of the page before it, before the
mapping counts.

The source is read:
  - nx2/build.py: the lifted code gets -DA64_MARK_BITMAP and the host's files -DHOS_MARK_BITMAP only with RX_MARK_BITMAP=1
    (off by default), and never without the soft write watch;
  - host/nvdrv.c: map_add calls hos_gpu_pages_set(guest, size) before it changes the mappings;
  - without the define the header's A64_MARK is the one it was (both forms still there).
And run (skipped without a C compiler): the header's marks (nx2/rtgen.py's own text) and host/mark_bitmap.c's code, cut from
the source, in a small program, with and without A64_MARK_ONE:
  - no bit, no mark: a store anywhere before a mapping is made marks nothing;
  - a mapping's pages and the page before it have their bit; the pages around them have none;
  - a store on a mapped page marks it; one that starts on the page before and crosses in marks both (the first alone
    with A64_MARK_ONE, which the collection reads as "this page and the next"); one two pages before marks nothing;
  - HOS_MARK_BITMAP_ALL=1: every store marks, as without the bitmap.

    python -I -B tests/test_mark_bitmap.py [--cc clang]
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "clang"]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nx2"))

PROGRAM = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define A64_DIRTY_PAGES (1ull << 27)
@MARKS@
uint8_t a64_dirty[A64_DIRTY_PAGES];
#define HOS_MARK_BITMAP 1
@BITMAP@
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
static int bit(uint64_t page) { return (a64_gpu_pages[page >> 3] >> (page & 7)) & 1; }
static int marks(void) { int n = 0; for (uint64_t p = 0x1FF00; p < 0x20100; p++) n += a64_dirty[p]; return n; }
static void clear(void) { memset(a64_dirty + 0x1FF00, 0, 0x200); }
int main(int argc, char **argv) {
    const int all = argc > 1 && atoi(argv[1]);
    uint64_t a;
    /* before any mapping: nothing marks (every bit set with HOS_MARK_BITMAP_ALL=1: everything does) */
    a = 0x20002010ull; A64_MARK(a, 4);
    CHECK(marks() == (all ? 1 : 0));
    clear();
    if (all) {
        a = 0x1FFFEFFEull; A64_MARK(a, 4);
#ifdef A64_MARK_ONE
        CHECK(marks() == 1 && a64_dirty[0x1FFFE]);
#else
        CHECK(marks() == 2 && a64_dirty[0x1FFFE] && a64_dirty[0x1FFFF]);
#endif
        return 0;
    }
    hos_gpu_pages_set(0x20002000ull, 0x2800);   /* pages 0x20002..0x20004 (the last one partly), and 0x20001 before them */
    hos_gpu_pages_set(0x20002000ull, 0);        /* (nothing) */
    CHECK(!bit(0x20000) && bit(0x20001) && bit(0x20002) && bit(0x20003) && bit(0x20004) && !bit(0x20005));
    /* on a mapped page */
    a = 0x20002010ull; A64_MARK(a, 4);
    CHECK(marks() == 1 && a64_dirty[0x20002]);
    clear();
    /* across two mapped pages */
    a = 0x20002FFCull; A64_MARK(a, 8);
#ifdef A64_MARK_ONE
    CHECK(marks() == 1 && a64_dirty[0x20002]);
#else
    CHECK(marks() == 2 && a64_dirty[0x20002] && a64_dirty[0x20003]);
#endif
    clear();
    /* from the page before, into the mapping */
    a = 0x20001FFEull; A64_MARK(a, 4);
#ifdef A64_MARK_ONE
    CHECK(marks() == 1 && a64_dirty[0x20001]);
#else
    CHECK(marks() == 2 && a64_dirty[0x20001] && a64_dirty[0x20002]);
#endif
    clear();
    /* two pages before, and right after: no bit, no mark */
    a = 0x20000FF0ull; A64_MARK(a, 8);
    a = 0x20005000ull; A64_MARK(a, 8);
    CHECK(marks() == 0);
    /* a mapping at the window's start has no page before it */
    hos_gpu_pages_set(0, 0x1000);
    CHECK(bit(0) && !bit(1));
    return 0;
}
"""


def fail(msg):
    raise SystemExit("mark bitmap: FAIL: " + msg)


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def check_source():
    build = read("nx2", "build.py")
    m = re.search(r"^MARK_BITMAP = (.*)$", build, re.M)
    if not m or 'os.environ.get("RX_MARK_BITMAP", "")' not in m.group(1) or '"-DA64_MARK_BITMAP"' not in m.group(1) \
            or "if WRITE_TRACK and" not in m.group(1) or not m.group(1).rstrip().endswith("else []"):
        fail("nx2/build.py: MARK_BITMAP is not -DA64_MARK_BITMAP only with RX_MARK_BITMAP=1 and the soft write watch")
    if '("1", "on", "true", "yes")' not in m.group(1):
        fail("nx2/build.py: RX_MARK_BITMAP is not off by default")
    if 'MARK_BITMAP_HOST = ["-DHOS_MARK_BITMAP"] if MARK_BITMAP else []' not in build:
        fail("nx2/build.py: the host's files do not get -DHOS_MARK_BITMAP with the lifted code's flag, and only then")
    if "+ WRITE_TRACK + MARK_BITMAP\n" not in build or "+ WRITE_TRACK + MARK_BITMAP_HOST\n" not in build:
        fail("nx2/build.py: the lifted code's or the host's flags do not hold the bitmap's define")
    nvdrv = read("host", "nvdrv.c")
    body = nvdrv[nvdrv.index("static void map_add(uint64_t va, uint64_t size, uint64_t guest) {"):]
    body = body[:body.index("\n}\n")]
    if "hos_gpu_pages_set(guest, size);" not in body or body.index("hos_gpu_pages_set(guest, size);") > body.index("maps_changed = 1;"):
        fail("host/nvdrv.c map_add: the pages' bits are not set before the mapping counts")
    import rtgen
    marks = rtgen.MARK_NATIVE_64
    for want in ("#if defined(A64_MARK_BITMAP)", "#elif defined(A64_MARK_ONE)",
                 "#define A64_MARK(a, n) (__atomic_store_n(&a64_dirty[A64_DIRTY_AT(a)], 1, __ATOMIC_RELEASE))\n",
                 "#define A64_MARK(a, n) (__atomic_store_n(&a64_dirty[A64_DIRTY_AT(a)], 1, __ATOMIC_RELEASE), \\\n"):
        if marks.count(want) != 1:
            fail("nx2/rtgen.py: the marks' text no longer has %r once" % want)
    return marks


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cc", default="clang")
    a = p.parse_args()
    marks = check_source()
    print("mark bitmap: source checks passed")
    cc = shutil.which(a.cc) or shutil.which("gcc") or shutil.which("cc")
    if not cc:
        print("mark bitmap: skipped the run (no C compiler)")
        return
    src = read("host", "mark_bitmap.c")
    cut = src[src.index("#ifdef HOS_MARK_BITMAP\n") + len("#ifdef HOS_MARK_BITMAP\n"):src.index("#else\nvoid hos_gpu_pages_set")]
    program = PROGRAM.replace("@MARKS@", marks).replace("@BITMAP@", cut)
    with tempfile.TemporaryDirectory(prefix="triforce-mark-bitmap-") as tmp:
        with open(os.path.join(tmp, "t.c"), "w", encoding="utf-8", newline="\n") as f:
            f.write(program)
        for one in (False, True):
            exe = os.path.join(tmp, "t%d.exe" % one)
            cmd = [cc, "-std=gnu11", "-O1", "-DA64_MARK_BITMAP"] + (["-DA64_MARK_ONE"] if one else []) + [os.path.join(tmp, "t.c"), "-o", exe]
            r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
            if r.returncode:
                print(r.stdout)
                fail("the program does not compile%s" % (" with A64_MARK_ONE" if one else ""))
            env = {k: v for k, v in os.environ.items() if k != "HOS_MARK_BITMAP_ALL"}
            for all_bits in (0, 1):
                e = dict(env, HOS_MARK_BITMAP_ALL="1") if all_bits else env
                r = subprocess.run([exe, str(all_bits)], env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                if r.returncode:
                    fail("%s%s: %s" % ("A64_MARK_ONE, " if one else "", "HOS_MARK_BITMAP_ALL=1" if all_bits else "the bitmap",
                                       r.stdout.strip() or "exit %d" % r.returncode))
    print("mark bitmap: pass (marks only on GPU pages and the page before; every page with HOS_MARK_BITMAP_ALL=1)")


if __name__ == "__main__":
    main()
