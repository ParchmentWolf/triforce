// (Triforce, 11-22, the performance audit's THREAD-25, after Source A's) Pages that something ever happened to, asked without a lock;
// and the question an invalidate asks of them first.
//
// The game invalidates each shape's 64-byte occlusion slot, per view: tens of thousands of nvnBufferInvalidateMappedRange calls in a
// few seconds. The host gives the calling thread's virtual core up before every one and queues for it again after, as the call can
// wait for the replay or for a write-back still on the GPU; nearly always it has nothing to wait for. What it would wait for is
// known from three things: a write-back ever made into the range's pages, a texture the GPU wrote ever listed there, and a live
// texture's storage there. The first two are tables under their own locks; PageMarks keeps, beside each, one bit a 4 KB page that is
// only ever set, set before the table changes and under the table's lock, and read with no lock. A range with no mark in either and
// no texture storage is one invalidate() returns from without waiting, so the host may keep the core and not make the call
// (invalidate_quick in vk_replay.cpp, asked through mkwvk_invalidate_quick by host/rx_backend.c).
//
// A mark is never taken back: a page written back once declines for good, and waits as before. Addresses at or past 512 GB are
// not kept and answer as marked. The header is written from the audit's description of Source A's, whose file is not here.
//
// RX_VK_INVALIDATE_QUICK=1 turns the question on; off unless set (see docs/development.md for why). tests/test_invalidate_quick.py
#pragma once

#include <atomic>
#include <cstdint>
#include <cstdlib>

namespace mkwvk {

struct PageMarks {
    static constexpr uint64_t kSpan = 1ull << 39;                // (512 GB: the guest window, and the GPU's addresses the pools lie in)
    static constexpr uint64_t kPageShift = 12, kPages = kSpan >> kPageShift;
    static constexpr uint64_t kChunkPages = 1ull << 18;          // (a chunk: 1 GB of addresses, 32 KB of bits, made at its first mark)
    static constexpr uint64_t kChunks = kPages / kChunkPages, kChunkWords = kChunkPages / 64;
    std::atomic<std::atomic<uint64_t>*> chunks[kChunks] = {};

    /// every page with a byte in [lo, hi) marked (what lies at or past 512 GB is not kept: any() answers true there)
    void mark(uint64_t lo, uint64_t hi) {
        if (hi > kSpan) hi = kSpan;
        if (hi <= lo) return;
        const uint64_t last = (hi - 1) >> kPageShift;
        for (uint64_t p = lo >> kPageShift; p <= last;) {
            std::atomic<uint64_t>* c = chunks[p / kChunkPages].load(std::memory_order_acquire);
            if (!c) {
                std::atomic<uint64_t>* made = new std::atomic<uint64_t>[kChunkWords];
                for (uint64_t i = 0; i < kChunkWords; i++) made[i].store(0, std::memory_order_relaxed);
                if (chunks[p / kChunkPages].compare_exchange_strong(c, made, std::memory_order_acq_rel)) c = made;
                else delete[] made;   // (another thread made it first: c is its chunk)
            }
            // (the pages of this word from p to the word's end, or to `last`)
            const uint64_t in_chunk = p % kChunkPages, bit = in_chunk % 64;
            const uint64_t word_last = p - bit + 63, to = word_last < last ? word_last : last;
            const uint64_t n = to - p + 1;
            const uint64_t mask = (n == 64 ? ~0ull : ((1ull << n) - 1)) << bit;
            c[in_chunk / 64].fetch_or(mask, std::memory_order_seq_cst);
            p = to + 1;
        }
    }
    /// whether a page with a byte in [lo, lo + size) was ever marked; true for a range that reaches 512 GB or wraps
    bool any(uint64_t lo, uint64_t size) const {
        if (!size) return false;
        if (lo >= kSpan || size > kSpan - lo) return true;
        const uint64_t last = (lo + size - 1) >> kPageShift;
        for (uint64_t p = lo >> kPageShift; p <= last;) {
            const std::atomic<uint64_t>* c = chunks[p / kChunkPages].load(std::memory_order_seq_cst);
            if (!c) {   // (a chunk never marked: skipped whole)
                p = (p / kChunkPages + 1) * kChunkPages;
                continue;
            }
            const uint64_t in_chunk = p % kChunkPages, bit = in_chunk % 64;
            const uint64_t word_last = p - bit + 63, to = word_last < last ? word_last : last;
            const uint64_t n = to - p + 1;
            const uint64_t mask = (n == 64 ? ~0ull : ((1ull << n) - 1)) << bit;
            if (c[in_chunk / 64].load(std::memory_order_seq_cst) & mask) return true;
            p = to + 1;
        }
        return false;
    }
};

namespace inv_quick {   // (the rule of vk_replay.cpp's invalidate_quick)

/// Whether the question is asked at all. quick: RX_VK_INVALIDATE_QUICK (a number other than 0 turns it on; off unless set). The
/// three others are switches that make invalidate() log every call or wait for every range: with one set, every call is made
inline bool on(const char* quick, const char* log_invalidate, const char* log_readback, const char* wait_all) {
    return quick && std::atoi(quick) != 0 && !log_invalidate && !log_readback && !wait_all;
}

/// What is known of a range when the question is asked
struct Look {
    uint64_t gpu = 0, size = 0;
    bool ticket_pending = false;   // (a fast fence poll's order ticket not yet left: invalidate() waits for that section first)
    bool tex_storage = false;      // (a live texture's storage in the range's pages: tex_pages_any)
    bool vw_marked = false;        // (a texture the GPU wrote ever listed there)
    bool wb_marked = false;        // (a write-back ever made into its pages in the game's memory)
};
/// true: invalidate(gpu, size) would return without waiting for anything and without work: the call may be left out
inline bool nothing_to_wait_for(const Look& l) {
    if (!l.size) return true;
    if (l.gpu >= PageMarks::kSpan || l.size > PageMarks::kSpan - l.gpu) return false;
    return !l.ticket_pending && !l.tex_storage && !l.vw_marked && !l.wb_marked;
}

} // namespace inv_quick
} // namespace mkwvk
