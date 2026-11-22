// (Triforce) The VRAM mirrors' budget by the card (vk_memory.cpp mirror_budget; RX_VK_MIRROR_MB=<MB> goes over it). Plain code with
// no Vulkan calls: tests/test_mirror_budget.py runs it on made-up cards.
//
// - A discrete card over 4.5 GB: a quarter of its video memory, at most 3 GB. On a 6 GB card (RTX 3060 Laptop, Hyrule Field,
//   whole mirrors) 512 MB of mirrors gave 17.6 fps, 1024 MB 30.7 and a quarter (1498 MB) 39.2: the pools left in system memory
//   were read over PCIe each frame. The eighth those cards had (768 MB) sat between two sizes measured as losses. Textures on
//   cards of 8.5 GB or less are 45% of the allowance and give memory back at 90% and 97% of it (vk_texture.cpp), the room a
//   quarter needs; the eighth was set for a 6 GB laptop before that rule, when a quarter and the textures went past the card.
// - 4.5 GB or less, and an integrated GPU up to 6.5 GB: an eighth (no smaller size was measured on a real small card, and an
//   integrated GPU's "video memory" is the system's).
// - Video memory not known: 3 GB.
#pragma once

#include <algorithm>
#include <cstdint>

namespace mkwvk::mirror_size {

constexpr uint64_t kMB = 1ull << 20;

constexpr uint64_t bytes(uint64_t vram, bool discrete) {
    if (!vram) return 3072 * kMB;
    if (vram <= 4608 * kMB || (!discrete && vram <= 6656 * kMB)) return vram / 8;
    return std::min<uint64_t>(vram / 4, 3072 * kMB);
}

}   // namespace mkwvk::mirror_size
