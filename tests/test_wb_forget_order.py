"""The write-back diff forgets the written pages without sorting their lists, to the same result (gpu/vk/vk_memory.cpp
shadows_forget_written; no game, no GPU).

(Triforce, 11-21, the performance audit's MEM-61, after Source A's.) At the end of each part with write-backs the diff
clears, for every page written since, the bit that says its pool's shadow knows the page. Its three lists were sorted
first, only so that the pool found for one page serves the next.

This cuts shadows_forget_written out of the source as it is and runs it twice over the same lists, unsorted (as it is
now) and sorted first (RX_VK_WB_FORGET_SORT=1's arm, set in the copy): two pools with a shadow and one without, lists in
no order with repeats, pages in no pool and pages in two lists. The shadows' bits and the three counts come out the
same.

And reads the source: the sort is made only under the switch; the call is timed for the 600-submit line; the switch is
in the switches table.

    python -I -B tests/test_wb_forget_order.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


FIXTURE = r"""
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <mutex>
#include <vector>
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
constexpr uint64_t kPageShift = 12;
struct Pool {
    uint64_t lo = 0, hi = 0;
    bool shadow = true;
    std::vector<uint64_t> shadow_known;
};
std::map<uint64_t, Pool> imported;
uint64_t shadow_bytes = 1;
std::mutex shadow_written_mu;
std::vector<uint32_t> shadow_written_pages, shadow_written_collected_list, shadow_written_by_replay;
bool shadow_written_all = false;
int64_t st_wbd_known_game = 0, st_wbd_known_collected = 0, st_wbd_known_replay = 0;
namespace unsorted {
@UNSORTED@
}
namespace sorted_first {
@SORTED@
}
static uint32_t rnd_state = 99;
static uint32_t rnd() { return rnd_state = rnd_state * 1664525u + 1013904223u; }
static void pools() {   // (two pools with a shadow, 200 and 300 pages, every page known; one of 100 pages without)
    imported.clear();
    Pool a, b, c;
    a.lo = 0x10000000, a.hi = a.lo + 200 * 4096, a.shadow_known.assign(4, ~0ull);
    b.lo = 0x20000000, b.hi = b.lo + 300 * 4096, b.shadow_known.assign(5, ~0ull);
    c.lo = 0x30000000, c.hi = c.lo + 100 * 4096, c.shadow = false, c.shadow_known.assign(2, ~0ull);
    imported[a.lo] = a, imported[b.lo] = b, imported[c.lo] = c;
    st_wbd_known_game = st_wbd_known_collected = st_wbd_known_replay = 0;
}
int main() {
    for (int round = 0; round < 50; round++) {
        std::vector<uint32_t> lists[3];
        for (auto& l : lists) {
            const int n = 20 + rnd() % 400;
            for (int i = 0; i < n; i++) {
                const uint32_t which = rnd() % 5;   // (the two shadowed pools, the one without, below every pool, between two)
                const uint32_t page = which == 0 ? 0x10000 + rnd() % 200 : which == 1 ? 0x20000 + rnd() % 300
                                      : which == 2 ? 0x30000 + rnd() % 100 : which == 3 ? rnd() % 0x10000 : 0x10000 + 200 + rnd() % 1000;
                l.push_back(page);
                if (rnd() % 4 == 0) l.push_back(page);                          // (a repeat)
                if (rnd() % 6 == 0) lists[rnd() % 3].push_back(page);           // (and in another list)
            }
        }
        std::map<uint64_t, std::vector<uint64_t>> bits[2];
        int64_t counts[2][3];
        for (int arm = 0; arm < 2; arm++) {
            pools();
            shadow_written_pages = lists[0], shadow_written_collected_list = lists[1], shadow_written_by_replay = lists[2];
            if (arm == 0) unsorted::shadows_forget_written();
            else sorted_first::shadows_forget_written();
            for (const auto& [lo, p] : imported) bits[arm][lo] = p.shadow_known;
            counts[arm][0] = st_wbd_known_game, counts[arm][1] = st_wbd_known_collected, counts[arm][2] = st_wbd_known_replay;
            CHECK(shadow_written_pages.empty() && shadow_written_collected_list.empty() && shadow_written_by_replay.empty());
        }
        CHECK(bits[0] == bits[1]);
        CHECK(counts[0][0] == counts[1][0] && counts[0][1] == counts[1][1] && counts[0][2] == counts[1][2]);
        CHECK(counts[0][0] + counts[0][1] + counts[0][2] > 0);                  // (the lists did reach known pages)
        CHECK(bits[0][0x30000000] == std::vector<uint64_t>(2, ~0ull));          // (a pool without a shadow is left alone)
    }
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    mem = (ROOT / "gpu" / "vk" / "vk_memory.cpp").read_text(encoding="utf-8").replace("\r\n", "\n")
    fn = block(mem, "void shadows_forget_written() {")
    switch = 'static const bool forget_sort = getenv("RX_VK_WB_FORGET_SORT") && atoi(getenv("RX_VK_WB_FORGET_SORT")) != 0;'
    check(switch in fn, "shadows_forget_written has no RX_VK_WB_FORGET_SORT switch")
    check(fn.count("std::sort(") == 1 and "if (forget_sort) std::sort(pages.begin(), pages.end());" in fn,
          "shadows_forget_written sorts its lists whatever the switch says: thousands of pages a part, three times, under pools_mu")
    end = block(mem, "void memory_end_submission(VkCommandBuffer cmd) {")
    at = 0
    for part in ("const auto f0 = std::chrono::steady_clock::now();", "shadows_forget_written();", "st_wbd_forget_ns +=",
                 "st_wbd_forget_calls++;", "shadows_reap(), shadows_check_room();"):
        at = end.find(part, at)
        check(at >= 0, "memory_end_submission does not time the forgetting, or no longer reaps and checks the shadows after it "
                       "(missing, or out of order: " + part + ")")
        at += len(part)
    check("forgetting the written pages took %.2f ms in %lld calls" in end, "the forgetting's time is not on the 600-submit line")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_WB_FORGET_SORT=1`" in dev, "docs/development.md: RX_VK_WB_FORGET_SORT is not in the switches table")

    # (the arm that sorts: the same function with its switch read as on)
    sorted_fn = fn.replace(switch, "static const bool forget_sort = true;")
    check(sorted_fn != fn, "the sorted arm could not be made of the function")
    with tempfile.TemporaryDirectory(prefix="wb-forget-") as tmp:
        c, exe = Path(tmp) / "forget.cpp", Path(tmp) / "forget.exe"
        c.write_text(FIXTURE.replace("@UNSORTED@", fn).replace("@SORTED@", sorted_fn), encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, env={"PATH": __import__("os").environ.get("PATH", ""),
                                                                           "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})
        check(r.returncode == 0, "unsorted against sorted:\n" + r.stdout)
    print("PASS: the write-back diff forgets the written pages unsorted, to the same bits and counts")


if __name__ == "__main__":
    main()
