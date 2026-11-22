// (Triforce, 11-22, the performance audit's PRESENT-46, after Source A's) A first start sized to the card: the Render
// resolution row set once on a weak GPU.
//
// With no options file every card started the same: the Render resolution at Auto, the game's dynamic resolution. Source A
// reads the card and puts it in a tier; its tier 1 is an integrated GPU (a handheld's is one), a card without mesh shaders,
// or a card with 4.5 GB of video memory or less, and it draws the 3D at 50% there, or at 33% on an integrated GPU beside
// 4 processor threads or fewer (its note: an i3-1115G4's own GPU took 60 to 220 ms a frame at 50%).
//
// This is that test, for a first start only (vk_menu.cpp menu_first_start): no options file, RX_VK_LOW_SPEC not set,
// nothing saved by it, so a start after the player has saved anything is the player's own. Left out, as the audit's
// entry says: Source A's preset row, its fingerprint that chooses again on new hardware (it would overwrite the player's
// rows), its tuner in play, any change of the upscaler or of the output's size, and its test of the SteamDeck variable,
// which took desktop PCs started from that launcher for handhelds: a handheld is found by its integrated GPU alone.
//
// RX_VK_FIRST_START_AUTO: not set or 0, off (as before; the default until the owner has decided what a first start on a
// weak card gets). 1: on. A larger number: on, the card taken as having that many MB of video memory, for the lab.
//
// No Vulkan, no menu: tests/test_first_start.py compiles this.
#pragma once
#include <cstdint>
#include <cstdlib>

namespace first_start {

/// What is read of the card
struct Card {
    bool integrated = false;     // (VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU)
    bool mesh_shaders = true;    // (VK_EXT_mesh_shader, as the device was made)
    uint64_t vram_mb = 0;        // (its video memory; 0: not known)
    unsigned threads = 0;        // (the processor's threads; 0: not known)
};

constexpr uint64_t kSmallVramMb = 4608;        // 4.5 GB: tier 1 up to here
constexpr unsigned kFewThreads = 4;            // an integrated GPU beside this many threads or fewer: 33%
constexpr int kRowHalf = 4, kRowThird = 6;     // opts.resolution's 50% and 33% (upscaler_rows.h)

enum Why { kKeep = 0, kIntegrated, kNoMeshShaders, kSmallVram };
/// The Render resolution row for the card's first start: row 0, the row left as it is (not tier 1)
struct Choice {
    int row = 0;
    Why why = kKeep;
};

inline Choice choose(const Card& c) {
    if (c.integrated) return {c.threads && c.threads <= kFewThreads ? kRowThird : kRowHalf, kIntegrated};
    if (!c.mesh_shaders) return {kRowHalf, kNoMeshShaders};
    if (c.vram_mb && c.vram_mb <= kSmallVramMb) return {kRowHalf, kSmallVram};
    return {};
}

inline const char* why_text(Why w) {
    switch (w) {
    case kIntegrated: return "an integrated GPU";
    case kNoMeshShaders: return "no mesh shaders";
    case kSmallVram: return "4.5 GB of video memory or less";
    default: return "not a weak card";
    }
}

/// RX_VK_FIRST_START_AUTO (value, null when unset): -1 off; 0 on, the card's own video memory; otherwise on, the card
/// taken as having that many MB
inline int64_t switch_mb(const char* text) {
    if (!text || !*text) return -1;
    const long long v = std::atoll(text);
    return v <= 0 ? -1 : v == 1 ? 0 : (int64_t)v;
}

/// Whether the first start's choice is made at all: the switch on, no options file, RX_VK_LOW_SPEC not asked (it sets the
/// row itself), and no switch that sets the Render resolution for this run (HOS_DYNRES)
inline bool applies(bool has_options, bool low_spec, bool resolution_env, int64_t switch_value) {
    return switch_value >= 0 && !has_options && !low_spec && !resolution_env;
}

}   // namespace first_start
