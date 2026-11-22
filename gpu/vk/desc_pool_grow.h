// A recording slot's descriptor pool, made at half size and made whole once a recording runs out of it (no game, no GPU:
// a rule; vk_draw.cpp make_pool, slot_reset_locked, draw_begin_recording).
//
// (Triforce, 11-22, the performance audit's DESC-33, after Source A's.) Each of the recording slots (48 at most) keeps a
// descriptor pool of 8192 sets and up to 32768 descriptors a type, and the driver may keep host memory for all of that,
// 48 times. Few recordings come near it: Source A saw one take at most 289 sets on a desktop card, and no pool at half
// size run out in three scenes on a handheld. So a slot's pool starts at half (4096 sets, 16384 uniform buffers and
// combined image samplers, and so on down the types).
//
// A recording that runs out is given a whole extra pool, as it always was (bind_descriptors), and that is the mark: at
// the slot's next reset, where the extra pools are destroyed anyway, a slot that has any and whose own pool is not whole
// has it destroyed and made again whole. From then on the slot is as it was before this rule. A busy slot so pays one
// extra pool, once.
//
// RX_VK_DESC_POOL_GROW=0: whole pools from the start, as before. RX_VK_DESC_POOL_DIV=<n> still divides both sizes.
// What the recordings took (sets and descriptors a type, the most one recording took of each) and how many pools were
// added and slots made whole go into the log's "recording streams" line, so a size can be judged from a run's log.
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdlib>

namespace mkwvk::desc_pool_grow {

/// RX_VK_DESC_POOL_GROW: on unless set to 0
inline bool on(const char* env) {
    return !env || std::atoi(env) != 0;
}

/// A whole pool's sets, and its descriptors by type in the order of Took::n
inline constexpr uint32_t kSets = 8192;
enum Kind { kUniform, kStorage, kSampled, kStorageImage, kUniformTexel, kStorageTexel, kKinds };
inline constexpr uint32_t kWhole[kKinds] = {32768, 16384, 32768, 4096, 2048, 2048};

/// The shift a new slot's pool is made with: half with the rule on, whole without it
constexpr uint32_t first_shift(bool on) {
    return on ? 1u : 0u;
}

/// A count of a pool made at `shift` (0 whole, 1 half) and divided by RX_VK_DESC_POOL_DIV's n (1..32): never 0
constexpr uint32_t count(uint32_t whole, uint32_t shift, uint32_t div) {
    const uint32_t n = (whole >> (shift > 8 ? 8 : shift)) / (div ? div : 1);
    return n ? n : 1;
}

/// Whether a slot's own pool is made again whole at its reset: its last recording ran out (it has extra pools) and the
/// pool is not whole yet
constexpr bool remake(uint32_t shift, size_t extra_pools) {
    return shift != 0 && extra_pools != 0;
}

/// Which of the six a Vulkan descriptor type is (VkDescriptorType's numbers, so that this header needs no Vulkan):
/// kKinds for any other
constexpr int kind(uint32_t vk_type) {
    switch (vk_type) {
    case 6: return kUniform;         // VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER
    case 7: return kStorage;         // VK_DESCRIPTOR_TYPE_STORAGE_BUFFER
    case 1: return kSampled;         // VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER
    case 3: return kStorageImage;    // VK_DESCRIPTOR_TYPE_STORAGE_IMAGE
    case 4: return kUniformTexel;    // VK_DESCRIPTOR_TYPE_UNIFORM_TEXEL_BUFFER
    case 5: return kStorageTexel;    // VK_DESCRIPTOR_TYPE_STORAGE_TEXEL_BUFFER
    default: return kKinds;
    }
}

/// What one recording took of its slot's pools: sets, and descriptors by type
struct Took {
    uint32_t sets = 0;
    uint32_t n[kKinds] = {};
};

/// One more set allocated, with these writes (W: VkWriteDescriptorSet, or a test's own with the same two fields)
template <class W>
inline void took(Took& t, const W* writes, size_t count_of) {
    t.sets++;
    for (size_t i = 0; i < count_of; i++) {
        const int k = kind((uint32_t)writes[i].descriptorType);
        if (k < kKinds) t.n[k] += (uint32_t)writes[i].descriptorCount;
    }
}

/// The most any recording took of each, raised by one recording's
inline void peak(Took& most, const Took& t) {
    if (t.sets > most.sets) most.sets = t.sets;
    for (int k = 0; k < kKinds; k++)
        if (t.n[k] > most.n[k]) most.n[k] = t.n[k];
}

/// Whether what a recording took fits a pool made at `shift` and divided by div (the tests', and the log's reader's)
constexpr bool fits(const Took& t, uint32_t shift, uint32_t div) {
    if (t.sets > count(kSets, shift, div)) return false;
    for (int k = 0; k < kKinds; k++)
        if (t.n[k] > count(kWhole[k], shift, div)) return false;
    return true;
}

} // namespace mkwvk::desc_pool_grow
