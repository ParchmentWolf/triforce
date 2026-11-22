// Which cards keep every large decoded ASTC texture as BC3, the finer blocks (UI, characters) too (vk_texture.cpp).
// tests/test_astc_bc_policy.py
#pragma once
#include <cstdint>

namespace astc_bc_policy {

// The VRAM the driver allows the process, in bytes: under 8.5 GB, every large ASTC texture as BC3 (a quarter of RGBA8).
// Issue 519 set it under 6 GB (an RTX 3050 Laptop, 3.3 GB allowed: 1.75 GB of decoded ASTC in Goron City, paged, 4 fps).
// 8 GB cards are allowed ~7-7.6 GB and fill up the same way: an RX 7700S (7.1 GB allowed) held 2.5 GB of decoded ASTC in
// Hyrule Castle Town's market with the VRAM at the limit; as BC3, 1.3 GB. 10 GB cards and up keep the finer ones as RGBA8
inline bool all_by_vram(uint64_t allowed) {
    return allowed && allowed < (8704ull << 20);
}

// (Triforce, 11-22, the performance audit's TEX-12, after Source A's) And every integrated GPU, whatever it is allowed. Its
// allowance is a share of the system's RAM (a 16 GB handheld reported 10,361 MB), so by the allowance alone it kept the
// fine-block textures of 2 to 64 MB as RGBA8, in RAM the game needs too, inside a texture budget capped at 2,560 MB.
// Source A measured the difference on a discrete card (RX_VK_ASTC_BC_ALL 0 against 1, Kokiri Forest: decoded ASTC
// 2,496-2,532 MB against 1,579-1,587, the GPU's frame the same); it was not run on an integrated GPU there either.
// The shape of tex_detail::by_vram(allowed, integrated). RX_VK_ASTC_BC_ALL=0: the finer ones as RGBA8, as before
inline bool all(uint64_t allowed, bool integrated) { return integrated || all_by_vram(allowed); }

} // namespace astc_bc_policy
