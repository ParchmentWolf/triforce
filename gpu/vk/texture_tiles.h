// ((Triforce) RX_VK_TILES_FAST, on unless =0) The CPU upload of a level made of complete GOBs (64 bytes by 8 rows), a
// strip of eight destination rows at a time: a taller walk evicted its own destination lines when the pitch is a power
// of two. The GOB's layout is decoders.h SWIZZLE_X_BITS / SWIZZLE_Y_BITS (16-byte runs at 0, 64, 256 and 320 for the
// row's four quarters; rows at (y & 3) * 16 + (y >> 2) * 128), its blocks rows_per_block GOBs high. False where the level
// is not such (the caller takes Tegra::Texture::UnswizzleTexture then). Measured elsewhere: 1.7 to 2.6 times the
// conversion's speed on a Ryzen 9 7900X. RX_VK_UNSWIZZLE_CHECK compares a threaded upload with the plain function
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <span>

namespace mkwvk::texture_tiles {
inline bool unswizzle(std::span<uint8_t> dest, std::span<const uint8_t> src,
                      uint64_t pitch, uint32_t height, uint32_t tile_height) {
    if (!pitch || pitch % 64 || !height || height % 8 || tile_height > 5 || pitch > dest.size() / height)
        return false;
    const std::size_t columns = std::size_t(pitch / 64);
    const std::size_t rows = height / 8;
    const std::size_t rows_per_block = std::size_t{1} << tile_height;
    const std::size_t padded_rows = (rows + rows_per_block - 1) / rows_per_block * rows_per_block;
    if (columns > src.size() / padded_rows / 512) return false;

    // Finish eight destination rows before moving down. A taller strip repeatedly
    // evicts its own destination cache lines when the pitch is a power of two.
    for (std::size_t y = 0; y < rows; ++y) {
        const std::size_t top = y & ~(rows_per_block - 1);
        for (std::size_t x = 0; x < columns; ++x) {
            const uint8_t* in = src.data() + (top * columns + x * rows_per_block + (y - top)) * 512;
            uint8_t* out = dest.data() + y * 8 * pitch + x * 64;
            for (std::size_t line = 0; line < 8; ++line) {
                const uint8_t* row = in + (line & 3) * 16 + (line >> 2) * 128;
                auto* d = out + line * pitch;
                std::memcpy(d, row, 16);
                std::memcpy(d + 16, row + 64, 16);
                std::memcpy(d + 32, row + 256, 16);
                std::memcpy(d + 48, row + 320, 16);
            }
        }
    }
    return true;
}
} // namespace mkwvk::texture_tiles
