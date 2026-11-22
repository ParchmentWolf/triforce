// (Triforce, the Intel logs of 11-21) Which compute programs have their driver's pipeline built by the shader preparation's
// translation pass (vk_draw.cpp prepare_run, warm_compute), apart from Vulkan so that tests/test_warm_computes.py can run it.
//
// The pass translates every compute program of the seed with its texture variants (up to 64 each) and has the driver compile
// each variant once, for the driver's cache and ours: 9681-9918 compute pipelines. Play dispatches about a tenth of them:
// the precompile after the pass builds only the programs play dispatched (triforce_computes.bin, the player's own list, 166
// keys and 920 pipelines on an Arc A750; 847-1063 pipelines in the lab's RTX 4070 SUPER runs). On NVIDIA the whole pass is
// 170 s. On the Arc A750 of the 0.6.0 ticket (12 threads) it was 5858 s, 5175 s of it before the first graphics program,
// in the compute programs alone (about 6.4 s of a worker for each compute pipeline): nearly an hour and a half of the four
// hours that preparation took, for pipelines play never asks for.
//
// So on Intel's GPUs the pass builds the pipelines of the listed programs only, once there is a list; the others are still
// translated and kept in the program cache, and one that play does dispatch later is compiled then on a worker (one at a
// time on Intel, RX_VK_COMPUTE_SERIAL), its dispatch left out until it is ready, as for any compute pipeline the caches miss.
// With no list yet (a first start: nothing has been played) every one is built, as before. Other GPUs as before.
// RX_VK_WARM_COMPUTES=listed or all chooses on any GPU. No stamp holds it: the programs are translated as before, and the
// pipeline cache only gains fewer entries.
#pragma once

#include <cstdint>
#include <cstring>

namespace warm_computes {

inline constexpr uint32_t kIntel = 0x8086;

/// Whether only the listed compute programs are built. asked: RX_VK_WARM_COMPUTES ("listed" or "all"; null when it is not
/// set, anything else as not set); vendor: the GPU's vendor ID
inline bool listed_only(const char* asked, uint32_t vendor) {
    if (asked && !strcmp(asked, "listed")) return true;
    if (asked && !strcmp(asked, "all")) return false;
    return vendor == kIntel;
}

/// Whether a compute program's pipeline is built in the pass: always unless listed_only; with it, when the list is empty (no
/// play yet) or the program is in it
inline bool build(bool listed_only, bool list_empty, bool listed) { return !listed_only || list_empty || listed; }

}   // namespace warm_computes
