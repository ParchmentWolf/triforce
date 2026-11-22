// (Triforce, 11-21, the performance audit's MEM-27, after Source A's: its first step) What the mirrors' sparse buffers cost.
//
// A mirror in pieces is a sparse buffer: address space, not memory, yet the driver charges by its size. Source A measured
// about 0.06 ms a MB to create one and 0.07 to destroy it (NVIDIA 617.42), 52 to 64 ms batches of destructions at an area
// change, and the game frees its pools there and makes them again at the same sizes. Its answer is to keep a freed
// mirror's buffer, unbound, for the next mirror of exactly that size. Before that is built here, this counts: the creates
// and destroys, their time, the longest, and how many creates a buffer freed earlier, of exactly their size, could have
// served. The line "vk: mirrors' sparse buffers" every 1200 submissions has them (vk_memory.cpp).
//
// The count alone, no Vulkan: tests/test_mirror_spare.py compiles it.
#pragma once
#include <cstdint>
#include <map>

namespace mirror_spare {

struct Counts {
    uint64_t creates = 0, destroys = 0, servable = 0;          // (servable: creates a freed buffer of their size was there for)
    double create_ms = 0, destroy_ms = 0, longest_create_ms = 0, longest_destroy_ms = 0;
    uint64_t create_bytes = 0, destroy_bytes = 0, over = 0;    // (over: calls of more than kLongMs)
    std::map<uint64_t, uint32_t> freed;                        // (sizes freed and not yet matched by a create)
};
inline constexpr double kLongMs = 4.0;

/// A sparse buffer of size bytes was destroyed in ms
inline void destroyed(Counts& c, uint64_t size, double ms) {
    c.destroys++, c.destroy_ms += ms, c.destroy_bytes += size, c.over += ms > kLongMs;
    if (ms > c.longest_destroy_ms) c.longest_destroy_ms = ms;
    c.freed[size]++;
}
/// A sparse buffer of size bytes was created in ms; true when one freed before, of exactly that size, could have served
inline bool created(Counts& c, uint64_t size, double ms) {
    c.creates++, c.create_ms += ms, c.create_bytes += size, c.over += ms > kLongMs;
    if (ms > c.longest_create_ms) c.longest_create_ms = ms;
    auto it = c.freed.find(size);
    if (it == c.freed.end()) return false;
    if (!--it->second) c.freed.erase(it);
    c.servable++;
    return true;
}

}   // namespace mirror_spare
