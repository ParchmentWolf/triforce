"""A recording slot's descriptor pool at half size, whole once a recording ran out (gpu/vk/desc_pool_grow.h; no game, no GPU).

(Triforce, 11-22, the performance audit's DESC-33, after Source A's.) Each recording slot kept a whole descriptor pool
(8192 sets, up to 32768 descriptors a type), 48 slots at most, and few recordings come near it. A slot's pool is now made
at half; a recording that runs out gets a whole extra pool on the spot, as before, and at the slot's next reset its own
pool is made again whole. RX_VK_DESC_POOL_GROW=0: whole from the start.

Compiles a small driver against the header and checks the rule: the switch (on unless 0), the first shift, the sizes at
each shift and under RX_VK_DESC_POOL_DIV (never 0), when a pool is made again, which descriptor type counts where, the
recordings' counts and their peaks.

Reads the source: make_pool takes the shift and sizes by the header; the extra pool of bind_descriptors is a whole one
and the set is counted after it; slot_reset_locked makes the whole pool before it lets the half one go and resets
otherwise; draw_begin_recording gives a new slot the first shift, by the switch read once, and logs the counts in a
"recording streams" line; the switches table has the three rows' names.

Runs the two cases of tests/test_recording_admission.py that drive the real make_pool, bind_descriptors' tail,
slot_reset_locked and draw_begin_recording on a fake driver (pool-grow, and pool-grow-off with the switch at 0).

    python -I -B tests/test_desc_pool_grow.py --headers <Vulkan include folder> [--cxx clang++]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{vulkan_headers}"]

DRIVER = r'''
#include "desc_pool_grow.h"
#include <cstdio>

using namespace mkwvk::desc_pool_grow;
static int checks, fails;
static void want(const char* what, bool ok) {
    checks++;
    if (!ok) fails++, printf("FAIL %s\n", what);
}
struct Write { int descriptorType; unsigned descriptorCount; };

int main() {
    want("on when unset", on(nullptr));
    want("on at 1", on("1"));
    want("off at 0", !on("0"));
    want("a new slot: half with the rule", first_shift(true) == 1);
    want("a new slot: whole without it", first_shift(false) == 0);
    // the sizes: whole as before, half of each at shift 1, an n-th under the divider, never none
    want("whole sets", count(kSets, 0, 1) == 8192);
    want("half sets", count(kSets, 1, 1) == 4096);
    static const unsigned whole[kKinds] = {32768, 16384, 32768, 4096, 2048, 2048};
    for (int k = 0; k < kKinds; k++) {
        want("a whole pool's descriptors are as they were", count(kWhole[k], 0, 1) == whole[k]);
        want("half of each type", count(kWhole[k], 1, 1) == whole[k] / 2);
        want("divided as before when whole", count(kWhole[k], 0, 4) == whole[k] / 4);
        want("the divider and the half together", count(kWhole[k], 1, 32) == whole[k] / 64);
        want("never none", count(kWhole[k], 8, 32) >= 1 && count(kWhole[k], 40, 32) >= 1 && count(kWhole[k], 1, 0) == whole[k] / 2);
    }
    // made again whole: only a pool that is not whole, of a slot whose last recording had extra pools
    want("a half pool that ran out", remake(1, 1) && remake(1, 3));
    want("a half pool that did not", !remake(1, 0));
    want("a whole pool that ran out", !remake(0, 1));
    want("a whole pool that did not", !remake(0, 0));
    // which type counts where (VkDescriptorType's numbers)
    want("kinds", kind(6) == kUniform && kind(7) == kStorage && kind(1) == kSampled && kind(3) == kStorageImage &&
                  kind(4) == kUniformTexel && kind(5) == kStorageTexel && kind(0) == kKinds && kind(2) == kKinds && kind(1000) == kKinds);
    // a recording's counts and the peaks
    Took a, b, most;
    const Write w1[] = {{6, 4}, {1, 9}, {1, 2}, {0, 5}};
    const Write w2[] = {{7, 3}, {5, 1}};
    took(a, w1, 4), took(a, w2, 2), took(b, w1, 4);
    want("sets counted", a.sets == 2 && b.sets == 1);
    want("descriptors by type", a.n[kUniform] == 4 && a.n[kSampled] == 11 && a.n[kStorage] == 3 && a.n[kStorageTexel] == 1 &&
                                a.n[kStorageImage] == 0 && a.n[kUniformTexel] == 0);
    peak(most, b), peak(most, a), peak(most, b);
    want("the peaks are the most of each", most.sets == 2 && most.n[kSampled] == 11 && most.n[kUniform] == 4 && most.n[kStorage] == 3);
    Took big;
    big.sets = 289, big.n[kSampled] = 17251;   // (Source A's busiest recording: fits a whole pool, not half of the sampled images)
    want("a busy recording outgrows the half", fits(big, 0, 1) && !fits(big, 1, 1));
    Took small;
    small.sets = 289, small.n[kSampled] = 9000;
    want("an ordinary one fits it", fits(small, 1, 1) && !fits(small, 1, 4));
    if (fails) printf("desc pool grow: FAILED (%d of %d checks)\n", fails, checks);
    else printf("desc pool grow: all %d checks passed\n", checks);
    return fails != 0;
}
'''


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


def ordered(text, parts, why):
    at = [text.find(p) for p in parts]
    need(min(at) >= 0 and at == sorted(at), why)


def check_source():
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    need('#include "desc_pool_grow.h"' in draw, "vk_draw.cpp does not include desc_pool_grow.h")
    need('static const bool on = desc_pool_grow::on(getenv("RX_VK_DESC_POOL_GROW"));' in block(draw, "bool pool_grow_on() {"),
         "the switch is not RX_VK_DESC_POOL_GROW, read once")
    res = block(draw, "struct RecordingRes {")
    need("uint32_t shift = 0;" in res and "desc_pool_grow::Took took;" in res, "RecordingRes does not keep its pool's shift and its counts")
    pool = block(draw, "VkDescriptorPool make_pool(uint32_t shift = 0) {")
    need("ci.maxSets = grow::count(grow::kSets, shift, div);" in pool and "grow::count(grow::kWhole[kind], shift, div)" in pool,
         "make_pool does not size the pool by the header with its shift")
    need('getenv("RX_VK_DESC_POOL_DIV")' in pool, "RX_VK_DESC_POOL_DIV no longer divides")
    for gone in ("32768", "8192 / div"):
        need(gone not in pool.split("static const uint32_t div")[1], "make_pool still has a size of its own: " + gone)
    bind = block(draw, "bool bind_descriptors(")
    ordered(bind, ["if (vkAllocateDescriptorSets(dev.device, &ai, &set) != VK_SUCCESS) {", "const VkDescriptorPool pool = make_pool();",
                   "cur->extra.push_back(pool);", "pool_took(dwr.writes.data(), dwr.writes.size());", "set_write_template(set, p)"],
            "bind_descriptors: the extra pool is not a whole one, or the set is not counted once it is allocated")
    need("desc_pool_grow::took(cur->took, writes, n);" in block(draw, "void pool_took("), "pool_took does not count into the recording's own")
    reset = block(draw, "void slot_reset_locked(RecordingRes& r) {")
    ordered(reset, ["if (desc_pool_grow::remake(r.shift, r.extra.size())) {", "if (const VkDescriptorPool made = make_pool(0)) {",
                    "vkDestroyDescriptorPool(dev.device, r.pool, nullptr);", "r.pool = made, r.shift = 0, whole = true;", "pools_whole++;",
                    "if (!whole) vkResetDescriptorPool(dev.device, r.pool, 0);", "pools_added += r.extra.size();",
                    "for (VkDescriptorPool p : r.extra) vkDestroyDescriptorPool(dev.device, p, nullptr);", "r.extra.clear();"],
            "slot_reset_locked does not make the whole pool before it lets the half one go, reset otherwise, and count")
    begin = block(draw, "void draw_begin_recording(int slot, VkCommandBuffer cmd, uint64_t value) {")
    ordered(begin, ["if (!r.pool) {", "r.shift = desc_pool_grow::first_shift(pool_grow_on());", "r.pool = make_pool(r.shift);",
                    "} else if (r.reset_ahead) {", "desc_pool_grow::peak(pool_most, r.took);", "r.took = {};",
                    'logf("vk: the recording streams: ', "logf(\"vk: the recording streams' descriptor pools: ", "pools_whole",
                    "pools_added", "pool_most.sets", "pool_most.n[desc_pool_grow::kSampled]"],
            "draw_begin_recording does not make a new slot's pool at the first shift, or its line lost the counts")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    for name in ("`RX_VK_DESC_POOL_GROW=0`", "`RX_VK_DESC_POOL_DIV=<1..32>`", "`RX_VK_STREAM_MB=<MB>`", "`gpu/vk/desc_pool_grow.h`"):
        need(name in docs, "docs/development.md: the switches table has no " + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    parser.add_argument("--headers", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="desc-pool-grow-") as tmp:
        cpp, exe = Path(tmp) / "desc_pool_grow_test.cpp", Path(tmp) / "desc-pool-grow.exe"
        cpp.write_text(DRIVER, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "gpu/vk"), str(cpp), "-o", str(exe)],
                       check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.returncode:
            raise SystemExit("FAIL: the half pool rule's checks failed")
    check_source()
    for case in ("pool-grow", "pool-grow-off"):
        subprocess.run([sys.executable, "-I", "-B", str(ROOT / "tests/test_recording_admission.py"), "--cxx", args.cxx,
                        "--headers", str(args.headers), "--case", case], check=True)
    print("PASS: the slots' descriptor pools start at half and are whole after a recording ran out; RX_VK_DESC_POOL_GROW=0 as before")


if __name__ == "__main__":
    main()
