"""The render targets' pool is bound by the allowance, trimmed oldest first, and held in tiers (gpu/vk/target_pool.h,
vk_texture.cpp pool_cap, pool_take, pool_put, pool_trim, texture_frame; no game, no GPU).

(Triforce, 11-21, the performance audit's TEX-29, after Source A's and Source B's.) The pool gives a dead render target's
image to the next target of its shape. It held a fixed 256 MB, kept every image 120 presents, was trimmed in its hash
table's order and emptied above 90% of the allowance: at 2560 x 1440 it destroyed nearly every image it was given.

This compiles target_pool.h alone and checks the rules: allowances of 3, 7 and 12 GB give 256, 597 and 768 MB and an
unknown one 256; the tier is 1 above 90% and 2 above 97%; tier 1 halves the bound and tier 2 leaves none, with the tiers
off any tier leaves none, and with a floor kept the bound stays; a shape never taken goes after 8 presents and one taken
before after 120; 16 images a present, 64 under a tier. And it runs a model of the pool with the same rules, an age list
and the shapes' lists as vk_texture.cpp has them: over the bound the oldest goes first whatever its shape; a one-off
shape is gone after 8 presents while a shape that is taken again is still there; a take gives the newest of its shape.

And reads the source: the bound is the switch or the rule's of the allowance; the trim walks the age list from its front
with the rule's cap, count and wait, and stops at the first image younger than the short wait; a take notes the shape;
the tier is set where the pressure is known; the switches are in the switches table.

    python -I -B tests/test_target_pool_rules.py [--cxx clang++]
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
#include <deque>
#include <list>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include "target_pool.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
using namespace target_pool;

// the pool as vk_texture.cpp keeps it: one list by age, each shape's entries, the shapes taken lately
struct Pooled { uint64_t key; int id; uint64_t bytes, since; };
static std::list<Pooled> age;
static std::unordered_map<uint64_t, std::deque<std::list<Pooled>::iterator>> by_key;
static std::unordered_set<uint64_t> taken;
static uint64_t bytes_held, now;
static std::vector<int> gone;
static void put(uint64_t key, int id, uint64_t bytes) {
    age.push_back({key, id, bytes, now});
    by_key[key].push_back(std::prev(age.end()));
    bytes_held += bytes;
}
static int take(uint64_t key) {
    auto it = by_key.find(key);
    if (it == by_key.end() || it->second.empty()) return -1;
    const auto at = it->second.back();
    const int id = at->id;
    bytes_held -= at->bytes;
    age.erase(at);
    it->second.pop_back();
    if (it->second.empty()) by_key.erase(it);
    taken.insert(key);
    return id;
}
static size_t trim(uint64_t cap, int tier_now, uint64_t idle) {
    const uint64_t bound = cap_for(cap, tier_now, true, false);
    const size_t most = trim_most(tier_now, false);
    size_t n = 0;
    for (auto it = age.begin(); it != age.end() && n < most;) {
        if (bytes_held <= bound && !idle_out(now, it->since, idle, taken.count(it->key) != 0)) {
            if (now - it->since <= idle) break;
            ++it;
            continue;
        }
        auto& v = by_key[it->key];
        for (auto m = v.begin(); m != v.end(); ++m)
            if (*m == it) { v.erase(m); break; }
        if (v.empty()) by_key.erase(it->key);
        gone.push_back(it->id), bytes_held -= it->bytes, n++;
        it = age.erase(it);
    }
    return n;
}

int main() {
    const uint64_t MB = 1ull << 20, GB = 1ull << 30;
    CHECK(default_mb(3 * GB) == 256 && default_mb(7 * GB) == 597 && default_mb(12 * GB) == 768 && default_mb(0) == 256);
    CHECK(default_mb(31419 * MB) == 768 && default_mb(8 * GB) == 682 && default_mb(1 * GB) == 256);
    CHECK(tier(true, 89, 100) == 0 && tier(true, 90, 100) == 0 && tier(true, 91, 100) == 1 && tier(true, 97, 100) == 1);
    CHECK(tier(true, 98, 100) == 2 && tier(false, 99, 100) == 0 && tier(true, 99, 0) == 0);
    CHECK(cap_for(600 * MB, 0, true, false) == 600 * MB && cap_for(600 * MB, 1, true, false) == 300 * MB && cap_for(600 * MB, 2, true, false) == 0);
    CHECK(cap_for(600 * MB, 1, false, false) == 0 && cap_for(600 * MB, 2, false, false) == 0 && cap_for(600 * MB, 0, false, false) == 600 * MB);
    CHECK(cap_for(600 * MB, 1, true, true) == 600 * MB && cap_for(600 * MB, 2, false, true) == 600 * MB);   // (a floor kept: not given back)
    CHECK(trim_most(0, false) == 16 && trim_most(1, false) == 64 && trim_most(2, false) == 64 && trim_most(2, true) == 16);
    CHECK(kIdle == 8 && kIdleTaken == 120);
    CHECK(!idle_out(108, 100, 8, false) && idle_out(109, 100, 8, false));          // (a one-off shape: after 8 presents)
    CHECK(!idle_out(220, 100, 8, true) && idle_out(221, 100, 8, true));            // (a shape taken before: after 120)
    CHECK(!idle_out(340, 100, 240, true) && idle_out(341, 100, 240, true) && idle_out(341, 100, 240, false));   // (a longer wait asked for)

    // the model: over the bound the oldest goes first, whatever its shape
    now = 1;
    put(0xA, 1, 100 * MB), put(0xB, 2, 100 * MB), put(0xA, 3, 100 * MB), put(0xC, 4, 100 * MB);
    CHECK(trim(256 * MB, 0, 8) == 2 && gone.size() == 2 && gone[0] == 1 && gone[1] == 2 && bytes_held == 200 * MB);
    CHECK(by_key.count(0xB) == 0 && by_key[0xA].size() == 1);
    // a take gives the newest of its shape
    put(0xA, 5, 10 * MB);
    CHECK(take(0xA) == 5 && take(0xA) == 3 && take(0xA) == -1 && take(0xD) == -1);
    CHECK(bytes_held == 100 * MB && age.size() == 1);
    // the waits: shape 0xA is taken again, 0xC and 0xE never were
    gone.clear();
    now = 10;
    put(0xA, 6, 10 * MB), put(0xE, 7, 10 * MB);
    now = 18;
    CHECK(trim(256 * MB, 0, 8) == 1 && gone[0] == 4);          // (0xC, in since present 1: long past 8; the others are 8 old)
    now = 19;
    CHECK(trim(256 * MB, 0, 8) == 1 && gone[1] == 7);          // (0xE, never taken, at 9 presents; 0xA's waits on)
    now = 130;
    CHECK(trim(256 * MB, 0, 8) == 0 && age.size() == 1);
    now = 131;
    CHECK(trim(256 * MB, 0, 8) == 1 && gone[2] == 6 && age.empty() && by_key.empty() && bytes_held == 0);
    // a tier: half the bound, then none; 64 a present
    gone.clear();
    for (int i = 0; i < 100; i++) put(0x100 + (uint64_t)i, i, 4 * MB);
    CHECK(trim(256 * MB, 1, 8) == 64 && bytes_held == 36 * 4 * MB);   // (400 MB held, the bound 128: but 64 a present)
    CHECK(trim(256 * MB, 1, 8) == 4 && bytes_held == 128 * MB);       // (to half the bound)
    CHECK(trim(256 * MB, 2, 8) == 32 && bytes_held == 0 && age.empty());
    for (size_t i = 1; i < gone.size(); i++) CHECK(gone[i] == gone[i - 1] + 1);   // (always the oldest next)
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    tex = (VK / "vk_texture.cpp").read_text(encoding="utf-8")

    check('#include "target_pool.h"' in tex and "#include <list>" in tex, "vk_texture.cpp does not use the rules")
    cap = block(tex, "uint64_t pool_cap() {")
    check('getenv("RX_VK_TARGET_POOL_MB")' in cap and "target_pool::default_mb(known ? allowed : 0)" in cap,
          "the bound is not the switch, or the rule's of the allowance")
    take = block(tex, "bool pool_take(")
    check("const std::list<Pooled>::iterator at = it->second.back();" in take and "pool_age.erase(at);" in take and
          "if (pool_taken.insert(key).second) {" in take and "target_pool::kTakenKeys" in take,
          "a take does not give the newest of its shape, leaves it in the age list, or does not note the shape as taken")
    put = block(tex, "void pool_put(Dead& d) {")
    check("pool_age.push_back(Pooled{d.pool_key," in put and "target_pool[d.pool_key].push_back(std::prev(pool_age.end()));" in put,
          "an image put in is not at the back of the age list and of its shape's")
    trim = block(tex, "size_t pool_trim() {")
    at = [trim.index(p) for p in (
        "const uint64_t cap = target_pool::cap_for(pool_cap(), pool_tier, tiers, floor_kept);",
        "const size_t most = target_pool::trim_most(pool_tier, floor_kept);",
        "for (auto it = pool_age.begin(); it != pool_age.end() && n < most;) {",
        "if (pool_bytes <= cap && !target_pool::idle_out(frame_no, it->since, idle, pool_taken.count(it->key) != 0)) {",
        "if (frame_no - it->since <= idle) break;", "pool_destroy(*it);", "it = pool_age.erase(it);")]
    check(at == sorted(at), "the trim does not walk the age list from its front with the rule's bound, count and wait")
    check('getenv("RX_VK_TARGET_POOL_TRIM")' in trim and 'getenv("RX_VK_POOL_IDLE")' in trim and "target_pool::kIdle" in trim,
          "the trim's switches are not read")
    check("pool_tier = target_pool::tier(known, pressure, allowed);" in tex, "the tier is not set where the pressure is known")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_TARGET_POOL_MB=<MB>`, `RX_VK_POOL_IDLE=<presents>`, `RX_VK_TARGET_POOL_TRIM=0`" in dev,
          "docs/development.md: the pool's switches are not in the table")

    with tempfile.TemporaryDirectory(prefix="target-pool-") as tmp:
        c, exe = Path(tmp) / "pool.cpp", Path(tmp) / "pool.exe"
        c.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the rules as made:\n" + r.stdout)
    print("PASS: the render targets' pool is bound by the allowance, trimmed oldest first, and held in tiers")


if __name__ == "__main__":
    main()
