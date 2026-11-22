// (Triforce, 11-21, the performance audit's TEX-14, after Source A's) Decoded ASTC used again.
//
// The game's textures are ASTC, decoded on the GPU and for the most part encoded again as BC3 or BC1: tens of ms of GPU
// time and the decoder's scratch for each. When the game leaves an area it finalizes its textures, and when it comes back
// it makes them again, mostly at other addresses: the same blocks are decoded and encoded again while the image made of
// them the first time may still be in VRAM, kept until the cache needs its room. Source A hashes an ASTC texture's blocks
// at its first whole upload, lists a texture the game finalizes under that hash, and gives a new texture with the same
// blocks and the same shape that image by a GPU copy, the old one going after it. Its tours of two areas four times at an
// 8 GB budget: peak decoded ASTC 3,603 to 2,562 MB, evictions 23,378 to 16,109, the slowest frame 637 to 487 ms.
//
// What keeps a hit right: 128 bits of hash over the blocks as the decoder is given them; every field of the image that
// the decode made and of the storage it was decoded from (Shape); and a source that was uploaded from memory and never
// drawn into, still listed (used again at its own address or gone, it is unlisted).
//
// RX_VK_ASTC_REUSE: 0 or not set, off (the audit: off until measured in play); 2: the blocks are hashed, the finalized
// textures listed and each hit counted, and every texture decoded as before: what a reuse would save, for no risk;
// 1: the hit's image is copied.
//
// No Vulkan here: tests/test_astc_reuse.py compiles it.
#pragma once
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <unordered_map>

#include "upload_same.h"   // (content_hash: the first of the two lanes)

namespace astc_reuse {

enum Mode { kOff = 0, kCopy = 1, kCount = 2 };
/// RX_VK_ASTC_REUSE's mode: 1 and 2 as they are, anything else off
inline Mode mode(const char* asked) {
    if (!asked || !*asked) return kOff;
    const int v = atoi(asked);
    return v == 1 ? kCopy : v == 2 ? kCount : kOff;
}

/// A second hash of n bytes, of other constants and another mix than upload_same::content_hash's: eight chains over 64
/// bytes a step, as there, so that both read at memory's speed
inline uint64_t lane2(const void* p, uint64_t n) {
    const uint8_t* b = static_cast<const uint8_t*>(p);
    const auto rotl = [](uint64_t x, int r) { return (x << r) | (x >> (64 - r)); };
    uint64_t h = 0xD6E8FEB86659FD93ull + n * 0x9FB21C651E98DF25ull, i = 0;
    if (n >= 512) {
        uint64_t c[8];
        for (int k = 0; k < 8; k++) c[k] = h + 0xA0761D6478BD642Full * (uint64_t)(2 * k + 1);
        for (; i + 64 <= n; i += 64) {
            uint64_t w[8];
            std::memcpy(w, b + i, 64);
            for (int k = 0; k < 8; k++) c[k] = rotl(c[k] + w[k] * 0xE7037ED1A0B428DBull, 29) * 0x8EBC6AF09C88C6E3ull;
        }
        for (int k = 0; k < 8; k++) h = rotl(h ^ c[k], 23) * 0x589965CC75374CC3ull + 0x1D8E4E27C47D124Full;
    }
    for (; i + 8 <= n; i += 8) {
        uint64_t w;
        std::memcpy(&w, b + i, 8);
        h = rotl(h + w * 0xE7037ED1A0B428DBull, 29) * 0x8EBC6AF09C88C6E3ull;
    }
    for (; i < n; i++) h = rotl(h ^ b[i], 11) * 0x589965CC75374CC3ull;
    h ^= h >> 32, h *= 0xD6E8FEB86659FD93ull, h ^= h >> 32;
    return h;
}

/// The blocks' hash, 128 bits, made of pieces given in order (a big texture's storage is read 64 MB at a time): each piece
/// goes through both lanes kStep bytes at a time, while they are in the cache, and is folded in with its length
struct Hash {
    uint64_t a = 0, b = 0;
    bool operator==(const Hash& o) const { return a == o.a && b == o.b; }
    explicit operator bool() const { return (a | b) != 0; }
};
inline constexpr uint64_t kStep = 256u << 10;
struct Hasher {
    Hash h;
    uint64_t bytes = 0;
    void add(const uint8_t* p, uint64_t n) {
        for (uint64_t at = 0; at < n; at += kStep) {
            const uint64_t m = n - at < kStep ? n - at : kStep;
            h.a = (h.a ^ upload_same::content_hash(p + at, m)) * 0x9E3779B97F4A7C15ull + m;
            h.b = (h.b + lane2(p + at, m)) * 0xC2B2AE3D27D4EB4Full ^ (m << 1 | 1);
        }
        bytes += n;
    }
    /// The hash, never all zero (zero is "not hashed")
    Hash done() const { return (h.a | h.b) ? h : Hash{1, 0}; }
};

/// What has to be the same besides the blocks for one image to stand for another: the image the decode made (its format,
/// size, levels and layers, the top levels left out and whether by the card's texture detail, kept as BC3 or BC1 or
/// RGBA8, BC1 given up for BC3, resized for AMD) and the storage it was decoded from (the NVN format, the key's layout)
struct Shape {
    uint32_t format, width, height, depth, levels, layers, skip, nvn_format, layout;
    bool bc, bc_resized, bc1, bc1_no, detail_skip;
    bool operator==(const Shape& o) const {
        return format == o.format && width == o.width && height == o.height && depth == o.depth && levels == o.levels &&
               layers == o.layers && skip == o.skip && nvn_format == o.nvn_format && layout == o.layout && bc == o.bc &&
               bc_resized == o.bc_resized && bc1 == o.bc1 && bc1_no == o.bc1_no && detail_skip == o.detail_skip;
    }
};

/// The finalized textures whose image may serve again, by their blocks' hash. T is the cache's texture; one is in the list
/// at most once: listed and unlisted by its pointer
template <class T>
class Freed {
public:
    void list(const Hash& hash, T* t) { by_hash.emplace(hash.a, Entry{hash.b, t}); }
    void unlist(const Hash& hash, T* t) {
        auto [a, b] = by_hash.equal_range(hash.a);
        for (auto it = a; it != b; ++it)
            if (it->second.t == t) {
                by_hash.erase(it);
                return;
            }
    }
    /// One listed with this hash, both lanes, whose shape is `shape` (shape_of(T*) gives each one's) and that is not
    /// `self`; null: none
    template <class ShapeOf>
    T* find(const Hash& hash, const Shape& shape, const T* self, ShapeOf shape_of) const {
        auto [a, b] = by_hash.equal_range(hash.a);
        for (auto it = a; it != b; ++it)
            if (it->second.b == hash.b && it->second.t != self && shape_of(it->second.t) == shape) return it->second.t;
        return nullptr;
    }
    size_t size() const { return by_hash.size(); }

private:
    struct Entry {
        uint64_t b;
        T* t;
    };
    std::unordered_multimap<uint64_t, Entry> by_hash;
};

}   // namespace astc_reuse
