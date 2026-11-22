"""Freed guest pages zeroed under a Vulkan import go through hos_guest_fill, which can mark them written for the renderer
(host/hos.h hos_guest_fill, host/hos_mem.c hos_mem_zero_mark and its three sites, host/hos_svc.c's one; no game).

(Triforce, 11-22, the performance audit's MEM-13, after Source A's.) Pages a Vulkan import holds are zeroed in place when
the game frees them, not discarded. A bare memset is invisible to the renderer (the soft write watch knows what guest
code and HOS_WRITTEN mark), so its mirror, captures and the write-back's shadow kept the freed bytes. hos_guest_fill
memsets and then, with HOS_MEM_ZERO_MARK=1, marks the range written. Off by default: the entry leaves the default to a
measurement at arrivals.

This cuts hos_guest_fill out of hos.h and hos_mem_zero_mark out of hos_mem.c and runs them over stand-ins:
  - HOS_MEM_ZERO_MARK unset, empty or 0: the bytes are filled and nothing is marked (a plain memset, as before);
  - =1: the same bytes, and exactly the filled range is marked, once, AFTER the bytes are there (the mark's stand-in
    reads the range: a capture takes the mark before it copies the page);
  - the switch is read once however often the helper is called; bytes outside the range are not touched.

And reads the source: the four sites (Windows' discard, Linux's discard, FreeMemoryPages, UnmapPhysicalMemory) call the
helper and keep their HOS_MEM_ZEROED note and their hos_guest_io bracket, none has a bare memset(GP( left, the helper
memsets before it marks, and the switches table has the row.

    python -I -B tests/test_host_free_marks.py [--cc clang]
"""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cc", "clang"]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(text, marker, what):
    check(text.count(marker) == 1, "not found once in %s: %s" % (what, marker))
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


FIXTURE = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL: line %d: %s\n", __LINE__, #c); fails++; } } while (0)
static unsigned char guest[1 << 16];
#define GP(a) ((void *)(guest + (a)))
/* (the mark: what it is given, and whether the fill's bytes were there already) */
static int marks, mark_saw_fill;
static uint64_t mark_at, mark_n;
static int want_byte;
static void mark_written(const void *p, size_t n) {
    marks++, mark_at = (uint64_t)((const unsigned char *)p - guest), mark_n = n, mark_saw_fill = 1;
    for (size_t i = 0; i < n; i++)
        if (((const unsigned char *)p)[i] != (unsigned char)want_byte) mark_saw_fill = 0;
}
#define HOS_WRITTEN(p, n) mark_written((p), (n))
static int env_reads;
static const char *env_value;
static const char *fake_getenv(const char *name) { env_reads++; return strcmp(name, "HOS_MEM_ZERO_MARK") ? NULL : env_value; }
#define getenv fake_getenv
static int logged;
static void hos_log(const char *fmt, ...) { (void)fmt; logged++; }
int hos_mem_zero_mark(void);
@@HELPER@@
@@SWITCH@@

int main(int argc, char **argv) {
    env_value = argc > 1 && strcmp(argv[1], "unset") ? argv[1] : NULL;
    const int on = argc > 2 && !strcmp(argv[2], "on");
    uint64_t state = 0x9E3779B97F4A7C15ULL;
    for (int t = 0; t < 2000; t++) {
        state ^= state << 13, state ^= state >> 7, state ^= state << 17;
        const uint64_t a = 4096 + state % 40000, n = (state >> 20) % 9000;
        const int v = t % 3 == 0 ? 0xA7 : 0;   /* (the sites fill with 0; any byte is the helper's) */
        memset(guest, 0x5A, sizeof guest);
        marks = 0, mark_saw_fill = 0, want_byte = v;
        hos_guest_fill(a, v, n);
        int ok = guest[a - 1] == 0x5A && guest[a + n] == 0x5A;   /* (nothing outside the range) */
        for (uint64_t i = 0; i < n; i++) ok &= guest[a + i] == (unsigned char)v;
        CHECK(ok);
        if (on) CHECK(marks == 1 && mark_at == a && mark_n == n && mark_saw_fill);
        else CHECK(marks == 0);
    }
    CHECK(env_reads == 1);          /* (read once) */
    CHECK(logged == (on ? 1 : 0));  /* (and said once, when on) */
    printf("%s: 2000 fills, %s\n", argc > 1 ? argv[1] : "unset", on ? "each marked after its bytes" : "none marked");
    return fails != 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    hos_h = (ROOT / "host/hos.h").read_text(encoding="utf-8")
    mem = (ROOT / "host/hos_mem.c").read_text(encoding="utf-8")
    svc = (ROOT / "host/hos_svc.c").read_text(encoding="utf-8")

    helper = block(hos_h, "static inline void hos_guest_fill(uint64_t a, int v, uint64_t n) {", "host/hos.h")
    order = [helper.find(s) for s in ("memset(GP(a), v, (size_t)n);", "if (hos_mem_zero_mark()) HOS_WRITTEN(GP(a), (size_t)n);")]
    check(min(order) >= 0 and order == sorted(order), "hos_guest_fill does not memset first and mark after, behind the switch")
    check(hos_h.index("#define HOS_WRITTEN(p, n) ((void)0)") < hos_h.index("static inline void hos_guest_fill("),
          "hos_guest_fill is defined before HOS_WRITTEN")
    switch = block(mem, "int hos_mem_zero_mark(void) {", "host/hos_mem.c")
    check('getenv("HOS_MEM_ZERO_MARK")' in switch and "static int on = -1;" in switch and "e && *e && atoi(e) != 0" in switch,
          "HOS_MEM_ZERO_MARK is not off unless set to a number other than 0, or is read more than once")

    # the four sites
    discard = block(mem, "static void discard_pages(", "host/hos_mem.c")
    free_pages = block(mem, "HLE(_ZN2nn2os15FreeMemoryPagesEmm)", "host/hos_mem.c")
    unmap = svc[svc.index("case 0x2D:   /* UnmapPhysicalMemory"):]
    unmap = unmap[:unmap.index("return;", unmap.index("c->x[0] = R_OK;"))]
    win = "if (held) hos_guest_fill(lo, 0, hi - lo), hos_mem_note(HOS_MEM_ZEROED, lo, hi - lo);"
    lin = "if (rx_guest_imported(lo, hi)) hos_guest_fill(lo, 0, hi - lo), hos_mem_note(HOS_MEM_ZEROED, lo, hi - lo);"
    check(discard.count(win) == 1 and discard.index("hos_guest_io_begin(GP(lo), hi - lo);") < discard.index(win) < discard.index("hos_guest_io_end(io);"),
          "Windows' discard does not zero imported pages through hos_guest_fill inside its hos_guest_io bracket")
    check(discard.count(lin) == 1 and discard.index("#elif !defined(__EMSCRIPTEN__)") < discard.index(lin), "Linux's discard does not zero imported pages through hos_guest_fill")
    fp = "if (hi > lo && rx_guest_imported(lo, hi)) hos_guest_fill(lo, 0, hi - lo), hos_mem_note(HOS_MEM_ZEROED, lo, hi - lo);"
    check(free_pages.count(fp) == 1 and free_pages.index("hos_guest_io_begin(GP(lo), hi - lo)") < free_pages.index(fp) < free_pages.index("hos_guest_io_end(io);"),
          "FreeMemoryPages does not zero imported pages through hos_guest_fill inside its hos_guest_io bracket")
    um = "hos_guest_fill(c->x[0], 0, c->x[1]), hos_mem_note(HOS_MEM_ZEROED, c->x[0], c->x[1]);"
    check(unmap.count(um) == 1 and unmap.index("hos_guest_io_begin(GP(c->x[0]), c->x[1]);") < unmap.index(um) < unmap.index("hos_guest_io_end(io);"),
          "UnmapPhysicalMemory does not zero imported pages through hos_guest_fill inside its hos_guest_io bracket")
    for name, text in (("discard_pages", discard), ("FreeMemoryPages", free_pages), ("UnmapPhysicalMemory", unmap)):
        check(not re.search(r"memset\(GP\(", text), "%s still has a bare memset of guest memory" % name)
    check(len(re.findall(r"hos_guest_fill\(", mem + svc)) == 4, "hos_guest_fill is not called at exactly the four sites")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`HOS_MEM_ZERO_MARK=1`" in dev, "docs/development.md: HOS_MEM_ZERO_MARK=1 is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="host-free-marks-") as tmp:
        src, exe = Path(tmp) / "marks.c", Path(tmp) / "marks.exe"
        src.write_text(FIXTURE.replace("@@HELPER@@", helper).replace("@@SWITCH@@", switch), encoding="utf-8")
        subprocess.run([args.cc, "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror", str(src), "-o", str(exe)], check=True)
        env = {k: v for k, v in os.environ.items() if k != "HOS_MEM_ZERO_MARK"}
        for value, on in (("unset", False), ("", False), ("0", False), ("1", True), ("2", True), ("off", False)):
            r = subprocess.run([str(exe), value, "on" if on else "off"], env=env, capture_output=True, text=True, timeout=120)
            print(r.stdout.rstrip())
            check(r.returncode == 0, "HOS_MEM_ZERO_MARK %s: the fill's checks failed" % (value or "(empty)"))
    print("PASS: freed pages zeroed under an import go through hos_guest_fill: a plain memset unless HOS_MEM_ZERO_MARK=1, "
          "then marked written after the bytes")


if __name__ == "__main__":
    main()
