// The count of an image in the game's own BC or ASTC blocks (gpu/vk/tex_count.h); run by tests/test_tex_count_blocks.py.
// (Triforce, 11-22, the performance audit's TEX-86, after Source A's.)
#include "tex_count.h"

#include <cstdio>

static int checks, fails;
static void want(const char* what, uint64_t got, uint64_t bytes) {
    checks++;
    if (got != bytes) fails++, std::printf("FAIL %s: %llu bytes, want %llu\n", what, (unsigned long long)got, (unsigned long long)bytes);
}
#define CHECK(x) do { checks++; if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)

// (the count as it was, for what the rule replaces: `texel` bytes for every texel of the chain)
static uint64_t by_texels(uint32_t w, uint32_t h, uint32_t d, uint32_t levels, uint32_t layers, uint32_t texel) {
    uint64_t px = 0;
    for (uint32_t l = 0; l < levels; l++)
        px += (uint64_t)((w >> l) ? (w >> l) : 1) * ((h >> l) ? (h >> l) : 1) * ((d >> l) ? (d >> l) : 1);
    return px * layers * texel;
}

int main() {
    using tex_count::bytes;
    using tex_count::level_blocks;
    // the switch: unset, empty and 0 count by blocks
    CHECK(!tex_count::by_texels(nullptr) && !tex_count::by_texels("") && !tex_count::by_texels("0"));
    CHECK(tex_count::by_texels("1") && tex_count::by_texels("2"));
    CHECK(!tex_count::by_texels("off"));
    // a level's blocks: rounded up each way, a level of 1 x 1 is one block
    CHECK(level_blocks(1365, 1365, 0, 8, 8) == 171 * 171 && level_blocks(1365, 1365, 2, 4, 4) == 86 * 86);
    CHECK(level_blocks(1, 1, 0, 4, 4) == 1 && level_blocks(256, 256, 20, 4, 4) == 1 && level_blocks(5, 9, 0, 4, 4) == 2 * 3);
    CHECK(level_blocks(100, 50, 0, 12, 10) == 9 * 5 && level_blocks(100, 50, 1, 12, 10) == 5 * 3);
    // BC1 (8 bytes a block), 256 x 256 with its whole chain: 4096 + 1024 + 256 + 64 + 16 + 4 + 1 and two tails of one block
    want("BC1 256x256, 9 levels", bytes(256, 256, 1, 0, 9, 1, 4, 4, 8), 5463ull * 8);
    want("BC1 as it was counted", by_texels(256, 256, 1, 9, 1, 1), 87381);          // (twice: a byte a texel)
    // BC4 (8 bytes), the game's two 64 x 64 x 64 volumes: a level's depth is slices of flat blocks
    want("BC4 64x64x64, 7 levels", bytes(64, 64, 64, 0, 7, 1, 4, 4, 8), (16384ull + 2048 + 256 + 32 + 4 + 2 + 1) * 8);
    want("BC4 64x64x64, one level", bytes(64, 64, 64, 0, 1, 1, 4, 4, 8), 131072);
    // BC7 (16 bytes): a byte a texel at whole blocks, a 1 x 1 tail a whole block
    want("BC7 1024x512, one level", bytes(1024, 512, 1, 0, 1, 1, 4, 4, 16), 1024ull * 512);
    want("BC7 1x1", bytes(1, 1, 1, 0, 1, 1, 4, 4, 16), 16);
    want("BC7 5x5", bytes(5, 5, 1, 0, 1, 1, 4, 4, 16), 4 * 16);
    want("BC7 4x4 with its tails", bytes(4, 4, 1, 0, 3, 1, 4, 4, 16), 3 * 16);
    want("BC7 cube 64x64, 6 layers", bytes(64, 64, 1, 0, 1, 6, 4, 4, 16), 6ull * 64 * 64);
    // ASTC, 16 bytes a block whatever the block
    want("ASTC 4x4 512x512", bytes(512, 512, 1, 0, 1, 1, 4, 4, 16), 512ull * 512);              // (a byte a texel; counted 16)
    want("ASTC 8x8 512x512", bytes(512, 512, 1, 0, 1, 1, 8, 8, 16), 512ull * 512 / 4);          // (counted 64 times this)
    want("ASTC 12x12 100x100", bytes(100, 100, 1, 0, 1, 1, 12, 12, 16), 81 * 16);
    want("ASTC 12x12 1x1 tail chain", bytes(12, 12, 1, 0, 4, 1, 12, 12, 16), 4 * 16);
    want("ASTC 10x5 100x100", bytes(100, 100, 1, 0, 1, 1, 10, 5, 16), 10 * 20 * 16);
    // the terrain array Source A measured: 1365 x 1365 x 90 layers, ASTC 8 x 8, 11 levels: 53.8 MiB, where 3,410 were counted
    const uint64_t terrain = bytes(1365, 1365, 1, 0, 11, 90, 8, 8, 16);
    want("the 1365x1365x90 ASTC 8x8 array", terrain, 39143ull * 16 * 90);
    CHECK(terrain * 10 / (1ull << 20) == 537);                                                  // (53.7.. MiB: "53.8" rounded)
    CHECK(by_texels(1365, 1365, 1, 11, 90, 16) >> 20 == 3410);
    // the levels from `first` on: what the first size estimate asks when top levels are left out
    want("from level 1", bytes(256, 256, 1, 1, 9, 1, 4, 4, 8), bytes(128, 128, 1, 0, 8, 1, 4, 4, 8));
    want("from level 3 of the array", bytes(1365, 1365, 1, 3, 11, 90, 8, 8, 16), (484ull + 121 + 36 + 9 + 4 + 3) * 16 * 90);
    want("no level left", bytes(256, 256, 1, 9, 9, 1, 4, 4, 8), 0);
    // never more than the old count for the formats it replaces it for (BC by a byte a texel only past whole blocks)
    static const struct { uint32_t bw, bh, bb; } F[] = {{4, 4, 8}, {4, 4, 16}, {5, 4, 16}, {6, 6, 16}, {8, 8, 16}, {10, 10, 16}, {12, 12, 16}};
    for (const auto& f : F)
        for (uint32_t w = 1; w <= 4096; w = w * 3 + 1)
            for (uint32_t h = 1; h <= 4096; h = h * 5 + 2) {
                uint32_t levels = 1;
                while (((w > h ? w : h) >> levels) > 0) levels++;
                const uint64_t n = bytes(w, h, 1, 0, levels, 3, f.bw, f.bh, f.bb);
                checks++;
                // (at least a block a level and layer; at most every level's texels rounded up to blocks)
                if (n < (uint64_t)levels * 3 * f.bb) fails++, std::printf("FAIL %ux%u %ux%u: under a block a level\n", w, h, f.bw, f.bh);
                uint64_t top = 0;
                for (uint32_t l = 0; l < levels; l++) top += level_blocks(w, h, l, f.bw, f.bh);
                checks++;
                if (n != top * f.bb * 3) fails++, std::printf("FAIL %ux%u %ux%u: not the sum of its levels\n", w, h, f.bw, f.bh);
            }
    // a block size of 0 (a format the table does not know) is taken as 1, not divided by
    want("a zero block", bytes(8, 8, 1, 0, 1, 1, 0, 0, 4), 8ull * 8 * 4);
    want("zero layers", bytes(8, 8, 1, 0, 1, 0, 4, 4, 8), 4 * 8);
    if (fails) std::printf("tex count: FAILED (%d of %d checks)\n", fails, checks);
    else std::printf("tex count: all %d checks passed\n", checks);
    return fails != 0;
}
