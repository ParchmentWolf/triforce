"""A capture's buffer: made with the spares' lock let go, a load's big spare left alone, the spare a load took made again
(gpu/vk/cap_spare.h, vk_memory.cpp cap_buf_get, cap_prewarm_class, cap_spare_make and cap_buf_free; no game, no GPU).

(Triforce, 11-22, the performance audit's MEM-33, after Source A's.) With no spare that fits, cap_buf_get made the buffer
on the game's submitting thread with cap_free_mu held, and the replay's take, holding pools_mu, waits on that mutex to
give a buffer back. Any spare that fit was taken, so a small capture could hold a load's 192 MB spare for the 24
submissions it is kept; and a spare made ahead was made once.

This compiles cap_spare.h and checks its rules against the code as it was on random inputs: pick() with any_size is the
old loop (the smallest that fits, the first of equals), keeps() with nothing reserved is the old limit, pick() with the
skip is the smallest fitting spare that is not a big one over twice the class, and stepped() stays between the need and
the class.

Then it cuts cap_buf_free, cap_buf_size, cap_spare_make, cap_prewarm_class and cap_buf_get out of vk_memory.cpp and runs
them over stand-ins (the worker's thread is a list the test runs by hand):
  - the first capture starts the workers and reserves their bytes; each worker's spare ends its reservation;
  - a 1 MB capture leaves the 32, 64 and 128 MB spares alone and makes its own, with cap_free_mu NOT held;
  - a capture of a 32 MB class takes the 32 MB spare, and no worker starts while a bigger spare is there; one of a 128
    MB class takes the 128 MB spare and a worker of 128 MB starts;
  - the allocation fails: the big spare is taken after all; with no spare, the exact size without a memory object of
    its own; a buffer made but not mapped is destroyed, not lost;
  - what is being made counts: a buffer given back is not kept past the limit a worker's spare is about to fill, the
    worker's spare is kept, no worker starts without room, and a worker that gets no buffer frees its reservation;
  - spares capped at 32 MB: any spare is taken, as before; steps only with RX_VK_CAP_STEP_MB;
  - RX_VK_CAP_SPARE_FIT=0: any fitting spare, no worker at a take, the buffer made with the lock held, nothing reserved.

And reads the source: the switches, the 600-take count, the switches table.

    python -I -B tests/test_capture_spare_reuse.py [--cxx clang++]
"""
import argparse
import os
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


def line(text, marker):
    check(marker in text, "vk_memory.cpp has no " + marker)
    start = text.index(marker)
    return text[start:text.index("\n", start)]


HEAD = r"""
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <set>
#include <string>
#include <thread>
#include <vector>
#include "cap_spare.h"
// ((Triforce, 11-22) MEM-141's swap hold, merged into cap_buf_free: off, as it always is on Windows
#include "linux_pressure.h"
static bool memory_swap_hold() { return false; }
static void memory_swap_valve(int, uint64_t) {}
typedef uint64_t VkBuffer;
typedef void* VmaAllocation;
typedef unsigned VkBufferUsageFlags;
#define VK_NULL_HANDLE 0
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
static const uint64_t MB = 1ull << 20;

struct FreeBuf { VkBuffer buffer; VmaAllocation alloc; void* map; uint64_t size; };
std::vector<FreeBuf> cap_free;
std::atomic<bool> cap_shutting_down{false};
std::mutex cap_free_mu;
uint64_t cap_free_bytes = 0;
uint64_t cap_reserved_bytes = 0;
size_t cap_reserved_n = 0;
std::atomic<uint64_t> cap_made_n{0}, cap_made_us{0};
std::atomic<int> cap_prewarm_busy{0};
std::atomic<int> cap_prewarm_class_busy[4]{};

// the stand-ins
static uint64_t spare_max_v = ~0ull, step_v = 0;
static bool fit_v = true, prewarm_v = true;
uint64_t cap_spare_max() { return spare_max_v; }
bool cap_spare_fit_on() { return fit_v; }
uint64_t cap_step_mb() { return step_v; }
bool cap_prewarm_on() { return prewarm_v; }
bool cap_free_async_on() { return false; }
VkBufferUsageFlags cap_usage() { return 0; }
void cap_exit_note() {}
void logf(const char*, ...) {}
static std::vector<VkBuffer> destroyed;
void destroy_buffer(VkBuffer b, VmaAllocation) { destroyed.push_back(b); }
void destroy_buffer_later(VkBuffer b, VmaAllocation, uint64_t) { destroyed.push_back(b); }
struct Made { uint64_t size; bool own, lock_held; VkBuffer id; };
static std::vector<Made> made;
static std::set<uint64_t> fail_sizes, unmapped_sizes;
static bool fail_all = false;
static VkBuffer next_id = 100;
bool cap_buf_make(uint64_t size, VkBuffer& buffer, VmaAllocation& allocation, void** mapped, bool dedicated) {   // (the capture buffers' maker)
    const bool held = !cap_free_mu.try_lock();   // (is the spares' lock held by the caller, the only thread here)
    if (!held) cap_free_mu.unlock();
    if (fail_all || fail_sizes.count(size)) {
        made.push_back({size, dedicated, held, 0});
        buffer = VK_NULL_HANDLE, allocation = nullptr;
        return false;
    }
    buffer = next_id++, allocation = (void*)&made;
    made.push_back({size, dedicated, held, buffer});
    if (mapped) *mapped = unmapped_sizes.count(size) ? nullptr : (void*)&made;
    return true;
}
struct Spawn { uint64_t bytes; int index; };
static std::vector<Spawn> spawned;   // (the workers' threads: run by hand)
"""

TAIL = r"""
static void reset(uint64_t spare_max, bool fit, uint64_t step = 0) {
    cap_free.clear(), cap_free_bytes = 0, cap_reserved_bytes = 0, cap_reserved_n = 0;
    spawned.clear(), made.clear(), destroyed.clear(), fail_sizes.clear(), unmapped_sizes.clear();
    spare_max_v = spare_max, fit_v = fit, step_v = step, fail_all = false;
    cap_prewarm_busy = 0;
    for (auto& b : cap_prewarm_class_busy) b = 0;
}
static VkBuffer spare(uint64_t mb) {
    cap_free.push_back({next_id, nullptr, (void*)&made, mb * MB});
    cap_free_bytes += mb * MB;
    return next_id++;
}
static void run_workers() {
    const std::vector<Spawn> s = spawned;
    spawned.clear();
    for (const Spawn& w : s) cap_spare_make(w.bytes, w.index);
}
static bool has_spare(uint64_t mb) {
    for (const FreeBuf& f : cap_free)
        if (f.size == mb * MB) return true;
    return false;
}
struct Got { bool ok; VkBuffer buffer; VmaAllocation alloc; void* map; uint64_t size; };
static Got get(uint64_t need) {
    Got g{false, 0, nullptr, nullptr, 0};
    g.ok = cap_buf_get(need, g.buffer, g.alloc, g.map, g.size);
    return g;
}
static uint64_t rnd_state = 0x9E3779B97F4A7C15ull;
static uint64_t rnd() {
    rnd_state ^= rnd_state << 13, rnd_state ^= rnd_state >> 7, rnd_state ^= rnd_state << 17;
    return rnd_state;
}

int main() {
    // ---- the rules against the code as it was, on random inputs ----
    static const uint64_t kSizes[] = {1, 2, 4, 8, 16, 20, 32, 48, 64, 100, 128, 192, 256};   // (no spare is over 256 MB)
    for (int t = 0; t < 20000; t++) {
        std::vector<uint64_t> sizes(rnd() % 13);
        for (uint64_t& s : sizes) s = kSizes[rnd() % 13] * MB;
        const uint64_t need = (rnd() % (260 * 256) + 1) * 4096;
        uint64_t cls = 2 * MB;   // (cap_buf_size without its switches)
        while (cls < need && cls < 16 * MB) cls <<= 1;
        if (cls < need) {
            cls = (need + MB - 1) & ~(MB - 1);
            for (uint64_t c : {32, 64, 128, 192, 256})
                if (c * MB >= need) { cls = c * MB; break; }
        }
        const auto size_of = [&](size_t i) { return sizes[i]; };
        size_t old_best = sizes.size();   // (the loop as it was)
        for (size_t i = 0; i < sizes.size(); i++)
            if (sizes[i] >= need && (old_best == sizes.size() || sizes[i] < sizes[old_best])) old_best = i;
        CHECK(cap_spare::pick(sizes.size(), size_of, need, cls, true) == old_best);
        size_t want = sizes.size();   // (with the skip: the smallest that fits and is not a big one over twice the class)
        for (size_t i = 0; i < sizes.size(); i++) {
            if (sizes[i] < need || (sizes[i] >= 32 * MB && sizes[i] > 2 * cls)) continue;
            if (want == sizes.size() || sizes[i] < sizes[want]) want = i;
        }
        const size_t got = cap_spare::pick(sizes.size(), size_of, need, cls, false);
        CHECK(got == want);
        if (got != sizes.size()) CHECK(sizes[got] >= need && old_best != sizes.size() && sizes[got] >= sizes[old_best]);
        if (cls >= 128 * MB) CHECK(got == old_best);   // (nothing kept is over twice a class of 128 MB or more)
        // the limit as it was, with nothing being made
        const size_t n = rnd() % 14;
        const uint64_t held = (rnd() % 900) * MB, size = kSizes[rnd() % 13] * MB;
        static const uint64_t kMax[] = {~0ull, 32ull << 20, 12ull << 20, 512ull << 20, 2048ull << 20};
        const uint64_t spare_max = kMax[rnd() % 5];
        for (int keep_old = 0; keep_old < 2; keep_old++) {
            const bool was = n < 12 && size <= (keep_old ? 64ull << 20 : 256ull << 20) &&
                             held + size <= std::min<uint64_t>(spare_max, keep_old ? ~0ull : 768ull << 20);
            CHECK(cap_spare::keeps(n, 0, held, 0, size, spare_max, keep_old != 0) == was);
            // and what is being made counts as if it were held already
            const size_t workers = rnd() % 4;
            const uint64_t reserved = (rnd() % 300) * MB;
            const bool with = n + workers < 12 && size <= (keep_old ? 64ull << 20 : 256ull << 20) &&
                              held + reserved + size <= std::min<uint64_t>(spare_max, keep_old ? ~0ull : 768ull << 20);
            CHECK(cap_spare::keeps(n, workers, held, reserved, size, spare_max, keep_old != 0) == with);
            CHECK(cap_spare::room(held, reserved, size, spare_max) == (held + reserved + size <= std::min<uint64_t>(spare_max, 768ull << 20)));
        }
        const uint64_t step = rnd() % 9;
        for (int capped = 0; capped < 2; capped++) {
            const uint64_t s = cap_spare::stepped(need, cls, step, capped != 0);
            CHECK(s >= need && s <= cls);
            if (!step || !capped || need <= 16 * MB || need > 32 * MB) CHECK(s == cls);
            else CHECK(s == cls || (s % (step * MB) == 0 && s - need < step * MB));
        }
    }
    CHECK(cap_spare::skips(192 * MB, 32 * MB, false) && !cap_spare::skips(64 * MB, 32 * MB, false) && cap_spare::skips(32 * MB, 2 * MB, false));
    CHECK(!cap_spare::skips(192 * MB, 32 * MB, true) && !cap_spare::skips(16 * MB, 2 * MB, false) && !cap_spare::skips(256 * MB, 128 * MB, false));
    CHECK(cap_spare::stepped(17 * MB, 32 * MB, 4, true) == 20 * MB && cap_spare::stepped(17 * MB, 32 * MB, 0, true) == 32 * MB);
    CHECK(cap_spare::stepped(17 * MB, 32 * MB, 4, false) == 32 * MB && cap_spare::stepped(31 * MB, 32 * MB, 4, true) == 32 * MB);
    CHECK(cap_spare::stepped(16 * MB, 16 * MB, 4, true) == 16 * MB && cap_spare::stepped(40 * MB, 64 * MB, 4, true) == 64 * MB);

    // ---- the cut code ----
    {   // the first capture: the workers start, their bytes reserved; the capture's own buffer is made with the lock let go
        reset(~0ull, true);
        const Got g = get(1 * MB);
        CHECK(g.ok && g.size == 2 * MB && made.size() == 1 && made[0].size == 2 * MB && !made[0].own && !made[0].lock_held);
        CHECK(spawned.size() == 3 && spawned[0].bytes == 32 * MB && spawned[1].bytes == 64 * MB && spawned[2].bytes == 128 * MB);
        CHECK(cap_reserved_bytes == 224 * MB && cap_reserved_n == 3 && cap_made_n.load() == 1);
        run_workers();
        CHECK(cap_reserved_bytes == 0 && cap_reserved_n == 0 && cap_free.size() == 3 && cap_free_bytes == 224 * MB);
        CHECK(cap_prewarm_busy.load() == 0 && has_spare(32) && has_spare(64) && has_spare(128) && destroyed.empty());
        CHECK(made.size() == 4 && made[1].own && !made[1].lock_held);   // (the workers' are not the submitting thread's count)
        CHECK(cap_made_n.load() == 1);

        // a 1 MB capture leaves the three big spares alone
        const Got small = get(1 * MB);
        CHECK(small.ok && small.size == 2 * MB && cap_free.size() == 3 && made.size() == 5 && !made[4].lock_held && spawned.empty());
        // a capture of the 32 MB class takes the 32 MB spare; a bigger spare is still there: no worker
        const Got mid = get(20 * MB);
        CHECK(mid.ok && mid.size == 32 * MB && cap_free.size() == 2 && !has_spare(32) && made.size() == 5 && spawned.empty());
        // a capture of the 128 MB class takes the 128 MB spare: a worker of 128 MB starts, its bytes reserved
        const Got big = get(100 * MB);
        CHECK(big.ok && big.size == 128 * MB && cap_free.size() == 1 && made.size() == 5);
        CHECK(spawned.size() == 1 && spawned[0].bytes == 128 * MB && spawned[0].index == 2 && cap_reserved_bytes == 128 * MB && cap_reserved_n == 1);
        run_workers();
        CHECK(has_spare(128) && cap_reserved_bytes == 0 && cap_reserved_n == 0);
        // a capture of the 64 MB class: the 64 MB spare, not the 128 MB one
        const Got c64 = get(40 * MB);
        CHECK(c64.ok && c64.size == 64 * MB && has_spare(128) && spawned.empty());
    }
    {   // the allocation fails: the big spare after all, and a worker for the one taken
        reset(~0ull, true);
        const VkBuffer s192 = spare(192);
        fail_sizes.insert(32 * MB);
        const Got g = get(20 * MB);
        CHECK(g.ok && g.buffer == s192 && g.size == 192 * MB && cap_free.empty() && cap_free_bytes == 0);
        CHECK(made.size() == 1 && made[0].size == 32 * MB && made[0].own && !made[0].lock_held);
        CHECK(spawned.size() == 1 && spawned[0].bytes == 192 * MB && spawned[0].index == 3);
    }
    {   // no spare either: the exact size, without a memory object of its own, the lock let go
        reset(~0ull, true);
        fail_sizes.insert(32 * MB);
        const uint64_t need = 20 * MB + 4096;
        const Got g = get(need);
        CHECK(g.ok && g.size == need && made.size() == 2 && made[1].size == need && !made[1].own && !made[1].lock_held);
        reset(~0ull, true);
        fail_all = true;
        const Got none = get(need);
        CHECK(!none.ok && made.size() == 2);
    }
    {   // made but not mapped: destroyed, then the exact size
        reset(~0ull, true);
        unmapped_sizes.insert(2 * MB);
        const Got g = get(1 * MB + 4096);
        CHECK(g.ok && g.size == 1 * MB + 4096 && made.size() == 2 && destroyed.size() == 1 && destroyed[0] == made[0].id && g.buffer == made[1].id);
    }
    {   // what is being made counts with what is held
        reset(256 * MB, true);
        spare(64);
        {
            std::lock_guard lk(cap_free_mu);
            cap_prewarm_class(128 * MB);
        }
        CHECK(spawned.size() == 1 && cap_reserved_bytes == 128 * MB && cap_reserved_n == 1);
        cap_buf_free(900, nullptr, (void*)&made, 100 * MB);   // (64 held + 128 being made + 100 > 256: not kept)
        CHECK(destroyed.size() == 1 && destroyed[0] == 900 && cap_free.size() == 1);
        cap_buf_free(901, nullptr, (void*)&made, 64 * MB);    // (64 + 128 + 64 = 256: kept)
        CHECK(destroyed.size() == 1 && cap_free.size() == 2 && cap_free_bytes == 128 * MB);
        {
            std::lock_guard lk(cap_free_mu);
            cap_prewarm_class(32 * MB);   // (no room: 128 held + 128 being made + 32 > 256. And a spare of 64 MB is there)
            cap_prewarm_class(192 * MB);
        }
        CHECK(spawned.size() == 1);
        run_workers();   // (the worker's 128 MB lands and is kept: its room was reserved)
        CHECK(destroyed.size() == 1 && cap_free.size() == 3 && cap_free_bytes == 256 * MB && cap_reserved_bytes == 0 && cap_reserved_n == 0);
        // twelve with the one being made
        reset(~0ull, true);
        for (int i = 0; i < 11; i++) spare(2);
        {
            std::lock_guard lk(cap_free_mu);
            cap_prewarm_class(32 * MB);
        }
        CHECK(spawned.size() == 1 && cap_reserved_n == 1);
        cap_buf_free(902, nullptr, (void*)&made, 2 * MB);
        CHECK(destroyed.size() == 1 && cap_free.size() == 11);
        run_workers();
        CHECK(destroyed.size() == 1 && cap_free.size() == 12 && has_spare(32));
        // a worker that gets no buffer frees what it reserved
        reset(~0ull, true);
        {
            std::lock_guard lk(cap_free_mu);
            cap_prewarm_class(64 * MB);
        }
        CHECK(cap_reserved_bytes == 64 * MB);
        fail_all = true;
        run_workers();
        CHECK(cap_reserved_bytes == 0 && cap_reserved_n == 0 && cap_free.empty() && cap_prewarm_busy.load() == 0);
    }
    {   // spares capped at 32 MB: any spare is taken, as before; a 32 MB class capture's spare is made again
        reset(32 * MB, true);
        const VkBuffer s32 = spare(32);
        const Got g = get(1 * MB);
        CHECK(g.ok && g.buffer == s32 && made.empty() && spawned.empty());
        reset(32 * MB, true);
        spare(32);
        const Got h = get(20 * MB);
        CHECK(h.ok && h.size == 32 * MB && made.empty() && spawned.size() == 1 && spawned[0].bytes == 32 * MB);
        // steps only with the switch, and only where spares are capped
        reset(32 * MB, true, 4);
        const Got st = get(17 * MB);
        CHECK(st.ok && st.size == 20 * MB && made.size() == 1 && made[0].own);
        reset(32 * MB, true, 0);
        CHECK(get(17 * MB).size == 32 * MB);
        reset(~0ull, true, 4);
        CHECK(get(17 * MB).size == 32 * MB);
        reset(32 * MB, false, 4);
        CHECK(get(17 * MB).size == 32 * MB);
    }
    {   // RX_VK_CAP_SPARE_FIT=0: as before
        reset(~0ull, false);
        const VkBuffer s192 = spare(192);
        const Got g = get(1 * MB);
        CHECK(g.ok && g.buffer == s192 && made.empty() && spawned.empty() && cap_reserved_bytes == 0);
        const Got n = get(1 * MB);
        CHECK(n.ok && n.size == 2 * MB && made.size() == 1 && made[0].lock_held && !made[0].own);
        const Got big = get(100 * MB);
        CHECK(big.ok && big.size == 128 * MB && made.size() == 2 && made[1].lock_held && made[1].own && spawned.empty());
        reset(256 * MB, false);
        spare(64);
        {
            std::lock_guard lk(cap_free_mu);
            cap_prewarm_class(128 * MB);
        }
        CHECK(spawned.size() == 1 && cap_reserved_bytes == 0 && cap_reserved_n == 0);
        cap_buf_free(903, nullptr, (void*)&made, 100 * MB);   // (kept: nothing is counted for the worker)
        CHECK(destroyed.empty() && cap_free.size() == 2);
        run_workers();   // (and the worker's spare is destroyed as it lands: what the reservation is for)
        CHECK(destroyed.size() == 1 && cap_free.size() == 2 && cap_reserved_bytes == 0);
    }
    if (fails) std::printf("capture spares: FAILED (%d checks)\n", fails);
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    mem = (VK / "vk_memory.cpp").read_text(encoding="utf-8")
    check((VK / "cap_spare.h").exists(), "gpu/vk/cap_spare.h is missing")
    check('#include "cap_spare.h"' in mem, "vk_memory.cpp does not include cap_spare.h")

    # the source
    on = block(mem, "bool cap_spare_fit_on() {")
    check('getenv("RX_VK_CAP_SPARE_FIT")' in on and "!(e && *e && atoi(e) == 0)" in on and "static const bool on" in on,
          "RX_VK_CAP_SPARE_FIT is not on unless set to 0, or is read more than once")
    step = block(mem, "uint64_t cap_step_mb() {")
    check('getenv("RX_VK_CAP_STEP_MB")' in step and "e && atoi(e) > 0 ? (uint64_t)atoi(e) : 0" in step and "static const uint64_t v" in step,
          "RX_VK_CAP_STEP_MB is not off unless set, or is read more than once")
    for decl in ("uint64_t cap_reserved_bytes = 0;", "size_t cap_reserved_n = 0;", "std::atomic<uint64_t> cap_made_n{0}, cap_made_us{0};"):
        check(decl in mem, "vk_memory.cpp has no " + decl)
    get = block(mem, "bool cap_buf_get(uint64_t need, VkBuffer& buffer, VmaAllocation& alloc, void*& map, uint64_t& size) {")
    order = [get.find(s) for s in (
        "std::unique_lock lk(cap_free_mu);",
        "if (take_spare(!fit || capped)) return map != nullptr;",
        "size = fit ? cap_spare::stepped(need, cls, cap_step_mb(), capped) : cls;",
        "if (!fit) {",
        "lk.unlock();\n    const bool made = cap_buf_make(size, buffer, alloc, &map, own);",
        "if (made && map) return true;",
        "lk.lock();\n    if (take_spare(true)) return map != nullptr;\n    lk.unlock();",
        "return cap_buf_make(size, buffer, alloc, &map, false) && map;")]
    check(min(order) >= 0 and order == sorted(order),
          "cap_buf_get: the spare, then the buffer made with the lock let go, then the two fallbacks, are not there in that order")
    check("if (fit && cls >= cap_spare::kBig) cap_prewarm_class(size);" in get, "a load's spare taken is not made again")
    check("const bool capped = cap_spare_max() <= cap_spare::kBig;" in get, "the skip and the steps do not go by the spares' cap")
    free = block(mem, "void cap_buf_free(VkBuffer buffer, VmaAllocation alloc, void* map, uint64_t size, bool from_worker = false) {")
    # ((Triforce, 11-22) MEM-141 caps the spares while its swap hold is on (never on Windows): spare_cap(false, x) is x
    check("cap_spare::keeps(cap_free.size(), cap_reserved_n, cap_free_bytes, cap_reserved_bytes, size," in free and
          "linux_pressure::spare_cap(swap_hold_on, cap_spare_max()), keep_old)) {" in free,
          "cap_buf_free does not count what is being made")
    cls = block(mem, "void cap_prewarm_class(uint64_t size) {")
    thread_line = "std::thread(cap_spare_make, bytes, index).detach();"
    check(cls.count(thread_line) == 1, "cap_prewarm_class does not start its worker as the test expects")
    check(cls.index("if (fit) cap_reserved_bytes += bytes, cap_reserved_n++;") < cls.index(thread_line),
          "the worker's bytes are not reserved before its thread starts")
    check("made on a submitting thread (600 takes)" in mem and "cap_made_n.load(std::memory_order_relaxed)" in mem,
          "the 600-take line does not count the buffers made on a submitting thread")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_CAP_SPARE_FIT=0`" in dev and "`RX_VK_CAP_STEP_MB=<n>`" in dev, "docs/development.md: the two switches are not in the switches table")

    cut = "\n".join([
        # (the switches' rule the capture's own switches are read by: RX_VK_CAPTURE_KEEP_OLD, RX_VK_CAP_BLOCKS)
        block(mem, "bool env_value_off(const char* v) {"),
        block(mem, "bool env_on(const char* name) {"),
        free,
        block(mem, "uint64_t cap_buf_size(uint64_t need) {"),
        line(mem, "int cap_prewarm_index(uint64_t size) {"),
        block(mem, "void cap_spare_make(uint64_t size, int index) {"),
        cls.replace(thread_line, "spawned.push_back({bytes, index});"),
        get,
    ])
    env = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_")}
    with tempfile.TemporaryDirectory(prefix="cap-spare-") as tmp:
        src, exe = Path(tmp) / "spare.cpp", Path(tmp) / "spare.exe"
        src.write_text(HEAD + cut + TAIL, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-pthread", "-I" + str(VK), str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=120, env=env)
        check(r.returncode == 0, "the capture spares as made:\n" + r.stdout + r.stderr)
    print("PASS: a capture's buffer is made with the spares' lock let go, a load's spare is left alone and made again, and "
          "what is being made counts with the spares")


if __name__ == "__main__":
    main()
