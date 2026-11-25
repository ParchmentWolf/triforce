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
#include <cstdlib>

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

// ---- (Triforce, RX_VK_TARGET_REUSE_MEMORY, off by default) a render target whose shape missed the pool takes a pooled
// image's memory ----
// OoT sizes each nearby character's shadow map anew every frame (397, 439, 479 ... texels a side), so its shape never comes
// back to the pool while an image of nearly the same size was just put in it; each was a new allocation, on a Steam Deck a
// kernel call that compacts memory (measured there: about 3.2 ms a frame of a camera turn in VMA's block allocations, 92% of
// them render targets made after the pool missed). With the switch a target that misses the pool is bound to the memory of a
// pooled image it fits in (vk_texture.cpp pool_take_memory), and at 2 the targets of the pooled kind are made on allocations
// of a size class so the next one a little larger fits (vk_vma.cpp create_image_in_class). Measured on a Steam Deck OLED at
// Render 50% in a Hyrule Field camera turn: 33.6 fps against 32.6, 1% low 15.7 against 13.1; not separated at Render 100%,
// no gain shown on a Steam Deck LCD, not run on a discrete card. The picture is the same: the image starts UNDEFINED and is
// cleared as a new one is.

/// RX_VK_TARGET_REUSE_MEMORY: 0 off (unset: off, as before), 1 a pooled image's memory taken by size, 2 also the size classes
inline int reuse_level(const char* env) {
    if (!env || !*env) return 0;
    const int v = atoi(env);
    return v <= 0 ? 0 : v >= 2 ? 2 : 1;
}

enum class Fit : uint8_t { fits, own_memory, type, alignment, too_small, too_big };
inline uint64_t class_bytes(uint64_t need, uint64_t block);
/// Whether a pooled render target's allocation can hold a new image of another shape, or why not: a memory type the new image
/// can use, an offset its alignment divides, at least its size and at most 1.5 times it (or its own size class, which under
/// 1 MB may be more), and not memory of its own (bound to the one image it was made for)
inline Fit verdict(uint64_t pooled_bytes, uint64_t pooled_offset, uint32_t pooled_memory_type, bool pooled_dedicated,
                   uint64_t need_bytes, uint64_t need_alignment, uint32_t need_memory_type_bits) {
    if (pooled_dedicated) return Fit::own_memory;
    if (pooled_memory_type >= 32 || !(need_memory_type_bits >> pooled_memory_type & 1)) return Fit::type;
    if (need_alignment > 1 && pooled_offset % need_alignment) return Fit::alignment;
    if (!need_bytes || pooled_bytes < need_bytes) return Fit::too_small;
    return pooled_bytes * 2 <= need_bytes * 3 || pooled_bytes <= class_bytes(need_bytes, UINT64_MAX) ? Fit::fits : Fit::too_big;
}
inline bool fits(uint64_t pooled_bytes, uint64_t pooled_offset, uint32_t pooled_memory_type, bool pooled_dedicated,
                 uint64_t need_bytes, uint64_t need_alignment, uint32_t need_memory_type_bits) {
    return need_bytes && verdict(pooled_bytes, pooled_offset, pooled_memory_type, pooled_dedicated, need_bytes, need_alignment,
                                 need_memory_type_bits) == Fit::fits;
}

/// Presents an image waits in the pool before a target of another shape may take its memory: a shape made every frame takes
/// its image back within the present it came in, and taking that one would only make the next of its shape miss
inline constexpr uint64_t kSizeTakeIdle = 1;
inline bool takeable_by_size(uint64_t now, uint64_t since, uint64_t min_idle) { return now - since >= min_idle; }

/// Why a target that missed the pool was not given a pooled image's memory either (the status line's "not reused by size")
enum class Miss : uint8_t { empty, too_new, unusable, too_small, too_big, between, over_block, requirements, not_bound, count };
struct Tally {
    uint32_t too_new = 0, unusable = 0, too_small = 0, too_big = 0;
    uint64_t largest_small = 0;   // (bytes: the largest of the smaller ones)
};
inline void add(Tally& t, bool takeable, Fit f, uint64_t pooled_bytes) {
    if (!takeable) t.too_new++;
    else if (f == Fit::too_small) t.too_small++, t.largest_small = std::max(t.largest_small, pooled_bytes);
    else if (f == Fit::too_big) t.too_big++;
    else if (f != Fit::fits) t.unusable++;
}
/// A scan of a pool that was not empty, none of it taken
inline Miss miss_reason(const Tally& t) {
    if (t.too_small || t.too_big) return !t.too_big ? Miss::too_small : !t.too_small ? Miss::too_big : Miss::between;
    return t.unusable ? Miss::unusable : Miss::too_new;
}

/// The short wait on an integrated GPU while the take by size is on (RX_VK_TARGET_REUSE_MEMORY 1 or 2): a shape not coming
/// back is then the next new shape's allocation, and there each allocation is a kernel call (a Steam Deck's camera turn: 8
/// presents left 1,006-1,104 new targets with the pool empty, 64 left 22-29). The pool's byte bound and tiers still hold it
inline constexpr uint64_t kIdleReuse = 64;
/// The short wait (a shape never taken from the pool): RX_VK_POOL_IDLE as set (at least 1), else kIdleReuse while the take by
/// size is on on an integrated GPU, kIdle otherwise
inline uint64_t idle_presents(const char* env, int reuse_level, bool integrated) {
    if (env && *env) return (uint64_t)std::max(1, atoi(env));
    return reuse_level >= 1 && integrated ? kIdleReuse : kIdle;
}

/// Size classes (RX_VK_TARGET_REUSE_MEMORY=2): from 64 KiB in steps of a quarter, each a multiple of 64 KiB, the largest the
/// block; where fewer than 8 fit a block a class holds no fewer to a block than the requirement rounded to 64 KiB would. At most
/// a quarter over the requirement rounded to 64 KiB. 0: none (nothing, or over a block)
inline constexpr uint64_t kClassFloor = 64 << 10, kClassAlign = 64 << 10;
inline uint64_t class_bytes(uint64_t need, uint64_t block) {
    if (!need || need > block) return 0;
    const auto up = [](uint64_t x) { return (x + kClassAlign - 1) / kClassAlign * kClassAlign; };
    uint64_t c = kClassFloor;
    while (c < need) c = up(c * 5 / 4);
    const uint64_t per_block = block / up(need);
    if (per_block < 8) c = std::min(c, block / per_block / kClassAlign * kClassAlign);
    return std::min(c, block);
}
/// The pool's index of class allocations: by memory type and class
inline uint64_t class_key(uint32_t memory_type, uint64_t class_bytes) { return class_bytes << 6 | (memory_type & 63); }

}   // namespace target_pool
