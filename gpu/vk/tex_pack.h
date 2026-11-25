// (Triforce, 11-24) Evil HD's texture pack: the key that names a game texture the same way in the renderer and in the pack's
// tool, as plain functions with no Vulkan, so tests/test_tex_pack.py can run them and D:\src\tools\texpack builds the same.
//
// A Switch texture lies in the GPU's memory exactly as its BNTX file stores it (the same block-linear swizzle, level 0
// first), so the first bytes of its level 0 name it: the key is FNV-1a 64 over the first kHashBytes of them (fewer when level
// 0 is smaller), mixed with its width and height. The pack's tool reads them from the game's romfs\Tex\*.bntx.zs; the
// renderer from the texture's GPU address (vk_texture.cpp). A pack file is <16 hex digits of the key>.png beside the others in
// the pack's folder (triforce_texpack\ in the game folder), twice the texture's width and height (the AI upscale), the
// texture's colour as RGBA.
//
// Only what can be swapped safely is asked for: two-dimensional, one layer, sampled and never drawn into, at least kMinSide
// each way (smaller ones gain nothing), and the colour (albedo) textures alone: the pack's tool takes *_Alb textures only.
#pragma once

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <initializer_list>

namespace mkwvk::tex_pack {

constexpr uint32_t kHashBytes = 16384;
constexpr uint32_t kMinSide = 256;
constexpr uint32_t kScale = 2;   // (the pack's textures: twice each way)

inline uint64_t key(const uint8_t* level0, size_t bytes, uint32_t width, uint32_t height) {
    uint64_t h = 1469598103934665603ull;
    const size_t n = bytes < kHashBytes ? bytes : kHashBytes;
    for (size_t i = 0; i < n; i++) h = (h ^ level0[i]) * 1099511628211ull;
    for (uint32_t v : {width, height})
        for (int k = 0; k < 4; k++) h = (h ^ ((v >> (8 * k)) & 0xffu)) * 1099511628211ull;
    return h;
}
/// The pack file's name for a key: 16 lower-case hex digits and ".png"
inline void file_name(uint64_t k, char out[21]) { std::snprintf(out, 21, "%016llx.png", (unsigned long long)k); }
/// Whether a texture of this shape is one the pack can stand in for
inline bool wanted(bool two_d, uint32_t layers, bool sampled_only, uint32_t width, uint32_t height) {
    return two_d && layers == 1 && sampled_only && width >= kMinSide && height >= kMinSide;
}

}  // namespace mkwvk::tex_pack
