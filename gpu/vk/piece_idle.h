// (Triforce, 11-22, the performance audit's MEM-26, its first step, after Source A's) What a mirror in pieces holds that
// no game pool covers any more, and how much of that no binding has reached for a while: counted, nothing released.
//
// A mirror in pieces gives a piece its memory when a binding first reaches it, and keeps it until the whole mirror goes.
// The mirror is an import's (a chunk of guest memory around what was bound), and the game's pools inside it come and go:
// a long-lived import keeps the memory of every piece any area reached, also where no game pool is left. Source A gives
// such memory back after two waits of 600 submissions. Before that is ported (the unbind and the free must wait for the
// GPU and for the bind timeline: memory freed under a compute pass that reads it lost devices before) this counts what
// it would find, every 1200 submissions, in the "mirrors in pieces" line: under about 100 MB at the end of a tour on a
// 6 GB card, the release is not worth having.
//
// Counted by piece. A release frees whole runs of pieces (one allocation a run), so this is the most it could give back.
// The rule alone, no Vulkan: tests/test_mirror_piece_idle.py compiles it against a page-by-page model.
#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <utility>
#include <vector>

namespace piece_idle {

using Ranges = std::vector<std::pair<uint64_t, uint64_t>>;   // ([first, second))

/// The ranges sorted and merged: disjoint, ascending, none empty (touching ones joined)
inline void merge(Ranges& r) {
    std::sort(r.begin(), r.end());
    size_t m = 0;
    for (const auto& e : r) {
        if (e.second <= e.first) continue;
        if (m && e.first <= r[m - 1].second) r[m - 1].second = std::max(r[m - 1].second, e.second);
        else r[m++] = e;
    }
    r.resize(m);
}

struct Count {
    uint64_t held = 0;        // (bytes of the pieces that have memory)
    uint64_t uncovered = 0;   // (of them, the pieces no game pool touches)
    uint64_t idle = 0;        // (of those, the ones no binding reached for idle_for submissions; 0 when that is not tracked)
};

/// A mirror at guest address lo of `size` bytes, in pieces of 1 << shift bytes: resident(i) says piece i has memory,
/// last(i) the submission a binding last reached it at. pools: the game's pools, merged (merge above). now: this
/// submission; idle_for: 0, or how many submissions without a binding make a piece idle. Adds to out
template <class Resident, class Last>
inline void count(uint64_t lo, uint64_t size, uint32_t shift, const Resident& resident, const Last& last, const Ranges& pools, uint64_t now,
                  uint64_t idle_for, Count& out) {
    const uint64_t piece = 1ull << shift, n = (size + piece - 1) >> shift;
    size_t at = 0;   // (the first pool that ends after the piece's start: the pieces come ascending)
    for (uint64_t i = 0; i < n; i++) {
        if (!resident(i)) continue;
        const uint64_t a = lo + (i << shift), b = lo + std::min(size, (i + 1) << shift);
        out.held += b - a;
        while (at < pools.size() && pools[at].second <= a) at++;
        if (at < pools.size() && pools[at].first < b) continue;   // (a game pool touches it)
        out.uncovered += b - a;
        if (idle_for && now - last(i) >= idle_for) out.idle += b - a;
    }
}

}   // namespace piece_idle
