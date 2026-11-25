"""A CPU read of GPU results waits for the write-backs over its own bytes, not for every one over its 4 KB pages
(gpu/vk/vk_memory.cpp wb_pages_note / memory_writeback_value, RX_VK_WB_SPANS).

OoT's culling tables are double-buffered: two slots back to back whose seam is one page. The GPU's write of one slot noted
that page, and the CPU's read of the other slot waited for it. Compiles the production pieces with a small harness and
checks:
  seam       a read of slot A does not wait for the submission that wrote slot B on their shared page; a read of B does
  own        a later write over A's bytes on that page is waited for
  base       a page's full-page note before its partial ones is still waited for
  full       a full-page note makes the partial ones' record stale: a read waits for it
  samevalue  ... also with the value they had, and a big note over a recorded page (interior)
  within     a note within a recorded page, over other bytes
  merge      many partial notes on a page: a read waits at least for the newest note over its bytes
  model      2,000 random write-backs and reads against an exact per-byte model: the value a read waits for is never older
             than the newest write over its own bytes (no write is missed), and never later than the page rule's (it waits
             no longer than before); "ever" is the page rule's
  off        RX_VK_WB_SPANS=0: the page rule, as before (the seam read waits for B's submission)

python -I -B tests/test_wb_spans.py [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include "gpu/vk/page_marks.h"
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <mutex>
#include <random>
#include <string>
#include <vector>

#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
using mkwvk::PageMarks;
constexpr uint64_t kPageShift = 12, kChunkPages = 64, kPages = 1024;
uint64_t vk_timeline_completed() { return 0; }
#include "env_value_off.inc"
namespace {
#include "wb_spans.inc"
}
#include "wb_value.inc"

struct Waits { uint64_t v; bool ever; };
Waits read(uint64_t guest, uint64_t size) {
    bool ever = false;
    const uint64_t v = memory_writeback_value(guest, size, &ever);
    CHECK(memory_writeback_value(guest, size, nullptr) == v);
    return {v, ever};
}
void note(uint64_t lo, uint64_t hi, uint64_t value) { wb_pages_note(lo, hi, value); }

// (two slots back to back, as OoT's: 0x9b040 bytes each from page 16)
constexpr uint64_t kA = 16ull << kPageShift, kSize = 0x9b040, kB = kA + kSize;

int seam() {
    note(kA, kA + kSize, 5);    // (last frame: slot A)
    note(kB, kB + kSize, 7);    // (this frame: slot B; its first page is A's last)
    const Waits a = read(kA, kSize), b = read(kB, kSize);
    CHECK(a.v == 5 && a.ever);   // (A: its own write, not B's)
    CHECK(b.v == 7 && b.ever);
    return 0;
}
int own() {
    note(kA, kA + kSize, 5);
    note(kB, kB + kSize, 7);
    const uint64_t seam_page = kB & ~0xfffull;
    note(seam_page + 0x10, seam_page + 0x30, 9);   // (a later write over A's bytes on the seam page)
    CHECK(read(kA, kSize).v == 9);
    CHECK(read(kA, 0x100).v == 5);   // (A's first bytes: not on that page)
    return 0;
}
int base() {
    const uint64_t pg = 40ull << kPageShift;
    note(pg, pg + 0x1000, 3);            // (the whole page)
    note(pg + 0x800, pg + 0x2000, 4);    // (its upper half and the next page: a record on the page)
    CHECK(read(pg, 0x100).v == 3);       // (the lower bytes: the full-page note)
    CHECK(read(pg + 0x900, 0x10).v == 4);
    CHECK(read(pg, 0x1000).v == 4);      // (the whole page: the newest)
    return 0;
}
int full() {
    note(kA, kA + kSize, 5);
    note(kB, kB + kSize, 7);
    const uint64_t seam_page = kB & ~0xfffull;
    note(seam_page, seam_page + 0x1000, 11);   // (the whole seam page again)
    CHECK(read(kA, kSize).v == 11);
    return 0;
}
int samevalue() {
    const uint64_t pg = 80ull << kPageShift;
    note(pg + 0x100, pg + 0x200, 50);   // (a partial note)
    note(pg, pg + 0x1000, 50);          // (then the whole page, with the same value)
    note(pg + 0x300, pg + 0x380, 50);   // (and another partial one)
    CHECK(read(pg + 0x800, 0x10).v == 50);   // (bytes only the whole-page note wrote: waited for)
    const uint64_t pg2 = 90ull << kPageShift;
    note(pg2, pg2 + 0x1000, 3);
    note(pg2 + 0x800, pg2 + 0x2000, 7);
    note(pg2, pg2 + 0x1000, 7);          // (the whole page again, the same submission as the partial one)
    CHECK(read(pg2, 0x100).v == 7);
    return 0;
}
int within() {
    const uint64_t pg = 110ull << kPageShift;
    note(pg + 0x40, pg + 0x2000, 4);       // (a record on page 110)
    note(pg + 0x400, pg + 0x500, 6);       // (a note within page 110, over other bytes)
    CHECK(read(pg + 0x40, 0x20).v == 4);   // (the read's bytes: last written by 4)
    CHECK(read(pg + 0x400, 0x20).v == 6);
    return 0;
}
int interior() {
    // (a big note over a page with a record: the record goes stale, the read waits for the big note)
    const uint64_t pg = 100ull << kPageShift;
    note(pg + 0x40, pg + 0x2000, 4);     // (partial on page 100: a record there)
    note(pg - 0x2000, pg + 0x3000, 8);   // (pages 98-102 whole: 100 an interior page of it)
    CHECK(read(pg, 0x20).v == 8);
    return 0;
}
int merge() {
    const uint64_t pg = 60ull << kPageShift;
    // (12 notes from the page before into page 61, each ending earlier on it: prefixes, the newest the shortest)
    const uint64_t T = pg + 0x1000;
    for (uint64_t i = 0; i < 12; i++) note(pg + 0x800, T + 0x1000 - 0x100 * (i + 1), 100 + i);
    for (uint64_t j = 0; j < 15; j++) {
        uint64_t want = 0;   // (the newest note over [T + 0x100 j, + 0x80))
        for (uint64_t i = 0; i < 12; i++)
            if (T + 0x1000 - 0x100 * (i + 1) > T + 0x100 * j) want = 100 + i;
        CHECK(read(T + 0x100 * j, 0x80).v >= want);   // (merged ones wait for more, never for less)
    }
    return 0;
}
int model() {
    // (pages 100..115, every byte's newest note in an exact model; values rise as the renderer's do, some notes share one)
    constexpr uint64_t lo0 = 100ull << kPageShift, n = 16ull << kPageShift;
    std::vector<uint64_t> bv(n, 0);
    std::vector<uint64_t> pv(16, 0);   // (the page rule's: each page's newest note)
    std::mt19937_64 rng(1234);
    uint64_t seq = 0;
    for (int step = 0; step < 2000; step++) {
        if (rng() % 3) {
            const uint64_t a = rng() % n, len = 1 + rng() % (rng() % 2 ? 0x300 : 0x3000);
            const uint64_t b = std::min(n, a + len);
            if (rng() % 4) seq++;   // (one in four: another range of the same submission)
            if (!seq) seq = 1;
            note(lo0 + a, lo0 + b, seq);
            for (uint64_t i = a; i < b; i++) bv[i] = seq;
            for (uint64_t p = a >> kPageShift; p <= (b - 1) >> kPageShift; p++) pv[p] = seq;
        } else {
            const uint64_t a = rng() % n, len = 1 + rng() % 0x2000, b = std::min(n, a + len);
            const Waits w = read(lo0 + a, b - a);
            uint64_t ev = 0, pgv = 0;
            for (uint64_t i = a; i < b; i++) ev = std::max(ev, bv[i]);
            for (uint64_t p = a >> kPageShift; p <= (b - 1) >> kPageShift; p++) pgv = std::max(pgv, pv[p]);
            CHECK(w.v >= ev);    // (the read's value: at least its bytes' newest)
            CHECK(w.v <= pgv);   // (no later submission than the page rule's)
            CHECK(w.ever == (pgv != 0));   // ("ever written back" stays the page rule's)
        }
    }
    return 0;
}
int off() {
    note(kA, kA + kSize, 5);
    note(kB, kB + kSize, 7);
    CHECK(read(kA, kSize).v == 7);   // (the page rule: B's submission on the shared page)
    return 0;
}

int main(int argc, char** argv) {
    const std::string c = argc > 1 ? argv[1] : "";
    if (c == "seam") return seam();
    if (c == "own") return own();
    if (c == "base") return base();
    if (c == "full") return full();
    if (c == "samevalue") return samevalue();
    if (c == "interior") return interior();
    if (c == "within") return within();
    if (c == "merge") return merge();
    if (c == "model") return model();
    if (c == "off") return off();
    std::fprintf(stderr, "unknown case %s\n", c.c_str());
    return 2;
}
'''
CASES = (("seam", {}), ("own", {}), ("base", {}), ("full", {}), ("samevalue", {}), ("interior", {}), ("within", {}), ("merge", {}),
         ("model", {}), ("model", {"RX_VK_WB_SPANS": "0"}), ("off", {"RX_VK_WB_SPANS": "0"}))


def block(text, marker):
    """The function (or struct) that starts at `marker`, through its closing brace"""
    start = text.index(marker)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cxx", default="clang++")
    parser.add_argument("--source", type=Path, default=ROOT)
    args = parser.parse_args()
    memory = (args.source / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")
    note = block(memory, "void wb_pages_note(")
    assert "wb_spans_note(guest_lo, guest_hi)" in note, "wb_pages_note no longer notes its pages' extents"
    assert note.index("wb_spans_note(") < note.index("wb_pages.set("), \
        "a page's rest must be taken before the page takes the note's value"
    # (every note into the pages goes through wb_pages_note, with the bytes it copies: what the spans rely on)
    assert memory.count("wb_pages.set(") == 1, "a page's write-back value is set outside wb_pages_note: are its bytes noted?"
    wb = memory[memory.index("std::mutex wb_pages_mu;"):memory.index("/// (Triforce) The byte ranges of a page that submissions not yet done")]
    compiler = shutil.which(args.cxx)
    if not compiler:
        raise SystemExit("C++ compiler not found: " + args.cxx)
    flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
    env = dict(os.environ)
    env["PATH"] = str(Path(compiler).parent) + os.pathsep + env.get("PATH", "")
    env.pop("RX_VK_WB_SPANS", None)
    env.pop("RX_VK_NO_READBACK_WAIT", None)
    with tempfile.TemporaryDirectory(prefix="wb-spans-") as temporary:
        tmp = Path(temporary)
        (tmp / "env_value_off.inc").write_text(block(memory, "bool env_value_off(const char* v) {") + "\n", encoding="utf-8")
        (tmp / "wb_spans.inc").write_text(wb, encoding="utf-8")
        (tmp / "wb_value.inc").write_text(block(memory, "uint64_t memory_writeback_value(") + "\n", encoding="utf-8")
        (tmp / "wb_spans_test.cpp").write_text(HARNESS, encoding="utf-8")
        exe = tmp / ("wb_spans_test" + (".exe" if os.name == "nt" else ""))
        subprocess.run([compiler, "-std=c++20", "-O1", "-w", "-I", str(args.source), "-I", str(tmp),
                        str(tmp / "wb_spans_test.cpp"), "-o", str(exe)], check=True, env=env, creationflags=flags)
        for case, extra in CASES:
            r = subprocess.run([str(exe), case], env=dict(env, **extra), capture_output=True, text=True, creationflags=flags)
            if r.returncode:
                raise SystemExit("case %s %s failed: %s" % (case, extra or "", (r.stderr or r.stdout).strip()))
    print("wb spans: %d cases pass" % len(CASES))


if __name__ == "__main__":
    main()
