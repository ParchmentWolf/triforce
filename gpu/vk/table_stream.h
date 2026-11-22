// (Triforce, 11-22, the performance audit's SYNC-04, after Source A's) The guest page table's changes of one recording,
// streamed into transfers of at most 64 KiB.
//
// A change to the table is a run: `count` pages from page `first`, each given `address` plus its offset (or 0 when the
// address is 0: unmapped). The recording's flush made a (page, value) pair for every page of every run, sorted them all
// and kept the last of each page: 16 bytes a page and a sort, on the recording thread, for ranges that are hundreds of
// MB when a pool is imported ahead or merged (150,000 pages: about 8 ms, and 2.4 MB of scratch).
//
// stream() writes the same transfers in the same order without the pairs: runs that come in page order and do not
// overlap, which is nearly always, are appended one after the other; any other set is swept by page with a heap of
// the runs covering the page, in which the newest run (the highest index) owns it. One batch of 8,192 entries is reused
// for every transfer. The transfers are those of the sort it replaces, entry for entry: tests/test_page_table_stream.py
// compares the two on random runs. RX_VK_TABLE_STREAM=0 (vk_memory.cpp memory_table_flush): the sort, as before.
//
// No Vulkan here: emit(first_page, values, n) is the caller's vkCmdUpdateBuffer.
#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <numeric>
#include <vector>

namespace table_stream {

constexpr size_t kBatch = 8192;   // (entries a transfer: 64 KiB, the most vkCmdUpdateBuffer takes)

struct Scratch {
    std::vector<uint64_t> batch;        // (the transfer being filled, kept from flush to flush)
    std::vector<uint32_t> order, heap;  // (the sweep's: an index a run)
};

/// The runs' changes (the later run of a page wins) as transfers of consecutive pages, ascending, each of kBatch entries
/// at most: emit(first_page, values, n). Run: {first, count, address}. How many entries were written
template <class Run, class Emit>
uint64_t stream(const Run* runs, size_t n, Scratch& s, Emit&& emit) {
    s.batch.clear();
    if (s.batch.capacity() < kBatch) s.batch.reserve(kBatch);
    uint64_t batch_first = 0, written = 0;
    const auto send = [&] {
        if (!s.batch.empty()) emit(batch_first, (const uint64_t*)s.batch.data(), s.batch.size());
        s.batch.clear();
    };
    // (count pages from `page`, the first one's value `address`, 0: all zero. A transfer ends at a gap or when it is full)
    const auto append = [&](uint64_t page, uint64_t count, uint64_t address) {
        written += count;
        while (count) {
            if (!s.batch.empty() && (page != batch_first + s.batch.size() || s.batch.size() == kBatch)) send();
            if (s.batch.empty()) batch_first = page;
            const uint64_t room = kBatch - s.batch.size(), take = count < room ? count : room;
            const size_t at = s.batch.size();
            s.batch.resize(at + (size_t)take);
            uint64_t* const out = s.batch.data() + at;
            if (address)
                for (uint64_t i = 0; i < take; i++) out[i] = address + (i << 12);
            else
                std::fill(out, out + take, uint64_t(0));
            page += take, count -= take;
            if (address) address += take << 12;
        }
    };
    // (in page order and apart: each run ends at or before the next one's first page)
    const bool in_order = std::adjacent_find(runs, runs + n, [](const Run& a, const Run& b) { return a.first + a.count > b.first; }) == runs + n;
    if (in_order) {
        for (size_t i = 0; i < n; i++) append(runs[i].first, runs[i].count, runs[i].address);
        send();
        return written;
    }
    // (overlapping or out of order: the runs by first page; of those covering a page the newest owns it. A run stays in
    // the heap past its end until it is the top, and is dropped there)
    s.order.resize(n);
    std::iota(s.order.begin(), s.order.end(), uint32_t(0));
    std::sort(s.order.begin(), s.order.end(), [&](uint32_t a, uint32_t b) { return runs[a].first != runs[b].first ? runs[a].first < runs[b].first : a < b; });
    s.heap.clear();
    uint64_t pos = 0;
    size_t k = 0;
    while (k < n || !s.heap.empty()) {
        if (s.heap.empty()) pos = runs[s.order[k]].first;
        while (k < n && runs[s.order[k]].first <= pos) {
            s.heap.push_back(s.order[k++]);
            std::push_heap(s.heap.begin(), s.heap.end());
        }
        while (!s.heap.empty() && runs[s.heap.front()].first + runs[s.heap.front()].count <= pos) {
            std::pop_heap(s.heap.begin(), s.heap.end());
            s.heap.pop_back();
        }
        if (s.heap.empty()) continue;
        const Run& r = runs[s.heap.front()];
        uint64_t stop = r.first + r.count;   // (this run owns the pages up to its end, or to where a run begins that may be newer)
        if (k < n && runs[s.order[k]].first < stop) stop = runs[s.order[k]].first;
        append(pos, stop - pos, r.address ? r.address + ((pos - r.first) << 12) : 0);
        pos = stop;
    }
    send();
    return written;
}

}   // namespace table_stream
