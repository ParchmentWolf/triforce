"""A texture the GPU drew first gets its page map at that draw (gpu/vk/drawn_page_map.h, vk_texture.cpp texture_written and
texture_dirty; no game, no GPU).

(Triforce, 11-21, the performance audit's TEX-21, after Source A's.) A texture in a virtual pool is checked through its
mapping, and its page map was recorded at its first check. One the GPU drew first had none: once the game finalized it,
the first check took its whole storage as mapped since and uploaded it from memory over what the GPU drew.

This compiles drawn_page_map.h and texture_dirty cut out of vk_texture.cpp as it is, over a mapping and write generations
of the test's own:
- without the seed, the first check of a drawn texture gives its whole storage (the fault);
- seeded as texture_written seeds it (generation 0), the same check gives nothing; a CPU write gives its pages alone; a
  page mapped anew gives that page alone;
- the rule: which writes seed (a reason, a virtual pool, no map of the storage's size yet) and the switch.

And reads the source: texture_written seeds by the rule, under the parallel replay's lock, with generation 0, before the
texture is marked GPU-written and uploaded; every caller that draws or copies gives a reason; the switch is in the
switches table.

    python -I -B tests/test_drawn_page_map.py [--cxx clang++]
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


def block(text, head):
    at = text.index(head)
    return text[at:text.index("\n}\n", at) + 3]


FIXTURE = r"""
#include <algorithm>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <memory>
#include <string>
#include <utility>
#include <vector>
#include "drawn_page_map.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
using Ranges = std::vector<std::pair<uint64_t, uint64_t>>;
struct WriteGen {
    uint64_t v = 0;
    constexpr WriteGen() = default;
    constexpr explicit WriteGen(uint64_t x) : v(x) {}
    constexpr explicit operator bool() const { return v != 0; }
};
struct Texture {
    uint32_t id = 1, width = 256, height = 256, layers = 1;
    int nvn_format = 0x25;
    bool gpu_written = false, uploaded = false;
    uint64_t gpu = 0, guest = 0, guest_size = 0, map_sig = 0;
    std::vector<uint64_t> page_map;
    struct Run { uint64_t off, guest, n; };
    std::vector<Run> runs;
    uint32_t runs_maps_gen = ~0u;
};
// the test's mapping: a virtual address to guest memory, 64 KB a page; and what the CPU wrote, with its generation
static std::map<uint64_t, uint64_t> mapping;
static uint32_t maps_gen = 1;
struct Host {
    uint32_t maps_generation() const { return maps_gen; }
    uint32_t vmap_generation() const { return 0; }
    uint64_t gpu_guest(uint64_t a) const {
        const auto it = mapping.find(a & ~0xFFFFull);
        return it == mapping.end() ? 0 : it->second + (a & 0xFFFF);
    }
};
static Host host_obj;
static Host* host = &host_obj;
struct Write { uint64_t lo, hi, gen; };
static std::vector<Write> writes;
static void memory_written_runs(uint64_t guest, uint64_t n, WriteGen gen, Ranges& out, bool = false) {
    for (const Write& w : writes)
        if (w.gen > gen.v && w.lo < guest + n && w.hi > guest)
            out.push_back({std::max(w.lo, guest) - guest, std::min(w.hi, guest + n) - guest});
    std::sort(out.begin(), out.end());
}
static uint64_t mix(uint64_t h, uint64_t v) { return (h ^ v) * 0x100000001b3ull + 0x9E3779B97F4A7C15ull; }
static std::map<uint64_t, std::unique_ptr<Texture>> textures;
static void logf(const char*, ...) {}

// (vk_texture.cpp's own, cut out by the test)
@TEXTURE_DIRTY@

static Texture drawn() {   // (a 256 KB texture in a virtual pool, four pages, mapped to guest memory that is not in one piece)
    Texture t;
    t.gpu = (1ull << 40) + 0x200000, t.guest_size = 4 * 65536;
    return t;
}
int main() {
    using namespace drawn_page_map;
    // the rule
    const uint64_t V = kVirtual + 0x200000;
    CHECK(on(nullptr) && on("") && on("1") && !on("0"));
    CHECK(pages(1) == 1 && pages(65536) == 1 && pages(65537) == 2 && pages(4 * 65536) == 4);
    CHECK(seeds(true, "a draw", V, 4 * 65536, 0));
    CHECK(!seeds(false, "a draw", V, 4 * 65536, 0));          // (the switch)
    CHECK(!seeds(true, "?", V, 4 * 65536, 0));                // (no reason given: a clear, the movie upscaler)
    CHECK(!seeds(true, nullptr, V, 4 * 65536, 0));
    CHECK(!seeds(true, "a draw", 0x80000000, 4 * 65536, 0));  // (not a virtual pool: checked in guest memory directly)
    CHECK(!seeds(true, "a draw", V, 0, 0));                   // (no storage)
    CHECK(!seeds(true, "a draw", V, 4 * 65536, 4));           // (the map is there: once a texture)
    CHECK(seeds(true, "a draw", V, 4 * 65536, 3));            // (a map of another size is none)

    mapping = {{V, 0x10000000}, {V + 65536, 0x10010000}, {V + 2 * 65536, 0x30000000}, {V + 3 * 65536, 0x30010000}};
    writes = {{0x10000000, 0x10001000, 5}};                   // (the CPU wrote a page of it long ago, generation 5)
    Ranges out;
    {   // without the seed: drawn, finalized at generation 9, and its first check takes the whole storage
        Texture t = drawn();
        CHECK(texture_dirty(t, WriteGen{9}, out) && out.size() == 1 && out[0].first == 0 && out[0].second == 4 * 65536);
    }
    {   // seeded at the draw, as texture_written does: generation 0
        Texture t = drawn();
        CHECK(seeds(true, "a draw", t.gpu, t.guest_size, t.page_map.size()));
        Ranges seeded;
        texture_dirty(t, WriteGen{}, seeded);
        CHECK(t.page_map.size() == 4 && t.page_map[0] == 0x10000000 && t.page_map[2] == 0x30000000);
        CHECK(!seeds(true, "a draw", t.gpu, t.guest_size, t.page_map.size()));   // (once)
        CHECK(!texture_dirty(t, WriteGen{9}, out) && out.empty());               // (finalized, checked: nothing to upload)
        writes.push_back({0x30010000, 0x30012000, 12});                          // (the CPU writes two 4 KB pages after that)
        CHECK(texture_dirty(t, WriteGen{9}, out) && out.size() == 1 && out[0].first == 3 * 65536 && out[0].second == 3 * 65536 + 0x2000);
        mapping[V + 65536] = 0x50000000, maps_gen++;                             // (and one of its pages is mapped anew)
        CHECK(texture_dirty(t, WriteGen{12}, out) && out.size() == 1 && out[0].first == 65536 && out[0].second == 2 * 65536);
        CHECK(!texture_dirty(t, WriteGen{12}, out));                             // (taken once)
    }
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    tex = (VK / "vk_texture.cpp").read_text(encoding="utf-8").replace("\r\n", "\n")
    written = block(tex, "void texture_written(Texture* tex, const char* why) {")
    at = 0
    for part in ('static const bool drawn_map = drawn_page_map::on(getenv("RX_VK_DRAWN_PAGE_MAP"));',
                 "if (drawn_page_map::seeds(drawn_map, why, tex->gpu, tex->guest_size, tex->page_map.size())) {",
                 "ParLock lk;", "texture_dirty(*tex, WriteGen{}, seeded);", "tex->gpu_written = true;", "tex->uploaded = true;"):
        at = written.find(part, at)
        check(at >= 0, "texture_written does not record a drawn texture's page map by the rule, under the parallel replay's lock, "
                       "with generation 0, before it marks the texture written and uploaded (missing, or out of order: " + part + ")")
        at += len(part)
    check('#include "drawn_page_map.h"' in tex, "vk_texture.cpp does not use the rule")
    # (the writers that draw or copy say who they are; none of them passes the "?" that keeps the old path)
    reasons = 0
    for name in ("vk_draw.cpp", "vk_xfer.cpp"):
        src = (VK / name).read_text(encoding="utf-8")
        for m in re.finditer(r"\btexture_written\(([^;]*)\);", src):
            call = m.group(1)
            check('"?"' not in call, name + ": a writer passes \"?\" itself: say who writes, or give no reason")
            reasons += call.count('"') >= 2
    check(reasons >= 8, "the writers that give a reason were not found (%d): the scan no longer reads the source" % reasons)
    check('void texture_written(Texture* tex, const char* why = "?");' in (VK / "vk_texture.h").read_text(encoding="utf-8"),
          "texture_written's default reason is no longer \"?\": a write without one would seed")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_DRAWN_PAGE_MAP=0`" in dev, "docs/development.md: RX_VK_DRAWN_PAGE_MAP is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="drawn-page-map-") as tmp:
        c, exe = Path(tmp) / "map.cpp", Path(tmp) / "map.exe"
        c.write_text(FIXTURE.replace("@TEXTURE_DIRTY@", block(tex, "bool texture_dirty(Texture& tex, WriteGen gen, Ranges& out, bool same_ok = false) {")),
                     encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Wno-unused-function", "-Wno-unused-variable", "-Werror",
                        "-I" + str(VK), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the map at the draw:\n" + r.stdout)
    print("PASS: a texture the GPU drew first gets its page map at that draw")


if __name__ == "__main__":
    main()
