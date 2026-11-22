"""Is a page in a sorted list of ranges, asked for a whole loop's pages by a cursor that only moves forward (gpu/vk/
range_walk.h; vk_memory.cpp's capture and collection loops; no game, no GPU).

(Triforce, 11-22, the performance audit's MEM-42, after Source A's.) memory_collect_written, capture_make and take_capture
asked of every page whether it lies in a range list (the captures' ranges, the texture storage's) with a binary search
a page. A loop's pages come ascending, or nearly, so each loop has a RangeWalk now.

This compiles the header and asks the walk and std::upper_bound, the search as the loops made it, the same addresses:
over ranges with gaps, ranges that touch, a list that starts at 0, an empty list, one range, and random lists (also
with overlapping ranges, which the search allowed), asked ascending by page, ascending with repeats, at random,
descending, and ascending with steps back; and the walk made to search every time (the switch, the lab knob). Every
answer must be the search's. It also counts the walk's steps over an ascending loop: no more than the ranges and the
addresses together (one pass).

And reads the source: none of the loops searches any more (no upper_bound over texr or the captures' ranges, in_tex_merged
only where one page is asked), each walk over tex_merged is made after shadow_mu is taken in its block, the switch is
read once and the lab knob at each walk, and the switches table has the row.

    python -I -B tests/test_range_walk.py [--cxx clang++]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(text, marker):
    check(marker in text, "vk_memory.cpp has no " + marker)
    start = text.index(marker)
    end = text.index("{", start + len(marker) - 1) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


PROGRAM = r"""
#include <cstdio>
#include "range_walk.h"
using range_walk::Ranges;
using range_walk::RangeWalk;
static int fails = 0;
static long asked = 0;
static uint64_t rnd_state = 0x853C49E6748FEA9Bull;
static uint64_t rnd() {
    rnd_state ^= rnd_state << 13, rnd_state ^= rnd_state >> 7, rnd_state ^= rnd_state << 17;
    return rnd_state;
}
// (the search as the loops made it)
static bool searched(const Ranges& r, uint64_t a) {
    auto it = std::upper_bound(r.begin(), r.end(), std::make_pair(a, ~uint64_t(0)));
    return it != r.begin() && a < std::prev(it)->second;
}
static void ask(const Ranges& r, const std::vector<uint64_t>& order, const char* what) {
    for (int always = 0; always < 2; always++) {
        RangeWalk w{r, always != 0};
        for (uint64_t a : order) {
            asked++;
            if (w.in(a) != searched(r, a)) {
                if (fails++ < 20) std::printf("FAIL %s%s: %#llx is %s by the search\n", what, always ? " (searching)" : "", (unsigned long long)a,
                                              searched(r, a) ? "in" : "out");
            }
        }
    }
}
static void every_order(const Ranges& r, uint64_t span, const char* what) {
    std::vector<uint64_t> asc, order;
    for (uint64_t a = 0; a < span; a += 4096) asc.push_back(a);
    ask(r, asc, what);
    order.clear();   // (ascending with repeats: a page asked twice, as the shadow's loop does where it stops)
    for (uint64_t a : asc) {
        order.push_back(a);
        if (rnd() % 3 == 0) order.push_back(a);
    }
    ask(r, order, what);
    order = asc;     // (at random)
    for (size_t i = order.size(); i > 1; i--) std::swap(order[i - 1], order[rnd() % i]);
    ask(r, order, what);
    order.assign(asc.rbegin(), asc.rend());   // (descending)
    ask(r, order, what);
    order.clear();   // (ascending with steps back: an unsorted capture)
    for (size_t i = 0; i < asc.size(); i++) {
        order.push_back(asc[i]);
        if (rnd() % 5 == 0) order.push_back(asc[rnd() % (i + 1)]);
    }
    ask(r, order, what);
    order.clear();   // (addresses inside pages, and the ranges' own edges)
    for (const auto& e : r)
        for (uint64_t a : {e.first - 1, e.first, e.first + 1, e.second - 1, e.second, e.second + 1}) order.push_back(a);
    ask(r, order, what);
    std::sort(order.begin(), order.end());
    ask(r, order, what);
}

int main() {
    const uint64_t P = 4096;
    every_order({{4 * P, 8 * P}, {16 * P, 17 * P}, {40 * P, 64 * P}, {100 * P, 101 * P}}, 128 * P, "ranges with gaps");
    every_order({{4 * P, 8 * P}, {8 * P, 12 * P}, {12 * P, 13 * P}, {13 * P, 40 * P}}, 64 * P, "ranges that touch");
    every_order({{0, 3 * P}, {5 * P, 6 * P}}, 16 * P, "a list from 0");
    every_order({{1, 3 * P}}, 16 * P, "one range");
    every_order({}, 16 * P, "no range");
    for (int t = 0; t < 300; t++) {
        Ranges r;
        const int n = 1 + (int)(rnd() % (t % 3 == 0 ? 256 : 16));
        uint64_t at = (rnd() % 8) * P;
        for (int i = 0; i < n; i++) {
            const uint64_t len = (1 + rnd() % 12) * P;
            r.push_back({at, at + len});
            at += len + (rnd() % 4 == 0 ? 0 : (rnd() % 9) * P);
        }
        every_order(r, at + 8 * P, "random ranges");
        if (t % 10 == 0) {   // (sorted by first but overlapping: the search's answers all the same)
            for (auto& e : r) e.second += (rnd() % 20) * P;
            every_order(r, at + 8 * P, "overlapping ranges");
        }
    }
    {   // one pass: an ascending loop moves the cursor at most once a range
        Ranges r;
        for (uint64_t i = 0; i < 256; i++) r.push_back({i * 16 * P, i * 16 * P + 4 * P});
        RangeWalk w{r};
        size_t moved = 0, in = 0;
        for (uint64_t a = 0; a < 256 * 16 * P; a += P) {
            const size_t before = w.next;
            in += w.in(a);
            if (w.next < before) fails++, std::printf("FAIL the cursor went back in an ascending loop\n");
            moved += w.next - before;
        }
        if (moved != r.size() || in != 256 * 4) fails++, std::printf("FAIL an ascending loop: the cursor moved %zu times over %zu ranges, %zu pages in\n", moved, r.size(), in);
    }
    if (fails) std::printf("range walk: FAILED (%d of %ld answers)\n", fails, asked);
    else std::printf("range walk: %ld answers, every one the search's\n", asked);
    return fails != 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    check((VK / "range_walk.h").exists(), "gpu/vk/range_walk.h is missing")
    mem = (VK / "vk_memory.cpp").read_text(encoding="utf-8")
    check('#include "range_walk.h"' in mem, "vk_memory.cpp does not include range_walk.h")

    # the loops
    collect = block(mem, "void memory_collect_written() {")
    check("RangeWalk in_capture{owned, range_walk_search()};" in collect and "in_capture.in(guest)" in collect and "upper_bound" not in collect,
          "memory_collect_written still searches the captures' ranges for every page")
    make = block(mem, "std::unique_ptr<Capture> capture_make(bool behind) {")
    check(make.count("RangeWalk in_texr{texr, range_walk_search()};") == 2 and make.count("in_texr.in(g)") == 2 and
          "std::upper_bound(texr" not in make, "capture_make's staging loop or its behind loop still searches the texture ranges")
    for m in re.finditer(r"RangeWalk in_texr\{", make):   # (each made right before its loop)
        check(make[m.end():].lstrip().split("\n")[1].lstrip().startswith("for ("), "capture_make: a walk is not made right at its loop")
    take = block(mem, "bool take_capture(std::unique_ptr<Capture> c, uint64_t value, uint64_t completed) {")
    walks = [m.start() for m in re.finditer(r"RangeWalk in_tex\{tex_merged, range_walk_search\(\)\};", take)]
    check(len(walks) == 5 and take.count("in_tex.in(") == 6,
          "take_capture: its loops over the texture storage's ranges are not the five walks (%d) and six asks (%d)" % (len(walks), take.count("in_tex.in(")))
    check(take.count("in_tex_merged(") == 1 and "const auto to_need = [&](uint32_t i) {\n                        if (!in_tex_merged(" in take,
          "take_capture: in_tex_merged is asked elsewhere than for the one page of to_need")
    # (a walk over tex_merged is made inside a hold of shadow_mu: the nearest lock or unlock before it is shadow_mu's guard)
    for at in walks:
        before = take[:at]
        lock = before.rfind("std::lock_guard sk(shadow_mu);")
        check(lock >= 0, "take_capture: a walk over tex_merged with shadow_mu not taken")
        depth = 0   # (the guard's block is still open where the walk is made)
        for ch in before[lock:]:
            depth += (ch == "{") - (ch == "}")
            check(depth >= 0, "take_capture: a walk over tex_merged made after its shadow_mu block ended")
    log_walk = "RangeWalk in_tex{tex_merged, range_walk_search()};   // ((Triforce, 11-22, MEM-42) under shadow_mu, for this loop)\n        for (size_t j = 0; j < m; j++) is_tex[j] = !tex_merged.empty() && in_tex.in("
    check("std::lock_guard sk(shadow_mu);\n        " + log_walk in mem, "the late wait's log does not walk the texture ranges under shadow_mu")
    check(mem.count("in_tex_merged(") == 2, "in_tex_merged is asked in some other loop")

    # the switch and the knob
    search = block(mem, "bool range_walk_search() {")
    check('getenv("RX_VK_RANGE_WALK")' in search and "static const bool off" in search and "e && *e && atoi(e) == 0" in search and
          'return off || lab_ab::on("norangewalk");' in search, "RX_VK_RANGE_WALK is not read once, on unless 0, with the lab knob norangewalk")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_RANGE_WALK=0`" in dev and "`norangewalk`" in dev, "docs/development.md: RX_VK_RANGE_WALK=0 is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="range-walk-") as tmp:
        src, exe = Path(tmp) / "walk.cpp", Path(tmp) / "walk.exe"
        src.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=300)
        print(r.stdout.rstrip())
        check(r.returncode == 0, "the walk's answers are not the search's")
    print("PASS: the capture and collection loops ask a forward cursor, whose answers are the binary search's in any order")


if __name__ == "__main__":
    main()
