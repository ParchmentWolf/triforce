// (Triforce, 11-21, the performance audit's TEX-29, after Source A's and Source B's) The render targets' pool: how much it
// may hold, what goes first, and when.
//
// The pool gives a dead render target's image to the next target of its shape, so that a target the game makes again each
// frame costs no image creation. It held a fixed 256 MB, kept every image 120 presents, was trimmed in the order of its
// hash table, and was emptied whenever VRAM use passed 90% of the allowance. Source A found it starved at 2560 x 1440: of
// 22,000 images it was given in 100 s it destroyed 21,879 for being over the bound, and with a larger bound, an age order
// and tiers the images made new fell from about 20,000 to about 4,300 a run and the 1% low rose from 36 to 44 fps.
//  - The bound: a twelfth of what the driver allows, 256 MB at least and 768 at most (RX_VK_TARGET_POOL_MB sets it; 0: no
//    pool).
//  - Trimmed oldest first, through one list in the order the images came in: over the bound, the image that has waited
//    longest goes, whatever its shape.
//  - The wait: a shape never taken from the pool goes after RX_VK_POOL_IDLE presents (8): the game's per-character shadow
//    maps come in sizes of their own that nothing asks for again, and at 120 presents they filled the bound. A shape that
//    was taken before keeps 120.
//  - Tiers by the VRAM in use: above 90% of the allowance half the bound, above 97% none. With a floor of blocks kept for
//    the targets (vk_vma.cpp target_floor_kept) the tiers do nothing, as the pool was not given back there before either:
//    what it gave back went into blocks the floor keeps.
// RX_VK_TARGET_POOL_TRIM=0: no tiers (the pool emptied above 90%), as before; with RX_VK_TARGET_POOL_MB=256 and
// RX_VK_POOL_IDLE=120 the pool is the one it was, but for the order.
//
// The rules alone, no Vulkan: tests/test_target_pool_rules.py compiles them.
#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>

namespace target_pool {

inline constexpr uint64_t kLeastMb = 256, kMostMb = 768;
inline constexpr uint64_t kIdle = 8, kIdleTaken = 120;       // (presents: a shape never taken from the pool; one taken before)
inline constexpr size_t kTrim = 16, kTrimPressed = 64;       // (images destroyed a present; while a tier holds)
inline constexpr size_t kTakenKeys = 4096;                   // (the shapes remembered as taken)

/// The bound in MB with no switch: a twelfth of the allowance (bytes), kLeastMb to kMostMb; not known (0): kLeastMb
inline uint64_t default_mb(uint64_t allowed) {
    return allowed ? std::clamp<uint64_t>((allowed >> 20) / 12, kLeastMb, kMostMb) : kLeastMb;
}
/// The tier: 0, 1 with the VRAM in use above 90% of the allowance, 2 above 97%. known: the driver gave both numbers
inline int tier(bool known, uint64_t in_use, uint64_t allowed) {
    if (!known || !allowed) return 0;
    return in_use > allowed / 100 * 97 ? 2 : in_use > allowed / 10 * 9 ? 1 : 0;
}
/// What the pool may hold under a tier. tiers: RX_VK_TARGET_POOL_TRIM (off: any tier empties it, as before). floor_kept: a
/// floor of the targets' blocks is kept, and the pool is not given back at all
inline uint64_t cap_for(uint64_t cap, int tier, bool tiers, bool floor_kept) {
    if (tier <= 0 || floor_kept) return cap;
    return tiers && tier == 1 ? cap / 2 : 0;
}
/// How many images a present may destroy
inline size_t trim_most(int tier, bool floor_kept) { return tier > 0 && !floor_kept ? kTrimPressed : kTrim; }
/// Whether an image put in at present since has waited out its time at present now. idle: RX_VK_POOL_IDLE; taken_before:
/// its shape was taken from the pool lately
inline bool idle_out(uint64_t now, uint64_t since, uint64_t idle, bool taken_before) {
    return now - since > (taken_before ? std::max(idle, kIdleTaken) : idle);
}

}   // namespace target_pool
