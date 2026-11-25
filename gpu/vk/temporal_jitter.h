// (Triforce) The upscaler's jitter (the scene's size and the jitter sequence's length) crosses from the replay to the game's
// thread (host/rx_backend.c hos_dlss_jitter_clip). It was three atomics read one at a time, by three questions of the host:
// a resize or a scale change between them gave the host one frame's jitter of one size with the other's sequence. Now one
// sample, published and read whole under a lock of its own (never the upscaler's: the GPU's and NGX's work stays out of it).
#pragma once

#include <cstdint>
#include <mutex>

#include "vk_api.h"

namespace mkwvk {

class TemporalJitter {
    std::mutex mu;
    MkwVkJitter sample{};
    uint64_t frame = 0;

public:
    /// One upscale's sample, of the frame `at` (texture_frame_no); a size or length of 0: none
    void publish(uint32_t width, uint32_t height, uint32_t phases, uint64_t at) {
        std::lock_guard lock(mu);
        sample = width && height && phases ? MkwVkJitter{width, height, phases} : MkwVkJitter{};
        frame = at;
    }
    /// The last one, all zero when none was published or it is more than 30 frames old at `now`
    MkwVkJitter read(uint64_t now) {
        std::lock_guard lock(mu);
        return frame && now >= frame && now - frame <= 30 ? sample : MkwVkJitter{};
    }
};

} // namespace mkwvk
