// (Triforce, 11-21, the performance audit's TEX-02, after Source A's) The 2 MB regions of GPU addresses a GPU buffer write
// ever reached (vk_texture.cpp texture_gpu_wrote, gpu_wrote_into).
//
// gpu_wrote_into asks, for every sampled and uploaded texture once an epoch, whether the GPU wrote into the texture's
// storage since its upload: it took gpu_wrote_mu and walked the map of written ranges each time, under the replay's ParLock
// where the quick touch failed, and nearly every answer is no. A texture whose storage lies in no region a GPU write ever
// reached was not written: that answer needs neither the lock nor the walk. One bit a 2 MB region of a 40-bit address
// space, 64 KB of atomics; a bit is never cleared, and addresses past 40 bits share the bits of those below. So a set bit
// only means "ask the map", whose answers are unchanged, and a clear one means no. A write's regions are marked before the
// map has it, and the map says yes only once the write's submission is complete, long after.
// RX_VK_WROTE_REGIONS=0: the lock and the walk each time, as before; 2: a check (a "no" asks the map too, disagreements
// counted and logged: there must be none).
//
// The bits alone, no Vulkan: tests/test_wrote_regions.py compiles them.
#pragma once
#include <algorithm>
#include <atomic>
#include <cstdint>

namespace wrote_regions {

inline constexpr unsigned kShift = 21;             // (2 MB)
inline constexpr uint64_t kRegions = 1ull << 19;   // (of a 40-bit address space: 64 KB of bits)
inline std::atomic<uint64_t> bits[kRegions / 64];

/// How many regions [lo, hi) touches, kRegions at the most (a longer range wraps onto every bit)
inline uint64_t span(uint64_t lo, uint64_t hi) { return std::min<uint64_t>(((hi - 1) >> kShift) - (lo >> kShift) + 1, kRegions); }

/// A GPU write of [lo, hi): its regions noted. Called before the write is in the map
inline void mark(uint64_t lo, uint64_t hi) {
    if (hi <= lo) return;
    const uint64_t a = lo >> kShift, n = span(lo, hi);
    for (uint64_t i = 0; i < n; i++) {
        const uint64_t r = (a + i) % kRegions;
        bits[r >> 6].fetch_or(1ull << (r & 63), std::memory_order_relaxed);
    }
}

/// Whether any region of [lo, hi) was ever written
inline bool any(uint64_t lo, uint64_t hi) {
    if (hi <= lo) return false;
    const uint64_t a = lo >> kShift, n = span(lo, hi);
    for (uint64_t i = 0; i < n; i++) {
        const uint64_t r = (a + i) % kRegions;
        if (bits[r >> 6].load(std::memory_order_relaxed) & (1ull << (r & 63))) return true;
    }
    return false;
}

}   // namespace wrote_regions
