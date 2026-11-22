// (Triforce, 11-22) Which part of a written binding is copied back to guest memory when the capture leaves memory out
// (vk_memory.cpp gpu_buffer_bind, RX_VK_CAP_ONLY_GPU=1; RX_VK_WB_EXCL_CLIP=0: all of it, as before).
//
// With RX_VK_CAP_ONLY_GPU=1 (0.6.0) the heap memory between the game's pools inside an imported chunk is "left out": the
// collection does not stamp the CPU's writes there, so no mirror sync copies them into the chunk's mirror, and the mirror's
// bytes there stay as they were when the mirror was made (or as a retired mirror left them). A written binding that reaches
// into that memory (a pointer table's bare entry: its first 64 bytes are marked written, vk_draw.cpp) was still written back
// from the mirror at the submission's end. The write-back diff compares the mirror with a shadow filled from guest memory,
// finds the CPU's newer words different, and copies the mirror's stale words over them. Players' 0.6.0 crashes at area
// changes (ModuleSystemWorker / sead::MainThread, guest 0x803b44e0 freeing a block whose header read 0x9ed00000001 or
// 0x1aa88000013fe): the game's heap had put a 12-byte block at exactly 0x18 past such a binding's base (0x117e70a000,
// 0x117f63a000, 0x117d35b000, 0x117e28a000 in four players' logs, each logged as "a buffer binding of <base> +0x40 reaches
// memory the capture leaves out"), and its header at +0x10 was overwritten.
//
// A GPU address below 1 TB is valid only inside a memory pool, so the GPU cannot have written that memory on a console: the
// left-out parts are not copied back (the GPU's writes stay in the mirror, where later GPU work reads them).
#pragma once

#include <algorithm>
#include <cstdint>
#include <utility>
#include <vector>

namespace wb_excl_clip {

using Range = std::pair<uint64_t, uint64_t>;

/// The parts of [lo, hi) outside every range of excl (sorted by start, not overlapping), appended to out in order. Returns
/// the bytes left out
inline uint64_t kept(uint64_t lo, uint64_t hi, const std::vector<Range>& excl, std::vector<Range>& out) {
    if (hi <= lo) return 0;
    // (the first range that ends past lo)
    auto it = std::upper_bound(excl.begin(), excl.end(), lo, [](uint64_t v, const Range& r) { return v < r.second; });
    uint64_t at = lo, dropped = 0;
    for (; it != excl.end() && it->first < hi; ++it) {
        const uint64_t a = std::max(at, it->first), b = std::min(hi, it->second);
        if (a > at) out.push_back({at, a});
        if (b > a) dropped += b - a;
        at = std::max(at, b);
        if (at >= hi) break;
    }
    if (at < hi) out.push_back({at, hi});
    return dropped;
}

/// The switch: RX_VK_WB_EXCL_CLIP (nullptr or "": not set, on; "0": off), and only while the capture leaves memory out
/// (cap_only: RX_VK_CAP_ONLY_GPU's mode; with 0 nothing is left out, with 2 the capture still takes everything)
inline bool on(const char* env, int cap_only) {
    if (cap_only != 1) return false;
    return !(env && env[0] == '0' && !env[1]);
}

} // namespace wb_excl_clip
