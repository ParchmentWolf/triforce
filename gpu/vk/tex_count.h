// What a block-compressed image the GPU samples as it is (BC, or ASTC where the driver samples it) takes: whole blocks
// (no game, no GPU: a rule). tests/test_tex_count_blocks.py
//
// (Triforce, 11-22, the performance audit's TEX-86, after Source A's.) vk_texture.cpp counted such an image by its texels:
// a byte a texel for BC, and for ASTC the 16 bytes of a block for every texel, which is 16 times its size at 4 x 4, 64
// times at 8 x 8 and 144 times at 12 x 12; BC1 and BC4, eight bytes a block, twice. The texture budget then let textures
// go for memory nothing held (Source A's Intel UHD 770, whose driver samples ASTC: 17,608 MB counted against a budget of
// 2,560, 2,241 MB by blocks), and the first size estimate left out the top levels of arrays that fit. A level is
// ceil(w / bw) x ceil(h / bh) blocks a slice, each block its bytes, times the layers. The textures the renderer encodes
// itself (decoded ASTC kept as BC3 or BC1) were counted right already and are not asked here.
// RX_VK_COUNT_BY_TEXELS=1: the count as it was.
#pragma once
#include <cstdint>
#include <cstdlib>

namespace tex_count {

/// RX_VK_COUNT_BY_TEXELS: unset, empty or 0 counts by blocks; anything else brings the count by texels back
inline bool by_texels(const char* env) { return env && *env && std::atoi(env) != 0; }

/// The blocks of one slice of level `l`: the level's size rounded up to whole blocks each way
constexpr uint64_t level_blocks(uint32_t width, uint32_t height, uint32_t l, uint32_t bw, uint32_t bh) {
    const uint32_t w = l < 32 && (width >> l) ? (width >> l) : 1, h = l < 32 && (height >> l) ? (height >> l) : 1;
    const uint32_t x = bw ? bw : 1, y = bh ? bh : 1;
    return (uint64_t)((w + x - 1) / x) * ((h + y - 1) / y);
}

/// The bytes of the levels `first` .. `levels - 1` of an image of blocks of `bw` x `bh` texels and `block_bytes` bytes:
/// a 3D image's level has its depth in slices of blocks (a block is flat), every layer has the whole chain
constexpr uint64_t bytes(uint32_t width, uint32_t height, uint32_t depth, uint32_t first, uint32_t levels, uint32_t layers,
                         uint32_t bw, uint32_t bh, uint32_t block_bytes) {
    uint64_t blocks = 0;
    for (uint32_t l = first; l < levels; l++) {
        const uint32_t d = l < 32 && (depth >> l) ? (depth >> l) : 1;
        blocks += level_blocks(width, height, l, bw, bh) * d;
    }
    return blocks * block_bytes * (layers ? layers : 1);
}

} // namespace tex_count
