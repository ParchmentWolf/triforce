// Whether the write-back of a texture the eviction chose is stale: another image was drawn over its storage since its own
// last drawing (no game, no GPU: a rule). tests/test_evict_reason.py
//
// (Triforce, 11-22, the performance audit's TEX-R404, after Source A's.) Over the budget, the eviction writes each chosen
// texture the GPU drew back into the game's memory before it goes, so that one made again over that storage is uploaded
// with what the GPU drew. The game draws its HUD labels (110 x 110, 46 x 46, 140 x 140) inside the storage of a
// 1920 x 1080 target it no longer uses. The eviction's own tests do not see that: drawn_over looks only at images of the
// same start, and target_overlap.h leaves out an image inside the target. So when the target went, its old texels landed
// over the labels, the pages counted as written, and the labels, finalized, were uploaded from them as noise (Source A:
// in 3 of 3 runs of two minutes in Hyrule Field at a 6 GB allowance, none with the rule).
//
// The rule: a write-back is left out when another image the GPU drew overlaps the texture's storage and was drawn in a
// later frame than the texture's own last drawing. The texture still goes. One drawn in the same frame keeps the
// write-back (a frame's targets drawn side by side), and so does one that only touches it. What is given up: the parts
// of the texture the newer image does not cover are not written back either; made again there and sampled undrawn, it
// starts from what the memory holds, as before the write-back existed. RX_VK_EVICT_STALE_FLUSH=1: written back, as before.
#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <vector>

namespace evict_reason {

/// RX_VK_EVICT_STALE_FLUSH: unset, empty or 0 leaves a stale write-back out; anything else writes it back, as before
inline bool flush_stale(const char* env) { return env && *env && std::atoi(env) != 0; }

/// Whether the storage [lo, hi) and [olo, ohi) share a byte (ranges that touch do not)
constexpr bool overlaps(uint64_t lo, uint64_t hi, uint64_t olo, uint64_t ohi) {
    return lo < hi && olo < ohi && lo < ohi && olo < hi;
}

/// Whether a texture last drawn in frame `last` holds texels older than what is in its storage: `other` is the frame of
/// the newest drawing of another image over that storage (0: none)
constexpr bool write_back_stale(uint64_t last, uint64_t other) { return other > last; }

/// A texture whose write-back the eviction is about to make
struct Candidate {
    uint64_t lo = 0, hi = 0;      // its storage
    size_t index = 0;             // the caller's own: its place in the eviction's list
    const void* self = nullptr;   // itself, so that it is not taken for another image over its own storage
    uint64_t newest = 0;          // the frame of the newest drawing of another image over its storage (0: none)
};

/// Puts the candidates in the order of their starts, for note(); returns the longest one's size
inline uint64_t by_start(std::vector<Candidate>& c) {
    std::sort(c.begin(), c.end(), [](const Candidate& a, const Candidate& b) { return a.lo < b.lo; });
    uint64_t longest = 0;
    for (const Candidate& k : c) longest = std::max(longest, k.hi > k.lo ? k.hi - k.lo : 0);
    return longest;
}

/// One image the GPU drew, [olo, ohi), last drawn in frame `o_written`: every candidate it overlaps (but itself) takes
/// that frame when it is newer than what the candidate has. `c` is in by_start's order, `longest` what by_start gave
inline void note(std::vector<Candidate>& c, uint64_t longest, uint64_t olo, uint64_t ohi, uint64_t o_written, const void* other) {
    if (ohi <= olo) return;
    // (a candidate over [olo, ohi) starts before ohi and after olo less its size: the search begins at olo less the longest)
    auto it = std::lower_bound(c.begin(), c.end(), olo > longest ? olo - longest : 0,
                               [](const Candidate& k, uint64_t g) { return k.lo < g; });
    for (; it != c.end() && it->lo < ohi; ++it)
        if (it->self != other && overlaps(it->lo, it->hi, olo, ohi) && o_written > it->newest) it->newest = o_written;
}

} // namespace evict_reason
