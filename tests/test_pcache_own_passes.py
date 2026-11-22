"""The back end's own compute passes made through the play cache (gpu/vk/pcache_play.h own_passes; vk_draw.cpp
shared_cache_compute; no game, no GPU).

(Triforce, 11-22, the performance audit's PIPE-95, after Source A's.) FSR 3.1's dozen passes, the anti-aliasing's and the
texture converters' were made with a bare vkCreateComputePipelines into the main pipeline cache. That cache's file is
written in play only after 64 MB of growth, so they waited for the exit's save of the whole main file, and an exit that
cut that write short left them to be compiled again at the next start. They now go the way a dispatch's pipeline goes:
cached_compute, under the cache's gate: the main cache asked without compiling, a miss compiled into the play cache, a
driver fault caught. RX_VK_PCACHE_OWN_PASSES=0: the bare creation, as before.

Compiles the switch's rule (on unless 0), then shared_cache_compute itself, cut out of vk_draw.cpp, over pcache_play.h's
real create() and a stand-in driver with a main cache and a play cache:
  - a pass the main cache has comes from it, asked without compiling, and nothing is compiled;
  - one it lacks is compiled into the play cache, with the creation's own flags, and found there the next time;
  - the gate closed (the cache let go): made with no cache, nothing asked of either;
  - no play cache: made into the main cache, as before;
  - the gate is held for the whole creation;
  - with the switch at 0: one bare creation into the main cache, the play cache never asked.
And reads the source: the callers (vk_fsr3.cpp, vk_aa.cpp, vk_texture.cpp) still make theirs through
shared_cache_compute, and the switches table has the row.

    python -I -B tests/test_pcache_own_passes.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#include "pcache_play.h"
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <set>
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)

// ---- a stand-in driver: two caches, each a set of the pipelines (by key) it holds
using VkResult = int;
constexpr VkResult VK_SUCCESS = 0, VK_PIPELINE_COMPILE_REQUIRED = 1000297000;
constexpr uint32_t VK_PIPELINE_CREATE_FAIL_ON_PIPELINE_COMPILE_REQUIRED_BIT = 0x100;
struct Cache { std::set<int> has; int asked = 0; };
using VkPipelineCache = Cache*;
using VkPipeline = int;
#define VK_NULL_HANDLE 0
struct VkComputePipelineCreateInfo { uint32_t flags; int key; };
struct { int device = 0; } dev;
int compiles, bare_calls, guarded_calls, gate_depth, made_inside_gate;
uint32_t last_flags;
static VkResult driver_create(VkPipelineCache cache, const VkComputePipelineCreateInfo* ci, VkPipeline* out) {
    made_inside_gate += gate_depth > 0;
    last_flags = ci->flags;
    if (cache) {
        cache->asked++;
        if (cache->has.count(ci->key)) return *out = ci->key, VK_SUCCESS;
        if (ci->flags & VK_PIPELINE_CREATE_FAIL_ON_PIPELINE_COMPILE_REQUIRED_BIT) return VK_PIPELINE_COMPILE_REQUIRED;
        cache->has.insert(ci->key);
    }
    compiles++;
    return *out = ci->key, VK_SUCCESS;
}
VkResult vkCreateComputePipelines(int, VkPipelineCache cache, uint32_t, const VkComputePipelineCreateInfo* ci, const void*, VkPipeline* out) {
    bare_calls++;
    return driver_create(cache, ci, out);
}
VkResult guarded_compute(VkPipelineCache cache, const VkComputePipelineCreateInfo* ci, VkPipeline* out) {
    guarded_calls++;
    return driver_create(cache, ci, out);
}
// ---- vk_draw.cpp's own, as it has them: the caches, the gate (open or let go), the creation through the play cache
Cache main_cache, play_cache;
VkPipelineCache pcache = &main_cache, pcache_play_cache = &play_cache;
std::atomic<int> pcache_preparing{0};
std::atomic<int64_t> pcache_main_built{0}, st_play_made{0};
bool gate_open = true;
struct PcacheUse {
    VkPipelineCache cache;
    PcacheUse() : cache(gate_open ? pcache : nullptr) { gate_depth++; }
    ~PcacheUse() { gate_depth--; }
};
PcacheUse pcache_use() { return PcacheUse(); }
/* CREATE */
VkResult cached_compute(VkPipelineCache cache, const VkComputePipelineCreateInfo* ci, VkPipeline* pl) {
    return cached_create(cache, ci, pl, guarded_compute);
}
/* SHARED */

int main(int argc, char** argv) {
    const bool off = argc > 1 && argv[1][0] == '0';
    main_cache.has = {1};
    VkPipeline pl = 0;
    VkComputePipelineCreateInfo ci{0x40, 1};
    if (off) {   // (RX_VK_PCACHE_OWN_PASSES=0: the bare creation into the main cache)
        ci.key = 2;
        CHECK(shared_cache_compute(&ci, &pl) == VK_SUCCESS && pl == 2 && bare_calls == 1 && guarded_calls == 0 && compiles == 1);
        CHECK(main_cache.has.count(2) && play_cache.asked == 0 && last_flags == 0x40 && made_inside_gate == 1 && gate_depth == 0);
        gate_open = false, ci.key = 3;
        CHECK(shared_cache_compute(&ci, &pl) == VK_SUCCESS && pl == 3 && bare_calls == 2 && !main_cache.has.count(3) && compiles == 2);
        std::printf("ok off\n");
        return 0;
    }
    // a pass the main cache has
    CHECK(shared_cache_compute(&ci, &pl) == VK_SUCCESS && pl == 1 && compiles == 0 && bare_calls == 0 && guarded_calls == 1);
    CHECK(main_cache.asked == 1 && play_cache.asked == 0 && (last_flags & VK_PIPELINE_CREATE_FAIL_ON_PIPELINE_COMPILE_REQUIRED_BIT));
    CHECK(made_inside_gate == 1 && gate_depth == 0);
    // one it lacks: into the play cache, with the creation's own flags
    ci.key = 2;
    CHECK(shared_cache_compute(&ci, &pl) == VK_SUCCESS && pl == 2 && compiles == 1 && play_cache.has.count(2) && !main_cache.has.count(2));
    CHECK(last_flags == 0x40 && guarded_calls == 3 && bare_calls == 0 && st_play_made == 1 && made_inside_gate == 3);
    // and found there the next time: nothing compiled
    CHECK(shared_cache_compute(&ci, &pl) == VK_SUCCESS && pl == 2 && compiles == 1 && play_cache.asked == 2);
    // the gate closed: no cache at all
    gate_open = false, ci.key = 5;
    const int main_asked = main_cache.asked, play_asked = play_cache.asked;
    CHECK(shared_cache_compute(&ci, &pl) == VK_SUCCESS && pl == 5 && compiles == 2);
    CHECK(main_cache.asked == main_asked && play_cache.asked == play_asked && !main_cache.has.count(5) && !play_cache.has.count(5));
    gate_open = true;
    // while a preparation builds: into the main cache
    pcache_preparing = 1, ci.key = 6;
    CHECK(shared_cache_compute(&ci, &pl) == VK_SUCCESS && main_cache.has.count(6) && !play_cache.has.count(6) && compiles == 3);
    pcache_preparing = 0;
    // no play cache: into the main cache, as before
    pcache_play_cache = nullptr, ci.key = 7;
    CHECK(shared_cache_compute(&ci, &pl) == VK_SUCCESS && pl == 7 && main_cache.has.count(7) && compiles == 4 && last_flags == 0x40);
    CHECK(bare_calls == 0 && gate_depth == 0);
    std::printf("ok on\n");
    return 0;
}
"""

RULE = r"""
#include "pcache_play.h"
#include <cstdio>
int main() {
    using pcache_play::own_passes;
    const bool ok = own_passes(nullptr) && own_passes("1") && own_passes("2") && !own_passes("0") && !own_passes("00");
    std::printf(ok ? "ok rule\n" : "FAIL: RX_VK_PCACHE_OWN_PASSES is not on unless 0\n");
    return !ok;
}
"""


def block(text, marker):
    start = text.index(marker)
    at = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[at] == "{") - (text[at] == "}")
        at += 1
    return text[start:at]


def need(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    shared = block(draw, "VkResult shared_cache_compute(const VkComputePipelineCreateInfo* ci, VkPipeline* out) {")
    for line in ('static const bool own_passes = pcache_play::own_passes(getenv("RX_VK_PCACHE_OWN_PASSES"));', "const auto use = pcache_use();",
                 "if (!own_passes) return vkCreateComputePipelines(dev.device, use.cache, 1, ci, nullptr, out);",
                 "return cached_compute(use.cache, ci, out);"):
        need(line in shared, "shared_cache_compute lost: " + line)
    need(shared.index("const auto use = pcache_use();") < shared.index("cached_compute("), "the gate is not taken before the creation")
    create = block(draw, "VkResult cached_create(VkPipelineCache cache, const Info* ci, VkPipeline* pl, Guarded guarded) {")
    for name, text in (("vk_fsr3.cpp", 3), ("vk_aa.cpp", 1), ("vk_texture.cpp", 1)):
        src = (ROOT / "gpu/vk" / name).read_text(encoding="utf-8")
        need(src.count("shared_cache_compute(&ci, ") >= text, name + " no longer makes its passes through shared_cache_compute")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    need("`RX_VK_PCACHE_OWN_PASSES=0`" in docs, "docs/development.md: the switches table has no RX_VK_PCACHE_OWN_PASSES row")
    env = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_")}
    with tempfile.TemporaryDirectory(prefix="pcache-own-passes-") as tmp:
        tmp = Path(tmp)
        fixture = FIXTURE.replace("/* CREATE */", "template <class Info, class Guarded>\n" + create).replace("/* SHARED */", shared)
        for name, text in (("rule", RULE), ("shared", fixture)):
            src, exe = tmp / (name + ".cpp"), tmp / (name + ".exe")
            src.write_text(text, encoding="utf-8")
            subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "gpu/vk"), str(src), "-o", str(exe)],
                           check=True)
        for exe, arg, more, want in (("rule", "", {}, "ok rule"), ("shared", "on", {}, "ok on"),
                                     ("shared", "0", {"RX_VK_PCACHE_OWN_PASSES": "0"}, "ok off")):
            r = subprocess.run([str(tmp / (exe + ".exe")), arg], capture_output=True, text=True, timeout=60, env={**env, **more})
            need(r.returncode == 0 and r.stdout.strip() == want, "the own passes' creation (%s): %s" % (arg or "rule", r.stdout.strip() or r.returncode))
            print(r.stdout.strip())
    print("PASS: the back end's own compute passes go through the play cache under the gate; RX_VK_PCACHE_OWN_PASSES=0 as before")


if __name__ == "__main__":
    main()
