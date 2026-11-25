"""An eviction leaves out the write-back of a texture another image drew into since (gpu/vk/evict_reason.h,
vk_texture.cpp texture_sweep and drawn_others; no game, no GPU).

(Triforce, 11-22, the performance audit's TEX-R404, after Source A's.) Over the budget the eviction writes each chosen
texture the GPU drew back into the game's memory. The game draws its HUD labels inside the storage of a 1920 x 1080
target it no longer uses; when the target went, its old texels landed over the labels, and the labels were uploaded from
them as noise.

Three parts:
  1. tests/test_evict_reason.cpp against the header: Source A's frames (3804 against 3987 stale; 0, 1468 and 3804 not),
     the overlap on the trace's addresses (the target at 0x1001e88fc00, 8,640 KB; the label at 0x1001f039400 inside it;
     ranges that touch are apart), the walk's candidates and the switch's values.
  2. drawn_others and texture_sweep's block, cut out of vk_texture.cpp and compiled with stand-ins: the target's
     write-back is left out and the label's kept, one drawn in the same frame, one that touches, an image the GPU never
     drew and one of no size change nothing, the skips are counted and logged; with RX_VK_EVICT_STALE_FLUSH=1 every
     write-back stays, as before.
  3. the source: the block sits between the loop that chooses and the batches that write back, the bookkeeping loop is
     as it was, drawn_others walks the cache and not the pass's ordered list, the switch is in the switches table.

    python -I -B tests/test_evict_reason.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

BLOCK_HEAD = '    static const bool stale_flush = evict_reason::flush_stale(getenv("RX_VK_EVICT_STALE_FLUSH"));\n'
BATCHES = "    {   // (the write-backs: batches of up to 64 textures or ~512 MB of staging memory, each one submission and one wait)\n"

HARNESS = r'''
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <unordered_map>
#include <vector>
#include "evict_reason.h"

struct Texture {
    uint64_t gpu = 0, guest_size = 0, last_written = 0;
    bool gpu_written = false;
    uint32_t id = 0, width = 0, height = 0;
};
static std::unordered_map<int, std::unique_ptr<Texture>> textures;
static int logged;
static void logf(const char* fmt, ...) {
    char line[512];
    va_list ap;
    va_start(ap, fmt);
    std::vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    logged++;
    std::printf("log: %s\n", line);
}
struct Evict { Texture* tex; bool flush, shifted; };

@DRAWN_OTHERS@

static uint64_t pass(std::vector<Evict>& evict) {
@BLOCK@
    return st_stale_skipped;
}

static int fails;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)

static Texture* add(uint64_t gpu, uint64_t size, uint64_t written, bool drawn = true) {
    static int ids;
    auto t = std::make_unique<Texture>();
    t->gpu = gpu, t->guest_size = size, t->last_written = written, t->gpu_written = drawn, t->id = (uint32_t)++ids;
    t->width = t->height = 16;
    Texture* p = t.get();
    textures[ids] = std::move(t);
    return p;
}

int main(int argc, char** argv) {
    const bool as_before = argc > 1 && argv[1][0] == '1';   // (run with RX_VK_EVICT_STALE_FLUSH=1)
    const uint64_t target_at = 0x1001e88fc00ull, target_size = 8640ull * 1024;
    Texture* target = add(target_at, target_size, 3804);
    Texture* label = add(0x1001f039400ull, 110ull * 110 * 4, 3987);                  // (inside the target, drawn later)
    Texture* beside = add(target_at + target_size, 1 << 20, 3804);                   // (touches the target's end)
    Texture* touching = add(target_at + target_size + (1 << 20), 4096, 3990);        // (touches `beside`, drawn later)
    Texture* pair_a = add(0x20000000000ull, 1 << 20, 500);                           // (two drawn in the same frame, overlapping)
    Texture* pair_b = add(0x20000000000ull + 4096, 1 << 20, 500);
    Texture* cpu = add(0x30000000000ull, 1 << 20, 100);
    add(0x30000000000ull + 4096, 4096, 900, false);                                  // (over `cpu`, but never drawn by the GPU)
    Texture* sized = add(0x40000000000ull, 1 << 20, 100);
    add(0x40000000000ull, 0, 900);                                                   // (an image of no size at its start)
    Texture* unflushed = add(0x50000000000ull, 1 << 20, 100);                        // (chosen, not written back: not asked)
    add(0x50000000000ull + 4096, 4096, 900);
    Texture* older = add(0x60000000000ull, 1 << 20, 800);
    add(0x60000000000ull + 8192, 4096, 799);                                         // (inside it, drawn a frame before)

    std::vector<Evict> evict = {{beside, true, false}, {label, true, false},  {pair_b, true, false}, {target, true, false},
                                {pair_a, true, false}, {cpu, true, false},    {sized, true, false},  {unflushed, false, true},
                                {older, true, false}};
    (void)touching;
    const uint64_t skipped = pass(evict);
    const auto flush_of = [&](const Texture* t) {
        for (const Evict& e : evict)
            if (e.tex == t) return e.flush;
        return false;
    };
    CHECK(evict.size() == 9 && evict[0].tex == beside && evict[3].tex == target && evict[7].tex == unflushed);   // (the list as it was)
    CHECK(evict[7].shifted && !evict[7].flush);
    if (as_before) {
        CHECK(skipped == 0 && logged == 0);
        CHECK(flush_of(target) && flush_of(label) && flush_of(beside) && flush_of(pair_a) && flush_of(pair_b) && flush_of(cpu) &&
              flush_of(sized) && flush_of(older));
    } else {
        CHECK(!flush_of(target));                       // (the label was drawn inside it since)
        CHECK(flush_of(label));                         // (the target over it was drawn before it)
        CHECK(flush_of(beside));                        // (its neighbours only touch it)
        CHECK(flush_of(pair_a) && flush_of(pair_b));    // (the same frame keeps both)
        CHECK(flush_of(cpu) && flush_of(sized) && flush_of(older));
        CHECK(skipped == 1 && logged == 1);
        // a second pass: the count goes on, and a write-back already left out is not asked again
        std::vector<Evict> again = {{target, false, false}, {older, true, false}};
        add(0x60000000000ull + 16384, 4096, 801);       // (now a later image inside `older`)
        CHECK(pass(again) == 2 && !again[1].flush && !again[0].flush && logged == 2);
        // the first 20 are logged, the rest counted
        for (int i = 0; i < 30; i++) {
            std::vector<Evict> more = {{older, true, false}};
            pass(more);
        }
        std::vector<Evict> last = {{older, true, false}};
        CHECK(pass(last) == 33 && logged == 20);
    }
    if (!fails) std::printf("the eviction's stale write-backs (%s): all checks passed\n", as_before ? "the switch set" : "the default");
    return fails != 0;
}
'''


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def function(text, head):
    start = text.index(head)
    return text[start:text.index("\n}\n", start) + 3]


def check_source(tex):
    check('#include "evict_reason.h"' in tex, "vk_texture.cpp does not include evict_reason.h")
    others = function(tex, "void drawn_others(std::vector<evict_reason::Candidate>& cands) {")
    check("for (auto& kv : textures) {" in others and "order" not in others,
          "drawn_others does not walk the cache itself (a pass's ordered list is filtered)")
    check("if (!o->gpu_written || !o->guest_size) continue;" in others and
          "evict_reason::note(cands, longest, o->gpu, o->gpu + o->guest_size, o->last_written, o);" in others,
          "drawn_others does not note every sized image the GPU drew with its last drawing")
    start = tex.index("void texture_sweep(uint64_t completed, bool sweep, uint64_t budget, uint64_t evict_to, bool known, uint64_t used, "
                      "uint64_t allowed,\n                   bool dead_only, uint64_t hold_to, uint64_t rule_to) {")
    sweep = tex[start:]
    at = [sweep.index(n) for n in (
        "    for (auto& [last, tex] : order) {\n        // (total_bytes can have drifted",       # the loop that chooses
        "        evict.push_back({tex, !no_flush && !overwritten && tex->gpu_written && !tex->released && flushable(*tex), shifted});",
        "        come_back_noted.store(true, std::memory_order_relaxed);",
        BLOCK_HEAD,
        "            if (evict[i].flush && evict[i].tex->guest_size)",
        "        if (!cands.empty()) drawn_others(cands);",
        "            if (!evict_reason::write_back_stale(tex->last_written, c.newest)) continue;\n            evict[c.index].flush = false;",
        BATCHES,
        "            if (!e.flush) continue;\n            batch.push_back(Flush{e.tex, e.tex->gpu, e.tex->gpu + e.tex->guest_size});",
        "    for (const Evict& e : evict) {   // (and each one's bookkeeping and its end, as before)",
        "        destroy_later(*tex);\n        forget_gpu(tex);\n        gone.insert(tex);")]
    check(at == sorted(at), "the stale write-backs are not left out between the loop that chooses and the batches that write back")
    check(sweep.count("drawn_others(") == 1 and sweep.count("for (auto& [last, tex] : order)") == 6,
          "texture_sweep asks drawn_others more than once, or walks its ordered list a new time")
    check("(%llu not: \"\n" in sweep[sweep.index(BATCHES):] and "(unsigned long long)st_stale_skipped);" in sweep[sweep.index(BATCHES):],
          "the write-backs' line no longer counts the ones left out")
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("| `RX_VK_EVICT_STALE_FLUSH=1` |" in docs and "`gpu/vk/evict_reason.h`" in docs,
          "docs/development.md: RX_VK_EVICT_STALE_FLUSH is not in the switches table")
    block = sweep[sweep.index(BLOCK_HEAD):sweep.index(BATCHES)]
    return others, block


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    check((VK / "evict_reason.h").is_file(), "gpu/vk/evict_reason.h is not there")
    tex = (VK / "vk_texture.cpp").read_text(encoding="utf-8")
    others, block = check_source(tex)
    flags = ["-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror"]
    with tempfile.TemporaryDirectory(prefix="evict-reason-") as tmp:
        rule = Path(tmp) / "rule.exe"
        subprocess.run([args.cxx, *flags, str(ROOT / "tests" / "test_evict_reason.cpp"), "-o", str(rule)], check=True)
        r = subprocess.run([str(rule)], capture_output=True, text=True)
        print((r.stdout + r.stderr).rstrip())
        check(r.returncode == 0, "the rule's checks failed")
        cpp, exe = Path(tmp) / "pass.cpp", Path(tmp) / "pass.exe"
        cpp.write_text(HARNESS.replace("@DRAWN_OTHERS@", others).replace("@BLOCK@", block), encoding="utf-8")
        subprocess.run([args.cxx, *flags, "-I" + str(VK), str(cpp), "-o", str(exe)], check=True)
        env = {k: v for k, v in os.environ.items() if k != "RX_VK_EVICT_STALE_FLUSH"}
        for value, arg in ((None, "0"), ("0", "0"), ("1", "1")):
            e = dict(env)
            if value is not None:
                e["RX_VK_EVICT_STALE_FLUSH"] = value
            r = subprocess.run([str(exe), arg], capture_output=True, text=True, env=e)
            tail = [line for line in r.stdout.splitlines() if not line.startswith("log: ")]
            print("\n".join(tail))
            check(r.returncode == 0, "the cut-out pass with RX_VK_EVICT_STALE_FLUSH %s:\n%s" % ("unset" if value is None else "=" + value, r.stdout))
            if value is None:
                check("log: vk: texture #1 0x1001e88fc00 16x16 the GPU last drew in frame 3804 goes without its write-back: another image "
                      "was drawn over its storage in frame 3987 (1 so far; RX_VK_EVICT_STALE_FLUSH=1: written back, as before)" in r.stdout,
                      "the skip's log line does not name the texture and both frames:\n" + r.stdout)
    print("PASS: an eviction leaves out the write-back of a texture another image drew into since")


if __name__ == "__main__":
    main()
