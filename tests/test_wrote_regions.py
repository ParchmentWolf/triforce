"""A texture whose storage no GPU write ever reached is answered "not written" without the lock (gpu/vk/wrote_regions.h,
vk_texture.cpp texture_gpu_wrote and gpu_wrote_into; no game, no GPU).

(Triforce, 11-21, the performance audit's TEX-02, after Source A's.) gpu_wrote_into took gpu_wrote_mu and walked the map
of written ranges for every sampled, uploaded texture once an epoch; nearly every answer is no.

This compiles wrote_regions.h alone and checks the bits against a map kept beside them: over 20,000 random writes and
60,000 random questions a "no" from the bits is never a range the map has a write in (a set bit may be a false "ask the
map", never the other way); a write marks every region it touches, across a region's edge too; an empty range marks and
answers nothing; a range longer than the bits wraps onto all of them; addresses past 40 bits share the bits below.

And reads the source: a write's regions are marked before the map's lock is taken, whatever the switch says; the
question is asked of the bits before the lock and answers no only in mode 1; mode 2 asks the map too and counts a
disagreement; mode 0 never reads the bits' answer; the switch is in the switches table.

    python -I -B tests/test_wrote_regions.py [--cxx clang++]
"""
import argparse
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
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


PROGRAM = r"""
#include <cstdint>
#include <cstdio>
#include <vector>
#include "wrote_regions.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
static uint64_t state = 0x2545F4914F6CDD1Dull;
static uint64_t rnd() { state ^= state << 13, state ^= state >> 7, state ^= state << 17; return state; }
int main() {
    using namespace wrote_regions;
    const uint64_t MB = 1ull << 20;
    CHECK(kShift == 21 && kRegions == (1ull << 19) && sizeof bits == 64 * 1024);
    CHECK(!any(0, 64 * MB) && !any(5, 5));
    mark(5, 5);                                   // (an empty range: nothing)
    CHECK(!any(0, 2 * MB));
    mark(3 * MB - 1, 3 * MB + 1);                 // (across a region's edge: both regions)
    CHECK(any(2 * MB, 2 * MB + 1) && any(3 * MB, 4 * MB) && !any(0, 2 * MB) && !any(4 * MB, 6 * MB));
    CHECK(any(0, 3 * MB) && any(1, 100 * MB));
    // against a list of the writes: a "no" is never wrong
    std::vector<std::pair<uint64_t, uint64_t>> writes;
    const uint64_t base = 0x20000000ull;
    for (int i = 0; i < 20000; i++) {
        const uint64_t lo = base + (rnd() % (64ull << 30) & ~0xfffull) * ((rnd() & 7) == 0), size = 1 + rnd() % (rnd() % 8 ? 256 * 1024 : 48 * MB);
        const uint64_t at = lo + (rnd() % 4096) * 4096 * 512;
        mark(at, at + size);
        writes.push_back({at, at + size});
    }
    int no = 0;
    for (int q = 0; q < 60000; q++) {
        const uint64_t lo = base + rnd() % (80ull << 30), hi = lo + 1 + rnd() % (8 * MB);
        if (any(lo, hi)) continue;
        no++;
        for (const auto& w : writes) CHECK(!(w.first < hi && lo < w.second));
        if (fails) break;
    }
    CHECK(no > 100);                              // (the bits do answer no: the test has something to check)
    for (const auto& w : writes) CHECK(any(w.first, w.second) && any(w.first, w.first + 1) && any(w.second - 1, w.second));
    // past 40 bits: the bits of the addresses below
    mark((1ull << 40) + 700ull * (2 * MB), (1ull << 40) + 700ull * (2 * MB) + 1);
    CHECK(any(700ull * (2 * MB), 700ull * (2 * MB) + 1));
    // a range longer than the bits: all of them
    CHECK(span(0, 1ull << 41) == kRegions);
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    tex = (VK / "vk_texture.cpp").read_text(encoding="utf-8")
    check('#include "wrote_regions.h"' in tex, "vk_texture.cpp does not use the bits")
    wrote = block(tex, "void texture_gpu_wrote(uint64_t gpu, uint64_t size) {")
    check(wrote.index("wrote_regions::mark(lo, hi);") < wrote.index("std::lock_guard lk(gpu_wrote_mu);") and
          wrote.count("wrote_regions::mark(") == 1 and "RX_VK_WROTE_REGIONS" not in wrote,
          "a write's regions are not marked before the map has it, or only under the switch")
    into = block(tex, "bool gpu_wrote_into(Texture& tex) {")
    at = [into.index(p) for p in ("const uint64_t lo = tex.gpu, hi = tex.gpu + std::max<uint64_t>(tex.guest_size, 1);",
                                  "const bool none = regions && !wrote_regions::any(lo, hi);", "if (regions == 1) return false;",
                                  "std::lock_guard lk(gpu_wrote_mu);", "if (!newest) return false;", "if (none && st_wrong.fetch_add(")]
    check(at == sorted(at), "the bits are not asked before the lock, or mode 2's check is not after the map's answer")
    check('getenv("RX_VK_WROTE_REGIONS") ? std::clamp(atoi(getenv("RX_VK_WROTE_REGIONS")), 0, 2) : 1' in into,
          "the switch is not RX_VK_WROTE_REGIONS, 1 unless set")
    check("it->second.second <= completed_value && it->second.second > tex.gpu_wrote_seen" in into, "the map's own answer changed")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_WROTE_REGIONS=0`, `=2`" in dev, "docs/development.md: RX_VK_WROTE_REGIONS is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="wrote-regions-") as tmp:
        c, exe = Path(tmp) / "regions.cpp", Path(tmp) / "regions.exe"
        c.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=300)
        check(r.returncode == 0, "the bits as made:\n" + r.stdout[-2000:])
    print("PASS: the regions' bits never say no to storage a GPU write reached, and are asked before the map's lock")


if __name__ == "__main__":
    main()
