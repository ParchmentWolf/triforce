// (Triforce, 11-21, the performance audit's TEX-10, after Source A's) How many layers the BC3 scratch has.
//
// Big ASTC textures are decoded into a 2048 x 2048 RGBA8 scratch and encoded again as BC3 on the GPU, into an output
// buffer. Both were made with 8 layers, 128 + 32 = 160 MB (and the second scratch of the textures encoded at another
// size, 128 MB more), whatever a run used; and a run decodes one layer (RX_VK_BC_LAYERS, the dark-line fix), so 140 MB
// were held and never written, for good once made (RX_VK_BC_IDLE_S is 0). Sized by the layers one run uses they are
// 16 + 4 = 20 MB. Source A measured 139 MiB less GPU memory on a Steam Deck, the median of 7 pairs, at the same fps.
// RX_VK_BC_SCRATCH_FULL=1: all 8 layers, as before.
//
// The rule alone, no Vulkan: tests/test_bc_scratch_layers.py compiles it.
#pragma once
#include <algorithm>
#include <cstdint>
#include <cstdlib>

namespace bc_scratch {

inline constexpr uint32_t kDim = 2048, kMost = 8;   // (the largest level a BC3 texture may have; the most layers a run may take)

/// The layers one run decodes and encodes: RX_VK_BC_LAYERS's value, 1 to kMost; not set, or not a number, 1
inline uint32_t run_layers(const char* asked) {
    return asked ? std::clamp<uint32_t>((uint32_t)std::max(atoi(asked), 0), 1u, kMost) : 1u;
}
/// The scratch's layers: a run's, or all of them when full (RX_VK_BC_SCRATCH_FULL)
inline uint32_t layers(uint32_t run, bool full) { return full ? kMost : std::clamp(run, 1u, kMost); }
/// The output buffer's bytes: BC3's 16 bytes a block of 4 x 4, every layer
inline uint64_t out_bytes(uint32_t layers) { return (uint64_t)(kDim / 4) * (kDim / 4) * layers * 16; }
/// What the scratch holds, in MB: the image and its output buffer, and the second image when there is one
inline uint64_t mb(uint32_t layers, bool second) {
    const uint64_t image = (uint64_t)kDim * kDim * 4 * layers;
    return (image + out_bytes(layers) + (second ? image : 0)) >> 20;
}

// ---- (Triforce, 11-21, the performance audit's TEX-09, after Source A's) the small scratch ----
// A run is a decode, an encode, a copy and three full barriers, and one layer a run made a 1365 x 1365 x 90 terrain array
// of 11 levels about 990 of them: the GPU spent most of that time between the runs (Source A, Hyrule Field's entry on an
// RX 9070 XT: 50 ms of GPU an array at one layer a run, 16-17 ms at 8; the lab's own array took 114.8 ms of an RTX 5090 in
// one upload command buffer). Levels of kSmallDim or less each way, the arrays' second level down, go small_layers() layers
// a run through a scratch of their own, kSmallDim x kSmallDim x 8: 32 MB, and the output buffer 8 MB for 4. One layer a
// run was for dark lines between Hyrule Field's ground tiles on an RX 6600, layers after a run's first wrong at the small
// levels, cause never found: so on AMD's cards the default stays 1 until the picture is checked there, and each layer of a
// run is copied by a region of its own, at the encoder's own layer stride. A level of a texture encoded at another size
// keeps the first scratch. RX_VK_BC_SMALL_LAYERS=<n>: the layers a run, 1 to 8; 1: no small scratch, as before.
inline constexpr uint32_t kSmallDim = 1024;

/// The small scratch's layers, a run's of a small level: RX_VK_BC_SMALL_LAYERS, 1 to kMost; not set, kMost, and 1 on AMD's
/// cards (vendor 0x1002)
inline uint32_t small_layers(const char* asked, uint32_t vendor) {
    if (asked && *asked) return std::clamp<uint32_t>((uint32_t)std::max(atoi(asked), 0), 1u, kMost);
    return vendor == 0x1002 ? 1u : kMost;
}
/// Whether a level decoded at w x h goes through the small scratch: there is one, the level fits it, and the texture is not
/// one encoded at another size (which has the second scratch)
inline bool small_level(uint32_t w, uint32_t h, bool have_small, bool resized) {
    return have_small && !resized && w <= kSmallDim && h <= kSmallDim;
}
/// The small scratch's part of the output buffer, and its image, in bytes
inline uint64_t small_out_bytes(uint32_t layers) { return (uint64_t)(kSmallDim / 4) * (kSmallDim / 4) * layers * 16; }
inline uint64_t small_image_bytes(uint32_t layers) { return (uint64_t)kSmallDim * kSmallDim * 4 * layers; }
/// Where layer k of a run begins in the encoder's output: host_shaders/bc_encoder.comp writes block
/// (z * blocks_y + y) * blocks_x + x, 16 bytes a block, 8 where only the colour half is written (an image kept as BC1)
inline uint64_t layer_offset(uint32_t k, uint32_t w, uint32_t h, bool bc1) {
    return (uint64_t)k * ((w + 3) / 4) * ((h + 3) / 4) * (bc1 ? 8 : 16);
}

}   // namespace bc_scratch
