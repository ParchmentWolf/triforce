// (Triforce, 11-22, the performance audit's SYNC-21, after Source A's) A recording's uniform updates as copies of many
// regions, ordered where they overlap: when a run of them ends.
//
// A recording's uniform updates are written into guest memory at its end, between two full barriers: one
// vkCmdUpdateBuffer an update (about 80 a frame), and nothing between two updates of the same bytes, whose order on the
// GPU is then not defined (transfer writes with no dependency between them; so far a validation finding only). With
// RX_VK_UB_BATCH=1 the updates' bytes go into the recording's stream and each run of them into one buffer is one
// vkCmdCopyBuffer of many regions. The regions of one copy may not overlap, and two writes of the same bytes need an
// order: a run ends where a piece would write bytes the run already wrote, or where the destination buffer changes, and
// the next run starts behind a barrier. This header is that rule alone (no Vulkan): vk_replay.cpp flush_ub_batched asks
// it, tests/test_ub_update_batch.py runs both and takes each part of the rule away in turn.
#pragma once
#include <cstddef>
#include <cstdint>
#include <utility>
#include <vector>

namespace ub_batch {

/// What has to happen before a piece joins the run: nothing; the regions so far copied (their source buffer is another,
/// no barrier); the run ended by an overlap; the run ended by another destination. The last two: the regions so far
/// copied, then a barrier, then a new run
enum Before : int { JOIN = 0, COPY = 1, RUN_OVERLAP = 2, RUN_IMPORT = 3 };

template <class Buffer>
struct Run {
    Buffer src{}, dst{};   // (the stream buffer the pending regions' bytes are in; the buffer the run writes)
    bool any = false;      // (a run is open: dst is set)
    size_t pending = 0;    // (regions not copied yet)
    std::vector<std::pair<uint64_t, uint64_t>> written;   // ([at, end) in dst written since the run began, copied or not)

    bool overlaps(uint64_t at, uint64_t end) const {
        for (const auto& w : written)
            if (at < w.second && w.first < end) return true;
        return false;
    }
    /// Before a piece from stream buffer s into [at, end) of d joins
    Before before(Buffer s, Buffer d, uint64_t at, uint64_t end) const {
        if (!any) return JOIN;
        if (d != dst) return RUN_IMPORT;
        if (overlaps(at, end)) return RUN_OVERLAP;
        if (pending && s != src) return COPY;
        return JOIN;
    }
    void clear() { any = false, pending = 0, written.clear(); }
    void begin(Buffer d) { dst = d, any = true, pending = 0, written.clear(); }                         // (a new run, into d)
    void add(Buffer s, uint64_t at, uint64_t end) { src = s, pending++, written.push_back({at, end}); }   // (a region joins)
    void wrote(uint64_t at, uint64_t end) { written.push_back({at, end}); }   // (bytes of dst written some other way in this run)
    void copied() { pending = 0; }                                            // (the pending regions went into a copy)
};

}   // namespace ub_batch
