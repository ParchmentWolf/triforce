"""The textures near Windows' commit limit, and the page files' room to grow counted as free commit (gpu/vk/commit_room.h,
vk_texture.cpp commit_now, page_file_growth and texture_frame's cut; no game, no GPU).

(Triforce, 11-22, the performance audit's OS-05, after Source A's.) Off unless RX_VK_TEX_COMMIT_RESERVE_MB is set (or, for the
growth alone, RX_VK_TEX_COMMIT_GROWTH=1): with neither, nothing changes.

- the rules: the switches' values; commit_low's line, which must agree with tex_pressure::commit_low over a grid of free
  commit, limits and its switch; when the growth is read; the cap (the shortfall under the reserve off what the textures
  hold, 1 GB at least, none with no reserve or the reserve free);
- the page files' records walked over made-up buffers laid out as 64-bit Windows gives them: a page file that may grow,
  one of fixed size, one shrunk, the growth capped by its drive's free space, two on one drive capped together, two
  drives apart, a name with no drive, a lower-case drive, a buffer too short; a record whose next one lies outside the
  buffer, overlaps it, or whose name lies outside, ends the walk with what came before counted; a drive's free space is
  asked only for drives with growth;
- commit_now, cut out of vk_texture.cpp over a scripted GlobalMemoryStatusEx and a stand-in growth, a process a case (the
  switches are read once): with no switch the growth is never asked and the answer is Windows' as before; with a reserve
  it is asked only while less is free than the reserve or commit_low's line, and added to the free commit and the limit;
  RX_VK_TEX_COMMIT_GROWTH=0 never asks, =1 asks under commit_low's line without a reserve, and not with that line off;
- page_file_growth compiled against Windows and run on this PC (NtQuerySystemInformation and the drives' free space, no
  network): it answers, and a second ask within the second gives the same answer without asking again;
- texture_frame's cut, cut out and run against stand-ins: no reserve, no look at the commit; the reserve free, nothing
  cut; short of it, the budget and the rules' budget held to what the textures hold less the shortfall, 1 GB at least,
  a lower budget kept; Linux (commit not known) nothing; the "commit limit near" line on a change and every 600 presents;
- mutations of the cut, of commit_now and of the header must each fail; the sources: the cut after the 97% rule and
  before rule_to, the growth in commit_now after Windows' numbers, the switches table.

    python -I -B tests/test_commit_room.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
CUT = "if (const uint64_t reserve = commit_reserve()) {"


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


def in_order(where, text, needles):
    at = [text.find(n) for n in needles]
    if -1 in at or at != sorted(at):
        fail(where + ": not in this order: " + " / ".join(needles))


RULES = r'''
#include <cstdio>
#include <cstring>
#include "commit_room.h"
#include "tex_pressure.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
using namespace commit_room;
static const uint64_t MB = 1ull << 20, GB = 1ull << 30;

// a buffer of records as 64-bit Windows lays them out, the names after them
struct Buf {
    alignas(8) uint8_t b[2048] = {};
    size_t len = 0, names = 1024;
    const uint16_t* name(const char* s) {
        uint16_t* at = (uint16_t*)(b + names);
        size_t n = std::strlen(s);
        for (size_t i = 0; i < n; i++) at[i] = (uint16_t)s[i];
        names += n * 2 + 8;
        return at;
    }
    // a record at `at`: its next, its size and the size it may grow to (pages), its name
    void put(size_t at, uint32_t next, uint32_t total, uint32_t most, const char* file, const uint16_t* where = nullptr) {
        PageFileRecord r{};
        r.next = next, r.total_pages = total, r.max_pages = most, r.min_pages = total;
        if (file) {
            r.name = where ? where : name(file);
            r.name_bytes = r.name_room = (uint16_t)(std::strlen(file) * 2);
        }
        std::memcpy(b + at, &r, sizeof r);
        len = names;
    }
};
static uint64_t free_c, free_d;
static int asked_c, asked_d, asked_other;
static uint64_t free_of(char d) {
    if (d == 'C') return asked_c++, free_c;
    if (d == 'D') return asked_d++, free_d;
    return asked_other++, 0;
}
static uint64_t walk(const Buf& B) { return growth(B.b, B.len, 4096, free_of); }
static void drives(uint64_t c, uint64_t d) { free_c = c, free_d = d, asked_c = asked_d = asked_other = 0; }

int main() {
    // ---- the switches ----
    CHECK(reserve_of(nullptr) == 0 && reserve_of("") == 0 && reserve_of("0") == 0 && reserve_of("x") == 0 && reserve_of("-5") == 0);
    CHECK(reserve_of("2560") == 2560 * MB && reserve_of("1") == MB && reserve_of("999999") == 65536 * MB);
    CHECK(!growth_on(nullptr, 0) && growth_on(nullptr, 2560 * MB) && !growth_on("", 0) && growth_on("", MB));   // (unset: with a reserve)
    CHECK(!growth_on("0", 2560 * MB) && !growth_on("0", 0) && growth_on("1", 0) && growth_on("1", MB) && !growth_on("x", MB));
    // ---- commit_low's line, as tex_pressure::commit_low has it ----
    CHECK(low_line(0, -1) == 0 && low_line(32 * GB, 0) == 0);
    CHECK(low_line(32 * GB, -1) == 4096 * MB && low_line(64 * GB, -1) == 64 * GB / 10 && low_line(32 * GB, 6000) == 6000 * MB);
    for (uint64_t limit : {0ull, 8 * GB, 16 * GB, 40 * GB, 41 * GB, 64 * GB, 128 * GB})
        for (int64_t want : {-1ll, 0ll, 1ll, 3000ll, 4096ll, 9000ll})
            for (uint64_t avail = 0; avail <= 20 * GB; avail += 256 * MB) {
                const uint64_t low = low_line(limit, want);
                if (tex_pressure::commit_low(avail, limit, want) != (low && avail < low)) {
                    std::printf("FAIL: low_line(%llu MB, %lld) disagrees with tex_pressure::commit_low at %llu MB free\n",
                                (unsigned long long)(limit / MB), (long long)want, (unsigned long long)(avail / MB));
                    fails++;
                    limit = 1ull << 62, avail = 1ull << 62;
                }
            }
    // ---- when the growth is read: counted, and under the higher of the reserve and the line ----
    CHECK(!read_growth(false, 0, 2560 * MB, 4096 * MB));
    CHECK(read_growth(true, 2000 * MB, 2560 * MB, 0) && !read_growth(true, 2560 * MB, 2560 * MB, 0));
    CHECK(read_growth(true, 3000 * MB, 2560 * MB, 4096 * MB) && !read_growth(true, 4096 * MB, 2560 * MB, 4096 * MB));
    CHECK(!read_growth(true, 0 + 1, 0, 0));   // (no reserve, the line off: never)
    // ---- the cap ----
    CHECK(cap(4 * GB, 1024 * MB, 0) == UINT64_MAX);                       // (no reserve)
    CHECK(cap(4 * GB, 2560 * MB, 2560 * MB) == UINT64_MAX && cap(4 * GB, 9 * GB, 2560 * MB) == UINT64_MAX);
    CHECK(cap(4 * GB, 1024 * MB, 2560 * MB) == 4 * GB - 1536 * MB);       // (the shortfall off what they hold)
    CHECK(cap(1500 * MB, 1024 * MB, 2560 * MB) == GB);                    // (1 GB at least)
    CHECK(cap(4 * GB, 0, 2560 * MB) == 4 * GB - 2560 * MB && cap(2 * GB, 0, 2560 * MB) == GB && cap(0, 0, 2560 * MB) == GB);
    // ---- the drive of a name ----
    {
        const uint16_t a[] = {'\\', '?', '?', '\\', 'C', ':', '\\', 'p'}, b[] = {'\\', '?', '?', '\\', 'd', ':', '\\'}, c[] = {'\\', 'D', 'e', 'v'};
        CHECK(drive_of(a, 8) == 'C' && drive_of(b, 7) == 'D' && drive_of(c, 4) == 0 && drive_of(a, 5) == 0);
    }
    // ---- the records ----
    {   // one that may grow by 2000 pages, on a drive with room
        Buf B;
        B.put(0, 0, 1000, 3000, "\\??\\C:\\pagefile.sys");
        drives(100 * GB, 0);
        CHECK(walk(B) == 2000ull * 4096 && asked_c == 1 && asked_d == 0 && asked_other == 0);
        drives(MB, 0);
        CHECK(walk(B) == MB);                                             // (capped by the drive's free space)
    }
    {   // fixed, and shrunk below what it may be: nothing
        Buf B;
        B.put(0, 40, 3000, 3000, "\\??\\C:\\pagefile.sys");
        B.put(40, 0, 3000, 2000, "\\??\\D:\\pagefile.sys");
        drives(100 * GB, 100 * GB);
        CHECK(walk(B) == 0 && asked_c == 0 && asked_d == 0);              // (no drive asked without growth)
    }
    {   // two on C capped together, one on D apart
        Buf B;
        B.put(0, 40, 1000, 3000, "\\??\\C:\\pagefile.sys");
        B.put(40, 40, 0, 1000, "\\??\\C:\\swap\\second.sys");
        B.put(80, 0, 0, 500, "\\??\\d:\\pagefile.sys");
        drives(10 * MB, 100 * GB);
        CHECK(walk(B) == 10 * MB + 500ull * 4096 && asked_c == 1 && asked_d == 1);
        drives(100 * GB, MB);
        CHECK(walk(B) == 3000ull * 4096 + MB);
    }
    {   // a name with no drive counts nothing, and the walk goes on
        Buf B;
        B.put(0, 40, 0, 1000, "\\Device\\HarddiskVolume3\\pagefile.sys");
        B.put(40, 0, 0, 1000, "\\??\\C:\\pagefile.sys");
        drives(100 * GB, 0);
        CHECK(walk(B) == 1000ull * 4096 && asked_other == 0);
    }
    {   // the next record outside the buffer: the walk ends, the first counted
        Buf B;
        B.put(0, 4000, 0, 1000, "\\??\\C:\\pagefile.sys");
        drives(100 * GB, 0);
        CHECK(walk(B) == 1000ull * 4096);
        B.put(0, 8, 0, 1000, "\\??\\C:\\pagefile.sys");                   // (one that would overlap it)
        B.put(40, 0, 0, 7000, "\\??\\C:\\pagefile.sys");
        CHECK(walk(B) == 1000ull * 4096);
    }
    {   // a name outside the buffer: that record and those after it count nothing
        Buf B;
        static const uint16_t elsewhere[] = {'\\', '?', '?', '\\', 'C', ':', '\\', 'p', 'f'};
        B.put(0, 40, 0, 1000, "\\??\\C:\\pagefile.sys");
        B.put(40, 40, 0, 2000, "\\??\\C:\\pf", elsewhere);
        B.put(80, 0, 0, 4000, "\\??\\C:\\pagefile.sys");
        drives(100 * GB, 0);
        CHECK(walk(B) == 1000ull * 4096);
        uint16_t* near_end = (uint16_t*)(B.b + B.len - 4);                // (a name that starts inside and runs past the end)
        near_end[0] = 'C', near_end[1] = ':';
        B.put(40, 40, 0, 2000, "\\??\\C:\\pf", near_end);
        B.len = B.names;
        CHECK(walk(B) == 1000ull * 4096);
    }
    {   // too short for a record, or empty
        Buf B;
        B.put(0, 0, 0, 1000, "\\??\\C:\\pagefile.sys");
        drives(100 * GB, 0);
        CHECK(growth(B.b, 39, 4096, free_of) == 0 && growth(B.b, 0, 4096, free_of) == 0 && asked_c == 0);
    }
    if (!fails) std::printf("PASS rules\n");
    return fails ? 1 : 0;
}
'''

NOW = r'''
#include <windows.h>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include "commit_room.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
static const uint64_t MB = 1ull << 20, GB = 1ull << 30;
// (Windows' numbers as the case sets them, and the page files' growth as a stand-in that counts its asks)
static uint64_t win_avail, win_limit;
static BOOL fake_status(LPMEMORYSTATUSEX m) {
    m->ullAvailPageFile = win_avail, m->ullTotalPageFile = win_limit;
    return TRUE;
}
#define GlobalMemoryStatusEx fake_status
static int growth_asks;
static uint64_t page_file_growth_fake() { return growth_asks++, 3 * GB; }
/* CUT */
static bool look(uint64_t avail_mb, uint64_t limit_mb, uint64_t* avail, uint64_t* limit) {
    win_avail = avail_mb * MB, win_limit = limit_mb * MB, growth_asks = 0;
    return commit_now(avail, limit);
}
int main(int argc, char** argv) {
    const std::string c = argc > 1 ? argv[1] : "";
    uint64_t a = 0, l = 0;
    if (c == "unset") {   // (no switch: Windows' numbers, the growth never asked, however little is free)
        for (uint64_t free_mb : {0ull, 100ull, 2000ull, 4000ull, 9000ull}) {
            CHECK(look(free_mb, 40000, &a, &l) && a == free_mb * MB && l == 40000 * MB && growth_asks == 0 && commit_grown == 0);
        }
    } else if (c == "reserve") {   // (RX_VK_TEX_COMMIT_RESERVE_MB=2560: under the higher of it and commit_low's line, 4 GB here)
        CHECK(look(9000, 40000, &a, &l) && a == 9000 * MB && l == 40000 * MB && growth_asks == 0);
        CHECK(look(4096, 40000, &a, &l) && growth_asks == 0);
        CHECK(look(4000, 40000, &a, &l) && a == 4000 * MB + 3 * GB && l == 40000 * MB + 3 * GB && growth_asks == 1 && commit_grown == 3 * GB);
        CHECK(look(1000, 40000, &a, &l) && a == 1000 * MB + 3 * GB && growth_asks == 1);
        CHECK(look(9000, 40000, &a, &l) && a == 9000 * MB && commit_grown == 0);   // (the last growth not carried over)
    } else if (c == "reserve-big") {   // (a reserve above commit_low's line: the reserve's)
        CHECK(look(5000, 40000, &a, &l) && growth_asks == 1 && a == 5000 * MB + 3 * GB);
        CHECK(look(6000, 40000, &a, &l) && growth_asks == 1);
        CHECK(look(8000, 40000, &a, &l) && growth_asks == 0 && a == 8000 * MB);
    } else if (c == "never") {   // (RX_VK_TEX_COMMIT_GROWTH=0, a reserve set: never)
        CHECK(look(100, 40000, &a, &l) && a == 100 * MB && l == 40000 * MB && growth_asks == 0);
    } else if (c == "growth-alone") {   // (RX_VK_TEX_COMMIT_GROWTH=1, no reserve: under commit_low's line)
        CHECK(look(5000, 40000, &a, &l) && growth_asks == 0);
        CHECK(look(4000, 40000, &a, &l) && growth_asks == 1 && a == 4000 * MB + 3 * GB);
    } else if (c == "line-off") {   // (RX_VK_TEX_COMMIT_GROWTH=1, RX_VK_TEX_COMMIT_FREE_MB=0, no reserve: nothing to read it for)
        CHECK(look(100, 40000, &a, &l) && growth_asks == 0 && a == 100 * MB);
    } else {
        std::printf("FAIL: unknown case\n");
        fails++;
    }
    if (!fails) std::printf("PASS %s\n", c.c_str());
    return fails ? 1 : 0;
}
'''

NOW_CASES = [
    ("unset", {}), ("reserve", {"RX_VK_TEX_COMMIT_RESERVE_MB": "2560"}), ("reserve-big", {"RX_VK_TEX_COMMIT_RESERVE_MB": "8000"}),
    ("never", {"RX_VK_TEX_COMMIT_RESERVE_MB": "2560", "RX_VK_TEX_COMMIT_GROWTH": "0"}),
    ("growth-alone", {"RX_VK_TEX_COMMIT_GROWTH": "1"}),
    ("line-off", {"RX_VK_TEX_COMMIT_GROWTH": "1", "RX_VK_TEX_COMMIT_FREE_MB": "0"}),
]

REAL = r'''
#include <windows.h>
#include <chrono>
#include <cstdio>
#include <vector>
#include "commit_room.h"
/* GROWTH */
int main() {
    const auto t0 = std::chrono::steady_clock::now();
    const uint64_t g = page_file_growth();
    const auto t1 = std::chrono::steady_clock::now();
    const uint64_t again = page_file_growth();
    const auto t2 = std::chrono::steady_clock::now();
    const double first_ms = std::chrono::duration<double, std::milli>(t1 - t0).count(), again_ms = std::chrono::duration<double, std::milli>(t2 - t1).count();
    std::printf("page files' room to grow on this PC: %llu MB (asked in %.3f ms, again in %.4f ms)\n", (unsigned long long)(g >> 20), first_ms, again_ms);
    if (again != g) { std::printf("FAIL: a second ask within the second gave another answer\n"); return 1; }
    if (g > (1ull << 50)) { std::printf("FAIL: an answer past any drive\n"); return 1; }
    std::printf("PASS real\n");
    return 0;
}
'''

FRAME = r'''
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <algorithm>
#include "commit_room.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
static const uint64_t MB = 1ull << 20, GB = 1ull << 30;
static uint64_t reserve_now, now_avail, now_limit = 40 * GB, commit_grown, frame_no;
static bool now_known = true;
static int asks, lines;
static char last_line[600];
static uint64_t commit_reserve() { return reserve_now; }
static bool commit_now(uint64_t* avail, uint64_t* limit) {
    asks++;
    if (!now_known) return false;
    *avail = now_avail, *limit = now_limit;
    return true;
}
static void logf(const char* f, ...) {
    va_list ap;
    va_start(ap, f);
    vsnprintf(last_line, sizeof last_line, f, ap);
    va_end(ap);
    lines++;
}
// one look's cut: budget and rule_budget as texture_frame has them after the 97% rule
static void look(uint64_t& budget, uint64_t& rule_budget, uint64_t total_bytes) {
/* CUT */
}
static uint64_t b, r;
static void at(uint64_t frame, uint64_t free_mb, uint64_t total_mb, uint64_t budget_mb = 0, uint64_t rule_mb = 6000) {
    frame_no = frame, now_avail = free_mb * MB, asks = 0;
    b = budget_mb ? budget_mb * MB : UINT64_MAX, r = rule_mb * MB;
    look(b, r, total_mb * MB);
}
int main() {
    // no reserve: no look at the commit, nothing cut, no line
    at(10, 100, 4096);
    CHECK(asks == 0 && b == UINT64_MAX && r == 6000 * MB && lines == 0);
    reserve_now = 2560 * MB;
    // the reserve free: nothing cut
    at(20, 3000, 4096);
    CHECK(asks == 1 && b == UINT64_MAX && r == 6000 * MB && lines == 0);
    // short by 1536 MB: what the textures hold less that, on both budgets, one line
    at(30, 1024, 4096);
    CHECK(b == 2560 * MB && r == 2560 * MB && lines == 1 && std::strstr(last_line, "vk: commit limit near: 1024 MB of 40960 free"));
    // still short: no line until a 600th present, then one
    at(40, 1024, 4096);
    CHECK(b == 2560 * MB && lines == 1);
    at(600, 1024, 4096);
    CHECK(lines == 2 && std::strstr(last_line, "near:"));
    // a budget already lower is kept; the floor
    at(610, 1024, 4096, 1000, 900);
    CHECK(b == 1000 * MB && r == 900 * MB);
    at(620, 1024, 1500);
    CHECK(b == GB && r == GB);
    at(630, 0, 900);
    CHECK(b == GB && r == GB);                       // (1 GB at least: more than they hold, nothing goes)
    // free again: nothing cut, one line
    at(640, 3000, 4096);
    CHECK(b == UINT64_MAX && r == 6000 * MB && lines == 3 && std::strstr(last_line, "no longer near"));
    // the commit not known (Linux): nothing
    now_known = false;
    at(650, 0, 4096);
    CHECK(b == UINT64_MAX && r == 6000 * MB && lines == 3);
    if (!fails) std::printf("PASS frame\n");
    return fails ? 1 : 0;
}
'''

# (each: where, what is taken out, the text, what replaces it)
MUTATIONS = [
    ("frame", "the budget capped", "        budget = std::min(budget, cap);\n", ""),
    ("frame", "the rules' budget capped", "        rule_budget = std::min(rule_budget, cap);\n", ""),
    ("frame", "the commit not known: no cut", "commit_now(&avail, &limit) ? commit_room::cap(total_bytes, avail, reserve) : UINT64_MAX",
     "(commit_now(&avail, &limit), commit_room::cap(total_bytes, avail, reserve))"),
    ("now", "the growth added", "*avail += commit_grown, *limit += commit_grown;", "(void)0;"),
    ("now", "the growth only where it can matter", "if (commit_room::read_growth(", "if (true || commit_room::read_growth("),
    ("header", "the floor", "return std::max(kFloor, total > shortfall ? total - shortfall : 0);", "return total > shortfall ? total - shortfall : 0;"),
    ("header", "the drive's cap", "sum += std::min<uint64_t>(by_drive[d], free_of((char)('A' + d)));", "sum += by_drive[d];"),
    ("header", "a name outside the buffer ends the walk", "if (n < base || n - base > len || r.name_bytes > len - (n - base)) break;",
     "if (n < base || n - base > len) break;"),
    ("header", "no growth unset without a reserve", "if (!env || !*env) return reserve != 0;", "if (!env || !*env) return true;"),
]


def read_sources():
    tex = (VK / "vk_texture.cpp").read_text(encoding="utf-8")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    if '#include "commit_room.h"' not in tex:
        fail("vk_texture.cpp does not include commit_room.h")
    now = block(tex, "bool commit_now(uint64_t* avail, uint64_t* limit) {")
    in_order("vk_texture.cpp commit_now (Windows' numbers, then the growth where it can matter, added to both)", now,
             ["*avail = ms.ullAvailPageFile, *limit = ms.ullTotalPageFile;",
              "if (commit_room::read_growth(commit_growth_on(), *avail, commit_reserve(), commit_room::low_line(*limit, commit_free_mb()))) {",
              "commit_grown = page_file_growth();", "*avail += commit_grown, *limit += commit_grown;", "return true;"])
    switches = {name: block(tex, sig) for name, sig in (("reserve", "uint64_t commit_reserve() {"), ("growth", "bool commit_growth_on() {"),
                                                       ("free", "int64_t commit_free_mb() {"))}
    for name, text, need in (("reserve", switches["reserve"], 'static const uint64_t v = commit_room::reserve_of(getenv("RX_VK_TEX_COMMIT_RESERVE_MB"));'),
                             ("growth", switches["growth"], 'static const bool v = commit_room::growth_on(getenv("RX_VK_TEX_COMMIT_GROWTH"), commit_reserve());'),
                             ("free", switches["free"], 'getenv("RX_VK_TEX_COMMIT_FREE_MB") ? atoll(getenv("RX_VK_TEX_COMMIT_FREE_MB")) : -1;')):
        if need not in text:
            fail("vk_texture.cpp: the %s switch is not read once as the rule says" % name)
    growth = block(tex, "uint64_t page_file_growth() {")
    for need in ("commit_room::kPageFileClass", "commit_room::growth(", "GetDiskFreeSpaceExW", "std::chrono::seconds(1)"):
        if need not in growth:
            fail("vk_texture.cpp page_file_growth: %r is not there" % need)
    frame = block(tex, "void texture_frame(uint64_t completed) {")
    if "static const int64_t want_mb = commit_free_mb();" not in frame:
        fail("vk_texture.cpp texture_frame: commit_low's switch is not the one commit_now reads")
    if frame.count(CUT) != 1:
        fail("vk_texture.cpp texture_frame: the reserve's cut is not there once")
    in_order("vk_texture.cpp texture_frame (the cut after the 97% rule, before rule_to and the pass)", frame,
             ["if (known && !by_blocks && used > allowed / 100 * 97 && !room_in_blocks) {",
              "rule_budget = std::min(rule_budget, total_bytes > over ? total_bytes - over : 0);", CUT,
              "const uint64_t rule_to =", "if (budget < evict_to) evict_to = hold_to = 0;",
              "texture_sweep(completed, total_bytes <= budget, budget,"])
    in_order("docs/development.md (the rows beside RX_VK_TEX_COMMIT_FREE_MB's)", dev,
             ["| `RX_VK_TEX_COMMIT_FREE_MB=<MB>` |", "| `RX_VK_TEX_COMMIT_RESERVE_MB=<MB>` |", "| `RX_VK_TEX_COMMIT_GROWTH=0` or `=1` |"])
    now_cut = "\n".join([switches["reserve"], switches["growth"], switches["free"], "uint64_t commit_grown = 0;", now])
    if now_cut.count("commit_grown = page_file_growth();") != 1:
        fail("vk_texture.cpp commit_now: the growth is not asked once")
    return block(frame, CUT), now_cut.replace("commit_grown = page_file_growth();", "commit_grown = page_file_growth_fake();"), growth


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    try:
        cut, now, growth = read_sources()
        header = (VK / "commit_room.h").read_text(encoding="utf-8")
    except (ValueError, OSError) as e:
        fail("a text this test reads is not there (%s)" % e)
    env = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_TEX_COMMIT_")}
    with tempfile.TemporaryDirectory(prefix="commit-room-") as tmp:
        tmpdir = Path(tmp)

        def build(name, text, head=None):
            inc = tmpdir / ("inc-" + name)
            inc.mkdir()
            (inc / "commit_room.h").write_text(head if head is not None else header, encoding="utf-8")
            src, exe = tmpdir / (name + ".cpp"), tmpdir / (name + ".exe")
            src.write_text(text, encoding="utf-8")
            built = subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                                    "-Wno-unused-parameter", "-I" + str(inc), "-I" + str(VK), str(src), "-o", str(exe)], capture_output=True, text=True)
            if built.returncode:
                print(built.stdout + built.stderr)
                fail("the fixture did not build (%s)" % name)
            return exe

        def run(exe, case=None, **switches):
            try:
                return subprocess.run([str(exe)] + ([case] if case else []), env=dict(env, **switches), capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired:
                return subprocess.CompletedProcess([], 1, "no end in 120 s", "")

        def passes(exe, cases):
            for case, switches in cases:
                done = run(exe, case, **switches)
                if done.returncode or "PASS" not in done.stdout:
                    return False, (done.stdout + done.stderr)[-2000:]
            return True, ""

        fixtures = {"rules": (RULES, None), "now": (NOW, now), "frame": (FRAME, cut)}
        cases = {"rules": [(None, {})], "now": NOW_CASES, "frame": [(None, {})]}

        def text_of(which, part):
            body, cut_text = fixtures[which]
            return body.replace("/* CUT */", part if part is not None else (cut_text or ""))

        for which in ("rules", "now", "frame"):
            ok, out = passes(build(which, text_of(which, None)), cases[which])
            if not ok:
                print(out)
                fail(which)
            print("PASS " + which + ("" if which != "now" else " (%d cases, each its own process)" % len(NOW_CASES)))
        done = run(build("real", REAL.replace("/* GROWTH */", growth)))
        print(done.stdout.strip())
        if done.returncode or "PASS real" not in done.stdout:
            fail("page_file_growth on this PC")
        for i, (where, what, old, new) in enumerate(MUTATIONS):
            if where == "header":
                if header.count(old) != 1:
                    fail("mutation %r: not in commit_room.h once (update the test with the code)" % what)
                ok = all(passes(build("m%d%s" % (i, w), text_of(w, None), header.replace(old, new)), cases[w])[0] for w in ("rules", "now", "frame"))
            else:
                part = fixtures[where][1]
                if part.count(old) != 1:
                    fail("mutation %r: not in the cut code once (update the test with the code)" % what)
                ok, _ = passes(build("m%d" % i, text_of(where, part.replace(old, new))), cases[where])
            if ok:
                fail("mutation %r: the fixtures still passed without it" % what)
            print("PASS mutation: without %s a case fails" % what)
    print("PASS: off unless set; the growth read only where it can matter and the walk bounded by the buffer; short of the "
          "reserve, the textures held to what they hold less the shortfall, 1 GB at least")


if __name__ == "__main__":
    main()
