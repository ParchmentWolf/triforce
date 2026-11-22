/* Render targets drawn over from another start (vk_texture.cpp's eviction): a frame's transient targets that the game
   makes in a scratch heap whose offsets shift from frame to frame. */
#pragma once

#include <algorithm>
#include <cstdint>

namespace mkwvk::target_overlap {

/// Whether a render target's storage [lo, hi), last used at frame `last_used`, was drawn over by another render target
/// [olo, ohi) last written at `o_written`: one that starts elsewhere (the same start is drawn_over's own case), is not
/// inside it (a view of a part of it), covers an eighth of it or more, and was written after its last use
inline bool shifted_over(uint64_t lo, uint64_t hi, uint64_t last_used, uint64_t olo, uint64_t ohi, uint64_t o_written) {
    if (hi <= lo || ohi <= olo || olo == lo || o_written <= last_used) return false;
    if (olo >= lo && ohi <= hi) return false;
    const uint64_t a = std::max(lo, olo), b = std::min(hi, ohi);
    return b > a && (b - a) * 8 >= hi - lo;
}

/// ((Triforce, 11-21, the performance audit's TEX-30, after Source A's) The same question for all the other render targets
/// together. Judged one by one, an eighth each, a target that two others had drawn over between them, one over its head
/// and one over its tail, each less than an eighth, was kept for good: its texels are as gone from that memory. Here the
/// parts the others cover inside [lo, hi) are added up, each byte once: add() takes the others in the order of their starts
/// (vk_texture.cpp's by_start), so a part never starts before the one before it and one pass merges them. A target with
/// the same start, one inside it and one not written after its last use count nothing, as in shifted_over
struct ShiftedOver {
    uint64_t lo, hi, last_used;
    uint64_t closed = 0, run_lo = 0, run_hi = 0;   // (the parts merged and done with, and the one still growing)

    void add(uint64_t olo, uint64_t ohi, uint64_t o_written) {
        if (hi <= lo || ohi <= olo || olo == lo || o_written <= last_used) return;
        if (olo >= lo && ohi <= hi) return;
        const uint64_t a = std::max(lo, olo), b = std::min(hi, ohi);
        if (b <= a) return;
        if (a <= run_hi) {
            run_hi = std::max(run_hi, b);
        } else {
            closed += run_hi - run_lo;
            run_lo = a, run_hi = b;
        }
    }
    /// The bytes of it the others cover
    uint64_t covered() const { return closed + (run_hi - run_lo); }
    /// Whether that is an eighth of it or more
    bool an_eighth() const { return hi > lo && covered() * 8 >= hi - lo; }
};

} // namespace mkwvk::target_overlap
