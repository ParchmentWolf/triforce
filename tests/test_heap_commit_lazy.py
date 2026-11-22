"""The Windows heap is committed as it is touched, with the three guards that needs (host/heap_commit.h, mkw_glue.c,
hos_mem.c, nn_fs.c; no game).

(Triforce, 11-21, the performance audit's MEM-09, after Source A's.) The game asks for a ~6.9 GB heap and touches a
part of it; committed whole at its start, all of it counted against RAM plus the page file. Left reserved, the
first-touch handler commits it 64 KB at a touch. That needs, first: a fault whose page another thread has committed
meanwhile tried again; a commit refused at the commit limit waited for; and guest memory committed before a file read
or write hands it to the kernel, which faults nothing in.

This compiles heap_commit.h alone: the heap whole on Linux, in large pages and with HOS_HEAP_COMMIT=1, and not
otherwise; a fault tried again only when committed, read-write and no execute fault; a touch's pages the reserved run
within its 64 KB; which touches get a log line.

And reads the source: SetMemoryHeapSize commits by the rule; commit_on_touch tries again before it looks for reserved
pages, on Windows only, commits only the run, waits at the limit and notes the touch; hos_commit waits at the limit
inside its bracket; the file read and write read each page of their buffers once before the kernel's call, without
VirtualQuery; the scanner knows commit_wait; the switch is in the switches table.

    python -I -B tests/test_heap_commit_lazy.py [--cc clang]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "host"
RUN_ALL_ARGS = ["--cc", "clang"]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(text, head):
    """The function that starts at head, to its closing brace at the line's start"""
    at = text.index(head)
    return text[at:text.index("\n}\n", at)]


def in_order(text, parts, why):
    at = [text.find(p) for p in parts]
    check(all(a >= 0 for a in at), why + " (missing: " + repr(parts[[a >= 0 for a in at].index(False)]) + ")" if not all(a >= 0 for a in at) else why)
    check(at == sorted(at), why)


PROGRAM = r"""
#include <stdint.h>
#include <stdio.h>
#include "heap_commit.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
int main(void) {
    /* whole: Linux, large pages, the switch */
    CHECK(!heap_commit_whole(NULL, 0, 1) && !heap_commit_whole("", 0, 1) && !heap_commit_whole("0", 0, 1));
    CHECK(heap_commit_whole("1", 0, 1) && heap_commit_whole("2", 0, 1));
    CHECK(heap_commit_whole(NULL, 1, 1) && heap_commit_whole("0", 1, 1));
    CHECK(heap_commit_whole(NULL, 0, 0) && heap_commit_whole("0", 0, 0));
    /* tried again */
    CHECK(heap_touch_again(1, 1, 0) && heap_touch_again(1, 1, 1));       /* (a read, a write) */
    CHECK(!heap_touch_again(1, 1, 8));                                   /* (an execute fault: the crash report) */
    CHECK(!heap_touch_again(0, 1, 1) && !heap_touch_again(1, 0, 1));     /* (reserved; protected: another handler's) */
    /* the pages of a touch */
    uint64_t lo, hi;
    heap_touch_range(0x12345678, 0x10000000, 0x20000000, &lo, &hi);      /* (a wide reserved run: the whole 64 KB) */
    CHECK(lo == 0x12340000 && hi == 0x12350000);
    heap_touch_range(0x12345678, 0x12343000, 0x12347000, &lo, &hi);      /* (committed pages on both sides: the run alone) */
    CHECK(lo == 0x12343000 && hi == 0x12347000);
    heap_touch_range(0x12345678, 0x12345000, 0x20000000, &lo, &hi);      /* (committed below) */
    CHECK(lo == 0x12345000 && hi == 0x12350000);
    heap_touch_range(0x12345678, 0x10000000, 0x12346000, &lo, &hi);      /* (committed above) */
    CHECK(lo == 0x12340000 && hi == 0x12346000);
    /* the log's lines */
    CHECK(heap_touch_said(1) && !heap_touch_said(2) && !heap_touch_said(1024) && heap_touch_said(4096) && !heap_touch_said(4097));
    CHECK(heap_touch_said(8192) && heap_touch_said(65536) && !heap_touch_said(12288));
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    glue = (HOST / "mkw_glue.c").read_text(encoding="utf-8")
    mem = (HOST / "hos_mem.c").read_text(encoding="utf-8")
    fs = (HOST / "nn_fs.c").read_text(encoding="utf-8")

    heap = block(mem, "HLE(_ZN2nn2os17SetMemoryHeapSizeEm)")
    in_order(heap, ['const int whole = heap_commit_whole(getenv("HOS_HEAP_COMMIT"), hos_large_hi != 0, windows);',
                    "if (size > hos_heap_size && whole) hos_commit(HOS_HEAP_BASE + hos_heap_size, size - hos_heap_size);",
                    "hos_heap_size = size;"], "SetMemoryHeapSize does not commit the heap by heap_commit.h's rule")
    check(heap.count("hos_commit(") == 1, "SetMemoryHeapSize commits the heap somewhere else too")
    check("#if defined(_WIN32)\n        const int windows = 1;\n#else\n        const int windows = 0;" in heap.replace("\r\n", "\n"),
          "the heap is left reserved on Linux too, or committed whole on Windows")

    touch = block(glue, "static LONG CALLBACK commit_on_touch(")
    in_order(touch, ["if (!VirtualQuery(p, &mbi, sizeof mbi)) return EXCEPTION_CONTINUE_SEARCH;", "#ifdef _WIN32",
                     "if (heap_touch_again(mbi.State == MEM_COMMIT, mbi.Protect == PAGE_READWRITE, rec->ExceptionInformation[0]))",
                     "return EXCEPTION_CONTINUE_EXECUTION;", "#endif",
                     "if (mbi.State != MEM_RESERVE) return EXCEPTION_CONTINUE_SEARCH;",
                     "heap_touch_range(guest, run, run + mbi.RegionSize, &lo, &hi);",
                     "if (!VirtualAlloc(GP(lo), (SIZE_T)(hi - lo), MEM_COMMIT, PAGE_READWRITE) &&",
                     "!(GetLastError() == ERROR_COMMITMENT_LIMIT && commit_wait(GP(lo), (SIZE_T)(hi - lo))))",
                     "hos_mem_note(HOS_MEM_TOUCHED, lo, hi - lo);"],
             "commit_on_touch: a fault another thread's commit answered is not tried again (on Windows only, before the look for "
             "reserved pages), or it commits more than the reserved run, does not wait at the commit limit, or does not note the touch")
    check("0x10000, MEM_COMMIT" not in touch, "commit_on_touch commits its whole 64 KB, over pages committed already")
    in_order(touch, ["const int heap = guest >= HOS_HEAP_BASE && guest - HOS_HEAP_BASE < hos_heap_size;",
                     "if (!heap && InterlockedIncrement(&touched) <= 16)", "InterlockedIncrement(&heap_touched);"],
             "the heap's first touches are among the 16 lines for pages nothing handed out, or not counted")

    wait = block(glue, "static int commit_wait(void *p, SIZE_T size) {")
    in_order(wait, ["const int tries = host_alloc_tries(hos_commit_wait_ms());", "for (int i = 0; i < tries; i++) {", "Sleep(50);", "if (VirtualAlloc(p, size, MEM_COMMIT, PAGE_READWRITE)) {",
                    "return 1;", "if (GetLastError() != ERROR_COMMITMENT_LIMIT) return 0;", "return 0;"],
             "commit_wait does not try a refused commit again for 5 s, or goes on after another error")
    commit = block(glue, "int hos_commit(uint64_t addr, uint64_t size) {")
    in_order(commit, ["const int io = hos_guest_io_begin(GP(lo), hi - lo);", "VirtualAlloc(GP(lo), (SIZE_T)(hi - lo), MEM_COMMIT, PAGE_READWRITE)",
                      "commit_err == ERROR_COMMITMENT_LIMIT && commit_wait(GP(lo), (SIZE_T)(hi - lo))", "hos_guest_io_end(io);",
                      "hos_mem_commit_end(census_had, lo, hi - lo, committed);"],
             "hos_commit does not wait at the commit limit inside its bracket, before it tells the census")
    touched = block(glue, "void hos_guest_touch(uint64_t addr, uint64_t size) {")
    in_order(touched, ["if (!hos_heap_on_touch || !size || !hos_guest_range(addr, size)) return;",
                       "for (uint64_t a = addr; a < end; a = (a | 0xFFF) + 1) (void)*(volatile const uint8_t *)GP(a);"],
             "hos_guest_touch does not read each page of a guest range once, or does with the heap committed whole")
    check("VirtualQuery" not in touched, "hos_guest_touch asks VirtualQuery: it walks every page of a committed region, GBs of them, "
                                         "in each file read")
    check("hos_heap_on_touch = 1;" in heap and heap.index("if (size > hos_heap_size && !whole) {") < heap.index("hos_heap_on_touch = 1;"),
          "SetMemoryHeapSize does not say the heap is committed as it is touched: the kernel calls' buffers are not touched")

    read = block(fs, "static uint64_t read_at(")
    in_order(read, ["const int away = hos_vcore_away();", "hos_guest_touch(buf, size);", "const int io = hos_guest_io_begin(GP(buf), size);",
                    "ReadFile(fh->h, GP(buf + done)"],
             "read_at does not touch its buffer before the kernel's read (with no virtual core held)")
    write = block(fs, "HLE(_ZN2nn2fs9WriteFileENS0_10FileHandleElPKvmRKNS0_11WriteOptionE)")
    in_order(write, ["hos_guest_touch(ARG(2), ARG(3));", "const int io = hos_guest_io_begin(GP(ARG(2)), ARG(3));", "WriteFile(fh->h, GP(ARG(2))"],
             "WriteFile does not touch its buffer before the kernel's write")
    check("void hos_guest_touch(uint64_t addr, uint64_t size);" in (HOST / "hos.h").read_text(encoding="utf-8"),
          "hos.h does not declare hos_guest_touch")
    check('("mkw_glue.c", "commit_wait", "VirtualAlloc")' in (ROOT / "tests" / "test_lazy_wb_host.py").read_text(encoding="utf-8"),
          "tests/test_lazy_wb_host.py does not know commit_wait's commit")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`HOS_HEAP_COMMIT=1`" in dev, "docs/development.md: HOS_HEAP_COMMIT is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="heap-commit-") as tmp:
        c, exe = Path(tmp) / "heap.c", Path(tmp) / "heap.exe"
        c.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cc, "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(HOST), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the rules as made:\n" + r.stdout)
    print("PASS: the Windows heap is committed as it is touched, behind its three guards")


if __name__ == "__main__":
    main()
