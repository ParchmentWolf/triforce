// tests/test_page_table_stream.py puts vk_memory.cpp's own page table code (TableRun to memory_table_flush) in the place of
// ACTUAL and runs its flush, streamed (gpu/vk/table_stream.h) and sorted as it was, on the same changes. No game, no GPU.
// (Triforce, 11-22, the performance audit's SYNC-04, after Source A's.)
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <new>
#include <string>
#include <utility>
#include <vector>
#include "table_stream.h"

// (the largest single allocation while `tracking` is set: the flush's scratch)
static bool tracking = false;
static size_t largest = 0;
static void* counted(size_t n) {
    if (tracking && n > largest) largest = n;
    void* p = std::malloc(n ? n : 1);
    if (!p) std::abort();
    return p;
}
void* operator new(size_t n) { return counted(n); }
void* operator new[](size_t n) { return counted(n); }
void* operator new(size_t n, const std::nothrow_t&) noexcept { return counted(n); }
void* operator new[](size_t n, const std::nothrow_t&) noexcept { return counted(n); }
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p, size_t) noexcept { std::free(p); }
void operator delete[](void* p, size_t) noexcept { std::free(p); }

namespace fixture {
int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)

uint64_t* guest_pages = nullptr;   // (nothing is written at once here: every change goes through the flush)
using VkBuffer = int;
using VkCommandBuffer = int;
VkBuffer guest_pages_buffer = 7;
std::atomic<bool> par_active{false};
// ((Triforce) RX_VK_GP_TABLE's cover, which the cut part feeds and these checks do not use: off)
std::atomic<bool> table_cover_on{false};
void table_mark_changed(uint64_t, uint64_t) {}
void table_flushed_keep() {}
struct Update {
    uint64_t first;
    std::vector<uint64_t> values;
    bool operator==(const Update& o) const { return first == o.first && values == o.values; }
};
std::vector<Update> updates;
size_t largest_update = 0;
void vkCmdUpdateBuffer(VkCommandBuffer, VkBuffer b, uint64_t offset, uint64_t bytes, const void* data) {
    CHECK(b == guest_pages_buffer && offset % 8 == 0 && bytes % 8 == 0 && bytes > 0);
    largest_update = std::max<size_t>(largest_update, (size_t)bytes);
    const bool was = tracking;
    tracking = false;   // (the stand-in's own copy is not the flush's scratch)
    updates.push_back({offset / 8, std::vector<uint64_t>((const uint64_t*)data, (const uint64_t*)data + bytes / 8)});
    tracking = was;
}
VkCommandBuffer upload_command_buffer() { return 1; }
struct GprofSpan {
    int items = 0;
    uint64_t bytes = 0;
    GprofSpan(VkCommandBuffer, const char*) {}
};
void logf(const char*, ...) {}

/* ACTUAL */

uint64_t rnd_state = 0xD1B54A32D192ED03ull;
uint64_t rnd() {
    rnd_state ^= rnd_state << 13, rnd_state ^= rnd_state >> 7, rnd_state ^= rnd_state << 17;
    return rnd_state;
}
const uint64_t kNone = ~0ull;   // (a page no change touched)

/// The runs flushed both ways: the same transfers, entry for entry, no transfer over 64 KiB, and the table they leave is
/// the last writer's of every page
void both_ways(const std::vector<TableRun>& runs, uint64_t span) {
    std::vector<uint64_t> model(span, kNone);
    for (const TableRun& r : runs)
        for (uint64_t i = 0; i < r.count; i++) model[r.first + i] = r.address ? r.address + (i << 12) : 0;
    updates.clear(), largest_update = 0;
    table_pending = runs;
    const bool any = memory_table_flush();
    CHECK(any == !runs.empty() && table_pending.empty());
    const std::vector<Update> streamed = updates;
    CHECK(largest_update <= 65536);
    std::vector<uint64_t> table(span, kNone);
    uint64_t next_free = 0;
    for (const Update& u : streamed) {
        CHECK(u.first >= next_free);   // (ascending, no page twice)
        for (size_t i = 0; i < u.values.size(); i++) table[u.first + i] = u.values[i];
        next_free = u.first + u.values.size();
    }
    CHECK(table == model);
    updates.clear();
    table_pending = runs;
    if (!runs.empty()) table_flush_sorted();
    CHECK(table_pending.empty());
    CHECK(updates == streamed);
}

int run(int argc, char** argv) {
    const std::string test = argc == 2 ? argv[1] : "";
    if (test == "random") {
        // 50 trials of 128 runs: anywhere in 4,000 pages, so most overlap, in any order
        for (int t = 0; t < 50; t++) {
            std::vector<TableRun> runs;
            for (int i = 0; i < 128; i++) {
                const uint64_t count = rnd() % 5 == 0 ? rnd() % 1200 : rnd() % 40;   // (some of 0 pages)
                const uint64_t first = rnd() % (4000 - count);
                runs.push_back({first, count, rnd() % 4 == 0 ? 0 : ((rnd() % 0xFFFFFF) + 1) << 12});
            }
            both_ways(runs, 4000);
        }
        // in page order and apart (the usual case: no sweep), some touching, some with gaps, some long
        for (int t = 0; t < 50; t++) {
            std::vector<TableRun> runs;
            uint64_t at = rnd() % 16;
            for (int i = 0; i < 128; i++) {
                const uint64_t count = rnd() % 9 == 0 ? 8000 + rnd() % 9000 : rnd() % 64;
                runs.push_back({at, count, rnd() % 4 == 0 ? 0 : ((rnd() % 0xFFFFFF) + 1) << 12});
                at += count + (rnd() % 3 == 0 ? rnd() % 50 : 0);
            }
            both_ways(runs, at + 1);
            // and the same runs with two of them swapped, or one repeated: the sweep
            std::swap(runs[rnd() % 128], runs[rnd() % 128]);
            runs.push_back(runs[rnd() % 128]);
            runs.back().address = 0x7770000000ull;
            both_ways(runs, at + 1);
        }
        // 256 single pages in any order, some twice
        std::vector<TableRun> singles;
        for (int i = 0; i < 256; i++) singles.push_back({rnd() % 300, 1, ((rnd() % 0xFFFF) + 1) << 12});
        both_ways(singles, 300);
        both_ways({}, 1);
        both_ways({{5, 0, 0x1000}}, 8);
        both_ways({{0, 8192, 0x4000000}, {8192, 1, 0x9000000}}, 8200);   // (a full transfer, then one entry)
        std::printf("ok: the streamed flush writes the sorted flush's transfers, entry for entry\n");
    } else if (test == "four" || test == "four-sorted") {
        // four overlapping ranges over 150,000 pages (a pool set, zeroed at its merge and set again in parts)
        const std::vector<TableRun> runs = {{0, 150000, 0x100000000ull}, {20000, 70000, 0}, {50000, 70000, 0x900000000ull}, {100000, 50000, 0xA00000000ull}};
        table_pending = runs;
        updates.clear(), largest = 0;
        tracking = true;
        if (test == "four") memory_table_flush();   // (as the process's environment says: streamed unless RX_VK_TABLE_STREAM=0)
        else table_flush_sorted();
        tracking = false;
        std::printf("largest %zu\n", largest);
        const std::vector<Update> got = updates;
        updates.clear();
        table_pending = runs;
        table_flush_sorted();
        CHECK(got == updates && !got.empty());
    } else {
        std::printf("a known case\n");
        return 1;
    }
    return fails != 0;
}
} // namespace fixture
int main(int argc, char** argv) { return fixture::run(argc, argv); }
